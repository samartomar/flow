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

**The spec has three modes; the session has two.** Type / Refine / Ask
(README) map onto DICTATE / — / CONVERSE: Type is dictate, Ask is converse,
and Refine's gold has no session counterpart yet. That is a documented gap,
not something this file extends `session.py` for — see `REFINE_GOLD` below.
The same applies to the 400 px panel the Refine and Ask artboards draw the
pill as the foot of, and to spoken punctuation: all are stubs citing their
artboards, not features.

Windowing is the same five probed attributes every Flow window wears
(`overrideredirect`, `-topmost`, `-alpha`, `-transparentcolor`, `-toolwindow`),
applied by ui.py's own `_shell_window` rather than re-probed here. Lite means
what it means there: nothing in this module imports `inject` or touches a
Win32 handle at module level — the scaffold has no hands to stub, and the day
the panel grows one, ui.py's guard (sys.platform == "win32", `_NoHands` at
flow/ui.py:68-79) is the pattern to copy.
"""

from __future__ import annotations

import time
import tkinter as tk
import traceback
from pathlib import Path

from .session import CONVERSE, DICTATE, Session, State

# The hues are ui.py's own, imported rather than restated: the spec's rule is
# "the hues flow/ui.py already gives those commands" (README), and a colour
# written down twice is a colour that drifts. `TEXT` is the near-white ui.py
# spends on primary text — the spec's "white" for Type.
from .ui import (
    CARD_ACCENT,
    DB_CEIL,
    DB_FLOOR,
    ERROR,
    FLASH_FRAMES,
    HEARING,
    LEVEL_FALL_ALPHA,
    LEVEL_RISE_ALPHA,
    MUTED,
    PILL_DRAG_SLOP,
    PILL_HOLD_SEC,
    SHELL,
    TEXT,
    WAITING,
    _dark_menu,
    _no_activate,
    _round_rect,
    _shell_window,
    _user32,
    foreground_hwnd,
    owned_by_flow,
    toplevel_hwnd,
)

#: The capsule, from Main.dc.html's `.pill`: 120 × 34, radius half the height.
#: Nothing on it is text — that is the design's first decision, not an omission.
PILL_W = 120
PILL_H = 34
PILL_ALPHA = 0.94

#: Mic glyph tint per mode (README: "white Type … violet Ask"). Keyed on the
#: session's two modes; the spec's third is below.
MODE_TINT = {
    DICTATE: TEXT,  # Type
    CONVERSE: CARD_ACCENT,  # Ask — the violet ui.py already gives the card
}

#: Refine's gold (README, and ui.py's Refine chip at flow/ui.py:2200). Declared
#: so the day the session grows a third mode the hue is already here — and a
#: constant rather than a map entry because nothing can reach it yet.
#:
#: TODO: no session counterpart. The session is DICTATE/CONVERSE and the spec's
#: Refine — "hands the CLI the workspace as its system role"
#: (design/compact/README.md) — is a mode session.py does not have. When it
#: lands, this joins MODE_TINT.
REFINE_GOLD = "#E1B75C"

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

#: The level meter: the spec's `.meter` is 2 px bars on a 2 px gap, blooming
#: around the centre line. Twelve of them fill what the glyph leaves of 120 px.
METER_X = 40
BARS = 12
BAR_W = 2
BAR_GAP = 4
BAR_MAX_HALF = 7.0  # half-height at full level — 14 px of travel inside 34

#: Where the docked panel grows to (Refine.dc.html, Ask.dc.html: "the pill
#: becomes the panel's foot … 120 -> 400 wide"). Not drawn by anything yet.
#:
#: TODO: the panel. Type never opens one; Refine and Ask raise 400 px of panel
#: *above* the pill, one window with one seam, the pill still holdable for
#: "say more" / reply, closed by Send / Esc / click-outside
#: (design/compact/README.md, Refine.dc.html, Ask.dc.html).
PANEL_W = 400

#: TODO: spoken punctuation ("press enter", "tab"), resolved locally so Type
#: gets it without a CLI (design/compact/README.md). The session's decode
#: pipeline owns words; this belongs beside it, not in the pill.


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
        if self._flash:
            self._flash -= 1
        self._draw()

    def _drain_hotkeys(self) -> bool:
        """Act on every hotkey that arrived since the last drain. False after a quit.

        The names are the ones `Pill._drain_hotkeys` (flow/ui.py:4333) acts on.
        `send` is bound here rather than arriving with the panel, because it was
        never the panel's: a dictation surface with no send is not a dictation
        surface. `cancel` alone still belongs to the panel ("Send / Esc /
        click-outside closes", design/compact/README.md) — until it docks there
        is nothing on this surface to cancel, so the chord is bound as a
        documented no-op rather than left to fall through. A name this loop does
        not know falls through, which is what an unbound chord does in the full
        UI too.
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
                self._press_talking = True
                self.session.talk_start()
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
                # A no-op until the panel lands (item 3, `PANEL_W`) — bound so
                # the chord is a decision, not a fall-through.
                pass
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

        Wordless, so the kinds split three ways. What the pill itself owns is
        exactly two — an error turns the ring red, and a `disarm` is the session
        saying capture has stopped and cannot restart itself, so the surface
        that owns "armed" has to stop claiming it. What the send path owns: a
        `draft` is the decode landing, its text is what `_send` hands over, and
        when a release is waiting on exactly that, this is where Type's arc
        finishes — release, draft, paste, and no panel (README: "Type never
        opens a panel"). What is still the panel's: `partial`, `note` and
        `reply` have nowhere to go until it docks (TODO, `PANEL_W`). `partial`
        is named and discarded rather than fallen through, because a stream
        kind nobody reads should be a decision, not an omission.
        """
        for ev in self.session.events():
            if ev.kind == "draft":
                self._last_draft = ev.text
                if ev.text and self._send_pending and not self._press_talking:
                    # Not mid-hold: a flag still armed from an earlier release
                    # must not fire on a segment final inside the *next*
                    # utterance. The words are cumulative in the draft either
                    # way — the next release re-arms and sends them all.
                    self._send()
            elif ev.kind == "partial":
                # Item 3 wires this into the panel's `heard` block.
                continue
            elif ev.kind == "error":
                self._flash = FLASH_FRAMES
            elif ev.kind == "disarm":
                self.armed = False

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
            self.session.talk_start()
        except Exception:
            # Same refusal `_toggle` makes: a green ring over a dead capture
            # is the one lie this surface must not tell.
            self._flash = FLASH_FRAMES
            self._press_at = None
            return
        self._press_talking = True
        self.armed = True

    # -- the gestures --------------------------------------------------------

    def _talk_end(self, *, send: bool) -> None:
        """The release, shared by the mouse and both hotkey endings.

        `send=False` is the `ctrl+win+d` path: the words are still committed
        and still land in the draft — nothing spoken is ever dropped (P2) —
        they simply do not paste themselves into whatever window a desktop
        switch just moved to. ui.py states the same at flow/ui.py:2760-2768.

        The send is *armed*, not fired: the decode is still in flight, and the
        `draft` event that brings the words is what fires it (`_pump_events`).
        Type only — Ask's release is the panel's "say more" and arrives with
        it (item 3), and `session.send()` in converse would ask the CLI, which
        README says this release never takes: "Type never opens a panel".
        """
        self._press_talking = False
        pending = self.session.talk_end()
        if send and pending and self.session.mode == DICTATE:
            self._send_pending = True

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
        """The button going down: remember when and where, decide nothing yet."""
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
        """Draw the whole pill onto `self.canvas`. Pure: state in, shapes out.

        Tested headless against a recording fake, exactly as `Pill._draw` is —
        which is why every attribute this reads that a fixture does not set is
        a class-level default above.
        """
        c = self.canvas
        c.delete("all")
        # The capsule body first, and it is load-bearing rather than cosmetic:
        # `_shell_window` keyed the canvas background out with
        # `-transparentcolor`, and on Windows a keyed pixel is a *click-through*
        # pixel — an unfilled pill is invisible against the desktop and lets the
        # press fall to whatever is behind it, which is exactly what the first
        # photographed run did to the right-click that was meant to open the
        # menu. Radius half the height, as Main.dc.html's `.pill` has it.
        _round_rect(c, 0, 0, PILL_W, PILL_H, PILL_H // 2, fill=SHELL, outline="")
        ring = self._ring_colour()
        if ring:
            # The hairline the spec means by "ring": a 2 px stroke a pixel
            # inside the capsule's own edge, rounded with it — a square corner
            # would poke past the capsule's into the keyed-out region.
            _round_rect(c, 1, 1, PILL_W - 1, PILL_H - 1, PILL_H // 2 - 1,
                        fill="", outline=ring, width=2)
        tint = self._glyph_tint()
        # Mic glyph: capsule + stand, the same three strokes ui.py draws
        # (flow/ui.py:4992-4998) at the same size — drawn, not fonted, so
        # there is no dependency on an emoji font being present.
        cx, cy = 20, PILL_H // 2
        c.create_oval(cx - 4, cy - 9, cx + 4, cy + 1, fill=tint, outline=tint)
        c.create_arc(cx - 7, cy - 5, cx + 7, cy + 6,
                     start=180, extent=180, style=tk.ARC, outline=tint, width=2)
        c.create_line(cx, cy + 6, cx, cy + 10, fill=tint, width=2)
        # The meter (R13's live level, restated wordless). Blooms around the
        # centre line so quiet reads as a flat line rather than an empty box.
        mid = PILL_H // 2
        lvl = self._meter_level
        shade = tint if lvl > 0.04 else MUTED
        centre = (BARS - 1) / 2
        for i in range(BARS):
            envelope = 1.0 - 0.6 * abs(i - centre) / centre
            h = 1.5 + lvl * BAR_MAX_HALF * envelope
            x = METER_X + i * (BAR_W + BAR_GAP)
            c.create_rectangle(x, mid - h, x + BAR_W, mid + h,
                               fill=shade, outline="")

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
