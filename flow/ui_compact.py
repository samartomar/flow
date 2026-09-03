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
import sys
import time
import tkinter as tk
import traceback
from pathlib import Path

from .session import CONVERSE, DICTATE, REFINE, Session, State

# The hues and the fonts are ui.py's own, imported rather than restated: the
# spec's rule is "the hues flow/ui.py already gives those commands" (README),
# and a colour written down twice is a colour that drifts. `TEXT` is the
# near-white ui.py spends on primary text — the spec's "white" for Type.
# `SEAM` is ui.py's `RING` hairline under the name the docked design gives it:
# the one line between the panel and its foot.
from .ui import (
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
    FONT_PARTIAL,
    HEARING,
    LEVEL_FALL_ALPHA,
    LEVEL_RISE_ALPHA,
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
    _no_activate,
    _round_rect,
    _shell_window,
    _user32,
    foreground_hwnd,
    owned_by_flow,
    toplevel_hwnd,
)
from .ui import RING as SEAM

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

#: TODO: spoken punctuation ("press enter", "tab"), resolved locally so Type
#: gets it without a CLI (design/compact/README.md). The session's decode
#: pipeline owns words; this belongs beside it, not in the pill.


def _capsule(c: tk.Canvas, x1, y1, x2, y2, square_top=False, **kw) -> None:
    """A true stadium, filled: two `create_arc` pieslices of diameter `h` at
    each end plus a `create_rectangle` between them.

    `_round_rect` is a smoothed polygon, and at `r = h/2` it yields a rounded
    rectangle, not a capsule — the difference is what `.shots/01-compact-rest.png`
    showed before this helper existed. Kept separate from `_round_rect` rather
    than an option on it: the shipped surface depends on that shape staying
    exactly what it is.

    `square_top` is the foot (gen.py `.foot`: `border-radius: 0 0 17px 17px`):
    the panel docks above, the top corners square off to meet it, and each end
    keeps only its bottom quarter-circle.
    """
    h = y2 - y1
    if square_top:
        c.create_rectangle(x1, y1, x2, y2 - h / 2, **kw)
        c.create_arc(x1, y2 - h, x1 + h, y2, start=180, extent=90,
                     style=tk.PIESLICE, **kw)
        c.create_arc(x2 - h, y2 - h, x2, y2, start=270, extent=90,
                     style=tk.PIESLICE, **kw)
        c.create_rectangle(x1 + h / 2, y2 - h / 2, x2 - h / 2, y2, **kw)
        return
    c.create_arc(x1, y1, x1 + h, y2, start=90, extent=180,
                 style=tk.PIESLICE, **kw)
    c.create_arc(x2 - h, y1, x2, y2, start=270, extent=180,
                 style=tk.PIESLICE, **kw)
    c.create_rectangle(x1 + h / 2, y1, x2 - h / 2, y2, **kw)


def _capsule_ring(c: tk.Canvas, x1, y1, x2, y2, colour: str, width=1,
                  square_top=False, top=True) -> None:
    """The stadium as a stroke: two arc outlines and the straight runs
    between them, because a pieslice's outline also draws its radii — the
    diameter line — and a capsule has none.

    The runs sit on integer rows while the bbox stays fractional-free,
    because the two primitives rasterize differently: an arc's stroke falls
    *inside* its bbox, and a line's centres on its path with half-pixels
    rounding up — a run drawn at `y1 + width/2` lands one row low (and the
    bottom run lands off the window entirely). Measured against
    `.shots/02-compact-hearing.png`, where both showed.

    `square_top` is the foot's variant: quarter arcs at the bottom corners and
    verticals up the sides. `top` says whether the top run is drawn — gen.py's
    `.foot` has `border-top: 0` (the seam belongs to the panel above it), but
    a state ring is a `box-shadow` and wraps all four sides.
    """
    h = y2 - y1
    dy = (width - 1) / 2
    if square_top:
        c.create_arc(x1, y2 - h, x1 + h, y2, start=180, extent=90,
                     style=tk.ARC, outline=colour, width=width)
        c.create_arc(x2 - h, y2 - h, x2, y2, start=270, extent=90,
                     style=tk.ARC, outline=colour, width=width)
        c.create_line(x1 + dy, y1, x1 + dy, y2 - h / 2,
                      fill=colour, width=width)
        c.create_line(x2 - 1 - dy, y1, x2 - 1 - dy, y2 - h / 2,
                      fill=colour, width=width)
        c.create_line(x1 + h / 2, y2 - 1 - dy, x2 - h / 2, y2 - 1 - dy,
                      fill=colour, width=width)
        if top:
            c.create_line(x1, y1 + dy, x2 - 1, y1 + dy,
                          fill=colour, width=width)
        return
    c.create_arc(x1, y1, x1 + h, y2, start=90, extent=180,
                 style=tk.ARC, outline=colour, width=width)
    c.create_arc(x2 - h, y1, x2, y2, start=270, extent=180,
                 style=tk.ARC, outline=colour, width=width)
    c.create_line(x1 + h / 2, y1 + dy, x2 - h / 2, y1 + dy,
                  fill=colour, width=width)
    c.create_line(x1 + h / 2, y2 - 1 - dy, x2 - h / 2, y2 - 1 - dy,
                  fill=colour, width=width)


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
    #: The right-click menu, built in `__init__`. None on a fixture, and
    #: `_on_menu` checks rather than assuming.
    _menu = None
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
    #: The window's current size: PILL_W × PILL_H alone, PANEL_W ×
    #: (PANEL_H + PILL_H) with the band. `_sync_shell` no-ops on equality,
    #: which is what a bare fixture's values describe.
    _shell_w = PILL_W
    _shell_h = PILL_H
    #: The outside-click poll's edge detector: the button's last read.
    _outside_was_down = False
    #: Whether the window is out of the activation chain. Set in `__init__`
    #: from `_no_activate`'s read-back; False on a fixture, which is the
    #: Lite/Mac answer `_on_menu`'s foreground borrow keys off.
    no_activate = False

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
        self._last_draft = ""
        self._send_pending = False
        self.paste_target = None
        self._panel_open = False
        self._panel_mode = None
        self._panel_heard = ""
        self._panel_heard_final = False
        self._panel_result = ""
        self._ask_pending = False
        self._shell_w = PILL_W
        self._shell_h = PILL_H
        self._outside_was_down = False

        # The window. `_shell_window` applies the five probed attributes and
        # answers with the background the canvas must agree with — see its
        # docstring for why the background is returned rather than assumed.
        self.geometry(f"{PILL_W}x{PILL_H}")
        bg = _shell_window(self, lite, PILL_ALPHA)
        self.configure(bg=bg)
        self.canvas = tk.Canvas(
            self, width=PILL_W, height=PILL_H, bg=bg,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

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
        self._menu.add_command(label="Quit", command=self.quit_app)
        # TODO: the rest of the menu is drawn in design/compact/Workspace.dc.html
        # — a mode list, Switch workspace, Workbench setup. Right-click is the
        # only menu the design allows, so all three land here when they land.

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
                # disarmed and flash, rather than showing a green ring over a
                # capture that does not exist — `_toggle`'s rule, kept here.
                self._flash = FLASH_FRAMES
            else:
                self.armed = True

        self.after(30, self._tick)

    # `mainloop` is tk.Tk's own, and that is deliberate: __main__.py drives
    # this class exactly as it drives Pill — construct, `mainloop()`, and
    # `quit_app()` out of the KeyboardInterrupt clause.

    def quit_app(self) -> None:
        # Idempotent, for the reason ui.py's is: ctrl+C reaches here down
        # either of two paths (caught in `_tick`, or escaping `mainloop`) and
        # nothing upstream can tell which one ran.
        if not self._alive:
            return
        self._alive = False
        try:
            if self.hotkeys is not None:
                self.hotkeys.stop()
            self.session.close()
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
        self._draw()

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
                # A pending paste belongs to the mode it was spoken in. Dictate
                # pastes into a window and converse asks a CLI, so a wait armed
                # in one and fired in the other does something the user never
                # asked for — ui.py:4363-4369's rule, whose words these are.
                # Dropped rather than translated: the words stay in the draft,
                # and Send in the new mode does whatever it now means.
                self._send_pending = False
                self.session.toggle_mode()
            elif name == "quit":
                self.quit_app()
                return False
        return True

    def _pump_events(self) -> None:
        """Drain what the session said since the last frame.

        The pill itself owns exactly two — an error turns the ring red, and a
        `disarm` is the session saying capture has stopped and cannot restart
        itself, so the surface that owns "armed" has to stop claiming it. The
        send path owns `draft`: the decode landing, its text what `_send` hands
        over when a Type release is waiting — release, draft, paste, and no
        panel (README: "Type never opens a panel"). The panel owns the rest: a
        `partial` is the heard block's live text, a `draft` against an armed
        ask is the question going to the CLI, a `reply` is the answer landing
        in the result block, and a `mode` closes the band — it belongs to the
        mode that raised it. `note` alone still falls through, documented:
        its homes ("nothing to ask", "still waiting") are item 6's fallback
        sentences, and it gets them there.
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
                    # The heard block's live text — italic until the release's
                    # draft makes it final.
                    self._panel_heard = ev.text
                    self._panel_heard_final = False
            elif ev.kind == "reply":
                if ev.text:
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
            elif ev.kind == "disarm":
                self.armed = False

    def _ask(self) -> None:
        """The panel-mode release: the heard block's final text goes to the CLI.

        `session.send()` in converse starts the ask and returns "" — the words
        are never pasted, which is the Type-only paste rule `_talk_end`'s gate
        states: Ask results land here, not in the window you were in. The
        answer itself arrives 4-20 s later as a `reply` event.
        """
        self._ask_pending = False
        self._panel_heard = self._last_draft
        self._panel_heard_final = True
        self._panel_result = ""
        self.session.send()

    def _send(self) -> None:
        """Hand the draft over: the words paste, or the ring says they could not.

        The shape is ui.py's `_send` (flow/ui.py:3756-3770) — the text from
        `session.send()`, the paste target this surface polls, the problem the
        handler hands back — down to the first line, which is what stops a
        release and the `send` hotkey pasting the same words twice. Where the
        full pill spends a problem on a bubble card, this one has no words to
        say it with yet: a problem is the red flash, the whole vocabulary for
        "something is wrong" until the panel lands. The CLI is not on this
        path — Type is dictate, and `session.send()` in dictate never asks.
        The Lite fallback (clipboard, plus "copied — press Ctrl+V" under the
        pill) is item 6's; with no handler there is nothing here yet.
        """
        self._send_pending = False
        text = self.session.send()
        if text and self.on_send:
            problem = self.on_send(text, self.paste_target) or ""
            if problem:
                self._flash = FLASH_FRAMES

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
        try:
            self._talk_start()
        except Exception:
            # Same refusal `_toggle` makes: a green ring over a dead capture
            # is the one lie this surface must not tell.
            self._flash = FLASH_FRAMES
            self._press_at = None
            return
        self.armed = True

    # -- the gestures --------------------------------------------------------

    def _talk_start(self) -> None:
        """The hold beginning, shared by the mouse pump and the `talk` hotkey.

        A hold in a panel mode raises the panel at once — the heard block is
        where the partials land — and starts fresh: "the next hold starts
        fresh" (Ask.dc.html), which is also what makes the foot's "hold to
        reply" a reply rather than an append. Type is not in `PANEL_SPEC`, so
        its holds change nothing on screen (README: "Type never opens a
        panel").
        """
        self._press_talking = True
        self.session.talk_start()
        if self.session.mode in PANEL_SPEC:
            self._panel_mode = self.session.mode
            self._panel_heard = ""
            self._panel_heard_final = False
            self._panel_result = ""
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
        """
        self._press_talking = False
        pending = self.session.talk_end()
        if send and pending:
            if self.session.mode == DICTATE:
                self._send_pending = True
            elif self.session.mode in PANEL_SPEC:
                self._ask_pending = True

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
                return
            self.armed = True

    def _on_press(self, e=None) -> None:
        """The button going down: remember when and where, decide nothing yet.

        Except where: with the panel open, a press in the band is a chip
        click, never a hold — the foot is the part that stays holdable
        (README), and the band is the part with buttons on it.
        """
        if (self._panel_open and e is not None
                and getattr(e, "y", PILL_H) < PANEL_H):
            self._panel_click(e)
            return
        self._press_at = time.perf_counter()
        self._press_xy = (getattr(e, "x_root", 0), getattr(e, "y_root", 0))
        self._press_moved = False
        self._press_talking = False

    def _on_motion(self, e=None) -> None:
        """A press that travels past the slop is the window being dragged."""
        if self._press_at is None:
            return
        x, y = getattr(e, "x_root", 0), getattr(e, "y_root", 0)
        if (abs(x - self._press_xy[0]) > PILL_DRAG_SLOP
                or abs(y - self._press_xy[1]) > PILL_DRAG_SLOP):
            self._press_moved = True

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
            # A pending paste belongs to the mode it was spoken in — the same
            # drop the `mode` hotkey documents, made by the tap that switches
            # modes here.
            self._send_pending = False
            self.session.toggle_mode()

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
        previous = foreground_hwnd() if self.no_activate else 0
        if self.no_activate:
            _user32.SetForegroundWindow(toplevel_hwnd(self))
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()  # the documented idiom; cheap insurance
            if previous:
                _user32.SetForegroundWindow(previous)

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
        """Resize the one window around the foot: 120×34 alone, 400×(200+34)
        with the band — the shipped surface's `_shell_h != PILL_H` mechanism
        (flow/ui.py:4985-5000), adapted to the capsule.

        The foot's bottom edge is the anchor — "the pill never hides and never
        moves" (README) — so the band grows upward, and the left edge stays
        put so the mic does. The two clamps are the screen saying otherwise:
        the band goes left rather than off the right edge (the mic moves
        before the panel clips), and down rather than off the top.
        """
        w = PANEL_W if self._panel_open else PILL_W
        h = PILL_H + (PANEL_H if self._panel_open else 0)
        if (w, h) == (self._shell_w, self._shell_h):
            return
        x, foot = self.winfo_rootx(), self.winfo_rooty() + self._shell_h
        if x + w > self.winfo_screenwidth():
            x = self.winfo_screenwidth() - w
        y = max(0, foot - h)
        self._shell_w, self._shell_h = w, h
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _panel_click(self, e) -> None:
        """A press in the band: the only live things there are the strip's
        close, the footer's Copy, and Send when the mode has one."""
        x, y = e.x, e.y
        if _hit(CLOSE_RECT, x, y):
            self._close_panel()
        elif _hit(COPY_RECT, x, y):
            self._copy_result()
        elif self._spec()["send"] and _hit(SEND_RECT, x, y):
            self._panel_send()

    def _copy_result(self) -> None:
        """The Copy chip: the answer, or the question if that is all there is.

        "Copy leaves the panel up" (Refine.dc.html) — it changes nothing but
        the clipboard. The borrow is ui.py's one clipboard transaction, shared
        rather than copied.
        """
        text = self._panel_result or self._panel_heard
        if not text:
            return
        if _copy_to_clipboard(self, text):
            self._flash = FLASH_FRAMES

    def _panel_send(self) -> None:
        """The footer Send: paste the result into `paste_target`, and close.

        The mechanism is item 4's Refine flow wired ahead of it — paste the
        refined text where the user was, through the same `on_send` contract
        item 1 pasted drafts through, target included. No mode sets `send`
        while the session has two: Ask's footer is Copy and the hint
        (Ask.dc.html), and Type never opens the panel at all.
        """
        text = self._panel_result
        if text and self.on_send:
            problem = self.on_send(text, self.paste_target) or ""
            if problem:
                self._flash = FLASH_FRAMES
        self._close_panel()

    def _outside_click_now(self) -> bool:
        """One frame's answer to "did the user just click somewhere that is
        not this window". Polled only while the panel is open.

        A NOACTIVATE window is never told it lost focus — it never had it —
        so click-outside is a poll, not an event: the left button's up→down
        edge with the cursor outside our rect. Two read-only Win32 calls a
        frame, and Lite does not ask — no target awareness there, and
        `_user32` is `_NoHands`.
        """
        if self.lite:
            return False
        down = bool(_user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
        was, self._outside_was_down = self._outside_was_down, down
        if not down or was:
            return False
        pt = _POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        x, y = self.winfo_rootx(), self.winfo_rooty()
        return not (x <= pt.x < x + self._shell_w
                    and y <= pt.y < y + self._shell_h)

    # -- the drawing ---------------------------------------------------------

    def _ring_colour(self) -> str:
        """This frame's ring, or "" for none at rest.

        The flash outranks the state, because an error is true regardless of
        which state raised it — the same layering ui.py's `accent` gives. A
        disarmed pill is at rest whatever the session thinks: capture is off,
        and a ring would claim otherwise.
        """
        if self._flash:
            return ERROR
        if not self.armed:
            return ""
        return RING.get(self.session.state, "")

    def _glyph_tint(self) -> str:
        """This frame's mic tint: the mode's hue (Main.dc.html)."""
        return MODE_TINT.get(self.session.mode, TEXT)

    def _draw(self) -> None:
        """Draw the whole window onto `self.canvas`. Pure: state in, shapes out.

        Tested headless against a recording fake, exactly as `Pill._draw` is —
        which is why every attribute this reads that a fixture does not set is
        a class-level default above.
        """
        c = self.canvas
        c.delete("all")
        if self._panel_open:
            self._draw_panel(c)
            self._draw_foot(c)
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
        c.create_arc(hi, hi, PILL_W - hi, PILL_H - hi,
                     start=0, extent=180, style=tk.ARC, outline=RING_TOP)
        self._draw_face(c, 0, BARS)

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
        self._draw_folder(c, PAD_X, STRIP_H // 2)
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
            if spec["result_tag"] is not None:
                # Refine.dc.html: the tag carries the hue, the text is plain.
                c.create_text(PAD_X, RESULT_Y, anchor="w",
                              text=spec["result_tag"], font=FONT_TAG,
                              fill=accent)
                c.create_text(PAD_X, RESULT_Y + 16, anchor="nw", text=result,
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
        c.create_text((x1 + x2) // 2, (y1 + y2) // 2, text="Copy",
                      font=FONT_CHIP, fill=CODE)
        c.create_text(x2 + 10, (y1 + y2) // 2, anchor="w",
                      text=spec["hint"], font=FONT_TAG, fill=DIM)
        if spec["send"]:
            x1, y1, x2, y2 = SEND_RECT
            _round_rect(c, x1, y1, x2, y2, CHIP_H // 2,
                        fill=PRIMARY_FILL, outline="")
            c.create_text((x1 + x2) // 2, (y1 + y2) // 2, text="Send",
                          font=FONT_CHIP_PRIMARY, fill=PRIMARY_TEXT)

    def _draw_folder(self, c, x: int, cy: int) -> None:
        """The strip's folder glyph, stroked like the mic: a tab and a body,
        13 px square, gen.py's `FOLDER` reduced to its two readable lines."""
        c.create_line(x, cy - 4, x + 4, cy - 4, x + 6, cy - 2,
                      fill=DIM, width=1)
        c.create_rectangle(x, cy - 2, x + 13, cy + 5, outline=DIM, width=1)

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
