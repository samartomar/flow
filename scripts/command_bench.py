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

from flow.diag import bench_identity  # noqa: E402
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


#: The message on the recording sheet, which is the draft every recorded command is
#: aimed at. It has to match the sheet exactly: half these operations are only legal
#: because their target is present, so a paraphrase here would score the wrong thing.
RECORDED_DRAFT = (
    "hi priya, the deploy is scheduled for Tuesday afternoon. sameer is writing the "
    "RELEASE NOTES and running the migration. I attached the summary from the "
    "standup. tell me if Tuesday still works."
)

#: What each manifest op should come back as, in (kind, op) form. Four of the eleven
#: are whole-utterance routes with no op, which is why this is not a plain string
#: compare against Plan.op.
ROUTES = {
    "replace_all": ("local", "replace_all"), "replace": ("local", "replace"),
    "capitalize": ("local", "capitalize"), "lower": ("local", "lower"),
    "delete": ("local", "delete"), "delete_last": ("local", "delete_last"),
    "insert_before": ("local", "insert_before"), "undo": ("undo", ""),
    "polish": ("semantic", "polish"), "followup": ("followup", ""),
    "rescue": ("rescue", ""),
}


def recorded() -> dict:
    """The same question as recall(), asked of real accented audio instead of strings.

    Everything above this line corrupts clean text the way ASR is *believed* to corrupt
    it. This decodes what a person actually said, through the real final-tier model,
    and routes the transcript — so an accent that defeats the acoustic model and an
    accent that defeats the grammar both show up, and they show up separately.
    """
    from flow.asr import WhisperTranscriber

    mf = Path(__file__).resolve().parent.parent / ".bench" / "recorded" / \
        "manifest-recorded.jsonl"
    if not mf.exists():
        print("\nno recorded manifest — run scripts/ingest_recordings.py")
        return {}
    rows = [json.loads(line) for line in mf.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    commands = [r for r in rows if r["op"] in ROUTES]
    if not commands:
        return {}

    import wave

    import numpy as np

    asr = WhisperTranscriber()
    root = mf.parent
    print(f"\nRECORDED — {len(commands)} spoken commands from "
          f"{len({r['speaker'] for r in commands})} speaker(s), decoded and routed\n")
    print(f"{'spk':<14}{'#':>3} {'expected':<14}{'routed':<14}{'transcript'}")

    out: dict[str, dict] = {}
    for row in commands:
        with wave.open(str(root / row["wav"]), "rb") as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        text = asr.text(pcm.astype(np.float32) / 32768.0, final=True)
        p = plan(text, RECORDED_DRAFT)
        want = ROUTES[row["op"]]
        got = (p.kind, p.op)
        hit = got == want
        group = out.setdefault(row["group"], {"n": 0, "hit": 0, "miss": []})
        group["n"] += 1
        group["hit"] += hit
        if not hit:
            group["miss"].append({"item": row["item"], "want": row["op"],
                                  "got": f"{p.kind}/{p.op}", "text": text})
        mark = " " if hit else "*"
        print(f"{row['speaker']:<14}{row['item']:>3}{mark}{row['op']:<14}"
              f"{(p.op or p.kind):<14}{text[:40]}")

    print()
    for group, s in sorted(out.items()):
        print(f"  {group:<14}{s['hit']:>3}/{s['n']:<4} {s['hit'] / s['n']:>7.1%}")
    return out


def main() -> None:
    if "--recorded" in sys.argv:
        rec = recorded()
        out = BENCH / "command-bench-recorded.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"identity": bench_identity(), **rec}, indent=1),
                       encoding="utf-8")
        print(f"\ndetail -> {out}")
        return

    print("RECALL — canonical commands, corrupted (synthetic, see module docstring)\n")
    r = recall()
    a = adversarial()
    p = precision()
    sp = spans()
    esc = escalations()
    out = BENCH / "command-bench.json" if BENCH.exists() else Path("command-bench.json")
    # Provenance under one key, deliberately. This file is the one a grammar change is
    # verified against by diffing two consecutive runs byte for byte, and the block below
    # contains a date: whoever repeats that verification must drop "identity" and compare
    # the rest, not conclude the grammar moved because the day did.
    out.write_text(
        json.dumps({"identity": bench_identity(),
                    "recall": r, "adversarial": a, "precision": p, "spans": sp,
                    "escalations": esc}, indent=1),
        encoding="utf-8",
    )
    print(f"\ndetail -> {out}")



#: Spoken target vs the draft the same voice produced a moment earlier. These are the
#: substitutions accented English actually makes — vowel colouring, a lost or added
#: syllable boundary, th/t and v/w and b/v swaps — and each one is a case where the
#: exact matcher escalates a free local edit to a 7 s CLI call over text that does not
#: contain the word.
TARGET_PAIRS = [
    ("Meeting on Tuesday with summer about the release.", "Sameer", "summer"),
    ("Call some ear tomorrow about the deploy.", "Sameer", "some ear"),
    ("The fone rang twice during standup.", "phone", "fone"),
    ("We shipped it on Wensday afternoon.", "Wednesday", "Wensday"),
    ("Ask Catherine to review the migration.", "Katherine", "Catherine"),
    ("Nakamora signed off on the design.", "Nakamura", "Nakamora"),
    ("Send it to Adithya before the standup.", "Aditya", "Adithya"),
    ("The realease notes are still in draft.", "release", "realease"),
    ("It happens every nite around two.", "night", "nite"),
    ("Smyth wrote the original parser.", "Smith", "Smyth"),
]

#: Targets that are genuinely absent. A span here is a silent rewrite of the wrong
#: words, which is worse than escalating to the CLI.
ABSENT = [
    ("Meeting on Tuesday with Sameer about the release.", "Wednesday"),
    ("Meeting on Tuesday with Sameer about the release.", "deployment"),
    ("Call Bob today about the invoice.", "Alice"),
    ("The report is due at the end of the month.", "support"),
    ("We deleted the old branch yesterday.", "completed"),
    ("Send the draft to the team.", "Friday"),
    ("The parser handles nested quotes.", "Sameer"),
    ("Ask about the migration timeline.", "notes"),
]


def _corpus_absent() -> list[tuple[str, str]]:
    """Real utterances paired with a word that is genuinely not in them.

    The hand-written ABSENT list is eight cases; this is the same question asked of
    every EdAcc reference, so the false-span rate has a denominator worth quoting.
    """
    entries = []
    for mf in sorted(BENCH.glob("manifest-edacc*.jsonl")):
        with mf.open(encoding="utf-8") as f:
            entries.extend(json.loads(line) for line in f if line.strip())
    refs = [e["ref"] for e in entries if len(e["ref"].split()) >= 4]
    out = []
    for i, ref in enumerate(refs):
        # A content word from a distant utterance, checked to be absent from this one.
        donor = refs[(i + len(refs) // 2) % len(refs)].split()
        candidates = [w.strip(".,!?").lower() for w in donor if len(w) > 4]
        target = next((w for w in candidates if w not in ref.lower()), None)
        if target:
            out.append((ref, target))
    return out


def escalations() -> dict:
    """What phonetic matching is *for*: corrections that stay local.

    Each pair is a real command whose target the draft spells differently. Exact
    matching cannot find it, so the router escalates to a ~7 s CLI call over text that
    does not contain the word. The measure is how many of those become free local
    edits, and whether the edit lands on the right span.
    """
    from flow.phonetic import find_span

    cases = [(draft, f"change {target} to REPLACED", expected)
             for draft, target, expected in TARGET_PAIRS]
    local = correct = 0
    for draft, utterance, expected in cases:
        p = plan(utterance, draft)
        if p.kind != "local":
            continue
        local += 1
        span = find_span(draft, p.target)
        correct += bool(span) and draft[span[0]:span[1]].strip(" .,").lower() == expected.lower()
    n = len(cases)
    print(f"\ncorrections whose target the draft spells differently ({n} cases):")
    print(f"  stayed local (no 7s CLI call):  {local}/{n}  {local / n:.0%}")
    print(f"  ...and edited the right span:   {correct}/{n}  {correct / n:.0%}")
    return {"n": n, "local": local, "correct": correct}


def spans() -> dict:
    """Sweep the phonetic match threshold: recall against false spans."""
    from flow.phonetic import find_span

    corpus_absent = _corpus_absent()
    print(f"\n{'threshold':<11}{'found':>8}{'correct':>9}{'false spans':>13}"
          f"{'corpus false':>15}")
    out = {}
    for t in (0.75, 0.80, 0.82, 0.85, 0.88, 0.90):
        found = correct = 0
        for draft, target, expected in TARGET_PAIRS:
            span = find_span(draft, target, threshold=t)
            if span:
                found += 1
                correct += draft[span[0]:span[1]].strip(" .,").lower() == expected.lower()
        false = sum(1 for draft, target in ABSENT if find_span(draft, target, threshold=t))
        corpus_false = sum(
            1 for draft, target in corpus_absent
            if find_span(draft, target, threshold=t)
        )
        print(f"{t:<11}{f'{found}/{len(TARGET_PAIRS)}':>8}"
              f"{f'{correct}/{len(TARGET_PAIRS)}':>9}{f'{false}/{len(ABSENT)}':>13}"
              f"{f'{corpus_false}/{len(corpus_absent)}':>15}")
        out[str(t)] = {"found": found, "correct": correct, "false": false,
                       "corpus_false": corpus_false, "n_pairs": len(TARGET_PAIRS),
                       "n_absent": len(ABSENT), "n_corpus": len(corpus_absent)}
    return out

if __name__ == "__main__":
    main()
