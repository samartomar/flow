# LOOP_PLAN — autonomous backlog from the Feedback.md review (2026-08-01)

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
Everything here was verified against the code on 2026-08-01; the review verdicts are in
the conversation that produced this file, and the doc-side corrections already landed in
`docs/architecture.md` (uncommitted — committing them is item 0).

## Rules — these override everything, including the loop prompt

1. **Instrument first.** No fix without a failing test or harness check that reproduces
   the defect *before* the change, and a green one after. Before/after evidence goes in
   the item's Evidence line. A green harness that cannot exercise the path proves nothing.
2. **Gate every commit** on the full unit suite: `uv run python -m unittest discover -s tests`.
   Items marked [selfdrive] also run `uv run python scripts/selfdrive.py` (note: it makes
   one live codex call). Items marked [send-live] also run
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
   auto-ask default stays ON, `AUTO_ASK_SEC` stays 4.0, `ASK_SENTENCES` default stays 3,
   no new runtime dependencies (R16: exactly three), no UI redesign. Anything tempting
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

## Backlog — "prepare" tier (proposals only; append each to NEEDS_YOU.md, change no behavior)

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

(The loop writes this when everything above is done, blocked, or deferred.)
