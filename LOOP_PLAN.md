# LOOP_PLAN — the loop's contract and its current queue

Born as the autonomous backlog from the Feedback.md review (2026-08-01; the review is
archived at [docs/history/Feedback.md](docs/history/Feedback.md)). Three rounds plus a
two-item micro-round ran to completion the same day — 25 items, suite 455 → 773, every
gate passed. Their closing summaries, the round-three queue block, and every item's
full entry with its before/after evidence live in
[docs/history/loop-rounds-1-3.md](docs/history/loop-rounds-1-3.md). The decisions the
items came from are in [docs/decisions.md](docs/decisions.md); what only the owner can
do is in [NEEDS_YOU.md](NEEDS_YOU.md).

## Round seven — the kiro-cli round, closed 2026-08-02

**Both landed.** Items 41 and 42, spec'd and executed the same day from decisions.md
"kiro-cli's 20-second wall, the six-character marker, and the cut bubble". Suite **1050 →
1067**, every gate green, [selfdrive] 64/64 on the one item that needed it. Commits
`40a3660`, `1273920`.

- **41, the wall and the slot.** One measurement earned two fields on one dataclass. `Cli`
  entries carry `timeout_sec` — a **floor** under the wait rather than a replacement for it,
  so `--cli-timeout` still means what §8 says it means and a lowered global cannot re-create
  the incident on the one CLI measured needing the most time — and kiro-cli ships 60 against
  the 35.8 the decision sized it from. The proof is the incident run on purpose: the same
  call, kiro-cli pinned in the MCP workspace, **answered in 38.9 s**, past the old 20 s wall
  by 18.9. The same entry carries `marker="kiro"`, because 8 characters had the pill drawing
  `ASK` while kiro-cli was the CLI about to answer. Item 15's marker rule has now been
  sharpened by three different names and it still says the same thing: the badge may decline
  to name a CLI, and may never name a different one — an alias is a shorter name for the
  same one, so agreement is computed from the entry rather than from a literal.
- **42, the window.** The instrument disagreed with the decision and the disagreement is the
  entry's most useful part. The top edge was **never** the breach — held at `top + 8` in all
  36 placements, every state, every corner, confirmed against `GetWindowRect` and not just
  Tk. What leaves the desktop is the **bottom**, on the **reply** path: a 4 000-character
  answer sized the window 1 459 px and a 12 000-character artifact 4 179 px on a 672 px
  screen, putting the chip row at screen y 1 427 and 4 147. Item 37's own Evidence line had
  predicted it in one sentence and nobody had measured it. `_render` fits the height to the
  work area before anything reads it, so the chip row comes inside with it and the position
  clamp stops being a best effort: **12 of 36 outside before, 0 of 36 after**. The reply's
  rendering is untouched and asserted so.

**What waits:** four desk checks in NEEDS_YOU — the workshop turn through kiro-cli now that
39 s is the real cost of an MCP workspace, the marker eyeball again (it says `kiro` now, and
whether a nickname is the right idea at all is the question the alias raises), the bubble
drawn *over* the pill when the pill is dragged to the very top, and the artifact tail that is
now clipped rather than off-screen. And one proposal, **P10**: §8 claimed "the bubble
scrolls" and no path did — the assumption that left the reply probe unbounded. Three shapes
for a reply that genuinely scrolls, and which one is a taste question about what the bubble
is for.

## Round six — the incident round, closed 2026-08-02

**All four landed.** Items 37–40, spec'd and executed the same day from decisions.md's
long-draft and npm-shim entries plus NEEDS_YOU's kiro-cli verification. Suite **979 →
1050**, every gate green, [selfdrive] 64/64 on both items that needed it. Commits
`4fa12b2`, `1d20961`, `094f42e`, `26e2b43`.

- **37, the bubble.** The whole draft was measured and laid out on every partial, so a
  50 000-character dictation cost **476.7 ms a frame** and sized the window **15 153 px
  tall in a 672 px work area** — the Send chip twenty screens below the display. Only the
  tail is laid out now, under a cap, with `… N earlier lines` above it: **4.3 ms and
  414 px**. Flat from 10k on, and a 1k draft is untouched because it still fits. No
  scrollback, deliberately — scrolling back would have to lay out what it scrolls to.
- **38, the exits.** By the time the stall had killed the mic, every spoken rescue needed a
  decoder that needed the mic, and the one thing that worked had been announced once, in a
  console. One note now names the living exits with the combo that actually registered —
  never on an empty draft, once per incident — and **Copy draft** joins the top of the menu:
  no model, no decode, no target window, and it asks the session for nothing at all.
  The decision's second trigger had to be re-derived: the idle unload refuses to run under
  a held draft, so hanging the note off it would have been a line that never fires. It
  reads the state instead.
- **39, the shim.** A `.cmd` launcher truncates every multi-line prompt at the first
  newline, and the CLI then **exits 0 and answers fluently about nothing**. Refused before
  a process starts, with the cure in the message; the repair ships as `stdin_ok`, off on
  every entry, because turning it on is a measurement. A test that pinned "a shim starts"
  now pins "a shim is refused", and the truncation itself stays measured — a claim about
  another program becomes folklore the day it stops being checked.
- **40, kiro-cli.** Wired from the verification, found by PATH *and* an AppData probe —
  which was not insurance: `which` returned `None` in this session while the probe path
  answered. Its furniture is stripped by a cleaner keyed to that one name. One live refine
  through Flow's own path came back in 2.7 s with the answer alone.

**What waits:** three desk checks in NEEDS_YOU — the long draft run on purpose, the shim
refusal read on a machine that has one, and the marker eyeball now that a verified CLI
overflows the slot. And one thing that is not a desk check: **Rule 2's selfdrive tripwire
fired.** `spoken: 'capitalize sameer'` is the same check that flaked on 2026-08-01, so two
sightings in two different runs makes it a quarantine-or-fix entry rather than more noise.
Both rerun green; the load question the decision told us to ask first is answered (yes,
this run followed two full suites back to back).

## Round five — the Lite round, closed 2026-08-02

**All three landed.** Items 33, 34 and 35, spec'd and executed the same day from
decisions.md "Flow Lite: a cross-platform clipboard-out mode". Suite **890 → 940**, every
gate green, [selfdrive] 64/64 on the one item that needed it. Commits `8481bc2`,
`13f1b1f`, `683e0f5`.

- **33, the definition first.** product.md gained an Environments paragraph and a one-page
  Lite section whose fence — features land in full Flow first, and reach Lite only if they
  survive without hands — is asserted by *direction* rather than by keyword, because a
  reversed fence contains every word a grep would look for. Six mutations, six caught.
- **34, the body.** `--lite`, automatic off Windows. The rule that made it testable here:
  the platform decides what can be imported, `lite` decides what happens — so `--lite` on
  Windows is the same code a Mac runs, and it was run. Send copies through Tk's clipboard,
  verified against a Win32 read-back; the spoken enter-variant collapses into the plain one
  and says so, because refusing it would make a lost word the working case.
- **35, the adapter.** `verified=False` means detection only. `opencode` looked verified —
  exit 0, answer alone on stdout — and is inert, because the *multi-line* prompt this
  module actually sends came back answering a question it never received, on an npm `.cmd`
  shim that truncates at the newline. `kiro` is not a candidate: it is an IDE launcher.

**What waits:** three CLI verifications and the macOS pill check at the desk, the macOS
Lite number the port decision needs, and one defect found out of scope — the same `.cmd`
shim breaks codex and claude on the install both of them document. All in NEEDS_YOU.md.

The entries are below and move to the history file when the next round opens.

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
  The split was superseded the same evening: this repo IS the public repo, and the
  workflow runs right here on tag push)

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
- Status: **superseded, never started** — the split-repo decision was reversed the
  same evening (decisions.md "Distribution, final"): the repo goes public in place,
  so there is no snapshot to publish and no second remote. Kept as the record of a
  spec that was right for a decision that did not survive the hour. Do not execute.

### 30. Help in the menu — a sheet generated from what *this* machine actually does
Owner-decided 2026-08-01 (decisions.md "First public feedback"), the evening of the
release: nothing in-app names a single command, or the hotkey that arms the mic. The
answer is a menu section, and the file behind it is **generated on every open** rather
than shipped — because every question worth answering here is machine-specific.
`ctrl+alt+space` is the *first* alternative in `DEFAULT_BINDINGS`, not necessarily the one
that registered (it was already taken on this machine, which is why the fallback list
exists), and the trigger word is whatever `profile.json` says, not what `edits.py` ships.
A static sheet would be right about a machine nobody is sitting at.
- Files: new `flow/help.py`, new `tests/test_help.py`, `flow/ui.py`, `flow/session.py`
  (a read-only `workspace` property — the sheet has to name the workshop the session is
  actually asking from, and `--cwd` never reaches the profile), `flow/edits.py`
  (`TAKE_VERBS` lifted out of `_TAKE_REPLY` so the sheet reads the grammar rather than
  restating it).
- Two entries, under **Help ▸** — item 31 builds the submenu, this builds what hangs off
  it:
  - **Commands & shortcuts** writes `<settings folder>/commands.txt` and opens it with
    `os.startfile`, which is the whole implementation `Open settings folder` already uses
    (R16 stays at three dependencies, and there is no viewer to maintain).
  - **Open the guide** opens `https://github.com/samartomar/flow#readme`, same call.
- What the sheet carries, each item for a reason: the hotkey combos from
  `hotkeys.chosen` — **what registered**, with any action in `hotkeys.failed` named as
  unavailable rather than silently missing; the two trigger words currently configured;
  one example per command family; the take-reply verbs; and the workshop line. Its first
  line says it is overwritten on every open — a file sitting in the settings folder that
  looks editable and is not is a trap, and this one is beside `lexicon.txt`, which *is*.
- Instrument first, in `tests/test_help.py`, against the text function with no Tk:
  1. Hotkeys that chose `ctrl+shift+space` render `ctrl+shift+space`, and
     `ctrl+alt+space` appears **nowhere** in the sheet. This is the defect the item
     exists to prevent, and the one a shipped file would ship with.
  2. A profile storing `goose` renders `goose` / `enter goose`, and `boom` appears
     nowhere.
  3. Every example in the sheet is fed to `plan()` and asserted to come back as the
     family it is filed under. A help file that documents a command the router does not
     have is worse than no help file — it is the product lying to the person who went
     looking.
  4. `hotkeys=None` (`--no-hotkeys`) and a non-empty `failed` list each render a
     sentence, not a blank section and not a traceback.
- Acceptance: suite green. The unit layer proves the text; it cannot prove
  `os.startfile` opened anything, so the eyeball is a NEEDS_YOU line per Rule 7 and the
  item is `done (desk check pending)`.
- Doc sync: §9's table gains the `commands.txt` row (generated, overwritten, never read
  back), and the no-settings-dialog paragraph gains the Help sentence.
- Evidence: the case for generating it, measured on this machine at the real `Hotkeys`
  object — `chosen` reads `toggle: ctrl+shift+space`, while `DEFAULT_BINDINGS`' first
  alternative for `toggle` is `ctrl+alt+space` (owned by another app here). A shipped
  sheet would have named a key that cannot arm the mic. The instrument was shown able to
  reject before it was trusted: an invented `scrub the header` filed as `local/delete`
  fails the routing leg, a leaked `ctrl+alt+space` fails the defaults leg, and a `boom`
  surviving a rename fails the trigger leg. Suite **814 → 839**, OK, 16.2 s. Commit
  `f925c81`.
- Status: **done.** The pending desk check — `os.startfile` opening the written file —
  was never performed and never will be: item 32 deleted that path. Recorded rather than
  ticked, because "the check passed" and "the thing it checked is gone" are different
  outcomes and only one of them is evidence.

### 31. Submenus, and a trigger word that can be changed without an editor
Owner-decided 2026-08-01 (decisions.md "First public feedback"). The first public ask was
to re-word the send trigger ("goose" / "enter goose"), and item 22 shipped it as
`profile.json` fields — which the owner has said they will not hand-edit. Three shapes
were argued and the **preset submenu** won because it keeps two standing decisions
intact: no settings dialog (§9, four challenges survived), and no word ships until it has
been measured. Free text was rejected for breaching both — free text cannot be
pre-measured — and speak-to-set for writing config through the accented decoder this
product exists to work around.
- Files: `flow/ui.py`, `flow/edits.py` (the preset list belongs beside `SEND_WORD`,
  which is the constant it makes choosable), `tests/test_triggers.py`, new
  `tests/test_menu.py`, `tests/test_offers.py` (its `FakeMenu` gains
  `add_radiobutton`, and its build patches `tk.StringVar` — the trigger submenu is built
  on every open, so the existing menu tests go through it).
- **The menu, reorganized.** Top level keeps what is one tap today and stays one tap:
  Send, the mode toggle, the correction offers, Clear draft, Quit. Underneath:
  **Settings ▸** takes Trigger word, Agent CLI, Voice, Mute/Speak replies, the auto-ask
  toggle, Never offer, and Open settings folder; **Help ▸** takes item 30's two entries.
  *"Was a command" is deliberately not moved and not added*: the decision lists it among
  the one-tap essentials, and it is a chip on the bubble rather than a menu item — it is
  already one tap, and a duplicate in the menu would be a second control for one action.
- **Settings ▸ Trigger word ▸** is a radio list of the presets, the current word checked.
  A tap stores it through the same path item 22's fields use — `profile.send_word`,
  `profile.send_enter_word`, `profile.save()` — and the bubble echoes what was stored, so
  the change is on screen and not only in JSON. The enter-variant is **derived, always**,
  in the safe order (`enter <word>`), including for a word that was already current: one
  rule with no special case, and the note says what it wrote. A word set by hand in
  `profile.json` that is not in the list is shown at the top, checked, so the menu never
  opens with nothing selected. No free-text entry anywhere; `profile.json` stays the path
  for a fully custom word, and item 30's sheet shows whatever is current either way.
  With `--no-profile` there is nothing to store into, so the submenu is absent rather
  than inert.
- **Instrument first, and the gate is the item.** A preset is admitted only by passing
  the discipline item 22's word passed, and `tests/test_triggers.py` asserts it of
  **every shipped preset**, so no word can be added later without paying the same price:
  1. whole utterance against the 580 real EdAcc references, the word *and* its
     enter-variant: **0 hits**;
  2. `command_bench`'s adversarial set with that preset installed as the trigger:
     **≤ 5/20**, the shipped number;
  3. `command_bench`'s recall classes with it installed: **100%**, all six classes.
     Legs 2 and 3 are what catch a preset shadowing the grammar — a trigger is matched
     ahead of every pattern in `plan()`, so a word that is also a command word eats it.
  4. And a fourth leg, added because the first three were measured to have no teeth on
     this question: **the word, said alone, must mean nothing to the grammar with the
     triggers removed**. Legs 1–3 pass "undo" — its corpus hits are 0, and
     `command_bench`'s recall cases are whole commands like "delete Tuesday", never a
     bare verb — while making "undo" a trigger would silently take undo away.
  The instrument must be shown able to reject, per Rule 1: the same four legs are run
  against words that should fail, and the failures are recorded in Evidence.
- Acceptance: suite green; every shipped preset passes all four legs; the menu tests
  pin the top-level/submenu split and the store-and-echo path.
- [selfdrive] is **not** required by the storing path — a trigger word is profile data,
  not grammar, and `plan()`'s trigger path is untouched. Run it anyway if any line inside
  `_trigger` or `plan()`'s trigger branch changes.
- Doc sync: §7's "Send, spoken" gains the preset paragraph and the four-leg gate; §9's
  no-settings-dialog paragraph gains the submenu split. README too, unnamed above and
  taken anyway: it told the reader to edit `profile.json` for a setting that is now a
  tap, and item 30 made the app point *at* that README.
- Evidence, the gate run over 20 candidates plus 5 controls (580 real utterances,
  `command_bench`'s 20 adversarial sentences and 180 recall cases each):
  - **Passed all four legs, shipped:** `boom`, `goose`, `tango`, `mango`, `falcon`,
    `rocket`, `banana` — each 0/580 hits, adversarial 5/20 (the shipped number), recall
    180/180, and `append` when said alone with the triggers removed.
  - **Passed, left out to keep the menu a choice:** `pelican`, `zulu`, `kilo`, `jupiter`,
    `otter`, `thunder`, `comet`, `pixel`, `walrus`, `badger`, `cobra`, `domino`,
    `harbour` — same four numbers. `thunder` and `otter` are also the two whose shapes
    (a `θ`, a flap) are worst for the anchor accents.
  - **Failed leg 1** — said alone in the corpus: `yeah` **44/580**, `yes` **12/580**,
    `okay` **10/580**, `no` **2/580**, `right` **1/580**.
  - **Failed leg 4** — already means something: `undo` (0/580 hits, adversarial 5/20,
    recall 180/180 — it passes legs 1–3, which is the entire reason leg 4 was added).
  - `command_bench.py` before and after: **identical bar the identity date**.
  - Suite **839 → 869**, OK, 17.3 s. Commit `4d061d4`.
- Status: **done.** The accent question the corpus gate structurally could not answer is
  now answered at the mic (2026-08-02): all six shipped words decode for this speaker, so
  nothing leaves the tuple and no `lexicon.txt` arrow line is needed. The nested-cascade
  `send_check.py --live` run is still open in NEEDS_YOU.

### 32. The sheet moves into Flow's window, and goose leaves the list
Owner review of items 30 and 31, decided 2026-08-02 (decisions.md "Help review"):
structure and presets approved, two changes. The verdict on the text file was three
words — *"which is not help"* — and it is right on its own terms: Notepad is another
application's chrome over Flow's content, it takes the foreground the app spends 96 call
sites avoiding, and it leaves a file in the settings folder that looks editable beside
one that is. **Presentation moves; the guarantees do not.** Same generated data, same
regeneration on every open, item 30's route-checked test untouched — that test never
looked at the rendering, which is what makes this a safe move rather than a rewrite.
- Files: `flow/help.py`, `flow/ui.py`, `tests/test_help.py`, `docs/architecture.md`,
  `README.md` (it describes the text file to the public, and Help ▸ points at it).
- **Part one, "goose" leaves `SEND_WORD_PRESETS`** → `boom, tango, mango, falcon,
  rocket, banana`. Taste, not measurement: its gate numbers stand unchanged in item 31's
  Evidence line and nothing is re-run. The thirteen passed-but-unshipped words stay
  swappable on the same basis. The tests that enumerate the shipped list follow; the
  four-leg gate itself is untouched, because it runs over the tuple rather than over a
  list written in a test.
- **Part two, the window.** `help.rows()` replaces `help.sheet()`: the same content as
  structured `(kind, left, right)` rows — section heads, two-column pairs, full-width
  notes — because a layout laid out with spaces is a layout for a monospace editor, and
  this one is drawn. `write()`, `open_file()` and `FILENAME` are removed rather than
  kept: a second surface is a second thing to keep true.
- **Read-only and mouse-only, and that is a constraint rather than a simplification.**
  The window carries `WS_EX_NOACTIVATE` like every other Flow window, so it cannot take
  the keyboard and must not be given anything that needs one. Scroll wheel and a Close
  chip in the bubble's idiom are the whole interaction.
  - **Named risk, because it is the same class of defect this file already carries
    twice** (the `Esc` binding that could never fire once the windows stopped taking
    focus; the popup menu whose modal loop received nothing until it borrowed the
    foreground): on Windows `WM_MOUSEWHEEL` is posted to the **focused** window, and this
    window is never focused. It works only via *Scroll inactive windows when I hover over
    them* — on by default in Windows 11, and a setting a user can switch off. So the
    wheel ships as decided **and** the body scrolls by press-and-drag, which is delivered
    by hit-test and cannot depend on focus. A footer hint names the drag when, and only
    when, the content overflows. Whether the wheel actually arrives is a desk check.
- Instrument first, and the before is already pinned: today's tap calls `os.startfile`
  with a path ending `commands.txt` and leaves the file behind — 3/3 green against the
  tree as it stands. The after inverts exactly that: `os.startfile` is **not** called for
  the sheet, no file is written, the window exists carrying the generated content, a
  hotkey line matches the combo that actually registered, a renamed trigger word appears
  in the rendered rows, the Close control closes it, and **"Open the guide" still shells
  out to the README URL** — asserted, so removing one path cannot quietly remove the
  other.
- Also asserted, because the window does not wrap: every row `rows()` can produce fits
  the column budget. The one row carrying user data (the workshop path) is truncated to
  that budget the way `edits.removed_text` truncates, rather than being allowed to run
  off the edge.
- Acceptance: suite green; item 30's `plan()` route check passes untouched; no
  `commands.txt` is written by any test.
- [selfdrive] not required — presentation only, no routing change. Run it if anything
  inside `plan()`'s trigger path moves.
- Doc sync: §9's `commands.txt` row is replaced by the window (it is no longer something
  written to disk, which is what that section is a list of); §7's preset sentence drops
  goose; §11's test count. §1 too, unnamed above: the module count and the surface band
  had never been updated for `help.py` when item 30 added it.
- Evidence:
  - **Before, pinned green against the tree as it stood** (3/3): the tap called
    `os.startfile` with a path ending `commands.txt`, the file was left behind in the
    settings folder, and the guide shelled out to the README URL. **After:** the same
    script errors on the sheet's two checks and still passes on the guide's — the
    inversion, demonstrated rather than asserted.
  - **The real window, on real Tk** (the fake canvas cannot see a bad Tk option):
    `_no_activate` applied and read back **True**, geometry **600×624+340+24** inside a
    measured `SPI_GETWORKAREA` of **1280×672**, **45** text items drawn of 50 rows, one
    wheel notch moved the top row to 3 and grew the canvas to 52 items (the thumb
    appearing), `close()` left it `withdrawn`.
  - **The route check did not change and did not need to** — `COMMANDS` → `plan()`, 17
    examples, all green before and after. That is what makes this a presentation move.
  - **Found while wiring it, and fixed:** `getattr(self, "_help", None)` on a `Pill` is
    not the safe read it looks like — `tk.Misc.__getattr__` forwards an unknown attribute
    to `self.tk`, so on an instance whose `__init__` has not run it recurses until the
    stack ends instead of returning the default. It surfaced as a `RecursionError` in the
    old before-script, which is exactly the kind of thing a pinned before is for.
  - Suite **869 → 890**, OK, 16.0 s. Commit `4eb3482`.
- Status: **done, desk check passed 2026-08-02.** The window reads as one of Flow's, the
  `Close` chip is where a hand goes, it stays put while the user types in another window
  — the confirmation that the `WS_EX_NOACTIVATE` read-back means what it says — and the
  wheel arrives. The drag path stays regardless: the wheel works because the mouse setting
  is on, which is a default rather than a guarantee. Approved on a 1280×672 work area,
  where 22 rows sit below the fold; a display tall enough to show the whole sheet is a
  different thing to look at and has not been.

### 33. product.md learns that Flow has two bodies, and where the fence between them runs
Owner-decided 2026-08-02 (decisions.md "Flow Lite"). product.md is the file that says what
Flow must do and for whom, and today it defines one product on one OS — so a second body
would arrive with nothing above it saying what it is allowed to be. The definition lands
*before* the code, because the load-bearing sentence is a rule about how every later
feature travels: **features land in full Flow first, and reach Lite only if they survive
without hands.** Written down first, it constrains item 34; written down after, it would
only describe it.
- Files: `docs/product.md`, new `tests/test_lite.py` (item 34 adds the behaviour classes
  to the same module — the definition and the build then fail beside each other, which is
  the reason for one module rather than two).
- What product.md gains, and nothing beyond it:
  1. **Environments**, a paragraph under "The user": the brain and the ear are portable
     Python with cross-platform wheels; the hands are 96 Win32 call sites in
     `inject`/`hotkey`/`ui`. The design-center user's own environments include macOS,
     which is what makes a portable body worth shipping. That sentence is the whole
     justification and the paragraph stops there — the decision entry is the boundary of
     what this repo knows about anybody.
  2. **Flow Lite**, a one-page section. What it **is**: the brain (routing, the
     correction loop, the workshop, the thread), the ear (the same two decoder tiers, the
     same lexicon, the same calibrated profile), and the clipboard as the way out. What it
     deliberately **is not**, four items stated as exclusions rather than as "not yet": no
     injection, no global hotkeys, no auto-paste, no target-window awareness — and
     therefore no OS permission beyond the microphone, which is the thing the exclusions
     buy.
  3. The fence in its own sentence, and what it costs: the hands-free magic is the price,
     and **the clipboard hop is the measurement** — sustained Lite use is what decides
     whether a native macOS body is ever funded.
- The P-table is **not** renumbered and gains no row. P1–P9 are requirements on Flow; Lite
  is a body that meets a subset of them, and a "P10: also works without hands" would turn
  the fence into a requirement instead of a rule about how requirements travel. Instead
  the Lite section names what it cannot meet, exactly: **P7 in full** (Flow does not do the
  pasting, so it cannot promise a multi-line draft arrives unexecuted — that becomes the
  terminal's business and the user's), and **the last step of P9's acceptance loop** (the
  draft is copied, not delivered into the terminal where the work is).
- Instrument first, the idiom `test_workshop.py`'s `TestP9SaysWhatItNowIs` already models —
  assertions against the file, red before the paragraphs exist: an Environments heading
  exists; the Lite section names all four exclusions; the fence sentence exists *and reads
  in the load-bearing direction* (full Flow first, Lite second — a test that only greps for
  both names would pass on a sentence saying the opposite); P7 and P9 are named as the two
  it cannot meet; and the Non-goals list is unchanged, because Lite adds no non-goal.
  Shown able to reject, per Rule 1: a section missing any one exclusion fails, and a
  reversed fence fails.
- Acceptance: suite green; each of the four exclusions and the fence asserted by name.
- Doc sync: none. `architecture.md` describes the build and no build exists yet; item 34
  is what syncs it. Named here so its absence is a decision rather than an oversight.
- Evidence:
  - **Before:** 6 of the 8 checks red against the tree as it stood — no Environments
    section, no Lite section, no fence sentence, no "clipboard hop". The two that were
    green (the P-table's nine rows, the five non-goals) are regression guards rather than
    defects, and stayed green.
  - **Shown able to reject**, six plausible ways the definition could go wrong, each
    caught by exactly one check and nothing else: dropping the auto-paste exclusion →
    `…names_every_one_of_the_four_exclusions`; reversing the fence to "land in Lite first"
    → `…reads_in_the_load_bearing_direction`; renaming the Environments heading →
    `…which_half_is_portable`; adding a P10 row → `…gains_no_row`; softening "P7" and "P9"
    to "one requirement" → `…the_two_requirements_it_cannot_meet`; rewording "clipboard
    hop" → `…named_as_the_measurement`.
  - The fence check reads the *order* of "full Flow" and "Lite" inside the sentence, not
    their presence: a reversed fence contains every word a grep would look for.
  - Suite **890 → 898**, OK, 15.8 s. Commit `8481bc2`.
- Status: **done**

### 34. Lite — the same brain, and the clipboard instead of hands
Owner-decided 2026-08-02 (decisions.md "Flow Lite"). Item 27's platform guard refuses on
non-Windows; this relaxes it to **run Lite, and say so**. The central design rule, and the
reason the whole thing is testable on the machine it is built on: **the platform decides
what can be *imported*; `lite` decides what *happens*.** `sys.platform` is read once, at
startup, to pick the mode — every branch after that reads a `lite` flag. So `--lite` on
Windows runs the same code a Mac runs, which makes it a live test bed rather than a
faked one, and makes every Lite path a unit test with no desktop.
- Files: `flow/__main__.py`, `flow/ui.py`, `flow/help.py`, `tests/test_lite.py` (item 33's
  module, gaining the behaviour classes), `tests/test_main.py` (the refusal it pins is the
  thing being replaced — that class is the "before"), `tests/test_help.py`.
- **The flag and the mode.** `--lite`, plus `lite = args.lite or sys.platform != "win32"`.
  The guard moves below argparse, which it could not be while it was a refusal: being told
  the flag is wrong when the platform is the problem was the right answer only while the
  platform *was* the problem. Startup says which body is running and why —
  `Flow Lite on darwin: Send copies the draft, and you paste it` — in ASCII, like every
  other startup line, for the reason `say()` documents.
- **What Lite does not build.** No `Hotkeys` (arming is the click on the pill that already
  exists, and `--arm` still works); no `paste` import and so no `on_send` closure; the
  three Win32 imports in `main()` stay under `if not lite:`. `flow/inject.py` is never
  imported in Lite and is not made portable — 470 lines of Win32 with no Lite meaning.
- **What `ui.py` needs to import at all off-Windows**, and only that: the module-level
  `ctypes.WinDLL("user32")` block and `from .inject import foreground_hwnd, owned_by_flow,
  take_warnings` go under `if sys.platform == "win32":`, with stubs otherwise
  (`foreground_hwnd() -> 0`, `owned_by_flow() -> False`, `take_warnings() -> []`). The
  Windows branch is byte-identical to what is there today — that is what "full-mode paths
  provably unchanged" means here. Two things need no change and the item must not pretend
  otherwise: `_work_area` and `_dpi_aware` already catch `AttributeError`, which is exactly
  what `ctypes.windll` raises where there is no `windll`, and both already fall back.
- **The Lite branches in the pill**, each because it is observable:
  - `-transparentcolor` and `-toolwindow` are Windows-only Tk attributes; in Lite they are
    not set, and the window and canvas take `SHELL` rather than the keyed `TRANSPARENT` —
    the magenta is only invisible *because* something keys it out.
  - `_track_target` returns immediately: no target-window awareness, and reading `lite`
    rather than relying on the stub is what makes `--lite` on Windows honest.
  - `_menu`'s foreground borrow, and `Bubble._edit`'s foreground dance plus its
    `owned_by_flow` verification, are skipped: a Lite window is not in the
    `WS_EX_NOACTIVATE` chain (`_no_activate` returns False off-Windows), so it can hold the
    keyboard the ordinary way, and the verification has nothing to verify with — left in,
    it closes the editor and reports that "Windows kept the focus" on a machine with no
    Windows.
  - `_open_settings` and `open_guide` are `os.startfile`, which does not exist off-Windows.
    `help.py` grows one `open_path()` that knows how this OS opens a thing — `os.startfile`
    on Windows, `open` on darwin, `xdg-open` elsewhere, stdlib `subprocess` only (R16
    holds at three dependencies).
- **Send, in Lite.** `Pill._send` copies through Tk's own clipboard —
  `clipboard_clear()` / `clipboard_append()` / `update()`, OS-agnostic and already a
  dependency — then shows the sent card as dictate mode does (R5: the words stay
  recoverable) with the note **"copied — paste where you need it"**.
- **The question the fence asks, answered here and tested: what do the spoken send
  triggers mean in Lite?** The plain trigger performs the copy. The enter-variant
  *collapses into it* — it copies too, and the note says what did not happen: "copied —
  Enter is yours to press". The alternative (make it a refusal) was rejected on
  `edits.enter_word`'s own argument: a decode that loses a word from "enter tango" yields
  "tango", so a refusing enter-variant would make the *degraded* decode the working case
  and the fuller utterance the broken one. That is the inversion the word order exists to
  prevent, and it must not be reintroduced one layer up.
- **Absent, not disabled-looking.** The enter-variant leaves the surfaces that offer it:
  `_set_trigger`'s note drops "or 'enter X' to submit", and `help.rows()` drops the
  enter row and the hotkeys section. Target naming goes the same way — "paste the draft
  into the window you were in" and the startup mode line's "Send pastes into the focused
  window" are about a window Lite does not know exists. The **grammar keeps both
  triggers**: somebody who learned "enter tango" in full Flow will say it, and the answer
  to saying it is the collapse above, not silence. Offered nowhere, handled anyway.
- Instrument first, all of it on Windows with `sys.platform` faked, and the before is
  already pinned: `tests/test_main.py`'s `TestTheNonWindowsGuard` is green today against
  a refusal with exit code 2. The after inverts exactly that class — darwin returns 0 into
  a Lite launch, the sentence names Lite and the platform, and `--lite` on win32 reaches
  the same mode. Then, against a `Pill` built the way `test_indicator.py` builds one:
  a Lite send copies and does not call `on_send`; an enter-variant send copies and notes
  the collapse; `paste_target` stays `None` after a frame that would have set it;
  `help.rows()` in Lite carries neither the enter word nor a hotkey row, and carries the
  plain word; `open_path` dispatches on the faked platform. And the proof that full mode
  did not move: `TestItDoesNotFireHere` plus the other 889 tests, untouched.
- Acceptance: suite green, with the existing 890 unchanged in behaviour; `uv run flow
  --lite` launches **on this machine** and its startup lines say Lite, no hotkey lines
  appear, and a Send puts the draft on the real clipboard. What Windows cannot prove — that
  Tk draws this pill on macOS at all — is a NEEDS_YOU desk check per Rule 7, and the item
  is `done (macOS check pending)`.
- [selfdrive] not required: no routing change and nothing about what `asr`/`text` returns.
  `edits.plan()` is untouched — Lite reads the same plan and does something else with it.
  Run it if any line inside `plan()`'s trigger branch moves.
- Doc sync: §1's band diagram and the "Eighteen modules" line (`ui.py` stops being
  unconditionally Win32); §7 "Send" gains a Lite subsection stating the copy and the
  collapse; §10's invariant about the foreground/`resolve()` refusal gains its Lite
  reading (there is no target, so there is nothing to refuse); §11's test count.
- Evidence:
  - **Before, and it is the class this item inverts:** `test_main.TestTheNonWindowsGuard`
    was green against a refusal — darwin got one sentence and exit **2**, and a bad flag
    got the platform message instead of argparse's. **After:** darwin returns **0**, says
    `Flow Lite on darwin`, hands `Pill` `lite=True`, `hotkeys=None` and `on_send=None`,
    and `--not-a-flag` is now simply a bad flag (`SystemExit 2`, "unrecognized
    arguments"). 21 new behaviour checks were red before the change.
  - **The real clipboard, measured rather than asserted** — the unit layer can only see
    that `clipboard_append` was called. A real `tk.Tk`, `Pill._copy`, then
    `inject.get_clipboard_text` (a Win32 read, a different implementation from the one
    that wrote it): **the draft comes back verbatim**. A refusing clipboard returns
    `could not copy: clipboard busy` and the words stay on the sent card.
  - **`uv run flow --lite` on this machine**, which is the whole reason `lite` is a flag
    and not a platform check: `Flow Lite on win32: …`, `mode: DICTATE - Send copies the
    draft, and you paste it`, and **zero** `hotkey` lines. The full body launched
    immediately after is unmoved — `mode: DICTATE - Send pastes into the focused window`
    and all five combos registered (`toggle ctrl+shift+space`, `send ctrl+alt+enter`,
    `cancel ctrl+alt+esc`, `mode ctrl+alt+M`, `quit ctrl+alt+Q`).
  - **Found while wiring it, and it is the same defect item 32 recorded one layer along:**
    reading a new attribute off a partially-built pill is not safe, and reading one off a
    `Mock` parent is worse — `tk.Misc.__getattr__` forwards to `self.tk`, so `self.lite`
    recursed on 42 `__new__`-built fixtures and came back *truthy* on the editor's Mock
    pill, silently running the Lite branch in a test about the full body. Class attributes
    on `Pill` and `Bubble` fix both, and no existing test needed changing.
  - **Also measured, and left alone:** Tk normalises line endings on write, so a string
    that is already CRLF comes back `\r\r\n`. Flow's own drafts are LF-only, so the copy
    is correct — recorded in §7 because it is a trap for the next thing that copies.
  - Suite **898 → 926**, OK, 16.2 s. Commit `13f1b1f`.
- Status: **done (macOS check pending)** — every Lite path is unit-tested and `--lite`
  runs here, but no Windows machine can prove Tk draws this pill on macOS. NEEDS_YOU
  carries it.

### 35. The adapter grows past two names — and never guesses a shape
Owner-decided 2026-08-02 (decisions.md "Flow Lite"). `CANDIDATES` is a two-entry tuple
behind one seam (`Cli`, `available()`, `_invoke_any`), and the seam is already right; what
is missing is entries, and the discipline that keeps a wrong entry out. **An invocation
shape is never asserted from memory.** An entry whose shape has not been run on a machine
that has the CLI ships **inert**: detection may find it and say so, and nothing invokes it.
- Files: `flow/refine.py`, `flow/__main__.py`, `tests/test_refine.py`,
  `tests/test_indicator.py`, `tests/test_converse.py`, `tests/test_main.py`.
- **The seam.** `Cli` gains `verified: bool = True`. `available()` keeps its meaning —
  what may be *invoked* — and so returns verified entries on PATH only, leaving every
  existing caller (`_invoke_any`, `_provider`, the pill's marker, the menu's picker)
  correct without knowing the field exists. A new `detected()` returns everything found
  including the unverified, which is the only thing that may name them.
- **What ships, and in which state:**
  - `opencode` — **verified live on this machine**, so it ships invocable:
    `("opencode", "run")`, prompt appended as the final argument, which is the shape the
    existing `Cli` already describes.
  - `copilot`, `gemini` — **inert**: `verified=False`, and `argv = (name,)`, carrying the
    executable name that detection needs and *no shape at all*. A guessed argv sitting in
    the tuple unused is still a guess somebody will later trust.
  - `kiro` — **not an entry, and the reason is recorded in the code**: verified live here,
    `kiro` on PATH is the IDE launcher (a VS Code fork; `--help` offers `--diff`, `--goto`,
    `--wait` and no headless prompt mode). Detecting it and saying "found kiro, not yet
    verified" would be false — it *is* verified, as not being an agent CLI — and invoking
    it would open an editor window instead of answering.
- **Naming and the pin must handle the new names.** `--cli gemini` currently resolves via
  `named()` and is then rejected as "not on PATH", which is a lie when it *is* on PATH:
  the two cases separate, and the unverified one says what to do about it. Startup prints
  one line per detected-unverified CLI. The pill's marker already refuses a name wider than
  `MARKER_MAX` = 6 and falls back to `ASK`; that rule is not changed, it is *pinned against
  the real names* — `gemini` (6) renders, `copilot` (7) and `opencode` (8) fall back — in
  place of `test_indicator.py`'s invented `gemini-cli`. `test_converse.py`'s
  "the marker and the note cannot disagree" runs over the new names too.
- Instrument first: red before the change, and the ones that matter are the negatives —
  `available()` never yields an unverified entry however it is arranged; `_invoke_any` with
  only unverified CLIs on PATH returns the no-CLI reason and starts **no process** (asserted
  on `Popen` never being called, not on the return value); every unverified entry has
  `argv == (name,)`, which is the rule that makes "no shape from memory" mechanical rather
  than a promise; `named("kiro")` is `None`.
- **Live verification is the gate for `verified=True`, and its evidence goes in this
  item's Evidence line**: one prompt in, text on stdout, exit code checked, banner on
  stderr — the stream discipline `refine.py`'s docstring already requires. Anything not run
  that way stays inert and gets a NEEDS_YOU entry saying exactly what to run and where to
  write the answer.
- Acceptance: suite green; `refine CLI:` at startup still names codex first on this
  machine; the two inert entries are named at startup and invoked by nothing.
- [selfdrive] **required** — `_invoke_any` and `available()` are what every CLI round trip
  goes through, and selfdrive is the only check that runs a real one.
- Doc sync: §8's `refine.CANDIDATES` row (the order, the new entries, and what `verified`
  means); §1's "What leaves the machine" paragraph, which names codex and claude as the
  cloud-backed pair; the Verification section's provenance line, which records the CLI
  versions this machine measured with. **Taken beyond the list**, because the verification
  attempt produced a rule worth writing down: a new "Verifying a candidate" subsection
  under Verification, holding the bar and the measurement that raised it.
- **Deviation, recorded rather than quiet:** `tests/test_main.py` was not in the file list
  and is in the commit. The pin's three refusals live in `__main__`, and asserting them
  from `test_refine.py` would mean driving the entry point from the adapter's test module.
- Evidence:
  - **Before:** the 13 new checks run against the pre-change tree (`git show HEAD:` into
    place, both files restored after) — **8 red, 5 green**. The five that already held are
    negatives that were true by absence, and they stay as regression guards: `available()`
    offering no inert entry, and `kiro` not being a candidate.
  - **`kiro`: verified live, and the answer is that it is not an adapter candidate.**
    `kiro --help` on this machine is the IDE launcher — Kiro 1.0.242, a VS Code fork
    offering `--diff`, `--goto`, `--wait`, `--new-window`, and no headless prompt mode;
    `bin/` holds only `kiro` and `kiro.cmd` beside `Kiro.exe` and the chromium DLLs.
    Adding it would open an editor window instead of answering. Not an entry, and the
    reason is in the code rather than here.
  - **`opencode`: verified live, and the verification is what stopped it shipping.**
    Through Flow's own `_invoke`, not beside it: `opencode run "Reply with exactly: PONG"`
    → **exit 0, 8.2 s, stdout `'PONG\n'`, `_clean` → `'PONG'`, banner on stderr** — every
    box this module asks for. Then the same path with a *multi-line* prompt, which is the
    only kind `refine.py` sends: `"Repeat the SECRET below verbatim…\n\nSECRET:\n
    marmalade-42"` → **`'No SECRET was provided.'`**, exit 0, no error anywhere.
  - **The cause, measured rather than inferred:** `shutil.which("opencode")` returns
    `opencode.CMD` (an `npm -g` shim) while codex and claude are WinGet `.EXE`s. Against a
    batch shim of the same shape, `['line one']` arrived where
    `['line one\nline two\nline three']` was sent; the identical argument through a real
    executable arrived whole. So what was measured is the **install**, not opencode's
    contract — and that is precisely the case `verified` exists for. Entry stays inert,
    with the measurement in the code and one command in NEEDS_YOU that settles it.
  - **Out of scope and worse than the item:** the same shim path breaks **codex and
    claude** on any machine where they were installed the way both CLIs document. Written
    to NEEDS_YOU with the repro and the three candidate fixes, not patched here (Rule 4).
  - **`copilot` and `gemini`: left inert, neither on this machine's PATH.** Each has a
    NEEDS_YOU entry naming the four commands that settle it — including the multi-line leg,
    which is now in the list *because* opencode passed without it.
  - **The marker and the note could only agree by accident.** Every shipped name fitted
    the 6-character slot until now, so `_provider() == _marker()` was equality *and*
    agreement at once; `opencode` at 8 breaks the tie and the test now states the real
    rule — the marker may decline to name a CLI (`ASK` is the mode), never name a
    different one.
  - Startup on this machine, unchanged where it should be and honest where it changed:
    `refine CLI: codex` / `(falls back to claude if it fails)` /
    `(found opencode, not yet verified - see NEEDS_YOU)`.
  - Suite **926 → 940**, OK, 15.8 s. [selfdrive] **64/64**, including the live codex
    converse round trip. Commit `683e0f5`.
- Status: **done** — with three verifications at the desk (copilot, gemini, opencode on a
  non-shim install) and the `.cmd` defect in NEEDS_YOU.

### 36. The ground is named as the question leaves, and switchable with a tap
Owner-decided 2026-08-02 (decisions.md "Workspace grounding: proven by a misfire").
The first real workshop session asked about one project while grounded in another —
the flag set at the command line and forgotten. The grounding itself worked (the answer
was concrete enough to be wrong about the wrong project); what failed is the pair of
mitigations the original decision priced the risk with: startup line and mode-switch
note are transient signals for persistent state, the same lesson already paid for twice
(the converse marker, the editor's countdown hold). Two fixes, one item, and one nailed
behaviour so this spec cannot guess: **egress names the ground, a tap switches it, and
a switch starts a fresh conversation.**
- Files: `flow/profile.py`, `flow/session.py`, `flow/ui.py`, `flow/__main__.py`,
  `tests/test_profile.py`, `tests/test_workshop.py`, `tests/test_menu.py`,
  `docs/architecture.md`.
- **Egress naming.** `_start_ask`'s note becomes `asking codex · acme…` — the
  workspace **leaf** name, bounded (`help._fit`'s idiom; the note is glanced at, not
  read), never the full path. The countdown's final state carries it too: the
  `_pump_auto_ask` firing note becomes `no more speech - asking · acme`, because
  auto-ask is the one path where words leave with no press. **No workspace set → both
  notes stay byte-for-byte what they are today** — a `· (not set)` suffix is noise
  nobody asked for, and the absence of a name is itself legible.
- **Settings ▸ Workspace ▸** — a recents submenu, radio-checked like the trigger
  presets, `(not set)` included as a real entry, one tap switches. Backed by an
  additive `workspaces` list in the profile (most recent first, `MAX_WORKSPACES = 5`
  — the same modal-stall budget that caps the offers at three and the presets at six),
  fed by every path that arrives via `--cwd` and promoted on every menu tap, deduped
  by `normcase+normpath` so a relaunch cannot grow the list. **No free text anywhere**
  — new paths enter once via the flag, then live in the list; a browse dialog would be
  the settings dialog refused five times. A current workspace missing from the list is
  shown at the top rather than dropped (the hand-set trigger word's rule, same
  reason). No profile, or nothing to offer → no submenu, rather than one that forgets.
- **The switch, nailed by the decision.** `Session.set_workspace(path | None)`:
  switching clears the conversation thread and the note says both things in one line —
  `workshop: acme — new conversation`. A switch to the **same** workspace
  (compared by path identity, not by spelling) is a no-op and clears nothing. A recents
  entry whose folder no longer exists is **shown but marked** in the menu, and tapping
  it refuses with the reason and switches nothing — `resolve_workspace`'s stale-path
  honesty, extended to the menu. A switch while an ask is in flight refuses like
  `send()` does, because the answer would land in a thread about a different project.
  A successful switch persists (`profile.workspace`, saved on the tap like the trigger
  word); the draft is never touched (R5 — the words are the user's, whatever ground
  they stand on).
- Instrument first, each its own check, the before pinned by a script per item 32's
  idiom:
  1. **Today the asking note names only the CLI** — assert `asking codex…` exactly,
     with a workspace set (green today), then invert: `asking codex · <leaf>…`. And
     the guard that holds before *and* after: with no workspace, the note is
     `asking codex…` byte-for-byte.
  2. A `--cwd` launch adds to recents **exactly once** — a second call with the same
     path (and with a case/separator variant of it) moves it to the front rather than
     duplicating it.
  3. The cap holds: a sixth workspace evicts the oldest, and a hand-grown file is
     bounded on load, not just on save.
  4. A tap switches `refine_cwd` for the next ask, and the workshop preamble of that
     ask carries the **new** path (asserted at `_invoke`, the way
     `TestTheQuestionCarriesTheWorkshop` does).
  5. The thread is empty after a switch, and intact after a same-workspace tap.
  6. A stale recents entry is shown and marked in the menu; `set_workspace` on it
     says "no longer exists", keeps the current ground, clears nothing, crashes
     nothing.
- Acceptance: suite green; the before-script's inverted checks now fail for the stated
  reason; the submenu builds through `tests/test_menu.py`'s `FakeMenu` with the radio
  tick on the current workspace.
- [selfdrive] **not required**: naming in notes is not routing, `plan()` and asr text
  handling are untouched. Run it if either moves.
- Doc sync: §8's constants table gains `Profile.MAX_WORKSPACES`; §9's `profile.json`
  row gains `workspaces` and the switch as a save moment; the workshop paragraph
  (§"Converse mode is a prompt workshop") gains egress naming and switch-clears-thread;
  the Settings ▸ paragraph gains the Workspace submenu beside Trigger word.
- Evidence:
  - **Before, pinned by script — 6/6 green on the pre-change tree — then inverted.**
    With a workspace set, the asking note was exactly `asking codex…` and the
    countdown's firing note exactly `no more speech - asking`; `Profile` had no
    `workspaces` and no `note_workspace`, `Session` no `set_workspace`. After the
    change the same script fails 5 of 6 — the notes now read `asking codex · flow…`
    and `no more speech - asking · flow`, and the three seams exist — while the check
    that had to survive still passes: no workspace → `asking codex…` byte-for-byte.
  - **The instrument, red before the build:** 35 new checks across four modules —
    workshop 14/16 red (the two greens are the unchanged-when-unset guards, green by
    design), menu 7/8 red (the green is no-submenu-by-absence), profile 9/9 behind
    the ImportError, main 2/2 red. All green after.
  - **Real Tk caught what the FakeMenu cannot, and it changed the code.** An empty
    radiobutton `-value` is read as *unset* and falls back to the label — measured: a
    row built with `value=""` read back `value='(not set)'` while the var held `""`,
    so with no workspace set the tick would silently never draw. The no-workspace
    row's value is now the literal `(not set)`, the var defaults to it, and the probe
    confirms the tick in both states on real Tk. The same call shape in `_voice_menu`
    ("Engine default", `value=""`) measures `ticked: False` today — out of scope
    (Rule 4), written to NEEDS_YOU with the measurement.
  - **The switch's edges, each its own check:** a same-workspace tap — even respelt,
    `D:/dev/x/` against `D:\dev\x` — is a silent no-op with the thread intact; a
    missing folder refuses with the reason and keeps ground and thread; a switch
    mid-ask refuses the way send() does; the draft survives every switch (R5); a
    failed save is said ("the switch lasts this session only") and the switch stands.
  - **The wiring, at main():** two launches with the same `--cwd` leave exactly one
    recents entry; a launch with no flag and one with a typo'd flag leave none. The
    trace is patched out in that test, so it cannot write the real `~/.flow` (Rule 5).
  - **Deviation, recorded rather than quiet:** `tests/test_main.py` and
    `tests/test_offers.py` are in the commit and not in the Files line. The wiring
    check belongs to the entry point (item 35's precedent, same file, same reason);
    test_offers' menu builder now traverses the new submenu — the exact reason item
    31's spec named test_offers when the trigger submenu appeared — and its session
    mock gains `workspace=None`, the Mock-parent defect class item 34 recorded.
  - Startup smoke on this machine: `--lite --no-profile --cwd D:/dev/flow` prints
    `workshop: D:/dev/flow` and reaches the pill; nothing about the new imports moves
    the full body.
  - Suite **940 → 976**, OK, 17.4 s. [selfdrive] not run: `plan()` and asr text
    handling untouched — naming in notes is not routing.
- Status: **done (desk check pending)** — the misfire that motivated the item, run on
  purpose through the menu, waits at the desk (NEEDS_YOU).

### 37. The bubble stops growing — a cap, a tail that follows, and a bounded layout
Owner-decided 2026-08-02 (decisions.md "The long-draft incident: no draft may disable its
own rescue", fixes 1 and 2). A very long dictation took down five layers in a chain at the
desk, and this item is the first link: `Bubble._render` measures and lays out the **whole**
draft on every partial, so render cost grows with the draft until the UI thread stalls —
and the bubble it sizes grows past the screen, taking the Send chip with it. Two fixes,
one item, because they are the same measurement: cap the height, and stop laying out what
the cap cannot show.
- Files: `flow/ui.py`, new `tests/test_bubble.py`, `docs/architecture.md`.
- **Instrument first, and the decision names the instrument**: render time vs draft size at
  **1k / 10k / 50k characters**, on a real `tk.Tk` with the real canvas — a fake that
  cannot wrap cannot measure wrapping, and the cost being bounded is a cost claim, not a
  layout claim. Before: the curve must *grow* (that is the stall, reproduced). After: flat.
  Both curves go in the Evidence line. The permanent guard is the unit-level half — how
  many characters `_render` hands the canvas for the body — which a `MeasuringCanvas` can
  see and which fails before the change at 10k and 50k.
- **The tail window.** Only a bounded window of the draft's end is laid out per event:
  `BODY_TAIL_CHARS`, sized from the cap (lines that fit × measured characters per line)
  with overshoot, cut at a whitespace boundary so no word is halved. Above it, one muted
  line `… N earlier lines`, where N is the elided head's line count — explicit newlines
  plus wraps estimated from a **measured** characters-per-line constant, recorded with the
  measurement beside it. A `str.count` over 50k is microseconds; it is Tk's text layout
  that is the cost, and that is what the window bounds.
- **The cap and the pinned chips.** `BODY_MAX_H` bounds the body slot, so `self._h` stops
  being a function of the draft; the chip row keeps drawing from `self._h` and therefore
  stays on screen at any draft size. The editor's box height falls out of the same probe
  and needs no separate rule — it is measured from the window, and `tk.Text` scrolls
  itself.
- **Tail-following, and no scrollback — stated rather than assumed.** The body is a
  viewport on the end of the draft: an append moves the text up and the newest words are
  visible with no manual scroll, which is what "like a terminal" means for an append-only
  stream. A user-driven scrollback is deliberately *not* added: it would have to lay out
  what it scrolls to, which re-grows the cost this item exists to bound, and the whole
  draft is already reachable through Edit — and, from item 38, through Copy draft.
- **The artifact-reply path is not touched.** `self._reply` keeps its full-text probe and
  its `ASK_ARTIFACT_MAX_CHARS` character bound; a test asserts a long reply renders exactly
  as it does today, so "the draft path joins the artifact path" cannot quietly become
  "both paths changed".
- Instrument first, each its own check in `tests/test_bubble.py`:
  1. The body text handed to the canvas is bounded — 1k renders whole, 10k and 50k render
     a window of the same order, and all three carry the **last** words of the draft.
  2. `… N earlier lines` appears exactly when something was elided, and never on a draft
     that fits.
  3. At 50k the chip row's top and bottom sit inside the work area (`_lay_out`'s geometry
     read back off the canvas, against `pill.work`), and `self._h` is within a bound
     derived from `BODY_MAX_H` rather than from the draft.
  4. An append is visible without scrolling: render, append, render, and the new words are
     in the drawn body both times.
  5. The reply path unchanged: a 4k reply's drawn item is byte-identical before and after.
- Acceptance: suite green; the before/after curves recorded; the geometry checks green at
  50k.
- [selfdrive] not required — rendering only; `plan()`, the router and asr text handling are
  untouched. Run it if anything inside the send or chip *bindings* moves.
- Doc sync: §7's bubble paragraph gains the cap and the tail window; §8's constants table
  gains `BODY_MAX_H` and `BODY_TAIL_CHARS` with the measurement behind each; invariant 7
  ("everything is bounded") gains rendering, which is the extension the decision names.
- Evidence:
  - **The curve, on the real canvas, before and after** (`scratchpad/render_cost.py`, a
    real `tk.Tk` and a real `tk.Canvas` — a fake that cannot wrap cannot measure wrapping;
    median of 12 renders after a warm-up, since font metrics cache on first use):

    | draft | before | after |
    |---|---|---|
    | 1 000 chars | 2.4 ms | 2.5 ms |
    | 10 000 chars | 32.7 ms | 4.2 ms |
    | 50 000 chars | **476.7 ms** | **4.3 ms** |

    Flat from 10k on, which is the claim. A 1k draft is unchanged because it still fits
    under the cap and is drawn whole — the fix is a window, not a truncation.
  - **The other half of the same defect, and the one the incident was actually about:** at
    50 000 characters the bubble sized itself **15 153 px tall in a 672 px work area** and
    the script said so — `OFF SCREEN — the chips are unreachable`. After: **414 px**, `on
    screen`. `reposition` clamps into the work area with 8 px of air, so a window taller
    than that cannot be placed with its chip row visible, whatever the clamp does.
  - **The constants are measurements, not taste.** On the real canvas at the body font and
    the 352 px the bubble wraps to: line height **17 px**, and 3 160 characters of ordinary
    prose wrapped to **56 lines** — 56.4 characters a line. So the cap is 20 lines and the
    window is about 28 of them, which is what keeps the visible tail full even where the
    text wraps early.
  - **The instrument, red before the build:** 14 checks in the new `tests/test_bubble.py`,
    **8 red** against the tree as it stood — the body handed to the canvas unbounded at 10k
    and 50k, the height tracking the draft (3 474 px vs 17 074 px on the measuring canvas),
    the chip row outside the work area, and no elision line anywhere. The **6 green** are
    the regression guards and stayed green: a short draft drawn whole, the window ending at
    the draft's end, an append visible with no scroll, no elision on a draft that fits, and
    both artifact-reply checks.
  - **The reply path was asserted rather than assumed.** A 4 000-character reply is still
    drawn as one whole item and still sizes the bubble — the decision says the draft path
    *joins* the artifact path, and this is what stops that becoming "both paths moved".
  - **`MeasuringCanvas` is borrowed from `test_editor.py`, not copied.** A second fake that
    wraps slightly differently is a second thing to keep true, and the drift would be
    invisible because both would pass.
  - Suite **979 → 993**, OK, 14.4 s. [selfdrive] not run: rendering only — `plan()`, the
    router and asr text handling are untouched. Commit `4fa12b2`.
- Status: **done**

### 38. The exits announce themselves, and one of them joins the menu
Owner-decided 2026-08-02 (same entry, fixes 3 and 4). The other half of the incident: once
the mic overflowed and the models unloaded, **every spoken rescue was impossible** — "boom"
needs a decode, a decode needs the models, the models need the mic the render killed — and
the one thing that still worked, the send hotkey, had been announced once, at startup, in a
console. So Flow says what still works at the moment it stops hearing, and gains the exit
that needs neither a decode nor a target.
- Files: `flow/session.py`, `flow/help.py`, `flow/ui.py`, `flow/__main__.py`,
  `tests/test_longrun.py` (where `TestOverflowIsSurfaced` already lives — the spec first
  said `test_resilience.py` and was corrected before a line was written, not after),
  `tests/test_menu.py`, `tests/test_help.py`, `docs/architecture.md`.
- **The note, and where its words come from.** `help.exits_note(hotkeys)` builds one line
  from `hotkeys.chosen` — **what registered**, never `DEFAULT_BINDINGS`, which is item 30's
  defect exactly and the reason that function lives in `help.py` beside `_hotkey_rows`
  rather than being written inline in a note. `hotkeys=None` (`--no-hotkeys`, Lite) is not
  a blank: it names the chip and the menu, because those are what still works there.
  `Session` gains a plain `hotkeys` attribute, assigned by `main()` after the hotkey block
  — a callable indirection would buy nothing, and the session already holds injected
  collaborators this way.
- **When it fires, and only then.** Mic overflow with a non-empty draft, or the idle model
  unload with a non-empty draft. **No note on an empty draft** — there is nothing to rescue,
  and a warning about a draft that does not exist is the noise that teaches people to
  ignore the real one. **No spam:** a latch, cleared in `_pump_health` whenever the draft is
  empty, so one voice-down stretch produces one note and the next one produces the next.
  The overflow note itself stays exactly as it is (invariant 4 — how much audio went); this
  is added beside it, because "audio was lost" and "here is what still works" answer
  different questions.
- **Copy draft.** Lite built `Pill._copy`; full mode gets it as a menu entry at the **top
  level**, beside Clear draft and before it — the universal, model-free, target-free exit
  that would have ended this incident in one tap, and a tap somebody makes mid-incident is
  by the menu's own rule (§9) not a tap that goes inside Settings. It reads
  `session.draft.text` and copies it; it does **not** go through `send()`, which would
  clear the draft and hand it to the paste layer. Empty draft → the entry says so rather
  than silently copying nothing.
- Instrument first:
  1. Two overflow bursts with a draft produce **one** exits note; clearing the draft and
     overflowing again produces a second. An overflow with an empty draft produces none.
  2. An idle unload with a draft produces the note; the existing unload note is unchanged.
  3. The note carries the combo `hotkeys.chosen` holds, and a fake whose `chosen` says
     `ctrl+shift+enter` renders `ctrl+shift+enter` — with `ctrl+alt+enter` appearing
     nowhere, which is the leg that catches a hardcoded default.
  4. `hotkeys=None` renders a sentence naming the chip, not an empty half-sentence.
  5. Copy draft: the clipboard holds the draft **verbatim** afterwards, `session.send` is
     never called, the draft is still there, and — the leg the decision cares about — the
     path touches no transcriber and no CLI (asserted on the fakes never being reached, not
     on the return value).
- Acceptance: suite green; the menu test sees Copy draft above Clear draft at the top level.
- [selfdrive] not required: no routing change, and the note is a note. Run it if anything
  in `plan()` moves.
- Doc sync: invariant 4's paragraph gains the exits note (the microphone saying what went
  is only half of "no words are dropped silently" when the words that are left have no way
  out); §7's Send section gains Copy draft; §9's menu paragraph gains the top-level entry.
- Evidence:
  - **The instrument, red before the build:** 20 new checks across three modules — longrun
    **6 of 8 red**, help **6 of 6 red** (behind the `AttributeError` for a function that
    did not exist), menu **7 of 7 red**. The two longrun greens are the ones true by
    absence and kept as regression guards: an overflow with no draft saying nothing extra,
    and the note not repeating on a steady counter.
  - **The leg that catches a hardcoded default, and it is item 30's defect one layer
    along:** a `Hotkeys` whose `chosen` says `ctrl+shift+enter` renders `ctrl+shift+enter`,
    and `ctrl+alt+enter` — the *first alternative* in `DEFAULT_BINDINGS`, already owned by
    another app on this machine — appears **nowhere**. Before the build the same assertion
    read `'ctrl+shift+enter' not found in 'microphone overflowed — about 320 ms of audio
    was lost while the UI was held'`, which is the whole gap in one line.
  - **The second trigger was re-derived rather than transcribed, and the spec was wrong
    about it.** The decision names "model unload with a non-empty draft"; `_pump_health`'s
    unload branch carries `and not self.draft.text` and `test_model_is_kept_while_a_draft_
    is_held` pins it, so that branch **cannot** produce the state. Hanging the note off it
    would have been a line that never fires. It is written as a condition instead — a draft
    held with `asr.loaded` false, whatever took the models away — which is reachable, is
    tested by unloading directly, and stays true if the guard above it ever changes.
  - **Copy draft asks the session for nothing.** Asserted on `session.method_calls == []`
    after the tap rather than on the outcome: a rescue that needs a decode is not a rescue
    from a dead microphone, and the strongest form of that claim is that the path calls
    nothing at all. `send()` is separately asserted un-called, and the draft is still there
    afterwards.
  - Startup on this machine is unmoved — `session.hotkeys = hotkeys` sits after the hotkey
    block and `--lite --no-profile --no-hotkeys` prints its eleven lines unchanged.
  - Suite **993 → 1013**, OK, 15.3 s. [selfdrive] not run: no routing change, and a note is
    a note. Commit `1d20961`.
- Status: **done**

### 39. A shim is refused before it can answer about nothing — and stdin becomes a capability
Owner-decided 2026-08-02 (decisions.md "The npm-shim defect: refuse loudly now, repair
per-CLI when measured"). Found by item 35's live verification: a `.cmd` launcher — the shape
`npm -g` writes on Windows — forwards `%*` through cmd.exe, which stops at the first
newline. **Every prompt `refine.py` sends is multi-line**, so a CLI installed the way both
CLIs document receives the framing and none of the user's text, **exits 0, and answers
fluently about nothing** — the silent-wrong-answer class this project ranks above every
other failure. The repair cannot be picked here (this machine's codex and claude are native
builds and there is no real npm shim of either to verify against), so the decision stages it:
refusal ships now, the repair ships as a capability that is off until somebody measures it.
- Files: `flow/refine.py`, `tests/test_refine.py`, `tests/test_lifecycle.py`, `README.md`,
  `docs/architecture.md`.
- **Instrument first, with NEEDS_YOU's four-line repro**: a test-built `.cmd` that echoes
  `%*`, invoked through `refine._invoke` with a two-line prompt, asserting the second line
  never arrives. Windows-only — `.cmd` is a Windows shape and `cmd.exe` is the mechanism —
  and **skipped elsewhere with the reason stated**, never silently passed, because a green
  check that cannot exercise the path proves nothing (Rule 1).
- **The refusal.** A CLI whose resolved executable ends `.cmd`/`.bat` is refused **before
  any process starts** — asserted on `Popen` never being called, not on the return value.
  The message names the CLI, states the cause in one plain sentence, and gives the cure
  (install the native build). It returns `(None, reason)` like every other failure, so
  refine and ask degrade non-destructively per invariant 3 and the draft is untouched.
- **The capability.** `Cli` gains `stdin_ok: bool = False`. When True, `_invoke` delivers
  the prompt on stdin — pipe, write, close — and a `.cmd` resolution is **not** refused for
  that CLI, because a shim that reads stdin never sees `%*`. `communicate(input=…)` is what
  pipes-writes-closes, and it may carry `input` exactly once: the poll loop passes it on the
  first call only, or CPython raises "Cannot send input after starting communication" on the
  first timeout — the kind of defect that only appears on a slow call.
- **codex and claude stay argv + `stdin=DEVNULL`**, with the measured hang recorded beside
  the flag: codex waits on stdin ("Reading additional input from stdin…") and would hang to
  the timeout on an open one. **No shipped entry flips `stdin_ok` True in this session** —
  that is item 35's verify-per-machine discipline, and a flag flipped from memory is the
  thing `verified` already exists to forbid.
- Prove the stdin path with a test-built executable that reads stdin and echoes it
  (`test_lifecycle.py`'s idiom — `sys.executable` is a real `.exe`, which is what makes it a
  proof rather than a mock).
- Acceptance: suite green; the shim test red before the refusal and green after; the stdin
  round trip returns the prompt verbatim; `refine CLI: codex` at startup is unchanged.
- [selfdrive] **required** — the resolution path every live call travels changed.
- Doc sync: §8's `refine.CANDIDATES` row gains `stdin_ok` and what it means; invariant 3
  gains the refusal (a failure that is loud is still non-destructive); the Verification
  section's "Verifying a candidate" subsection gains the shim leg, since it is now a thing a
  candidate can fail on. README's agent-CLI paragraph gains one sentence: native builds, not
  `npm -g`; Flow refuses a shim and says why.
- Evidence:
  - **The defect, reproduced with the four lines NEEDS_YOU asked for, and kept.** A
    test-built `echoer.cmd` carrying `echo %*`, handed the exact argv `_invoke` builds —
    `['line one\nline two\nline three']` as one element — returns `line one` on stdout,
    **no `line three`, and exit code 0**. That last assertion is the point: the silence is
    the defect, not the truncation. Windows-only and skipped elsewhere with the reason
    stated (`.cmd` is a Windows shape and cmd.exe is what truncates it); it stays in the
    suite after the refusal, because a claim about another program's behaviour becomes
    folklore the day it stops being measured.
  - **The instrument, red before the build:** 16 red in `test_refine.py` and 4 in
    `test_lifecycle.py`. The one that mattered most was a *pinned green being inverted* —
    `test_a_cmd_shim_is_found_and_actually_starts` asserted `'SHIMMED\n' is not None`
    against the tree as it stood, which was the right answer to the earlier `WinError 2`
    defect and the wrong answer to this one. It is now
    `test_a_cmd_shim_is_found_and_then_refused`.
  - **Refused before anything starts**, asserted on `Popen` never being called rather than
    on the return value — a call that was made and then failed would satisfy a check that
    only read the answer. `.cmd` and `.BAT` (case-insensitively) refuse; `.EXE` and an
    extensionless path start normally, so macOS, Linux and WinGet installs are untouched.
  - **Non-destructive, per invariant 3:** `refine()` and `ask()` each come back
    `(None, reason)` with the reason naming the CLI, and no process is started for either.
  - **The stdin path is proved on real processes**, in the module that is allowed to start
    them: a child that echoes stdin gets the multi-line prompt back **verbatim**, including
    `marmalade-42` on the last line — the exact leg a shim loses. The prompt leaves the
    argv when it travels that way (`len(sys.argv)` comes back **1**), an argv CLI still
    gets `stdin=DEVNULL` with nothing written, and a **`.cmd` shim that reads stdin is
    usable again end to end**, which is the whole claim of the capability.
  - **Found while wiring it, and it would only ever have appeared on a slow call:**
    `_invoke` polls `communicate` in a loop, and `communicate` may carry `input` exactly
    once — a second call with it raises `ValueError: Cannot send input after starting
    communication`. The prompt goes on the first pass only, and `test_a_slow_reader_still_
    gets_its_input` (a child that sleeps past the first poll) is what holds it.
  - **A pinned test had to be split rather than deleted.** `test_the_launch_uses_the_path_
    the_lookup_returned` drove a real `.cmd` on a real PATH into `Popen`, which the refusal
    now makes impossible. Its two halves are both still true and are now two checks: what
    `which` finds is what `available()` reports (real PATH, real `PATHEXT`), and the launch
    uses the resolved path rather than the bare name (no `PATHEXT` dependency).
  - **No shipped entry flips `stdin_ok`**, asserted over the whole of `CANDIDATES` — the
    same mechanical discipline `verified` already carries.
  - Suite **1013 → 1031**, OK, 15.2 s. [selfdrive] **63/64 then 64/64 on the automatic
    rerun** — the failing check was `spoken: 'capitalize sameer'`, which is Rule 2's
    **second sighting of the same check** and therefore fires the tripwire: a NEEDS_YOU
    quarantine-or-fix entry is written, with the load question the decision names answered
    (yes — this run followed two full suites and three real-Tk measurements back to back).
    Nothing in this item touches the decoder, the gate or the router. Commit `094f42e`.
- **Deviation, recorded rather than quiet:** §11's test count was not updated in this
  commit and is carried into item 40's doc sync, which touches the same file and moves the
  number again.
- Status: **done**

### 40. kiro-cli, wired — and a cleaner for the furniture it prints
The measurement is NEEDS_YOU's entry "kiro-cli — verified, all four legs, 2026-08-02, this
machine", which is item 35's gate paid in full: `--version` → `kiro-cli-chat 2.16.0`;
one-shot `chat --no-interactive --trust-tools= "<prompt>"` → answer, exit 0, ~1 s; and the
leg that matters — a SECRET on the last line of a three-line prompt came back **verbatim**
through `Popen` list-argv, because this is a native exe and not a shim. Round five's `kiro`
rejection stands and was about a different binary: `kiro` on PATH is the IDE launcher.
- Files: `flow/refine.py`, `tests/test_refine.py`, `tests/test_indicator.py`,
  `tests/test_converse.py`, `tests/test_main.py`, `tests/test_help.py`,
  `docs/architecture.md`.
- **The entry.** `Cli("kiro-cli", ("kiro-cli", "chat", "--no-interactive",
  "--trust-tools="))`, verified, prompt appended as the final argv element — the shape
  `Cli` already describes. `--trust-tools=` empty is the right courier default: no tool runs
  without asking, which is what an agent CLI being used as a rewriter must never do.
- **Detection.** By PATH, because the MSI adds `%LOCALAPPDATA%\Kiro-Cli\` to the user PATH
  (verified in the registry; this session's first "off-PATH" impression was its own stale
  environment). `%LOCALAPPDATA%\Kiro-Cli\kiro-cli.exe` is kept as a **fallback probe** for
  stale environments only — cheap insurance, and the reason is in the code so the next
  reader does not take it for a second source of truth. Resolution moves into one helper
  both `available()`/`detected()` and `_invoke` use, so detection and launch cannot disagree
  about where the executable is — the class of defect §7 already records for
  `shutil.which` vs `CreateProcess`.
- **The cleaner, per CLI and nowhere else.** kiro-cli's stdout carries furniture: ANSI
  colour, a `> ` answer prefix, and a `▸ Credits: … • Time: …` status line (it meters, ~0.10
  credits/call). `_clean` takes the `Cli` that answered and applies that CLI's furniture
  stripper before the generic tidy; **codex and claude pass through untouched**, asserted,
  because a cleaner that fires for everybody is a parser, and this module's docstring is an
  argument against needing one.
- Instrument first: a fixture of the **real captured output** from this machine — escapes,
  prefix, credits line and all — asserted to clean down to the answer alone, red before the
  cleaner exists. Plus the negatives: codex output with a `>` in it (a shell prompt inside a
  quoted answer) is unchanged, and a kiro-cli answer that contains the word "Credits"
  mid-sentence keeps it.
- **Naming, the pin, the marker and the sheet all handle the new name** — extend the tests
  that already enumerate the shipped names rather than writing new ones. `kiro-cli` is 8
  characters, so `_marker()` falls back to `ASK` by the rule item 35 pinned at `opencode`;
  that rule is not changed, it is extended, and **whether ASK is the right thing to see when
  kiro-cli is the CLI that would answer is an eye question** — desk list, per item 15's
  precedent for the 6 pt marker.
- Acceptance: suite green; [selfdrive] **64/64**; and **one live call through Flow's own
  refine path** — kiro-cli is installed and authenticated on this machine — refining a
  two-line draft, with the cleaned result in the Evidence line and the credits furniture
  gone.
- [selfdrive] **required** — `available()` and the resolution path are what every CLI round
  trip goes through.
- Doc sync: §8's `refine.CANDIDATES` row gains the entry and the cleaner; §1's "What leaves
  the machine" paragraph, which names the cloud-backed CLIs; the Verification section's
  provenance line gains the kiro-cli version this was measured with.
- Evidence:
  - **The fixture is transcribed, not imagined.** Captured through the same `Popen` shape
    `_invoke` uses, before a line of the cleaner existed:
    stdout `'\x1b[m> \x1b[0mThe deploy failed this morning because of the migration.'`;
    a multi-line answer `'\x1b[m> \x1b[0mApples\x1b[0m\x1b[0m\nPears\x1b[0m\x1b[0m\nPlums'`
    — so the `> ` marker is on the **first line only**, and stripping it per line would
    have eaten a quoted shell command out of a real answer.
  - **The verification note was right about the furniture and wrong about which stream it
    is on, and the capture is what found it.** With the streams apart — this module's
    discipline, and what `_invoke` does — `▸ Credits: 0.05 • Time: 1s` goes to **stderr**
    and never reaches `_clean` at all; it only lands on stdout when the two are merged,
    which is the shape an interactive terminal shows. Stripped anyway, because that is what
    the CLI prints when they are together and removing an absent line costs nothing — and
    recorded as measured rather than left as an assumption. Also on stderr and left alone:
    a `WARNING:` that `--trust-tools` wants an `@{MCPSERVERNAME}/` prefix. Exit 0, answer
    correct, and nothing is done about a warning on a stream this module discards.
  - **The probe is doing real work here, not standing by.** `shutil.which("kiro-cli")`
    returned **`None`** in this session while `%LOCALAPPDATA%\Kiro-Cli\kiro-cli.exe`
    existed and answered — the MSI's PATH entry does not reach a shell that predates the
    install. NEEDS_YOU's "detection by PATH works, keep the probe as cheap insurance" is
    true of a *fresh* shell; in the environment an installer leaves behind, the probe is
    the difference between working and not.
  - **The instrument, red before the build:** 21 new checks in `test_refine.py` — the
    entry's shape, the four resolution cases, and eight cleaner cases including the two
    negatives that make it per-CLI (a codex answer containing `> git status` and the word
    "Credits" comes through byte-identical; a kiro-cli answer *about* credits keeps the
    word, because the status line is matched as a shape and not as a word).
  - **One live call through Flow's own `refine()`**, pinned to kiro-cli — the entry, the
    resolution, the argv, the cleaner and the commentary guard all the ones that ship:
    - resolved at `C:\Users\samar\AppData\Local\Kiro-Cli\kiro-cli.exe`
    - `available()` → `['codex', 'claude', 'kiro-cli']`, `detected()` → those plus
      `opencode`
    - a **two-line** draft in, back in **2.7 s** from `'kiro-cli'`:
      `The deploy failed this morning roughly ten minutes after the migration ran, and no
      one noticed until the alerts fired.`
    - the `repr` of that result carries **no escape, no `> `, no credits line** — the
      furniture is gone and the answer is the whole of what came back.
  - **The Help sheet needed nothing, and now says so.** Every other surface that touches a
    CLI name had to be extended; the sheet names none, and a new check over `CANDIDATES`
    asserts that rather than leaving it a coincidence somebody could break with one
    example.
  - **`kiro-cli` at 8 characters is the first *verified* name the marker declines**, so the
    pill draws `ASK` while kiro-cli is the CLI that would answer. `opencode` proved the
    rule while inert — nothing could ever be asked of it — so this is the first time the
    slot's refusal has a live call behind it. The rule is unchanged and extended in
    `test_indicator.py` and `test_converse.py`; whether `ASK` is the right thing to see
    there is an eye question and is on the desk list, per item 15's precedent.
  - **A machine-dependence was closed while wiring it, and it is the defect `cli_env.py`
    was written for, one seam along:** the probe made `available()` answer from the
    developer's disk in tests that had carefully declared what PATH holds. `cli_env` gains
    `no_off_path_installs()`, and `no_cli_on_path()` now covers every candidate rather than
    the two names it was written with.
  - Suite **1031 → 1050**, OK, 16.6 s. [selfdrive] **64/64**, including the live codex
    converse round trip. Commit `26e2b43`.
- Status: **done** — with the marker eyeball on the desk list.

### 41. A CLI that needs longer says so, and the marker learns a short name for it
Owner-decided 2026-08-02 (decisions.md "kiro-cli's 20-second wall, the six-character
marker, and the cut bubble", fixes 1 and 2). Two fields on one dataclass, because they are
the same finding read twice: kiro-cli is a CLI the module's global constants were not
written for. The identical one-line call measured **4.3 s in a bare directory and 35.8 s
inside a workspace whose `.kiro` settings declare MCP servers** — kiro-cli spawns the
project's MCP servers on every `chat` invocation, uvx-resolved and cold — so `TIMEOUT_SEC`
= 20 executes the call at second twenty, every time, in exactly the workspaces the workshop
is for. And `kiro-cli` at 8 characters overflows item 15's 6-character slot, so the pill
draws `ASK` while kiro-cli is the CLI that would answer; item 40 put that on the desk list
and the owner's reading came back — "Kiro is not captured".
- Files: `flow/refine.py`, `flow/ui.py`, `tests/test_refine.py`, `tests/test_lifecycle.py`,
  `tests/test_indicator.py`, `tests/test_converse.py`, `docs/architecture.md`.
- **`timeout_sec`, and the one thing it must not become.** `Cli` gains it; kiro-cli ships
  **60**, which is 35.8 measured plus headroom, and every other entry defaults to the
  global. It is a **floor, not a replacement** — `_invoke` waits `max(caller, cli)` — and
  that is a decision worth stating rather than a shortcut: `--cli-timeout` is documented
  as the knob that *raises* the wait, so a per-CLI value that simply won would mean the
  one CLI measured needing the most time is the one the flag cannot reach. Read the other
  way round it is the same sentence: a global lowered below what a CLI was measured to
  need would re-create this incident on the only entry that has ever had it.
- **The note keeps naming the CLI and the seconds it actually waited.** It already
  interpolates the timeout, so this is a check rather than a change — and it is worth a
  check, because the number in that message is now per-CLI and a hardcoded 20 would look
  right on three entries out of four.
- **`marker`, the display alias.** `Cli` gains it, empty for everything that already fits;
  kiro-cli ships `"kiro"`. `_marker()` draws the alias where there is one, the full name
  where it fits the bound, and `ASK` as the unchanged fallback — so the rule item 35 pinned
  at `opencode` is extended, not rewritten, and an inert 8-character name with no alias
  still falls back. The bound is asserted **over every shipped entry** rather than over the
  one alias that exists, because the next alias is where a 7-character one gets typed.
- **The full name is what every other surface keeps.** The menu, the notes and the Help
  sheet name CLIs in prose, where 8 characters cost nothing; only the 6 pt slot beside the
  level bars has a wall. Asserted, so "the marker learned a nickname" cannot spread into
  the places a user is reading rather than glancing.
- Instrument first, both inverted:
  1. A slow child through a fake `Cli` dies at the global timeout today and completes on
     its own after — `test_lifecycle.py`'s idiom, a real process because a per-CLI wait is
     a wait, with the seconds sized to the suite. **Never gated on a live 36-second call**:
     the property is that the number `_invoke` waits comes from the entry, and a real
     kiro-cli would only prove that this machine is slow.
  2. `_marker()` for a `Cli` named `kiro-cli` reads `ASK` today and `kiro` after.
- Acceptance: suite green; [selfdrive] **64/64**; and **one live ask through Flow's own
  path** with kiro-cli pinned and `cwd=D:\dev\ai-continuum\ai-continuum-product` — the
  incident run on purpose, in the workspace whose `.kiro/settings/mcp.json` declares the
  uvx-resolved servers that cause it — completing under the new timeout, with its duration
  in the Evidence line.
- [selfdrive] **required** — the invoke path changed.
- Doc sync: §8's `refine.TIMEOUT_SEC` row gains the reason a CLI may need more than the
  constant and what the floor means for `--cli-timeout`; the `refine.CANDIDATES` row gains
  both fields and kiro-cli's two values with the measurement behind each.
- Evidence:
  - **The incident, run on purpose, through Flow's own `ask()`** — kiro-cli pinned,
    `cwd=D:\dev\ai-continuum\ai-continuum-product`, whose `.kiro/settings/mcp.json`
    declares four uvx/npx-resolved servers. Resolved at
    `C:\Users\samar\AppData\Local\Kiro-Cli\kiro-cli.exe`, entry reading
    `timeout_sec=60, marker='kiro'`, and the answer came back in **38.9 s** — grounded in
    that workspace, not generic. **Past the old global 20 s by 18.9 s**: this exact call is
    the one the owner watched fail, and it is now the one that answers. 38.9 against the
    35.8 the decision sized 60 from, so the headroom is real and it is not large — which is
    the residue the entry states rather than hides.
  - **The instrument, red before the build:** 10 of 24 checks across the three modules
    failed against the tree as it stood — three of the four `timeout_sec` checks (the field
    did not exist), both entry-shape checks, five of the six alias checks, and the shipped-
    names rule, which flipped from `ASK` to `kiro`. The **14 green** are the regression
    guards and stayed green: an entry *without* a declared timeout still dies at the
    caller's number, a name that fits is still drawn as itself, a name that overflows with
    no alias still falls back to `ASK`, and every pre-existing kiro-cli entry check.
  - **The floor is asserted in both directions**, because "the entry wins" and "the entry
    is a floor" pass the same happy-path check: an entry declaring 1.2 s carries a 0.8 s
    child through a 0.4 s caller budget, *and* an entry declaring 0.2 s cannot shorten a
    5.0 s caller. The second is what keeps `--cli-timeout` meaning what §8 says it means.
  - **The note quotes the wait, not the constant.** `slow timed out after 1s` from an entry
    declaring 1.0 against a caller's 0.4 — asserted as the whole string, so a message that
    went back to naming the global cannot pass by containing the right words.
  - **The marker/note agreement check had to be restated rather than relaxed**, and that is
    the third time item 15's rule has been sharpened by a new name. It read "equal, or
    `ASK`"; an alias is a shorter name for the *same* CLI, so agreement now reads "the
    entry's alias where it has one, the name where it fits, `ASK` where neither does" —
    computed from the entry, because a literal `"kiro"` there would have passed whatever
    the pill drew.
  - **The bound is on the slot, not on the field.** An alias of 8 characters falls back to
    `ASK` like any other name that does not fit, and every shipped alias is asserted against
    `Pill.MARKER_MAX` over the whole table — the next alias is where a seven-character one
    gets typed.
  - Suite **1050 → 1062**, OK, 25.9 s. [selfdrive] **64/64**, including the live codex
    converse round trip. Commit `40a3660`.
  - **One process note, recorded rather than left in the reflog:** the first commit landed
    with a stray `@` as its subject — PowerShell here-string syntax typed into a POSIX
    shell — and was amended in place. Rule 3 forbids amending, and it also requires a plain
    imperative subject; leaving `@` would have broken the second to obey the first, on an
    unpushed tip commit whose content nobody had seen. The content is byte-identical.
- Status: **done**

### 42. The bubble is clamped inside the work area by position, not only by size
Owner-decided 2026-08-02 (same entry, fix 3). Item 37 capped the *draft* body and left
placement to `reposition`'s clamp; the owner's screenshots show a bubble whose border runs
off the display edge. The cap bounds one path's size, and nothing bounds the window.
- Files: `flow/ui.py`, `tests/test_bubble.py`, `tests/test_editor.py`,
  `docs/architecture.md`.
- **Instrument first, item 37's style and the same four corners.** A real `tk.Tk`, a real
  `Bubble`, the pill placed at each corner of the work area, and every edge of the window
  read back — from `GetWindowRect` as well as from Tk, because `winfo_y()` reports what was
  *asked for* and a screenshot can only disagree with where the window actually is. Before:
  the breaches and their sizes. After: every edge inside the work area, at every corner, in
  every state.
- **What the instrument found, and it is not what the entry read off the screenshot.** The
  top edge is already held — `max(top + 8, …)` has been there since item 24 and no state at
  any corner puts the window above the work area. The breach is the **bottom**, and it is
  the reply path: a 4 000-character answer sizes the window **1 459 px** and a 12 000-
  character artifact **4 179 px**, both pinned at `top + 8` on a 672 px desktop, so the chip
  row lands at screen y **1 427** and **4 147**. The entry's *diagnosis* moves to the other
  edge; its *finding* stands exactly as written — the bubble leaves the screen by position,
  the chips go with it, and this is the long-draft incident's own principle alive on the one
  path item 37 deliberately did not touch. Recorded rather than quietly corrected, because
  the decision is the authority and this is the measurement disagreeing with one word of it.
- **One bound, not two numbers that must agree.** `_render` fits the height it computes to
  the work area before anything reads it, so `self._h` is *already* inside the desktop, and
  the existing position clamp becomes a proof rather than a hope: with `h ≤ work − 2·air`,
  `max(top + air, min(y, bottom − h − air))` cannot put either edge outside. The air is
  `EDGE_AIR` in both places rather than four literal `8`s — the note that used to land on
  the chip row was two numbers that had to agree and nothing made them.
- **The chips come with it, because they are drawn from `self._h`.** That is the same
  sentence item 37 wrote about the draft, and it is why the fix belongs on the height rather
  than on the geometry string: bounding only what is *placed* would leave the row drawn
  below the visible window, which looks fixed and is not.
- **The reply/artifact path is asserted unchanged** — item 37's guard, kept: the answer
  keeps its full-text probe, its `ASK_ARTIFACT_MAX_CHARS` bound and its single drawn item,
  and a long reply still sizes the bubble larger than a short one. What changes is that the
  window stops at the desktop edge. The honest residue, stated: past what fits, the tail of
  a very long artifact is now clipped by a window instead of being off the screen entirely,
  and the chip row sits over its last lines. A reply that *scrolls* is the real cure and is
  a proposal, not this item — §8's `ASK_ARTIFACT_MAX_CHARS` row currently claims "the bubble
  scrolls", which this measurement shows is not true of any path, and the doc sync fixes it.
- Instrument first, each its own check in `tests/test_bubble.py`:
  1. Every edge inside the work area with the pill at all four corners, for a 1k draft, a
     50k draft, a 4k reply and a 12k artifact reply — the geometry `reposition` computes,
     against `pill.work`. Red today on the two reply cases at all four corners.
  2. The chip row's band is inside the work area in the same matrix — the property the
     window bound exists for, and the one a placed-only clamp would fake.
  3. A reply taller than the desktop no longer sizes the window past it, and a reply that
     fits is untouched — both directions, so a constant cannot pass this.
  4. The reply path unchanged: a 4k reply is still drawn as one whole item and still sizes
     the bubble larger than a short one.
- Acceptance: suite green; the before/after corner tables recorded in Evidence.
- [selfdrive] not required — geometry only; `plan()`, the router and asr text handling are
  untouched, and no send or chip *binding* moves.
- Doc sync: §7's "The bubble under a long draft" paragraph gains the placement bound and
  says what is now true of the reply path; §8 gains `EDGE_AIR` and corrects
  `ASK_ARTIFACT_MAX_CHARS`'s "the bubble scrolls" to what the window actually does.
- Evidence:
  - **The corners, before and after** (`scratchpad/bubble_place.py`, a real `tk.Tk` and a
    real `Bubble`, nine states × four corners, every edge compared against the work area
    the app itself computed — 1280 × 672 here):

    | state | before | after |
    |---|---|---|
    | 1k draft, all four corners | inside | inside |
    | 50k draft, all four corners | inside | inside |
    | 4k reply, all four corners | h **1 459**, **795 px past the bottom** | h **656**, inside |
    | 12k artifact reply, all four corners | h **4 179**, **3 515 px past the bottom** | h **656**, inside |
    | 12k reply + a long note | h 4 261, **3 597 px past** | h 656, inside |

    **12 of 36 placements outside the work area before, 0 of 36 after.** The draft states
    were inside at every corner both times, which is item 37's cap holding.
  - **Read back from Windows, not from Tk** (`scratchpad/bubble_rect.py`): `winfo_y()`
    reports what was *asked for*, and a screenshot can only disagree with where the window
    actually is. `GetWindowRect` agreed with Tk in every case, which is what makes the
    numbers above the screen's and not the toolkit's. The figure that names the defect is
    the chip row: **screen y 1 427** on an ordinary answer and **4 147** on an artifact, on
    a 672 px desktop. After: **624**, on both.
  - **The measurement disagrees with one word of the decision, and it is recorded rather
    than quietly fixed.** The entry reads the owner's screenshot as a top edge gone
    negative. It has not: `max(top + EDGE_AIR, …)` held the top at 8 in **all 36
    placements**, in every state including the editor, the sent card, a long note and the
    float-up animation's own frames. The breach is the **bottom**, and the path is the
    reply — the one item 37 deliberately did not touch, whose own Evidence line predicted
    exactly this ("a window taller than that cannot be placed with its chip row visible,
    whatever the clamp does"). The decision's finding stands as written: the bubble leaves
    the screen by position and takes the chips with it. The edge is the other one.
  - **The instrument, red before the build:** 5 of the 6 new checks failed against the tree
    as it stood — 16 subTest failures across the two corner matrices, all on the two reply
    states at all four corners, plus 3 errors for `EDGE_AIR` not existing. The **14
    pre-existing checks stayed green**, including both artifact-reply guards, which is what
    says this fix did not move the reply's rendering.
  - **One bound, not two numbers that must agree.** `EDGE_AIR` is the air the height is
    fitted to (`work − 2 × air`) *and* the air the position is clamped by, and a check
    pins that a 12k reply lands exactly at `top + air` and `bottom − air`. That is the
    lesson from the note that used to land on the chip row: `52` and `PAD + CHIP_H` were
    two numbers nothing made agree.
  - **A fixture gap fell out of it, and the failure was the right shape.** `_render` now
    reads `pill.work`, so three checks in `test_editor.py` raised `TypeError: cannot unpack
    non-iterable Mock` — loud, immediate, and naming the line. `WORK` moved next to
    `MeasuringCanvas` and `test_bubble.py` borrows both, for the reason it already borrowed
    the canvas: two files disagreeing about how tall the desktop is would be two layout
    answers, both passing.
  - **The residue is stated rather than hidden.** Past what fits, the tail of a very long
    artifact is now clipped by a window instead of running off the display, and the chip row
    sits over its last lines. That is strictly better than unreachable — the incident's own
    principle is that a reply must not disable its own exits — and it is not the cure. A
    reply that genuinely *scrolls* is a NEEDS_YOU proposal, and §8's claim that "the bubble
    scrolls" is corrected in the same commit, because it was the assumption that let the
    reply path keep an unbounded probe in the first place.
  - Suite **1062 → 1067**, OK, 25.9 s. [selfdrive] not run — geometry only; `plan()`, the
    router and asr text handling are untouched and no send or chip binding moved. Its own
    `the bubble is inside the work area` check was green on the previous run and is the
    same property this item now asserts at four corners instead of one. Commit `1273920`.
- Status: **done**

## Backlog — "prepare" tier

(empty — the round-one proposals P1–P4 were all decided or parked; see
[docs/decisions.md](docs/decisions.md) and NEEDS_YOU.md's parked section)
