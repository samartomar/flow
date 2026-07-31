"""ASR spike benchmark (stage 2b).

Answers two questions with numbers instead of estimates:
  1. R4  - can a growing audio prefix be decoded fast enough to show live partials?
  2. R2/R3 - is base.en accurate enough, or is small.en required?

Deliberately uses only stdlib `wave` + numpy to read audio, mirroring the real
runtime path (numpy frames straight off sounddevice). If this script never touches
`av`, then `av` is dead weight in the dependency tree and that is worth knowing.

Usage:  uv run python scripts/asr_bench.py [model]
"""

import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent.parent / ".bench"
SR = 16000


def load_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        sr, nframes, nch, width = (
            w.getframerate(),
            w.getnframes(),
            w.getnchannels(),
            w.getsampwidth(),
        )
        raw = w.readframes(nframes)
    if width != 2:
        raise SystemExit(f"{path.name}: expected 16-bit PCM, got {width * 8}-bit")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        a = a.reshape(-1, nch).mean(axis=1)
    return a, sr


def to_16k(a: np.ndarray, sr: int) -> np.ndarray:
    """Linear resample. Good enough for a benchmark; the real path will ask
    sounddevice for 16 kHz directly and skip this entirely."""
    if sr == SR:
        return a
    n_out = int(len(a) * SR / sr)
    return np.interp(
        np.linspace(0, len(a) - 1, n_out), np.arange(len(a)), a
    ).astype(np.float32)


def words(s: str):
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(
                d[i - 1, j] + 1,
                d[i, j - 1] + 1,
                d[i - 1, j - 1] + (r[i - 1] != h[j - 1]),
            )
    return float(d[len(r), len(h)]) / max(1, len(r))


def main() -> None:
    from faster_whisper import WhisperModel

    name = sys.argv[1] if len(sys.argv) > 1 else "base.en"

    t0 = time.perf_counter()
    model = WhisperModel(name, device="cpu", compute_type="int8")
    print(f"MODEL={name}  load+fetch={time.perf_counter() - t0:.2f}s")

    def run(audio, label):
        t = time.perf_counter()
        segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
        text = " ".join(s.text for s in segs).strip()
        dt = time.perf_counter() - t
        dur = len(audio) / SR
        print(f"{label:12s} audio={dur:5.2f}s  decode={dt:5.2f}s  rtf={dt / dur:4.2f}")
        return text, dt

    print("\n--- accuracy (SAPI-synthesised speech: OPTIMISTIC vs real mic) ---")
    for kind in ("short", "medium", "long"):
        wav = BENCH / f"{kind}.wav"
        if not wav.exists():
            print(f"{kind}: missing, skipped")
            continue
        audio = to_16k(*load_wav(wav))
        ref = (BENCH / f"{kind}.txt").read_text(encoding="utf-8").strip()
        text, _ = run(audio, kind)
        print(f"             WER={wer(ref, text):.3f}  {text!r}")

    print("\n--- R4 gate: growing prefix must decode in well under 1.5s ---")
    audio = to_16k(*load_wav(BENCH / "long.wav"))
    for secs in (1, 2, 3, 5, 8, 12):
        n = int(secs * SR)
        if n > len(audio):
            break
        run(audio[:n], f"prefix_{secs}s")


if __name__ == "__main__":
    main()
