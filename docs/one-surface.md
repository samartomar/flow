# One surface: what Flow's final shape should be, and how the two become one

Written 2026-09-04, after reviewing both surfaces side by side — the shipped pill in
`flow/ui.py` and the compact design in `flow/ui_compact.py` — against
[product.md](product.md) and the canvas in `design/compact/`. The owner's verdict on the
compact design was that it is the one they like; this document says what that means for
the product, what the compact surface still has to absorb before it can be the *only*
surface, and the order to do it in. It is a recommendation for the owner's decision
([NEEDS_YOU.md](../NEEDS_YOU.md) carries the open entry); nothing here is decided yet.

**Decided 2026-11-23: compact only.** The owner's words, the same day as the check
below. [decisions.md](decisions.md), "One surface", is the record, with the stages and
what reopens it. The first stage is done: nobody is offered the shipped surface (the
Design row and the Classic panel row are out of Flow Home, a profile that named it is
told once and moved, and `--design` is unlisted and never stored). This page stays as
the reasoning; the order of what is left is in that entry, not in the five steps below.
The second stage, the tests sorted and the ones that reached shared code through a
Classic window ported, is recorded at the foot of this page ("Stage 2").

**Update 2026-11-23.** The owner asked what is left to adopt from the shipped surface,
or whether to ignore it in full. Checked against the code: **nothing is left to adopt.**
All five gaps below are closed (two by Flow Home, three on 2026-10-02), step 4 happened
on 2026-09-23 (`DESIGN_DEFAULT` is `"compact"`), and the owner's profile runs compact.
What stands between here and step 5 is **step 2, which was never done**:
`ui_compact.py` still imports 59 names from `ui.py` (7,936 lines), and `theme.py`,
`shell.py` and `menus.py` do not exist. Beyond that, 33 test files import the module
(1,658 tests between them, not all of them about the shipped window), nine scripts do,
and `scripts/selfdrive.py`'s gate drives `Pill`, which the order below does not
mention: it is ported to the compact surface or dropped before the class goes. The taste
call at the foot of this page stands at "nothing" today: a Type hold says "listening -
let go to paste" and names no window. The decision is still the owner's
([NEEDS_YOU.md](../NEEDS_YOU.md)).

**Update 2026-10-02.** Step 3 is **done**: the compact Refine panel carries an Edit chip
between Copy and Send, opening a `tk.Text` in its own Toplevel over the panel, with
Escape, Ctrl+Enter, and Cancel/Done buttons. Ask gets none — its panel holds a
conversation, not one prompt — and Type gets none, because paste-on-release is the point
of Type. The session seam (`begin_edit` / `commit_edit` / `cancel_edit`, and the P4
learning behind it) was already there and is used unchanged; the port added a box and a
chip. The editor is still its own window rather than a widget on the composited surface,
which is forced rather than chosen — a layered GDI+ window shows the bitmap Windows was
handed and nothing else.

**Still to do before `ui.py` goes:** steps 4 and 5 (the notes-loop strip lines, Refine's
"say more" meaning say more), then the deletion itself. That deletion is the reason this
document is still a plan: `flow/ui.py` is ~7 000 lines and the majority of the suite
exercises it directly, so retiring it is staged with the suite green at each step rather
than done in one commit.

**Update 2026-10-02 (steps 4 and 5).** Both are done. **Step 4**: `Session` emits a new
`kept` event — the compact strip says "kept", or "kept <file>" when the notes were
written to one. `ui.py` deliberately ignores it; that surface already says the whole
sentence and has a card stack to say it in. **Step 5**: the foot's "hold the mic to say
more" now means it. `Session` arms `following_up` when it delivers a refine as a result,
which is what puts the previous result into the CLI's `context`; the compact panel keeps
that result on screen and appends the new hold's words to the heard block rather than
replacing them. A failed refine is not extended — its CLI line stands in the same slot and
there is nothing there worth adding to.

**Step 5 is what `ui.py` gets retired for.** With these, the compact surface has the hand
editor, the notes loop and "say more", and the shipped surface has nothing left that the
compact one has not absorbed. `flow/ui.py` (~7 000 lines) is still on disk and still the
`"current"` design choice — deleting it means dropping ~13 test files that exercise it
directly (`test_pill.py` alone has 48 references to it), and that is a separate, staged
commit rather than something to bury under this one. The suite is green either way.

**Update 2026-09-22.** Flow Home ([decisions.md](decisions.md), "Flow Home") took two of
the five gaps below off the compact surface's list: **Settings** is Home's Models and
Settings pages rather than live rows in a setup box (the box is deleted), and **Help**
lands on Home's Voice page with the spoken commands. The other three — the hand editor,
the notes-loop strip lines, and Refine's "say more" — are still the compact surface's to
absorb. The Design row the compact menu kept moved into Home too, so the retirement in
step 5 no longer has a menu to unpick.

The standing decision it answers is the 2026-09-03 one in [decisions.md](decisions.md):
*"a second surface is a standing cost, justified only while both are real"*, reopening
when parity lands and one of the two stops being used. Parity landed on this branch, and
the owner has said which one they use.

## Where the two stand today

| | Shipped (`ui.py`, 7 539 lines, ~540 tests) | Compact (`ui_compact.py`, 2 345 lines, 151 tests) |
|---|---|---|
| The pill | A 34 px row: app slot, mic, meter, marks, three icons, a status word | A wordless 120 × 34 capsule: glyph tint = mode, ring = state, meter |
| Talking | Click to arm, or hold; the chord | Hold the pill or the chord; tap cycles the mode |
| Type | Draft held in a bubble with Send, Refine, Edit, Undo chips; sent card | Paste on release, no panel (the mini mic, drawn as the whole surface) |
| Refine | A spoken instruction, or a Refine chip, rewrites the draft in place | A mode: the panel shows heard → refined-for-this-repo → Send on purpose |
| Ask | A conversation card: question pinned, answer, older turns, Take / Copy / New | The panel: question, answer card, Copy, hold to reply |
| Rendering | GDI+ composited at native resolution since the evening of 2026-09-04, through the same painter; the hand editor is a Tk text box in its own window over the panel | GDI+ composited, per-pixel alpha, native resolution |
| Icons | One stroked glyph set shared with the compact surface since 2026-09-04 (`flow/glyphs.py`); the row and the marks keep their colours | The same glyphs, monochrome |
| Switching | Design row switches the running surface in place, keeping the session | The same row, the same switch |
| Settings | Right-click → Settings cascade: gesture, mic, model, effort, triggers, voice, panel, place, workspace, lexicon, notes, design, mic view | Right-click → three modes, Switch workspace (palette), Workbench setup (read-only), Design |
| Help | Commands sheet, welcome card, guide | None |
| Feedback | Notes on the bubble; the card; the sent card | The ring, the glyph, and a one-line strip under the pill |
| Hand editing | A real `tk.Text` editor in the bubble, with typed corrections learned (P4) | None |
| Placement | Two named places; multi-monitor re-synced every 4th frame | Drag anywhere (after the 2026-09-04 fixes: across monitors) |

Both drive the same `Session`, through the same pull contract, and that is what makes
this a surface question rather than an architecture one: nothing below the window changes
whichever way this goes.

## The recommendation

**One surface, and it is the compact one.** Not because it is smaller, but because it is
the one whose shape matches the product definition: three things a developer does with
their voice — type it, shape it for the repo, ask about the repo — on a pill that says
which one with a colour and never asks a question the gesture already answered. The
shipped pill grew a control for every capability the session gained, which is how it
came to carry eleven things on a 34 px row; the compact design started from the three
jobs and gave each one a place.

The shipped surface is not reskinned further. Later the same day it was brought to the
compact surface's rendering — native DPI, GDI+ compositing, one glyph set — and the
design switch became live, so the two are one product in every sense but the layout;
that work is what makes the retirement below a choice about *layout* rather than a
rescue from a soft, aliased row. It still gets **retired**, in stages, once the compact
surface has absorbed the five things it lacks: a second layout is a standing cost
whatever it renders like. Until then both stay selectable, one press apart, and the
compact one becomes the default.

## What the compact surface must absorb first

Ranked by how often somebody would hit the gap. Each is a piece of work with its own
commit, tests, and photograph.

### 1. Settings, without a settings dialog

The shipped Settings cascade is nineteen builder methods on `Pill`, and every one of
them is a real need: which microphone, which CLI model and effort, the chord's gesture,
the trigger words, the voice, the lexicon and notes folders. The canvas says "there is no
preferences window", and the house stance (no settings dialog, four challenges survived)
agrees — but a menu is not a dialog, and the compact surface already has the row the
canvas drew for this: **Workbench setup**, "mic, CLI, where it pastes".

The box's rows become live. Each row opens the same dark popup the shipped surface
builds for that setting, under the pointer, and the box redraws with the new value. The
builders move out of `Pill` into a surface-neutral `flow/menus.py` — functions taking
`(session, profile, say)` rather than methods reading `self.bubble` — so the shipped
surface mounts them as cascades and the compact one mounts them as row popups, from one
implementation. The box gains the rows the artboard did not draw because the canvas did
not know about them: Voice (and mute), Model · effort, Gesture, Trigger words, Lexicon.
Read-only stays read-only where it is a discovery rather than a choice (the CLI found on
PATH is a fact; which model to ask it for is a setting).

### 2. Help

A surface with three gestures and a spoken command grammar has to be able to explain
itself. `flow/help.py` is portable and already renders the commands sheet for the shipped
window. The compact menu gets **Help** beside Design — the same rule that let Design in:
*a surface may leave out anything the drawing leaves out except the way out of itself*,
and "what can I say" is part of the way out. The sheet opens as a standalone box like the
palette, keyboard-dismissed.

### 3. The hand editor, as its own box

The product's third ingredient is *prompt correction* — "the held draft you can edit by
voice before anything is sent". On the compact surface the held draft is Refine's heard
block, and voice corrections already apply to it. What is missing is the keyboard: the
shipped editor is a `tk.Text` inside the pill's window, which is also the one thing that
stops that window being composited. On the compact surface it becomes a standalone box —
an **Edit** chip on the Refine panel (there is no edit hotkey today, and the five
actions in `hotkey.DEFAULT_BINDINGS` need not grow one for this) — opening a `tk.Text`
in its own Toplevel over the panel, Enter commits, Esc leaves. `Session.begin_edit` /
`commit_edit` / `cancel_edit` are the seam and already do the P4 learning; the box is the
only new code. Type mode does not get one: paste-on-release is the point of Type.

### 4. Every message has a home

The notice strip (2026-09-04, "a wordless pill still has to say three things") is the
compact surface's one channel for words, and the 2026-09-04 fixes route the session's
`drop`, `edit`, `send` and refusal `note` events to it. What remains is the notes loop of
P9: "keep note" and "wrap up" work (they are session commands), but the surface says
nothing when a note is kept or a file is written. Two more strip lines — *kept* and the
wrapped file's leaf name — close it.

### 5. Refine's "say more" means say more

The foot's hint reads *hold the mic to say more*, and today a second hold sends a fresh
draft to be refined on its own: `send()` cleared the first one, and `_start_refine` only
passes the thread as context when `following_up` is set. For a mode whose job is shaping
one prompt, the second hold should extend the first: the heard block appends, and the
refine runs over the whole with the previous result as context. One flag in the session
(`following_up` set true after a reply-delivered refine, cleared by Send or a mode
switch) and the panel appending rather than replacing.

## Two things the shipped surface has that the compact one should *not* take

**The status word and the marks.** "LISTENING", "HELD", the marks row, the three icons —
they exist because the shipped row had to name the state in words. The ring and the
glyph now carry that, and the 2026-09-04 decision ("five meanings on one ring is already
the most it can carry") sets the line: if the surface ever needs a sixth thing said, it
gets a channel, not a hue.

**The mic view.** The shipped surface's 90 px controls-free pill (2026-09-03) was the
compact idea prototyped inside the old window. It is redundant the day the compact
surface is the default, and it goes with `ui.py`.

## One thing to decide, not build: where the words are going

The mic view showed the focused app's name for a reason the compact pill cannot answer:
*dictating into the wrong window is the one mistake a hold cannot see*. The wordless
pill shows nothing about its target. Two honest options, and it is the owner's call:

- The strip, during a Type hold only, names the target app (`app_label`, the same rule
  the shipped row uses). Words on the wordless pill, but only while the hand is on it.
- Nothing. The paste lands where the last click was, which is where the user is looking;
  the mistake is rare and the undo is Ctrl+Z.

The first is a few lines once the strip exists; the second costs nothing. Neither should
be built before the owner has said which mistake they would rather make.

## The order, and what each step is measured by

1. **Land the 2026-09-04 fixes** (this branch): the send that waits for the decoder, the
   monitor and DPI arithmetic, the events with nowhere to go, the panel that grows with
   its text, the fonts GDI+ could not see, the frame that repaints only when something
   changed. Measured by the suite and by `scripts/compact_shots.py` — a photograph per
   state, as the build brief requires.
2. **Move the shared code out of `ui.py`.** `ui_compact.py` imports forty names from
   the 7 500-line module it is meant to replace. The palette and fonts go to
   `flow/theme.py`; the windowing (`_shell_window`, `_no_activate`, `_pointer_monitor`,
   `bottom_centre`, `_dark_menu`, the clipboard borrow, the Win32 reads) to
   `flow/shell.py`; the settings builders to `flow/menus.py`. `ui.py` imports them back.
   No behaviour changes; every existing test passes unchanged. This is the step that
   makes step 5 a deletion rather than a surgery.
3. **Absorb the five gaps above**, one commit each, in the order listed. Each adds its
   shots to `compact_shots.py` and its tests to the compact suite.
4. **Flip the default.** `DESIGN_DEFAULT` becomes `"compact"`; the shipped surface stays
   selectable from both Design rows for one release; README and guide describe the
   compact gestures first. The release notes say the old surface is going and why.
5. **Retire.** One release later — the decision's own bar is "one of the two stops being
   used", and the owner is the measurement — delete `Pill`, `Bubble`, `ConversationCard`,
   `HelpWindow` and their ~540 tests, `TeeCanvas` in `paint.py` (it existed for the port
   that hit the wall), and the `design` profile field after a release of ignoring it.
   `theme.py`, `shell.py`, `menus.py` and `help.py` stay; `ui.py` is gone.

Steps 1 and 2 are days each; step 3 is the real work, roughly a week of the pace this
branch was built at; steps 4 and 5 are an afternoon each, gated by use rather than by
code.

## What this costs, said plainly

Two things are lost and should be named rather than papered over. The **draft bubble**
— seeing your words before they paste — does not exist in Type mode and never will on
this surface; somebody who wants to read before they send uses Refine, which is the mode
built for it. And the **conversation card's scrolling history** is narrower on the
compact panel, which shows the last exchange; older turns are in the thread and reach the
CLI, but the surface shows one at a time. If either turns out to matter in use, the
panel is where it would grow — the mechanism is the same band, taller.

Everything else the shipped surface does, the session does, and the compact surface
inherits by driving the same session.

## Stage 2: the tests sorted (2026-11-23)

The 33 test files that import `flow/ui.py` hold 1,659 tests. Each one was sorted by
the production code its assertion checks, and whether that code survives deleting
`Pill`, `Bubble`, `ConversationCard`, `HelpWindow` and the `ui.py` code only they use:

- **a, stays.** It tests a helper the compact pill also runs (window classification,
  Win32 reads, work area, fonts and palette, `scaled_font`, `bottom_centre`), or code
  that is not in `ui.py` at all and never needed a Classic window.
- **b, goes with the classes.** The code under test is the Classic windows': their
  drawing, chips, menus, marks row, mic view, panel widths, placement, push-to-talk
  wait, or the `--design` rebuild loop. Listed here and left in place.
- **c, ported.** It checks session or other shared code, and a Classic window was only
  the route. Each is now asserted against `Session` directly or through `CompactPill`,
  or was found already asserted that way by a named test. The originals are left in
  place: each goes with its class in stage 3, and its coverage stays behind.

A first pass was mechanical. An AST walk of each test, through its fixtures and its
helpers, including helpers imported from other test files, split the tests that never
reach a Classic window or a Classic-only `ui.py` name from the 610 that do. Those 610
were then read one by one. "Mixed" below is a test with both a (b) half and an (a) or
(c) half.

| File | Tests | a | b | c | Kind c: ported to, or already asserted by |
|---|---:|---:|---:|---:|---|
| `test_ask_chord.py` | 55 | 52 | 3 | 0 | — (b: `TestGTheClassicPillSwitchesSidesToo`; compact's is `TestFTheCompactPillSwitchesSides`) |
| `test_bubble.py` | 37 | 0 | 37 | 0 | — |
| `test_card.py` | 56 | 1 | 55 | 0 | — |
| `test_chord.py` | 74 | 69 | 4 | 1 | The tripwire on the chord's four words in `ui.py`'s dispatch → `test_and_they_are_the_words_the_compact_pill_dispatches_on`, same class, reading `ui_compact.py`. Mixed (a): `test_a_pill_fixture_can_never_reach_for_tk` loses its `Pill` line in stage 3 |
| `test_compact_pass.py` | 15 | 0 | 15 | 0 | — (the Classic pill's 2026-09-01 "compact pass", not `CompactPill`) |
| `test_compact_screen.py` | 31 | 31 | 0 | 0 | — |
| `test_composite.py` | 46 | 18 | 28 | 0 | — |
| `test_converse.py` | 85 | 84 | 1 | 0 | — (b: the Classic row's CLI marker) |
| `test_editor.py` | 93 | 52 | 37 | 4 | `TestTypingAFixTeachesInLiteToo` (2) → `TestALiteSessionLearnsFromTheSameSeam`. `TestAnEditorThatCannotHearIsClosed` (2, mixed): the session half is already asserted by `TestTheEditIsAnOrdinaryDraftChange` |
| `test_glyphs.py` | 15 | 14 | 1 | 0 | — Mixed (a): `test_the_compact_mic_and_the_shipped_mic_are_one_drawing` loses its `ui.glyphs` line in stage 3 |
| `test_help.py` | 62 | 36 | 19 | 7 | `test_the_guide_still_shells_out_to_the_browser` → `TestTheGuideOpensInTheBrowser` (2). The `legend_rows` half of `test_the_legend_matches_...` → `test_the_legend_names_no_pill_colour_the_app_stopped_drawing`. Five mixed (`TestTheWindowShowsTheGeneratedContent` 3, `TestTheMenuReachesIt` 2): the `help.rows` half is already asserted by `TestItNamesWhatRegistered`, `TestItNamesTheWordsCurrentlyConfigured` and `TestEveryExampleIsRealSpeech` |
| `test_history.py` | 84 | 81 | 3 | 0 | — (b: `TestTheClassicSurface`; compact's is `TestTheCompactSurfaceHandsOver`) |
| `test_hotkey.py` | 56 | 48 | 0 | 8 | The startup-block launches (7, and the AltGr one): changed in place to launch with no `--design` and `flow.ui_compact.CompactPill` patched. The file no longer imports `flow.ui` |
| `test_icon.py` | 14 | 14 | 0 | 0 | — Mixed (a): `test_both_pills_call_it` drops `"ui.py"` from its loop in stage 3 |
| `test_indicator.py` | 35 | 20 | 15 | 0 | — |
| `test_inject_target.py` | 111 | 110 | 1 | 0 | — (b, and not portable: see the gaps below) |
| `test_lexicon.py` | 49 | 45 | 2 | 2 | The `lexicon.ensure` half of the settings-folder first and second open → `TestTheTemplateIsWrittenOnceAndNeverOver` (2) |
| `test_lite.py` | 34 | 20 | 13 | 1 | `test_both_spoken_triggers_reach_it_through_the_router` (mixed): the router half is already asserted by `test_triggers.py`'s `test_the_session_asks_rather_than_pasting_on_its_own` and `test_no_profile_at_all_still_has_working_defaults` |
| `test_main.py` | 49 | 12 | 8 | 29 | 28 launch tests changed in place: `launch()` and its siblings launch with no `--design` and `CompactPill` patched. The default-launch half of `test_the_process_is_made_dpi_aware_before_any_window_exists` → `test_the_process_is_made_dpi_aware_before_the_pill_exists`. The 8 b are the `TestTheDesignSwitch` cases that pin `--design current` and the rebuild loop |
| `test_menu.py` | 35 | 0 | 35 | 0 | — (its fixtures are imported elsewhere: see stage 3) |
| `test_mic.py` | 77 | 3 | 71 | 3 | The profile halves (`mic` and `mic_at` round trip, a junk `mic_at` still saves) → `test_profile.py` `TestTheClassicPillsFieldsStillLoad` (2) |
| `test_offers.py` | 23 | 16 | 7 | 0 | — (b: the Classic draft menu; the lexicon and profile halves are asserted by this file's other classes) |
| `test_overlay.py` | 17 | 0 | 14 | 3 | `TestTheProfileRemembersIt` (`panel` survives a save, its default, a nonsense value is named) → `test_profile.py` `TestTheClassicPillsFieldsStillLoad` (3) |
| `test_paint.py` | 30 | 30 | 0 | 0 | — |
| `test_pill.py` | 130 | 47 | 80 | 3 | `test_the_mode_glyph_is_a_pen_in_refine_not_a_bubble` → `test_glyphs.py` `test_the_pen_is_its_own_mark_and_the_bubble_has_its_tail`. The unknown-mode and muted-speaker cases are already asserted by `test_a_fourth_mode_raises_rather_than_drawing_the_third` and `test_the_speakers_mute_is_one_more_line_and_no_waves` |
| `test_resilience.py` | 78 | 70 | 7 | 1 | `test_no_state_the_pill_paints_green_survives_the_loss` → `test_no_state_the_compact_ring_paints_green_survives_the_loss`, same class, against `ui_compact.RING` |
| `test_scale.py` | 37 | 19 | 17 | 1 | `test_the_editor_asks_the_module_for_its_own` → `TestTheCompactEditorsFontReadsTheModuleScale` (2), which sets `ui.SCALE` itself |
| `test_stats.py` | 60 | 54 | 0 | 6 | `test_it_exits_before_a_model_a_microphone_or_a_window` changed in place to watch `CompactPill`. `TestTheHelpSheetCarriesTodaysWords` (5, mixed): the `stats.today_note` half → `TestTodaysRowSaysWhatTheTraceHolds` (5) |
| `test_switch.py` | 20 | 16 | 2 | 2 | `TestASecondTkInOneProcess`'s two round trips → `test_the_compact_pill_is_built_detached_and_built_again`, same class: a real Tk over a real `Session`. 15 of the 16 a loop over `SURFACES`, so stage 3 drops the `current` row rather than the test |
| `test_talk.py` | 49 | 0 | 37 | 12 | → new `tests/test_talk_session.py` (11): the stream that lingers after a release, the hold that gives back what it took, the commit a release makes, nothing heard between holds |
| `test_tray.py` | 25 | 9 | 16 | 0 | — |
| `test_triggers.py` | 49 | 43 | 0 | 6 | `TestItPressesTheSameButton` (5) and `TestConverseIgnoresTheSuffix` (1) → `TestTheCompactPillPressesTheSameButton` and `TestConverseIgnoresTheSuffixOnTheCompactPill`, through `CompactPill._send` over a real `Session` |
| `test_version.py` | 28 | 25 | 3 | 0 | — |
| **33 files** | **1,659** | **1,039** | **531** | **89** | 37 launch tests changed in place; 42 ported into 41 new tests; 10 already asserted elsewhere |

One file outside the 33 belongs in the same list: `test_notes.py`
`TestTheMenuIsTheFloor` (5 tests, kind b) builds the Classic menu through
`test_menu.py`'s `Menu` fixture.

### Classic guarantees with no compact counterpart

These are kind b, because the code under test is the Classic pill's. But the
guarantees they pin are gone the day it is deleted. None can be ported without product
code, so none was, and they are the owner's to decide before stage 3:

1. **The hold ceiling.** `Pill._pump_talk` ends a hold whose release never arrives
   after `PTT_MAX_HOLD_SEC` (120 s), and keeps the words (`test_talk.py`
   `TestTheTwoTimeoutsAreNotHypothetical`, 3 cases). `CompactPill` has the paste-wait
   ceiling and not this one: a dropped keyup leaves the hold open.
2. **Late paste warnings.** `Pill._pump_warnings` drains `inject`'s warnings every
   frame (`test_inject_target.py` `TestLateWarningsReachTheBubble`). `ui_compact.py`
   never calls `take_warnings`, so the clipboard-restore skip waits for the next Send.
3. **A hold while the hand editor is open.** `Pill._talk_start` refuses it and says
   why. `CompactPill._talk_start` has no such check.
4. **The editor's focus check.** `Bubble._edit` closes the editor when Windows refuses
   it the focus. `CompactPill._open_editor` does not check.
5. **Flow's own window as the paste target.** `Pill._track_target` refusing it is
   tested. Compact's copy of the method is tested only with `owned_by_flow` patched to
   False.

### Found on the way, in the compact pill (read, not run)

- **Fixed 2026-11-24.** `CompactPill._open_editor` called a bare `dev(self, …)`, so the
  Edit chip raised `NameError` after `session.begin_edit()` had run, leaving the session
  in `editing` with no box; behind it, `bring_forward()` was called with no window
  handle. Both fixed, and four tests now run the method's body (they failed before).
  Checked on real windows with a Mock session: the box opens with the text and the
  focus, and Escape, Ctrl+Enter, Cancel and Done each reach the session and close it.
- `ui.SCALE` is set only by `apply_scale`, which only `Pill.__init__` calls, so the
  compact editor's fonts (`scaled_font`) never scale above 100 %.
- `ui._load_fonts`, the GDI registration Tk-drawn text needs, is called only by
  `Pill.__init__`. A compact launch hands IBM Plex to GDI+ alone, so the compact
  surface's Tk text (the editor, the menus) may be falling back to a system face.

Left with no caller when the classes go: `help.rows`, `help.legend_rows` and
`help.open_guide` (Flow Home imports only `help.COMMANDS`); `stats.today_note`;
`refine.Cli.marker`; and the profile fields `mic` and `mic_at` as well as `design`,
`panel` and `place`. `help.exits_note` still names Classic affordances ("click the draft
to edit"), and `test_editor.py` `test_the_note_that_promises_it_still_does` pins that
wording.

### What stage 3 has to move before it deletes

- **Fixtures other files import.** From `test_menu.py`: `FakeMenu` and `FakeVar`
  (`test_ui_compact.py`, `test_compact_events.py`, `test_history.py`), and `Menu`
  (`test_mic.py`, `test_notes.py`). From `test_pill.py`: `pill` and `Canvas`
  (`test_ask_chord.py`, `test_chord.py`, `test_compact_pass.py`, and `test_history.py`
  and `test_mic.py` at module level). From `test_bubble.py`: `bubble` and `draft`
  (`test_compact_pass.py`). From `test_editor.py`: `WORK` and `MeasuringCanvas`
  (`test_bubble.py`, `test_card.py`, `test_composite.py`).
- **Kind a tests inside mostly-Classic files.** The Classic tests are cut out of these
  files class by class; the files are not deleted whole. `test_pill.py` (47: the work
  area, `_mix`, parking, the window styles), `test_composite.py` (18), `test_scale.py`
  (19, and their `ScaleCase` resets `ui.apply_scale`), `test_indicator.py` (20),
  `test_lite.py` (20), `test_switch.py` (16), `test_tray.py` (9), `test_mic.py` (3),
  `test_card.py` (1).
- **Tests that read `flow/ui.py` as text.** `test_pill.py` `TestTheMacFrame` (2, a)
  follows the shared code when step 4 moves it. Outside the 33,
  `test_ui_compact.py`'s `test_a_shipped_surface_ignores_it_because_it_already_said_more`
  and its `refine_says_more` assertion name `ui.py` too.
- **`scripts/shots.py`** imports the Classic pill. Its `FakeSession` is why the new
  round trip in `test_switch.py` uses a real `Session` instead.
