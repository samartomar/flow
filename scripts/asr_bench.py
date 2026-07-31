"""ASR spike benchmark (stage 2b) and the R4 partial-latency gate.

Answers two questions with numbers instead of estimates:
  1. R4  - can a growing audio prefix be decoded fast enough to show live partials?
  2. R2/R3 - is base.en accurate enough, or is small.en required?

Deliberately uses only stdlib `wave` + numpy to read audio, mirroring the real
runtime path (numpy frames straight off sounddevice). If this script never touches
`av`, then `av` is dead weight in the dependency tree and that is worth knowing.

**What the R4 gate actually measures.** In [flow/session.py](../flow/session.py) a
partial is submitted only when the decode worker is free and the utterance has grown
by `PARTIAL_MIN_GROWTH_SEC`, and it always decodes the *whole utterance so far*. So
the staleness of what the user reads is one decode of the current prefix: the gate is
`decode(prefix) < 1.5 s`, evaluated on the worst case, not the average — a user does
not experience a median. Prefixes run to 20 s because
[MAX_UTTERANCE_SEC](../flow/__init__.py) cuts an utterance at 24 s.

Sources are real accented speech (the longest EdAcc clip in each L1 group under
`.bench/accent/`, if `scripts/fetch_accent_data.py` has been run) plus the SAPI
`long.wav`, so the number is measured on the population the roadmap targets rather
than on synthesised US English. Decode parameters are imported from
`flow.asr.decode_options` rather than restated here — a bench that drifts from the app
measures a build nobody runs.

Usage:  uv run python scripts/asr_bench.py [model ...]
            [--prefix-only] [--finals] [--repeats=N]
        default model: base.en
"""

import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flow.asr import decode_options  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench"
ACCENT = BENCH / "accent"
SR = 16000

#: R4: a partial the user is watching may lag speech by at most this much.
PARTIAL_BUDGET_SEC = 1.5

#: Prefix durations to probe, in seconds. The tail matters most: Whisper pads every
#: input to one 30 s mel window, so if cost were flat these would all be equal — the
#: measured curve is what says whether that holds at this model tier.
PREFIX_LENGTHS = (1, 2, 3, 5, 8, 12, 16, 20)


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


# -- R4 gate ---------------------------------------------------------------


def median(xs) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def summarise_gate(
    rows: list[tuple[int, float]], budget: float = PARTIAL_BUDGET_SEC
) -> dict:
    """Fold (prefix_seconds, decode_seconds) samples into a verdict.

    A prefix length passes on its **worst** observed decode, not its median: the gate
    exists to bound what the user feels, and they feel the slow one. `longest_pass` is
    the longest prefix reachable without any shorter length already having failed —
    a length that passes above a failing one is not a usable operating point.

    Each input sample should already be one *source's* median across repeats (see
    `prefix_gate`), so "worst case" here means the worst voice, not the unluckiest
    moment on a shared dev CPU.
    """
    by_len: dict[int, list[float]] = {}
    for secs, elapsed in rows:
        by_len.setdefault(secs, []).append(elapsed)

    per_length = []
    for secs in sorted(by_len):
        times = by_len[secs]
        per_length.append({
            "secs": secs,
            "n": len(times),
            "median": median(times),
            "max": max(times),
            "pass": max(times) < budget,
        })

    longest_pass = None
    for row in per_length:
        if not row["pass"]:
            break
        longest_pass = row["secs"]

    return {
        "budget": budget,
        "per_length": per_length,
        "longest_pass": longest_pass,
        "verdict": "PASS" if per_length and all(r["pass"] for r in per_length) else "FAIL",
    }


def prefix_sources() -> list[tuple[str, np.ndarray]]:
    """Audio to cut prefixes from: real accented speech first, SAPI as a control.

    One clip per L1 group (the longest available), so a per-length cell has a real
    denominator across accents rather than repeats of one voice.
    """
    out: list[tuple[str, np.ndarray]] = []
    manifests = sorted(ACCENT.glob("manifest-*.jsonl"))
    entries: list[dict] = []
    for mf in manifests:
        with mf.open(encoding="utf-8") as f:
            entries.extend(json.loads(line) for line in f if line.strip())
    longest: dict[str, dict] = {}
    for e in entries:
        g = e["group"]
        if g not in longest or e["duration"] > longest[g]["duration"]:
            longest[g] = e
    for g in sorted(longest):
        e = longest[g]
        wav = ACCENT / e["wav"]
        if wav.exists():
            out.append((f"{g}({e['duration']:.0f}s)", to_16k(*load_wav(wav))))
    if (BENCH / "long.wav").exists():
        out.append(("sapi(10s)", to_16k(*load_wav(BENCH / "long.wav"))))
    if not out:
        raise SystemExit(
            "no prefix audio — run scripts/fetch_accent_data.py or record .bench/long.wav"
        )
    return out


def timed_decode(model, audio: np.ndarray, **overrides) -> float:
    """One decode, timed, with the app's own parameters unless overridden."""
    opts = decode_options(final=overrides.pop("final", False))
    opts.update(overrides)
    t = time.perf_counter()
    segments, _ = model.transcribe(audio, **opts)
    list(segments)  # the generator is where the decode actually happens
    return time.perf_counter() - t


def prefix_gate(model, sources: list[tuple[str, np.ndarray]], repeats: int = 3) -> dict:
    """Decode growing prefixes with production *partial* parameters and time them.

    Each (length, source) cell is decoded `repeats` times and contributes its median,
    because a shared CPU produces occasional 2x outliers that would otherwise decide a
    worst-case gate on scheduler noise rather than on the model.
    """
    # Warm-up: the first decode after load pays one-off allocation the user only ever
    # pays once per session, and charging it to the 1 s cell would misreport the gate.
    timed_decode(model, sources[0][1][:SR])

    rows: list[tuple[int, float]] = []
    detail: list[dict] = []
    for secs in PREFIX_LENGTHS:
        n = int(secs * SR)
        for label, audio in sources:
            if n > len(audio):
                continue
            times = [
                timed_decode(model, audio[:n])  # the app's own partial options
                for _ in range(repeats)
            ]
            cell = median(times)
            rows.append((secs, cell))
            detail.append({"secs": secs, "source": label,
                           "times": [round(x, 3) for x in times]})
            print(f"  prefix_{secs:>2}s  {label:<16} median={cell:5.2f}s"
                  f"  spread={min(times):.2f}-{max(times):.2f}s  rtf={cell / secs:4.2f}")

    summary = summarise_gate(rows)
    summary["repeats"] = repeats
    summary["detail"] = detail
    print(f"\n  {'prefix':>7}{'n':>4}{'median':>9}{'max':>8}{'gate':>7}")
    for row in summary["per_length"]:
        print(f"  {row['secs']:>6}s{row['n']:>4}{row['median']:>9.2f}{row['max']:>8.2f}"
              f"{'ok' if row['pass'] else 'BREACH':>7}")
    longest = summary["longest_pass"]
    reach = f"worst case clean up to {longest}s of speech" if longest else "breaches at 1s"
    print(f"  R4 budget {PARTIAL_BUDGET_SEC}s -> {summary['verdict']}  ({reach})")
    return summary


def finals_cost(model, sources: list[tuple[str, np.ndarray]], repeats: int = 2) -> dict:
    """What a *final* costs at each beam width.

    Finals are not latency-bound the way partials are — the draft is held on screen
    while they run (R5) — but "not bound" is not "free", and Phase 1 proposes beam 5.
    This prices that proposal at a typical dictation length and at the longest real
    utterance available, so the cost of the accuracy is on the record.
    """
    out: dict[str, dict] = {}
    for beam in (1, 2, 5):
        for label, audio in sources:
            for secs in (5, None):
                clip = audio if secs is None else audio[: secs * SR]
                if len(clip) < SR:
                    continue
                dur = len(clip) / SR
                cell = median([
                    timed_decode(model, clip, final=True, beam_size=beam)
                    for _ in range(repeats)
                ])
                key = f"beam{beam}/{'5s' if secs else 'full'}"
                agg = out.setdefault(key, {"beam": beam, "n": 0, "times": [],
                                           "audio_s": 0.0})
                agg["n"] += 1
                agg["times"].append(round(cell, 3))
                agg["audio_s"] += dur
    print(f"\n  {'case':<14}{'n':>4}{'median':>9}{'max':>8}{'rtf':>7}")
    for key, agg in out.items():
        agg["median"] = median(agg["times"])
        agg["max"] = max(agg["times"])
        agg["rtf"] = sum(agg["times"]) / agg["audio_s"]
        print(f"  {key:<14}{agg['n']:>4}{agg['median']:>9.2f}{agg['max']:>8.2f}"
              f"{agg['rtf']:>7.2f}")
    return out


def main() -> None:
    from faster_whisper import WhisperModel

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    names = args or ["base.en"]
    prefix_only = "--prefix-only" in flags
    want_finals = "--finals" in flags
    repeats = next(
        (int(f.split("=", 1)[1]) for f in flags if f.startswith("--repeats=")), 3
    )

    sources = prefix_sources()
    print("prefix sources: " + ", ".join(label for label, _ in sources))

    results = {}
    for name in names:
        t0 = time.perf_counter()
        model = WhisperModel(name, device="cpu", compute_type="int8")
        print(f"\nMODEL={name}  load+fetch={time.perf_counter() - t0:.2f}s")

        def run(audio, label):
            t = time.perf_counter()
            segs, _ = model.transcribe(
                audio, language="en", beam_size=1, vad_filter=False
            )
            text = " ".join(s.text for s in segs).strip()
            dt = time.perf_counter() - t
            dur = len(audio) / SR
            print(f"{label:12s} audio={dur:5.2f}s  decode={dt:5.2f}s  rtf={dt / dur:4.2f}")
            return text, dt

        if not prefix_only:
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

        print(f"\n--- R4 gate: a partial must land within {PARTIAL_BUDGET_SEC}s ---")
        results[name] = prefix_gate(model, sources, repeats=repeats)

        if want_finals:
            print("\n--- finals cost by beam width (not latency-bound, but not free) ---")
            results[name]["finals"] = finals_cost(model, sources)

    if len(results) > 1:
        print("\n--- R4 summary ---")
        for name, s in results.items():
            reach = f"{s['longest_pass']}s" if s["longest_pass"] else "none"
            print(f"{name:<12} {s['verdict']:<5} longest clean prefix: {reach}")

    out = ACCENT / "prefix-gate.json" if ACCENT.exists() else BENCH / "prefix-gate.json"
    # Merge rather than overwrite: re-running one model to settle a noisy cell should
    # not silently delete the other model's numbers from the record.
    merged = {}
    if out.exists():
        try:
            merged = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            merged = {}
    merged.update(results)
    out.write_text(json.dumps(merged, indent=1), encoding="utf-8")
    print(f"\ndetail -> {out}")


if __name__ == "__main__":
    main()
