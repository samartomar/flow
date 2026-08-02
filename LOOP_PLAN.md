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

### 27. Publication readiness — everything the visibility flip needs, except the flip
Owner-decided 2026-08-01 (decisions.md "Distribution"). The repo goes public and is
listed in ai-harness; this item makes it legally and socially ready. The flip itself,
the license *choice*, and the consent wording are the owner's (NEEDS_YOU); this item is
the mechanical remainder, and it must not run until the owner's license word exists.
- Files: `LICENSE` (new), `pyproject.toml`, `README.md`, `flow/__main__.py`, tests.
- Do, each its own commit-safe piece:
  1. `LICENSE` with the owner's chosen text (recommendation on record: MIT) and
     `pyproject.toml` gains `license`, `authors`, and `[project.urls]` (repository +
     the ai-harness listing).
  2. README gains an **Install** section at the top: the uv two-liner
     (`uv tool install git+https://github.com/samartomar/flow`), the binary-zip
     alternative (item 28's artifact, with the one-time SmartScreen sentence stated
     honestly), Windows-only stated plainly, and the agent-CLI paragraph — dictation
     works without `codex`/`claude`; refine and the workshop need one on PATH, and
     Flow says so at startup rather than failing.
  3. **A `sys.platform` guard at the top of `main()`**: on non-Windows, exit with one
     honest sentence ("Flow's paste and hotkey layer is Windows-only today") before
     any ctypes import can traceback. Instrument first: a test that fakes the platform
     and asserts the message and the clean exit — a Mac user's first impression is a
     sentence, not a stack.
- Acceptance: suite green; `uv run flow --help` still works; README's install commands
  are copy-paste-exact.
- Doc sync: none beyond README (which this item names); architecture.md is untouched.
- Status: (not started — **blocked on the owner's license word**, then mechanical)

### 28. A binary anyone can download — PyInstaller zip on GitHub Releases, built by CI
Owner-decided 2026-08-01 (decisions.md "Distribution", widened same day). People
outside ai-harness get `flow.exe` with no Python: a **onedir** PyInstaller bundle,
zipped, attached to a GitHub Release by a workflow that runs on tag push.
- Files: new `.github/workflows/release.yml`, new `packaging/flow.spec` (PyInstaller
  spec, committed — a spec file is a measurement of what the bundle needs, not a
  scratch artifact), README's install section (one line pointing at Releases), tests
  only if a seam needs one.
- Shape, with the traps named:
  - **onedir, never onefile** — onefile trips antivirus heuristics and pays an unpack
    on every launch; a zip of onedir is the same download with neither cost.
  - Models are NOT bundled: they download to the HF cache on first decode exactly as
    the dev install does, and the startup line already names the path. Keeps the zip
    ~100 MB instead of ~400.
  - The known DLL collectors: `faster-whisper`/`ctranslate2` and `sounddevice`'s
    bundled PortAudio need PyInstaller `collect_all`/`collect_dynamic_libs` entries in
    the spec — build once locally and *run the exe* before trusting CI with it.
  - Version comes from `pyproject.toml`, not hand-typed in the workflow; the release
    tag and the wheel version must agree or the workflow fails loudly.
  - The workflow builds on `windows-latest`, uploads `flow-windows-x64.zip`, and runs
    the unit suite first — a release that skips the gate is not a release.
- Instrument first, adapted to packaging: the local build's acceptance is the bundled
  `flow.exe` launching on this machine and printing its startup lines (hotkeys, trace
  path, workshop line), plus `--help` exiting zero. What a local run cannot prove — a
  machine with no Python at all — is the owner's clean-machine desk check, written to
  NEEDS_YOU as `done (clean-machine check pending)` per Rule 2's pattern.
- Acceptance: suite green; local bundle launches and speaks its startup lines; the
  workflow file is syntax-valid (`gh workflow` lint or a dry parse); README points at
  Releases.
- Doc sync: architecture.md's Verification section gains one line on where releases
  come from and that the suite gates them.
- Status: (not started — item 27 first, so the release ships with a LICENSE inside.
  Amended by the split decision: the workflow file ships *in the public snapshot* and
  runs there — the public repo must build its own releases, which is also the proof
  the snapshot is complete)

### 29. The publish script — one command turns the private repo into the public snapshot
Owner-decided 2026-08-01 (decisions.md "Distribution amendment"). Two repos is a
standing sync problem; this makes it one command. The private repo (gosaminfo/flow)
is the source of truth; the public repo (samartomar/flow) receives a curated snapshot.
- Files: new `scripts/publish_snapshot.py`, tests (`tests/test_publish.py`), README
  (one line in a maintainer section).
- The whitelist, explicit in the script and mirrored in a test: `flow/`, `tests/`,
  `scripts/`, `docs/product.md`, `docs/architecture.md`, `docs/analysis.md`,
  `docs/roadmap.md`, `README.md`, `LICENSE`, `pyproject.toml`, `uv.lock`,
  `.github/workflows/release.yml`, `.gitignore`. **Excluded, and the test asserts each
  never lands in a snapshot:** `NEEDS_YOU.md`, `LOOP_PLAN.md`, `docs/decisions.md`,
  `docs/history/`, `docs/recording-kit.md`, `Feedback.md` (gone already, belt and
  braces), `.bench/` (carries the owner's decoded speech), `.claude/`.
- Instrument first, three checks that must fail before the script exists:
  1. **Self-sufficiency of links:** every relative markdown link in the snapshot set
     resolves inside the set. Run it against today's tree and it will fail — README
     links `docs/history/PROGRESS.md`, architecture.md links `history/` and
     `decisions.md` — and those references get a public-safe form (drop, reword, or
     point at the private repo by absolute URL with a "maintainer's record" note).
  2. **Self-sufficiency of the suite:** the unit suite runs green *inside a snapshot
     staging directory*. `tests/test_bench.py` and anything else reading `.bench/`
     must skip cleanly when the directory is absent — a skip with a reason, never a
     failure, and never a silent pass that proves nothing.
  3. **The snapshot is a squash, not a history:** the script commits the staged tree
     as a single commit on the public remote's `main` ("Snapshot from private repo at
     <short-hash>"), so no private history can leak through a snapshot push.
- Acceptance: suite green in the working repo AND in a staged snapshot; the link
  check reports zero danglers; a dry run prints the file list it would ship and the
  one it deliberately withholds.
- Doc sync: architecture.md's Verification section notes that the public repo is a
  generated snapshot and where it is generated from.
- Status: (not started — runs after 26–28; the first real publish is the owner's
  Stage 2)

## Backlog — "prepare" tier

(empty — the round-one proposals P1–P4 were all decided or parked; see
[docs/decisions.md](docs/decisions.md) and NEEDS_YOU.md's parked section)
