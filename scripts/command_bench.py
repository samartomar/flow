"""Does the hardened command grammar catch more commands without eating dictation?

Two numbers, because a grammar has two ways to fail and fixing one usually worsens
the other:

  **Recall** — canonical commands from the inventory in flow/edits.py, corrupted the
  ways ASR actually corrupts them (politeness the model transcribes verbatim, a verb
  suffix, one substituted or transposed letter, and the observed mis-hearings from the
  alias table). How many still route to the right operation?

  **Precision** — real conversational speech from the EdAcc references, none of which
  is a command, routed against a draft. Anything that comes back as an edit is a
  silent misroute: the user's sentence would have deleted their text instead of being
  typed. This is the number fuzzy matching endangers, and it is measured on real
  utterances rather than invented ones.

The corruptions are synthetic and labelled as such. They are drawn from the failure
classes the audit named, not from recordings of accented speakers — that benchmark
needs recorded speakers and is deferred. What this harness *can* do honestly is show that the grammar
survives the named classes and that the extra tolerance did not cost precision.

Usage:  uv run python scripts/command_bench.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.edits import _ALIASES, _plan_exact, plan, snap  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench" / "accent"

#: (utterance, draft, expected op). The draft is what makes a weak verb safe, so it is
#: part of the case rather than a constant.
DRAFT = "Meeting on Tuesday with Sameer about the release notes."
COMMANDS = [
    ("change Tuesday to Wednesday", "replace"),
    ("replace Sameer with Samir", "replace"),
    ("swap Tuesday for Friday", "replace"),
    ("delete Tuesday", "delete"),
    ("remove the release notes", "delete"),
    ("cut Sameer", "delete"),
    ("delete the last two words", "delete_last"),
    ("replace all Tuesday with Friday", "replace_all"),
    ("insert urgent before release", "insert_before"),
    ("add today after notes", "insert_after"),
    ("capitalize sameer", "capitalize"),
    ("uppercase release", "upper"),
    ("lowercase Sameer", "lower"),
    ("delete from Tuesday to release", "delete_range"),
]

LEAD_INS = ("please ", "can you ", "could you please ", "no, ", "sorry, ",
            "actually, ", "um, can you ", "just ")


def _suffix(utterance: str) -> str:
    verb, _, rest = utterance.partition(" ")
    return f"{verb}ing {rest}" if not verb.endswith("e") else f"{verb[:-1]}ing {rest}"


def _substitute(utterance: str) -> str:
    verb, _, rest = utterance.partition(" ")
    if len(verb) < 4:
        return utterance
    swapped = verb[:2] + ("x" if verb[2] != "x" else "y") + verb[3:]
    return f"{swapped} {rest}"


def _transpose(utterance: str) -> str:
    verb, _, rest = utterance.partition(" ")
    if len(verb) < 4:
        return utterance
    mid = len(verb) // 2
    return f"{verb[:mid]}{verb[mid + 1]}{verb[mid]}{verb[mid + 2:]} {rest}"


def _alias(utterance: str) -> str | None:
    """Replace the verb with an observed mis-hearing of it, if one is listed."""
    verb, _, rest = utterance.partition(" ")
    for wrong, right in _ALIASES.items():
        if right == verb.lower():
            return f"{wrong} {rest}"
    return None


def recall() -> dict:
    classes: dict[str, list[tuple[str, str]]] = {
        "clean": [], "politeness": [], "verb suffix": [],
        "one substitution": [], "transposition": [], "known mis-hearing": [],
    }
    for utterance, op in COMMANDS:
        classes["clean"].append((utterance, op))
        for lead in LEAD_INS:
            classes["politeness"].append((lead + utterance, op))
        classes["verb suffix"].append((_suffix(utterance), op))
        classes["one substitution"].append((_substitute(utterance), op))
        classes["transposition"].append((_transpose(utterance), op))
        if (aliased := _alias(utterance)) is not None:
            classes["known mis-hearing"].append((aliased, op))

    print(f"{'corruption':<20}{'n':>5}{'exact':>9}{'snapped':>10}")
    out = {}
    for name, cases in classes.items():
        exact = sum(1 for u, op in cases if _plan_exact(u, DRAFT).op == op)
        snapped = sum(1 for u, op in cases if plan(u, DRAFT).op == op)
        n = len(cases)
        print(f"{name:<20}{n:>5}{exact / n:>9.1%}{snapped / n:>10.1%}")
        out[name] = {"n": n, "exact": exact, "snapped": snapped}
    return out


#: Dictation that *starts like a command*, with a draft containing its own words —
#: the worst case for a grammar that decides by shape and target presence. EdAcc
#: supplies almost none of this (of 580 utterances, exactly one even reaches the
#: snapper), so without these the precision number would be measured on speech that
#: could never have failed.
ADVERSARIAL = [
    ("Delete key handling is broken.", "the delete key handling is broken"),
    ("Change management is hard at this scale.", "change management is hard"),
    ("Add the milk to the shopping list.", "add the milk to the list"),
    ("Stop the build before it deploys.", "stop the build before it deploys"),
    ("Cut the scope for this release.", "cut the scope for this release"),
    ("Remove the packaging before use.", "remove the packaging before use"),
    ("Insert the card and wait.", "insert the card and wait"),
    ("Swap files are filling the disk.", "swap files are filling the disk"),
    ("Replace parts are on order.", "replace parts are on order"),
    ("Drop tables are how you lose a database.", "drop tables are how you lose it"),
    ("At the conference we met Sameer.", "at the conference we met Sameer"),
    ("The lead is buried three paragraphs down.", "the lead is buried down"),
    ("Undo history is bounded at thirty entries.", "undo history is bounded"),
    ("Scratch pads are cheaper than documents.", "scratch pads are cheaper"),
    ("Forget about the deadline for a moment.", "forget about the deadline"),
    ("Capitalize on the momentum we have.", "capitalize on the momentum"),
    ("Strike action was announced on Tuesday.", "strike action was announced"),
    ("Adding tests before the refactor is wise.", "adding tests before refactor"),
    ("Deleting a branch does not delete the history.",
     "deleting a branch does not delete the history"),
    ("Changing Tuesday to Wednesday broke the booking.",
     "changing Tuesday to Wednesday broke the booking"),
]


def adversarial() -> dict:
    """Dictation shaped like a command, judged against a draft full of its own words."""
    print(f"\nadversarial dictation ({len(ADVERSARIAL)} sentences that start like "
          "commands):")
    out = {}
    for label, fn in (("exact", _plan_exact), ("snapped", plan)):
        bad = [(u, fn(u, d).kind, fn(u, d).op)
               for u, d in ADVERSARIAL if fn(u, d).kind in ("local", "undo")]
        out[label] = len(bad)
        print(f"  {label:<9} {len(bad):>4} misroutes  "
              f"{len(bad) / len(ADVERSARIAL):>7.2%}")
        for u, kind, op in bad:
            print(f"     {kind}/{op}: {u!r}")
    return out | {"n": len(ADVERSARIAL)}


def precision() -> dict:
    """Real speech, none of it a command. Any edit is a silent misroute."""
    entries = []
    for mf in sorted(BENCH.glob("manifest-edacc*.jsonl")):
        with mf.open(encoding="utf-8") as f:
            entries.extend(json.loads(line) for line in f if line.strip())
    if not entries:
        print("\nno EdAcc manifest — run scripts/fetch_accent_data.py for precision")
        return {}

    # Each utterance is judged against the *next* one as the held draft: real text,
    # and adversarial, because consecutive turns share vocabulary and so the targets
    # a mis-parse would look for are unusually likely to be present.
    refs = [e["ref"] for e in entries]
    misroutes = {"exact": [], "snapped": []}
    for i, ref in enumerate(refs):
        draft = refs[(i + 1) % len(refs)]
        for label, fn in (("exact", _plan_exact), ("snapped", plan)):
            p = fn(ref, draft)
            if p.kind in ("local", "undo"):
                misroutes[label].append((ref, p.kind, p.op))

    n = len(refs)
    print(f"\nprecision on {n} real utterances (none of them commands):")
    for label in ("exact", "snapped"):
        hits = misroutes[label]
        print(f"  {label:<9} {len(hits):>4} misroutes  {len(hits) / n:>7.2%}")
    for ref, kind, op in misroutes["snapped"][:5]:
        print(f"     {kind}/{op}: {ref[:64]!r}")
    return {k: len(v) for k, v in misroutes.items()} | {"n": n}


def main() -> None:
    print("RECALL — canonical commands, corrupted (synthetic, see module docstring)\n")
    r = recall()
    a = adversarial()
    p = precision()
    out = BENCH / "command-bench.json" if BENCH.exists() else Path("command-bench.json")
    out.write_text(
        json.dumps({"recall": r, "adversarial": a, "precision": p}, indent=1),
        encoding="utf-8",
    )
    print(f"\ndetail -> {out}")


if __name__ == "__main__":
    main()
