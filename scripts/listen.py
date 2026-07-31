"""Headless proof of stage 3 (R4): live partials while speaking, held draft on stop.

Two sources, one code path:

  uv run python scripts/listen.py                 # real microphone
  uv run python scripts/listen.py --wav .bench/long.wav

The --wav mode exists so the gate/partial/commit logic can be exercised without a
person at a mic; it feeds identical blocks through identical logic, padded with
silence so the end-of-speech edge actually fires.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import MAX_UTTERANCE_SEC, SAMPLE_RATE  # noqa: E402
from flow.asr import WhisperTranscriber  # noqa: E402
from flow.audio import BLOCK, Mic, SpeechGate  # noqa: E402

PARTIAL_EVERY = 0.9  # s — matched to the measured ~0.8 s decode floor; asking for
# partials faster than the decoder can produce them just builds a backlog


def wav_blocks(path: Path, realtime: bool = True):
    """Yield BLOCK-sized mono 16 kHz blocks, then ~1.5 s of silence.

    Paced to real time by default. Draining a file as fast as the disk allows means
    ten seconds of audio arrive in under a second, the partial timer never elapses,
    and the live-partial path silently goes untested — which is exactly what happened
    on the first run of this script.
    """
    with wave.open(str(path), "rb") as w:
        sr, nch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SystemExit("expected 16-bit PCM")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        a = a.reshape(-1, nch).mean(axis=1)
    if sr != SAMPLE_RATE:
        n = int(len(a) * SAMPLE_RATE / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(
            np.float32
        )
    a = np.concatenate([a, np.zeros(int(1.5 * SAMPLE_RATE), dtype=np.float32)])
    block_sec = BLOCK / SAMPLE_RATE
    clock = time.perf_counter()
    for i in range(0, len(a) - BLOCK, BLOCK):
        if realtime:
            clock += block_sec
            # Never sleep negative: if a decode overran, catch up rather than drift.
            behind = clock - time.perf_counter()
            if behind > 0:
                time.sleep(behind)
        yield a[i : i + BLOCK]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", type=Path)
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--model", default="base.en")
    args = ap.parse_args()

    asr = WhisperTranscriber(args.model)
    t0 = time.perf_counter()
    asr.load()
    print(f"[model ready in {time.perf_counter() - t0:.2f}s]", file=sys.stderr)

    gate = SpeechGate()
    utter: list[np.ndarray] = []
    committed: list[str] = []
    last_partial = 0.0
    decodes = 0
    decode_time = 0.0

    def flush(reason: str) -> None:
        """Finalise the current utterance into the committed draft."""
        nonlocal utter, decodes, decode_time
        if not utter:
            return
        audio = np.concatenate(utter)
        t = time.perf_counter()
        text = asr.text(audio, final=True)
        decode_time += time.perf_counter() - t
        decodes += 1
        utter = []
        if text:
            committed.append(text)
            print(f"\r\033[K[{reason}] {text}")

    def blocks():
        if args.wav:
            yield from wav_blocks(args.wav)
        else:
            print("[listening — speak, then pause. ctrl-c to stop]", file=sys.stderr)
            with Mic(device=args.device) as mic:
                while True:
                    got = mic.drain()
                    if not got:
                        time.sleep(0.02)
                        continue
                    yield from got

    try:
        for block in blocks():
            started, stopped = gate.push(block)
            if started and not utter:
                last_partial = time.perf_counter()
            if gate.speaking:
                utter.append(block)
                secs = len(utter) * BLOCK / SAMPLE_RATE

                # R8 / risk 7: never let one utterance cross Whisper's 30 s window.
                if secs >= MAX_UTTERANCE_SEC:
                    flush("cut")
                    continue

                now = time.perf_counter()
                if now - last_partial >= PARTIAL_EVERY:
                    last_partial = now
                    t = time.perf_counter()
                    partial = asr.text(np.concatenate(utter))
                    dt = time.perf_counter() - t
                    decode_time += dt
                    decodes += 1
                    print(f"\r\033[K  …{partial[-90:]}  ({dt:.2f}s)", end="", flush=True)
            elif stopped:
                flush("draft")
    except KeyboardInterrupt:
        pass

    flush("draft")
    draft = " ".join(committed)
    print("\n" + "=" * 60)
    print("DRAFT (held — not sent, per R5):")
    print(draft or "(nothing captured)")
    if decodes:
        print(
            f"\n[{decodes} decodes, mean {decode_time / decodes:.2f}s, "
            f"noise floor {gate.floor_db:.1f} dB]"
        )


if __name__ == "__main__":
    main()
