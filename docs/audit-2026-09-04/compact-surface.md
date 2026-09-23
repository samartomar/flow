# Review of the compact surface, 2026-09-04

A deep read of `flow/ui_compact.py`, `flow/paint.py`, and the session and launcher
changes on the `compact-design` branch (25 commits, `6f30dd4`..`da6c669`), done after
the build brief's seven items had landed and the owner had said the compact design is
the one they use. Two questions: where does it fail, and where is it weaker than it needs
to be. Each finding below carries its evidence — a headless reproduction, a probe, a
measurement, or the arithmetic — and the commit that closed it. The product-shape
question the same review raised is answered separately in [../one-surface.md](../one-surface.md).

The suite stood at **2536 tests, OK, 2 skipped** before any of this and at **2700, OK,
2 skipped** after the ten commits; the photographs were re-taken and are in `.shots/`.

## How it was done

The two surfaces were read side by side (`Pill` in `flow/ui.py` for the proven shape of
every mechanism the compact pill re-implements), the compact decisions in
`docs/decisions.md` were read for what was deliberate, and every suspicion was then
tested rather than argued: the send-path defects were driven against the suite's own
fixtures, the font gap was probed through GDI+ directly, the frame cost was timed on a
real window at 300 %. What could not be verified is said so.

The fixes were fanned out to five agents in isolated worktrees, partitioned by method so
they could run at once, each with its own tests in a new file and its own commit, and
merged back in order. The photographs (`scripts/compact_shots.py`) were re-taken after
the merge, because "it renders" is a picture and not a claim.

## Findings

Severity is about what the user sees: **failure** means words or a gesture are lost;
**defect** means the surface is wrong in a way somebody will hit; **quality** means it
works and should not be built this way.

### F1 · failure — a release after a trailing pause never pastes

The gate closes 800 ms after the speaker stops (`audio.Gate`, `hang_ms`), so a hold that
ends with a pause — finish the sentence, think, let go — finalises *during* the hold. The
final decodes, and its `draft` event arrives while the button is still down;
`_pump_events` skipped it (`if not ev.text or self._press_talking: continue`). At the
release `session.talk_end()` finds nothing in flight and returns False, and `_talk_end`
armed the send only on that flag. The words sat in `session.draft`; nothing pasted,
nothing said, nothing shown — the exact report this surface has drawn six times.

Reproduced headlessly against the fixtures: `_send_pending` False, `session.send` never
called, the draft still holding the sentence. The shipped `Pill` has the same arming rule
but shows the draft in its bubble with a Send chip, so there the failure is visible; on a
surface with no bubble it was silent.

**Fixed:** the release arms a wait whenever there are words — in flight *or already in
the draft* — and a per-frame `_pump_send` fires it once the decoder is idle.

### F2 · failure — a split utterance pastes only its first half

`_pump_events` fired `_send()` on the first `draft` event after a release. A hold long
enough to cross `MAX_UTTERANCE_SEC`, or any hold with two finals queued, delivers two;
the first fired the paste while `session.busy` was still True and the second landed in
the draft after it, stranded. Reproduced: `['first half of the sentence']` pasted, the
second half never.

**Fixed** with F1: the wait fires on `not session.busy`, the shipped `_pump_talk`'s
rule, and `_send` stays the one choke point so the `send` hotkey cannot double-paste.

### F3 · defect — the panel jumps monitors, and the pill cannot leave one

`_sync_shell` clamped the band's x against `winfo_screenwidth()`, which on Windows is
the *primary* monitor's width, while the pill is placed on the monitor under the pointer
in virtual-screen coordinates. On any monitor to the right of the primary the clamp is
always true, and opening the panel moved the window to `primary_width - 400`. `y` was
clamped to 0 rather than the work area's top; nothing clamped the bottom, so the notice
strip could run under the taskbar. `_move_window` clamped drags to `self.work`, read
once in `__init__` and never refreshed, so "Drag it anywhere" (Main.dc.html) stopped at
the edge of the monitor Flow launched on.

**Fixed:** a `_sync_monitor` every 4th frame keyed to the window's own centre (the
shipped surface re-asks every 4th frame, keyed to the pointer), clamps against the
monitor's work area, drags clamped to the virtual desktop so the pill can cross.

### F4 · defect — device pixels compared with design pixels

`_outside_click_now` tested the cursor (device px) against `_shell_w`/`_shell_h`
(design px), so at 150 % or 300 % the "inside" rectangle was a third of the real window
and a click in the right or lower part of an open panel closed it. `_on_box_click`
divided the event's device-pixel `y` by design-pixel row heights, so a palette row click
at scale > 1 chose the wrong workspace. `_on_press` and `_panel_click` already converted
through `self.design()`; these two did not. This machine runs at 300 %.

**Fixed:** both compare in one unit, and the anchors are read from the tracked
`_shell_xy` rather than `winfo_*` — which the module's own comments say lags.

### F5 · defect — session events with nowhere to go

`_pump_events` handled six kinds. The rest fell through silently:

- `send` — the spoken trigger ("boom", "enter boom"). Nothing happened, and `_deliver`
  never carried the `submit` flag, so "enter boom" could not work here at all.
- `drop` — a rejected utterance. P2 says a rejection is never silent; here it was.
- `edit` — "changed 'thursday' to 'Tuesday'", the one feedback a spoken correction gets.
- `note` — the Send refusals: "nothing to send", "nothing to ask", "still waiting on the
  last answer", "still rewriting". Pressing `send` with an empty draft did nothing visible.

The notice strip added on 2026-09-04 is the channel that now exists for exactly this.

**Fixed:** `send` pastes (with `submit` when the trigger was the enter form), `drop`,
`edit` and the refusal notes are said on the strip; progress notes the ring already
carries are deliberately not.

### F6 · defect — the menu's mode choice kept a pending paste

The radios called `session.toggle_mode(to=)` directly while the tap and the `mode`
chord went through `_cycle_mode`, which first drops a waiting send ("a pending paste
belongs to the mode it was spoken in"). Choose Ask from the menu with a Type paste
waiting and the next draft went to the CLI as a question.

**Fixed:** one `_choose_mode` seam for all three routes.

### F7 · defect — a silent reply-hold destroyed the answer on screen

`_talk_start` in a panel mode cleared the heard and result blocks the instant the hold
began. Hold to reply, hear nothing, release: `_talk_end` saw an empty band and closed the
panel — the answer that had been on screen was gone. Ask.dc.html's "the next hold starts
fresh" is about the thread, not about erasing a visible answer before a word arrives.

**Fixed:** the blocks clear when words arrive (the first partial, or the question
firing); a hold that hears nothing leaves the exchange exactly as it was.

### F8 · defect — a frame that raised never repainted

`_tick` caught the exception, flashed, printed the traceback — and `_draw()` was the
line that had been skipped. With the layered-window path the last presented bitmap stays
on screen, possibly at a size `_sync_shell` had already changed. `NEEDS_YOU.md` records
the same shape on the shipped surface; here it was worse because nothing repaints until
a frame succeeds.

**Fixed:** the handler repaints inside its own guard.

### F9 · defect — the panel's rows collided and the answer could not be read

Photographed in `11-compact-refine-panel.png`: the result's second line ran under the
Copy/Send chips (`RESULT_Y + 16 + 2 × 18 = 160`, past `FOOTER_Y = 156`), and the
"refined for this repo" tag sat on the heard block's last line with no air. Both blocks
were cut to two lines with an ellipsis — an Ask answer of ten lines showed two, and the
Refine result, the thing Send is about to paste, could not be read before sending.
`_fit` collapsed newlines and indentation, so a refined prompt's bullets displayed as one
run-on line while Send pasted the real shape. The artboards grow with their text.

**Fixed:** the band's height is computed from its text up to a cap, the rows and chip
rectangles come from one layout, `_fit` keeps paragraph breaks and indentation.

### F10 · quality — GDI+ never saw the design's fonts

`ui._load_fonts` registers the bundled IBM Plex files with `AddFontResourceExW(FR_PRIVATE)`,
which GDI and Tk see and GDI+'s installed collection does not. Probed on this machine:
`GdipCreateFontFamilyFromName("IBM Plex Sans")` → 14 (not found), likewise Mono and
"Medm"; so every string the compact surface drew on Windows fell to Segoe UI / Consolas
(visible in `07-compact-ask-panel.png`). The same probe proved the fix: a private
collection filled with the five files resolves all three names.

**Fixed:** `paint.load_fonts` and a private collection consulted first.

### F11 · quality — every frame repainted and re-presented

Measured on a real window at 300 %, 200 frames of `_draw()`: **0.77 ms/frame** with the
pill alone, **4.38 ms/frame** with the panel open — 15 % of the frame budget, spent
drawing the same picture thirty times a second. The shipped `Pill._draw_key` skips an
unchanged frame; the compact surface had no key, and the "composited, not painted"
decision names this cost as its reopen condition.

**Fixed:** a draw key built from every read `_draw` makes; an idle frame costs the reads.

### F12 · quality — the photograph gate had a blind spot

`scripts/compact_shots.py`'s `copied` case set `pill._copied`, an attribute the
2026-09-04 notice rework renamed, so `19-compact-copied.png` was a picture of a bare
pill and nobody could have noticed the strip missing. **Fixed** with F9, and two shots
added for the growing band.

### F13 · quality — smaller things, fixed alongside

- `_on_menu` rebuilt the Design cascade on every right-click and never destroyed the
  previous submenu — a `tk.Menu` leaked per open.
- The UI called `session._provider()` in two places; `Session.provider` is now public.
- No fast tick: hotkeys and the decode landing waited for the 30 ms frame, up to two
  frames on the release-to-paste path the felt-latency pass measured. Added, modelled on
  the shipped `_fast_tick`.
- The standalone box (palette, setup) anchored off `winfo_*` and was not kept on screen at
  the right edge.

## Left as they are, on purpose

- **Spoken punctuation's bare words.** `_SHAPE_TABLE` resolves "tab", "period", "dash",
  "colon" and "comma" wherever they appear, by design ("unconditional, by design" — the
  send-trigger convention, one level down). "Open a new tab" therefore pastes an indent.
  The decision is recorded and undo holds the words; the alternative — a lead-in
  ("press", "then") required for the ambiguous single words, the marks left bare — is a
  product call and is raised in `NEEDS_YOU.md`, not taken here.
- **`TeeCanvas` in `paint.py`** is unused by the compact surface. It is the port that
  hit the wall, kept deliberately by the 2026-09-04 decision; it goes with `ui.py`.
- **The forty imports from `ui.py`.** The shared palette, fonts and windowing helpers
  should live in modules both surfaces import, so the compact one stops depending on the
  module it replaces. That is step 2 of [../one-surface.md](../one-surface.md) and a
  refactor of its own, not a fix.
- **The shipped surface's own frame-pump gap** (`NEEDS_YOU.md`, "An exception in the
  frame pump leaves the row painted at the last width") is unchanged: F8 fixed the
  compact copy of it, and the shipped one is the owner's call as recorded there.

## The commits

Ten, on `compact-design` after `da6c669`, in the order they were merged. Each agent
worked in its own worktree from the same base; the cherry-picks met in one docstring,
one method body, one test and one photograph, all recorded in the commits themselves.

| Commit | Closes | What it says |
|---|---|---|
| `acec694` | F5, F6, F7, F13 (menu leak, `provider`) | Say the four things the compact pill was dropping, and stop it eating its own answer |
| `9d5dd7c` | F10 | Give GDI+ the type, which FR_PRIVATE was never going to hand it |
| `c42b4f0` | F11 | Stop the compact pill repainting a picture that has not changed |
| `c96d73d` | F3, F4, F13 (box, `winfo_*`) | The compact pill asks which monitor it is on, and in the right pixels |
| `83a8001` | F1, F2 | Let the release wait for the decoder, not for an event that already came |
| `5b81377` | F8, F13 (fast tick) | Give the compact pill the 5 ms clock, and a frame that repaints when it dies |
| `63d7f72` | — | Drive the deferred-clear test through the wait the release now arms |
| `db36cdf` | F9 | Let the compact panel grow with its text, the way its artboards do |
| `5aa05a0` | F12 | Photograph the grown band, and give the copied shot back its line |
| `b23c759` | F7, found by the photographs | A hold over a closed band starts clean, and the silence shot is grey again |

The last one is what the photograph gate is for: the deferred clear (F7) kept an
exchange across a *closed* band too, so a silent hold after Esc raised the dismissed
answer, and `16-compact-silence.png` came out as a panel where the artboard says grey.

Six new test files sit beside `tests/test_ui_compact.py`: `test_compact_send.py`,
`test_compact_screen.py`, `test_compact_events.py`, `test_compact_panel.py`,
`test_compact_draw.py`, and additions to `test_paint.py`. Where an existing test pinned
the behaviour a fix replaced, it was changed in place and says so.

## What the agents noticed and left, for the record

- `scripts/compact_shots.py` defines `loading()` and `mic_open()` twice and lists their
  six steps twice, so shots 20 and 21 are taken twice and the second overwrites the
  first. Harmless; a cleanup.
- `scripts/shots.py` defines `FakeAsr` twice and assigns `capturing`/`asr` twice in
  `FakeSession.__init__` — the same duplicated block, from the same merge.
- `flow/paint.py` has two statements where a line continuation collapsed into a run of
  spaces (`round_rect`'s corner tuple and `_font`'s stand-in). They parse; they read as
  damage.
- `_move_window` clamps a drag to the virtual desktop's bounding box, which on monitors
  of unequal height includes regions no display covers. The tray is the way back, and
  the four-frame monitor sync recovers `work`; a true per-monitor union needs an
  `EnumDisplayMonitors` walk.
- `_wrap` gives a wrapped bullet's continuation line no hanging indent; the artboard's
  bullets hang. Detecting list markers is a step past "preserve indentation".
- `_panel_layout` runs twice per panel frame (once to size the window, once to draw).
  Cheap with the line-height cache; a knowingly duplicated computation.
- `_pump_press` still turns a mouse press into a hold only on the 30 ms frame; the fast
  clock does not run before a hold exists. The chord path, the documented gesture, is
  unaffected.
- The notice strip is wider than the capsule and hangs from its left edge
  (`19-compact-copied.png`): `_sync_shell` widens the window to the sentence but
  `_draw` keeps the capsule at x = 0. Centring it means shifting the window left by
  half the extra width for the strip's three seconds and back after, so the capsule
  stays put on screen. Cosmetic, and the reason it is not fixed here is that it touches
  the hit-testing every package above just settled.
