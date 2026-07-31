"""The floating pill and the draft bubble (R12-R15).

tkinter only — no GUI dependency. Two borderless always-on-top windows:

  Pill    a small capsule: mic glyph, live level bars, colour = state (R12, R13)
  Bubble  rises above the pill when a draft exists, with Refine / Continue / Send
          (R14, R15)

All five window attributes this relies on were probed on this machine before the file
was written: overrideredirect, -topmost, -alpha, -transparentcolor, -toolwindow.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
import traceback
from collections import deque

from .session import DICTATE, Session, State


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


#: SystemParametersInfo(SPI_GETWORKAREA)
_SPI_GETWORKAREA = 0x0030


def _work_area(sw: int, sh: int) -> tuple[int, int, int, int]:
    """The desktop minus the taskbar, in the same pixels `geometry` uses.

    The pill used to be placed against `winfo_screenheight()` less a guessed 90 px of
    taskbar. Guessing is why it ended up sitting on top of the tray: the taskbar is a
    different height on every machine, and can be on any edge.
    """
    rect = _RECT()
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
    except (AttributeError, OSError):
        ok = 0
    if not ok or rect.right <= rect.left or rect.bottom <= rect.top:
        return 0, 0, sw, sh
    return rect.left, rect.top, rect.right, rect.bottom


def _dpi_aware() -> float:
    """Tell Windows this process draws its own pixels, and return the scale factor.

    Without this the pill is bitmap-stretched by the compositor — visibly soft next to
    native text — and, worse, every coordinate goes wrong: `winfo_screenwidth` reports
    *logical* pixels while the window is placed in *physical* ones, so on a 150%
    display the pill computes a position for a 1280-wide screen and lands somewhere in
    the corner of a 1920-wide one, dragging the bubble off the edge with it.

    Must run before the first Tk window exists. `ctypes` is stdlib, so R16 holds.
    """
    try:
        # Per-monitor v2 where it exists: the scale can differ per display, and a
        # window dragged between them has to be told.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                return 1.0
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except (AttributeError, OSError):
        return 1.0

TRANSPARENT = "#ff00fe"  # keyed out by -transparentcolor; unlikely in real content
SHELL = "#12161f"
TEXT = "#e6e9ef"
MUTED = "#8b93a5"
CHIP = "#1f2632"

#: R13: colour encodes state, so the pill reads at a glance without being looked at.
ACCENT = {
    State.IDLE: "#64748b",  # slate  - resting
    State.LISTENING: "#22c55e",  # green  - capturing speech
    State.DRAFT: "#f59e0b",  # amber  - text held, awaiting a decision
    State.REFINING: "#3b82f6",  # blue   - CLI rewrite in flight
    State.ASKING: "#a855f7",  # violet - P9, a question is with the CLI
}
ERROR = "#ef4444"

#: P9. The answer, distinct from the user's own words in the same bubble. Nothing else
#: in the UI is this colour, because mistaking the model's words for your own is the
#: one confusion converse mode can create that dictate mode cannot.
REPLY = "#7dd3fc"

PILL_W, PILL_H = 152, 40
BARS = 18
BAR_W, BAR_GAP = 4, 2
DB_FLOOR, DB_CEIL = -58.0, -12.0  # level range mapped onto bar height

BUBBLE_W = 380
PAD = 14


def _round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle via a smoothed polygon — no image assets, no dependency."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


class Pill(tk.Tk):
    """The always-visible control. Click to arm/disarm, drag to move."""

    def __init__(self, session: Session, on_send=None, hotkeys=None, arm=False) -> None:
        scale = _dpi_aware()  # before the first Tk window exists, or it has no effect
        super().__init__()
        self.scale = scale
        self.session = session
        self.on_send = on_send
        self.hotkeys = hotkeys
        self._arm_on_start = arm
        self.levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self.armed = False
        self._flash = 0  # frames remaining of the error flash

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.94)
        self.attributes("-transparentcolor", TRANSPARENT)
        self.attributes("-toolwindow", True)
        self.configure(bg=TRANSPARENT)

        self.work = _work_area(self.winfo_screenwidth(), self.winfo_screenheight())
        left, top, right, bottom = self.work
        self.x = right - PILL_W - 28
        self.y = bottom - PILL_H - 24
        self.geometry(f"{PILL_W}x{PILL_H}+{self.x}+{self.y}")

        self.canvas = tk.Canvas(
            self, width=PILL_W, height=PILL_H, bg=TRANSPARENT, highlightthickness=0
        )
        self.canvas.pack()

        self.bubble = Bubble(self)
        self._bind_drag()
        self.canvas.bind("<Button-1>", self._toggle)
        self.canvas.bind("<Button-3>", self._menu)
        self.bind("<Escape>", lambda _e: self.quit_app())

        self._draw()
        # Arm after the first frame is painted, so a capture failure has somewhere
        # visible to report itself.
        if self._arm_on_start:
            self.after(120, self._toggle)
        self.after(30, self._tick)

    # -- interaction -------------------------------------------------------

    def _bind_drag(self) -> None:
        self._drag = (0, 0)

        def press(e):
            self._drag = (e.x_root - self.x, e.y_root - self.y)

        def drag(e):
            left, top, right, bottom = self.work
            self.x = max(left, min(e.x_root - self._drag[0], right - PILL_W))
            self.y = max(top, min(e.y_root - self._drag[1], bottom - PILL_H))
            self.geometry(f"{PILL_W}x{PILL_H}+{self.x}+{self.y}")
            self.bubble.reposition()

        self.canvas.bind("<B1-Motion>", drag)
        self.canvas.bind("<ButtonPress-1>", press, add="+")

    def _toggle(self, _e=None) -> None:
        if self.armed:
            self.armed = False
            self.session.pause()
        else:
            try:
                self.session.start()
            except Exception as exc:
                # No microphone, device in exclusive use, driver failure. Stay disarmed
                # and say so, rather than flipping to a green pill that captures nothing.
                self._flash = 60
                self.bubble.surface(f"could not start capture: {exc}")
                self._draw()
                return
            self.armed = True
        self._draw()

    def _menu(self, e) -> None:
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Send", command=self._send)
        m.add_command(
            label="Converse mode" if self.session.mode == DICTATE else "Dictate mode",
            command=self.session.toggle_mode,
        )
        if getattr(self.session, "speaker", None) is not None:
            m.add_command(
                label="Mute replies" if not self.session.muted else "Speak replies",
                command=self.session.toggle_speech,
            )
        m.add_command(label="Clear draft", command=self._clear)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit_app)
        m.tk_popup(e.x_root, e.y_root)

    def _send(self) -> None:
        text = self.session.send()
        if text and self.on_send:
            self.on_send(text)
        # In converse mode send() returns "" and the answer is still coming, so the
        # bubble has to stay up to render it.
        if self.session.mode == DICTATE:
            self.bubble.hide()

    def _clear(self) -> None:
        self.session.draft.clear()
        self.bubble.hide()

    def quit_app(self) -> None:
        try:
            if self.hotkeys is not None:
                self.hotkeys.stop()
            self.session.close()
        finally:
            self.destroy()

    # -- the pump ----------------------------------------------------------

    def _tick(self) -> None:
        """Drive one frame. Must never propagate an exception.

        The re-schedule is in `finally` deliberately: a raise out of this callback would
        break the `after()` chain and leave a pill that is still on screen but completely
        dead, with the traceback buried in a stderr nobody is watching. For an
        always-on widget that is the worst available failure mode, so any error becomes
        a red flash plus a visible note and the loop carries on.
        """
        try:
            self._frame()
        except Exception as exc:
            self._flash = 40
            self.bubble.surface(f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            self.after(30, self._tick)

    def _frame(self) -> None:
        # Hotkeys arrive on their own thread; Tk is only ever touched from this one.
        if self.hotkeys is not None:
            for name in self.hotkeys.drain():
                if name == "toggle":
                    self._toggle()
                elif name == "send":
                    self._send()
                elif name == "cancel":
                    self._clear()
                elif name == "mode":
                    self.session.toggle_mode()

        if self.armed:
            self.session.tick()
            self.levels.append(self._norm(self.session.level_db))
        else:
            self.levels.append(0.0)

        for ev in self.session.events():
            if ev.kind == "draft":
                if ev.text:
                    self.bubble.show(ev.text)
                elif self.session.state is not State.ASKING:
                    self.bubble.hide()
                else:
                    # Asking clears the draft, and hiding here left the user staring
                    # at nothing for the ten seconds the CLI takes. Keep the bubble up
                    # so "asking..." is somewhere to be seen.
                    self.bubble.show_reply("")
            elif ev.kind == "partial":
                self.bubble.show_partial(ev.text)
            elif ev.kind == "error":
                self._flash = 12
                self.bubble.note(ev.text)
            elif ev.kind == "note":
                self.bubble.note(ev.text)
            elif ev.kind == "reply":
                self.bubble.show_reply(ev.text)
            elif ev.kind == "mode":
                pass  # the accompanying note is what the user reads
            elif ev.kind == "drop":
                # Shown, not hidden: P2 is that a rejection is never silent. The
                # recovery affordance itself is Phase 3's rescue chip.
                self.bubble.note(ev.text)

        if self._flash:
            self._flash -= 1
        self._draw()

    @staticmethod
    def _norm(db: float) -> float:
        return max(0.0, min(1.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))

    # -- painting ----------------------------------------------------------

    @property
    def accent(self) -> str:
        if self._flash:
            return ERROR
        if not self.armed:
            return ACCENT[State.IDLE]
        return ACCENT.get(self.session.state, ACCENT[State.IDLE])

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        accent = self.accent
        _round_rect(c, 1, 1, PILL_W - 1, PILL_H - 1, PILL_H // 2, fill=SHELL, outline=accent)

        # Mic glyph: capsule + stand, drawn rather than fonted so there is no
        # dependency on an emoji font being present and correctly sized.
        cx, cy = 22, PILL_H // 2
        c.create_oval(cx - 4, cy - 9, cx + 4, cy + 1, fill=accent, outline=accent)
        c.create_arc(
            cx - 7, cy - 5, cx + 7, cy + 6, start=180, extent=180,
            style=tk.ARC, outline=accent, width=2,
        )
        c.create_line(cx, cy + 6, cx, cy + 10, fill=accent, width=2)
        # P9: which mode Send is in, readable at a glance. Without it, "there was no
        # spoken reply" and "I was never in converse mode" look identical.
        if getattr(self.session, "mode", DICTATE) != DICTATE:
            c.create_text(
                cx, PILL_H - 7, text="ASK", fill=accent,
                font=("Segoe UI", 6, "bold"),
            )

        # Level bars (R13). Mirrored around the centre line so quiet reads as a
        # flat line rather than an empty box.
        x0 = 40
        mid = PILL_H // 2
        for i, lvl in enumerate(self.levels):
            h = max(1.5, lvl * (PILL_H - 16) / 2)
            x = x0 + i * (BAR_W + BAR_GAP)
            shade = accent if lvl > 0.04 else MUTED
            c.create_rectangle(x, mid - h, x + BAR_W, mid + h, fill=shade, outline="")


class Bubble(tk.Toplevel):
    """The draft, floated above the pill (R14) with Refine / Continue / Send (R15)."""

    def __init__(self, pill: Pill) -> None:
        super().__init__(pill)
        self.pill = pill
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.attributes("-transparentcolor", TRANSPARENT)
        self.attributes("-toolwindow", True)
        self.configure(bg=TRANSPARENT)
        self.canvas = tk.Canvas(self, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self._visible = False
        self._text = ""
        self._note = ""
        self._partial = ""
        self._reply = ""
        #: Which float-up animation is current; older ones stop when this moves.
        self._anim = 0
        self._h = 120
        self.withdraw()

    # -- content -----------------------------------------------------------

    def show_reply(self, text: str) -> None:
        """P9: the CLI's answer. Clears the draft area — the question was sent.

        An empty `text` means "the question has gone, the answer is still coming":
        keep the bubble up and leave whatever is there, so the wait is visible.
        """
        self._text, self._partial = "", ""
        if text:
            self._reply = text
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()
        self._render()

    def show(self, text: str) -> None:
        # The answer stays up while the next question is dictated. It used to be
        # cleared the moment the user spoke again, which meant the reply they had just
        # asked for vanished before they could read it.
        self._text, self._partial = text, ""
        self._render()
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()

    def show_partial(self, text: str) -> None:
        # Partials are dimmed: they contain hallucinated fragments on mid-word
        # boundaries, so "not final yet" has to be visible.
        self._partial = text
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()
        self._render()

    def note(self, msg: str) -> None:
        self._note = msg
        if self._visible:
            self._render()

    def surface(self, msg: str) -> None:
        """Show a note even with no draft — used for errors, which must be seen."""
        self._note = msg
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()
        self._render()

    def hide(self) -> None:
        self._visible = False
        self._text = self._partial = self._note = self._reply = ""
        self.withdraw()

    # -- geometry ----------------------------------------------------------

    def reposition(self, lift: int = 0) -> None:
        """Anchor above the pill, clamped inside the work area.

        The clamp used to be `max(8, x)` alone, which pins the left edge and lets the
        right edge run off the display — so on a screen whose coordinates the app had
        got wrong, the bubble hung half outside it with its buttons unreachable. Both
        edges are bounded now, and against the work area rather than the raw screen.
        """
        left, top, right, bottom = self.pill.work
        x = self.pill.x + PILL_W - BUBBLE_W
        y = self.pill.y - self._h - 10 + lift
        x = max(left + 8, min(x, right - BUBBLE_W - 8))
        y = max(top + 8, min(y, bottom - self._h - 8))
        self.geometry(f"{BUBBLE_W}x{self._h}+{x}+{y}")

    def _float_up(self) -> None:
        """R14: rise into place rather than appearing, so the eye follows it.

        Generation-guarded. Each run schedules eight `after` callbacks that each move
        the window, so two overlapping runs fight over the position and the bubble
        visibly jitters between two places — which is what a fast show/hide/show cycle
        produces.
        """
        steps = 8
        self._anim += 1
        mine = self._anim

        def step(i: int) -> None:
            if not self._visible or mine != self._anim:
                return
            t = i / steps
            ease = 1 - (1 - t) ** 3
            self.attributes("-alpha", 0.96 * ease)
            self.reposition(lift=int(18 * (1 - ease)))
            if i < steps:
                self.after(16, step, i + 1)

        step(0)

    # -- painting ----------------------------------------------------------

    def _render(self) -> None:
        c = self.canvas
        accent = self.pill.accent
        body = self._text
        c.delete("all")

        # Measure first: the window has to be sized to the wrapped text.
        probe = c.create_text(
            PAD, PAD, anchor="nw", text=body or " ", fill=TEXT,
            font=("Segoe UI", 10), width=BUBBLE_W - 2 * PAD,
        )
        x1, y1, x2, y2 = c.bbox(probe)
        text_h = y2 - y1
        reply_h = 0
        if self._reply:
            rprobe = c.create_text(
                PAD, PAD, anchor="nw", text=self._reply, fill=REPLY,
                font=("Segoe UI", 10), width=BUBBLE_W - 2 * PAD,
            )
            rx1, ry1, rx2, ry2 = c.bbox(rprobe)
            reply_h = ry2 - ry1 + 8
        extra = reply_h
        if self._partial:
            extra += 34
        if self._note:
            extra += 18
        self._h = max(96, text_h + extra + 74)
        c.configure(width=BUBBLE_W, height=self._h)
        self.reposition()

        c.delete("all")
        _round_rect(c, 1, 1, BUBBLE_W - 1, self._h - 1, 14, fill=SHELL, outline=accent)
        y = PAD
        if self._reply:
            c.create_text(
                PAD, y, anchor="nw", text=self._reply, fill=REPLY,
                font=("Segoe UI", 10), width=BUBBLE_W - 2 * PAD,
            )
            y += reply_h
        if body:
            c.create_text(
                PAD, y, anchor="nw", text=body, fill=TEXT,
                font=("Segoe UI", 10), width=BUBBLE_W - 2 * PAD,
            )
            y += text_h + 6
        if self._partial:
            c.create_text(
                PAD, y, anchor="nw", text=self._partial, fill=MUTED,
                font=("Segoe UI", 9, "italic"), width=BUBBLE_W - 2 * PAD,
            )
            y += 28
        if self._note:
            c.create_text(
                PAD, self._h - 52, anchor="nw", text=self._note, fill=MUTED,
                font=("Segoe UI", 8), width=BUBBLE_W - 2 * PAD,
            )

        self._chips()

    def _chips(self) -> None:
        c = self.canvas
        specs = [
            ("Refine", self._refine, "force the next utterance to be an instruction"),
            ("Continue", self._continue, "force the next utterance to be dictation"),
        ]
        # Only offered when there is something to re-read. A chip that is always
        # present but usually does nothing teaches people to ignore it.
        if getattr(self.pill.session, "can_rescue", False):
            specs.append(
                ("Was a command", self._was_a_command,
                 "re-read the last dictation as an instruction"),
            )
        converse = getattr(self.pill.session, "mode", DICTATE) != DICTATE
        specs.append(
            ("Ask", self.pill._send, "put this to the agent CLI")
            if converse
            else ("Send", self.pill._send, "hand the draft off")
        )
        x = PAD
        y2 = self._h - PAD
        y1 = y2 - 26
        for label, cmd, _tip in specs:
            w = 20 + 7 * len(label)
            fill = self.pill.accent if label in ("Send", "Ask") else CHIP
            tag = f"chip-{label}"
            _round_rect(c, x, y1, x + w, y2, 13, fill=fill, outline="", tags=tag)
            c.create_text(
                x + w / 2, (y1 + y2) / 2, text=label,
                fill=SHELL if label in ("Send", "Ask") else TEXT,
                font=("Segoe UI", 9, "bold"), tags=tag,
            )
            c.tag_bind(tag, "<Button-1>", lambda _e, f=cmd: f())
            x += w + 8

    def _was_a_command(self) -> None:
        self.pill.session.rescue_last_append()

    def _refine(self) -> None:
        self.pill.session.force_next = "edit"
        self.note("listening for an instruction…")

    def _continue(self) -> None:
        self.pill.session.force_next = "append"
        self.note("listening to continue…")
