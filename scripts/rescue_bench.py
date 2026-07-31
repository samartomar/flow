"""Does a biased second decode recover a command the first decode got wrong?

The router escalates to a ~7 s CLI call when a correction's target is nowhere in the
draft. Usually that means the model mis-heard a word, not that the user wanted
judgement — so Flow re-decodes the same audio biased toward the trigger verbs and the
draft's own words (`edits.command_bias`). This measures whether that works.

Method: synthesise the command inventory with Windows SAPI (two voices), bury it in
white noise at falling SNR until the decoder starts failing, and at each level ask two
questions — did the first read route to a local edit, and if not, did the biased
re-read rescue it?

**What this is not.** SAPI is a US-English synthesiser, so this measures the
*mechanism* — can biasing recover a command the model got wrong — and not the
population. Accented recordings remain the missing benchmark. Noise is a stand-in for
"the decoder is unsure", which is the condition biasing acts on, but it is a stand-in.

Usage:  uv run python scripts/rescue_bench.py [model] [--snr 15,10,5,0]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from asr_bench import load_wav, median, to_16k  # noqa: E402
from flow.asr import decode_options  # noqa: E402
from flow.clean import normalise  # noqa: E402
from flow.edits import command_bias, plan  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench" / "commands"
SR = 16000

DRAFT = "Meeting on Tuesday with Sameer about the release notes."
COMMANDS = [
    ("change Tuesday to Wednesday", "replace"),
    ("replace Sameer with Samir", "replace"),
    ("swap Tuesday for Friday", "replace"),
    ("delete Tuesday", "delete"),
    ("remove the release notes", "delete"),
    ("delete the last two words", "delete_last"),
    ("replace all Tuesday with Friday", "replace_all"),
    ("insert urgent before release", "insert_before"),
    ("add today after notes", "insert_after"),
    ("capitalize Sameer", "capitalize"),
    ("uppercase release", "upper"),
    ("lowercase Sameer", "lower"),
]
VOICES = ("Microsoft David Desktop", "Microsoft Zira Desktop")


def synthesise() -> list[tuple[Path, str, str]]:
    """One WAV per (command, voice), via PowerShell. Cached on disk."""
    BENCH.mkdir(parents=True, exist_ok=True)
    out = []
    for vi, voice in enumerate(VOICES):
        for ci, (text, op) in enumerate(COMMANDS):
            path = BENCH / f"v{vi}_{ci:02d}.wav"
            if not path.exists():
                script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.SelectVoice('{voice}'); "
                    f"$s.SetOutputToWaveFile('{path}'); "
                    f"$s.Speak('{text}'); $s.Dispose()"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", script],
                               check=True, capture_output=True)
            out.append((path, text, op))
    return out


def add_noise(audio: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """White noise at a given SNR. Deterministic per clip, so runs are comparable."""
    if snr_db is None:
        return audio
    rng = np.random.default_rng(seed)
    speech_power = float(np.mean(audio**2)) + 1e-12
    noise = rng.normal(0.0, 1.0, len(audio)).astype(np.float32)
    noise *= np.sqrt(speech_power / (10 ** (snr_db / 10.0)) / (np.mean(noise**2) + 1e-12))
    return np.clip(audio + noise, -1.0, 1.0).astype(np.float32)


def main() -> None:
    from faster_whisper import WhisperModel

    argv = sys.argv[1:]
    snrs: list[float | None] = [None, 15.0, 10.0, 5.0, 0.0]
    if "--snr" in argv:
        i = argv.index("--snr")
        snrs = [None] + [float(x) for x in argv[i + 1].split(",")]
        del argv[i:i + 2]
    name = argv[0] if argv else "small.en"

    clips = synthesise()
    model = WhisperModel(name, device="cpu", compute_type="int8")
    bias = command_bias(DRAFT)
    print(f"{len(clips)} clips ({len(COMMANDS)} commands x {len(VOICES)} voices), "
          f"MODEL={name}")
    print(f"bias: {len(bias.split())} terms\n")

    def decode(audio, hotwords=""):
        t = time.perf_counter()
        segments, _ = model.transcribe(audio, **decode_options(True, hotwords or None))
        text = normalise(" ".join(s.text.strip() for s in segments))
        return text, time.perf_counter() - t

    print(f"{'SNR':>6}{'first read':>12}{'appended':>10}{'escalated':>11}"
          f"{'after re-read':>15}{'re-read s':>11}")
    rows = {}
    for snr in snrs:
        first_ok = rescued_ok = appended = escalated = 0
        rescue_times = []
        for i, (path, _text, op) in enumerate(clips):
            audio = add_noise(to_16k(*load_wav(path)), snr, seed=i)
            heard, _ = decode(audio)
            p = plan(heard, DRAFT)
            if p.kind == "local" and p.op == op:
                first_ok += 1
                rescued_ok += 1
                continue
            # How the misroute presents matters: an escalated plan gets the automatic
            # re-decode, while an append is silent and needs the user to say "that was
            # a command". Both end in the same biased re-read.
            if p.kind == "append":
                appended += 1
            elif p.escalated:
                escalated += 1
            heard2, dt = decode(audio, bias)
            rescue_times.append(dt)
            p2 = plan(heard2, DRAFT)
            rescued_ok += int(p2.kind == "local" and p2.op == op)
        n = len(clips)
        label = "clean" if snr is None else f"{snr:.0f} dB"
        print(f"{label:>6}{f'{first_ok}/{n}':>12}{appended:>10}{escalated:>11}"
              f"{f'{rescued_ok}/{n}':>15}"
              f"{median(rescue_times) if rescue_times else 0:>11.2f}")
        rows[label] = {"n": n, "first": first_ok, "rescued": rescued_ok,
                       "appended": appended, "escalated": escalated,
                       "rescue_s": median(rescue_times) if rescue_times else None}

    out = BENCH / f"rescue-{name}.json"
    out.write_text(json.dumps({"model": name, "rows": rows}, indent=1), encoding="utf-8")
    print(f"\ndetail -> {out}")


if __name__ == "__main__":
    main()
