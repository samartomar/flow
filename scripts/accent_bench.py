"""Per-accent WER benchmark (roadmap Phase 0, product target P1/P2).

Answers, with numbers, the questions the SAPI bench in asr_bench.py cannot:

  1. What is the real WER per accent group, per model?  (P1: the floor matters)
  2. How much text does Flow's filter stack silently delete from real accented
     speech?  (P2)

Flow used to run *two* filters: faster-whisper's internal segment skip
(no_speech_prob > 0.6 AND avg_logprob < -1.0) plus clean.is_invented(). The
first one deleted segments before Flow could see or log them, and it accounted
for 5 of the 9 silent deletions measured on the short-clip slice — so
flow/asr.py now passes `no_speech_threshold=None` and there is one filter,
Flow's own, which records what it drops and why.

Every clip is decoded ONCE with the internal skip disabled, then the filters
are *simulated* from the recorded per-segment signals, which lets the shipped
build and the pre-fix build be scored from the same decode:

    model WER   - every decoded segment kept: what the model heard
    app WER     - after the shipped filter: what Flow would show today
    pre-fix     - what the library's hidden skip would additionally have eaten

Decode parameters come from flow/asr.py; only no_speech_threshold is raised
during decoding, to keep rejected segments observable in the recorded signals.

Scoring note: references are conversational EdAcc transcripts (uppercase, no
punctuation, spelled-out numbers, hesitation tokens). Normalisation here is
deliberately basic — lowercase, strip punctuation, split letter/digit runs,
digits->words, drop filler tokens from both sides. Absolute WER therefore runs
high; the *deltas* — model vs model, model WER vs app WER, group vs us-control —
are the signal. Check the denominator: n and ref-words are printed per cell.

**False-reject accounting (P2).** Beyond per-segment drop counts, every clip is
scored for whether Flow would have shown the user *nothing at all*:

    model_empty   - the model itself produced no text: an ASR failure, not a filter
    false_reject  - the model produced text and the filters deleted all of it

`false_reject` is the number P2 bounds at < 1%, and it is the one that matters:
the user spoke, the words were recognised, and the app showed silence. Drops are
attributed to the exact rule that fired (`flow.clean.invented_reason`), and the
rule this one replaced (`legacy_reason`, which dropped on shortness alone) is
scored from the same signals, so every change keeps a before-and-after.

Decode parameters come from `flow.asr.decode_options(final=True)` — the app's own
final-decode settings — so a config change is measured as the app will run it.
`--beam` / `--temperature` override them to A/B a proposed change, and `--tag`
keeps the two results files apart.

Usage:  uv run python scripts/accent_bench.py [model ...] [--manifest NAME]
            [--beam N] [--temperature 0.0,0.2,0.4] [--tag SUFFIX]
        default models: base.en small.en small
        default manifest: manifest-edacc.jsonl (the >= 1.5 s WER slice)
        short-clip probe: --manifest manifest-edacc-short.jsonl
Writes: .bench/accent/results-<model><slice><tag>.json
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
from flow.asr import (  # noqa: E402
    LOG_PROB_THRESHOLD,
    NO_SPEECH_THRESHOLD,
    decode_options,
)
from flow.clean import (  # noqa: E402
    LOW_CONFIDENCE,
    NO_SPEECH_MAX,
    invented_reason,
    normalise,
)
from flow.clean import _FILLER_ONLY as FILLER_ONLY  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench" / "accent"
SR = 16000

# faster-whisper's own defaults, which flow/asr.py used to inherit. Kept as named
# constants because they are the counterfactual every P2 number is compared against:
# pass them to apply_filters() to measure the build as it was before the library's
# invisible second filter was turned off.
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


def legacy_reason(text: str, ns: float | None, lp: float | None) -> str | None:
    """`clean.invented_reason` as it stood before 2026-07-31.

    Kept here, in the bench rather than the app, so the thin-rule change keeps a
    denominator: every P2 number can be quoted against the build it replaced. It
    dropped on shortness alone, which is what defect 3 was about.
    """
    stripped = normalise(text).strip().strip(".!?,").lower()
    if not stripped:
        return "empty"
    if ns is None:
        return "filler" if stripped in FILLER_ONLY else None
    if ns <= NO_SPEECH_MAX:
        return None
    thin = len(stripped.split()) <= 3
    unconfident = lp is not None and lp < LOW_CONFIDENCE
    if thin and unconfident:
        return "thin+unconfident"
    if thin:
        return "thin"
    if unconfident:
        return "unconfident"
    return None


def apply_filters(
    segs: list[dict],
    no_speech_threshold: float | None = NO_SPEECH_THRESHOLD,
    log_prob_threshold: float | None = LOG_PROB_THRESHOLD,
) -> dict:
    """Run the production filters over recorded per-segment signals.

    Pure, so the accounting that produces the P2 number can be tested without a
    model. `segs` are dicts of {text, ns, lp}; each dropped segment is annotated
    in place with the rule that dropped it, which is what the results JSON carries.

    The thresholds default to the app's own (`flow.asr`), where `None` means the
    library's invisible skip is off. Pass `LIB_NO_SPEECH` / `LIB_LOG_PROB` to measure
    the pre-fix build instead.

    Returns the surviving text under the shipped rule (`app_text`) and under the
    rule it replaced (`legacy_text`), plus drop counts by rule.
    """
    survivors, legacy, lib_skipped, clean_dropped = [], [], 0, 0
    reasons: dict[str, int] = {}
    skips = no_speech_threshold is not None and log_prob_threshold is not None
    for s in segs:
        if skips and s["ns"] > no_speech_threshold and s["lp"] < log_prob_threshold:
            lib_skipped += 1
            s["drop"] = "lib-skip"
            continue
        reason = invented_reason(s["text"], s["ns"], s["lp"])
        # Score the rule this one replaced from the same signals, so the change has
        # a before-and-after rather than just an after.
        if legacy_reason(s["text"], s["ns"], s["lp"]) is None:
            legacy.append(s["text"].strip())
        if reason is not None:
            clean_dropped += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            s["drop"] = reason
            continue
        survivors.append(s["text"].strip())
    return {
        "app_text": normalise(" ".join(survivors)),
        "legacy_text": normalise(" ".join(legacy)),
        "lib_skipped": lib_skipped,
        "clean_dropped": clean_dropped,
        "reasons": reasons,
    }


def load_manifest(pattern: str = "manifest-edacc.jsonl") -> list[dict]:
    """Load one slice. Slices are separate files on purpose — the short-clip probe
    must not contaminate the WER benchmark's denominator, and vice versa."""
    entries = []
    for mf in sorted(BENCH.glob(pattern)):
        with mf.open(encoding="utf-8") as f:
            entries.extend(json.loads(line) for line in f if line.strip())
    if not entries:
        raise SystemExit(
            f"no manifest matching {pattern!r} under {BENCH} — "
            "run scripts/fetch_accent_data.py first"
        )
    return entries


def bench_model(
    name: str, entries: list[dict], slice_tag: str = "", overrides: dict | None = None
) -> dict:
    from faster_whisper import WhisperModel

    # The app's own final-decode parameters, so a config change is measured as the app
    # will run it. Overrides exist to A/B a proposed change against the shipped one.
    opts = decode_options(final=True)
    opts.update(overrides or {})
    # Decoding always keeps rejected segments observable, whatever the app ships:
    # the filters are re-applied below from the recorded per-segment signals.
    decode_opts = {**opts, "no_speech_threshold": 2.0}

    t0 = time.perf_counter()
    model = WhisperModel(name, device="cpu", compute_type="int8")
    print(f"\nMODEL={name}  load+fetch={time.perf_counter() - t0:.2f}s  "
          f"beam={opts['beam_size']}  temperature={opts['temperature']}")

    groups: dict[str, dict] = {}
    clips = []
    for i, e in enumerate(entries):
        audio = load_wav(BENCH / e["wav"])
        t = time.perf_counter()
        segments, _ = model.transcribe(audio, **decode_opts)
        segs = [
            {"text": s.text, "ns": float(s.no_speech_prob), "lp": float(s.avg_logprob)}
            for s in segments
        ]
        decode = time.perf_counter() - t

        model_text = normalise(" ".join(s["text"].strip() for s in segs))
        # The pre-fix build, scored from the same decode: a copy, because
        # apply_filters annotates each segment with the rule that dropped it.
        pre_fix = apply_filters(
            [dict(s) for s in segs], LIB_NO_SPEECH, LIB_LOG_PROB
        )
        f = apply_filters(segs)
        app_text, legacy_text = f["app_text"], f["legacy_text"]
        lib_skipped, clean_dropped, reasons = (
            f["lib_skipped"], f["clean_dropped"], f["reasons"]
        )

        em, nr = wer_counts(e["ref"], model_text)
        ea, _ = wer_counts(e["ref"], app_text)
        model_empty = not model_text
        app_empty = not app_text
        g = groups.setdefault(e["group"], {
            "n": 0, "ref_words": 0, "model_edits": 0, "app_edits": 0,
            "segments": 0, "lib_skipped": 0, "clean_dropped": 0,
            "model_empty": 0, "app_empty": 0, "false_reject": 0,
            "false_reject_legacy": 0, "false_reject_pre_fix": 0,
            "pre_fix_lib_skipped": 0, "reasons": {},
            "audio_s": 0.0, "decode_s": 0.0,
        })
        g["n"] += 1
        g["ref_words"] += nr
        g["model_edits"] += em
        g["app_edits"] += ea
        g["segments"] += len(segs)
        g["lib_skipped"] += lib_skipped
        g["clean_dropped"] += clean_dropped
        g["model_empty"] += int(model_empty)
        g["app_empty"] += int(app_empty)
        g["false_reject"] += int(app_empty and not model_empty)
        g["false_reject_legacy"] += int(not legacy_text and not model_empty)
        g["false_reject_pre_fix"] += int(not pre_fix["app_text"] and not model_empty)
        g["pre_fix_lib_skipped"] += pre_fix["lib_skipped"]
        for reason, count in reasons.items():
            g["reasons"][reason] = g["reasons"].get(reason, 0) + count
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

    # P2: what fraction of clips the user would have seen nothing for.
    print(f"\n{'group':<12}{'n':>4}{'mdl-empty':>11}{'pre-fix':>9}{'rate':>8}"
          f"{'false-rej':>11}{'rate':>8}{'legacy':>10}{'rate':>8}")
    tot = {"n": 0, "model_empty": 0, "false_reject": 0, "false_reject_legacy": 0,
           "false_reject_pre_fix": 0, "pre_fix_lib_skipped": 0}
    for slug in sorted(groups):
        g = groups[slug]
        for k in tot:
            tot[k] += g[k]
        print(f"{slug:<12}{g['n']:>4}{g['model_empty']:>11}"
              f"{g['false_reject_pre_fix']:>9}{g['false_reject_pre_fix'] / g['n']:>8.1%}"
              f"{g['false_reject']:>11}{g['false_reject'] / g['n']:>8.1%}"
              f"{g['false_reject_legacy']:>10}"
              f"{g['false_reject_legacy'] / g['n']:>8.1%}")
    print(f"{'ALL':<12}{tot['n']:>4}{tot['model_empty']:>11}"
          f"{tot['false_reject_pre_fix']:>9}{tot['false_reject_pre_fix'] / tot['n']:>8.1%}"
          f"{tot['false_reject']:>11}{tot['false_reject'] / tot['n']:>8.1%}"
          f"{tot['false_reject_legacy']:>10}"
          f"{tot['false_reject_legacy'] / tot['n']:>8.1%}"
          f"   (P2 target: < 1%)")
    print(f"segments the library used to eat before Flow saw them: "
          f"{tot['pre_fix_lib_skipped']}")

    all_reasons: dict[str, int] = {}
    for g in groups.values():
        for reason, count in g["reasons"].items():
            all_reasons[reason] = all_reasons.get(reason, 0) + count
    total_segs = sum(g["segments"] for g in groups.values())
    lib = sum(g["lib_skipped"] for g in groups.values())
    detail = ", ".join(f"{r}={c}" for r, c in sorted(all_reasons.items())) or "none"
    print(f"\nsegment drops over {total_segs} segments: lib-skip={lib}, {detail}")

    out = BENCH / f"results-{name.replace('/', '_')}{slice_tag}.json"
    out.write_text(
        json.dumps({"model": name, "groups": groups, "clips": clips}, indent=1),
        encoding="utf-8",
    )
    print(f"detail -> {out}")
    return groups


def main() -> None:
    argv = sys.argv[1:]

    def take(flag: str, default=None):
        if flag in argv:
            i = argv.index(flag)
            value = argv[i + 1]
            del argv[i:i + 2]
            return value
        return default

    pattern = take("--manifest", "manifest-edacc.jsonl")
    overrides: dict = {}
    if (beam := take("--beam")) is not None:
        overrides["beam_size"] = int(beam)
    if (temps := take("--temperature")) is not None:
        overrides["temperature"] = tuple(float(t) for t in temps.split(","))
    if (lp := take("--log-prob")) is not None:
        overrides["log_prob_threshold"] = float(lp)
    tag = take("--tag", "")
    models = argv or ["base.en", "small.en", "small"]

    entries = load_manifest(pattern)
    # Distinct results files per slice, so the short-clip probe cannot quietly
    # overwrite the WER benchmark it is not comparable to.
    stem = pattern.removeprefix("manifest-edacc").removesuffix(".jsonl")
    n_groups = len({e["group"] for e in entries})
    durations = sorted(e["duration"] for e in entries)
    print(f"{len(entries)} clips ({pattern}), {n_groups} groups, "
          f"{sum(durations) / 60:.1f} min audio, "
          f"duration {durations[0]:.2f}-{durations[-1]:.2f}s "
          f"(median {durations[len(durations) // 2]:.2f}s)")
    print("columns: model=model WER  app=after Flow's two filters  "
          "lib-/cln-=segments dropped by each filter")

    for name in models:
        bench_model(name, entries, slice_tag=stem + tag, overrides=overrides)


if __name__ == "__main__":
    main()
