# LOOP_PLAN — the loop's contract and its current queue

Born as the autonomous backlog from the Feedback.md review (2026-08-01; the review is
archived at [docs/history/Feedback.md](docs/history/Feedback.md)). Three rounds plus a
two-item micro-round ran to completion the same day — 25 items, suite 455 → 773, every
gate passed. Their closing summaries, the round-three queue block, and every item's
full entry with its before/after evidence live in
[docs/history/loop-rounds-1-3.md](docs/history/loop-rounds-1-3.md). The decisions the
items came from are in [docs/decisions.md](docs/decisions.md); what only the owner can
do is in [NEEDS_YOU.md](NEEDS_YOU.md).

## Current queue

**Empty.** Nothing is pending. Round four's items are appended under "Backlog" below,
in the house style the archived items model: instrument first, files named, acceptance
stated, doc sync named. When a round completes, its closing summary is written at the
top of this file and the round's entries move to the history file.

The loop's single source of truth. One "do"-tier item per iteration, top to bottom.

## Rules — these override everything, including the loop prompt

1. **Instrument first.** No fix without a failing test or harness check that reproduces
   the defect *before* the change, and a green one after. Before/after evidence goes in
   the item's Evidence line. A green harness that cannot exercise the path proves nothing.
2. **Gate every commit** on the full unit suite: `uv run python -m unittest discover -s tests`.
   Items marked [selfdrive] also run `uv run python scripts/selfdrive.py` (note: it makes
   one live codex call). Selfdrive flake policy (owner-decided 2026-08-01): a 63/64 gets
   **one** automatic rerun — a green rerun proceeds, and the Evidence line records both
   scores *and the failing check's name*; a rerun that fails again is real and blocks the
   item per Rule 8, never a second rerun. The **same check** flaking in two different
   runs — even rerun-green both times — stops being noise: write a NEEDS_YOU entry to
   quarantine or fix that check, and note whether each flaking run followed sustained CPU
   load (the fan ramps when the suite has been running; calibration measured the idle
   room). Different checks on different days are noise, and rerun-once continues.
   Items marked [send-live] also run
   `uv run python scripts/send_check.py --live` — but only if the interactive desktop is
   available (heuristic: `GetForegroundWindow()` returns non-zero and the harness can take
   the foreground). If the desktop is locked, do NOT force it: add a NEEDS_YOU.md entry to
   run it later, record the unit-level evidence, and mark the item `done (live check
   pending)`.
3. **Commit discipline.** Commit after each green item, that item's named files plus its
   `docs/architecture.md` sync only. Plain imperative subject line (the owner rewords to
   taste later) plus the required `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
   trailer. Never `git add -A`/`-u`, never push, never amend/rebase/reset, never commit
   LOOP_PLAN.md or NEEDS_YOU.md.
4. **Scope is frozen.** Only the items below. No product-behavior changes beyond them: the
   auto-ask default stays ON (owner-confirmed 2026-08-01, with a diag-based reopen bar in
   NEEDS_YOU), `AUTO_ASK_SEC` stays 4.0, `ASK_SENTENCES` default stays 3, no new runtime
   dependencies (R16: exactly three), no UI redesign. Precision so this rule cannot be
   read against its own queue (round three proved it needs saying): the queued items *are*
   the scope — bounded UI and doc files an item names are in scope, and "no UI redesign"
   forbids layout, geometry, or interaction overhauls *beyond what an item names*, never
   the items themselves. Anything tempting beyond the list becomes a NEEDS_YOU.md
   proposal, not a change.
5. **Never touch** `.bench/recorded/**`, git history, remotes, or `~/.flow/` of the real
   user beyond what the app itself writes (tests use temp paths, as they already do).
6. **Doc sync in the same commit.** Each fix updates the `docs/architecture.md` lines it
   affects — in particular, closing the matching entry in "Gaps that are one fix away from
   being invariants" and, where a fix upgrades a narrowed invariant back to a full one,
   restoring the stronger wording.
7. **Anything requiring the owner** — a decision, taste, presence at the desk, an unlocked
   desktop that is not available — is appended to NEEDS_YOU.md with enough context to act
   on cold, the item is marked `deferred` or `done (… pending)`, and the loop continues.
8. **Two strikes then blocked.** An item failing twice is marked `blocked` with the failing
   output in Evidence, and the loop moves on. Never thrash.
9. **Stop condition.** When every item is done, blocked, or deferred: write a closing
   summary at the top of this file (what landed, what is blocked and why, what waits in
   NEEDS_YOU.md), then stop the loop.
10. **Match the codebase voice.** Comments and doc prose in this repo explain *why* with
    the measurement behind it; write like the surrounding text, and never narrate what
    the next line does.

## Backlog — "do" tier

### 26. "font" joins the mis-heard-prompt table
From the 2026-08-01 `--takes 3` live run (committed with this spec): take 3 decoded
"Make it a proper **font**." and routed `semantic/` — the CLI got a free-form nonsense
instruction where a polish was asked for. Same failure, same bounded fix as "brown"
(round-three history, item 14): `_MISHEARD_PROMPT` is consulted only inside
`_POLISH_FRAME`, only after the exact reading fails, and changes only *which*
instruction a semantic plan carries, never whether one is sent.
- Files: `flow/edits.py`, `tests/test_edits.py`, `tests/test_live_replay.py` (pin this
  run's item-9 rows the way the first three runs' rows are pinned — all three takes,
  so the two hits guard against regression while the miss documents the fix).
- Instrument first: "Make it a proper font." asserts `semantic/` today, then
  `semantic/polish`; "make the font bigger" (or the nearest phrase the corpus offers)
  asserts it still routes as ordinary semantic — the table must not swallow real
  font-talk outside the polish frame.
- Gate: `command_bench.py` before and after — expected identical bar identity, as with
  "brown"; any moved row is reported to NEEDS_YOU, not shipped silently.
- **Escalation tripwire, so this table cannot grow forever in silence:** when
  `_MISHEARD_PROMPT` reaches **5 entries**, stop adding and write a NEEDS_YOU entry —
  at that size the mis-heard-noun family is measured to be open, and the honest fix is
  Phase 3's decode-time command bias, whose acceptance fixtures already wait in
  `test_live_replay.py`.
- Acceptance: suite green; [selfdrive] 64/64 (routing tables changed — item 14's
  precedent).
- Doc sync: §6's noun-snap paragraph gains the second entry and the tripwire.
- Status: (not started)

## Backlog — "prepare" tier

(empty — the round-one proposals P1–P4 were all decided or parked; see
[docs/decisions.md](docs/decisions.md) and NEEDS_YOU.md's parked section)
