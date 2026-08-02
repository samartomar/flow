# LOOP_PLAN — the loop's contract and its current queue

Born as the autonomous backlog from the Feedback.md review (2026-08-01; the review is
archived at [docs/history/Feedback.md](docs/history/Feedback.md)). Three rounds plus a
two-item micro-round ran to completion the same day — 25 items, suite 455 → 773, every
gate passed. Their closing summaries, the round-three queue block, and every item's
full entry with its before/after evidence live in
[docs/history/loop-rounds-1-3.md](docs/history/loop-rounds-1-3.md). The decisions the
items came from are in [docs/decisions.md](docs/decisions.md); what only the owner can
do is in [NEEDS_YOU.md](NEEDS_YOU.md).

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

## Backlog — "prepare" tier

(empty — the round-one proposals P1–P4 were all decided or parked; see
[docs/decisions.md](docs/decisions.md) and NEEDS_YOU.md's parked section)
