# Flow, compact — design canvas

The compact three-function Flow (Type / Refine / Ask on one wordless pill), drawn
as a Claude Design canvas. Live canvas:

https://claude.ai/code/artifact/0ab88c75-8b24-455b-b96f-f9e5763a45fc

## Files

- `gen.py` — generates every `*.dc.html` artboard. Edit this, not the artboards;
  the pill and its docked "foot" are shared functions so all frames agree.
- `Main.dc.html` pill: glyph colour = mode, ring colour = state, where the panel docks.
- `Refine.dc.html`, `Ask.dc.html` — the 400 px panel on its foot.
- `Workspace.dc.html` — the right-click menu, switch-workspace palette, workbench setup.
- `States.dc.html` — fallbacks (no CLI, no mic, silence, refine failed, workspace gone, Lite).
- `canvas.json` — artboard positions, frame sizes, sticky notes.
- `flow-compact.html` — the seeded canvas page, regenerated from the above. Do not edit.

## Decisions the canvas encodes

- The pill carries no text. Mic glyph tint: white Type, gold `#E1B75C` Refine, violet
  `#B48EF5` Ask (the hues `flow/ui.py` already gives those commands). Ring: green
  `#3ECF8E` hearing, blue `#7AA2F7` CLI, red `#F2584A` wrong, none at rest.
- Tap (< `PILL_HOLD_SEC`) cycles the mode; hold talks; right-click is the only menu
  (mode list, Switch workspace, Workbench setup).
- Type never opens a panel. Refine and Ask raise the panel *above* the pill; the
  pill becomes the panel's foot (one window, one seam, 120 -> 400 wide), stays
  holdable for "say more" / reply, and never hides. Send / Esc / click-outside closes.
- Refine hands the CLI the workspace as its system role; spoken punctuation
  ("press enter", "tab") is resolved locally so Type gets it without a CLI.
- The tray stays (decided 2026-09-03, against Workspace.dc.html's "There is no
  preferences window and no tray menu"): it is the escape hatch if the pill is ever
  dragged somewhere unreachable — hidden must not mean gone. That canvas line is
  superseded — but only that sentence. The icon goes up at launch instead, and
  carries Show and Quit.
- The menu drawing stands as drawn but for **one row: Design** (decided
  2026-09-04). `profile.design` picks the surface, the control that writes it was
  a row in the shipped design's Settings menu, and with compact stored that made
  the switch unreachable from the only surface running. Two designs somebody can
  choose between have to be reachable from each other.

## Rebuild and re-save

In a Claude Code session, `/design` re-extracts the seeding helper and gives its
base directory; then:

    python gen.py
    node "<base>/seed-canvas.mjs" --template "<base>/payload.template.html" \
      --out flow-compact.html --title "Flow, compact" \
      --artboard Main.dc.html --artboard Refine.dc.html --artboard Ask.dc.html \
      --artboard Workspace.dc.html --artboard States.dc.html --canvas canvas.json
    node "<base>/seed-canvas.mjs" --check flow-compact.html

Then save `flow-compact.html` to the URL above with the Artifact tool. If the canvas
was edited and saved in the browser since, read it back first (`action: "read"`,
then `seed-canvas.mjs --extract <saved file> --to <empty dir>`) and merge.
