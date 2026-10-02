from __future__ import annotations

import json
import sys
from pathlib import Path


#: The groups in the order every published table has used, with `us-control` last
#: because it is the comparison rather than a population. A group a file does not carry
#: is printed `n/a` rather than `0.000`: the five here are what EdAcc has, and a new
#: corpus adding a sixth should show up as a missing number, not a perfect one.
GROUPS = ("indian", "japanese", "russian", "spanish", "us-control")

#: The P2 bound from `docs/product.md`: a filter or gate may reject audio, but the user
#: can always find out that it happened and recover the text. Below this the claim holds.
P2_BOUND = 0.01


def wer(row):
    """Word error rate for one group, or None when the denominator is zero.

    `ref_words` rather than the clip count is the denominator, and it is read out of the
    file rather than recomputed: the bench already normalised both sides before counting,
    and doing it a second time here is how a report ends up disagreeing with the thing it
    is reporting on.
    """
    words = (row or {}).get("ref_words") or 0
    return None if not words else row["model_edits"] / words


def rate_for(groups, key):
    """`(hits, clips, rate)` summed across every group, for a whole-run number.

    `key` names a per-clip count the file carries - `false_reject`, `model_empty`. The
    raw counts come back beside the rate on purpose: P2 is a rate and rates hide their
    denominators, and 0% over 3 clips is not the same claim as 0% over 300. The rate is
    None when there are no clips at all, so a caller rendering a table cannot turn an
    empty run into a perfect score.
    """
    hits = sum((g or {}).get(key, 0) for g in groups.values())
    clips = sum((g or {}).get("n", 0) for g in groups.values())
    return hits, clips, (None if not clips else hits / clips)


def table_for(datasets, groups=GROUPS):
    """The WER table as `[(group, [cell, ...])]`, one cell per dataset.

    Datasets are `(label, data)` pairs; a cell is `"0.236"` or `"n/a"`. Kept as a plain
    nested list rather than a rendered string so the numbers can be asserted without
    matching on spacing, and so `--markdown` and the plain listing format the same facts
    twice instead of being two hand-maintained tables that can disagree.
    """
    rows = []
    for group in groups:
        cells = []
        for _label, data in datasets:
            got = wer((data.get("groups") or {}).get(group))
            cells.append("n/a" if got is None else f"{got:.3f}")
        rows.append((group, cells))
    return rows


def main(argv=None) -> int:
    """Print every accent number the product claims, from the results files on disk.

    Three of them already live in `docs/roadmap.md` as a table somebody typed. That is
    the problem this exists to fix: the table cannot be re-derived, so it silently rots
    the moment a bench is re-run, and a stale number in a document nobody has to
    regenerate is worse than no number at all. Everything printed here comes out of
    `.bench/accent/results-*.json`, so re-running a bench and re-running this together
    keeps the prose honest.

    Refuses to print rather than printing a guess. A missing results file is not a zero
    WER, and this is the one script in `scripts/` that writes nothing and is expected to
    be run by a person reading the output rather than by CI, so a clean "no data" line
    is more useful than a traceback.

    Usage:  uv run python scripts/accent_report.py
            uv run python scripts/accent_report.py --markdown   # for pasting into docs
    """
    import argparse

    ap = argparse.ArgumentParser(
        prog="accent_report",
        description="Per-accent WER and P2 false-reject rates, from .bench/accent/")
    ap.add_argument("--markdown", action="store_true",
                    help="print the roadmap table instead of the plain listing")
    args = ap.parse_args(argv)

    bench = Path(__file__).resolve().parent.parent / ".bench" / "accent"
    #: The pairs the tuning decisions were made on (development.md). `-shipped` is the
    #: build that shipped; `-proposed` is the counterfactual it was measured against, and
    #: this project does not decide anything without both halves. The short-clip file is
    #: the P2 slice - the one whose false-reject rate is over the bound, and the reason it
    #: is printed next to the other two rather than filed away.
    wanted = [
        ("results-base.en-shipped.json", "base.en"),
        ("results-base.en-proposed.json", "base.en + proposed"),
        ("results-base.en-short-shipped.json", "base.en (short clips)"),
    ]

    def load(name):
        try:
            return json.loads((bench / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    datasets = []
    missing = []
    for name, label in wanted:
        data = load(name)
        (datasets.append((label, data)) if data is not None else missing.append(label))

    if not datasets:
        print("no accent results under .bench/accent/ - run scripts/accent_bench.py first")
        return 0

    rows = table_for(datasets)

    if args.markdown:
        names = [label for label, _d in datasets]
        print("| group | " + " | ".join(names) + " |")
        print("|---|" + "---|" * len(names))
        for group, cells in rows:
            print(f"| {group} | " + " | ".join(cells) + " |")
        return 0

    print("Accent WER (model WER: every decoded segment, before Flow's filters)")
    print("Read the denominator: these are conversational EdAcc transcripts, so even")
    print("us-control runs high. Within-group model deltas are the signal.\n")
    width = max(len(label) for label, _d in datasets) + 3
    print(f"{'group':<14}" + "".join(f"{label:>{width}}" for label, _d in datasets))
    for group, cells in rows:
        print(f"{group:<14}" + "".join(f"{c:>{width}}" for c in cells))

    print("\nP2 false-reject: utterances where the model heard words and the filters ate "
          "all of them.")
    print(f"The product bound is < {P2_BOUND * 100:.0f}%.")
    for label, data in datasets:
        hits, clips, rate = rate_for(data["groups"], "false_reject")
        shown = "n/a" if rate is None else f"{rate * 100:.1f}%"
        verdict = "n/a" if rate is None else ("within" if rate < P2_BOUND else "OVER")
        print(f"  {label:<{width}}{hits}/{clips} = {shown}  [{verdict}]")
    if missing:
        print("\nnot on disk (re-run the bench to include these):")
        for label in missing:
            print(f"  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())