# Compact design — build brief

Written 2026-09-03, after a QA pass over `088cc87` against the canvas in this
directory. The scaffold in `flow/ui_compact.py` is well-made and honestly
commented, and every gap in it is cited rather than hidden. This brief closes
those gaps in the order that makes the surface usable soonest.

**Read first:** `design/compact/README.md` (the decisions), then the five
artboards — `Main`, `Refine`, `Ask`, `Workspace`, `States`. `gen.py` is the
source of all five; the exact pixel values quoted below come from it and are
the authority when this brief and your memory disagree.

**Rules that hold across every item:**

- No new runtime dependency. R16 keeps the install at three packages; this is
  tkinter and ctypes like the rest of the UI.
- Every item lands as its own commit with its own tests, in the order below.
  The suite is `uv run python -m unittest discover -s tests` and it is green
  now (2358 tests, 2 skipped). It stays green at every commit, not just the last.
- `flow/ui.py` is not to be reskinned. The compact design is a sibling surface
  (decisions.md, 2026-09-03). Where the two need the same helper, the helper
  moves to a place both import — it does not get copied.
- Photographs are the gate for anything visual:
  `uv run --with pillow python scripts/compact_shots.py`. Extend that script
  with a shot for every state you add. "It renders" is a picture, not a claim.

---

## The QA findings this brief closes

Verified on `088cc87` by reading the code and photographing all six states.

1. **The surface cannot deliver a word.** `on_send` is accepted at
   `flow/ui_compact.py:177` and never called anywhere in the file. Hold, speak,
   release — the session builds the draft and nothing ever leaves. The canvas's
   opening line is "Hold the pill. Speak. Let go."
2. **Answers are dropped on the floor.** `_pump_events` handles `error` and
   `disarm` only. `draft`, `partial`, `reply` and `note` fall through, so in Ask
   mode the CLI's answer arrives and is silently discarded.
3. **No third mode.** `MODE_TINT` has two entries; `REFINE_GOLD` is a constant
   nothing can reach. Tap cycles Type ↔ Ask, not Type → Refine → Ask.
4. **No panel.** `PANEL_W = 400` is a TODO. Refine and Ask have nowhere to land.
5. **No workspace, reachable or otherwise.** The right-click menu holds one
   item, "Quit". Without Switch workspace there is no way to ground Refine or
   Ask from this surface at all.
6. **No fallbacks.** None of the six cases in `States.dc.html` exist: no slashed
   mic, no amber `RECOVER`, no "no CLI so Refine and Ask are not offered", no
   Lite "copied — press Ctrl+V".
7. **No spoken punctuation.**
8. **Visual drift from `Main.dc.html`** — detailed in item 7 below.

---

## Item 1 — Make Type work end to end

The first commit, because until it lands the surface is a demonstration rather
than a tool.

- Call `on_send`. Copy the shape from `flow/ui.py:3759-3770`: the text, the
  paste target, the returned problem string. A returned problem is a red flash
  here — this pill has no words to say it with yet.
- Drain the whole event stream in `_pump_events`. `draft` sets the text the
  send path will use; `partial` has nowhere to go until item 3 and may be
  discarded *explicitly*, with a comment, not by falling through. `error`
  and `disarm` keep their current behaviour.
- Bind `send` and `cancel` in `_drain_hotkeys`. The docstring at
  `flow/ui_compact.py:307-316` says they belong to the panel and arrive with
  it; that was true of `cancel` and never true of `send` — a dictation surface
  with no send is not a dictation surface.
- **`Type` never opens a panel** (README). Release → refine-free → paste. The
  CLI is not on this path, and item 6's no-CLI fallback depends on that staying
  true.

**Acceptance:** a headless test drives press → hold past `PILL_HOLD_SEC` →
release → a `draft` event, and asserts `on_send` was called with that text.
A second asserts a returned problem flashes rather than being swallowed.
Then, on a real desktop: `--design compact`, hold, speak into a text editor,
and the words appear in it.

## Item 2 — The capsule, pixel-exact to `Main.dc.html`

The canvas wins where it and the shipped house style disagree. Decided
2026-09-03.

- **A true stadium.** `_round_rect` is a smoothed polygon and at `r = h/2` it
  yields a rounded rectangle, not a capsule — visible in `.shots/01-compact-rest.png`.
  Write a `_capsule` helper: two `create_arc` pieslices of diameter `h` at each
  end plus a `create_rectangle` between them. Keep `_round_rect` untouched; the
  shipped surface depends on its current shape.
- **The three hairlines.** `.pill` in `gen.py` is `background: SHELL`, a 1 px
  `RING_OUTER` border and an `inset 0 1px 0 RING_TOP` highlight. The compact
  pill currently draws a bare fill. `_panel_chrome` (`flow/ui.py:2270`) is the
  same idea for the shipped surface — read it, then draw the capsule equivalent.
- **The ring is 1 px, not 2** (`box-shadow: 0 0 0 1px <state>`).
- **The meter is 15 bars, 2 px wide on a 2 px gap** — `BARS = 12`, `BAR_GAP = 4`
  today, which is why rest photographs as a row of dots instead of the flat line
  the spec asks for. Rest height is 3 px. Keep the centre-blooming envelope.
- **The mic is stroked, not filled.** `gen.py`'s `mic()`: a 14×18 viewBox,
  1.4 px strokes, round caps — a rounded rect capsule, an arc cradle, a stem.
  The current glyph is `ui.py`'s filled oval. Draw it with `create_arc`,
  `create_line` and an outlined `_round_rect`.

**Acceptance:** re-run `compact_shots.py` and put `01-compact-rest.png` beside
`Main.dc.html`'s "Actual size" block at 2×. They should be the same object.

## Item 3 — The panel, and the pill as its foot

The centrepiece. One window, not two — this is the hard part and the reason the
scaffold left it alone.

- The window grows from 120×34 to 400 wide with the panel above the pill; the
  pill becomes the bottom band of the same window. `flow/ui.py:4985-5000` shows
  how the shipped surface already does exactly this: `_shell_h != PILL_H` means
  a panel band is above, corners become `(0, 0, PANEL_R, PANEL_R)`, and
  `seam="top"` makes the join read as an internal divider rather than two
  windows touching. That mechanism is proven — reuse the reasoning, adapt it to
  the capsule.
- **The pill never hides and never moves.** The panel rises above it. The foot
  stays holdable — hold for "say more" (Refine) or a reply (Ask).
- The panel from `Refine.dc.html` / `Ask.dc.html`, top to bottom: the workspace
  strip (folder icon, path, note, close), the `heard` block in `PLACEHOLDER`
  grey, the result block, and a footer with Copy, the hold hint, and Send in
  Refine only.
- Closed by Send, Esc, or a click outside. On close the window is 120 wide again.
- `partial` events now have a home; wire them into the `heard` block.

**Acceptance:** shots for panel-open in both modes, and one of the window at
120 wide immediately after a close, proving it returns.

## Item 4 — REFINE as a third session mode

Core work, its own commit, ahead of the pill mode that uses it. Decided
2026-09-03: it goes in `flow/session.py` properly rather than being tracked by
the surface.

- `session.py` already has `State.REFINING` and a CLI rewrite over a held draft.
  Refine is an *action on a draft* today; this makes it a mode. Most of the
  machinery exists — do not build a second pipeline.
- `toggle_mode` (`flow/session.py:3373`) currently flips two ways. It becomes a
  cycle of three. Its docstring's promise — the draft survives a mode switch —
  holds for all three. Read what it emits: the mode note names the provider and
  the workspace, and Refine's note must do the same work.
- **The workspace is the CLI's system role** (README). `GROUNDING_WHERE` and
  `_refine_cwd` are the existing seam.
- The shipped `Pill` reads `session.mode` in several places. Every one of them
  must answer sensibly for a third value — a two-way `if` that treats REFINE as
  CONVERSE is the defect to hunt for here, and it will not announce itself.

**Acceptance:** the existing session tests still pass unchanged, plus new ones
for the three-way cycle and for Refine handing the workspace down. Launch the
*shipped* design and confirm nothing about it changed.

## Item 5 — The gestures, complete

- Tap cycles Type → Refine → Ask, wrapping. `MODE_TINT` gains `REFINE_GOLD`.
- Right-click opens the menu from `Workspace.dc.html`: the three modes with a
  check on the current one and the sub-line "tap the pill to cycle"; a separator;
  **Switch workspace** with the current path beneath it; a separator; **Workbench
  setup** with "mic, CLI, where it pastes" beneath it. Then Quit.
- `_dark_menu` and the foreground-borrow in `_on_menu` are correct as they
  stand — verified by photograph. Do not change them.
- **Keep the tray.** Decided 2026-09-03, against the canvas's "no tray": it is
  the escape hatch if the pill is ever dragged somewhere unreachable. The canvas
  text about there being no tray menu is superseded; note it in `README.md`.
- **Switch workspace** is the search palette in `Workspace.dc.html` — type a few
  letters, top hit highlighted, Enter sets, Esc leaves, "No workspace — just
  talk" always last. The list is the folders Flow has been pointed at;
  `profile.note_workspace` already records them. `session.set_workspace`
  (`flow/session.py:2426`) already does the switch and already treats it as a
  topic change.
- **Workbench setup** is three read-only lines with the values Flow already
  found: Microphone, Agent CLI, On release.

**Acceptance:** shots of the menu, the palette mid-search, and the setup box.

## Item 6 — The fallbacks

All six cases in `States.dc.html`. The rule under every one of them: **Type
never depends on the CLI, and nothing spoken is thrown away because a later step
failed.**

| Case | Behaviour |
|---|---|
| No agent CLI on PATH | Type still works. Refine and Ask are **not offered** — tapping does not cycle to them. Grey, not red. |
| Mic blocked or unplugged | Slashed mic glyph, red ring. The one gesture the pill refuses outright. |
| Held, nothing said | Straight back to grey. No panel, no toast. |
| Refine failed or timed out | Panel opens holding the raw dictation. The CLI's own last line is the message. Send still works — unrefined text beats no text. |
| Workspace moved or deleted | Amber `RECOVER` `#E8A33D` once, at launch. Falls back to no workspace. |
| Cannot type into the window (Lite) | Clipboard, plus a line under the pill: `copied — press Ctrl+V`. Not an error state. |

`RECOVER` is a fourth ring colour the scaffold's `RING` map does not have. Add
it, and add the slashed variant to the glyph.

**Acceptance:** a shot per case, and a test per case for the ones that are logic
rather than paint — the no-CLI cycle in particular.

## Item 7 — Spoken punctuation

"You say the key; the text carries the shape." `press enter` → a newline,
`tab` → an indent, and so on, per `Refine.dc.html`.

- **Resolved locally**, in or beside the decode pipeline — *not* in the pill —
  so Type gets it with no CLI on the machine.
- `flow/edits.py` and `flow/clean.py` are where the existing correction grammar
  lives; this belongs with them, and their table-driven test style is the one to
  follow.
- Both surfaces inherit it. That is intended.

**Acceptance:** table tests over spoken input → expected text, including the
`… press enter press enter then tab dash fix the tests` example from the
artboard, which must produce a blank line and an indented `- fix the tests`.

---

## When it is done

- The suite is green and larger.
- `scripts/compact_shots.py` produces a photograph of every state in this brief.
- `docs/decisions.md` gains an entry for REFINE-as-a-mode and one for keeping the
  tray against the canvas — with its reopen bar, in the house style.
- The 2026-09-03 compact entry in `docs/decisions.md` has a **"Reopens if"** line
  about the compact design reaching spec parity. Parity is what this brief is.
  Say so there when it lands.
