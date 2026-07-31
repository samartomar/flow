"""Per-accent WER benchmark (roadmap Phase 0, product target P1/P2).

Answers, with numbers, the questions the SAPI bench in asr_bench.py cannot:

  1. What is the real WER per accent group, per model?  (P1: the floor matters)
  2. How much text does Flow's filter stack silently delete from real accented
     speech?  Two filters run in production: faster-whisper's internal segment
     skip (no_speech_prob > 0.6 AND avg_logprob < -1.0 — library defaults that
     flow/asr.py does not override) and clean.is_invented().  (P2)

So every clip is decoded ONCE with the internal skip disabled, then both filters
are *simulated* from the recorded per-segment signals:

    model WER   - every decoded segment kept: what the model heard
    app WER     - after internal-skip + clean.is_invented(): what Flow would show

The gap between the two columns is pure filter damage on known-real speech.

Decode parameters mirror flow/asr.py finals (language=en, beam_size=2,
vad_filter=False, condition_on_previous_text=False); only no_speech_threshold
is raised to keep rejected segments observable.

Scoring note: references are conversational EdAcc transcripts (uppercase, no
punctuation, spelled-out numbers, hesitation tokens). Normalisation here is
deliberately basic — lowercase, strip punctuation, split letter/digit runs,
digits->words, drop filler tokens from both sides. Absolute WER therefore runs
high; the *deltas* — model vs model, model WER vs app WER, group vs us-control —
are the signal. Check the denominator: n and ref-words are printed per cell.

Usage:  uv run python scripts/accent_bench.py [model ...]
        default models: base.en small.en small
Writes: .bench/accent/results-<model>.json
"""

from __future__ import annotations

import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flow.clean import is_invented, normalise  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench" / "accent"
SR = 16000

# The production defaults flow/asr.py inherits from faster-whisper — simulated
# here so the bench reports what the library silently does in the real app.
LIB_NO_SPEECH = 0.6
LIB_LOG_PROB = -1.0

_FILLERS = {"uh", "um", "erm", "mm", "mhm", "hmm", "ah", "eh", "huh", "mmm"}

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def _num_words(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        out = [_ONES[n // 100], "hundred"]
        return out + (_num_words(n % 100) if n % 100 else [])
    if n < 1_000_000:
        out = _num_words(n // 1000) + ["thousand"]
        return out + (_num_words(n % 1000) if n % 1000 else [])
    return list(str(n))  # beyond scope; per-digit is stable on both sides


def norm_words(s: str) -> list[str]:
    """Shared ref/hyp normalisation. Basic on purpose — see module docstring."""
    # EdAcc annotation tags (<LIPSMACK>, <OVERLAP>, <LAUGH>...) are events, not
    # words; scoring them as words charges the model for silence it never heard.
    s = re.sub(r"<[A-Z_' -]+>", " ", s)
    s = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", s)
    s = re.sub(r"[^a-z0-9' ]", " ", s.lower())
    out: list[str] = []
    for tok in s.split():
        tok = tok.strip("'")
        if not tok or tok in _FILLERS:
            continue
        if tok.isdigit() and len(tok) <= 7:
            out.extend(_num_words(int(tok)))
        else:
            out.append(tok)
    return out


def wer_counts(ref: str, hyp: str) -> tuple[int, int]:
    """(edit_distance, ref_len) so corpus WER can be pooled across clips."""
    r, h = norm_words(ref), norm_words(hyp)
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
    return int(d[len(r), len(h)]), max(1, len(r))


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def load_manifest() -> list[dict]:
    entries = []
    for mf in sorted(BENCH.glob("manifest-*.jsonl")):
        with mf.open(encoding="utf-8") as f:
            entries.extend(json.loads(line) for line in f if line.strip())
    if not entries:
        raise SystemExit(
            f"no manifest under {BENCH} — run scripts/fetch_accent_data.py first"
        )
    return entries


def bench_model(name: str, entries: list[dict]) -> dict:
    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(name, device="cpu", compute_type="int8")
    print(f"\nMODEL={name}  load+fetch={time.perf_counter() - t0:.2f}s")

    groups: dict[str, dict] = {}
    clips = []
    for i, e in enumerate(entries):
        audio = load_wav(BENCH / e["wav"])
        t = time.perf_counter()
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=2,
            vad_filter=False,
            condition_on_previous_text=False,
            # Disable ONLY the internal skip so rejected segments stay
            # observable; it is re-applied below from the recorded signals.
            no_speech_threshold=2.0,
        )
        segs = [
            {"text": s.text, "ns": float(s.no_speech_prob), "lp": float(s.avg_logprob)}
            for s in segments
        ]
        decode = time.perf_counter() - t

        model_text = normalise(" ".join(s["text"].strip() for s in segs))
        survivors, lib_skipped, clean_dropped = [], 0, 0
        for s in segs:
            if s["ns"] > LIB_NO_SPEECH and s["lp"] < LIB_LOG_PROB:
                lib_skipped += 1
                continue
            if is_invented(s["text"], s["ns"], s["lp"]):
                clean_dropped += 1
                continue
            survivors.append(s["text"].strip())
        app_text = normalise(" ".join(survivors))

        em, nr = wer_counts(e["ref"], model_text)
        ea, _ = wer_counts(e["ref"], app_text)
        g = groups.setdefault(e["group"], {
            "n": 0, "ref_words": 0, "model_edits": 0, "app_edits": 0,
            "segments": 0, "lib_skipped": 0, "clean_dropped": 0,
            "audio_s": 0.0, "decode_s": 0.0,
        })
        g["n"] += 1
        g["ref_words"] += nr
        g["model_edits"] += em
        g["app_edits"] += ea
        g["segments"] += len(segs)
        g["lib_skipped"] += lib_skipped
        g["clean_dropped"] += clean_dropped
        g["audio_s"] += e["duration"]
        g["decode_s"] += decode
        clips.append({**e, "model_text": model_text, "app_text": app_text,
                      "segs": segs, "decode_s": round(decode, 3)})
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(entries)} clips...")

    print(f"\n{'group':<12}{'n':>4}{'refw':>6}{'model':>8}{'app':>8}"
          f"{'segs':>6}{'lib-':>6}{'cln-':>6}{'rtf':>6}")
    for slug in sorted(groups):
        g = groups[slug]
        print(f"{slug:<12}{g['n']:>4}{g['ref_words']:>6}"
              f"{g['model_edits'] / g['ref_words']:>8.3f}"
              f"{g['app_edits'] / g['ref_words']:>8.3f}"
              f"{g['segments']:>6}{g['lib_skipped']:>6}{g['clean_dropped']:>6}"
              f"{g['decode_s'] / g['audio_s']:>6.2f}")

    out = BENCH / f"results-{name.replace('/', '_')}.json"
    out.write_text(
        json.dumps({"model": name, "groups": groups, "clips": clips}, indent=1),
        encoding="utf-8",
    )
    print(f"detail -> {out}")
    return groups


def main() -> None:
    models = sys.argv[1:] or ["base.en", "small.en", "small"]
    entries = load_manifest()
    n_groups = len({e["group"] for e in entries})
    print(f"{len(entries)} clips, {n_groups} groups, "
          f"{sum(e['duration'] for e in entries) / 60:.1f} min audio")
    print("columns: model=model WER  app=after Flow's two filters  "
          "lib-/cln-=segments dropped by each filter")

    for name in models:
        bench_model(name, entries)


if __name__ == "__main__":
    main()
