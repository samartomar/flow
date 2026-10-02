"""Measure Flow's time to first word, in a fresh interpreter, on a cold machine.

The number this replaces was typed once into `docs/guide.md` (~1.4 s cold start) from a
run nobody could repeat. `flow/coldstart.py` says why the harness is a script and not a
test, and why "cold" is the hard part.

`--repeat` forks per run rather than looping in-process, because the page cache holds the
weights after the first load and run 2 onwards would measure a RAM copy. Repeated runs are
reported as **warm** and never labelled cold: publishing a warm number as a cold one is
how a 4 s first run becomes a 1.4 s claim.

Reads its device and tiers from the same `flow.asr` the app resolves from, and records
them in the result, because a CPU number and a CUDA number are not comparable and the
guide's table has no device column.

Writes: .bench/cold-start/results-<tag>.json
Usage:  uv run python scripts/cold_start.py [--repeat N] [--tag SUFFIX] [--markdown]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import coldstart  # noqa: E402
from flow.asr import default_models, resolve_device  # noqa: E402
from flow.diag import bench_identity  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench" / "cold-start"


def one_run() -> dict:
    """Build both tiers in this process and return the three marks.

    `WhisperTranscriber` rather than a bare `faster_whisper.WhisperModel` on purpose: the
    number has to be the one a launch actually pays, with this class, this device
    resolution and this compute type. Building the raw model directly would be a faster
    measurement of a slower product.
    """
    from flow.asr import WhisperTranscriber

    marks = coldstart.stage_times()
    #: `resolve_device` is timed as its own stage because it is not free: probing for a
    #: CUDA device costs seconds on a machine that has one, which is more than the model
    #: load itself. Folded into `model-load` it would have been indistinguishable from
    #: decoding weights, and it is the one stage here that a launch could plausibly do
    #: lazily or in the background.
    t0 = time.monotonic()
    device = resolve_device("auto")
    t1 = time.monotonic()
    marks[coldstart.STAGE_RESOLVE] = t1 - t0

    partial, final = default_models("cpu")
    asr = WhisperTranscriber(partial_model=partial, final_model=final, device=device)

    before = time.monotonic()
    asr.load()
    after = time.monotonic()

    marks[coldstart.STAGE_MODEL] = after - before
    #: Cumulative from process start, so the figure quoted is the one a person waits
    #: through. Read fresh *after* the load and used as-is: `origin()` returns the
    #: elapsed time at the moment it is called, so asking it here already includes the
    #: model build. An earlier version added the load duration on top of that, which
    #: double-counted it and made `ready` exceed the sum of its own stages by ~2.5 s - the
    #: same gap that first looked like a missing CUDA probe. It was this line.
    marks[coldstart.STAGE_READY] = coldstart.origin()
    return marks


def median_of(n: int) -> dict:
    """`n` runs, each in its own interpreter, summarised by each stage's median.

    Median rather than mean because one antivirus scan is enough to make a single cold
    sample meaningless, and the middle of a cold-start distribution is what a person
    experiences - they reboot once and get it. Worst case rides along so a tail the median
    hides stays visible.

    A run that could not build a model is not a zero: the failure is reported and the
    whole measurement abandoned, rather than a median being quoted over however many runs
    happened to succeed. That is how a bench ends up answering a question about five
    samples using three.
    """
    import subprocess

    here = Path(__file__).resolve()
    rows = []
    for _ in range(max(1, n)):
        done = subprocess.run(
            [sys.executable, str(here), "--one", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(here.parent.parent))
        if done.returncode != 0:
            sys.stderr.write(done.stderr or done.stdout)
            raise SystemExit("a cold-start run failed; nothing measured")
        rows.append(json.loads(done.stdout))

    out = {}
    for stage in coldstart.STAGES:
        got = [r[stage] for r in rows if r.get(stage) is not None]
        out[stage] = statistics.median(got) if got else None
        out[f"{stage}_worst"] = max(got) if got else None
    out["runs"] = len(rows)
    return out
def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.2f} s"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="cold_start", description="Measure Flow's time to first word, cold or warm")
    ap.add_argument("--repeat", type=int, default=1,
                    help="median of N fresh interpreters; warm after the first")
    ap.add_argument("--tag", default="", help="suffix for the results file")
    ap.add_argument("--markdown", action="store_true", help="print the guide's table row")
    ap.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.one:
        # The child. JSON on stdout and nothing else, because one library warning printed
        # here makes the parent's `json.loads` fail on a measurement that actually worked.
        print(json.dumps(one_run()))
        return 0

    marks = one_run() if args.repeat <= 1 else median_of(args.repeat)
    device = resolve_device("auto")
    partial, final = default_models("cpu")
    marks["identity"] = bench_identity(models=(partial, final), device=device)
    marks["warm"] = args.repeat > 1

    BENCH.mkdir(parents=True, exist_ok=True)
    path = BENCH / f"results-{args.tag or 'cold'}.json"
    path.write_text(json.dumps(marks, indent=1), encoding="utf-8")

    if args.markdown:
        # The stages are listed rather than collapsed into two numbers, because the guide's
        # old row (1.4 s = 0.40 import + 0.98 load) did not add up to the total it claimed
        # and a reader had no way to tell what the missing time was. This one does.
        stages = " + ".join(_fmt(marks[s]) for s in coldstart.STAGES[:-1])
        print("| | |")
        print("|---|---|")
        print(f"| Time to first word | {_fmt(marks[coldstart.STAGE_READY])} "
              f"({stages}), {device} |")
        return 0

    kind = ("warm - a restart without a reboot, NOT the number a reboot gives"
            if marks["warm"] else "cold - one fresh interpreter")
    print(f"Flow time to first word: {kind}")
    print(f"device: {device}   runs: {marks.get('runs', 1)}   written: {path.name}\n")
    width = max(len(s) for s in coldstart.STAGES) + 2
    for stage in coldstart.STAGES:
        worst = marks.get(f"{stage}_worst")
        print(f"  {stage:<{width}}{_fmt(marks[stage])}"
              + (f"   worst: {_fmt(worst)}" if worst is not None else ""))
    #: The stages must add up to the total. Checked and said out loud rather than trusted:
    #: it is the check that caught the double-count, and a report that quietly disagreed
    #: with itself is worse than one that prints a warning.
    parts = [marks[s] for s in coldstart.STAGES[:-1]]
    total = marks[coldstart.STAGE_READY]
    if total is not None and all(p is not None for p in parts):
        drift = abs(sum(parts) - total)
        note = "adds up" if drift < 0.35 else f"DOES NOT ADD UP (off by {drift:.2f} s)"
        print(f"\n  stages sum to {sum(parts):.2f} s against a {total:.2f} s total: {note}")
    print("\nRun this after a reboot for a number you can quote. Repeating in one")
    print("process measures the second load, which reads the page cache.")
    return 0


if __name__ == "__main__":
    sys.exit(main())