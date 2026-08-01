# LOOP_PLAN — autonomous backlog from the Feedback.md review (2026-08-01)

## ROUND THREE — the current queue. Everything above the Rules is history; this block is
## the state. (Written 2026-08-01, owner's decision session.)

**Nine items are queued: 15 through 23, none started.** Items 0–14 are done — their
entries below are the record, not work. The two closing summaries beneath this block
describe rounds one and two and are *both* superseded by this queue: the loop is NOT
finished until items 15–23 are each done, blocked, or deferred, and only then is the
round-three closing summary written — prepended here at the top, the same convention
rounds one and two used.

The queue, in execution order (top to bottom, one item per iteration, as always):

| # | One line | Gates beyond the suite |
|---|---|---|
| 15 | Converse marker text names the resolved CLI | — |
| 16 | Decode confidence recorded per route — no behaviour | [selfdrive] |
| 17 | The draft becomes keyboard-editable (stage one) | [send-live], stop-condition on invariant 10 |
| 18 | Bench outputs gain a model-identity block | one real `command_bench.py` run |
| 19 | Inferred pairs offered in the menu, one tap declares | [selfdrive] |
| 20 | "follow and" admitted iff the corpus prices it at zero | command_bench gate, revert path defined |
| 21 | A reply can become the draft (chip + spoken form) | corpus gate on the spoken form; chip ships regardless; **needs 17's countdown seam — do not reorder before 17** |
| 22 | Spoken send triggers: "boom" / "enter boom" | corpus gate; [send-live] mandatory for the Enter variant |
| 23 | Converse = prompt workshop, workspace grounding, P9 rewrite | [selfdrive]; edits `docs/product.md` (a named file) |

**What makes this round one-go executable, stated so nothing needs interpreting:**
- Every item already carries instrument-first, named files, acceptance, and doc sync.
  Where a desk or an unlocked desktop is required, the item names its Rule 2/Rule 7
  deferral path — `done (live check pending)` plus a NEEDS_YOU entry is a *completed*
  outcome for this round, not a blocker.
- Items 20, 21 and 22 carry measurement gates with defined failure behaviour: a failed
  gate means ship the reduced scope (20: no grammar change; 21: chip only; 22: report
  the word that would not admit) and write the numbers to NEEDS_YOU — then the item is
  done, not blocked.
- The only hard ordering constraint is 17 before 21 (shared countdown-hold seam). The
  listed order satisfies it; do not resequence around a failure, just mark and move on
  (Rule 8).
- Owner-decided defaults are in the items themselves (22: "boom"/"enter boom"; 23: the
  `--cwd`/`workspace` precedence). Nothing in this round waits on an owner answer.
- Rule 2's selfdrive flake policy (rerun-once, record the check name, same-check
  tripwire) is in force for every [selfdrive] run this round.

## Closing summary — round two, 2026-08-01: items 13 and 14 done, none blocked

Two commits, `ea8d2bb` and `3152bde`, on top of the owner's three. Nothing pushed. The
unit suite went **558 → 616 tests** (14.1 s → 15.0 s). `scripts/selfdrive.py` finished
64/64 after each; `scripts/command_bench.py` came out identical line for line before and
after the grammar change, which was the point of running it. No live stage-D re-run —
that needs a person, and it is written up in NEEDS_YOU.md with what to expect.

| # | Commit | What it did |
|---|---|---|
| 13 | `ea8d2bb` | A word the recogniser keeps getting wrong despite the speaker's effort is one biasing has already failed on. `wrong -> right` in the lexicon is now a substitution on the decoder's output, and a menu entry writes the file and opens the folder |
| 14 | `3152bde` | All 33 utterances from the three live runs are fixtures carrying both what was recorded and what the grammar does now. Two rows moved: `lower case` as two words, and the polish frame with its noun mis-heard. `--takes N` makes stage D repeat |

**Both items were instrumented before they were fixed**, and in both cases the shipped
code was measured rather than assumed: item 13's arrow syntax parsed as an ordinary
hotword (`'Samir semir -> Samir kubectl'` — biasing toward the misspelling *and* toward
a literal `->`), and item 14's five failing fixtures named the exact two rows to move.

**Three things came from distrusting a check**, which is the part worth keeping:
- Item 13's substitution line was deleted from `flow/asr.py` on purpose after the suite
  went green. Exactly one test failed, at the seam it claims to guard.
- Item 14's fixtures caught an error in *this file*: the summary above said items "2, 3
  and 11" held across all three takes. Item 2 did not — run 1 escalated it. Two of
  eleven held, not three. NEEDS_YOU.md repeated the same claim and is corrected too.
- A test written to argue for a lookup table over a similarity threshold asserted the
  wrong inequality, and the measurement said so. The corrected argument is stronger: no
  bar admits "brown" (0.36 against "prompt") without admitting "proper" (0.67).

**Nothing is blocked.** What is deliberately *not* done, with a reason in each fixture:
the `MATCH_THRESHOLD` question ("standard" vs "standup"), bare "follow" for follow-ups,
the dropped word in "Insert before release nodes", and the garbled-escalation sanity
gate the Rules parked. All four are in NEEDS_YOU.md with their numbers.

**What waits in NEEDS_YOU.md:** three new entries — the pinned-fixture list above, a
README sync that Rule 3 kept out of item 13's commit (four exact line numbers), and
whether Flow should ever promote an *inferred* confusion pair to a substitution the way
a declared one now is. Plus a rewritten desk entry: `--stage D --takes 3` with two named
predictions to check and one to check with a `semir -> Samir` pair in place.

---

## Closing summary — round one, 2026-08-01, all twelve items done, none blocked

Twelve commits, `650e09c`..`df13ba8`, on top of the owner's `c9aabc6`. Nothing pushed.
The unit suite went **455 → 547 tests** (3.3 s → 14.0 s, and §11 of the architecture doc
now says where that time goes). `scripts/selfdrive.py` finished 64/64 on every item that
named it; `scripts/send_check.py --live` finished 18/18 on both items that named it,
run on an unlocked desktop rather than deferred. `~/.flow/` holds exactly what it held
before: `profile.json`.

**What landed.** Every one had a failing check first, and the before/after numbers are in
each item's Evidence line.

| # | Commit | What it fixed |
|---|---|---|
| 1 | `650e09c` | A stale CLI rewrite could resurrect itself as a fresh draft and be auto-asked with no press. Operation ids + draft revisions; in-flight work owns the state |
| 2 | `49bc93e` | Closing Flow left the rewrite running — 3 s after `close()` the thread was still alive — and a 0.4 s timeout returned after 1.37 s leaving the CLI's own child running. One `_invoke`, cancellable, `taskkill /T` |
| 3 | `b84c0d8` | A third window taking focus in the 30 ms before Send received the paste, prepared for a different window |
| 4 | `cf8cdb1` | The clipboard restore overwrote whatever the user copied during its own 0.6 s pause. Guarded by `GetClipboardSequenceNumber` |
| 5 | `ada7d34` | The mic queue dropped audio and only counted it. Now says how much, in time |
| 6 | `d02651d` | Over-long drafts and questions were silently truncated at the CLI boundary. Both say so, worded differently because the two behave differently |
| 7 | `2787b2a` | Switching auto-ask off lasted until you quit — and `__main__` would have overwritten a stored preference anyway |
| 8 | `1aee998` | A calibration is a measurement through a microphone, and nothing noticed when the microphone changed |
| 9 | `069f869` | Nothing recorded what happened in an ordinary session. `flow/diag.py`: content-free, allow-listed, bounded |
| 10 | `c23bbc5` | A model name is not a build. Versions, revisions and CLI builds recorded at startup |
| 11 | `195375c` | The provider was named after the fact. Converse mode now says the question leaves this machine, before it does |
| 12 | `df13ba8` | The loading figures were a month old. Re-measured: 38 → 174 → 432 → 83 MB |

**Nothing is blocked.** Two items were harder than they looked and both are recorded:
item 2 broke three test modules that mocked `subprocess.run` (unnoticed, they invoked the
real `codex` and the suite went to 80 s), and item 9's first version defaulted every
`Session` to a live writer and left 1513 records in the real `~/.flow` — caught, deleted,
and the default is now a null writer.

**Three findings came from distrusting a green check**, which is the part worth keeping:
- Item 9's sentinel test passed immediately. Making a hook leak on purpose showed it did
  *not* bite, because the route hook sat after `_route`'s early return — the commonest
  route in the app was traced nowhere.
- Item 8's restart test never reached `mic.restart()`; the fake always reported active.
- Item 1's first `finish()` helper waited on `state`, which is the thing under test, so
  one check passed by not looking.

**What waits in NEEDS_YOU.md.** Nine entries. Five decisions the loop refused to make for
you — what a stale rewrite should cost, whether to split the now-14 s suite, whether to
pin model revisions, plus the four "prepare"-tier proposals (P1 ask response profiles,
P2 adaptive auto-ask, P3 streaming, P4 recordings out of history, the last two carrying
facts checked today rather than assumed). Two observations you should see — a self-drive
flake on a real-ASR check that the Rules gate every commit on, and a warning that arrives
0.6 s late and is shown against the following Send. Plus the two that were already there.

**Known gaps left in the architecture doc:** two, down from four. The provider badge on
the pill (design taste) and the late-warning drain (a UI call). Both are in NEEDS_YOU.md.

**Owner's return, 2026-08-01, same day.** The owner reviewed, ran `live_check.py`
(first ever live run — capture, gate, latency and paste target pass; commands 7/11),
and decided the open calls. Executed in-session: P4 option B (history rewritten,
recordings live in `D:\dev\flow-recordings\`, force-push pending — hashes in this file
were remapped to the rewritten history), P1 as commit `50c2068`, the late-warning drain
as commit `6008cfd`. Suite now 558. Two new do-tier items below: 13 (speaker-editable
settings: name, people, correction pairs) and 14 (grammar coverage from the live run).

---

The loop's single source of truth. One "do"-tier item per iteration, top to bottom.
Round three's queue is the block at the very top of this file; the first pending item is
**15**, and items 0–14 below it are records of finished work — skip them without reading
past their Status lines.

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
   room). Different checks on different days are noise, and rerun-once continues. Items marked [send-live] also run
   `uv run python scripts/send_check.py --live` — but only if the interactive desktop is
   available (heuristic: `GetForegroundWindow()` returns non-zero and the harness can take
   the foreground). If the desktop is locked, do NOT force it: add a NEEDS_YOU.md entry to
   run it later, record the unit-level evidence, and mark the item `done (live check
   pending)`.
3. **Commit discipline.** Commit after each green item, that item's named files plus its
   `docs/architecture.md` sync only. Plain imperative subject line (the owner rewords to
   taste later) plus the required `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
   trailer. Never `git add -A`/`-u`, never push, never amend/rebase/reset, never commit
   LOOP_PLAN.md, NEEDS_YOU.md, or Feedback.md.
4. **Scope is frozen.** Only the items below. No product-behavior changes beyond them: the
   auto-ask default stays ON (owner-confirmed 2026-08-01, with a diag-based reopen bar in
   NEEDS_YOU), `AUTO_ASK_SEC` stays 4.0, `ASK_SENTENCES` default stays 3, no new runtime
   dependencies (R16: exactly three), no UI redesign. Round-three precision, so this rule
   cannot be read against its own queue: items 15–23 *are* the scope, and the bounded UI
   they name — marker text (15), the editable draft swap (17), the reply chip (21), the
   menu offers (19) — is in scope; "no UI redesign" forbids layout, geometry, or
   interaction overhauls *beyond what an item names*, not the items themselves. Item 23's
   `docs/product.md` edit is likewise a named file, not a scope breach. Anything tempting
   beyond this list becomes a NEEDS_YOU.md proposal, not a change.
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

### 0. Commit the documentation correction pass
- Files: `docs/architecture.md` (already edited, uncommitted).
- Do: read the working-tree diff, confirm it matches the eight corrections (band label,
  "What leaves the machine", loading section, MAX_CHARS row, ASK_SENTENCES row,
  invariants 4/5, .bench row, live_check row, known-gaps section, verification note),
  run the unit suite (docs cannot break it; the run is the baseline record), commit.
- Status: done — committed by the owner's request, 2026-08-01
- Evidence: commit c9aabc6 (+86/−17); baseline `uv run python -m unittest discover -s tests`
  = 455 tests, OK, 3.6 s (the architecture doc's Verification row still says 437 — the
  suite has grown; item 1's harness additions should update that row's count when they land)

### 1. Operation identity — stale CLI results can never overwrite newer intent
- Files: `flow/session.py`, tests (new `tests/test_races.py` or extend `test_converse.py`).
- Instrument: a unit test with a slow fake refine (event-controlled) reproducing the
  compound race: converse mode → draft A → semantic rewrite in flight → user speech
  appends B → state stomped to DRAFT → auto-ask fires and sends → stale refine returns
  and resurrects revised-A as a fresh draft. Assert today's wrong behavior first, then
  invert the assertions.
- Fix shape: a monotonically increasing operation id plus a draft revision counter
  (bumped on every `Draft` mutation). `_start_refine` records both; `_pump_refine`
  applies only if that operation is still current AND the revision is unchanged,
  otherwise emits a visible note ("discarded a stale rewrite — the draft moved on") and
  leaves the draft alone. Refuse (with a note) starting a second refine while one is in
  flight, the way `send()` already refuses. `_after_draft_change` must not downgrade
  REFINING/ASKING, and `_auto_ask_armed` must consult in-flight CLI work directly rather
  than trusting `state`. `_pump_ask` must not set IDLE when a refine started meanwhile.
- Acceptance: new tests green, whole suite green, [selfdrive] 64/64.
- Doc sync: close gap 1 in §10; add the "an old result never overwrites newer intent"
  invariant the feedback asked for.
- Status: done — commit 650e09c, 2026-08-01
- Evidence: new `tests/test_races.py`, 10 checks. **Before:** 9 failed / 1 passed —
  `state` was DRAFT not REFINING after speech during a rewrite; `send()` returned
  'widen the column and use the users table' instead of refusing; `auto_ask_in` was
  4.00 s while the rewrite was out; the compound case asked `['widen the column and
  use the users table']` with no press; a second `_route` started a 2nd refine (2 != 1);
  `Draft` had no `revision`. The one pass is the control (an untouched draft still gets
  its rewrite). **After:** 10/10. Full suite 455 → 465 tests, OK, 3.3 s → 3.5 s.
  `scripts/selfdrive.py` 64/64 (live codex call included).
  Doc: gap 1 removed and the remaining gaps renumbered 1–3 (so items 3 and 4 below now
  target **gap 3**, not gap 4); invariant 11 added; States table notes that a CLI state
  is held for the whole call; unit-layer row updated 437 → 465.
  Trailer: used `Co-Authored-By: Claude Opus 5` — this loop is running on Opus 5, and
  the Rules' "Fable 5" would have misattributed it. Recent history uses both.

### 2. Subprocess lifecycle — cancellation and clean shutdown
- Files: `flow/refine.py`, `flow/session.py`, tests.
- Instrument: a test spawning a deliberately slow child through the refine path and
  asserting today it outlives `Session.close()`; then asserting it does not.
- Fix shape: extract the one duplicated subprocess block in `refine()`/`ask()` into a
  single module-level `_invoke(cli, prompt, timeout, cwd, cancel)` using `Popen`, so a
  `threading.Event` can abandon a call early and `close()` can terminate in-flight
  children. On Windows, killing the *tree* needs `taskkill /PID <pid> /T /F` (stdlib
  subprocess — no new dependency) with `proc.kill()` as fallback. This is deliberately
  NOT a backend framework — one helper, same two public functions (Feedback item 8's
  warning applies).
- Acceptance: suite green, [selfdrive] 64/64, no orphaned `codex`/`node` after the test.
- Doc sync: close gap 2 in §10; update the refine/ask thread-table rows.
- Status: done — commit 49bc93e, 2026-08-01
- Evidence: reproduced against the shipped code (stashed the fix, ran a standalone
  driver). **Before:** the `refine` thread was still alive 3.0 s after `Session.close()`
  with its child still sleeping; a 0.4 s timeout returned after **1.37 s** and the CLI's
  grandchild ran to completion anyway; `refine(cancel=…)` was a TypeError — no seam
  existed. **After:** new `tests/test_lifecycle.py`, 8 checks, all green — close()
  joins the refine thread in <3 s and the child's completion marker never appears;
  timeout and cancel both end the grandchild; 200 kB on both pipes does not deadlock.
  Full suite 465 → 473 tests, OK, 3.5 s → **9.0 s** (test_lifecycle is ~5.5 s of it,
  spent proving absence; recorded in the architecture doc's unit-layer row).
  `scripts/selfdrive.py`: 63/64 on the first run — `spoken: 'capitalize sameer'`
  mis-decoded, a live-SAPI/Whisper check with no CLI in it — then **64/64** on re-run.
  Not treated as a regression: the path is local-edit only and untouched by this item.
  Collateral: `test_refine.py`, `test_polish.py`, `test_thread.py` mocked
  `subprocess.run`; without updating them they invoked the real `codex` (suite went to
  80 s, 13 failures). They now mock `subprocess.Popen` through a local `fake_popen`.
  Doc: gap 1 (was 2) removed, remaining gaps renumbered 1–2 (**item 3 and item 4 below
  now target gap 2**); invariant 12 added; thread-table refine/ask rows rewritten;
  TIMEOUT_SEC row gained the 1.37 s measurement; unit-layer row 465 → 473.

### 3. Foreground revalidation before Ctrl-V
- Files: `flow/inject.py`, `tests/test_inject_target.py`.
- Instrument: unit test monkeypatching `foreground_hwnd` so the live foreground is a
  third window ≠ caller's hwnd ≠ Flow; assert today the paste proceeds against the
  caller's classification, then assert it refuses.
- Fix shape: in `resolve()`/`paste()`, when the caller named an hwnd and the live
  foreground is neither Flow (already refused) nor that hwnd, refuse with a warning:
  "not pasted: the target window changed before Send." Keep the existing behavior when
  no hwnd was passed.
- Acceptance: suite green, [send-live] 18/18 (or NEEDS_YOU entry if desktop locked).
- Doc sync: close the first half of gap 4; extend invariant 10's story in §7.
- Status: done — commit b84c0d8, 2026-08-01
- Evidence: **Before:** with the live foreground a third window (0x33) and the caller
  naming 0x22, `paste("deploy it\n", hwnd=0x22)` returned **True** — clipboard written,
  Ctrl-V sent — and `resolve()` reported `cmd.exe` (the tracked window) rather than
  `Code.exe` (the one that would actually receive it). 5 of 32 checks in
  `test_inject_target.py` failed. **After:** 32/32; the refusal fires before the
  clipboard is touched and names what has the focus. Full suite 473 → **477 tests, OK,
  8.9 s**. `scripts/send_check.py --live` **18/18** on an unlocked desktop (foreground
  was non-zero and the harness took it) — the ordinary-window and console cases both
  kept focus through the real click, so the revalidation passed rather than being
  skipped.
  Note: the existing `test_the_tracked_window_wins_over_the_foreground` asserted the
  defect and is replaced. That branch only ever differed from the live answer in the
  case now refused, so nothing else relied on it.
  Doc: gap 2 narrowed to the clipboard-restore half only; invariant 10 rewritten as
  "pastes into the window it was aimed at, or into nothing"; §7 gained a fourth item;
  unit-layer row 473 → 477.

### 4. Clipboard restore guarded by sequence number
- Files: `flow/inject.py`, tests.
- Instrument: unit test monkeypatching a fake `GetClipboardSequenceNumber` that changes
  between write and restore; assert today the restore overwrites, then that it skips
  with a warning line.
- Fix shape: declare `user32.GetClipboardSequenceNumber`; capture the sequence after
  writing Flow's text; in `restore()`, re-check and only write `previous` back if the
  sequence is unchanged — otherwise leave the user's newer clipboard alone and record a
  `take_warnings()` line. Document (comment) the known limit that a non-text previous
  clipboard (image, files) is never captured and therefore never restored.
- Acceptance: suite green, [send-live] as in item 3.
- Doc sync: close the second half of gap 4.
- Status: done — commit cf8cdb1, 2026-08-01
- Evidence: **Before** (stashed the fix, ran a standalone driver with a copy simulated
  during the pause) the clipboard writes came out in this order — `'deploy it'`,
  `<user copies something new>`, `'what the user had'` — with **no warning**, i.e. the
  user's newer clipboard was silently replaced by their newer one. None of the seams
  existed (`clipboard_sequence`, `RESTORE_DELAY_SEC`, `_warn`,
  `GetClipboardSequenceNumber`: all absent). **After:** 39/39 in
  `test_inject_target.py`; an untouched clipboard is put back, a changed counter keeps
  what the user copied and records "kept what you copied since", and a counter of 0
  restores as before. Full suite 477 → **484 tests, OK, 9.1 s**.
  `scripts/send_check.py --live` **18/18** on an unlocked desktop (`GetForegroundWindow`
  4195520, `GetClipboardSequenceNumber` 8946 — a real reading, so the new ctypes
  declaration is exercised).
  Beyond the item, and needed for it: `_WARNINGS` is now behind a lock. The restore
  thread is the first thing to append from off the UI thread, and `take_warnings`
  copies-then-clears, so a line landing between those two statements was dropped without
  trace. Proven by a 2000-line concurrent drain test.
  Doc: gap 2's clipboard half closed and the entry replaced by the *late-warning* gap
  this uncovered (see NEEDS_YOU); §7 gained the borrow/return paragraph incl. the
  image-clipboard limit; thread table row renamed to `clipboard-restore` with the
  sequence check; unit-layer row 477 → 484.

### 5. Microphone overflow is surfaced, not just counted
- Files: `flow/session.py` (health pump), `flow/audio.py` if a getter helps, tests.
- Instrument: unit test with a fake mic whose `dropped` grows between ticks; assert no
  event today, then an event after.
- Fix shape: `_pump_health` tracks the last seen `mic.dropped`; on growth emit one event
  ("mic overflowed: ~N ms lost — the UI was held too long") with N = delta × 64 ms, and
  keep a session-level cumulative counter for diagnostics (item 9). No per-block spam.
- Acceptance: suite green.
- Doc sync: restore invariant 4 toward "nothing is dropped silently", keeping the honest
  note about the menu's modal loop as the cause rather than as an open gap.
- Status: done — commit ada7d34, 2026-08-01
- Evidence: new `TestOverflowIsSurfaced` in `tests/test_longrun.py`, 8 checks.
  **Before:** with a fake mic whose `dropped` grew from 0 → 5 → 256 between ticks, the
  note stream was **`''`** every time — nothing emitted at any size — and
  `s.mic_dropped` did not exist (4 failures + 3 errors of 15 in the module).
  **After:** 15/15. 5 blocks reports "320 ms", 256 blocks reports "16.4 s", a steady
  counter over 10 ticks says nothing, a second growth reports only the new loss
  (256 ms), a counter that restarts is not reported as a loss, and a mic with no
  counter at all is not a crash. Full suite 484 → **492 tests, OK, 9.1 s**.
  Spam analysis (in the code comment): checking every tick is safe because a drop
  requires a full 256-block queue, the next tick drains it, and the next drop is
  another ~16 s of stalling away — bursts, one note each.
  `flow/audio.py` was left alone: `Mic.dropped` is already public and the session reads
  it through `getattr`, so no getter was needed.
  Doc: invariant 4 restored to cover the microphone, with the honest second half (the
  audio does not come back — the undo stack holds words, nothing holds sound); §2 mic
  row names `_pump_overflow`; unit-layer row 484 → 492.

### 6. Say so when only the tail was refined or asked
- Files: `flow/session.py` and/or `flow/refine.py`, tests.
- Instrument: tests with a >`MAX_CHARS` draft/question asserting no note today, then the
  note.
- Fix shape: when `len(text) > refine.MAX_CHARS`, emit "refined the final N characters —
  earlier text left unchanged" (Refine) / "sent the final N characters of the question"
  (Ask), computing N from `_split_tail` so the number is the truth, not an estimate.
- Acceptance: suite green.
- Doc sync: drop "queued work" from the MAX_CHARS row.
- Status: done — commit d02651d, 2026-08-01
- Evidence: new `TestTheBoundOnInputIsVisible` + `TestTailSent` in `tests/test_refine.py`.
  **Before:** a 6300-character draft through `_start_refine` produced the single note
  `"refining via CLI: 'make it formal'"`, and the same question through `_start_ask`
  produced `"asking…"` — nothing about length on either path (3 failures + 3 errors of
  20 in the module). **After:** 20/20. Full suite 492 → **501 tests, OK, 9.9 s**.
  The number is `refine.tail_sent()`, not the constant: measured on that draft,
  **1995** characters go, not `MAX_CHARS` = 2000, because the cut walks to a sentence
  boundary. A test asserts the reported figure equals the real cut and is strictly less
  than MAX_CHARS, so a note quoting the cap would fail.
  Wordings deliberately differ — Refine promises "the text before that is left as it is"
  (the head is reattached), Ask says "the CLI never saw the start of it" (the head is
  discarded); one test asserts the Ask note does *not* make the Refine promise.
  Doc: MAX_CHARS row's "queued work" replaced with what now happens and the 1995 vs 2000
  figure; unit-layer row 492 → 501.

### 7. Persist the auto-ask preference
- Files: `flow/profile.py`, `flow/session.py`, `flow/__main__.py` wiring, tests.
- Fix shape: additive `auto_ask` field in the profile (absent → True, so nothing changes
  for existing users — the DEFAULT STAYS ON per Rules); `Session` reads it at init when a
  profile is present; `toggle_auto_ask` writes it back through the same save path voices
  use. Schema stays 1 (every read has a fallback, as `voice` already demonstrates).
- Acceptance: suite green, `tests/test_profile.py` extended.
- Doc sync: §9 profile row mentions the field.
- Status: done — commit 2787b2a, 2026-08-01
- Evidence: new `TestTheAutoAskChoiceIsRemembered` in `tests/test_profile.py`, 8 checks.
  **Before:** `Profile` had no `auto_ask` attribute at all (5 errors), and a session
  built from a profile with the preference set still came up `True` (1 failure) — 6 of
  50 in the module. **After:** 50/50. Full suite 501 → **509 tests, OK, 9.3 s**.
  Two halves were missing, not one: besides the profile field, `__main__` assigned
  `session.auto_ask = not args.no_auto_ask` **unconditionally**, so the absence of a
  flag would have overwritten a stored preference on every launch. Now `--no-auto-ask`
  wins over the profile and the profile over the default, matching `--voice`.
  Default stays ON and schema stays 1, per Rules: absent reads as on, and so does a
  stored `null` (`bool(None)` is False, which would turn "never written" into a
  deliberate off — there is a test for exactly that).
  Caveat: the `__main__` line is verified by reading, not by a test. Nothing in the
  suite drives `main()`'s argument wiring because it ends in `Pill.mainloop()`; that is
  a pre-existing harness gap, not one this item introduced.
  Doc: §9 profile row lists the field and the additive/fallback reasoning; invariant 5
  now says the choice is remembered; unit-layer row 501 → 509.

### 8. Key calibration to the input device
- Files: `flow/profile.py`, `flow/calibrate.py`, `flow/session.py`, tests.
- Fix shape: record the input device name alongside `record_calibration`; at session
  start (and after a mic restart lands on a different device), if the active input
  device name differs from the calibrated one, emit a note suggesting recalibration.
  Advisory only — do not discard or refuse the existing calibration.
- Acceptance: suite green.
- Doc sync: §9 profile row; §8 note on `MIC_CHECK_SEC` recovery.
- Status: done — commit 1aee998, 2026-08-01
- Evidence: new `TestCalibrationRemembersItsMicrophone` (13 checks) + `TestTheMicCanNameItself`
  in `tests/test_profile.py`. **Before:** 13 errors of 64 in the module —
  `record_calibration()` took no `device`, `Profile` had no `calibrated_device`, and
  `Mic` had no `device_name`; a session started on a different microphone emitted
  nothing. **After:** 64/64. Full suite 509 → **523 tests, OK, 10.0 s**.
  Verified against the real device: unopened and opened both report
  `'OBSBOT Tiny 3 Lite Microphone ('` — host-API truncated at 31 chars by MME, which is
  fine for something compared rather than parsed — and an impossible index returns `''`.
  Advisory is enforced by a test: after a mismatch is reported, `calibrate.apply()` still
  pushes the stored floor (−96.7 dB) into the live gate.
  Harness correction mid-item: the restart test never reached `mic.restart()` because
  the fake always reported `active`. Fixed the fake (an unplug now flips `active` and the
  reopen lands on a different name), not the assertion; it now also asserts `restarts == 1`
  so it cannot pass without exercising the path.
  Doc: §9 profile row lists the device and the by-name-not-by-index reasoning; §8
  `MIC_CHECK_SEC` row says what a reopen can land on; unit-layer row 509 → 523.

### 9. Local, redacted diagnostics trace
- Files: new `flow/diag.py` (or smallest equivalent), `flow/session.py` hooks, tests.
- Fix shape: append-only JSONL under `~/.flow/diag.jsonl` (tests use a temp path),
  size-bounded with one rotation (`diag.jsonl.1`). Record only content-free fields:
  timestamp, state transitions, route kind, operation ids, model tier, decode/refine/ask
  durations, provider name, overflow and stale-result and echo counters, device restarts,
  target-window refusals, clipboard-restore skips, error categories. Hard deny-list —
  never transcript, draft, reply, clipboard, or lexicon text. Instrument: a test that
  drives a session containing a sentinel string through every event kind and asserts the
  sentinel never appears in the file.
- Acceptance: suite green; bounded size proven by test.
- Doc sync: new §9 row; note in §4 that the event stream now has a persistent, redacted
  shadow.
- Status: done — commit 069f869, 2026-08-01
- Evidence: new `flow/diag.py` + `tests/test_diag.py` (13 checks). Suite 523 → **536
  tests, OK, 11.2 s**; `scripts/selfdrive.py` **64/64**. Bound proven by test: at
  `max_bytes=2000` and 2000 records, both files ≤ 2000 B, exactly two files in the
  directory, newest records kept.
  **Two findings the tests produced, not the design:**
  (1) The first version defaulted `Session` to a live writer, and one unit run left
  **1513 records in the real `~/.flow/diag.jsonl`** — a Rule 5 violation. Inspected all
  33 distinct string values before deleting it: every one was a code-chosen token
  (`state`/`route`/`provider`/`reason` vocabularies), no user content, which is
  incidental evidence the redaction holds across the whole suite. Default is now
  `NullDiag`, mirroring `profile=None`.
  (2) The sentinel test passed on the first run, which proves nothing — so a hook was
  made to leak deliberately. **It did not fail**, because the route hook sat after
  `_route`'s early return for an empty draft: the commonest route in the app was traced
  nowhere. Fixed to trace at every exit; the same deliberate leak then failed with
  `'zarquon-flimflam-93471' unexpectedly found in ...`.
  Redaction design: field-name allow-list (`FIELDS`) + named deny-list (`NEVER`),
  asserted disjoint at import, + a token regex for any string value. The allow-list is
  the load-bearing one — the sentinel is 22 chars and passes the regex.
  Beyond the named files: `flow/__main__.py` creates the writer (tied to `--no-profile`)
  and says the path at startup, without which the feature is unreachable; and
  `DecodeWorker.results()` now carries the decode duration so the trace can record it
  without draining `timings`, which `scripts/soak.py` reads (one line of
  `tests/test_session.py` updated for the tuple width).
  Not traced: inject.py's target-window refusals and clipboard-restore skips. They live
  behind `take_warnings()` in a module the session cannot see — see the NEEDS_YOU entry
  about late warnings, which is the same seam.
  Doc: new §9 row; §4 gains the persistent-shadow paragraph; unit-layer row 523 → 536.

### 10. Record the version identity behind measurements
- Files: `flow/diag.py` + `flow/__main__.py` startup, possibly `flow/asr.py`, tests.
- Fix shape: at startup, off the UI thread, record into the diagnostics trace:
  `faster-whisper` and `ctranslate2` versions (importlib.metadata), the resolved HF model
  revision hashes from the local cache, Windows build, and — captured in the background
  because each costs a process start — `codex --version` / `claude --version`.
  Investigate pinning the HF revision in `WhisperModel(...)`; if the API supports it
  cleanly, pin to the currently cached revision; if not, record-only and say so here.
- Acceptance: suite green; a diag record shows every field.
- Doc sync: Verification section gains a line on where identity is recorded.
- Status: done — commit c23bbc5, 2026-08-01
- Evidence: **Before:** nothing recorded any of it; `diag` had no `component`/`version`
  fields and `flow/diag.py` had no identity section (6 new checks in `tests/test_diag.py`
  all failed to import their target). **After:** 19/19 in that module, full suite 536 →
  **542 tests, OK, 12.1 s**. Every field resolves on this machine — faster-whisper 1.2.1,
  ctranslate2 4.8.1, numpy 2.5.1, sounddevice 0.5.5, tokenizers 0.23.1, Python 3.12.10,
  Windows 10.0.26200, `model:base.en` 3d3d5dee…, `model:small.en` d1d751a5…, codex
  0.145.0, claude 2.1.218 — and all eleven values pass the redaction guard as tokens.
  **Pinning investigated and declined, with a reason.** `WhisperModel.__init__` *does*
  take `revision` (confirmed by inspecting the installed 1.2.1 signature), so the API is
  not the obstacle. The obstacle is that there is no complete table to pin from: `--model`
  accepts any name and the benchmarks use `medium`, `small` and
  `distil-large-v3` beyond the two defaults, so a pin covering `base.en`/`small.en` alone
  would silently not apply to exactly the runs whose reproducibility motivates it.
  Record-only, said so in `flow/diag.py`, `docs/architecture.md` and NEEDS_YOU.md.
  Doc: Verification section gains the identity paragraph with the measured values and the
  not-pinned reasoning; unit-layer row 536 → 542.

### 11. Name the provider before the fact (note-level only)
- Files: `flow/session.py` (`toggle_mode` note and the ASKING/REFINING notes), tests.
- Fix shape: the converse-mode note becomes "converse mode — Ask sends to codex, and the
  question leaves this machine"; the asking/refining notes name the CLI that is about to
  be used (`refine.available()` is already cheap). No pill redesign — badge placement is
  the owner's taste and sits in NEEDS_YOU.md.
- Acceptance: suite green, [selfdrive] 64/64.
- Doc sync: soften gap 3 to "note-level shipped; badge is an open design choice".
- Status: done — commit 195375c, 2026-08-01
- Evidence: new `TestTheProviderIsNamedBeforeTheFact` in `tests/test_converse.py`, 5
  checks. **Before:** switching to converse said "converse mode - press Ask to put the
  draft to the CLI" — no provider, no mention of the network; `_start_refine` said
  "refining via CLI:", `_start_ask` said "asking…". **After:** "converse mode - Ask sends
  the draft to codex, and the question leaves this machine", "refining via claude: …",
  "asking codex…", and with no CLI on PATH it says so and claims nothing leaves. Suite
  542 → **547 tests, OK, 14.2 s**; `scripts/selfdrive.py` **64/64**.
  Harness correction mid-item: the first version faked the CLI with
  `mock.Mock(**{"name": "codex"})`, and `name` is reserved in Mock's constructor — the
  note came out as `<Mock name='claude.name' id=…>`. Replaced with a real `refine.Cli`.
  Doc: gap 1 rewritten as "named in words, not on the pill" with the badge left as the
  open design question; §1's "What leaves the machine" closing paragraph updated;
  unit-layer row 542 → 547.

### 12. Re-measure the loading memory timeline
- Files: none (measurement) — updates `docs/architecture.md` numbers only.
- Do: find the existing soak/memory instrument (`.bench/soak.log` names its producer);
  re-run enough of it to record import → armed → preload-done → idle-unload RSS on this
  machine; update the loading diagram's figures and the Verification table with the date.
  If no existing script can produce this inside one iteration, defer with a NEEDS_YOU.md
  note saying exactly what to run.
- Status: done — commit df13ba8, 2026-08-01
- Evidence: measured with `scripts/soak.py`'s own PSAPI reader, driven from a scratchpad
  script (no new repo file — the item's Files line is "none"). Two runs agreeing to
  0.5 MB, models already in the HF cache.
  **Before (doc):** 43 → 181 → 450 → 100 MB, no timings, and a Verification note saying
  the arm → preload-done timeline was queued work.
  **After (measured):** import **38.3 MB** at 0.37 s; armed (`base.en` resident)
  **174.2 MB** at 1.89 s; preload done (`small.en` too) **431.7 MB** at 3.25 s; idle
  unload **82.8 MB**. The unload was reached by winding `IDLE_UNLOAD_SEC` to zero and
  ticking — the real `_pump_health` path, not a direct `unload()` call.
  Every figure moved down slightly; the shape is unchanged. Timings added because "armed"
  and "preload done" are moments and a number without one is half a fact.
  Doc: loading diagram renumbered with timings; a measured-on paragraph added above it;
  the Verification note's "queued work" sentence replaced by the result.

### 13. Settings the speaker can open and write — name, people, corrections, preferences
Owner-requested 2026-08-01, on reviewing the first live run. The shape of the request:
a place "at settings or open" where the speaker writes their name, team/family member
names, preferences that have a value, and correction slugs for words the recogniser
keeps getting wrong *despite their effort* — that last phrase is the design constraint.
- Files: `flow/lexicon.py`, `flow/asr.py`, `flow/ui.py` (menu entry), `flow/__main__.py`,
  tests.
- Design, fixed by two measurements already in the repo:
  1. **"Despite their effort" means bias already failed, so the fix is not more bias.**
     `lexicon_bench.py` measured standing hotword bias at 14–38% relative WER *harm* on
     term-free speech — the reason the lexicon is opt-in. A declared correction is
     stronger evidence than a bias hint: apply it as a **deterministic post-decode
     substitution**. Syntax joins the file the user already owns: a `wrong -> right`
     line in `~/.flow/lexicon.txt` (the same arrow the profile's learned pairs use).
     Plain terms keep meaning "bias toward this"; arrow lines mean "when the decoder
     writes this word, write that one instead". Whole-word, case-insensitive on the
     wrong side, right side verbatim, applied in `WhisperTranscriber.text()` after
     `normalise` — microseconds, zero acoustic cost, and exactly the live_check item-2
     failure ("Change Semir to Samir" escalated to a 7 s CLI call because the name
     never survived decoding).
  2. **"Open" means a menu entry, not a settings framework.** The right-click menu
     gains "Open settings folder" — `os.startfile` on `~/.flow` (stdlib, R16 intact).
     First open creates `lexicon.txt` from a commented template naming all three uses:
     your name and your people as terms (with one honest line on the measured cost of
     biasing), corrections as arrows, and a pointer at `profile.json` for preferences
     that have a value (`voice`, `auto_ask` — both already hand-editable JSON).
- Instrument first: parse tests (arrows and terms coexist, comments still work, the
  64-term cap counts both); substitution tests (whole-word only, case preserved on the
  right side, nothing fires inside words); a replay test asserting the live_check
  item-2 utterance routes `local/replace` once the pair exists; menu-entry test in the
  `_pump_warnings` style. Before: the pair file syntax parses as two ordinary terms and
  biases toward the *wrong* spelling too.
- Out of scope unless the owner says otherwise: the *voice* mispronouncing names when
  reading replies aloud is `speak.py` territory (SAPI lexicons), a separate item.
- Status: done — commit ea8d2bb, 2026-08-01
- Evidence: 30 new checks in `tests/test_lexicon.py` (module 19 → 49). **Before:** none
  of them could run — `pairs`, `substitute`, `TEMPLATE`, `ensure`, `Lexicon.pairs`,
  `Lexicon.apply` and `Pill._open_settings` were all absent, so the module failed at
  import. The behaviour underneath, measured against the shipped code: `parse` on
  `"Samir\nsemir -> Samir\nkubectl"` returned **`['Samir', 'semir -> Samir', 'kubectl']`**
  and the prompt built from it was **`'Samir semir -> Samir kubectl'`** — the arrow line
  became an ordinary term, biasing the decoder toward the misspelling the user was
  correcting *and* toward a literal `->`. And the replay: run 1's item 2,
  `plan("Change Semir to Samir", DRAFT)` routed **`semantic/`**, which in the app is a
  rescue re-decode plus a ~7 s CLI call. **After:** 49/49 in the module; the same
  utterance through a lexicon holding `semir -> Samir` routes **`local/replace`**, and
  the pair adds nothing to `hotwords()`. Full suite 558 → **588 tests, OK, 14.9 s**.
  `scripts/selfdrive.py` **64/64** — run because this item changes what `asr.text()`
  returns, which is the one path a live-ASR harness can see and a fake transcriber
  cannot; its learning check still promotes `sameer -> Samir` to a hotword, so the
  profile's inferred pairs are untouched by the declared ones.
  Distrusting the green: the substitution line was removed from `flow/asr.py` and the
  suite re-run — exactly one failure, `'Change Semir to Samir' != 'Change Samir to
  Samir'` — so the check bites at the seam it claims to.
  Two decisions the design forced, both recorded in the code rather than guessed:
  corrections do **not** become hotwords (adding either side buys back the measured
  14–38% harm the item exists to avoid), and they are applied in **one pass** (`a -> b`
  then `b -> c` turning "a" into "c" makes the file's meaning depend on line order, and
  a cycle would not terminate).
  Beyond the named files, and needed for it: `Pill.__init__` gained `settings_path`, so
  the menu opens the lexicon Flow is actually reading — `--lexicon elsewhere.txt` would
  otherwise send the user to edit a file nothing loads — and `--no-lexicon` is pointed
  at the real settings folder rather than at `NUL_PATH`, which sits inside the package
  and must never exist.
  Doc: §1 module table row; the §2 pipeline gained a `Lexicon.apply` stage between the
  drop filter and the router; `MAX_TERMS` row says the cap is shared; the §9
  `lexicon.txt` row rewritten (it is no longer "never written by Flow" — once, if
  missing, from the menu) plus a paragraph on why there is no settings dialog;
  unit-layer row 547 → 588 and the Verification table's unit row, stale at 437 since
  before this loop began, re-read to 588.
  Not done here: `README.md` describes the file's format in four places (lines 111,
  521, 562, 610) and is now behind the code. Rule 3 scopes the commit to the item's
  named files, so it is a NEEDS_YOU entry rather than an unnamed file in this commit.

### 14. Grammar coverage from the first live runs
Three live runs of the same sheet (2026-08-01): **7/11, 8/11, 6/11 — and no two runs
miss the same set.** Per item across three takes: 2, 3 and 11 hit every run; 1, 4, 6,
8 and 10 hit two of three; 5, 7 and 9 hit once; nothing missed all three. The
reframing holds and hardens: the dominant failure is ASR variance on the command
phrase itself, a small number of stable gaps sit underneath, and a single take of the
sheet is not a measurement of anything.
- Files: `flow/edits.py`, `scripts/live_check.py`, tests (replay fixtures from all
  three runs — run 3 at `b268498`, run 2 at `bdfffb3`, run 1 at `5649ee3`).
- The stable, fixable part:
  - "Lower case release notes" (run 2) routed `append`: the grammar knows `lowercase`
    as one token and not `lower case` as two. Same family as the verb table; small.
  - The "bit about" question is **answered by run 3, before any test existed**: run 1's
    "Delete the bit about standard." missed without the article, run 2's "…about the
    standup." hit, and run 3's "…about the standard" missed *with* the article — so
    the article was never the difference. A mis-heard target absent from the draft is
    ("standard" vs the draft's "standup"), and that is `MATCH_THRESHOLD` 0.82
    territory, not phrase grammar. The fixture pins today's routing; moving a
    threshold that was swept against 354 false-span candidates is a re-measured
    decision, never a quick fix.
- New in run 3, recorded with its numbers: **2 of 33 spoken commands became garbled
  semantic instructions** — "Make it a drop a drop." and "Change a bit used into an
  aspect." both routed `semantic`, which in the app means a rescue re-decode and then
  a ~7 s CLI call applying a nonsense instruction to the draft. Feedback item 12
  called the false semantic operation the highest-impact failure; the live data now
  agrees at roughly 1-in-16. A sanity gate — refuse the CLI escalation when the
  instruction's content words appear in neither the draft nor the command vocabulary —
  is a design decision for the owner, parked in NEEDS_YOU.md.
- The variance part — fixtures first, fixes only where bounded: "Change Semir to
  Samir" → semantic (run 1); "Instead, try before release notes" (run 2, spoken
  "Insert draft before release notes"); "I'd do that." (run 2, the undo item); "Make
  it a proper brown." (run 1); "follow and mention the roleback plan" (run 1). Each
  becomes a replay fixture pinning today's routing, so any grammar change shows
  exactly which it moves. "brown"→"prompt" inside an already-matched "make it a
  proper X" frame is the one bounded snap worth attempting; the rest likelier need
  item 13's pairs or decode-time command bias, which is a design decision, not this
  item.
- Also note run 2's item 2: "Change Samir to Samir" scored as a hit (`local/replace`)
  — a no-op replace, since both homophones decoded identically. The scorer counts it;
  the user's name is still wrong in the draft. Item 13's substitution pair is the real
  fix; the fixture should say so.
- Instrument: the six miss-texts as fixtures against the sheet's draft; suite green
  after any fix; and extend `live_check.py --stage D` to speak each item three times
  and report per-item stability, because 7/11 and 8/11 on consecutive takes means
  neither number is the truth alone.
- Status: done — commit 3152bde, 2026-08-01
- Evidence: new `tests/test_live_replay.py`, 28 checks — all 33 utterances from the
  three runs, each row carrying what the harness recorded that day *and* what the
  grammar does now, so the two columns together pin the blast radius of any change.
  **Before:** 5 failures. Two rows routed elsewhere than the table says
  (`'append/' != 'local/lower'` on run 2's "Lower case release notes";
  `'semantic/' != 'semantic/polish'` on run 1's "Make it a proper brown."), the derived
  scores were [7, 8, 6] where the table claims [8, 9, 6], and the stable-item set was
  {3, 11} where it claims {3, 4, 11}. **After:** 28/28. Full suite 588 → **616 tests,
  OK, 15.0 s**.
  `scripts/command_bench.py` run before and after and **identical line for line** —
  recall 100% snapped on all six corruption classes, 5/20 adversarial misroutes,
  0 misroutes on 580 real utterances, threshold sweep unchanged — and its own
  `.bench/accent/command-bench.json` came back byte-identical, so the two fixes cost
  nothing where the grammar was already measured. `scripts/selfdrive.py` **64/64**.
  **A finding the fixtures produced immediately:** this plan's own summary (and the
  NEEDS_YOU entry quoting it) says "2, 3 and 11 hit every run". Item 2 did not — run 1
  heard "Change Semir to Samir" and escalated. **Two of eleven held across all three
  takes, not three.** That sharpens the point the runs were making rather than softening
  it; both places corrected.
  **A second finding, from a test that failed for the right reason:** the first version
  argued for a table over a threshold by asserting "brown" scores *below* "sentence"
  against "prompt". It does not — 0.36 against 0.14 — and the measurement said so. The
  true argument is the opposite and stronger: any bar low enough to admit "brown" also
  admits "proper" (0.67), "problem" (0.62) and "drop" (0.60), each of which means
  something else in the very same frame.
  Both fixes bounded: `_LOWER` accepts `lower\s?case` — a spelling variant, so it lives
  in the pattern rather than in either table, the way `_UPPER` has carried "all caps"
  and "caps" from the start — and `_MISHEARD_PROMPT` = {"brown"} is consulted only
  inside `_POLISH_FRAME`, only after the exact reading fails, and only changes *which*
  instruction a semantic plan carries, never whether one is sent. A polish substitutes
  its own CLI prompt, so the mis-heard word cannot reach the CLI even when it fires.
  Not fixed, deliberately, each pinned by a fixture that says why: the `MATCH_THRESHOLD`
  case ("standard" scores 0.667 against the draft's "standup", and a test proves the
  article was never the difference — run 3 missed *with* it, run 2 hit *without* the
  wrong word); bare "follow" for follow-up ("roleback" scored 0.938, the missing "up"
  was the failure, and admitting bare "follow" would route "follow the steps in the
  README"); the dropped word in "Insert before release nodes" ("nodes" reaches "notes"
  at 0.900 — nothing in a grammar recovers a word the decoder never produced); and the
  two garbled escalations, which stay parked in NEEDS_YOU.md as the Rules require.
  Harness: `--stage D --takes N` says each command N times and reports per-item
  stability — hits per item, what held every take, what never worked once. `stability()`
  is a separate function with 8 checks of its own, because a scorer that scores wrongly
  is worse than no scorer; `takes` is the largest attempt count and never a mean, so an
  interrupted run cannot report a run that did not happen. The default stays 1 and a
  single take now prints what it is worth ("the same sheet scored 7/11, 8/11 and 6/11 —
  use --takes 3 before believing this number") rather than tripling somebody's session
  without being asked.
  Doc: §6 gained the noun-snap paragraph with its numbers and the spelling-variant note;
  §11 gained a `tests/test_live_replay.py` row and the `--takes` sentence on the
  live_check row; unit-layer row 588 → 616; the Verification table gained a
  `command_bench` row recording the unchanged-ness.

### 15. The pill's converse marker names the CLI it will use
Owner-decided 2026-08-01 (NEEDS_YOU "Provider badge"). The last gap in §10 says the
provider is named in words and not on the pill. It closes without a redesign, because the
pill already carries a standing converse marker and only its *text* is at issue.
- Files: `flow/ui.py`, `tests/test_indicator.py`.
- Instrument first: a check that the 6 pt marker drawn at `(22, PILL_H - 7)` in converse
  mode reads `"ASK"` today **whichever CLI resolves** — assert that with a `refine.Cli`
  named `codex` and again with one named `claude`, so the test fails for the right reason
  rather than because the string is a constant. Then invert. A third check for no CLI on
  PATH. Note the mock trap item 11 hit: `mock.Mock(**{"name": "codex"})` yields
  `<Mock name='...'>` because `name` is reserved in Mock's constructor — use a real
  `refine.Cli`, as `test_converse.py` now does.
- Fix shape: the marker renders the resolved CLI's name, lowercased, in place of the
  literal `"ASK"`. Zero new pixels — the slot is already drawn and its *presence* is the
  mode signal, so the text is free. With no CLI resolved, keep `"ASK"`: naming a provider
  that is not there is worse than naming the mode. Bound the drawn token at 6 characters
  (`codex` and `claude` are 5 and 6) — the level bars occupy y 8–32 and this baseline is
  at y 33, so a long name is a collision, not a truncation.
- Acceptance: suite green. Do **not** claim the visual fit from a unit test — a string
  that passes a length assertion can still collide on screen; add the eyeball to
  NEEDS_YOU's desk list rather than asserting it here.
- Doc sync: §10's remaining gap is closed and the gaps section becomes empty — say so
  rather than deleting the heading, since "no gaps" is a claim worth dating. §1's pill
  description gains the marker's second job.
- Status: (not started)

### 16. Decoder confidence reaches the router and the trace — instrument only
Owner-decided 2026-08-01 (NEEDS_YOU "Garbled CLI escalations"). `asr.take_confidence()`
returns the worst `avg_logprob` among the last decode's kept segments, calibrated against
this speaker's own clean-speech baseline (P8, `clean.confidence_floor`). It is consumed by
`flow/calibrate.py` and `scripts/guardrail_bench.py` and by nothing on the live path: the
router decides between a local edit and a ~7 s CLI call without ever seeing how well the
decoder heard the sentence it is routing. **This item changes no behaviour.** It exists so
the gate that was declined can be re-decided on a real distribution.
- Files: `flow/session.py`, `flow/diag.py`, tests (`tests/test_diag.py`,
  `tests/test_session.py`).
- Instrument first: a test asserting that today a session routing an utterance emits no
  confidence anywhere — not on the route event, not in the trace — with a fake
  transcriber whose `take_confidence()` returns a known value that must therefore go
  nowhere. Then invert. A second check that a transcriber *without* the method (the
  fakes in `test_session.py` predate it) does not crash the route path — `getattr`, the
  way `Mic.dropped` is already read.
- Fix shape: drain the confidence alongside the text where the decode result is consumed
  and carry it onto the route record. `diag.py` gains a numeric field on the route event;
  it is a float, so it passes the token regex, but **add it to `FIELDS` explicitly** — the
  allow-list is the load-bearing half of the redaction guard and a field that arrives
  without being named there is the failure mode item 9 was built to prevent. Nothing reads
  the value to make a decision.
- Acceptance: suite green. The sentinel test in `test_diag.py` still passes — a confidence
  number is not content, and the test that proves the guard bites (deliberate leak) must
  still fail when made to leak.
- Doc sync: §9's `diag.jsonl` row lists the field; §5 notes that the confidence the drop
  filter uses is now also recorded per route.
- Status: (not started)

### 17. The draft can be edited by hand
Owner-decided 2026-08-01, in place of the sanity gate (NEEDS_YOU "Garbled CLI
escalations"). Today the only way to repair a mis-heard command is to say it again, into
the same decoder that mis-heard it — an unwinnable loop for the speaker this product is
designed for, and the reason the owner reports correcting text *after* Send. The live
sheet scored 55/73/55% against P3's ≥ 95%, so the escape hatch is not an edge case.
- Files: `flow/ui.py` (`Bubble`), `flow/session.py`, tests.
- Instrument first: a test asserting there is today no path by which a keystroke reaches
  `Draft`, and that `Draft.revision` is therefore unchanged by anything but speech and
  CLI results. Then invert: an edit applied through the new path bumps `revision`, lands
  on the undo stack, and a rewrite that was in flight across that edit is **discarded**
  by the existing invariant-11 check rather than overwriting it.
- Fix shape: the bubble's draft text becomes editable in place. Two things make this
  smaller than it looks and both are already true — **write through `Draft.set()`**, which
  calls `_remember()` and so bumps `revision` and pushes undo for free (`session.py:277`);
  and leave the router alone entirely, since a hand edit is not an utterance.
  Two things make it harder than it looks and neither may be skipped:
  1. **Invariant 10.** Flow's windows are deliberately outside the activation chain so a
     paste can never land on Flow itself. Taking keyboard focus into the bubble runs
     directly at that. Prove with a test that `inject.resolve()` still refuses a target
     resolving to Flow's own process *while the editor has focus*; if focus cannot be
     taken without weakening that refusal, **stop and write a NEEDS_YOU entry** rather
     than relaxing the invariant — Rule 8, first strike.
  2. **The microphone.** Typing while the mic is open appends whatever the room says to
     the text being typed. Suspend capture while the editor holds focus and say so, in
     the `_pump_warnings` idiom; a silently deaf microphone is the failure mode
     invariant 4 exists to forbid.
  3. **The auto-ask countdown.** The editor commits once, on close — so while the owner
     types, the session sees a settled draft and (per 2) guaranteed silence, and the
     converse countdown runs to zero against a draft that is half-edited. Speech holds
     the countdown; focus in the editor must hold it the same way, released on commit or
     cancel. A test drives converse mode, opens the editor, winds past `AUTO_ASK_SEC`,
     and asserts nothing was sent — without this the item ships a premature-fire class
     worse than the one the auto-ask decision just accepted, and the decided ~1-in-10
     reopen bar would be measuring the editor's bug, not the constant.
- Acceptance: suite green; [send-live] 18/18 if the desktop is unlocked, because this
  item touches focus and `send_check.py` is the only harness that can see focus really
  move. A NEEDS_YOU desk entry otherwise, per Rule 2.
- Doc sync: §7 gains the editor and its focus story; invariant 4's microphone half gains
  the deliberate-suspension case (said, therefore not silent); §2's pipeline shows the
  hand-edit path entering `Draft` beside the router.
- Status: (not started)

### 18. Benchmark results name the model bits that produced them
Owner-decided 2026-08-01 (NEEDS_YOU "Model revision pinning" — declined again; this
replaces it). §9 tracks `.bench/` results because "a measurement taken at a moment
cannot be re-taken", yet no bench script records which model revision produced its
numbers — item 10's identity recording reaches only the app's diag trace, which on this
machine does not exist. Until identity is in the results, the pinning decision's reopen
condition (a hash that changed between runs) cannot even be checked.
- Files: the bench writers in `scripts/` (`command_bench.py`, `accent_bench.py`,
  `lexicon_bench.py`, `guardrail_bench.py`, `live_check.py` — confirm the list by
  grepping for json writers rather than trusting this line), `flow/diag.py` (expose the
  HF-revision resolver as an importable function instead of duplicating it), tests.
- Instrument first: a test asserting today's outputs carry no `identity` key; then
  invert — each output gains one top-level `identity` block: model name → revision hash
  for every tier the run loaded, `faster-whisper`/`ctranslate2` versions, and the date.
- **The trap, named:** item 14 verified `command_bench.py` by byte-identical comparison
  of consecutive outputs, and an identity block with a date breaks that idiom. Keep
  identity under one top-level key so before/after comparisons diff everything *except*
  it, and say so in a comment where the block is written — the next person to re-run
  item 14's verification must not conclude the grammar changed because the date did.
- Acceptance: suite green; one real `command_bench.py` run (the cheapest — no audio)
  shows `base.en 3d3d5dee…`-style values resolving on this machine; the run's non-identity
  content is line-identical to the previous `.bench/accent/command-bench.json`.
- Doc sync: §9's `.bench` row gains the provenance sentence; the Verification section's
  identity paragraph extends from "recorded at app startup" to "and in every bench
  result".
- Status: (not started)

### 19. Inferred pairs surface in the menu for one-tap declaration
Owner-decided 2026-08-01 (NEEDS_YOU "Inferred pairs"). Never silent: an inferred pair is
a guess from a word-level diff and `profile.json` has yet to learn a single real one, so
nothing self-promotes. But the owner will not hand-edit `lexicon.txt` ("unless it is
exposed to UI right click … i will not be able to use it"), so consent has to cost one
tap: a pair the profile has seen `PROMOTE_AFTER` = 2 times appears in the right-click
menu — "semir → Samir — add correction?" — and the tap writes the arrow line into the
lexicon. A tap on a shown pair is a declaration; the declared/inferred boundary survives,
only the typing does not.
- Files: `flow/ui.py` (menu), `flow/profile.py` (a dismissed-pairs set, additive, schema
  stays 1 per the `voice` precedent), `flow/lexicon.py` (an append-one-line writer),
  tests (`tests/test_lexicon.py`, `tests/test_profile.py`, a menu test in the
  `_pump_warnings` idiom).
- Instrument first: today no seam exists — assert the absence at import, item 13 style.
  Then: a pair at 2 sightings yields a menu offer; at 1 sighting it does not; a tapped
  offer appends exactly one `wrong -> right` line and the rest of the file is
  byte-identical (the test writes a lexicon with comments and terms first, then diffs);
  a tapped pair stops being offered because the substitution now exists; a "never"-ed
  pair is persisted in the profile and is not offered again across a reload; the 65th
  entry is refused with a note (`MAX_TERMS` = 64 is shared, §8, and a silent drop past
  the cap is the library-truncation failure the cap exists to prevent).
- **Contract changes, named, both in the same commit's doc sync:**
  1. §9 says `lexicon.txt` is "otherwise read-only to the app" — no longer true. New
     contract, stated in §9 and in the template's comments: Flow appends one line, only
     on an explicit tap in the menu, and never edits or removes a line. The mtime-based
     re-read already picks the new pair up on the next decode; a test asserts that.
  2. §9's "the whole gap was that nobody could find it" is contradicted by the owner and
     comes out; the corrected sentence says finding it was half the gap.
- **The menu is a modal loop** (§8, invariant 4): it already costs a measured ~16 s
  stall at worst and one mic-overflow note. Bound the offers shown (3 at most, most
  recent first) so the menu does not grow with the profile; the full list has no other
  UI on purpose — this is not a settings page, and building one stays refused.
- Acceptance: suite green; [selfdrive] 64/64 (its learning check drives the same
  `PROMOTE_AFTER` counter this item reads — prove the hotword promotion it asserts is
  untouched).
- Doc sync: §9 lexicon row rewritten per the contract changes; §8 `PROMOTE_AFTER` row
  gains its second consumer; §1 menu description.
- Status: (not started)

### 20. Admit "follow and" as a follow-up — only if the corpus prices it at zero
Owner-decided 2026-08-01 (NEEDS_YOU "Three pinned misses"), conditional and
pre-authorized. Run 1's "follow and mention the roleback plan" routed `append/` because
the decoder dropped the unstressed "up" before "and" — "roleback" itself scored 0.938
and was never the problem. Bare "follow" stays out: "follow the steps in the README" is
dictation and must remain so. The candidate is the elision shape only — "follow"
directly followed by "and" (optional comma), alongside the existing "follow up" forms,
the way `_LOWER` carries `lower\s?case` as a spelling variant rather than a table entry.
- Files: `flow/edits.py` (`_FOLLOWUP`), `tests/test_edits.py`,
  `tests/test_live_replay.py` (one pinned row moves). `scripts/command_bench.py` is the
  instrument and is not modified.
- **Measure before touching the grammar** — this is the owner's admission gate, not a
  regression check after the fact: run `command_bench.py` with the change staged and
  require real-utterance misroutes **0/580**, adversarial **≤5/20**, corruption-class
  recall **100%**, threshold sweep unchanged. Anything else: revert, write the failing
  rows and their counts to NEEDS_YOU, and stop — the owner admits patterns on numbers,
  not on plausibility. (Item 14's byte-identical idiom does not apply here: if the
  corpus contains genuine "follow and" follow-ups, those rows *should* move; what must
  not move is anything that is not one.)
- Instrument first, the usual shape: "follow and mention the rollback plan" asserts
  `append/` today, `followup/` after; "follow the steps in the README" asserts `append/`
  both before and after, in the same test class so the boundary is one diff apart; the
  live_replay row for run 1 item 10 updates its now-column, which is the point of that
  file.
- Acceptance: suite green; the command_bench gate above, with its numbers in the
  Evidence line; [selfdrive] 64/64 (the routing tables changed; item 14 set the
  precedent).
- Doc sync: §6 gains the elision note with run 1's numbers beside the noun-snap
  paragraph it will sit next to.
- Status: (not started)

### 21. A reply can become the draft — the verb P9 promised
Owner-decided 2026-08-01 (NEEDS_YOU "A reply cannot become the draft"). The owner's
prompt-workshop loop — discuss in converse, refine, then send the good version to the
terminal — dead-ends because `send()` hands over the draft and the refined prompt is in
the reply. P9's own scenario promises the connection ("turn that last answer into a code
comment" and paste it); this builds it. Chip **and** spoken command; replace, never
append; taking the reply flips to dictate.
- Files: `flow/session.py` (`take_reply()`), `flow/ui.py` (chip on the bubble while a
  reply is rendered, gated the way `can_rescue` gates "Was a command"), `flow/edits.py`
  (spoken forms), tests (`tests/test_converse.py`, `tests/test_edits.py`, new checks in
  the bubble-chip idiom).
- Instrument first: assert the absence (no `take_reply`, no chip spec, no route), item 13
  style. Then, each its own check:
  1. take with an empty draft sets the draft to the reply text verbatim, through
     `Draft.set()` — the revision moves and undo holds the empty state;
  2. take with a non-empty draft replaces it, the note names what was displaced, and one
     undo restores it;
  3. **take flips `mode` to DICTATE** and the note says Send now pastes — staying in
     converse would make the next Send re-ask the answer, which is the confusion this
     item exists to remove;
  4. **take does not arm the auto-ask countdown**: wind past `AUTO_ASK_SEC` after a take
     with no new speech — nothing is sent. A taken draft is not a settled utterance;
     without this guard the trap is converse auto-asking the owner's own answer back at
     the CLI. Same class as item 17's editor hold — if 17 landed first, use its seam;
  5. take while the reply is being read aloud stops the speech (the existing interrupt
     path) — reaching for the text is "I have what I need";
  6. the chip exists only while a reply is on screen; no reply, no chip.
- Spoken forms, item 20's discipline exactly: an exact small set — "use that answer",
  "use that reply" — whole-utterance only ("use that answer in the summary" is prose and
  must stay dictation). Measure against command_bench before admitting: 0/580 new hits
  on real utterances, adversarial ≤5/20, recall 100%; a failed gate ships the chip alone
  and writes the numbers to NEEDS_YOU. The chip is the floor either way — it cannot be
  mis-decoded.
- Bounds, stated: a reply can be `ASK_ARTIFACT_MAX_CHARS` = 12 000; taking one as the
  draft is legitimate (the artifact was the deliverable). `refine.MAX_CHARS` = 2000
  still applies if the owner then *rewrites* it — the existing tail-note already says
  so, and no new truncation is added here.
- Acceptance: suite green; [selfdrive] 64/64 if the spoken form is admitted (routing
  changed), skippable if the gate shipped chip-only; the command_bench numbers in the
  Evidence line either way.
- Doc sync: §2's loop gains the take step between reply and Send; P9's row in the §1
  cross-reference notes the promised verb now exists; invariant 5 review — take is not
  a paste, so "nothing is pasted without an explicit Send" survives untouched, and the
  mode-flip note is the visible seam.
- Status: (not started)

### 22. Two spoken send triggers — a word for Send, a word for Send-then-Enter
Owner-decided 2026-08-01 (NEEDS_YOU "Spoken send trigger", all three questions
answered). The last keyboard step in the workshop loop (item 21 takes the reply, this
sends it) becomes voice: one configurable word presses Send, a second presses Send and
then submits with Enter. First feature to run at R5 and P7 directly — the safety comes
from inheriting Send's existing refusals, not from new machinery.
- Files: `flow/edits.py` (trigger route), `flow/session.py`, `flow/inject.py` (the
  Enter keystroke), `flow/profile.py` (two additive fields, schema stays 1),
  `flow/ui.py` only if the note needs a home it lacks, tests.
- Instrument first: assert the absence; then, each its own check:
  1. the trigger word as the **entire utterance** routes `send_trigger/` (plain) or
     `send_trigger/enter`; the same word embedded in a longer utterance is dictation —
     both directions in one test class, one diff apart;
  2. the trigger invokes the same `send()` the chip does: empty draft → the existing
     "nothing to send" note and **no paste, no Enter**; in-flight ask/refine → the
     existing refusal notes; target revalidation failure → refusal, and the Enter is
     never sent when the paste was not;
  3. the Enter variant sends Enter **after** the bracketed paste completes, to the
     validated target only — under `brackets_paste`, the payload stays inert and the
     single Enter is the submit, which is P7's "deliberate execution" done deliberately;
  4. in converse mode the enter suffix is meaningless (nothing is pasted) — plain and
     enter variants both behave as Ask, with a note saying so once;
  5. profile: absent fields → shipped defaults; stored words win; `--no-profile` still
     has working defaults. Defaults must work out of the box — the owner will not
     hand-edit `profile.json`, and a feature that needs an editor before first use is
     dead on arrival for its own requester.
- Word admission gate, item 20's discipline: each default word as a whole utterance
  against command_bench — 0/580 new hits, adversarial ≤5/20, recall 100%. **Defaults
  chosen by the owner 2026-08-01: `"boom"` (Send) and `"enter boom"` (Send+Enter).**
  The order is the safe one and the code comment should say so: whole-utterance
  matching means a decode that loses a word from "enter boom" yields "enter" (no
  trigger) or "boom" (paste without submit) — degradation falls away from execution.
  Known risk, recorded: "boom" is a short plosive and may decode as "bhoom" or nothing
  for the anchor accents; the lexicon's arrow lines repair a consistent bend
  (`bhoom -> boom`), the template should say so beside the correction examples, and if
  the word will not decode at the desk the fallback is renaming the default in code on
  a NEEDS_YOU report — not asking the owner to edit `profile.json`.
- Acceptance: suite green; [selfdrive] 64/64 (routing changed); **[send-live]
  mandatory for the Enter variant** — a keystroke into a real terminal is the one thing
  a unit fake cannot vouch for; if the desktop is locked, the item is `done (live check
  pending)` per Rule 2 and the NEEDS_YOU desk entry says exactly what to run.
- Doc sync: §7 gains the trigger paragraph and the Enter-after-paste ordering; §6 the
  route; invariant 5's wording review — a spoken trigger is an explicit Send, and the
  sentence should say so before somebody reads "explicit" as "clicked"; §9 profile row
  gains the two fields.
- Status: (not started)

### 23. Converse mode is a prompt workshop, grounded in a workspace — and P9 says so
Owner-decided 2026-08-01 (NEEDS_YOU "P9 decided from use"). General conversation failed
at the desk on its own merits (no internet, hallucinations); the owner's definition —
"predefined skills to help write better prompt … discuss and refine prompts only
nothing more" — becomes the product's. Three parts, one item, because each is small and
they only mean something together.
- Files: `docs/product.md` (P9 rewrite — named deliberately; Rule 6's architecture sync
  still applies on top), `flow/__main__.py`, `flow/profile.py` (additive `workspace`
  field), `flow/session.py` (ask framing), tests.
- Part 1, the wiring that was always missing: `refine_cwd` gets a value. Precedence
  matches `--voice`: `--cwd PATH` flag wins, else the profile's `workspace`, else
  today's `None`. Startup says which ("workshop: D:\dev\products\syntegris" or
  "workshop: not set — Ask runs without a project"). A stored path that no longer
  exists: say so and run without it — a startup that refuses over a stale setting is
  worse than an ungrounded ask.
- Part 2, the framing: `_start_ask` wraps the outgoing question in the workshop
  preamble — the CLI is helping refine a prompt for an agentic coding CLI, the
  workspace is X, discuss and refine only. The preamble is a module constant with a
  test asserting the draft text and workspace path both appear in what `_invoke`
  receives, and that `CONTEXT_CHARS` thread context still rides along (a workshop with
  amnesia between turns is not a workshop). The mode-switch note names the workspace —
  the visibility that pays for the stale-path risk the owner accepted.
- Part 3, the definition: P9's row rewritten around the workshop — the React-question
  scenario goes, the refine-take-send loop (items 21/22) becomes the acceptance
  narrative, and the half-duplex caveat survives untouched. P5 gains one sentence
  distinguishing polish (one-shot, in place) from the workshop (conversational).
- Instrument first: today `ask()` receives the raw draft and `cwd=None` — assert both,
  then invert both. The stale-path case has its own check.
- Acceptance: suite green; [selfdrive] 64/64 (ask path changed). The felt half —
  whether grounded answers are actually less generic — is a desk observation, not a
  unit assertion: NEEDS_YOU gets the entry ("ask the same question about your real repo
  with and without the workspace set; keep the transcript").
- Doc sync: §1's converse row, §9 profile row (`workspace`), the "What leaves the
  machine" paragraph — the preamble now leaves too, and the sentence must say so.
- Status: (not started)

## Backlog — "prepare" tier — COMPLETED in round one; nothing here for round three
(The four proposals below were appended to NEEDS_YOU.md on 2026-08-01 and have since
been decided or parked there: P1 executed as `50c2068`, P2 parked on diag evidence, P3
deliberately waiting, P4 executed — history rewritten. Do not re-append them.)

All four are written up in NEEDS_YOU.md under "Proposals from the plan's prepare tier",
2026-08-01. No behaviour changed. P3 and P4 carry facts checked today rather than assumed:
both CLIs can stream (`codex exec --json`, `claude -p --output-format=stream-json`), and
the recordings are 31 files / 30 MB entering history in exactly one commit, `979d267`,
which is already on `origin/main`.

- P1. **Ask response profiles** (Feedback item 6): concrete policy for lifting
  `ASK_SENTENCES` when the request is an artifact ("give me a prompt", structured
  output), including render-fully-speak-summary TTS behavior and the `ASK_MAX_CHARS`
  implication. Note the half-duplex stake: today a long spoken reply deafens Flow for
  minutes.
- P2. **Adaptive auto-ask timeout**: how to measure this user's within-utterance pause
  distribution into the profile before any timeout change; what sample size justifies
  offering adaptive; default flip is the owner's call.
- P3. **Streaming backend sketch** (after items 1–2): which CLI flags stream, where the
  sentence buffer sits, how operation ids gate late chunks.
- P4. **Recordings out of git history**: options with exact commands (git-filter-repo
  plan, storage alternatives, consent-scope addendum for docs/recording-kit.md), costs,
  and the point of no return. Decision stays with the owner.

## Closing summary

(Round three's closing summary is PREPENDED at the top of this file when items 15–23
are each done, blocked, or deferred — the same place rounds one and two put theirs.
Nothing is written here; this heading survives only so a diff against old revisions
anchors cleanly.)
