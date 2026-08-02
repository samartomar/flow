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
import os
import sys
import time
import tkinter as tk
import traceback
from collections import deque
from pathlib import Path

from .edits import SEND_WORD, SEND_WORD_PRESETS, enter_word
from .help import TITLE as HELP_TITLE, open_guide, open_path, rows as help_rows
from .lexicon import (
    DEFAULT_PATH as LEXICON_PATH,
    append_pair,
    ensure as ensure_lexicon,
    pairs,
)
from .profile import path_key, resolve_workspace
from .refine import available
from .session import DICTATE, Session, State


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


#: SystemParametersInfo(SPI_GETWORKAREA)
_SPI_GETWORKAREA = 0x0030


class _NoHands:
    """Every Win32 entry point this module has, answering "nothing happened".

    Lite's rule is that the *platform* decides what can be imported and `lite` decides
    what happens, so every call site that matters is already guarded by `self.lite`. This
    exists for the ones that are not: a stray call returns 0 instead of raising an
    `AttributeError` inside a Tk callback, where the only place it would surface is a
    stderr nobody is watching.
    """

    def __getattr__(self, _name):
        return lambda *_a, **_kw: 0


if sys.platform == "win32":
    from .inject import foreground_hwnd, owned_by_flow, take_warnings

    #: Its own handle rather than `ctypes.windll.user32`, which is a process-wide cached
    #: object: declaring `restype` on it would change the signature under `inject.py`
    #: too. Every call below is declared for the reason inject.py spells out — an
    #: undeclared ctypes restype is C `int`, so a 64-bit HWND or style word comes back
    #: truncated.
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetParent.argtypes = [ctypes.c_void_p]
    _user32.GetParent.restype = ctypes.c_void_p
    _user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    _user32.SetForegroundWindow.restype = ctypes.c_int
    # The Ptr forms exist only on 64-bit; the plain ones are the whole API on 32-bit.
    _get_style = getattr(_user32, "GetWindowLongPtrW", None) or _user32.GetWindowLongW
    _set_style = getattr(_user32, "SetWindowLongPtrW", None) or _user32.SetWindowLongW
    _get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _get_style.restype = ctypes.c_ssize_t
    _set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    _set_style.restype = ctypes.c_ssize_t
else:
    # `inject.py` is not made portable and is not imported: 470 lines of Win32 with no
    # meaning in a body that never types into another window. Its three exports are the
    # only ones this module needs, and each has an honest answer with no hands — there is
    # no foreground to find, nothing of Flow's to recognise, and no paste to warn about.
    def foreground_hwnd() -> int:
        return 0

    def owned_by_flow(_hwnd) -> bool:
        return False

    def take_warnings() -> list[str]:
        return []

    _user32 = _NoHands()

    def _get_style(*_a, **_kw) -> int:
        return 0

    _set_style = _get_style

GWL_EXSTYLE = -20

#: "This window is not what the user is working in."
#:
#: Load-bearing, not cosmetic. Without it a click on the pill makes Flow the foreground
#: window and the target loses it — and `inject.paste()` then asks the OS what has focus
#: *after* the theft, so the Ctrl-V lands on a Tk canvas that ignores it. That is why no
#: prompt had ever arrived via the Send chip. Measured before the fix: both toplevels
#: carried 0x00080088, which is TOPMOST | TOOLWINDOW | LAYERED and nothing else.
WS_EX_NOACTIVATE = 0x08000000


def toplevel_hwnd(win) -> int:
    """The window handle Windows knows about, behind a Tk widget. 0 if there is none yet.

    `winfo_id()` is the *child* HWND — class `TkChild`, carrying its own extended styles
    — so a window style set on it changes nothing anyone can see. The toplevel is its
    parent, class `TkTopLevel`, and that is what holds -topmost, -toolwindow and -alpha.

    Tk creates that parent lazily, at the first `update_idletasks()`, and until then
    there is no parent to find. This returns 0 rather than falling back to the child,
    which is not a nicety: the first version fell back, so the no-activate style was
    written to the child *and read back off the child*, and the read-back that exists
    precisely to catch a call that did nothing agreed that it had worked.
    """
    return _user32.GetParent(win.winfo_id()) or 0


def _no_activate(win) -> bool:
    """Take `win` out of the activation chain, and report whether it took.

    Read back rather than trusted. `SetWindowLongPtr` returns the *previous* style word,
    so a call that did nothing and a call that worked hand back the same plausible
    number, and there is no other way to tell them apart. The one thing this window
    style has to be is true.
    """
    try:
        # The wrapper has to exist before it can be styled, and this is what creates it.
        win.update_idletasks()
        hwnd = toplevel_hwnd(win)
        if not hwnd:
            return False
        _set_style(hwnd, GWL_EXSTYLE, _get_style(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
        return bool(_get_style(hwnd, GWL_EXSTYLE) & WS_EX_NOACTIVATE)
    except (AttributeError, OSError, tk.TclError):
        return False


def _shell_window(win, lite: bool, alpha: float) -> str:
    """Apply the window attributes every Flow window shares, and return its background.

    Two of the five are Windows-only Tk attributes. `-transparentcolor` is what keys the
    magenta out, so without it the keyed colour is not invisible — it is a magenta
    rectangle where the app should be — and `-toolwindow` does not exist off Windows at
    all. Asking for either is a `TclError` before anything is drawn.

    The background is returned rather than left to the caller so a window cannot be given
    one that contradicts what was applied to it.
    """
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", alpha)
    if lite:
        return SHELL
    win.attributes("-transparentcolor", TRANSPARENT)
    win.attributes("-toolwindow", True)
    return TRANSPARENT


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
#: The chip row's height, named because two places need it: `_lay_out` draws the row and
#: `_render` has to keep the note clear of it. It used to be a 26 in one place and a 52
#: in the other, and nothing tied them together — which is how a note came to be drawn on
#: top of the chips the moment it wrapped to a second line.
CHIP_H = 26

#: What Lite says instead of pasting. Both name the same fact from two directions: the
#: draft is on the clipboard and the last step belongs to the user. The second exists
#: because the enter-variant has to be *answered* rather than ignored — a spoken trigger
#: that produces silence reads as the app being broken, which is the report that put the
#: refusals in `session.send()` in the first place.
#:
#: Unicode is fine here and only here: these are drawn by Tk, not printed through
#: `__main__.say`, whose ASCII rule is about a redirected console code page.
COPIED = "copied — paste where you need it"
COPIED_ENTER = "copied — Enter is yours to press"

#: How long the bubble stays up after a dictate-mode Send, holding what was sent.
#:
#: Not `session.AUTO_ASK_SEC`, which is also four seconds and is a different four
#: seconds: that one is how long a settled draft waits before it asks itself, and this
#: is how long words stay recoverable after they have already gone. Either could move
#: without the other, so they do not share a constant.
#:
#: Long enough to read the first line and reach the chip, short enough to be gone before
#: the next sentence is spoken. The number this replaces was zero: the bubble vanished
#: on Send, so a Send that went nowhere looked exactly like one that worked.
SENT_LINGER_SEC = 4.0

#: The help window. Wider than the bubble because it has two columns and does not wrap:
#: a row is one line, so the width is what the widest row costs rather than a taste.
#: `HELP_RIGHT_X` is the gutter both columns are measured against in `help.MAX_*`.
HELP_W = 600
HELP_RIGHT_X = 214
HELP_LINE_H = 19
HELP_GAP_H = 9
#: Extra air above a section heading, so the sections separate without a rule.
HELP_HEAD_TOP = 7
HELP_HEAD_H = HELP_LINE_H + HELP_HEAD_TOP
#: The title band and the chip row, both of which the body scrolls under rather than over.
HELP_HEAD_BAND = 40
HELP_FOOT_BAND = PAD + CHIP_H + PAD
#: Bounded like everything else (invariant 7): the sheet grows with every command added,
#: and a window that grows with it would eventually be taller than the screen. The work
#: area bounds it too, and usually first — measured on this machine, `SPI_GETWORKAREA`
#: reports 1280×672 while the full sheet wants 1025 px, so the fit is decided by the
#: desktop rather than by this number. Scrolling exists for that case; on a display with
#: room, the whole sheet is simply on screen and neither the thumb nor the drag hint
#: appears.
#: Set just above what the whole sheet measures today (1025 px), so a display with the
#: room shows all of it and anything added past that scrolls rather than growing the
#: window off the bottom of the screen.
HELP_MAX_H = 1040
#: Air left around the window inside the work area, so it reads as floating rather than
#: as a panel wedged against the edges.
HELP_MARGIN = 48

#: How long each dot of the indeterminate-wait animation holds.
#:
#: Three dots at this cadence is a 1.2 s cycle — visibly alive without being a strobe,
#: and slow enough that the bubble repaints about 2.5 times a second instead of the 33
#: it would take to redraw every frame of the 30 ms pump. The bubble renders on events
#: and a wait has no events, so the frame is computed and compared before anything is
#: drawn; same discipline as the auto-ask countdown, for the same reason.
DOT_SEC = 0.4


def chip_tag(key: str) -> str:
    """The canvas tag for a chip, from its key.

    Spaces are removed rather than tolerated. Tk parses a `tags` string as a Tcl *list*,
    so `tags="chip-Put it back"` does not tag one item with one name — it tags it with
    three, `chip-Put`, `it` and `back`, and every later `find_withtag` and `tag_bind`
    for the whole name then matches nothing. That is not hypothetical: it is why the
    "Was a command" chip could be drawn and could not be clicked.
    """
    return "chip-" + key.replace(" ", "-")


def _round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle via a smoothed polygon — no image assets, no dependency."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


class Pill(tk.Tk):
    """The always-visible control. Click to arm/disarm, drag to move."""

    #: Declared on the class, not only assigned in `__init__`, and that is load-bearing:
    #: `tk.Misc.__getattr__` forwards an unknown attribute to `self.tk`, so on an instance
    #: built with `__new__` — which is how every UI test fixture in this suite builds one
    #: — a missing name recurses until the stack ends instead of defaulting (item 32 found
    #: exactly this as a `RecursionError`). A class attribute is a real lookup that never
    #: reaches `__getattr__`; `__init__` overrides it per instance.
    lite = False

    def __init__(
        self, session: Session, on_send=None, hotkeys=None, arm=False,
        settings_path=None, lite=False,
    ) -> None:
        scale = _dpi_aware()  # before the first Tk window exists, or it has no effect
        super().__init__()
        self.scale = scale
        self.session = session
        self.on_send = on_send
        self.hotkeys = hotkeys
        #: Lite: no hands (product.md). Set before either child window is built, because
        #: both read it. A plain attribute rather than a `getattr` default at each use —
        #: `tk.Misc.__getattr__` forwards an unknown name to `self.tk`, so a missing one
        #: recurses instead of defaulting (item 32 found this the hard way).
        self.lite = lite
        #: The lexicon actually in use, so the menu opens the folder Flow is reading
        #: rather than the default one — `--lexicon elsewhere.txt` would otherwise send
        #: the user to edit a file nothing loads.
        self.settings_path = (
            Path(settings_path) if settings_path is not None else LEXICON_PATH
        )
        self._arm_on_start = arm
        self.levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self.armed = False
        self._flash = 0  # frames remaining of the error flash
        self._clis: list | None = None  # PATH lookup, deferred and then kept (`_resolved`)
        #: Built on first use, then kept — see `_open_commands`.
        self._help: HelpWindow | None = None
        self._alive = True
        #: The last window that had the foreground and was not Flow's own — where a
        #: Send is aimed. Seeded before any of Flow's windows can take it.
        self.paste_target: int | None = None
        self._track_target()

        self.bg = _shell_window(self, lite, 0.94)
        self.configure(bg=self.bg)

        self.work = _work_area(self.winfo_screenwidth(), self.winfo_screenheight())
        left, top, right, bottom = self.work
        self.x = right - PILL_W - 28
        self.y = bottom - PILL_H - 24
        self.geometry(f"{PILL_W}x{PILL_H}+{self.x}+{self.y}")

        self.canvas = tk.Canvas(
            self, width=PILL_W, height=PILL_H, bg=self.bg, highlightthickness=0
        )
        self.canvas.pack()

        self.bubble = Bubble(self)
        self._bind_drag()
        # add="+", and that is not decoration: `<Button-1>` and `<ButtonPress-1>` are
        # the same Tk event, so binding this one without it replaced the whole binding
        # list and threw away the press handler that records where in the pill it was
        # grabbed. The pill dragged — it just snapped its top-left corner to the cursor
        # first, every time.
        self.canvas.bind("<Button-1>", self._toggle, add="+")
        self.canvas.bind("<Button-3>", self._menu)
        # No <Escape> binding. It used to be here and it could not work once the windows
        # stopped taking focus — a shortcut that silently does nothing is worse than
        # none — so quit moved to the hotkey table, which does not need focus at all.

        # Both windows exist now, which is the earliest either has a handle to set a
        # style on. Reported rather than assumed: see `_no_activate`. Built as a list
        # first because `all()` over a generator stops at the first False — which would
        # mean a pill that failed silently took the bubble down with it, unstyled.
        applied = [_no_activate(win) for win in (self, self.bubble)]
        self.no_activate = all(applied)

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
        """The right-click menu: what is one tap stays one tap, the rest goes inside.

        Two submenus rather than one flat list, because the list had grown past the point
        where anybody scans it — and it grows again with every setting. The split is by
        *how often a tap is the answer*, not by category: mode, the correction offers,
        Send and Clear are things somebody does mid-sentence, so they stay at the top;
        Voice, the CLI, the trigger word and the settings folder are things somebody does
        once, so they go under Settings. Whatever is here is still bounded by the modal
        stall the menu costs (§9), which is why the offers cap at three and this does not
        become a page.

        Not moved and not added: **Was a command**. It is already one tap, as a chip on
        the bubble where the utterance it rescues is on screen — a menu copy would be a
        second control for one action, in the place least connected to what it acts on.
        """
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Send", command=self._send)
        m.add_command(
            label="Converse mode" if self.session.mode == DICTATE else "Dictate mode",
            command=self.session.toggle_mode,
        )
        offered = self._offer_pairs(m)
        m.add_command(label="Clear draft", command=self._clear)
        m.add_separator()
        self._settings_menu(m, offered)
        self._help_menu(m)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit_app)

        # A Tk popup menu on Windows is a native `TrackPopupMenu`, and that runs a modal
        # loop which only receives input while its owner is the foreground window. With
        # WS_EX_NOACTIVATE the pill never becomes the foreground by being clicked, and
        # measured: the menu posted, nothing dismissed it — not Escape, not clicking
        # elsewhere — and `tk_popup` did not return, taking the UI thread with it.
        #
        # So the menu, alone in this app, borrows the foreground and hands it straight
        # back. It is allowed to: the right-click that got us here is the last input
        # event, which is what earns a process the right to call SetForegroundWindow —
        # asking without that click is refused, which is exactly what the first attempt
        # at this did. The style itself stays on; it does not need lifting.
        #
        # Send is unharmed either way. `paste_target` only ever records a window that is
        # not Flow's own, so a menu passing through the foreground cannot become the
        # thing a later paste is aimed at.
        # None of which applies in Lite: `_no_activate` cannot take, so the window is in
        # the activation chain like any other and the popup gets its input the ordinary
        # way. Borrowing a foreground there would be a Win32 call with nothing behind it.
        previous = 0 if self.lite else foreground_hwnd()
        if not self.lite:
            _user32.SetForegroundWindow(toplevel_hwnd(self))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()  # the documented idiom; harmless, and cheap insurance
            if previous:
                _user32.SetForegroundWindow(previous)

    def _settings_menu(self, parent: tk.Menu, offered) -> None:
        """Everything somebody sets once, in one place they can find it twice.

        Still not a settings dialog: every entry here writes to `profile.json` or
        `lexicon.txt`, the two files that were always the settings, and the menu is the
        way to reach them without an editor. What is refused is a *page* — a surface that
        invites options to be added to it.
        """
        sub = tk.Menu(parent, tearoff=0)
        self._trigger_menu(sub)
        # Also the CLI marker's refresh point: a CLI installed mid-session shows up here,
        # where a press is already paying for the PATH walk `_resolved` will not repeat.
        clis = self._clis = available()
        if len(clis) > 1:
            # Offered only when there is a choice to make. Automatic tries them in order,
            # but a fallback only runs after the first one has failed — which for a
            # timeout means paying the whole wait first. Anyone who already knows which
            # CLI is answering today should be able to say so without restarting.
            picker = tk.Menu(sub, tearoff=0)
            current = getattr(self.session, "cli", None)
            here = current.name if current is not None else None

            # Plain commands and a text marker rather than radiobuttons: a Tk variable
            # needs a master and a lifetime, and this menu is rebuilt on every press.
            def choice(label: str, cli) -> None:
                name = cli.name if cli is not None else None
                picker.add_command(
                    label=label + ("   (current)" if name == here else ""),
                    command=lambda c=cli: self.session.set_cli(c),
                )

            choice("Automatic", None)
            for candidate in clis:
                choice(candidate.name, candidate)
            sub.add_cascade(label="Agent CLI", menu=picker)
        self._workspace_menu(sub)
        if getattr(self.session, "speaker", None) is not None:
            sub.add_command(
                label="Mute replies" if not self.session.muted else "Speak replies",
                command=self.session.toggle_speech,
            )
            self._voice_menu(sub)
        if self.session.mode != DICTATE:
            sub.add_command(
                label="Ask only when I press it" if self.session.auto_ask
                else "Ask after a pause",
                command=self.session.toggle_auto_ask,
            )
        if offered:
            never = tk.Menu(sub, tearoff=0)
            for wrong, right in offered:
                never.add_command(
                    label=f"{wrong} → {right}",
                    command=lambda w=wrong, r=right: self._dismiss_pair(w, r),
                )
            sub.add_cascade(label="Never offer", menu=never)
        sub.add_command(label="Open settings folder", command=self._open_settings)
        parent.add_cascade(label="Settings", menu=sub)

    def _trigger_menu(self, parent: tk.Menu) -> None:
        """The word that presses Send, as a list rather than a text box.

        A curated list is the whole design, argued and chosen over the two alternatives:
        free text cannot be measured before it is live, and a spoken setting would write
        config through the accented decoder this product exists to work around. Every
        word here has passed the gate in `tests/test_triggers.py` — 0 hits across 580
        real utterances, `command_bench` unmoved, and no meaning of its own in the
        grammar.

        The enter-variant is derived on every tap, in the safe order, with no special
        case for a word that was already current. One rule is worth more than a clever
        one here, and the note says what was written, so a hand-set `send_enter_word`
        that this replaces is replaced *visibly*.

        `--no-profile` gets no submenu at all: there is nothing to store into, and an
        entry that silently forgets is worse than one that is not there.
        """
        profile = getattr(self.session, "profile", None)
        if profile is None:
            return
        current = getattr(profile, "send_word", SEND_WORD)
        sub = tk.Menu(parent, tearoff=0)
        # Held on self for the reason `_voice_var` is: a Tk variable that goes out of
        # scope stops driving the indicator, and the tick is the answer to "which one am
        # I using".
        self._trigger_var = tk.StringVar(value=current)
        # A word set by hand in profile.json is listed first rather than dropped, so the
        # menu never opens with nothing selected — which would read as no word being set.
        words = list(SEND_WORD_PRESETS)
        if current not in words:
            words.insert(0, current)
        for word in words:
            sub.add_radiobutton(
                label=word, value=word, variable=self._trigger_var,
                command=lambda w=word: self._set_trigger(w),
            )
        parent.add_cascade(label="Trigger word", menu=sub)

    def _set_trigger(self, word: str) -> None:
        """Store the pair, and say what was stored.

        Saved now rather than at the next Send, for the reason `set_voice` gives: a
        choice made just before closing the app is still a choice. Echoed because the
        alternative is a setting that only exists inside a JSON file the owner has said
        they will not open.
        """
        profile = getattr(self.session, "profile", None)
        if profile is None:
            return
        profile.send_word = word
        profile.send_enter_word = enter_word(word)
        # Stored in both bodies and echoed in only one. The enter-variant is derived
        # unconditionally so a profile written in Lite is a full-Flow profile too — but
        # offering it here would be advertising an Enter Lite does not press.
        if profile.save():
            self.bubble.note(f'send: say "{word}"' if self.lite
                             else f'send: say "{word}", or "{enter_word(word)}" to submit')
        else:
            self._flash = 12
            self.bubble.note(f"could not save {profile.path}")

    #: What fits in a menu row. A path is the one label here the user's filesystem
    #: wrote, so it is cut like `edits.removed_text` cuts — and from the *left*,
    #: because a path's discriminating half is its tail.
    WORKSPACE_LABEL_MAX = 60

    #: The "(not set)" row's label *and* its radio value. A stored path can never
    #: equal it: every entry in the list went through `normpath`, and this is not a
    #: path anybody's `--cwd` resolves to.
    WORKSPACE_NOT_SET = "(not set)"

    def _workspace_menu(self, parent: tk.Menu) -> None:
        """Where questions are asked from, as a list of places already chosen.

        Recents rather than a browse dialog or a text field: a path typed into a
        dialog is free text with separators, and the no-settings-dialog stance stands.
        New paths enter once, via `--cwd`; after that they are a tap. "(not set)" is a
        real entry because running without a project is a real choice, and the switch
        itself — thread cleared, note saying so — is the session's
        (`Session.set_workspace`), so the menu stays a dispatcher like the CLI picker.

        A current workspace missing from the list is shown at the top rather than
        dropped — the hand-set trigger word's rule, for the same reason: the menu must
        never open with nothing ticked. A folder that is gone is shown and marked
        rather than hidden (a project on a detached drive is still a place the user
        knows); the tap on it is refused with the reason, one layer down.

        No profile, or nothing to offer, means no submenu: there is nothing to switch
        between, and an entry that silently forgets is worse than one that is absent.
        """
        profile = getattr(self.session, "profile", None)
        if profile is None:
            return
        current = getattr(self.session, "workspace", None)
        recents = list(getattr(profile, "workspaces", ()) or ())
        if current and all(path_key(w) != path_key(current) for w in recents):
            recents.insert(0, current)
        if not recents:
            return
        sub = tk.Menu(parent, tearoff=0)
        # Held on self for the reason `_voice_var` is: a Tk variable that goes out of
        # scope stops driving the tick, and the tick is the answer to "which one".
        # The no-workspace value is the label itself, never "": measured on real Tk,
        # an empty radiobutton -value is read as *unset* and falls back to the label,
        # so a var holding "" matches no row and the tick silently never draws.
        self._workspace_var = tk.StringVar(value=current or self.WORKSPACE_NOT_SET)
        for w in recents:
            label = (w if len(w) <= self.WORKSPACE_LABEL_MAX
                     else "…" + w[-(self.WORKSPACE_LABEL_MAX - 1):])
            if not Path(w).is_dir():
                label += "  (missing)"
            sub.add_radiobutton(
                label=label, value=w, variable=self._workspace_var,
                command=lambda p=w: self.session.set_workspace(p),
            )
        sub.add_radiobutton(
            label=self.WORKSPACE_NOT_SET, value=self.WORKSPACE_NOT_SET,
            variable=self._workspace_var,
            command=lambda: self.session.set_workspace(None),
        )
        parent.add_cascade(label="Workspace", menu=sub)

    #: The "Engine default" row's label *and* its radio value, the workspace sentinel's
    #: shape for the workspace sentinel's reason: never "", because on real Tk an empty
    #: radiobutton -value reads back as the *label* — Tk treats it as unset and falls
    #: back — so a var holding "" matches no row and the tick silently never draws. A
    #: voice name cannot equal it: every named row's value is an engine's installed
    #: voice name, and those name a person, not a fallback.
    VOICE_ENGINE_DEFAULT = "Engine default"

    def _voice_menu(self, parent: tk.Menu) -> None:
        """A submenu of the voices this machine actually has.

        Listed rather than cycled: "next voice" is unusable when the good one is fourth
        of nine, and the whole reason this exists is that the engine's default is the
        oldest voice on the box and nobody had ever chosen it. A tick marks the one in
        use, so the answer to "which am I hearing" is on screen and not in a log line
        that scrolled away at startup.
        """
        voices = self.session.voices()
        if not voices:
            return
        sub = tk.Menu(parent, tearoff=0)
        # Read from the engine and rebuilt on every open, so it cannot drift from a
        # voice set by --voice or by a profile written in another session. Held on self
        # because a Tk variable that goes out of scope stops driving the indicator.
        self._voice_var = tk.StringVar(
            value=getattr(self.session.speaker, "voice", None)
            or self.VOICE_ENGINE_DEFAULT
        )
        sub.add_radiobutton(
            label=self.VOICE_ENGINE_DEFAULT, value=self.VOICE_ENGINE_DEFAULT,
            variable=self._voice_var,
            command=lambda: self.session.set_voice(None),
        )
        sub.add_separator()
        for v in voices:
            sub.add_radiobutton(
                label=v.describe(), value=v.name, variable=self._voice_var,
                command=lambda name=v.name: self.session.set_voice(name),
            )
        parent.add_cascade(label="Voice", menu=sub)

    def _copy(self, text: str) -> str:
        """Lite's way out: the draft onto the clipboard. Returns what went wrong, or "".

        Tk's own clipboard rather than `inject`'s Win32 one — it is the same three
        declared dependencies on every OS, and it is the whole of Lite's handoff.

        `update_idletasks`, not `update`: Tk owns the selection while the interpreter
        lives and the copy has to be flushed out to the OS, but a full `update` from
        inside `_tick` would service the pending `after` callbacks and re-enter the frame
        pump. Idle tasks are what needs draining here, and they are not timers.
        """
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
        except tk.TclError as exc:
            return f"could not copy: {exc}"
        return ""

    def _send(self, submit: bool = False) -> None:
        """R5: hand the draft over, and leave it recoverable either way.

        `submit` presses Enter after the paste, and arrives only from the spoken
        Send-then-Enter trigger — no chip and no hotkey can set it.

        **In Lite it collapses.** The plain trigger copies, and the enter-variant copies
        too and says what did not happen. Refusing it was the alternative and it is wrong
        on `edits.enter_word`'s own argument: a decode that drops a word from "enter
        boom" yields "boom", so a refusing enter-variant would make the degraded decode
        the working case and the fuller utterance the broken one — the exact inversion
        the word order exists to prevent.
        """
        text = self.session.send()
        problem = ""
        if text and self.lite:
            problem = self._copy(text)
        elif text and self.on_send:
            # The window is chosen here, on the UI thread, from what was polled before
            # the click — not inside `paste()` after it. The handler reports back what
            # went wrong rather than printing it somewhere nobody is looking.
            #
            # Passed only when it is true, the way `DecodeWorker` passes `hotwords`: a
            # handler predating this — `send_check.py`'s fixture is one — still works.
            extra = {"submit": True} if submit else {}
            problem = self.on_send(text, self.paste_target, **extra) or ""
        if getattr(self.session, "mode", DICTATE) != DICTATE:
            # Converse: send() returns "" and the answer is still coming, so the bubble
            # stays up to render it and there is nothing to linger over.
            return
        if problem:
            # Flashed whether the paste failed outright or merely could not be
            # guaranteed. A terminal that will run each line as it arrives is the
            # loudest thing Flow can cause, so both deserve to be looked at.
            self._flash = 40
            self.bubble.show_sent(text, problem)
        elif text:
            self.bubble.show_sent(text)
            if self.lite:
                # After the card, not instead of it: the words are the important half and
                # the note is what tells somebody the last step is theirs.
                self.bubble.note(COPIED_ENTER if submit else COPIED)
        # Nothing else: an empty `text` means send() refused and said why in a note, and
        # hiding the bubble here is what used to take that explanation off the screen.

    def _offer_pairs(self, m: tk.Menu) -> list[tuple[str, str]]:
        """Words Flow keeps seeing corrected, offered for the user to declare.

        Never silent. An inferred pair is a guess from a word-level diff, and turning
        one into a substitution on its own would be Flow rewriting speech on evidence
        it collected about itself. What the owner said is the other half: "unless it is
        exposed to UI right click … i will not be able to use it" — so the boundary
        stays and the typing goes. One tap on the offer declares it.

        "Never" gets a submenu rather than a second tap on the offer, because the tap
        that matters is the one that says yes — and it now sits under Settings, one
        level away from the offer itself, for the same reason: saying no is a decision
        somebody makes once, and saying yes is the one this menu is for.

        Returns what it offered, so Settings can build the matching "Never" list without
        reading the profile a second time.
        """
        profile = getattr(self.session, "profile", None)
        if profile is None:
            return []  # --no-profile: nothing was learned, so nothing is offered
        # Everything that reads state is inside the guard, and the guard is wide on
        # purpose. This runs on the UI thread from a right-click binding, *not* from
        # `_tick` — so `_tick`'s catch cannot reach it, and an exception here would take
        # out the menu, which is how somebody reaches Quit. Offers are the least
        # important thing in it.
        try:
            try:
                declared = pairs(Path(self.settings_path).read_text(encoding="utf-8"))
            except OSError:
                declared = []  # no file yet is the normal case, not a failure
            offers = profile.offered_pairs(declared=declared)
        except Exception as exc:
            self.bubble.note(f"could not read the corrections: {exc}")
            return []
        for wrong, right in offers:
            m.add_command(
                label=f"Add correction:  {wrong} → {right}",
                command=lambda w=wrong, r=right: self._declare_pair(w, r),
            )
        return offers

    def _declare_pair(self, wrong: str, right: str) -> None:
        """Write the arrow line the user has just agreed to."""
        reason = append_pair(self.settings_path, wrong, right)
        self.bubble.note(reason if reason
                         else f"correction added: {wrong} → {right}")

    def _dismiss_pair(self, wrong: str, right: str) -> None:
        profile = getattr(self.session, "profile", None)
        if profile is None:
            return
        profile.dismiss_pair(wrong, right)
        # Saved now rather than at the next Send, for the reason `set_voice` gives: a
        # choice made just before closing the app is still a choice.
        profile.save()
        self.bubble.note(f"not offering {wrong} → {right} again")

    def _open_settings(self) -> None:
        """Show the folder Flow reads, with a lexicon file in it to type into.

        A settings *folder*, not a settings dialog. Everything the user can set is
        already two hand-editable files — the lexicon and profile.json — and the whole
        gap was that nobody could find them. Explorer is the editor, `os.startfile` is
        the whole implementation, and R16 keeps its three dependencies.

        The file is written first because an empty folder answers none of the questions
        that brought someone here; the template's comments are the documentation for a
        format that is otherwise invisible.
        """
        folder = self.settings_path.parent
        try:
            created = ensure_lexicon(self.settings_path)
            open_path(folder)
        except OSError as exc:
            # A locked profile directory, or a shell with no handler for a folder. Said
            # on screen: the menu item did nothing visible, and there is no other place
            # a user would look.
            self._flash = 12
            self.bubble.note(f"could not open {folder}: {exc}")
            return
        if created:
            self.bubble.note(
                f"created {self.settings_path.name} - the comments in it say what "
                "each kind of line does"
            )

    def _help_menu(self, parent: tk.Menu) -> None:
        """Help — a sheet about this machine, and the guide about the product.

        Nothing in the app named a single command or the hotkey that arms the mic, which
        was the first thing asked for once other people had it. Two entries rather than
        one because they answer different questions: what does *this* copy do right now,
        and what is this thing.
        """
        sub = tk.Menu(parent, tearoff=0)
        sub.add_command(label="Commands & shortcuts", command=self._open_commands)
        sub.add_command(label="Open the guide", command=self._open_guide)
        parent.add_cascade(label="Help", menu=sub)

    def _open_commands(self) -> None:
        """Regenerate the sheet for this machine, and show it in Flow's own window.

        Regenerated on every open, not cached, and that is the feature: the combos are
        the ones `RegisterHotKey` accepted this launch rather than the first alternative
        in the table, and the trigger words are the ones stored rather than the ones
        shipped. A cached render is the stale help file this replaced, one surface along.

        The workshop line is worded by `resolve_workspace`, the same function the startup
        line uses, and it is asked about the path the *session* holds — `--cwd` outranks
        the profile and never reaches it.

        The window is built on first use rather than at launch. Nothing else needs it,
        and a second `Toplevel` costs a handle and a paint on a path most sessions never
        take.
        """
        # `self._help`, never `getattr(self, "_help", None)`. `tk.Misc.__getattr__`
        # forwards an unknown attribute to `self.tk`, so on an instance whose `__init__`
        # has not run the "safe" default-getattr looks up `tk`, misses, looks up `tk`
        # again, and dies of recursion rather than returning the default. `__init__` sets
        # this; a straight read is both correct and the one that fails legibly.
        if self._help is None:
            self._help = HelpWindow(self)
        self._help.show(help_rows(
            hotkeys=self.hotkeys,
            send_words=self.session.send_words,
            workspace_note=resolve_workspace(
                getattr(self.session, "workspace", None), None
            )[1],
            lite=self.lite,
        ))

    def _open_guide(self) -> None:
        try:
            open_guide()
        except OSError as exc:
            self._flash = 12
            self.bubble.note(f"could not open the guide: {exc}")

    def _clear(self) -> None:
        # Clear is the cheapest "stop" the user has, and with the microphone gated while
        # Flow talks it is one of the few ways left to cut a reply short. Doing that
        # first means one press does the obvious thing whichever is in progress.
        self.session.stop_speaking()
        self.session.draft.clear()
        self.bubble.hide()

    def quit_app(self) -> None:
        # Cleared before anything is torn down, so a `_tick` already in flight does not
        # re-arm itself against a destroyed interpreter on its way out.
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
            if self._alive:
                self.after(30, self._tick)

    def _track_target(self) -> None:
        """Remember the last window that had the foreground and was not Flow's own.

        Two cheap user-mode calls per frame, and the reason Send can be aimed at all:
        by the time `paste()` runs, the click that started it has had its chance to move
        the foreground. This is the same question asked 30 ms earlier, and filtered.

        Lite has no target-window awareness (product.md), so it does not ask. Gated on
        `lite` rather than on the platform, which is what makes `--lite` here the same
        code a Mac runs instead of a rehearsal of it.
        """
        if self.lite:
            return
        hwnd = foreground_hwnd()
        if hwnd and not owned_by_flow(hwnd):
            self.paste_target = hwnd

    def _frame(self) -> None:
        self._track_target()

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
                elif name == "quit":
                    self.quit_app()
                    return

        if self.armed:
            self.session.tick()
            if getattr(self.session, "hearing", True):
                self.levels.append(self._norm(self.session.level_db))
            else:
                self._flatten()
        else:
            # Still collect what the CLI owes us. Disarming used to strand an answer
            # that was already on its way — the pill went quiet and nothing ever
            # arrived, because the code that collects a reply sat behind this check.
            self.session.pump_results()
            self.levels.append(0.0)

        self._pump_warnings()
        for ev in self.session.events():
            if ev.kind == "draft":
                if ev.text:
                    self.bubble.show(ev.text)
                elif self.session.state is State.ASKING:
                    # Asking clears the draft, and hiding here left the user staring
                    # at nothing for the ten seconds the CLI takes. Keep the bubble up
                    # so "asking..." is somewhere to be seen.
                    self.bubble.show_reply("")
                elif not self.bubble.showing_sent:
                    self.bubble.hide()
                # The other way the draft empties is Send, which puts the words on the
                # sent card in the same breath. Hiding on that event is what used to
                # take them straight back off the screen.
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
            elif ev.kind == "send":
                # A spoken trigger. Handled here rather than in the session because the
                # paste belongs to this thread and to `paste_target` — the same button
                # the chip presses, arrived at by a different route.
                self._send(submit=ev.text == "enter")
            elif ev.kind == "drop":
                # Shown, not hidden: P2 is that a rejection is never silent. The
                # recovery affordance itself is Phase 3's rescue chip.
                self.bubble.note(ev.text)

        self.bubble.tick_countdown()
        self.bubble.tick_activity()
        self.bubble.tick_sent()
        if self._flash:
            self._flash -= 1
        self._draw()

    def _pump_warnings(self) -> None:
        """Surface inject warnings that arrived since the last frame.

        `on_send` drains the synchronous ones and puts them on the sent card, where
        they belong to the Send that raised them. This drain exists for the one that
        cannot be there: the clipboard-restore thread records its skip 0.6 s after
        `paste()` returned, and before this it sat in the queue until the *next* Send
        drained it — shown, but against the wrong paste. Per-frame, the line lands
        while the card for its own Send is still on screen.
        """
        for line in take_warnings():
            self._flash = 12
            self.bubble.note(line)

    def _flatten(self) -> None:
        """Drop the meter to a flat line in one frame.

        `Session.level_db` already reports silence while Flow is talking, so appending
        it would get here eventually — but "eventually" is eighteen frames, and for over
        half a second the meter would still be sliding Flow's own voice out to the left
        while claiming to hear someone. A lie with a decay curve is still a lie.
        """
        for i in range(BARS):
            self.levels[i] = 0.0

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

    #: What fits beside the level bars. The baseline is at y 33 and the bars run to
    #: y 32 from x 40, so a wider token overlaps them rather than being clipped —
    #: `codex` and `claude` are 5 and 6, and anything longer falls back to the mode.
    MARKER_MAX = 6

    def _resolved(self) -> list:
        """The agent CLIs on PATH, looked up once.

        `Session._provider` says `available()` is cheap *because it is only reached from
        note paths*, and this is the caller that breaks that: `_draw` runs every 30 ms.
        Measured on this machine, `available()` is **10.2 ms** — 34% of a frame, twice a
        PATH walk across every `PATHEXT` entry. Installing a CLI while Flow is running is
        rare and already needs a menu press to select; `_menu` re-resolves there, which is
        a user action paying for its own lookup.
        """
        if self._clis is None:
            self._clis = available()
        return self._clis

    def _marker(self) -> str:
        """The CLI that would answer an Ask, or the mode when none would.

        Reads the pin first: `set_cli` is what makes a wedged CLI recoverable without a
        restart, and a marker still naming the one it was taken off would be the pin's
        only visible effect being wrong.
        """
        pinned = getattr(self.session, "cli", None)
        found = self._resolved()
        cli = pinned if pinned is not None else (found[0] if found else None)
        if cli is None:
            return "ASK"
        name = cli.name.lower()
        return name if len(name) <= self.MARKER_MAX else "ASK"

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
        # spoken reply" and "I was never in converse mode" look identical. The slot is
        # drawn either way, so naming the CLI in it costs no pixels — and the note that
        # says the question leaves the machine only appears at the mode switch, which is
        # the wrong moment to still be reading it.
        if getattr(self.session, "mode", DICTATE) != DICTATE:
            c.create_text(
                cx, PILL_H - 7, text=self._marker(), fill=accent,
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


class HelpWindow(tk.Toplevel):
    """Commands & shortcuts, drawn by Flow instead of handed to Notepad.

    This used to write `~/.flow/commands.txt` and shell out to it. The owner's verdict
    was three words — "which is not help" — and the three reasons behind it are all
    structural: Notepad is another application's chrome around Flow's content, opening it
    takes the foreground that 96 Win32 call sites exist to protect, and it leaves a file
    in the settings folder that looks editable sitting beside one that is. The generated
    data did not change and neither did its guarantees; only the surface did.

    **Read-only and mouse-only, and that follows from the window rather than from taste.**
    It carries `WS_EX_NOACTIVATE` like every other window here, so it can never hold the
    keyboard — which means it must never be given anything that needs one. A Close chip
    in the bubble's idiom and a scrolling body are the whole interaction.

    **Two ways to scroll, and the second one is not redundancy.** On Windows
    `WM_MOUSEWHEEL` is posted to the *focused* window, and this window is never focused;
    the wheel reaches it only through "Scroll inactive windows when I hover over them",
    which is a default a user can switch off. That is the same shape as the two defects
    this file already carries — the `Esc` binding that could not fire once the windows
    stopped taking focus, and the popup menu that received nothing until it borrowed the
    foreground — so the body also scrolls by press-and-drag, which is delivered by
    hit-test and cannot depend on focus. The footer names the drag only when there is
    something below the fold to reach.

    The body scrolls by whole rows rather than by pixels. Nothing is clipped that way: a
    row is either drawn or it is not, so scrolled text can never appear under the title
    or over the chip, and no overpainting is needed to hide it.
    """

    def __init__(self, pill: Pill) -> None:
        super().__init__(pill)
        self.pill = pill
        self.bg = _shell_window(self, pill.lite, 0.0)
        self.configure(bg=self.bg)
        self.canvas = tk.Canvas(self, bg=self.bg, highlightthickness=0)
        self.canvas.pack()
        #: Reported rather than assumed, exactly as the pill and bubble do it: a style
        #: that failed to apply would give this window the focus the moment it opened,
        #: and take it from whatever the user was typing in.
        self.no_activate = _no_activate(self)
        self._rows: list[tuple[str, str, str]] = []
        self._top = 0  # index of the first row drawn
        self._drag_y: int | None = None
        self._drag_px = 0
        self._h = 200
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-1>", self._grab)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.withdraw()

    # -- content -----------------------------------------------------------

    def show(self, rows) -> None:
        """Replace what is shown and bring the window up, back at the top.

        Replaced on every open rather than kept: the combos, the trigger words and the
        workshop are read at the moment the menu is tapped, and a window that reused the
        last render would be the stale help file this replaced, one surface along.
        """
        self._rows = list(rows)
        self._top = 0
        self._render()
        self.deiconify()
        self.attributes("-alpha", 0.97)

    def close(self) -> None:
        self.withdraw()

    @property
    def showing(self) -> bool:
        return bool(self.winfo_exists() and self.state() != "withdrawn")

    # -- scrolling ---------------------------------------------------------

    @staticmethod
    def _row_h(kind: str) -> int:
        return {"gap": HELP_GAP_H, "head": HELP_HEAD_H}.get(kind, HELP_LINE_H)

    def _view_h(self) -> int:
        return self._h - HELP_HEAD_BAND - HELP_FOOT_BAND

    def _max_top(self) -> int:
        """The furthest first-row index that still fills the view.

        Walked from the end so the last row can always be reached and the body never
        scrolls into empty space below itself.
        """
        height = 0
        for i in range(len(self._rows) - 1, -1, -1):
            height += self._row_h(self._rows[i][0])
            if height > self._view_h():
                return min(i + 1, len(self._rows) - 1)
        return 0

    def _scroll(self, rows: int) -> None:
        top = max(0, min(self._top + rows, self._max_top()))
        if top != self._top:
            self._top = top
            self._render()

    def _wheel(self, e) -> None:
        # Three rows a notch, the Windows default. Delivered only when the OS is
        # forwarding the wheel to the hovered window; see the class docstring.
        self._scroll(-3 * (e.delta // 120 or (1 if e.delta > 0 else -1)))

    def _grab(self, e) -> None:
        self._drag_y, self._drag_px = e.y, 0

    def _drag(self, e) -> None:
        if self._drag_y is None:
            return
        self._drag_px += self._drag_y - e.y
        self._drag_y = e.y
        # Content follows the hand: dragging up moves the page up, which is the direction
        # every touch surface has taught. Whole rows, so the accumulator keeps the
        # remainder rather than dropping it and making a slow drag do nothing.
        steps, self._drag_px = divmod(self._drag_px, HELP_LINE_H)
        if steps:
            self._scroll(steps)

    # -- painting ----------------------------------------------------------

    def _render(self) -> None:
        c = self.canvas
        accent = self.pill.accent
        content = sum(self._row_h(kind) for kind, _l, _r in self._rows)
        _l, top, _r, bottom = self.pill.work
        self._h = min(HELP_HEAD_BAND + content + HELP_FOOT_BAND, HELP_MAX_H,
                      max(200, bottom - top - HELP_MARGIN))
        c.configure(width=HELP_W, height=self._h)
        self._place()

        c.delete("all")
        _round_rect(c, 1, 1, HELP_W - 1, self._h - 1, 14, fill=SHELL, outline=accent)
        c.create_text(PAD, PAD + 2, anchor="nw", text=HELP_TITLE, fill=TEXT,
                      font=("Segoe UI", 11, "bold"))

        y, floor = HELP_HEAD_BAND, self._h - HELP_FOOT_BAND
        drawn = self._top
        for kind, left, right in self._rows[self._top:]:
            h = self._row_h(kind)
            if y + h > floor:
                break
            if kind == "head":
                c.create_text(PAD, y + HELP_HEAD_TOP, anchor="nw", text=left,
                              fill=accent, font=("Segoe UI", 10, "bold"))
                if right:
                    c.create_text(HELP_RIGHT_X, y + HELP_HEAD_TOP + 2, anchor="nw",
                                  text=right, fill=MUTED, font=("Segoe UI", 8))
            elif kind == "pair":
                c.create_text(PAD, y, anchor="nw", text=left, fill=TEXT,
                              font=("Segoe UI", 10))
                if right:
                    c.create_text(HELP_RIGHT_X, y + 2, anchor="nw", text=right,
                                  fill=MUTED, font=("Segoe UI", 9))
            elif kind == "note":
                c.create_text(PAD, y, anchor="nw", text=left, fill=MUTED,
                              font=("Segoe UI", 9))
            y += h
            drawn += 1

        self._scrollbar(drawn)
        self._footer(drawn)

    def _place(self) -> None:
        """Centred in the work area, clamped inside it.

        Not anchored to the pill like the bubble: the pill lives in a corner and this is
        three times the height, so anchoring would push it off the edge on the one
        display it has to work on.
        """
        left, top, right, bottom = self.pill.work
        x = left + ((right - left) - HELP_W) // 2
        y = top + ((bottom - top) - self._h) // 2
        self.geometry(f"{HELP_W}x{self._h}+{max(left, x)}+{max(top, y)}")

    def _scrollbar(self, drawn: int) -> None:
        """A thumb, only when there is something off screen to point at."""
        if self._top == 0 and drawn >= len(self._rows):
            return
        c = self.canvas
        x = HELP_W - 9
        y1, y2 = HELP_HEAD_BAND, self._h - HELP_FOOT_BAND
        c.create_rectangle(x, y1, x + 3, y2, fill=CHIP, outline="")
        span = max(1, len(self._rows))
        shown = max(1, drawn - self._top)
        height = max(24, int((y2 - y1) * shown / span))
        offset = int((y2 - y1 - height) * self._top / max(1, span - shown))
        c.create_rectangle(x, y1 + offset, x + 3, y1 + offset + height,
                           fill=MUTED, outline="")

    def _footer(self, drawn: int) -> None:
        """The Close chip, and the hint that says the drag exists.

        The hint is conditional on purpose. Advice about scrolling on a window with
        nothing below the fold is noise, and it is the second thing somebody reads.
        """
        c = self.canvas
        label = "Close"
        w = 20 + 7 * len(label)
        y2 = self._h - PAD
        y1 = y2 - CHIP_H
        tag = chip_tag(label)
        _round_rect(c, PAD, y1, PAD + w, y2, 13, fill=CHIP, outline="", tags=tag)
        c.create_text(PAD + w / 2, (y1 + y2) / 2, text=label, fill=TEXT,
                      font=("Segoe UI", 9, "bold"), tags=tag)
        c.tag_bind(tag, "<Button-1>", lambda _e: self.close())
        if self._top or drawn < len(self._rows):
            c.create_text(PAD + w + 12, (y1 + y2) / 2, anchor="w",
                          text="scroll, or drag the page, for the rest",
                          fill=MUTED, font=("Segoe UI", 8))


class Bubble(tk.Toplevel):
    """The draft, floated above the pill (R14) with Refine / Continue / Send (R15)."""

    #: Copied from the pill at construction rather than read back off it, for the reason
    #: the class attribute exists at all: `self.pill` is a `Mock` in several fixtures, and
    #: `mock.lite` is a truthy Mock — so a bubble that asked its parent each time would
    #: quietly run every Lite branch in tests that are about the full body. Same class-
    #: attribute default as `Pill.lite`, and for the same `__getattr__` reason.
    lite = False

    def __init__(self, pill: Pill) -> None:
        super().__init__(pill)
        self.pill = pill
        self.lite = pill.lite
        self.bg = _shell_window(self, pill.lite, 0.0)
        self.configure(bg=self.bg)
        self.canvas = tk.Canvas(self, bg=self.bg, highlightthickness=0)
        self.canvas.pack()
        self._visible = False
        self._text = ""
        self._note = ""
        self._partial = ""
        self._reply = ""
        #: What Send just handed over, and when. Held for `SENT_LINGER_SEC` so the words
        #: are still on screen — and still recoverable — when a Send goes wrong.
        self._sent = ""
        self._sent_at = 0.0
        #: Last linger second painted, so the countdown repaints once a second and not
        #: 33 times. Same discipline as `_countdown`.
        self._sent_left: int | None = None
        #: Last auto-ask second painted, so the countdown repaints once a second
        #: rather than on every frame.
        self._countdown: int | None = None
        #: The indicator, and the exact frame of it last painted. Compared before any
        #: repaint, for the same reason `_countdown` is.
        self._act = None  # session.Activity | None
        self._frame_key: str | None = None
        self._dot = 0
        #: True when the bubble is on screen *only* to carry the indicator, so a wait
        #: that ends with nothing to show takes its window away again rather than
        #: leaving an empty card behind.
        self._for_activity = False
        #: Which float-up animation is current; older ones stop when this moves.
        self._anim = 0
        #: The hand editor, while one is open, and the window to give the foreground
        #: back to when it closes — which is never Flow's own, by `_track_target`.
        self._editor: tk.Text | None = None
        self._previous_focus = 0
        self._h = 120
        self.withdraw()

    # -- content -----------------------------------------------------------

    @property
    def showing_sent(self) -> bool:
        """True while the bubble is holding the words Send just handed over."""
        return bool(self._sent)

    def show_reply(self, text: str) -> None:
        """P9: the CLI's answer. Clears the draft area — the question was sent.

        An empty `text` means "the question has gone, the answer is still coming":
        keep the bubble up and leave whatever is there, so the wait is visible.
        """
        self._text, self._partial, self._sent = "", "", ""
        if text:
            self._reply = text
        self._for_activity = False
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()
        self._render()

    def show_sent(self, text: str, problem: str = "") -> None:
        """R5/P6: what just left, and a way to get it back.

        The bubble used to be withdrawn the instant Send was pressed, which made the two
        outcomes identical to look at: a prompt that landed in the editor and a prompt
        that landed nowhere both ended with an empty screen. Now the words stay put for
        `SENT_LINGER_SEC` with a chip that returns them to the draft, so a mis-aimed
        Send costs one click instead of the whole utterance.

        `problem` is what the paste refused with. There is no version of this where the
        refusal is silent — that is invariant 5 — so it is shown on the same card as the
        words it failed to deliver.
        """
        self._sent, self._sent_at, self._sent_left = text, time.perf_counter(), None
        self._text = self._partial = ""
        self._for_activity = False
        if problem:
            self._note = problem
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()
        self._render()

    def show(self, text: str) -> None:
        if self._editor is not None:
            # Something landed behind the editor — a decode that was already running, a
            # rewrite coming back. Redrawing here would move the words under the cursor
            # mid-keystroke. The commit displaces it and says so, and it is one undo
            # back; that is the honest order.
            return
        # The answer stays up while the next question is dictated. It used to be
        # cleared the moment the user spoke again, which meant the reply they had just
        # asked for vanished before they could read it.
        self._text, self._partial, self._sent = text, "", ""
        self._for_activity = False
        self._render()
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()

    def show_partial(self, text: str) -> None:
        # Partials are dimmed: they contain hallucinated fragments on mid-word
        # boundaries, so "not final yet" has to be visible.
        self._partial, self._sent = text, ""
        self._for_activity = False
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
        self._for_activity = False
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._float_up()
        self._render()

    def hide(self) -> None:
        # Clear and the cancel hotkey both come through here, and an editor left open
        # would leave `session.editing` true with the window gone — a microphone that
        # is off with nothing on screen to say why. Cancelled rather than committed:
        # the press that got here was somebody stopping, not somebody finishing.
        if self._editor is not None:
            self._cancel_edit()
        self._visible = False
        self._text = self._partial = self._note = self._reply = self._sent = ""
        self._for_activity = False
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
        # The sent card takes the body slot: it is the same words in the same place,
        # which is what makes "that went to the wrong window" readable at a glance.
        body = self._sent or self._text
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
        # The note gets measured too, and did not until 2026-08-02. It reserved a flat
        # 18 px — one line — and drew at a fixed offset from the foot with `anchor="nw"`,
        # so every line past the first grew *downward* into the chip row. An Ask that
        # failed on a Hyper-V VM put its reason across Refine / Continue / Ask and the
        # owner could read neither. Errors are the longest strings this ever shows and
        # the ones it is least acceptable to hide.
        note_h = 0
        if self._note:
            nprobe = c.create_text(
                PAD, PAD, anchor="nw", text=self._note, fill=MUTED,
                font=("Segoe UI", 8), width=BUBBLE_W - 2 * PAD,
            )
            nx1, ny1, nx2, ny2 = c.bbox(nprobe)
            note_h = ny2 - ny1
        # The box gets a floor of its own: a one-line draft measures ~18 px, and a
        # text box that size is a slot to squint into rather than something to work in.
        edit_h = max(text_h + 8, 44) if self._editor is not None else 0
        extra = reply_h
        if edit_h:
            extra += edit_h - text_h + 8
        if self._sent:
            extra += 16  # the "sent" label above the words
        if self._partial:
            extra += 34
        if self._act is not None:
            extra += 20
        if self._note:
            extra += note_h + 4
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
        if self._sent:
            c.create_text(
                PAD, y, anchor="nw", text="sent", fill=MUTED,
                font=("Segoe UI", 8, "bold"), tags="sent",
            )
            y += 16
        if self._editor is not None:
            # The box takes the body's slot rather than opening below it, so the words
            # do not move under the cursor at the moment somebody reaches for them.
            c.create_window(
                PAD, y, anchor="nw", window=self._editor,
                width=BUBBLE_W - 2 * PAD, height=edit_h,
            )
            y += edit_h + 6
        elif body:
            # Muted once it has gone: these are no longer the words being worked on.
            c.create_text(
                PAD, y, anchor="nw", text=body, fill=MUTED if self._sent else TEXT,
                font=("Segoe UI", 10), width=BUBBLE_W - 2 * PAD,
            )
            y += text_h + 6
        if self._partial:
            c.create_text(
                PAD, y, anchor="nw", text=self._partial, fill=MUTED,
                font=("Segoe UI", 9, "italic"), width=BUBBLE_W - 2 * PAD,
            )
            y += 28
        if self._act is not None:
            # In the flow of the text rather than pinned to the foot: it belongs to what
            # is being waited on, and the note below is about what already happened.
            self._indicator(y)
            y += 20
        if self._note:
            # Anchored to its own bottom edge, four pixels clear of the chip row, and
            # derived from the row's geometry rather than restating it: the old `52` and
            # `_lay_out`'s `PAD + CHIP_H` were two numbers that had to agree and nothing
            # made them. `sw` is what makes a second line grow up into the space the
            # measurement above just reserved, instead of down onto the chips.
            c.create_text(
                PAD, self._h - PAD - CHIP_H - 4, anchor="sw", text=self._note,
                fill=MUTED, font=("Segoe UI", 8), width=BUBBLE_W - 2 * PAD,
            )

        self._chips()

    def _chips(self) -> None:
        # (key, label, command). The key becomes the canvas tag and the label is what is
        # drawn, and they are separate because two chips carry a countdown: tagging by
        # the visible text would rename the tag every second, so the click binding and
        # anything looking for it — the self-drive harness included — would chase a name
        # that no longer exists. `chip_tag` is how a key with spaces in it survives.
        c = self.canvas
        if self._sent:
            # One thing to offer, because there is one thing left to decide: whether
            # those words needed to come back. Refine and Continue have nothing to act
            # on — the draft is empty — and Send has already happened.
            specs = [("Put it back", f"Put it back {self._linger_left()}s",
                      self._put_back)]
            self._lay_out(specs)
            return
        if getattr(self.pill.session, "editing", False):
            # The whole row, because every other chip acts on a draft that is currently
            # two things at once — what the session holds and what is in the box. One
            # decision to make, so one pair of chips to make it with.
            self._lay_out([
                ("Done", "Done", self._commit_edit),
                ("Cancel", "Cancel", self._cancel_edit),
            ])
            return
        specs = [
            ("Refine", "Refine", self._refine),
            ("Continue", "Continue", self._continue),
        ]
        # Only with words on screen: an editor over an empty draft is a text box for
        # dictating with a keyboard, which is a different product.
        if self._text:
            specs.append(("Edit", "Edit", self._edit))
        # Only offered when there is something to re-read. A chip that is always
        # present but usually does nothing teaches people to ignore it.
        if getattr(self.pill.session, "can_rescue", False):
            specs.append(("Was a command", "Was a command", self._was_a_command))
        # Same gating, same reason: only while an answer is on screen to take.
        if self._reply and getattr(self.pill.session, "can_take_reply", False):
            specs.append(("Use this", "Use this", self._take_reply))
        if getattr(self.pill.session, "mode", DICTATE) != DICTATE:
            # The countdown lives on the button it is going to press. Anywhere else it
            # is just a timer running somewhere on screen; here it says which action is
            # about to happen and how long there is to stop it.
            left = getattr(self.pill.session, "auto_ask_in", None)
            specs.append(
                ("Ask", "Ask" if left is None else f"Ask {int(left) + 1}s",
                 self.pill._send)
            )
        else:
            specs.append(("Send", "Send", self.pill._send))
        self._lay_out(specs)

    def _lay_out(self, specs) -> None:
        """Draw a row of chips left to right, tagged by key rather than by label."""
        c = self.canvas
        x = PAD
        y2 = self._h - PAD
        y1 = y2 - CHIP_H
        for key, label, cmd in specs:
            w = 20 + 7 * len(label)
            primary = key in ("Send", "Ask", "Put it back")
            tag = chip_tag(key)
            _round_rect(
                c, x, y1, x + w, y2, 13,
                fill=self.pill.accent if primary else CHIP, outline="", tags=tag,
            )
            c.create_text(
                x + w / 2, (y1 + y2) / 2, text=label,
                fill=SHELL if primary else TEXT,
                font=("Segoe UI", 9, "bold"), tags=tag,
            )
            c.tag_bind(tag, "<Button-1>", lambda _e, f=cmd: f())
            x += w + 8

    def tick_countdown(self) -> None:
        """Repaint when the auto-ask number changes, and only then.

        The bubble otherwise renders on events, and a countdown has no events. Redrawing
        every frame would rebuild the whole canvas 33 times a second for a digit that
        changes once; comparing the digit first makes it once a second.
        """
        left = getattr(self.pill.session, "auto_ask_in", None)
        shown = None if left is None else int(left) + 1
        if shown == self._countdown:
            return
        self._countdown = shown
        if self._visible:
            self._render()

    def _linger_left(self) -> int:
        """Whole seconds still on the clock, counting down to 1 and then gone."""
        return int(max(0.0, SENT_LINGER_SEC - (time.perf_counter() - self._sent_at))) + 1

    def tick_sent(self) -> None:
        """Run the linger down, repainting only when the digit changes.

        A countdown has no events, so the number that *would* be drawn is computed and
        compared first — once a second rather than the 33 times a frame-by-frame redraw
        would cost. Exactly what `tick_countdown` does, for exactly the same reason.
        """
        if not self._sent:
            return
        if time.perf_counter() - self._sent_at >= SENT_LINGER_SEC:
            self.hide()
            return
        left = self._linger_left()
        if left == self._sent_left:
            return
        self._sent_left = left
        self._render()

    def tick_activity(self) -> None:
        """Say what Flow is doing, animate it, and repaint only when that changes.

        Same discipline as `tick_countdown`, and the same reason: a wait has no events,
        so the frame that *would* be drawn is built and compared first. At `DOT_SEC`
        that is 2.5 repaints a second rather than 33.

        A wait with nothing else on screen brings the bubble up — the invisible states
        are exactly the ones with no draft to hang a note on — and takes it away again
        when it ends, so the model load at the start of a session does not leave an
        empty card sitting over the user's work.
        """
        act = getattr(self.pill.session, "activity", None)
        dot = int(time.perf_counter() / DOT_SEC) % 3 if act and act.waiting else 0
        key = None if act is None else f"{act.label}/{dot}"
        if key == self._frame_key:
            return
        self._frame_key, self._act, self._dot = key, act, dot

        surfacing = act is not None and not self._visible
        if surfacing:
            self._for_activity = True
            self._visible = True
            self.deiconify()
        elif act is None and self._for_activity and not (
            self._text or self._partial or self._reply or self._note
        ):
            self.hide()
            return
        if self._visible:
            self._render()
        if surfacing:
            # After the render, not before: `_float_up` repositions against `self._h`,
            # which is what the render computes. Animating first moves the window to a
            # height it does not have yet and the rise starts with a jump.
            self._float_up()

    def _indicator(self, y: int) -> None:
        """The one row that says what Flow is doing, and whether it can still hear.

        Three marching dots for the indeterminate waits — the honest shape for a wait
        whose length nobody knows, where a progress bar would have to invent a
        denominator. A flat line instead when the answer is "not listening", because
        that is exactly what the pill's level bars are doing at the same moment: the
        same fact, drawn the same way, in the two places the user is looking.
        """
        c = self.canvas
        x = PAD
        if self._act.waiting:
            for i in range(3):
                lit = i == self._dot
                r = 3.0 if lit else 2.0
                cx, cy = x + 4 + i * 10, y + 8
                c.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    fill=self.pill.accent if lit else CHIP, outline="", tags="waiting",
                )
        else:
            c.create_line(x, y + 8, x + 24, y + 8, fill=MUTED, width=2, tags="waiting")
        c.create_text(
            x + 34, y, anchor="nw", text=self._act.label, fill=MUTED,
            font=("Segoe UI", 9), tags="indicator",
        )

    def _put_back(self) -> None:
        """P6: return the words Send took, into the draft they came from.

        The same path "bring back my last prompt" already takes. A second way of doing
        it would be a second thing to keep working.
        """
        self.pill.session.recall()

    def _was_a_command(self) -> None:
        # Reaching for any chip means the user is still working on this draft.
        self.pill.session.hold_auto_ask()
        self.pill.session.rescue_last_append()

    def _take_reply(self) -> None:
        """P9's verb, on the card the answer is drawn on.

        The chip is the floor for this feature whatever the spoken form does: it cannot
        be mis-decoded, and the workshop loop is unusable without *some* way across.
        """
        if self.pill.session.take_reply():
            # The answer has been moved, so the card stops showing it as an answer —
            # otherwise the same text sits on screen twice, once as a reply and once as
            # the draft, and only one of them is what Send will hand over.
            self._reply = ""
            self._render()

    # -- repairing the text by hand ----------------------------------------

    def _edit(self) -> None:
        """Open the draft in a real text box, with the keyboard focus in it.

        This is the one thing in the app that deliberately takes the foreground, and it
        is allowed to for the same reason the right-click menu is: the click that got us
        here is the last input event, which is what earns a process the right to call
        `SetForegroundWindow`. Invariant 10 is unharmed by it and that is not a hope —
        `inject.resolve()` refuses on a live process-id check against whatever actually
        has the foreground, so Flow holding it makes the refusal *fire*, which is the
        correct answer while somebody is typing. `_track_target` keeps the last
        foreground that was not Flow's own, so the window Send is aimed at survives.
        """
        text = self.pill.session.begin_edit()
        if text is None:
            return  # refused, and the note says why
        # Lite skips the whole foreground argument: with no `WS_EX_NOACTIVATE` to work
        # around, `focus_force` on an ordinary window is the whole implementation, and
        # the verification below has nothing to verify with — left in, it would close the
        # editor and report that "Windows kept the focus" on a machine with no Windows.
        lite = self.lite
        self._previous_focus = 0 if lite else foreground_hwnd()
        box = self._editor = tk.Text(
            self, bg=SHELL, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightbackground=self.pill.accent,
            highlightcolor=self.pill.accent, wrap="word",
            font=("Segoe UI", 10), undo=True, padx=6, pady=4,
        )
        box.insert("1.0", text)
        # Escape cancels and Ctrl+Enter commits; a bare Enter is a newline, because a
        # prompt is not a single line and the chips are the discoverable way out anyway.
        box.bind("<Escape>", lambda _e: (self._cancel_edit(), "break")[1])
        box.bind("<Control-Return>", lambda _e: (self._commit_edit(), "break")[1])
        self._render()
        if not lite:
            _user32.SetForegroundWindow(toplevel_hwnd(self))
        box.focus_force()
        box.mark_set("insert", "end")

        # Verified, not assumed. `SetForegroundWindow` is *refused* for a process that
        # does not own the last input event, and it reports that by doing nothing —
        # which leaves a text box on screen, with a cursor in it, collecting nothing,
        # while every keystroke goes to whatever really has the focus. Measured: driven
        # without a click, the editor opened and the word typed into it landed in the
        # browser behind. Better to close and say so than to swallow somebody's typing.
        if not lite and not owned_by_flow(foreground_hwnd()):
            self._close_editor()
            self.pill.session.cancel_edit()
            self.note("could not open the editor - Windows kept the focus where it was")

    def _close_editor(self) -> str:
        """Tear the box down and hand the foreground back. Returns what was in it."""
        box, self._editor = self._editor, None
        text = ""
        if box is not None:
            try:
                text = box.get("1.0", "end-1c")
            except tk.TclError:
                text = ""
            box.destroy()
        previous, self._previous_focus = self._previous_focus, 0
        # Back to whatever had it, which by construction is the window the user was
        # dictating into — never Flow, because `_track_target` filters those out.
        if previous:
            try:
                _user32.SetForegroundWindow(previous)
            except OSError:
                pass
        return text

    def _commit_edit(self) -> None:
        self.pill.session.commit_edit(self._close_editor())
        self._render()

    def _cancel_edit(self) -> None:
        self._close_editor()
        self.pill.session.cancel_edit()
        self._render()

    # Both chips toggle. Pressing one used to be a one-way door until it timed out 30 s
    # later, so a mis-click meant every utterance in the next half minute was forced
    # down the wrong path with no way to take it back — which reads exactly like the app
    # being "locked to refine".
    def _refine(self) -> None:
        self.note(self._arm_next("edit", "listening for an instruction…"))

    def _continue(self) -> None:
        self.note(self._arm_next("append", "listening to continue…"))

    def _arm_next(self, mode: str, armed_note: str) -> str:
        session = self.pill.session
        # Arming a chip is a statement that something is about to be said, so the
        # countdown must not run out while the user is drawing breath to say it.
        session.hold_auto_ask()
        if session.force_next == mode:
            session.force_next = None
            return "back to deciding for itself"
        session.force_next = mode
        return armed_note
