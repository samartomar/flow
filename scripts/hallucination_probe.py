"""What does the model emit when there is nothing to transcribe?

Whisper is known to invent text on silence and noise (artefacts of its training data).
For a dictation tool that pastes into the user's document, an invented "Thank you." is a
serious defect, not a curiosity. Before writing a filter, measure what actually happens
and whether `no_speech_prob` is a usable signal.

    uv run python scripts/hallucination_probe.py
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import SAMPLE_RATE  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench"


def load(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr, nch = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        a = a.reshape(-1, nch).mean(axis=1)
    if sr != SAMPLE_RATE:
        n = int(len(a) * SAMPLE_RATE / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(
            np.float32
        )
    return a


def main() -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    rng = np.random.default_rng(11)

    cases: list[tuple[str, np.ndarray]] = [
        ("digital silence 3s", np.zeros(3 * SAMPLE_RATE, dtype=np.float32)),
        ("very quiet noise 3s", (rng.standard_normal(3 * SAMPLE_RATE) * 0.0003).astype(np.float32)),
        ("room-ish noise 3s", (rng.standard_normal(3 * SAMPLE_RATE) * 0.004).astype(np.float32)),
        ("louder hiss 2s", (rng.standard_normal(2 * SAMPLE_RATE) * 0.02).astype(np.float32)),
        ("clipped fragment 0.4s", load(BENCH / "long.wav")[: int(0.4 * SAMPLE_RATE)]),
        ("real speech (control)", load(BENCH / "medium.wav")),
    ]

    for label, audio in cases:
        segments, info = model.transcribe(
            audio, language="en", beam_size=1, vad_filter=False,
            condition_on_previous_text=False,
        )
        segs = list(segments)
        print(f"\n=== {label} ===")
        print(f"  segments: {len(segs)}")
        for s in segs:
            nsp = getattr(s, "no_speech_prob", None)
            avg = getattr(s, "avg_logprob", None)
            print(
                f"  no_speech_prob={nsp!s:<22} avg_logprob={avg!s:<22} text={s.text.strip()!r}"
            )
        if not segs:
            print("  (nothing emitted)")

    # Second pass: what the app actually surfaces, i.e. after flow/clean.py filtering.
    from flow.asr import WhisperTranscriber

    asr = WhisperTranscriber("base.en")
    print("\n\n=== through WhisperTranscriber (filtered) ===")
    for label, audio in cases:
        got = asr.text(audio, final=True)
        verdict = "SUPPRESSED" if not got else f"{got!r}"
        print(f"  {label:<24} -> {verdict}")


if __name__ == "__main__":
    main()
