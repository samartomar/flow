"""Parakeet TDT 0.6B v3 on onnx-asr: accuracy, speed, and the numbers the gate rests on.

Answers, for one variant at a time (`fp32` or `int8`, see `flow/parakeet.py`):

  1. Errors per 100 words on the EdAcc accent slice, per group — scored with
     `accent_bench.wer_counts`, the same scorer every other model in `flow/home/models.py`
     was scored with, on the same `manifest-edacc.jsonl` clips.
  2. Speed on the CPU: real-time factor, per-clip p50/p95, and load time.
  3. The distribution of the **mean token log-probability** over those clips (p1/p5/p50,
     and the share of clips below `clean.TOKEN_LOGPROB_MIN`) — what real speech looks like
     to the hallucination gate, which is what the threshold has to stay clear of.
  4. What the model says to silence and noise: the eight clips with nothing in them
     (four synthetic, four recorded in a room with a fan) and the four recorded with speech
     in them for contrast — and the mean log-probability of anything it invents.

The model is built by `flow.parakeet.load_model` and decoded by `flow.parakeet.decode`, so
this measures what Flow runs, thread count included. It needs the `[parakeet]` extra:

    uv run --extra parakeet python scripts/parakeet_bench.py fp32 [--model-dir DIR]
    uv run --extra parakeet python scripts/parakeet_bench.py int8 --threads 8 --limit 50

Writes `.bench/accent/results-parakeet-<variant><tag>.json` (a few KB: per-clip numbers,
no audio). `--model-dir` points at a directory of the variant's files when they are not
under `~/.flow/models`. The recorded silence clips are 48 kHz and are resampled here;
`accent_bench.load_wav` does not resample, and the accent clips are already 16 kHz.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from accent_bench import BENCH, load_wav, wer_counts  # noqa: E402
from flow import parakeet  # noqa: E402
from flow.clean import TOKEN_LOGPROB_MIN  # noqa: E402
from flow.diag import bench_identity  # noqa: E402

SR = 16000
RECORDINGS = BENCH.parent

#: The recordings with nothing to hear, then the ones with speech in them. Same names the
#: spike used, so numbers compare across runs.
EMPTY = ["room", "fan45_quiet", "fan55_quiet", "setup_quiet"]
SPOKEN = ["acoustic", "fan45_speech", "fan55_speech", "setup_speech"]


def load_resampled(path: Path) -> np.ndarray:
    """A recording as mono float32 at 16 kHz, by linear interpolation (these are noise
    and speech for a gate measurement, not a fidelity test)."""
    with wave.open(str(path), "rb") as w:
        rate, channels = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    if rate != SR:
        n = int(len(a) * SR / rate)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a


def silence_cases() -> dict[str, tuple[np.ndarray, bool]]:
    """{name: (audio, expected_empty)} — seeded, so two runs hear the same noise."""
    rng = np.random.default_rng(11)
    cases = {
        "digital silence 3s": np.zeros(3 * SR, np.float32),
        "very quiet noise 3s": (rng.standard_normal(3 * SR) * 0.0003).astype(np.float32),
        "room-ish noise 3s": (rng.standard_normal(3 * SR) * 0.004).astype(np.float32),
        "loud noise 3s": (rng.standard_normal(3 * SR) * 0.05).astype(np.float32),
    }
    out = {name: (audio, True) for name, audio in cases.items()}
    for name in EMPTY + SPOKEN:
        path = RECORDINGS / f"{name}.wav"
        if path.exists():
            out[name] = (load_resampled(path), name in EMPTY)
    return out


def percentile(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("variant", choices=sorted(parakeet.VARIANTS))
    ap.add_argument("--model-dir", default=None, help="the variant's files, if not installed")
    ap.add_argument("--threads", type=int, default=None,
                    help=f"intra-op threads (default {parakeet.default_threads()}, as Flow)")
    ap.add_argument("--manifest", default="manifest-edacc.jsonl")
    ap.add_argument("--limit", type=int, default=10**9, help="first N clips (smoke runs)")
    ap.add_argument("--tag", default="", help="suffix for the results file")
    args = ap.parse_args()

    threads = args.threads or parakeet.default_threads()
    t0 = time.perf_counter()
    model = parakeet.load_model(args.variant, args.model_dir, threads)
    load_s = time.perf_counter() - t0
    print(f"parakeet {args.variant}: load {load_s:.2f}s, {threads} threads", flush=True)

    for _ in range(3):  # warm-up: kernel selection and allocator growth, off the clock
        parakeet.decode(model, np.zeros(3 * SR, np.float32))

    quiet = []
    for name, (audio, expected_empty) in silence_cases().items():
        text, lp = parakeet.decode(model, audio)
        quiet.append({"name": name, "expected_empty": expected_empty, "text": text,
                      "mean_logprob": lp})
        shown = "-" if lp is None else f"{lp:.2f}"
        print(f"[{'silence' if expected_empty else 'speech '}] {name:20} -> {text!r} "
              f"(mean lp {shown})", flush=True)

    rows = [json.loads(line) for line in (BENCH / args.manifest).open(encoding="utf-8")]
    rows = rows[:args.limit]
    groups: dict[str, dict] = {}
    clips, latencies, logprobs = [], [], []
    for row in rows:
        audio = load_wav(BENCH / row["wav"])
        t = time.perf_counter()
        text, lp = parakeet.decode(model, audio)
        took = time.perf_counter() - t
        errors, words = wer_counts(row["ref"], text)
        g = groups.setdefault(row["group"], {"errors": 0, "words": 0, "audio": 0.0,
                                             "decode": 0.0, "clips": 0, "empty": 0})
        g["errors"] += errors
        g["words"] += words
        g["audio"] += len(audio) / SR
        g["decode"] += took
        g["clips"] += 1
        g["empty"] += not text
        latencies.append(took)
        if lp is not None:
            logprobs.append(lp)
        clips.append({"wav": row["wav"], "group": row["group"], "errors": errors,
                      "words": words, "seconds": len(audio) / SR, "decode_s": took,
                      "mean_logprob": lp, "text": text})

    print(f"\n{'group':12} {'errors/100':>10} {'clips':>6} {'words':>7} {'rtf':>6}")
    for name, g in sorted(groups.items()):
        print(f"{name:12} {100 * g['errors'] / g['words']:10.1f} {g['clips']:6d} "
              f"{g['words']:7d} {g['decode'] / g['audio']:6.3f}")
    errors = sum(g["errors"] for g in groups.values())
    words = sum(g["words"] for g in groups.values())
    audio_s = sum(g["audio"] for g in groups.values())
    decode_s = sum(g["decode"] for g in groups.values())
    below = sum(lp < TOKEN_LOGPROB_MIN for lp in logprobs)
    summary = {
        "errors_per_100": 100 * errors / words,
        "rtf": decode_s / audio_s,
        "p50_ms": 1000 * float(np.median(latencies)),
        "p95_ms": 1000 * float(np.percentile(latencies, 95)),
        "load_s": load_s,
        "empty_clips": sum(g["empty"] for g in groups.values()),
        "logprob_p1": percentile(logprobs, 1),
        "logprob_p5": percentile(logprobs, 5),
        "logprob_p50": percentile(logprobs, 50),
        "clips_below_threshold": below,
        "threshold": TOKEN_LOGPROB_MIN,
        "clips": len(clips),
    }
    print(f"\nTOTAL parakeet {args.variant}: errors/100 words={summary['errors_per_100']:.1f} "
          f"rtf={summary['rtf']:.3f} ({1 / summary['rtf']:.0f}x real time) "
          f"p50={summary['p50_ms']:.0f}ms p95={summary['p95_ms']:.0f}ms load={load_s:.2f}s "
          f"empty={summary['empty_clips']}")
    print(f"mean token log-prob over {len(logprobs)} clips: p1={summary['logprob_p1']:.2f} "
          f"p5={summary['logprob_p5']:.2f} p50={summary['logprob_p50']:.2f}; "
          f"{below} below {TOKEN_LOGPROB_MIN}")
    invented = [q for q in quiet if q["expected_empty"] and q["text"]]
    print(f"silence/noise: {len(invented)} of "
          f"{sum(q['expected_empty'] for q in quiet)} empty clips invented text"
          + "".join(f"\n  {q['name']}: {q['text']!r} (mean lp {q['mean_logprob']:.2f})"
                    for q in invented))

    out = BENCH / f"results-parakeet-{args.variant}{args.tag}.json"
    payload = {
        "identity": bench_identity(models=(f"parakeet-{args.variant}",), device="cpu"),
        "variant": args.variant, "threads": threads, "summary": summary,
        "groups": groups, "silence": quiet, "clips": clips}
    # `bench_identity` knows faster-whisper and the Hugging Face cache; this model is
    # neither, so what produced these numbers is added to the block: the runtime versions
    # and the exact commit of the weights.
    import importlib.metadata as md

    identity = payload["identity"]
    for package in ("onnx-asr", "onnxruntime"):
        identity[package] = md.version(package)
    identity["models"][f"parakeet-{args.variant}"] = f"{parakeet.REPO}@{parakeet.REVISION}"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"detail -> {out}")


if __name__ == "__main__":
    main()
