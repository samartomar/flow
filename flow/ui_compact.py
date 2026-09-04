"""The compact pill — the second UI, drawn from design/compact.

`flow/ui.py` is the full surface: a labelled pill with a draft bubble and a
conversation card docking to it. This module is the other design — a wordless
120 px capsule whose entire vocabulary is two colours and a meter
(design/compact/README.md, Main.dc.html):

  glyph colour = mode     ring colour = state     meter = the level, as ever

It runs the same `Session` the full UI runs, through the same contract: the UI
pulls, the session never calls into it. A 30 ms frame calls `session.tick()`
while armed and `session.pump_results()` while not, drains `session.events()`,
and reads the state attributes (`state`, `mode`, `level_db`, `hearing`,
`busy`, `draft`) at draw time.

**The spec has three modes, and so does the session.** Type / Refine / Ask
(README) map onto DICTATE / REFINE / CONVERSE: Type is dictate, Ask is
converse, and Refine is the polish pass over the held draft with the workspace
as the CLI's system role — an action on a draft that became a mode in
session.py, delivered as a `reply` rather than a draft rewrite. The panel the
Refine and Ask artboards draw the pill as the foot of is mode-driven:
`PANEL_SPEC` maps a mode to its panel, and Type is the only mode with no
entry (README: "Type never opens a panel"). Spoken punctuation is still a
stub citing its artboard, not a feature.

Windowing is the same five probed attributes every Flow window wears
(`overrideredirect`, `-topmost`, `-alpha`, `-transparentcolor`, `-toolwindow`),
applied by ui.py's own `_shell_window` rather than re-probed here. Lite means
what it means there: nothing in this module imports `inject` — the two Win32
reads the panel's click-outside poll needs are declared on ui.py's own
`_user32` under the same platform guard ui.py used to declare its own
(flow/ui.py:82-101), and every call site is `lite`-guarded, with ui.py's
`_NoHands` (flow/ui.py:68-79) under the ones that are not.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import time
import math
import tkinter as tk
import tkinter.font as tkfont
import traceback
from pathlib import Path

from . import tray
from . import paint
from .profile import DESIGNS, DESIGN_DEFAULT
from .session import CONVERSE, DICTATE, REFINE, Session, State

# The hues and the fonts are ui.py's own, imported rather than restated: the
# spec's rule is "the hues flow/ui.py already gives those commands" (README),
# and a colour written down twice is a colour that drifts. `TEXT` is the
# near-white ui.py spends on primary text — the spec's "white" for Type.
# `SEAM` is ui.py's `RING` hairline under the name the docked design gives it:
# the one line between the panel and its foot.
from .ui import (
    _FONT_DIR,
    _FONT_FILES,
    _POINT,
    CARD_ACCENT,
    CHIP,
    CODE,
    DB_CEIL,
    DB_FLOOR,
    DIM,
    ERROR,
    FLASH_FRAMES,
    FONT_BODY,
    FONT_CHIP,
    FONT_CHIP_PRIMARY,
    FONT_MONO,
    FONT_NOTE,
    FONT_PARTIAL,
    HEARING,
    LEVEL_FALL_ALPHA,
    LEVEL_RISE_ALPHA,
    MUTED,
    PILL_DRAG_SLOP,
    PILL_HOLD_SEC,
    PLACEHOLDER,
    PRIMARY_FILL,
    PRIMARY_TEXT,
    RING_OUTER,
    RING_TOP,
    SHELL,
    TEXT,
    WAITING,
    _copy_to_clipboard,
    _dark_menu,
    _mix,
    _monitor_at,
    _no_activate,
    _pointer_monitor,
    _round_rect as _tk_round_rect,
    _shell_window,
    _user32,
    _virtual_desktop,
    foreground_hwnd,
    owned_by_flow,
    toplevel_hwnd,
)
from .ui import PANEL_BOTTOM_OFFSET, bottom_centre
from .ui import RING as SEAM

# The same five files `ui._load_fonts` registers, handed to GDI+ as well.
# `AddFontResourceExW(FR_PRIVATE)` is a GDI registration, and GDI+ keeps its
# own collection: measured on this machine, "IBM Plex Sans" answered
# FontFamilyNotFound to GDI+ *after* `_load_fonts` had run, so every string
# this surface composites came out in `paint`'s stand-ins — Segoe UI where the
# design says Plex Sans, Consolas where it says Plex Mono. Here rather than in
# `__init__` because the painter is built there and this has to be true before
# the first font is asked for; `load_fonts` is idempotent and answers 0 off
# Windows, so an import costs nothing where there is no GDI+ to tell.
paint.load_fonts(str(_FONT_DIR / name) for name in _FONT_FILES)

if sys.platform == "win32":
    # The click-outside poll's two reads, declared for the reason inject.py
    # spells out and ui.py repeats at flow/ui.py:85-94: an undeclared ctypes
    # restype is C `int`, so a 64-bit HWND or style word comes back truncated.
    # GetCursorPos writes through a pointer, which is the half of that rule
    # that applies here.
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    _user32.GetCursorPos.restype = ctypes.c_int

#: The left mouse button, for the click-outside poll's edge detector.
_VK_LBUTTON = 0x01

#: The capsule, from Main.dc.html's `.pill`: 120 × 34, radius half the height.
#: Nothing on it is text — that is the design's first decision, not an omission.
PILL_W = 120
PILL_H = 34
PILL_ALPHA = 0.94

#: Refine's gold (README, and ui.py's Refine chip at flow/ui.py:2200). Declared
#: once, ahead of the mode itself, and aliased into the two maps that wear it:
#: a colour written down twice is a colour that drifts.
REFINE_GOLD = "#E1B75C"

#: Mic glyph tint per mode (README: "white Type … violet Ask") — all three,
#: now that the session has all three.
MODE_TINT = {
    DICTATE: TEXT,  # Type
    REFINE: REFINE_GOLD,  # Refine
    CONVERSE: CARD_ACCENT,  # Ask — the violet ui.py already gives the card
}

#: Ring colour per state (README: "green hearing, blue CLI, red wrong, none at
#: rest"). The same hues ui.py's ACCENT map gives the same states. IDLE and
#: DRAFT have no entry because rest is the absence of a ring, not a colour for
#: it. `session.busy` — a final decode still running — is not a ring colour
#: either: it happens inside the utterance it is decoding, which LISTENING's
#: green already covers, and one state gets one colour.
RING = {
    State.LISTENING: HEARING,
    State.REFINING: WAITING,
    State.ASKING: WAITING,  # the same wait from the user's side, as in ui.py
}

#: The fourth ring colour (States.dc.html): amber, once, at launch, when the
#: workspace the profile remembers is gone. Not a session state — a launch
#: notice — so it is not in `RING`; `_recover` counts it down.
RECOVER = "#E8A33D"
#: Frames the amber notice stays up (~9 s at the 30 ms frame), and the one
#: thing that ends it early: a hold — the user is back, and has seen it.
RECOVER_FRAMES = 300

#: Lite's last inch (States.dc.html): the words are on the clipboard, said
#: once in a strip under the pill, never in an error colour. The strip's
#: height in the window, and how long it stays (~3 s).
NOTICE_H = 18
COPIED_FRAMES = 100
COPIED_TEXT = "copied — press Ctrl+V"
#: The same line for the enter-variant of the spoken trigger, on ui.py's
#: `COPIED_ENTER` argument (flow/ui.py:1085): "enter boom" collapses to a copy
#: here like every other send, and the Enter it asked for is the one step the
#: clipboard cannot take for you. Said rather than dropped — a suffix that
#: sometimes does something with no signal either way is how somebody learns
#: to distrust the one that does.
COPIED_ENTER_TEXT = "copied — press Ctrl+V, then Enter"
#: Air either side of a notice's words. The strip is as wide as it needs
#: to be and never narrower than the pill.
NOTICE_PAD = 14

#: The notes the strip says out loud, matched on their opening words.
#:
#: Most notes are progress the ring is already carrying, and the strip stayed
#: empty for all of them — including the handful that are the only answer to
#: "I pressed it and nothing happened". Send's three refusals are the sharp
#: case: press the `send` hotkey on an empty draft and this surface did
#: *nothing at all*, no colour, no motion, no sentence. A wordless surface
#: takes on the obligation to answer the questions its words used to answer
#: (decisions.md, 2026-09-04), and these are questions no hue can be an answer
#: to: the three "nothing to send/ask/refine", the two "still" refusals of a
#: send while the last one is in flight, the two truncations that say the CLI
#: was handed less than was said, the stale rewrite that was thrown away, and
#: the long hold that was stopped for you.
#:
#: What is deliberately *not* here is everything else. The mode notes are the
#: glyph's own hue, said a second time. "asking claude · in ~/dev/flow" and
#: the rest of the progress lines are true for exactly as long as the ring is
#: blue, which is a better channel for them than a strip that expires. The
#: draft-shaped notes have the panel. A 400 px sentence under the pill on
#: every tap is noise, and noise is how the strip that matters gets ignored.
SAID_NOTES = ("nothing to", "still ", "only the last", "discarded",
              "stopped after")

#: The mic glyph's frame in the window, from gen.py's `.pill`: a 14×18
#: viewBox after the 12 px left padding, centred in the 34 px height. The
#: glyph itself is stroked, not filled — `mic()` in gen.py is 1.4 px strokes
#: with round caps. Tk has no fractional rasterizer; 1.4 is passed through
#: and lands as it lands (see the shots).
MIC_X = 12
MIC_Y = (PILL_H - 18) // 2
MIC_STROKE = 1.4

#: The level meter, gen.py's `.meter`: 15 bars 2 px wide on a 2 px gap, 3 px
#: at rest, in a 14 px band, blooming around the centre line. It starts after
#: the padding, the glyph and the 9 px gap the flex row gives them.
METER_X = MIC_X + 14 + 9
BARS = 15
BAR_W = 2
BAR_GAP = 2
BAR_MAX_HALF = 7.0  # half-height at full level — 14 px of travel inside 34

#: The docked panel (Refine.dc.html, Ask.dc.html): 400 px of band *above* the
#: pill, which becomes its foot — one window, one seam, the foot still
#: holdable for "say more" / reply, closed by Send / Esc / click-outside
#: (design/compact/README.md). The band is a fixed height: the artboards grow
#: with their text, and the residual delta is that tkinter here wraps to a
#: line budget instead — see `LINE_CHARS` / `_fit`.
PANEL_W = 400
PANEL_H = 200

#: The foot's meter, gen.py's `pill(foot=True, n=40)`: the same 2 px bars on
#: the same 2 px gap, more of them for the wider band.
BARS_FOOT = 40

#: The workspace strip's background (gen.py `.strip`). The one hue this palette
#: adds — ui.py's v2 ramp has no step this side of `SHELL`, and a colour
#: written down twice is a colour that drifts, so it is written down once,
#: here.
STRIP = "#15181D"

#: The strip's tag labels ("heard", the workspace note), gen.py's `.tag`:
#: mono, 10 px, grey. Tk has no letterspacing; the size carries the read.
FONT_TAG = (FONT_MONO, -10)

#: Panel layout rows, top to bottom (gen.py `.strip`, the heard/result blocks,
#: the footer). Fixed, because the band is.
STRIP_H = 35
HEARD_TAG_Y = 50
HEARD_Y = 66
RESULT_Y = 108
FOOTER_Y = 156
CHIP_H = 26
PAD_X = 16
COPY_RECT = (PAD_X, FOOTER_Y, 72, FOOTER_Y + CHIP_H)
SEND_RECT = (PANEL_W - 74, FOOTER_Y, PANEL_W - 16, FOOTER_Y + CHIP_H)
CLOSE_RECT = (PANEL_W - 30, 8, PANEL_W - 6, 30)
#: The panel's text budget. Tk wraps canvas text by pixel width and happily
#: wraps *past the bottom of the block it is given* — `.shots/11` drew a
#: three-line answer through the footer chips before this was measured. So the
#: band wraps itself, in characters: FONT_BODY measures about 7 px a
#: character, the blocks are 356-368 px wide, and the line counts are what the
#: fixed rows below leave between a block's first row and the next block's.
LINE_CHARS = 52
HEARD_LINES = 2
RESULT_LINES = 2

#: The mode → panel map: which modes raise the panel on a hold, and what their
#: panel looks like. The mechanism (open on hold, `heard` ← partials and the
#: release's draft, `result` ← the reply, a Send chip when `send` is true) is
#: mode-generic; the entries are the whole of what differs. Type is never here
#: (README: "Type never opens a panel").
PANEL_SPEC = {
    REFINE: {
        # Refine.dc.html: the raw dictation in PLACEHOLDER grey under a "heard"
        # tag; the shaped text under a gold "refined for this repo" tag — no
        # accent bar, the tag carries the hue; the footer's Send pastes what
        # came back.
        "heard_tag": "heard",
        "heard_fill": PLACEHOLDER,
        "result_tag": "refined for this repo",
        "result_accent": REFINE_GOLD,
        "hint": "hold the mic to say more",
        "send": True,
    },
    CONVERSE: {
        # Ask.dc.html: the question is body text, not a grey transcript, and
        # carries no tag; the answer is a card with a violet left bar; the
        # footer is Copy and the hint — no Send.
        "heard_tag": None,
        "heard_fill": TEXT,
        "result_tag": None,
        "result_accent": CARD_ACCENT,
        "hint": "hold the mic to reply",
        "send": False,
    },
}

#: The modes' names on this surface (README, Workspace.dc.html). The shipped
#: UI's Dictate/Converse named the mechanism; the compact names the job.
MODE_NAME = {DICTATE: "Type", REFINE: "Refine", CONVERSE: "Ask"}

#: The standalone box (Workspace.dc.html's `.box`) the palette and the setup
#: share: 360 px wide, SHELL with a `RING_OUTER` border and the `RING_TOP`
#: inset highlight. Its rows, measured off the artboard.
BOX_W = 360
PALETTE_FIELD_H = 40
PALETTE_ROW_H = 30
PALETTE_FOOT_H = 34
SETUP_ROW_H = 42

#: TODO: spoken punctuation ("press enter", "tab"), resolved locally so Type
#: gets it without a CLI (design/compact/README.md). The session's decode
#: pipeline owns words; this belongs beside it, not in the pill.


def _round_rect(c, x1, y1, x2, y2, r, **kw) -> None:
    """A rounded rectangle on whichever target is drawing.

    `GdiCanvas` has a real one, built from quarter-circles; a `tk.Canvas` has
    only the smoothed polygon `ui.py` has always used. Dispatched rather than
    always sending the polygon, because GDI+ renders that spline wider than Tk
    does and a 26 px chip at radius 13 came out visibly ballooned.
    """
    rr = getattr(c, "round_rect", None)
    if rr is not None:
        rr(x1, y1, x2, y2, r, **kw)
        return
    _tk_round_rect(c, x1, y1, x2, y2, r, **kw)


def _unkey(win) -> None:
    """Take a window off the colour key and off Tk's own alpha, for the
    layered path.

    Both are answers to the question `GdiCanvas` is now answering, and both
    get in its way. `-transparentcolor` keys a colour out of whatever is
    painted, so the pill's own `SHELL` pixels would be punched out of the
    bitmap we just antialiased; `-alpha` puts the window into
    `SetLayeredWindowAttributes` mode, and a window in that mode refuses
    `UpdateLayeredWindow` outright — which photographed as the key colour
    standing in a solid rectangle where the pill should be. The opacity
    `-alpha` was carrying is not lost: it moves to the blend's
    `SourceConstantAlpha` (`GdiCanvas.constant_alpha`).

    Neither attribute exists off Windows, and neither is worth an exception
    here: this only runs where `paint.available()` already said yes.
    """
    for attr, value in (("-transparentcolor", ""), ("-alpha", 1.0)):
        try:
            win.attributes(attr, value)
        except tk.TclError:
            pass


def _capsule_points(x1, y1, x2, y2, square_top=False, inset=0.0) -> list:
    """The stadium as one open point run, from its top-left to its top-right.

    One path, sampled, rather than the arcs-plus-rectangles this drew before —
    and the reason is in `.shots/02-compact-hearing.png` from the run before
    this: a pieslice's *fill* and an arc's *stroke* do not rasterize onto the
    same pixels, so the ring stood a pixel outside the body and a dark halo
    ran around the inside of both caps, with a visible step where each
    straight run met its arc. Fill and stroke taken from the same points
    cannot disagree about where the edge is.

    `inset` pulls the path in by that many pixels, which is how a stroke that
    centres on its path stays inside a fill that stops at it.

    `square_top` is the foot (gen.py `.foot`: `border-radius: 0 0 17px 17px`)
    — the panel docks above, so the top corners square off to meet it and only
    the bottom quarter-circles survive. Open rather than closed because the
    foot's border has `border-top: 0`: the caller closes the loop when it
    wants all four sides, and does not when the seam above is somebody else's
    line to draw.
    """
    x1, y1, x2, y2 = x1 + inset, y1 + inset, x2 - inset, y2 - inset
    r = (y2 - y1) / 2
    #: 24 points to the half-circle — a 7.5 degree step, which on a 17 px
    #: radius is a 2.2 px chord: below the eye's read of a curve at this size,
    #: and cheap enough for a 30 ms frame.
    steps = 24
    pts = []
    if square_top:
        pts.append((x1, y1))
        pts.append((x1, y2 - r))
        # y grows downward, so the quarters sweep with `+ r sin a` — negating
        # it mirrors each corner into the top half and folds the foot into a
        # wedge, which is what `.shots/11-compact-refine-panel.png` drew.
        for i in range(steps + 1):  # bottom-left quarter: left side to bottom
            a = math.pi - i * (math.pi / 2) / steps
            pts.append((x1 + r + r * math.cos(a), y2 - r + r * math.sin(a)))
        for i in range(steps + 1):  # bottom-right quarter: bottom to right side
            a = math.pi / 2 - i * (math.pi / 2) / steps
            pts.append((x2 - r + r * math.cos(a), y2 - r + r * math.sin(a)))
        pts.append((x2, y1))
        return pts
    cy = y1 + r
    for i in range(steps * 2 + 1):  # the left cap, top tangent round to bottom
        a = math.pi / 2 + i * math.pi / (steps * 2)
        pts.append((x1 + r + r * math.cos(a), cy + r * math.sin(a)))
    for i in range(steps * 2 + 1):  # the right cap, bottom tangent round to top
        a = -math.pi / 2 + i * math.pi / (steps * 2)
        pts.append((x2 - r + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _flat(pts) -> list:
    """A point list as the flat `x1, y1, x2, y2, ...` Tk takes."""
    return [v for pt in pts for v in pt]


def _capsule(c: tk.Canvas, x1, y1, x2, y2, square_top=False, **kw) -> None:
    """The stadium, filled. One polygon over `_capsule_points`."""
    c.create_polygon(_flat(_capsule_points(x1, y1, x2, y2, square_top)),
                     **kw)


def _capsule_ring(c: tk.Canvas, x1, y1, x2, y2, colour: str, width=1,
                  square_top=False, top=True) -> None:
    """The stadium as a stroke, on the same points the fill uses.

    Inset by half the stroke, because a Tk line centres on its path: without
    it half of every stroke falls outside the body it is meant to trace, which
    is the halo this replaced.

    `top` says whether the run across the top is drawn — gen.py's `.foot` has
    `border-top: 0`, the seam above being the panel's line, but a state ring
    is a `box-shadow` and wraps all four sides.
    """
    pts = _capsule_points(x1, y1, x2, y2, square_top, inset=width / 2)
    if top:
        pts = pts + [pts[0]]
    c.create_line(_flat(pts), fill=colour, width=width)


def _hit(rect, x, y) -> bool:
    """Whether (x, y) falls in a (x1, y1, x2, y2) chip rect — the panel's
    whole hit-testing vocabulary."""
    x1, y1, x2, y2 = rect
    return x1 <= x < x2 and y1 <= y < y2


def _fit(text: str, line_chars: int, max_lines: int) -> str:
    """`text` word-wrapped to at most `max_lines` lines of about `line_chars`,
    with an ellipsis on the last when there was more.

    The fixed-height band's answer to Tk's width-only wrapping: wrapped here,
    on explicit newlines, the text cannot spill into the block below it — see
    `LINE_CHARS` for what this costs.
    """
    words, lines, cur = text.split(), [], ""
    truncated = False
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and len(trial) > line_chars:
            lines.append(cur)
            if len(lines) == max_lines:
                truncated = True
                break
            cur = word
        else:
            cur = trial
    if truncated:
        lines[-1] = lines[-1].rstrip() + "…"
    else:
        lines.append(cur)
    return "\n".join(lines)


class _Palette:
    """The Switch-workspace palette's state (Workspace.dc.html): the query,
    and the rows it leaves standing.

    Logic only, so a bare fixture can drive it — the window, the keys and the
    `set_workspace` call are CompactPill's, thin triggers beside it. The list
    is the folders Flow has been pointed at, most recent first: the profile's
    own record (`profile.workspaces`, written by `note_workspace`), so the
    order the profile keeps is already the palette's ranking, and a substring
    filter never re-sorts it.
    """

    #: The pinned last row (Workspace.dc.html). Choosing it clears the
    #: workspace, which is what `session.set_workspace(None)` already means.
    NONE = "No workspace — just talk"

    def __init__(self, workspaces) -> None:
        self.query = ""
        self.workspaces = list(workspaces)

    def type(self, ch: str) -> None:
        self.query += ch

    def backspace(self) -> None:
        self.query = self.query[:-1]

    def rows(self) -> list:
        """(label, is_none) per visible row: the query's substring hits in
        profile order, then the pinned row — always last, never filtered out."""
        q = self.query.lower()
        hits = [(w, False) for w in self.workspaces if q in w.lower()]
        return hits + [(self.NONE, True)]

    def choose(self, index: int = 0):
        """What the highlighted row (or row `index`) hands
        `session.set_workspace` — the path, or None for the pinned row."""
        label, is_none = self.rows()[index]
        return None if is_none else label


class CompactPill(tk.Tk):
    """The wordless capsule. Press and hold to talk, tap to switch mode."""

    #: Declared on the class, not only assigned in `__init__`, and that is
    #: load-bearing — the same reason every one of these carries in ui.py:
    #: `tk.Misc.__getattr__` forwards an unknown attribute to `self.tk`, so on
    #: an instance built with `__new__` — which is how every UI test fixture in
    #: this suite builds one — a missing name recurses until the stack ends
    #: instead of defaulting (item 32 found exactly this as a RecursionError
    #: through the full Pill). A class attribute is a real lookup that never
    #: reaches `__getattr__`; `__init__` overrides it per instance.
    lite = False
    armed = False
    hotkeys = None
    on_send = None
    settings_path = None
    #: `_tick`'s re-schedule and `quit_app`'s idempotence both read this, so a
    #: bare fixture has to find it here. True: a fixture that drives `_frame`
    #: directly is alive by definition.
    _alive = True
    #: The eased and the drawn level, read by `_frame` and `_draw`. A bare
    #: fixture draws the silent meter these describe.
    _eased_level = 0.0
    _meter_level = 0.0
    #: Frames of error flash left. Zero — no flash — is what a fixture reads.
    _flash = 0
    #: The press's two clocks and two flags: when the button went down, where
    #: (root coordinates, for the drag slop), whether it has travelled since,
    #: and whether the frame pump has already turned it into an utterance. All
    #: idle here, which is the state a fixture that never touched a mouse
    #: should read as — the same four, for the same reason, as ui.py's press
    #: defaults at flow/ui.py:2394-2398.
    _press_at: float | None = None
    _press_xy = (0, 0)
    _press_moved = False
    _press_talking = False
    #: Where inside the window the press landed, so a drag moves the pill by
    #: the pointer's travel rather than snapping its corner to the cursor.
    _drag = (0, 0)
    #: `tkfont.Font(...).measure` per font spec, built on demand by `_measure`.
    _fonts: dict = {}
    #: Where the frame draws, and where a box's frame draws. `None` on a bare
    #: fixture, which never presents; `_draw` sets `paint` from the canvas in
    #: `__init__`, and the tests hand it their recording fake directly.
    paint = None
    _box_paint = None
    #: Device pixels per design pixel on this window's monitor. 1.0 until
    #: `__init__` asks, and 1.0 for good on a DPI-unaware process, a Mac or a
    #: Linux desktop — so a fixture that never asked reads the identity.
    k = 1.0
    #: Where the window is, and where the capsule's top edge is, both in
    #: device pixels and both *tracked* rather than read back. `winfo_rootx`
    #: and `winfo_rooty` lag a `geometry` call by a frame or two — the same
    #: staleness `_open_box` records for its own anchor — so a `_sync_shell`
    #: that read them re-anchored off the position before last and walked the
    #: window down the screen by the panel's height each time. At 100 % that
    #: was survivable and unnoticed; at 300 % it is 600 px a step, and the
    #: pill left the bottom of the display.
    _shell_xy = (0, 0)
    _capsule_y = 0
    #: The monitor this window is placed against, as the two rectangles the
    #: shipped design places against — `full` to centre on, `work` to stand on.
    #: Class defaults so a `__new__`-built fixture can read them without a Tk.
    #: Refreshed by `_sync_monitor`, because a pill that can be dragged can be
    #: dragged onto another monitor and these were read once, in `__init__`.
    full = (0, 0, 1920, 1080)
    work = (0, 0, 1920, 1080)
    #: Every monitor's bounding box — what a *drag* may cross, as against the
    #: one monitor a placed window is clamped into. `None` until a
    #: `_sync_monitor` has answered, which is what makes `_move_window` fall
    #: back to `work` on a fixture that has no Win32 to ask.
    desktop = None
    #: `_sync_monitor`'s frame counter, on the class for the reason all of
    #: these are: `_frame` increments it, and a fixture that drives `_frame`
    #: directly has no `__init__` to have set it.
    _frame_no = 0
    #: The right-click menu, built in `__init__`. None on a fixture, and
    #: `_on_menu` checks rather than assuming. `_mode_var` is the radios'
    #: tick, on the instance because a Tk variable dies with the frame that
    #: created it (see `_populate_menu`).
    _menu = None
    _mode_var = None
    #: The Design cascade's submenu, built once and kept. `_populate_menu`
    #: clears the top-level menu on every open, and Tk's `delete` unlinks a
    #: cascade *entry* while the submenu behind it is a widget of its own that
    #: outlives it — so a fresh `_dark_menu` per right-click leaked one
    #: `tk.Menu` per right-click, for the life of a process that is always on.
    _design_sub = None
    #: What the last `draft` event carried — the text the send path hands
    #: over, and what item 3's panel `heard` block will read. "" on a fixture,
    #: which is also the true answer for a pill that has heard nothing.
    _last_draft = ""
    #: Armed by a release whose `talk_end` reported words in flight; fired by
    #: the `draft` event that brings them. The send path's whole state, and
    #: False on a fixture for the same reason the press flags are idle there.
    _send_pending = False
    #: The window Send is aimed at, polled by `_track_target` the way ui.py's
    #: own `paste_target` is (flow/ui.py:2486). None on a fixture, which is
    #: also the Lite answer: no target-window awareness, and `paste()` asks
    #: the foreground instead.
    paste_target = None
    #: The panel's whole state: open or not; the mode it was opened for, which
    #: is what its spec lookup keys on — the drawing follows the mode that
    #: *raised* it, so an answer landing after a mode switch still draws as
    #: the Ask it is; the heard block's text and whether it is final (a
    #: partial draws italic, the draft does not); the result block's text; and
    #: the release-armed ask waiting on its draft. All closed and empty on a
    #: fixture, which is the resting pill.
    _panel_open = False
    _panel_mode = None
    _panel_heard = ""
    _panel_heard_final = False
    _panel_result = ""
    _ask_pending = False
    #: Whether the hold in flight has yet to say anything. Set by a panel-mode
    #: `_talk_start` and cleared by the first thing that arrives — a `partial`,
    #: or `_ask` when the question fires. It is what moves "the next hold
    #: starts fresh" (Ask.dc.html) from the press to the words: a hold that
    #: hears nothing must leave the answer on screen exactly as it was, and
    #: clearing at the press destroyed it before a syllable had landed. False
    #: on a fixture, which is a pill holding nothing.
    _hold_fresh = False
    #: The window's current size: PILL_W × PILL_H alone, PANEL_W ×
    #: (PANEL_H + PILL_H) with the band. `_sync_shell` no-ops on equality,
    #: which is what a bare fixture's values describe.
    _shell_w = PILL_W
    _shell_h = PILL_H
    #: The outside-click poll's edge detector: the button's last read.
    _outside_was_down = False
    #: The tray's three states (the escape hatch the canvas said no to and
    #: 2026-09-03 kept — design/compact/README.md): the icon, the queue it
    #: puts its clicks on, and whether the window is hidden behind it. All
    #: idle on a fixture, which is a pill that was never hidden.
    _tray = None
    _tray_events = None
    _hidden = False
    #: Where the window was when it was hidden, so `show_from_tray` puts it
    #: back rather than where the window manager feels like.
    _home = None
    #: The standalone box (palette or setup) and its state: one at a time,
    #: None when closed — which is all a fixture ever sees. `_palette` holds
    #: the palette's logic while its box is open; `_box_kind` says which box.
    _box = None
    _box_canvas = None
    _box_kind = ""
    _palette = None
    #: The box's anchor: left edge and bottom row, recorded at open because
    #: `winfo_*` lags a `geometry` call by a frame and `_sync_box` re-heights
    #: off them. Zero on a fixture, whose box is never open.
    _box_x = 0
    _box_foot = 0
    #: The three fallback states the ring can be in without a session state
    #: behind them (States.dc.html). `_mic_gone` is the persistent one: the
    #: mic is blocked or unplugged, so the glyph wears a slash and the ring
    #: stays red until a capture answers — the one gesture the pill refuses
    #: outright. `_recover` is the amber launch notice's countdown. `_copied`
    #: is Lite's clipboard notice's countdown. All zero/False on a fixture,
    #: which is a healthy pill.
    _mic_gone = False
    _recover = 0
    #: Frames of notice strip left, and what it says. `_copied` was this
    #: with one hardcoded sentence; the strip is the same strip.
    _notice = 0
    _notice_text = COPIED_TEXT
    #: How wide the strip has to be for its words. The pill is 120 px and a
    #: sentence is not: measured when the notice is set, because a strip that
    #: keeps the capsule's width simply cuts its own message in half — which
    #: is what `.shots/22-compact-mic-silent.png` showed the first time.
    _notice_w = PILL_W
    #: When the hold in flight opened the microphone. Its own clock rather
    #: than `_press_at`, because `_on_release` clears that *before* calling
    #: `_talk_end` — so a release measuring against it measured zero, and the
    #: silence check below could never fire on a real hold.
    _hold_since = None
    #: The loudest level seen during the hold in flight, so a release can tell
    #: a quiet room from a microphone that is delivering nothing at all.
    #: Whether the CLI's failure line is what's in the result block — so Copy
    #: and Send hand over the raw dictation instead, because unrefined text
    #: beats no text.
    _panel_failed = False
    #: The capsule's y-offset inside the window — the panel band's height at
    #: the last `_sync_shell`. The capsule's screen position is the anchor
    #: every resize keeps ("the pill never hides and never moves").
    _capsule_off = 0
    #: Whether the window is out of the activation chain. Set in `__init__`
    #: from `_no_activate`'s read-back; False on a fixture, which is the
    #: Lite/Mac answer `_on_menu`'s foreground borrow keys off.
    no_activate = False
    #: What `_draw_key` answered for the frame currently on screen, or None
    #: for "whatever is up there, do not trust it". A class default because
    #: `_frame` reads it before anything has ever set it — and None on a bare
    #: fixture is the honest answer: nothing has been composited at all.
    _drawn_key = None

    def __init__(
        self, session: Session, on_send=None, hotkeys=None, arm=False,
        settings_path=None, lite=False,
    ) -> None:
        super().__init__()
        self.session = session
        self.on_send = on_send
        self.hotkeys = hotkeys
        self.lite = lite
        self.settings_path = (
            Path(settings_path) if settings_path is not None else None
        )
        self.armed = False
        self._eased_level = 0.0
        self._meter_level = 0.0
        self._flash = 0
        self._press_at = None
        self._press_xy = (0, 0)
        self._press_moved = False
        self._press_talking = False
        self._drag = (0, 0)
        self._fonts = {}
        self._last_draft = ""
        self._send_pending = False
        self.paste_target = None
        self._panel_open = False
        self._panel_mode = None
        self._panel_heard = ""
        self._panel_heard_final = False
        self._panel_result = ""
        self._ask_pending = False
        self._hold_fresh = False
        self._shell_w = PILL_W
        self._shell_h = PILL_H
        self._outside_was_down = False
        self._tray = None
        self._tray_events = queue.Queue()
        self._hidden = False
        self._home = None
        self._box = None
        self._box_canvas = None
        self._box_kind = ""
        self._palette = None
        self._mic_gone = False
        self._recover = 0
        self._notice = 0
        self._notice_text = COPIED_TEXT
        self._panel_failed = False
        self._capsule_off = 0

        # The window. `_shell_window` applies the five probed attributes and
        # answers with the background the canvas must agree with — see its
        # docstring for why the background is returned rather than assumed.
        # Where it opens, and this was missing: the window was given a size and
        # no position, so Windows dropped it in the top-left corner — over the
        # menu bar of whatever was behind it, which is the one place a
        # always-on-top pill must not be. `bottom_centre` is the shipped
        # design's own arithmetic (FluidVoice's `positionWindow`): centred on
        # the monitor under the pointer, stood clear of the taskbar. The same
        # place, on every machine, whatever is docked to which edge.
        # Asked once the window exists, because it is a property of the
        # monitor the window is on and there is no window before now.
        self.k = paint.scale_for(self)
        self.full, self.work = _pointer_monitor(
            self.winfo_screenwidth(), self.winfo_screenheight(), self)
        x, y = bottom_centre(self.dev(PILL_W), self.dev(PILL_H),
                             self.full, self.work,
                             round(PANEL_BOTTOM_OFFSET * self.k))
        self.geometry(f"{self.dev(PILL_W)}x{self.dev(PILL_H)}+{x}+{y}")
        self._shell_xy = (x, y)
        self._capsule_y = y
        bg = _shell_window(self, lite, PILL_ALPHA)
        self.configure(bg=bg)
        self.canvas = tk.Canvas(
            self, width=self.dev(PILL_W), height=self.dev(PILL_H), bg=bg,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        # What the frame actually draws on. `painter_for` answers with a
        # `GdiCanvas` where Windows can composite per-pixel alpha and with
        # this canvas everywhere else — same calls either way, which is why
        # every `_draw_*` below takes the target as an argument and none of
        # them knows which it got.
        #
        # The key comes off when it does: `-transparentcolor` and a layered
        # window are two answers to the same question, and Windows honours the
        # key, so leaving it set would punch the pill's own `SHELL` pixels out
        # of the bitmap we just antialiased.
        self.paint = paint.painter_for(self.canvas, PILL_W, PILL_H, lite,
                                       PILL_ALPHA, self.k)
        if getattr(self.paint, "antialiased", False):
            _unkey(self)

        # Three gestures on one button (README: "Tap (< PILL_HOLD_SEC) cycles
        # the mode; hold talks; right-click is the only menu"). The hold is
        # not a timer of its own: the 30 ms frame is the only clock this pill
        # has — the same rule ui.py states for its dots and its flash — so a
        # press past the threshold becomes an utterance in `_pump_press`, and
        # a release that never got there is a tap.
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_menu)
        # The panel's Esc (README: "Send / Esc / click-outside closes"). The
        # window is out of the activation chain, so this only ever fires where
        # the style cannot take (Lite, a Mac); everywhere else Esc is the
        # `cancel` hotkey, which is global and does not ask who has focus.
        self.bind("<Escape>", lambda _e: self._close_panel())

        self._menu = _dark_menu(self)
        self._populate_menu(self._menu)

        # Out of the activation chain, like every Flow window (ui.py:2570). Not
        # cosmetic: a window the click *activates* is raised and focused by it,
        # which both disturbs the z-order under the always-on-top band and earns
        # the popup a foreground it must then be refused — see `_on_menu`.
        self.no_activate = _no_activate(self)

        if arm:
            try:
                self.session.start()
            except Exception:
                # No microphone, a device held exclusively elsewhere. Stay
                # disarmed and slash the glyph, rather than showing a green
                # ring over a capture that does not exist — `_toggle`'s rule,
                # kept here.
                self._flash = FLASH_FRAMES
                self._mic_gone = True
            else:
                self.armed = True

        # States.dc.html's amber case, detected once, at launch.
        self._check_workspace_gone()

        # The icon goes up now, because the pill's menu no longer carries a
        # way out — see `_start_tray`. A machine with no notification area
        # says so by returning False, and nothing here depends on it.
        self._start_tray()

        self.after(30, self._tick)

    # `mainloop` is tk.Tk's own, and that is deliberate: __main__.py drives
    # this class exactly as it drives Pill — construct, `mainloop()`, and
    # `quit_app()` out of the KeyboardInterrupt clause.

    def dev(self, v) -> int:
        """A design length in device pixels — what Tk geometry now takes.

        Every size in this module is written in the units
        `design/compact/gen.py` uses, and the whole DPI story is that those are
        no longer the units the screen is measured in: on a 300 % display a
        120 px capsule is a 360 px window holding a bitmap GDI+ drew at 360 px.
        Rounded, not floored, so a 34 px pill at 150 % is 51 and not 50 — half
        a pixel of drift at the bottom edge is a hairline outside the window.

        Not clamped to a minimum, because this converts offsets as well as
        sizes and a zero offset is a real answer: floored at one, a closed
        panel moved the capsule a pixel every time it was drawn. Sizes here
        are constants that are never zero, and the bitmap clamps its own.
        """
        return round(v * self.k)

    def design(self, v) -> float:
        """A device length back in design pixels, for hit-testing.

        Tk reports pointer coordinates in device pixels once the process is
        DPI-aware, and every rectangle this module tests against is written in
        design pixels. Without this the panel's chips move out from under the
        pointer by exactly the scale factor.
        """
        return v / self.k

    def quit_app(self) -> None:
        # Idempotent, for the reason ui.py's is: ctrl+C reaches here down
        # either of two paths (caught in `_tick`, or escaping `mainloop`) and
        # nothing upstream can tell which one ran.
        if not self._alive:
            return
        self._alive = False
        try:
            # Before the hotkeys and before the window: an icon outliving its
            # process is a ghost in the notification area that only a hover
            # clears (ui.py:4114-4118, whose order this keeps).
            if self._tray is not None:
                self._tray.stop()
            if self.hotkeys is not None:
                self.hotkeys.stop()
            self.session.close()
            for painter in (self.paint, self._box_paint):
                close = getattr(painter, "close", None)
                if close is not None:
                    close()
        finally:
            self.destroy()

    # -- the pump ----------------------------------------------------------

    def _tick(self) -> None:
        """Drive one frame. Must never propagate an exception.

        The re-schedule is in `finally`, for the reason ui.py's `_tick` states
        at length: a raise out of this callback would break the `after()` chain
        and leave a pill on screen but dead, and for an always-on widget that
        is the worst available failure mode. An error becomes a red flash —
        which on this pill is the whole vocabulary for "something is wrong" —
        and the loop carries on.
        """
        try:
            self._frame()
        except KeyboardInterrupt:
            # Tcl's event loop is C, so a pending SIGINT is raised where Python
            # bytecode next runs — here. Taken as the quit it was, as ui.py
            # does, because the alternative is a microphone left open.
            self.quit_app()
        except Exception:
            self._flash = FLASH_FRAMES
            traceback.print_exc()
        finally:
            if self._alive:
                self.after(30, self._tick)

    def _frame(self) -> None:
        """One pull of the session: tick or collect, drain, ease, draw."""
        # Hotkeys arrive on their own thread; Tk is only ever touched from
        # this one.
        if not self._drain_hotkeys():
            return
        self._drain_tray()
        self._sync_monitor()
        self._track_target()
        if self.armed:
            self.session.tick()
            hearing = getattr(self.session, "hearing", True)
            target = self._norm(self.session.level_db) if hearing else 0.0
            self._meter_level = self._eased(target)
        else:
            # Still collect what the CLI owes us. Disarming must not strand an
            # answer already in flight — the defect ui.py's identical branch
            # comments on, and the reason `pump_results` exists separately.
            self.session.pump_results()
            self._meter_level = self._eased(0.0)
        self._pump_events()
        self._pump_press()
        if self._panel_open and self._outside_click_now():
            self._close_panel()
        if self._flash:
            self._flash -= 1
        if self._recover:
            self._recover -= 1
        if self._notice:
            self._notice -= 1
            if not self._notice:
                # The notice strip's time is up; the window is 120×34 again.
                self._sync_shell()
        # Only when the picture has changed. `_draw` rebuilds every item and
        # composites a whole bitmap, and an idle pill asked it to draw the
        # same pill thirty times a second — see `_draw_key` for the numbers
        # and for what makes the key trustworthy. Stored before the draw, the
        # way the shipped surface does it: a `_draw` that raises is a frame
        # `_tick` turns into a flash, and the flash moves the key itself.
        key = self._draw_key()
        if key != self._drawn_key:
            self._drawn_key = key
            self._draw()

    def _sync_monitor(self) -> None:
        """Which monitor the *window* is on, re-asked every fourth frame.

        `self.full` and `self.work` were read once, in `__init__`, off the
        pointer — and then never again for the life of the process. Everything
        that keeps this surface on screen clamps against them: `_move_window`'s
        drag bounds, `_sync_shell`'s four edges, the box's right edge. So a
        pill dragged to a second monitor spent the rest of the session being
        clamped into a rectangle it had left, and the first panel it opened
        was thrown back onto the primary display. That is not a rounding
        error; it is the whole width of a monitor.

        **Keyed on the window, where `Pill._sync_monitor` (flow/ui.py:4233) is
        keyed on the pointer.** The shipped design re-places its stack when the
        pointer changes screen, so the pointer *is* the question there. This
        one is dragged by hand and stays where it was put, so the question is
        where the capsule is standing — and during a drag those two differ for
        as long as the seam takes to cross. The point asked about is the
        capsule's centre in device pixels: the window is 400 px wide with the
        band up and the capsule is 120, so asking about the window's corner
        near a seam would hand the far monitor's rectangle to a pill standing
        on this one.

        Every fourth frame (~120 ms), for the reason `Pill._frame` states at
        flow/ui.py:4318: the question is three ctypes calls, the answer changes
        a few times an hour, and a tenth of a second is fast enough to follow a
        window across a seam.
        """
        if not self._alive:
            # The tray's Quit is drained one line above the call to this, and
            # it destroys the window inside the frame that is still running —
            # so this is the first line afterwards that asks Tk for anything,
            # and "application has been destroyed" would land as a traceback
            # on the console of somebody who has just pressed quit. `_present`
            # catches the same thing at the other end of the frame.
            return
        self._frame_no += 1
        if self._frame_no % 4 != 1:
            return
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.full, self.work = _monitor_at(
            self._shell_xy[0] + self.dev(self._shell_w) // 2,
            self._capsule_y + self.dev(PILL_H) // 2, sw, sh, self)
        # What a drag is allowed to cross: every monitor there is, the union
        # `park_spot` already places against. Asked here rather than inside
        # `_move_window` so a drag costs no Win32 calls of its own — a motion
        # event arrives far more often than every 120 ms.
        self.desktop = _virtual_desktop(sw, sh)

    def _drain_hotkeys(self) -> bool:
        """Act on every hotkey that arrived since the last drain. False after a quit.

        The names are the ones `Pill._drain_hotkeys` (flow/ui.py:4333) acts on.
        `send` is bound here rather than arriving with the panel, because it was
        never the panel's: a dictation surface with no send is not a dictation
        surface. `cancel` is the panel's Esc ("Send / Esc / click-outside
        closes", design/compact/README.md) — a chord rather than a key binding
        because this window never has focus for one to fire on. A name this loop
        does not know falls through, which is what an unbound chord does in the
        full UI too.
        """
        if self.hotkeys is None:
            return True
        for name in self.hotkeys.drain():
            if name == "toggle":
                self._toggle()
            elif name == "warm":
                # The chord's press-down, one put ahead of `talk`, so the
                # models load during the hold instead of inside the sentence.
                self.session.warm()
            elif name == "talk":
                self._talk_start()
            elif name == "talk-end":
                self._talk_end(send=True)
            elif name == "talk-break":
                # Windows meant `ctrl+win+d`. What was said is committed either
                # way (session.talk_end's own contract, P2); it simply does not
                # paste itself into whatever window a desktop switch moved to.
                self._talk_end(send=False)
            elif name == "send":
                self._send()
            elif name == "cancel":
                self._close_panel()
            elif name == "mode":
                self._cycle_mode()
            elif name == "quit":
                self.quit_app()
                return False
        return True

    def _check_workspace_gone(self) -> None:
        """States.dc.html's amber case: the workspace the profile remembers is
        gone. `resolve_workspace` has already dropped it and said so on the
        console (flow/profile.py:289-291) — the fallback to no workspace is
        done; the pill's half is to say it the one way this surface can,
        once, in amber. A hold or the countdown ends the notice."""
        stored = getattr(getattr(self.session, "profile", None),
                         "workspace", None)
        if stored and not Path(stored).is_dir():
            self._recover = RECOVER_FRAMES

    def _cli_offered(self) -> bool:
        """Whether Refine and Ask exist on this machine right now
        (States.dc.html: with no agent CLI on PATH they are simply not
        offered). The same answer the setup box's "none found" gives —
        `Session.provider`'s own cache pays the PATH lookup, and it is the
        public seam for it: this is a surface asking the session a question,
        not a surface reading the session's implementation."""
        return bool(self.session.provider)

    def _cycle_mode(self) -> None:
        """The tap's and the `mode` chord's cycle, filtered by what the
        machine offers.

        The session stays three-mode — the shipped UI cycles through all
        three and a CLI can arrive mid-session. The exclusion is this
        surface's, and it is grey, not red: no flash, no error, Type simply
        does not cycle. Already off Type (the CLI vanished mid-session), the
        one cycle that still runs is the way back to it.

        Both endings go through `_choose_mode`, which is where the pending
        send is dropped — this method used to carry that rule alone, and the
        menu's radios, which change the mode just as completely, did not.
        """
        if self._cli_offered():
            self._choose_mode(None)
        elif self.session.mode != DICTATE:
            self._choose_mode(DICTATE)

    def _choose_mode(self, to: str | None) -> None:
        """Change mode, from whichever gesture asked. `None` is the cycle.

        **The one seam, because the rule under it was in one of two places.**
        A pending paste belongs to the mode it was spoken in (ui.py:4363-4369)
        — so the arm is dropped here, and the words themselves stay in the
        draft, which is `toggle_mode`'s own promise. `_cycle_mode` had that;
        `_populate_menu`'s radios called `session.toggle_mode(to=)` straight
        and did not. Choose Ask from the menu with a Type paste waiting and the
        arm survived the switch: the next `draft` fired `session.send()` in
        CONVERSE, which asks — so the words went to the CLI as a question
        instead of into the window they were dictated for, and the only sign
        was an answer to something nobody had asked.

        `_ask_pending` goes with it, for the mirror of the same reason: a
        release in Ask that is still waiting on its decode must not fire an
        ask into a session that is now in Type.

        The cycle keeps its own call rather than passing `to=None`. They are
        the same thing to the session and not the same thing to read: one is
        "next mode", the other is "this mode", and the session's API says so
        with two forms.
        """
        self._send_pending = False
        self._ask_pending = False
        if to is None:
            self.session.toggle_mode()
        else:
            self.session.toggle_mode(to=to)

    def _pump_events(self) -> None:
        """Drain what the session said since the last frame.

        The pill itself owns two persistent kinds — an error turns the ring
        red (and a CLI's failure line joins the panel's result block; a
        `disarm` that is not a release means the device is gone, and the
        slash stays until a capture answers). The send path owns `draft`: the
        decode landing, its text what `_send` hands over when a Type release
        is waiting — release, draft, paste, and no panel (README: "Type never
        opens a panel"). The panel owns the rest: a `partial` is the heard
        block's live text, a `draft` against an armed ask is the question
        going to the CLI, a `reply` is the answer landing in the result
        block, and a `mode` closes the band — it belongs to the mode that
        raised it.

        And the four kinds after `disarm` are the ones that used to fall
        through, which on a wordless surface is not the same as "nothing to
        draw": a spoken `send` trigger did nothing at all, and a `drop`, an
        `edit` and Send's refusal notes were the surface's whole answer to
        "why did that not work". They go on the notice strip, which is the
        channel that now exists for exactly this — see `SAID_NOTES` for which
        notes, and for the ones deliberately left silent. `conversation` still
        needs nothing: there is nothing of it on this screen to clear.
        """
        for ev in self.session.events():
            if ev.kind == "draft":
                self._last_draft = ev.text
                if not ev.text or self._press_talking:
                    # Not mid-hold: a flag still armed from an earlier release
                    # must not fire on a segment final inside the *next*
                    # utterance. The words are cumulative in the draft either
                    # way — the next release re-arms and sends them all.
                    continue
                if self._send_pending:
                    self._send()
                elif self._ask_pending:
                    self._ask()
            elif ev.kind == "partial":
                if self._panel_open:
                    if self._hold_fresh:
                        # The words of this hold have arrived, so *now* the
                        # exchange before it goes. `_talk_start` marks the
                        # hold and clears nothing — see there for the answer
                        # this used to wipe off the screen at the press.
                        self._hold_fresh = False
                        self._panel_result = ""
                        self._panel_failed = False
                    # The heard block's live text — italic until the release's
                    # draft makes it final.
                    self._panel_heard = ev.text
                    self._panel_heard_final = False
            elif ev.kind == "reply":
                if ev.text:
                    # Whatever hold is in flight has been overtaken: this
                    # answer is newer than the exchange that hold was going to
                    # clear, so the arming goes and the next partial leaves it
                    # standing. Hold again before the CLI has answered — 4-20 s
                    # is long enough that people do — and without this the
                    # answer appeared and was wiped by the first word of the
                    # follow-up, which is a fact arriving and being taken away.
                    self._hold_fresh = False
                    self._panel_failed = False
                    self._panel_result = ev.text
                    # Never silent (P2): if the panel was closed while the CLI
                    # was working, the answer reopens it rather than landing
                    # nowhere. Esc is "not looking right now", not "never tell
                    # me" — the question was asked from this surface.
                    self._open_panel()
            elif ev.kind == "mode":
                self._close_panel()
            elif ev.kind == "error":
                self._flash = FLASH_FRAMES
                if (self._panel_open
                        and ev.text.startswith(("refine failed", "ask failed"))):
                    # The panel opens holding the raw dictation; the CLI's own
                    # last line is the message, not a generic failure
                    # (States.dc.html). Send still works — `_panel_text`
                    # answers with the raw text, because unrefined text beats
                    # no text. Notes that are not this stay unread: the
                    # failure arrives as an `error`, and the rest have no
                    # surface the artboards draw.
                    self._panel_failed = True
                    self._panel_result = ev.text
            elif ev.kind == "disarm":
                self.armed = False
                if ev.text != "push-to-talk":
                    # Not a release — the device itself went away and did not
                    # come back (ui.py:4526-4532's case, the same words). The
                    # slash and the red ring persist until a capture answers.
                    self._mic_gone = True
            elif ev.kind == "send":
                # The spoken trigger — "boom", or "enter boom" for a paste
                # that presses Enter after itself (`edits.enter_word`). It
                # presses the same button the `send` hotkey does, arrived at
                # by a different route, which is ui.py:4558-4562's rule and
                # the reason the paste is decided here rather than in the
                # session: it belongs to this thread and to `paste_target`.
                # Without this branch the trigger word was simply inert on
                # this surface, and "enter boom" had nowhere to put its Enter.
                self._send(submit=ev.text == "enter")
            elif ev.kind == "drop":
                # An utterance Flow rejected. Said, never swallowed: P2 is
                # that a rejection is never silent, and on a pill with no
                # words the alternative was speech vanishing with no event
                # anybody could see.
                self._say(ev.text)
            elif ev.kind == "edit":
                # A correction Flow applied — "changed 'thursday' to
                # 'Tuesday'". The whole feedback a spoken correction gets, and
                # invisible here until now: the draft is not on screen in Type
                # mode, so the strip is the only place the change can be seen
                # at all. The shipped surface offers a way back with it
                # (`undoable=True`); this one has no chip to offer, and saying
                # what happened is the half it can do.
                self._say(ev.text)
            elif ev.kind == "note" and ev.text.startswith(SAID_NOTES):
                # The few notes no colour on this pill can carry — see
                # `SAID_NOTES`, which is also the list of what stays silent
                # and why.
                self._say(ev.text)

    def _ask(self) -> None:
        """The panel-mode release: the heard block's final text goes to the CLI.

        `session.send()` in converse starts the ask and returns "" — the words
        are never pasted, which is the Type-only paste rule `_talk_end`'s gate
        states: Ask results land here, not in the window you were in. The
        answer itself arrives 4-20 s later as a `reply` event.

        The other end of `_talk_start`'s deferred clear: the question is
        leaving, so the exchange before it goes now if no partial already took
        it — a short hold whose only words land in the release's draft still
        starts fresh.
        """
        self._ask_pending = False
        self._hold_fresh = False
        self._panel_failed = False
        self._panel_heard = self._last_draft
        self._panel_heard_final = True
        self._panel_result = ""
        self.session.send()

    def _send(self, submit: bool = False) -> None:
        """Hand the draft over: the words paste, or the ring says they could not.

        The shape is ui.py's `_send` (flow/ui.py:3756-3770) — the text from
        `session.send()`, the paste target this surface polls, the problem the
        handler hands back — down to the first line, which is what stops a
        release and the `send` hotkey pasting the same words twice. The way
        out itself is `_deliver`'s, shared with the panel's Send.

        `submit` presses Enter after the paste and arrives from one place
        only: the spoken "enter boom", routed here as a `send` event. No chip
        and no hotkey can set it, which is the same rule the shipped surface
        runs under.

        Type is dictate and `session.send()` in dictate never asks — but this
        is not a Type-only path any more, because the trigger word can be
        spoken in any mode. In a panel mode `send()` returns "" and starts the
        ask instead, exactly as it does for the shipped `_send`, and nothing
        here needs to know which happened: an empty return delivers nothing,
        and the refusal notes say why when the answer is neither.
        """
        self._send_pending = False
        text = self.session.send()
        if text:
            self._deliver(text, submit=submit)

    def _deliver(self, text: str, submit: bool = False) -> None:
        """The words' way out, shared by both sends: paste where the user
        was, or Lite's clipboard — which is not an error state, and says so
        under the pill rather than flashing (States.dc.html's last case).
        Where the full pill spends a problem on a bubble card, this one has
        no words to say it with: a problem is the red flash, the whole
        vocabulary for "something is wrong" that is not a fallback with its
        own artboard.

        With no handler the copy is what is left, and a `submit` there is
        still just a copy: the clipboard cannot press Enter for anybody, so
        the strip names the step that is theirs. Refusing the enter-variant
        was the alternative and it is wrong on `edits.enter_word`'s own
        argument — a decode that drops a word from "enter boom" yields
        "boom", so refusing would make the degraded decode the working case.
        """
        if self.on_send:
            # Passed only when it is true, the idiom ui.py:3803-3806 keeps for
            # the same reason: a handler written before the flag existed —
            # `send_check.py`'s two-argument fixture is one — still works.
            extra = {"submit": True} if submit else {}
            problem = self.on_send(text, self.paste_target, **extra) or ""
            if problem:
                self._flash = FLASH_FRAMES
        elif _copy_to_clipboard(self, text):
            self._flash = FLASH_FRAMES
        else:
            self._say(COPIED_ENTER_TEXT if submit else COPIED_TEXT)
            self._sync_shell()

    def _track_target(self) -> None:
        """Remember the last window that had the foreground and was not Flow's own.

        ui.py:4223-4244's poll, minus the per-app classification this surface
        has no slot for: by the time `paste()` runs, the gesture that started
        it has had its chance to move the foreground, so the target is asked a
        frame at a time rather than at send time. Lite has no target-window
        awareness and does not ask — which is what makes `--lite` here the
        same code a Mac runs instead of a rehearsal of it.
        """
        if self.lite:
            return
        hwnd = foreground_hwnd()
        if hwnd and not owned_by_flow(hwnd):
            self.paste_target = hwnd

    def _pump_press(self) -> None:
        """Turn a press that has outlived `PILL_HOLD_SEC` into an utterance.

        Polled here rather than scheduled with `after`: the frame is the only
        clock, and a timer would be a second thing a bare test fixture has no
        Tk to run. A press that moved past the drag slop is a drag, not a
        hold, and never reaches `talk_start`.
        """
        if (self._press_at is None or self._press_talking
                or self._press_moved):
            return
        if time.perf_counter() - self._press_at < PILL_HOLD_SEC:
            return
        self._talk_start()
        if not self._press_talking:
            # The refusal `_toggle` also makes: a green ring over a dead
            # capture is the one lie this surface must not tell — and this
            # press is over, so it cannot become a tap either.
            self._press_at = None
            return

    # -- the gestures --------------------------------------------------------

    def _talk_start(self) -> None:
        """The hold beginning, shared by the mouse pump and the `talk` hotkey.

        A hold in a panel mode raises the panel at once — the heard block is
        where the partials land — and arms a fresh start: "the next hold
        starts fresh" (Ask.dc.html), which is also what makes the foot's "hold
        to reply" a reply rather than an append. Type is not in `PANEL_SPEC`,
        so its holds change nothing on screen (README: "Type never opens a
        panel").

        **Armed, not done.** The blocks used to be emptied right here, and
        that read the artboard's sentence as being about the press when it is
        about the thread: hold to reply, hear nothing or change your mind, let
        go, and `_talk_end` found nothing pending over an empty band and took
        the panel down — so the answer somebody was reading vanished because
        they touched the button, before a single word had arrived. The clear
        waits for words now (`_hold_fresh`), and a hold that hears nothing
        leaves the last exchange exactly as it was — which the release's own
        rule then keeps on screen, the band having something to show.

        A hold into a dead microphone is the one gesture the pill refuses
        outright (States.dc.html): the refusal is the persistent slashed
        glyph and red ring, not a flash that forgets by morning. A capture
        that answers clears the slash — it was about then, not now.
        """
        self._press_talking = True
        try:
            self.session.talk_start()
        except Exception:
            self._press_talking = False
            self._mic_gone = True
            self._flash = FLASH_FRAMES
            return
        self._mic_gone = False
        # **Armed here, and this is the whole of "push to talk does nothing".**
        # `_frame` pumps the session only while armed — `session.tick()` is
        # what reads the microphone — and this used to be set in
        # `_pump_press`, which is the *mouse* path. A chord hold went through
        # here instead, opened the device, and then sat in a frame loop that
        # never once read from it: `capturing` true, the ring green, and not a
        # sample pumped for the whole hold. The chord is the documented
        # push-to-talk gesture, so that was every hold that mattered.
        self.armed = True
        # The hold's own clock: `_on_release` clears `_press_at` before
        # `_talk_end` runs, so anything measuring the hold needs its own.
        self._hold_since = time.perf_counter()
        self._recover = 0  # a hold ends the launch notice: seen, and moved on
        if self.session.mode in PANEL_SPEC:
            self._panel_mode = self.session.mode
            self._hold_fresh = True
            self._open_panel()

    def _talk_end(self, *, send: bool) -> None:
        """The release, shared by the mouse and both hotkey endings.

        `send=False` is the `ctrl+win+d` path: the words are still committed
        and still land in the draft — nothing spoken is ever dropped (P2) —
        they simply do not paste themselves into whatever window a desktop
        switch just moved to. ui.py states the same at flow/ui.py:2760-2768.

        The send is *armed*, not fired: the decode is still in flight, and the
        `draft` event that brings the words is what fires it (`_pump_events`).
        What it arms is the mode's own path — Type's paste, a panel mode's ask
        — and the paste rule stays Type-only: an Ask hold while the panel is
        up is a reply, and its result lands in the panel, never in the window
        you were in (README: "Type never opens a panel").

        A hold with nothing said into it ends in nothing: straight back to
        grey, no panel, no toast (States.dc.html). The band the hold raised
        has nothing to show, so it goes back down — silence is a normal thing
        to do with a push-to-talk button.
        """
        self._hold_since = None
        self._press_talking = False
        pending = self.session.talk_end()
        if send and pending:
            if self.session.mode == DICTATE:
                self._send_pending = True
            elif self.session.mode in PANEL_SPEC:
                self._ask_pending = True
        elif (not pending and self._panel_open
                and not (self._panel_heard or self._panel_result)):
            self._close_panel()

    def _toggle(self) -> None:
        """The arm/disarm click's logic, shared by the hotkey of the same name."""
        if self.armed:
            self.armed = False
            self.session.pause()
        else:
            try:
                self.session.start()
            except Exception:
                self._flash = FLASH_FRAMES
                self._mic_gone = True
                return
            self._mic_gone = False
            self.armed = True

    def _on_press(self, e=None) -> None:
        """The button going down: remember when and where, decide nothing yet.

        Except where: with the panel open, a press in the band is a chip
        click, never a hold — the foot is the part that stays holdable
        (README), and the band is the part with buttons on it.
        """
        if (self._panel_open and e is not None
                and self.design(getattr(e, "y", self.dev(PILL_H))) < PANEL_H):
            self._panel_click(e)
            return
        self._press_at = time.perf_counter()
        self._press_xy = (getattr(e, "x_root", 0), getattr(e, "y_root", 0))
        # The grab point, from the event's own window-relative coordinates
        # rather than from `winfo_rootx()`. Two reasons, and either alone
        # would decide it: `winfo_*` lags a `geometry` call by a frame (the
        # staleness `_open_box` records), and touching Tk here recurses
        # through `tk.Misc.__getattr__` on a `__new__`-built fixture — the
        # RecursionError this module's class defaults exist to prevent.
        self._drag = (getattr(e, "x", 0), getattr(e, "y", 0))
        self._press_moved = False
        self._press_talking = False

    def _on_motion(self, e=None) -> None:
        """A press that travels past the slop drags the window.

        This used to only *record* that the press had moved, which made the
        drag slop work and left the pill nailed to wherever Tk first put it —
        "Drag it anywhere" (Main.dc.html) was the one gesture on the canvas
        with no code behind it.

        The order is `Pill._on_motion`'s (flow/ui.py:2712) and for its reason:
        once capture is open the pointer is irrelevant, because somebody
        talking into a held pill may well move the mouse and moving the window
        out from under them is the gesture betraying them. Before that, motion
        is both the thing that tells a drag from a hold and the drag itself.

        The offset is the grab point inside the window, taken on the press —
        without it the window snaps its own corner to the cursor on the first
        motion event, which is the defect flow/ui.py:2588-2592 records.
        """
        if self._press_at is None or self._press_talking:
            return
        x, y = getattr(e, "x_root", 0), getattr(e, "y_root", 0)
        # The slop is a design length and the travel is a device one, so the
        # threshold is converted rather than compared across units: at 300 % an
        # unconverted 4 px slop is a pixel and a third of real movement, and
        # every hold by a hand that is not perfectly still becomes a drag.
        slop = PILL_DRAG_SLOP * self.k
        if not (abs(x - self._press_xy[0]) > slop
                or abs(y - self._press_xy[1]) > slop):
            return
        self._press_moved = True
        self._move_window(x - self._drag[0], y - self._drag[1])

    def _move_window(self, x: int, y: int) -> None:
        """Put the window's top-left at `(x, y)`, clamped to the desktop.

        Its own method because it is the only part of a drag that touches Tk,
        and `_on_motion`'s other job — telling a drag from a hold — has to
        stay callable on a `__new__`-built fixture. Clamped so the pill cannot
        be thrown somewhere only the tray could get it back from; the window
        is the capsule plus whatever the panel and the notice have added, so
        the bound is the drawn size and not `PILL_W`/`PILL_H`.

        **Clamped to every monitor, not to the one it is on.** "Drag it
        anywhere" (Main.dc.html), and `self.work` is one screen: with that as
        the bound the pill stopped dead at the seam, because the pointer had
        crossed to the next monitor and the window was being pinned to the
        edge of this one — which reads as a pill that has snagged on nothing.
        `desktop` is the union `park_spot` already places against, refreshed by
        `_sync_monitor`, and the same sync brings `work` up to date a frame or
        four after the capsule lands on the other side. `None` on a fixture
        with no Win32 to ask, which then clamps to the single screen it has.
        """
        left, top, right, bottom = self.desktop or self.work
        dw, dh = self.dev(self._shell_w), self.dev(self._shell_h)
        nx = max(left, min(x, right - dw))
        ny = max(top, min(y, bottom - dh))
        self._shell_xy = (nx, ny)
        # The capsule moved with the window, so the anchor the band grows from
        # moves too — it sits below whatever panel height is currently drawn.
        self._capsule_y = ny + self.dev(self._capsule_off)
        self.geometry(f"{dw}x{dh}+{nx}+{ny}")
        # No box to re-anchor: the palette and the setup box hold the keyboard
        # and close on `FocusOut`, so the press that starts this drag has
        # already dismissed either of them.

    def _on_release(self, e=None) -> None:
        """The button coming up: a hold ends the talk, anything else is a tap.

        The tap does not re-check the clock. In real time the 30 ms frame has
        fired ten times inside `PILL_HOLD_SEC`, so a genuine hold is already
        `_press_talking` before any release can arrive — the pump is the
        decision, this is the dispatch. A drag is neither, and does nothing.
        """
        if self._press_at is None:
            return
        talking = self._press_talking
        moved = self._press_moved
        self._press_at = None
        self._press_moved = False
        if talking:
            self._talk_end(send=True)
        elif not moved:
            self._cycle_mode()

    def _populate_menu(self, m) -> None:
        """The only menu the design allows (Workspace.dc.html), rebuilt on
        every open: the mode check and the workspace path are live values,
        and a stale check over a new mode is the same lie as no check.

        Tk has no sub-line row, so the canvas's `msub` lines are disabled
        entries — `_dark_menu` already greys them. The mode rows go through
        `_choose_mode`, which is the chooser API (`toggle_mode(to=)`) plus the
        rule that has to travel with it: a flip cannot serve "choose Refine"
        in a three-mode world, and a mode change from here drops a pending
        paste for the same reason the tap does — see `_choose_mode`, which the
        radios used to bypass.

        **One row is here that the artboard does not draw**, and it is the
        one that lets somebody leave. `profile.design` decides which surface
        launches, and the control that writes it is a row in the *shipped*
        design's Settings menu — so with compact stored, the only switch there
        was lived inside the surface you could no longer reach. A one-way
        door, and `--design current` typed at a shell is not an answer for
        somebody who launched Flow from a shortcut. The owner relaxed the
        artboard's "everything it offers" for exactly this on 2026-09-04; the
        two designs are reachable from each other or they are not two designs
        somebody can choose between.

        Nothing else was let back in. Hide to tray and Quit are still gone —
        the tray icon carries those, raised at launch by `_start_tray`, and
        Quit is also the `quit` hotkey, which needs neither focus nor menu.
        """
        current = self.session.mode
        # On the instance, not the stack: a Tk variable dies with the frame
        # that created it, and a radiobutton whose variable is gone draws no
        # indicator — `.shots/06` showed three modes and no check until this
        # was `self.`.
        self._mode_var = tk.StringVar(value=MODE_NAME.get(current, ""))
        # No CLI on PATH: the cycle skips Refine and Ask, and the menu says so
        # the same way — grey, not absent (States.dc.html: a smaller Flow,
        # not a broken one; Workbench setup is the row that explains it).
        offered = self._cli_offered()
        for mode in (DICTATE, REFINE, CONVERSE):
            name = MODE_NAME[mode]
            kw = {} if mode == DICTATE or offered else {"state": "disabled"}
            m.add_radiobutton(
                label=name, value=name, variable=self._mode_var,
                command=lambda t=mode: self._choose_mode(t), **kw)
        m.add_command(label="tap the pill to cycle", state="disabled")
        m.add_separator()
        m.add_command(label="Switch workspace", command=self._open_palette)
        ws = getattr(self.session, "workspace", "") or ""
        m.add_command(label=ws or "no workspace", state="disabled")
        m.add_separator()
        m.add_command(label="Workbench setup", command=self._open_setup)
        m.add_command(label="mic, CLI, where it pastes", state="disabled")
        m.add_separator()
        self._design_menu(m)

    def _design_menu(self, parent) -> None:
        """Which surface the *next* launch draws, switchable from this one.

        The shipped design's `_design_menu` (flow/ui.py:3073) in this surface's
        idiom, and deliberately the same shape: the same names, the same
        `(current)` marker, and the same promise about when it takes effect. A
        design's whole window tree is built in its constructor — `__main__`
        picks the class before the first frame — so the only honest thing a
        press can do is write the name and say that it lands next time.

        Where the shipped one notes into its bubble, this one prints: a
        wordless pill has nowhere to put a sentence, and this sentence has to
        be read or the switch reads as a press that did nothing.

        **Built once, refreshed after.** `_on_menu` rebuilds the whole menu on
        every open, because the mode check and the workspace path are the
        values of now — and `delete(0, "end")` removes the *cascade entry*
        while the submenu behind it is a window of its own that goes on
        existing, unreferenced and undestroyed. A fresh `_dark_menu` per
        right-click was therefore one leaked `tk.Menu` per right-click, on the
        one surface in this app that is never closed. The rows are the part
        that changes — the `(current)` marker moves — and refreshing them is
        all that ever needed to happen.
        """
        sub = self._design_sub
        if sub is None:
            sub = self._design_sub = _dark_menu(parent)
        else:
            sub.delete(0, "end")
        profile = getattr(self.session, "profile", None)
        here = getattr(profile, "design", DESIGN_DEFAULT)
        for name in DESIGNS:
            sub.add_command(
                label=name.capitalize() + ("   (current)" if name == here
                                           else ""),
                command=lambda n=name: self._choose_design(n),
            )
        parent.add_cascade(label="Design", menu=sub)

    def _choose_design(self, name: str) -> None:
        """Store `name` as the design and say when it takes effect."""
        profile = getattr(self.session, "profile", None)
        if profile is None:
            # `--no-profile`. The choice has nowhere to live past this process
            # and a design switch exists only at launch, so there is nothing
            # even a session-local apply could mean. Said, not swallowed.
            print("flow: design not saved - launched with --no-profile",
                  flush=True)
            return
        profile.design = name
        # A setting somebody chooses once, so a save that failed has to be
        # visible now rather than at the next launch that ignores it.
        if profile.save():
            print(f"flow: design: {name} - launches next time", flush=True)
        else:
            self._flash = FLASH_FRAMES
            print(f"flow: could not save {profile.path}", flush=True)

    def _on_menu(self, e=None) -> None:
        """Right-click — the only menu the design allows (Workspace.dc.html).

        Borrows the foreground for the popup's lifetime, the trick `Pill._menu`
        documents at flow/ui.py:2909-2923: a Tk popup is a native
        `TrackPopupMenu` whose modal loop only receives input while its owner is
        the foreground window, and `WS_EX_NOACTIVATE` means the click never made
        us that. Guarded on `no_activate` — where the style cannot take (Lite,
        Mac) the window is in the activation chain already, and a borrow would
        be a Win32 call with nothing behind it. `_user32` is ui.py's `_NoHands`
        there, so the guard is about clarity, not safety.
        """
        if self._menu is None or e is None:
            return
        # Rebuilt rather than refreshed: the mode check and the workspace
        # line are the values of now, not of when the menu was first made.
        self._menu.delete(0, "end")
        self._populate_menu(self._menu)
        previous = foreground_hwnd() if self.no_activate else 0
        if self.no_activate:
            _user32.SetForegroundWindow(toplevel_hwnd(self))
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()  # the documented idiom; cheap insurance
            if previous:
                _user32.SetForegroundWindow(previous)

    # -- the tray ------------------------------------------------------------

    def _start_tray(self) -> bool:
        """Put the icon in the notification area. True once it is there.

        Raised at launch rather than on demand, and that is what pays for
        trimming the pill's menu back to the canvas (`_populate_menu`): the
        artboard's menu ends at Workbench setup, so Show and Quit have to
        live somewhere that does not depend on a menu row — the icon's own
        `Show Flow` / `Quit Flow` (tray.py:308-309). It is also the escape
        hatch the 2026-09-03 decision kept the tray for: a pill dragged
        somewhere unreachable is now genuinely reachable, which it was not
        while the way back was a row on the window you had lost.

        Idempotent, and false on a machine with no notification area (a Mac,
        a Linux desktop) — where `quit` is the hotkey, as it has always been.
        """
        if not tray.available():
            return False
        if self._tray is None:
            self._tray = tray.Tray("Flow - press the chord to talk",
                                   self._tray_events)
        return self._tray.start()

    def hide_to_tray(self) -> bool:
        """Park the window behind a notification-area icon. True when it hid.

        ui.py:4038-4051's one act, compact-sized, and kept against the
        canvas's "no tray menu" (decided 2026-09-03 — the tray is the escape
        hatch if the pill is ever dragged somewhere unreachable;
        design/compact/README.md). The icon comes first and hiding is
        conditional on it: a withdrawn window with nothing in the
        notification area is a Flow only Task Manager can reach — invariant
        4, hidden must not mean gone. `withdraw` rather than `park`: the
        shipped shell re-asserts its geometry every frame and would drag a
        parked window straight back, and this one re-asserts only on a
        panel transition, so unmapping is safe here.
        """
        if not self._start_tray():
            self._flash = FLASH_FRAMES
            return False
        # The tracked anchor, not `winfo_*`: this is the position the window
        # was last *given*, and `winfo_rootx` lags a `geometry` call by a
        # frame or two — so a hide within a frame of a panel closing recorded
        # the position before last and put the pill back there.
        self._home = self._shell_xy
        self._hidden = True
        self.withdraw()
        return True

    def show_from_tray(self) -> None:
        """Bring the window back where the user left it. The icon stays:
        somebody who hid Flow once will hide it again.

        The anchor goes back with it. `_shell_xy` is what `_sync_shell` grows
        the band from and what `_outside_click_now` hit-tests against, and a
        pill returned to `_home` while those still described somewhere else is
        a pill whose next panel opens off its own capsule.
        """
        if not self._hidden:
            return
        self._hidden = False
        if self._home is not None:
            x, y = self._home
            self.geometry(f"+{x}+{y}")
            self._shell_xy = (x, y)
            self._capsule_y = y + self.dev(self._capsule_off)
        self.deiconify()
        self.lift()
        # A layered window that has just been mapped again has nothing on it:
        # the bitmap presented before the withdraw is not the window's to keep,
        # and the key is unchanged by hiding — so the next frame would skip the
        # draw and the pill would come back invisible. `_open_box` learned the
        # same thing on `<Map>`; this is the one place the key cannot see.
        self._drawn_key = None

    def _drain_tray(self) -> None:
        """What the icon decided, acted on from Tk's own thread — the only
        place Tk is touched, which is the rule tray.py's whole threading
        argument exists for."""
        if self._tray is None:
            return
        while True:
            try:
                event = self._tray_events.get_nowait()
            except queue.Empty:
                return
            if event == tray.SHOW:
                self.show_from_tray()
            elif event == tray.QUIT:
                self.quit_app()
                return

    # -- the standalone box --------------------------------------------------

    def _workspace_recents(self) -> list:
        """The folders Flow has been pointed at, most recent first — the
        profile's own record, which `session.set_workspace` already writes."""
        profile = getattr(self.session, "profile", None)
        return list(getattr(profile, "workspaces", ()) or ())

    def _open_palette(self) -> None:
        """Switch workspace, from the menu: the search palette in
        Workspace.dc.html over the folders the profile has recorded."""
        self._palette = _Palette(self._workspace_recents())
        self._open_box("palette")

    def _open_setup(self) -> None:
        """Workbench setup, from the menu: three read-only lines with the
        values Flow already found."""
        self._palette = None
        self._open_box("setup")

    def _box_height(self) -> int:
        if self._box_kind == "palette" and self._palette is not None:
            return (PALETTE_FIELD_H
                    + PALETTE_ROW_H * len(self._palette.rows())
                    + PALETTE_FOOT_H)
        return SETUP_ROW_H * 3 + 2

    def _open_box(self, kind: str) -> None:
        """Raise the standalone 360 px box (Workspace.dc.html's `.box`) above
        the pill, which itself never hides and never moves.

        One at a time — palette or setup, not both. The box *takes* the
        keyboard, the one window this surface activates on purpose: the
        palette is a type-ahead, and a type-ahead nobody can type into is a
        picture of one. It gives the focus back the way it came — Esc,
        Enter, or a click anywhere else (`FocusOut`, which a no-activate
        window could never offer, is exactly what taking focus buys).
        """
        # Replace, not close: the caller has already set the new box's state
        # (`_palette`), which `_close_box` would wipe along with the old
        # window. One at a time still holds.
        if self._box is not None:
            self._box.destroy()
            self._box = None
            self._box_canvas = None
            if self._box_paint is not None:
                close = getattr(self._box_paint, "close", None)
                if close is not None:
                    close()
                self._box_paint = None
        self._box_kind = kind
        box = tk.Toplevel(self)
        bg = _shell_window(box, self.lite, PILL_ALPHA)
        box.configure(bg=bg)
        self._box = box
        self._box_canvas = tk.Canvas(box, bg=bg, highlightthickness=0, bd=0)
        self._box_canvas.pack(fill="both", expand=True)
        h = self._box_height()
        self._box_paint = paint.painter_for(self._box_canvas, BOX_W, h,
                                            self.lite, PILL_ALPHA, self.k)
        if getattr(self._box_paint, "antialiased", False):
            _unkey(box)
        # Tracked, not read back — and this line said so while reading
        # `winfo_rootx()` two lines above it. `winfo_*` lags the window
        # manager by a frame or two after a `geometry` call, and `_sync_box`
        # re-anchoring off a stale read parked the box above the screen's top
        # edge; `.shots/12-compact-palette.png` was a picture of the backdrop.
        # `_shell_xy` is the anchor the window was actually placed at.
        x, y = self._shell_xy
        # A 360 px box at a 120 px pill's x runs off the right of the display
        # whenever the pill is parked near that edge — the same clamp the band
        # gets in `_sync_shell`, for the same reason: the box is the only
        # thing on screen with the answer on it. The top is the work area's,
        # not zero, because a monitor above the primary has a negative one.
        left, top, right, _bottom = self.work
        x = max(left, min(x, right - self.dev(BOX_W)))
        self._box_x = x
        self._box_foot = max(top, y - self.dev(h + 8)) + self.dev(h)
        box.geometry(f"{self.dev(BOX_W)}x{self.dev(h)}"
                     f"+{x}+{self._box_foot - self.dev(h)}")
        box.bind("<Key>", self._on_box_key)
        box.bind("<ButtonPress-1>", self._on_box_click)
        box.bind("<FocusOut>", lambda _e: self._close_box())
        # Redrawn when Windows puts it on screen, and not only now. A layered
        # window's content does not survive its own mapping: the frame
        # presented before the map is discarded, and a box that is only ever
        # drawn at open and on a keystroke then has nothing on it at all —
        # which is what an empty `.shots/12-compact-palette.png` was a picture
        # of, with `present` returning True the whole time.
        box.bind("<Map>", lambda _e: self._draw_box())
        box.focus_force()
        box.update_idletasks()
        self._draw_box()

    def _close_box(self) -> None:
        """Idempotent, like every close on this surface: Esc, Enter, a click
        away and a second menu choice can all mean the same close."""
        self._palette = None
        if self._box is not None:
            self._box.destroy()
            self._box = None
            self._box_canvas = None
            self._box_kind = ""
        if self._box_paint is not None:
            close = getattr(self._box_paint, "close", None)
            if close is not None:
                close()
            self._box_paint = None

    def _sync_box(self) -> None:
        """Re-height and redraw the box after a keystroke changed its rows.
        Bottom-anchored, like the panel: the box grows upward, off the anchor
        `_open_box` recorded — see there for why not `winfo_*`.

        It inherits that anchor's clamps rather than repeating them, and can,
        because a palette is at its tallest the moment it opens: the query is
        empty, so every workspace is a row, and typing only ever narrows. A
        foot placed to keep *that* height inside the work area keeps every
        shorter one inside it too.
        """
        if self._box is None:
            return
        h = self._box_height()
        self._box.geometry(
            f"{self.dev(BOX_W)}x{self.dev(h)}"
            f"+{self._box_x}+{self._box_foot - self.dev(h)}")
        resize = getattr(self._box_paint, "resize", None)
        if resize is not None:
            resize(BOX_W, h)
        self._draw_box()

    def _on_box_key(self, e) -> None:
        """The palette's keyboard: letters build the query, Backspace edits,
        Enter sets the top hit, Esc leaves it — the footer's own legend."""
        if e.keysym == "Escape":
            self._close_box()
            return
        if self._box_kind != "palette" or self._palette is None:
            return
        if e.keysym == "BackSpace":
            self._palette.backspace()
        elif e.keysym == "Return":
            self.session.set_workspace(self._palette.choose())
            self._close_box()
            return
        elif e.char and e.char.isprintable():
            self._palette.type(e.char)
        else:
            return
        self._sync_box()

    def _on_box_click(self, e) -> None:
        """A row tap is the same choice as Enter on it. Read-only boxes
        (setup) swallow the click and stay.

        The event's y is a device length and the row heights are design ones,
        so it is converted first — `_on_press` and `_panel_click` already do
        the same, and this was the one hit test left comparing across units.
        At 300 % that divided the click's y by nothing and the rows by three:
        every tap below the first row chose a workspace three rows above the
        one under the pointer, which for a "switch workspace" palette is the
        gesture picking somebody else's answer.
        """
        if self._box_kind != "palette" or self._palette is None:
            return
        i = int((self.design(e.y) - PALETTE_FIELD_H) // PALETTE_ROW_H)
        if 0 <= i < len(self._palette.rows()):
            self.session.set_workspace(self._palette.choose(i))
            self._close_box()

    def _draw_box(self) -> None:
        if self._box_paint is None:
            return
        c = self._box_paint
        c.delete("all")
        if self._box_kind == "palette":
            self._draw_palette(c)
        else:
            self._draw_setup(c)
        present = getattr(c, "present", None)
        if self._box is not None and present is not None:
            # Told where, not asked: the box has just been given its geometry
            # and `winfo_*` has not caught up, which composited the first
            # frame off screen and photographed as an empty backdrop.
            present(self._box,
                    at=(self._box_x,
                        self._box_foot - self.dev(self._box_height())))

    # -- the panel -----------------------------------------------------------

    def _spec(self) -> dict:
        """The panel spec for the mode the panel was raised for (`PANEL_SPEC`).

        Keyed on `_panel_mode` rather than `session.mode`: a mode switch
        closes the band, but a reply that reopens it lands after the switch,
        and the answer still draws as the Ask it is.
        """
        return PANEL_SPEC.get(self._panel_mode, PANEL_SPEC[CONVERSE])

    def _open_panel(self) -> None:
        """Raise the band above the foot. Idempotent — a reply that reopens a
        closed panel and a fresh hold that reuses an open one both land here.

        Only the flag and the geometry: the text blocks are their own state,
        cleared by the hold that starts fresh (`_talk_start`) and filled by
        the events that have something to say (`_pump_events`).
        """
        self._panel_open = True
        self._sync_shell()

    def _close_panel(self) -> None:
        """Back to 120 wide. Idempotent, for the same reason `quit_app` is:
        Esc, a click outside, a mode switch and Send can all mean the same
        close, and nothing upstream can tell which one ran.
        """
        if not self._panel_open:
            return
        self._panel_open = False
        self._ask_pending = False
        self._sync_shell()

    def _sync_shell(self) -> None:
        """Resize the one window around the capsule: 120×34 alone, 400×(200+34)
        with the band, 18 px taller while Lite's copied notice is showing.

        The capsule's screen position is the anchor — "the pill never hides
        and never moves" (README) — tracked in `_capsule_off` rather than read
        back off `winfo_*`, which lags the window manager. The band grows
        upward from it, the notice strip downward, and the result is clamped
        into the monitor's work area on all four edges: the band goes left
        rather than off the right (the mic moves before the panel clips), and
        it stops at the work area's top and bottom rather than at the
        taskbar's face.
        """
        panel_h = PANEL_H if self._panel_open else 0
        notice_h = NOTICE_H if self._notice else 0
        w = PANEL_W if self._panel_open else PILL_W
        if self._notice:
            # The capsule keeps its own 120 px — `_draw` still draws it at
            # `PILL_W` — and the window grows around it so the strip beneath
            # has room for its sentence.
            w = max(w, self._notice_w)
        h = PILL_H + panel_h + notice_h
        if (w, h) == (self._shell_w, self._shell_h):
            return
        # Screen arithmetic is in device pixels — `geometry`, `GetCursorPos`
        # and the monitor rectangles all speak them — so design lengths are
        # converted before they meet it, never after.
        # Off the tracked anchor, never off `winfo_*`: the capsule's top edge
        # is the fixed point of this whole surface — "the pill never hides and
        # never moves" (README) — and the band grows upward from it while the
        # notice grows downward.
        #
        # **Against `self.work`, and this used to be `winfo_screenwidth()`.**
        # On Windows that call reports the *primary* monitor's width, while
        # the pill is placed on the monitor under the pointer, whose rectangle
        # is in virtual-screen coordinates — so on any right-hand monitor
        # `x + w` was trivially greater than it, and opening the panel threw
        # the whole window back onto the primary display. The same read gave
        # the top edge a floor of 0, which is somebody else's monitor when the
        # one in use is above the primary and its `top` is negative.
        left, top, right, bottom = self.work
        dw, dh = self.dev(w), self.dev(h)
        x = max(left, min(self._shell_xy[0], right - dw))
        # The notice strip grows *downward* from a capsule already standing
        # PANEL_BOTTOM_OFFSET above the taskbar, so it is the one thing here
        # that can leave the bottom of the work area — and it did, running
        # under the taskbar with its sentence half-covered. Shifted up by the
        # overflow instead: a capsule that moved a few pixels is a smaller lie
        # than a message nobody can read at all.
        y = max(top, min(self._capsule_y - self.dev(panel_h), bottom - dh))
        self._shell_w, self._shell_h = w, h
        self._capsule_off = panel_h
        self._shell_xy = (x, y)
        # Where the capsule actually ended up, which is only where it was when
        # no clamp bit. The anchor has to be re-derived rather than kept, or
        # the next sync grows its band from a capsule that is no longer there
        # and walks the window off the edge the clamp just pulled it back from.
        self._capsule_y = y + self.dev(panel_h)
        self.geometry(f"{dw}x{dh}+{x}+{y}")
        resize = getattr(self.paint, "resize", None)
        if resize is not None:
            resize(w, h)

    def _panel_click(self, e) -> None:
        """A press in the band: the only live things there are the strip's
        close, the footer's Copy, and Send when the mode has one."""
        x, y = self.design(e.x), self.design(e.y)
        if _hit(CLOSE_RECT, x, y):
            self._close_panel()
        elif _hit(COPY_RECT, x, y):
            self._copy_result()
        elif self._spec()["send"] and _hit(SEND_RECT, x, y):
            self._panel_send()

    def _panel_text(self) -> str:
        """What Copy copies and Refine's Send pastes: the result, unless the
        CLI failed — then the raw dictation, because unrefined text beats no
        text (States.dc.html)."""
        if self._panel_failed:
            return self._panel_heard
        return self._panel_result or self._panel_heard

    def _copy_result(self) -> None:
        """The Copy chip: the answer, or the question if that is all there is.

        "Copy leaves the panel up" (Refine.dc.html) — it changes nothing but
        the clipboard. The borrow is ui.py's one clipboard transaction, shared
        rather than copied.
        """
        text = self._panel_text()
        if not text:
            return
        if _copy_to_clipboard(self, text):
            self._flash = FLASH_FRAMES

    def _panel_send(self) -> None:
        """The footer Send: paste the result into `paste_target`, and close.

        The mechanism is Refine's flow — paste the refined text where the user
        was, through the same `on_send` contract item 1 pasted drafts through,
        target included, and the Lite clipboard when there is no handler.
        `_panel_text` is what "Send still works" means on a failed refine:
        the raw dictation goes, because unrefined text beats no text. Ask's
        footer has no Send (Ask.dc.html), and Type never opens the panel.
        """
        text = self._panel_text()
        if text:
            self._deliver(text)
        self._close_panel()

    def _outside_click_now(self) -> bool:
        """One frame's answer to "did the user just click somewhere that is
        not this window". Polled only while the panel is open.

        A NOACTIVATE window is never told it lost focus — it never had it —
        so click-outside is a poll, not an event: the left button's up→down
        edge with the cursor outside our rect. Two read-only Win32 calls a
        frame, and Lite does not ask — no target awareness there, and
        `_user32` is `_NoHands`.

        **Every length here is a device length.** `GetCursorPos` answers in
        device pixels and so does the tracked anchor, but `_shell_w` and
        `_shell_h` are the *design* sizes this module writes everything in —
        so the rect being tested was the window scaled down by `k`. At 300 %
        that is a third of the real window, and a click in the right or lower
        two-thirds of an open panel read as a click outside it and closed the
        panel under the pointer. `_shell_xy` rather than `winfo_rootx`, for
        the reason `_shell_xy` exists: `winfo_*` lags a `geometry` call, and
        this runs every frame.
        """
        if self.lite:
            return False
        down = bool(_user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
        was, self._outside_was_down = self._outside_was_down, down
        if not down or was:
            return False
        pt = _POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        x, y = self._shell_xy
        return not (x <= pt.x < x + self.dev(self._shell_w)
                    and y <= pt.y < y + self.dev(self._shell_h))

    # -- the drawing ---------------------------------------------------------

    def _ring_colour(self) -> str:
        """This frame's ring, or "" for none at rest.

        The flash outranks the state, because an error is true regardless of
        which state raised it — the same layering ui.py's `accent` gives. The
        two fallbacks that are not session states come next (States.dc.html):
        the mic's persistent red, then the launch notice's one amber. A
        disarmed pill is at rest whatever the session thinks: capture is off,
        and a ring would claim otherwise.
        """
        if self._flash:
            return ERROR
        if self._mic_gone:
            return ERROR
        if self._recover:
            return RECOVER
        loading = bool(getattr(self.session.asr, "loading", False))
        if self.armed:
            state = RING.get(self.session.state, "")
            if state:
                return state
            if self.session.capturing:
                # Open and hearing a silent room. `LISTENING` means speech was
                # *detected*, so without this the pill looked identical
                # whether it was holding the microphone open or doing nothing
                # at all — which is what made a muted mic impossible to tell
                # from a dead application.
                #
                # **Above `loading`, and that ordering is the whole point.**
                # The models take about eighteen seconds to come off disk
                # here, which is exactly the window somebody spends finding
                # out whether the thing works — and with loading on top, every
                # hold in that window answered "loading" to the question "is
                # my microphone on". Both facts are true; this is the one
                # being asked.
                return HEARING
        if loading:
            # The models, coming off disk. `session.activity` already calls
            # this "loading the model" for the shipped surface; this is the
            # same fact in the only vocabulary this one has, and it is the
            # answer to "why did my first hold do nothing".
            return WAITING
        # A disarmed pill is at rest whatever the session thinks: capture is
        # off, and a ring would claim otherwise.
        return ""

    def _glyph_tint(self) -> str:
        """This frame's mic tint: the mode's hue — or red, while the mic is
        the thing that is wrong (gen.py's `mic(mode if not slash else state)`)."""
        if self._mic_gone:
            return ERROR
        return MODE_TINT.get(self.session.mode, TEXT)

    def _draw_key(self) -> tuple:
        """Everything `_draw` and its helpers read, as one comparable value.

        The frame repainted whether or not anything had moved: `delete("all")`,
        every item back, and a whole bitmap through `UpdateLayeredWindow`,
        thirty times a second for as long as Flow is open. Measured here at
        300 % — 0.78 ms a frame with the pill alone and **4.53 ms with the
        panel open**, 15 % of the 30 ms budget, all of it spent drawing the
        same picture as last time. `Pill._draw_key` (flow/ui.py:4973) is the
        shipped surface's answer to exactly this, and decisions.md's
        "composited, not painted" says the choice reopens if compositing's
        frame cost ever shows up. It showed up.

        Built from the same reads the drawing makes, under the same guards, so
        a fixture that can be drawn can be keyed:

          `_ring_colour` folds the flash, the mic, the recover countdown, the
          session state, `capturing` and `asr.loading` into one colour — which
          is all the ring is; `_glyph_tint` folds `_mic_gone` and the mode into
          the other. `_flash` and `_recover` ride along as booleans anyway,
          because they are countdowns and the frame they reach zero on is a
          frame that changes.

          `_draw_face` reads the level, rounded to the thousandth here — a
          thousandth of `BAR_MAX_HALF` is seven thousandths of a pixel of bar.

          `_draw_panel` reads `_panel_mode` (through `_spec`), the session's
          `workspace`, both heard fields, the result and `_panel_failed`;
          `_draw_notice` reads `_notice_text` and the two shell dimensions.

        The shell size is in here for a second reason: it is also how a
        resize invalidates itself. `_sync_shell` only ever reaches the painter
        after `(w, h)` has changed, and it recreates the bitmap when it does —
        so the frame after a resize is a frame whose key has already moved,
        and no second mechanism is needed to force the redraw. A remapped
        window is the case the key *cannot* see, and `show_from_tray` clears
        it by hand for the reason `_open_box` binds `<Map>`.
        """
        session = self.session
        return (
            self._ring_colour(), self._glyph_tint(),
            round(self._meter_level, 3), self._mic_gone,
            bool(self._flash), bool(self._recover),
            self._panel_open, self._panel_mode,
            self._panel_heard, self._panel_heard_final,
            self._panel_result, self._panel_failed,
            bool(self._notice), self._notice_text, self._notice_w,
            self._shell_w, self._shell_h,
            # The two the drawing reads off the session directly: the strip
            # prints the workspace, and the mode is what `_glyph_tint` has
            # already folded in — kept separate because a mode with no tint of
            # its own would otherwise be a mode change nothing could see.
            getattr(session, "workspace", "") or "",
            getattr(session, "mode", DICTATE),
        )

    def _draw(self) -> None:
        """Draw the whole window onto `self.canvas`. Pure: state in, shapes out.

        Tested headless against a recording fake, exactly as `Pill._draw` is —
        which is why every attribute this reads that a fixture does not set is
        a class-level default above.
        """
        c = self.paint
        c.delete("all")
        if self._panel_open:
            self._draw_panel(c)
            self._draw_foot(c)
            if self._notice:
                self._draw_notice(c)
            self._present()
            return
        # The capsule body first, and it is load-bearing rather than cosmetic:
        # `_shell_window` keyed the canvas background out with
        # `-transparentcolor`, and on Windows a keyed pixel is a *click-through*
        # pixel — an unfilled pill is invisible against the desktop and lets the
        # press fall to whatever is behind it, which is exactly what the first
        # photographed run did to the right-click that was meant to open the
        # menu. A true stadium, as Main.dc.html's `.pill` has it — see
        # `_capsule` for why not `_round_rect`.
        _capsule(c, 0, 0, PILL_W, PILL_H, fill=SHELL, outline="")
        # The chrome, gen.py's `.pill`: a 1 px `RING_OUTER` border and an inset
        # `RING_TOP` highlight, plus the state ring one pixel further out when
        # there is one (`box-shadow: 0 0 0 1px <state>` — 1 px, not 2). The
        # window is exactly the capsule, so "further out" does not exist and
        # the stack shifts in instead: the ring takes the outermost pixel, the
        # border steps one in, the highlight one more. `_panel_chrome`
        # (flow/ui.py:2269) is the same idea for the shipped surface — three
        # opaque hairlines instead of a shadow no keyed window could composite.
        ring = self._ring_colour()
        inset = 0
        if ring:
            _capsule_ring(c, 0, 0, PILL_W, PILL_H, ring)
            inset = 1
        _capsule_ring(c, inset, inset, PILL_W - inset, PILL_H - inset, RING_OUTER)
        hi = inset + 1
        # `inset 0 1px 0 RING_TOP` is a *straight* line along the top, the way
        # `_panel_chrome` draws its own (flow/ui.py:2301) — not a curve. This
        # was an arc over the full 120×32 bbox, which is an ellipse the width
        # of the pill: it photographed as a bulge sweeping across the capsule
        # and reading as the shape's own edge. It spans the flat run between
        # the two end-cap centres, because that is the only part of a stadium
        # a horizontal inset line can sit on.
        c.create_line(hi + PILL_H // 2, hi, PILL_W - hi - PILL_H // 2, hi,
                      fill=RING_TOP)
        self._draw_face(c, 0, BARS)
        if self._notice:
            self._draw_notice(c)
        self._present()

    def _present(self) -> None:
        """Hand the finished frame to the desktop, where there is one to hand.

        A no-op on the real canvas — Tk has already painted it — and the whole
        of the layered path everywhere else: nothing `_draw` drew is visible
        until this runs, which is also why this surface cannot flicker. The
        frame is composited whole rather than assembled in front of the user.
        """
        present = getattr(self.paint, "present", None)
        if present is None:
            return
        try:
            present(self)
        except tk.TclError:
            # "application has been destroyed". `quit_app` destroys the window
            # while a frame that began before it is still running, and this is
            # the first line of that frame to ask Tk for anything — so the
            # whole traceback lands on the console of somebody who has just
            # pressed quit and thinks they broke something. Nothing is wrong:
            # there is no window left to composite onto.
            self._alive = False

    def _say(self, text: str, frames: int = COPIED_FRAMES) -> None:
        """Put one sentence under the pill for `frames` frames.

        The wordless pill's only words, and it has them for the same reason
        Lite's "copied" line has them: there are a handful of facts that no
        colour can carry, and a surface that cannot say them leaves somebody
        holding a button that does nothing with no way to find out why.
        """
        self._notice_text = text
        self._notice = frames
        self._notice_w = self._text_width(text, FONT_TAG) + 2 * NOTICE_PAD
        self._sync_shell()

    def _text_width(self, text: str, spec) -> int:
        """How wide `text` is in `spec`, through whatever is drawing.

        Through the painter, because GDI+ and Tk do not agree on metrics and
        the one that will lay the glyphs down is the one worth asking. Falls
        back to a nominal advance where neither can answer — a bare fixture,
        which has no window to size anyway.
        """
        measure = getattr(self.paint, "measure", None)
        if measure is not None:
            try:
                return int(measure(text, spec)[0])
            except Exception:
                pass
        return int(len(text) * abs(spec[1]) * 0.55)

    def _draw_notice(self, c) -> None:
        """Lite's last inch, said once and never in an error colour
        (States.dc.html): the words are on the clipboard and the last step is
        the user's. The strip has a body, not just floating glyphs: Tk
        anti-aliases text against the canvas behind it, and on the keyed-out
        region that background is the magenta the window is keyed by — text
        drawn without one photographed as the key colour itself
        (`.shots/19-compact-copied.png` before this strip had a fill)."""
        y = self._shell_h - NOTICE_H
        w = self._shell_w
        _capsule(c, 0, y, w, self._shell_h, square_top=True,
                 fill=SHELL, outline="")
        _capsule_ring(c, 0, y, w, self._shell_h, RING_OUTER,
                      square_top=True, top=False)
        c.create_text(w // 2, y + NOTICE_H // 2, text=self._notice_text,
                      font=FONT_TAG, fill=DIM)

    def _draw_foot(self, c) -> None:
        """The pill as the panel's foot: the same face, 400 wide, squared on
        the join.

        gen.py's `.foot`: `border-radius: 0 0 17px 17px`, `border-top: 0`, no
        inset highlight — the seam above is the panel's to draw, and the light
        source would read as a second line under it. The state ring is the
        exception to `border-top: 0`: it is a `box-shadow`, and a box-shadow
        wraps all four sides. The ring is the foot's, not the window's — the
        panel band above keeps its own neutral border.
        """
        y0 = PANEL_H
        _capsule(c, 0, y0, PANEL_W, y0 + PILL_H, square_top=True,
                 fill=SHELL, outline="")
        ring = self._ring_colour()
        inset = 0
        if ring:
            _capsule_ring(c, 0, y0, PANEL_W, y0 + PILL_H, ring,
                          square_top=True, top=True)
            inset = 1
        _capsule_ring(c, inset, y0 + inset, PANEL_W - inset,
                      y0 + PILL_H - inset, RING_OUTER,
                      square_top=True, top=False)
        self._draw_face(c, y0, BARS_FOOT)

    def _draw_face(self, c, y0: int, bars: int) -> None:
        """The mic and the meter, shared by the capsule (y0=0, 15 bars) and
        the foot (y0=PANEL_H, 40): one face, two window sizes."""
        tint = self._glyph_tint()
        # The mic, stroked not filled — gen.py's `mic()`: a rounded-rect
        # capsule, an arc cradle, a stem, in a 14×18 viewBox with round caps.
        # The coordinates are the viewBox's, offset by its frame in the window.
        x, y = MIC_X, y0 + MIC_Y
        _round_rect(c, x + 4.3, y + 1.2, x + 9.7, y + 10.8, 2.7,
                    fill="", outline=tint, width=MIC_STROKE)
        c.create_arc(x + 1.8, y + 3.2, x + 12.2, y + 13.6,
                     start=180, extent=180, style=tk.ARC,
                     outline=tint, width=MIC_STROKE)
        c.create_line(x + 7, y + 13.6, x + 7, y + 16.4,
                      fill=tint, width=MIC_STROKE, capstyle=tk.ROUND)
        if self._mic_gone:
            # The slashed variant (States.dc.html, gen.py's `mic(slash=True)`):
            # one diagonal across the glyph — "the one gesture the pill
            # refuses outright", in the same red the ring wears.
            c.create_line(x + 1.6, y + 1.8, x + 12.4, y + 16.4,
                          fill=tint, width=MIC_STROKE, capstyle=tk.ROUND)
        # The meter (R13's live level, restated wordless): 2 px bars on a 2 px
        # gap, 3 px at rest, blooming around the centre line so quiet reads as
        # a flat line rather than an empty box. Rest is gen.py's `DIM` — grey
        # claims no state — the mode's tint is earned by an actual level.
        mid = y0 + PILL_H // 2
        lvl = self._meter_level
        shade = tint if lvl > 0.04 else DIM
        centre = (bars - 1) / 2
        for i in range(bars):
            envelope = 1.0 - 0.6 * abs(i - centre) / centre
            h = 1.5 + lvl * BAR_MAX_HALF * envelope
            x = METER_X + i * (BAR_W + BAR_GAP)
            # gen.py's `.meter i` carries `border-radius: 1px`, so the caps
            # are round — the same call ui.py:5060 makes for its own bars, and
            # squared off below the cap's own diameter for its reason: a
            # smoothed polygon pinches into a lozenge there.
            if h * 2 > BAR_W:
                _round_rect(c, x, mid - h, x + BAR_W, mid + h, BAR_W / 2,
                            fill=shade, outline="")
            else:
                c.create_rectangle(x, mid - h, x + BAR_W, mid + h,
                                   fill=shade, outline="")

    def _draw_panel(self, c) -> None:
        """The 400 px band above the foot: strip, heard, result, footer.

        gen.py's `.shell`: SHELL fill, a 1 px `RING_OUTER` border on the
        rounded top corners (18 px) and the sides, and a `SEAM`-coloured
        bottom border that is the one line between panel and foot — the join
        reads as an internal divider, not two windows touching
        (flow/ui.py:4985-5000's `seam="top"`, adapted to the capsule). Text is
        `create_text` with ui.py's own font tuples, wrapped to a line budget
        by `_fit` rather than by Tk — the band is fixed-height where the
        artboards grow, and that is the residual delta.
        """
        spec = self._spec()
        # The band, then the seam, then the strip — the foot's fill, drawn
        # after this, covers the border's bottom stroke, which is why the
        # seam is a line of its own rather than the border's fourth side.
        _round_rect(c, 0, 0, PANEL_W - 1, PANEL_H, (18, 18, 0, 0),
                    fill=SHELL, outline=RING_OUTER)
        c.create_line(0, PANEL_H - 1, PANEL_W, PANEL_H - 1, fill=SEAM)
        _round_rect(c, 1, 1, PANEL_W - 2, STRIP_H, (16, 16, 0, 0),
                    fill=STRIP, outline="")
        c.create_line(0, STRIP_H, PANEL_W, STRIP_H, fill=SEAM)
        # The workspace strip: folder, path, note, close (gen.py `strip()`).
        # The workspace is the CLI's system role (README) — this line is where
        # the panel says which repo it is about to be about.
        ws = getattr(self.session, "workspace", "") or ""
        self._draw_folder(c, PAD_X, STRIP_H // 2, HEARING if ws else DIM)
        c.create_text(PAD_X + 20, STRIP_H // 2, anchor="w",
                      text=ws or "no workspace", font=FONT_TAG,
                      fill=CODE if ws else PLACEHOLDER)
        c.create_text(CLOSE_RECT[0] - 10, STRIP_H // 2, anchor="e",
                      text="grounded" if ws else "plain talk",
                      font=FONT_TAG, fill=DIM)
        cx, cy = (CLOSE_RECT[0] + CLOSE_RECT[2]) // 2, STRIP_H // 2
        c.create_line(cx - 4, cy - 4, cx + 4, cy + 4, fill=DIM, width=1)
        c.create_line(cx - 4, cy + 4, cx + 4, cy - 4, fill=DIM, width=1)
        # The heard block: the question, live. Partials draw italic until the
        # release's draft makes them final — the same honesty FONT_PARTIAL
        # gives the shipped bubble.
        y = HEARD_TAG_Y
        lines = 3
        if spec["heard_tag"] is not None:
            c.create_text(PAD_X, y, anchor="w", text=spec["heard_tag"],
                          font=FONT_TAG, fill=DIM)
            y = HEARD_Y
            lines = HEARD_LINES
        heard = _fit(self._panel_heard, LINE_CHARS, lines)
        if heard:
            c.create_text(PAD_X, y, anchor="nw", text=heard,
                          font=FONT_BODY if self._panel_heard_final
                          else FONT_PARTIAL,
                          fill=spec["heard_fill"])
        # The result block: the answer, on its accent bar (Ask.dc.html's
        # card) or under its tag (Refine.dc.html). Nothing at all while the
        # CLI is still working — the foot's blue ring is already saying that.
        result = _fit(self._panel_result, LINE_CHARS, RESULT_LINES)
        if result:
            accent = spec["result_accent"]
            if spec["result_tag"] is not None and not self._panel_failed:
                # Refine.dc.html: the tag carries the hue, the text is plain.
                # Suppressed on a failure — "refined for this repo" over the
                # CLI's last line would claim a refinement that did not happen.
                c.create_text(PAD_X, RESULT_Y, anchor="w",
                              text=spec["result_tag"], font=FONT_TAG,
                              fill=accent)
                c.create_text(PAD_X, RESULT_Y + 16, anchor="nw", text=result,
                              font=FONT_BODY, fill=TEXT)
            elif spec["result_tag"] is not None:
                c.create_text(PAD_X, RESULT_Y, anchor="nw", text=result,
                              font=FONT_BODY, fill=TEXT)
            else:
                # Ask.dc.html's card: a violet left bar, no tag.
                if accent:
                    c.create_rectangle(PAD_X, RESULT_Y, PAD_X + 2,
                                       RESULT_Y + 44, fill=accent, outline="")
                c.create_text(PAD_X + 12, RESULT_Y, anchor="nw", text=result,
                              font=FONT_BODY, fill=TEXT)
        # The footer: Copy, the hold hint, and Send in the modes that have one
        # (Refine.dc.html; Ask's footer stops at the hint).
        x1, y1, x2, y2 = COPY_RECT
        _round_rect(c, x1, y1, x2, y2, CHIP_H // 2, fill=CHIP, outline="")
        # gen.py's chip is `{COPY_ICON}Copy` — two offset rounded rectangles,
        # the back one open where the front overlaps it. The label sits after
        # the glyph rather than centred in the chip, which is what the flex
        # row with its 6 px gap does.
        gx, gy = x1 + 11, (y1 + y2) // 2
        _round_rect(c, gx - 1, gy - 2, gx + 7, gy + 6, 2,
                    fill="", outline=MUTED, width=1)
        c.create_line(gx + 2, gy - 2, gx - 4, gy - 2, gx - 4, gy + 3,
                      fill=MUTED, width=1)
        c.create_text(gx + 13, gy, anchor="w", text="Copy",
                      font=FONT_CHIP, fill=CODE)
        c.create_text(x2 + 10, (y1 + y2) // 2, anchor="w",
                      text=spec["hint"], font=FONT_TAG, fill=DIM)
        if spec["send"]:
            x1, y1, x2, y2 = SEND_RECT
            _round_rect(c, x1, y1, x2, y2, CHIP_H // 2,
                        fill=PRIMARY_FILL, outline="")
            c.create_text((x1 + x2) // 2, (y1 + y2) // 2, text="Send",
                          font=FONT_CHIP_PRIMARY, fill=PRIMARY_TEXT)

    def _draw_folder(self, c, x: int, cy: int, colour: str = DIM) -> None:
        """The strip's folder glyph, stroked like the mic: a tab and a body,
        13 px square, gen.py's `FOLDER` reduced to its two readable lines.

        `colour` because gen.py's `strip()` and `wsrow()` both take one, and
        it carries meaning rather than decoration: green says this workspace
        is real and grounded, grey says there is none. Drawn `DIM` whatever
        the state, the strip claimed "no workspace" over a live path."""
        c.create_line(x, cy - 4, x + 4, cy - 4, x + 6, cy - 2,
                      fill=colour, width=1)
        c.create_rectangle(x, cy - 2, x + 13, cy + 5, outline=colour, width=1)

    def _draw_box_chrome(self, c, h: int) -> None:
        """The `.box` shell both standalone windows share: SHELL, the 1 px
        `RING_OUTER` border at 18 px, and the `RING_TOP` inset highlight —
        the pill's own three hairlines at the box's radius."""
        _round_rect(c, 0, 0, BOX_W - 1, h, 18, fill=SHELL, outline=RING_OUTER)
        c.create_line(19, 1, BOX_W - 19, 1, fill=RING_TOP)

    def _draw_palette(self, c) -> None:
        """The search palette from Workspace.dc.html: field with caret, the
        filtered folders with the top hit lit, the matched letters tinted, the
        pinned last row, the footer legend.

        The `.hit` tint is measured, not skipped. It was left out as needing
        "font metrics a 30 ms frame will not pay for" — but this box does not
        redraw at 30 ms. It redraws on a keystroke, which is the only thing
        that can change what matched, and `tkfont.Font.measure` on one cached
        font is nothing at that rate."""
        h = self._box_height()
        self._draw_box_chrome(c, h)
        # The field: search glyph, the query so far, the caret.
        c.create_oval(16, 13, 26, 23, outline=DIM, width=1)
        c.create_line(25, 22, 30, 27, fill=DIM, width=1)
        query = self._palette.query
        c.create_text(38, PALETTE_FIELD_H // 2, anchor="w", text=query,
                      font=(FONT_MONO, -13), fill=TEXT)
        caret = 38 + len(query) * 8
        c.create_line(caret, 11, caret, PALETTE_FIELD_H - 11,
                      fill=HEARING, width=1)
        c.create_line(0, PALETTE_FIELD_H, BOX_W, PALETTE_FIELD_H, fill=SEAM)
        for i, (label, is_none) in enumerate(self._palette.rows()):
            y = PALETTE_FIELD_H + i * PALETTE_ROW_H
            if i == 0:
                # "Top hit highlighted" — the row, not the matched letters.
                c.create_rectangle(1, y, BOX_W - 1, y + PALETTE_ROW_H,
                                   fill=CHIP, outline="")
            cy = y + PALETTE_ROW_H // 2
            # gen.py's `wsrow`: the current row's folder is green, the rest
            # grey, and the "just talk" row's is grey because there is no
            # folder behind it.
            self._draw_folder(c, 16, cy,
                              HEARING if i == 0 and not is_none else DIM)
            font = (FONT_MONO, -12)
            hit = -1 if is_none or not query else label.lower().find(query.lower())
            if hit >= 0:
                # gen.py's `.hit`: the matched letters carry a green wash and
                # step up to `TEXT`. The wash is a blend rather than an alpha
                # — this window is colour-keyed and cannot composite, which is
                # the rule `_mix` exists for (flow/ui.py:1850).
                m = self._measure(c, font)
                x0 = 38 + m(label[:hit])
                x1 = x0 + m(label[hit:hit + len(query)])
                c.create_rectangle(x0 - 1, cy - 8, x1 + 1, cy + 8,
                                   fill=_mix(CHIP if i == 0 else SHELL,
                                             HEARING, 0.16), outline="")
            c.create_text(38, cy, anchor="w", text=label, font=font,
                          fill=PLACEHOLDER if is_none else CODE)
            if hit >= 0:
                c.create_text(x0, cy, anchor="w",
                              text=label[hit:hit + len(query)],
                              font=font, fill=TEXT)
        foot = h - PALETTE_FOOT_H
        c.create_line(0, foot, BOX_W, foot, fill=SEAM)
        c.create_text(16, foot + PALETTE_FOOT_H // 2, anchor="w",
                      text="↵ set    esc leave it", font=FONT_TAG, fill=DIM)

    def _setup_rows(self) -> list:
        """The workbench's three answers (Workspace.dc.html), each a value
        Flow already found: the microphone PortAudio opened, the CLI
        `Session.provider` names — "none found" when there isn't one, which
        item 6's no-CLI fallback needs too — and where a release's words go."""
        mic = self.session.mic.device_name or "none found"
        cli = self.session.provider or "none found"
        on_release = ("paste into last window" if self.session.pastes
                      else "copy — you paste it")
        return [("Microphone", mic), ("Agent CLI", cli),
                ("On release", on_release)]

    def _measure(self, c, spec):
        """A text-width function for `spec` on the target that is drawing.

        Through `c` and not always through Tk, because the two do not agree:
        the palette measures a prefix to place the `.hit` tint over the
        letters that matched, and measuring in Tk's metrics while GDI+ draws
        the glyphs put the tint further off with every character
        (`.shots/12-compact-palette.png`, where the highlight and the text it
        was highlighting had come apart).

        The Tk answer is cached per spec, because building a `tkfont.Font`
        asks the interpreter for metrics and the palette would otherwise do it
        per row per keystroke. `GdiCanvas` does its own caching.
        """
        measure = getattr(c, "measure", None)
        if measure is not None:
            return lambda text: measure(text, spec)[0]
        fn = self._fonts.get(spec)
        if fn is None:
            try:
                fn = tkfont.Font(font=spec).measure
            except (tk.TclError, RuntimeError):
                # No interpreter behind this instance, or none yet — every
                # headless draw test. The palette's font is mono, so the nominal advance is
                # the real answer there rather than a stand-in, and it is the
                # same number the field's caret already steps by.
                advance = abs(spec[1]) * 2 // 3
                fn = lambda s, _w=advance: len(s) * _w  # noqa: E731
            self._fonts[spec] = fn
        return fn

    def _draw_setup_icon(self, c, row: int, x: int, cy: int) -> None:
        """Workbench setup's three glyphs (gen.py's `workspace` page), stroked
        at 14 px like every other glyph on this surface: a microphone and a
        terminal in `HEARING`, and a muted arrow-into-a-baseline for where the
        words land."""
        if row == 0:  # Microphone — the mic, minus the meter's stem
            _round_rect(c, x + 4, cy - 6, x + 10, cy + 1, 3,
                        fill="", outline=HEARING, width=1)
            c.create_arc(x + 1, cy - 4, x + 13, cy + 5, start=180, extent=180,
                         style=tk.ARC, outline=HEARING, width=1)
            c.create_line(x + 7, cy + 5, x + 7, cy + 7, fill=HEARING, width=1)
        elif row == 1:  # Agent CLI — a prompt chevron and its line, in a box
            _round_rect(c, x + 1, cy - 6, x + 13, cy + 6, 2,
                        fill="", outline=HEARING, width=1)
            c.create_line(x + 4, cy - 3, x + 6, cy, x + 4, cy + 3,
                          fill=HEARING, width=1)
            c.create_line(x + 8, cy + 3, x + 11, cy + 3, fill=HEARING, width=1)
        else:  # On release — down into a baseline
            c.create_line(x + 7, cy - 6, x + 7, cy + 1, fill=MUTED, width=1)
            c.create_line(x + 4, cy - 2, x + 7, cy + 1, x + 10, cy - 2,
                          fill=MUTED, width=1)
            c.create_line(x + 2, cy + 5, x + 12, cy + 5, fill=MUTED, width=1)

    def _draw_setup(self, c) -> None:
        """Workbench setup: three read-only lines. Open it when something is
        wrong; otherwise never (Workspace.dc.html)."""
        self._draw_box_chrome(c, self._box_height())
        for i, (name, value) in enumerate(self._setup_rows()):
            y = i * SETUP_ROW_H
            if i:
                c.create_line(0, y, BOX_W, y, fill=SEAM)
            cy = y + SETUP_ROW_H // 2
            # Each row leads with its glyph (gen.py's `.row`: a 14 px icon,
            # then a 10 px gap, then the label). Green on the two Flow found
            # for itself, muted on the one that is a preference rather than a
            # discovery — the artboard's own split, and the reason the box can
            # be read at a glance instead of line by line.
            self._draw_setup_icon(c, i, 16, cy)
            c.create_text(38, cy, anchor="w", text=name,
                          font=FONT_BODY, fill=TEXT)
            c.create_text(BOX_W - 16, cy, anchor="e", text=value,
                          font=FONT_NOTE, fill=MUTED)

    def _eased(self, target: float) -> float:
        """This frame's drawn level, one step closer to `target` than the last.

        ui.py's one-pole, at the same 30 ms tick and the same two time
        constants (rise 60 ms → 0.3935, fall 160 ms → 0.1639 — hardcoded in
        ui.py rather than recomputed, for the reason flow/ui.py:995-1000
        states): peaks fall slower than they rise, so a loud spike does not
        vanish in the frame it arrived in.
        """
        alpha = LEVEL_RISE_ALPHA if target > self._eased_level else LEVEL_FALL_ALPHA
        self._eased_level += (target - self._eased_level) * alpha
        return self._eased_level

    @staticmethod
    def _norm(db: float) -> float:
        return max(0.0, min(1.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))
