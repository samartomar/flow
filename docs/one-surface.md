# One surface: what Flow's final shape should be, and how the two become one

Written 2026-09-04, after reviewing both surfaces side by side — the shipped pill in
`flow/ui.py` and the compact design in `flow/ui_compact.py` — against
[product.md](product.md) and the canvas in `design/compact/`. The owner's verdict on the
compact design was that it is the one they like; this document says what that means for
the product, what the compact surface still has to absorb before it can be the *only*
surface, and the order to do it in. It is a recommendation for the owner's decision
([NEEDS_YOU.md](../NEEDS_YOU.md) carries the open entry); nothing here is decided yet.

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
| Rendering | Tk canvas, colour-keyed, aliased, DPI-unaware | GDI+ composited, per-pixel alpha, native resolution |
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

The shipped surface does not get reskinned, ported or composited — the 2026-09-04
decision already found the wall (it contains a text editor). It gets **retired**, in
stages, once the compact surface has absorbed the five things it still lacks. Until then
both stay selectable, exactly as they are now, and the compact one becomes the default.

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
