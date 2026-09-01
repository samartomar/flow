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
import math
import os
import queue
import sys
import time
import tkinter as tk
import traceback
from collections import deque
from pathlib import Path

from .edits import SEND_WORD, SEND_WORD_PRESETS, enter_word
from .help import (
    AUTO_ASK_OFF_LABEL,
    WELCOME_TITLE,
    welcome_rows,
    fit,
    AUTO_ASK_ON_LABEL,
    TITLE as TITLE_DEFAULT,
    open_guide,
    open_path,
    rows as help_rows,
)
from .lexicon import (
    DEFAULT_PATH as LEXICON_PATH,
    append_pair,
    ensure as ensure_lexicon,
    pairs,
)
from . import tray
from .notes import Notes
from .profile import path_key, resolve_workspace
from .refine import EFFORT_DEFAULT, EFFORTS, available
from .session import CONVERSE, DICTATE, Session, State
from .stats import today_note
from .thread import MAX_TURNS as THREAD_MAX_TURNS
from .version import version


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


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
    from .inject import classify, foreground_hwnd, owned_by_flow, take_warnings

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
    # meaning in a body that never types into another window. Its four exports are the
    # only ones this module needs, and each has an honest answer with no hands — there is
    # no foreground to find, nothing of Flow's to recognise, no window to name, and no
    # paste to warn about.
    def foreground_hwnd() -> int:
        return 0

    def classify(_hwnd):
        # An unnamed app, which reads downstream as one with no per-app note — the same
        # answer `_track_target` gives on Lite, and the behaviour every launch had before
        # per-app notes existed.
        from .inject import Target

        return Target()

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

    **Off Windows this cannot take, and the app is built on that.** `_menu` borrows the
    foreground on Windows precisely because a `WS_EX_NOACTIVATE` window would otherwise
    get no input for its popup, and says in as many words that Lite needs none of it —
    the window is in the activation chain like any other and the popup gets its input the
    ordinary way.

    Aqua does offer an equivalent, `MacWindowStyle ... noActivates`, and asking for it
    was a mistake: it took the windows out of that chain, and a window that never
    activates does not take clicks either. Send stopped working on a Mac. The frame is
    handled in `_shell_window` now, where `overrideredirect` already lives and where it
    always belonged.
    """
    if sys.platform != "win32":
        return False
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


def _bare_window(win) -> None:
    """Take the frame off, by the means the platform will accept.

    `overrideredirect` is how this is done everywhere, and on Aqua it is the cause of
    both faults reported from a Mac: click the app you want to dictate into and Flow's
    window vanishes, and clicking Send does nothing. A probe of six variants split on
    exactly this line — every window without it kept its place when another app came
    forward and had its button reached by a click; every window with it was deaf and
    gone. Which is a fair description of what it means: a window the window manager has
    been told to stop managing.

    Tk 9 on Aqua has a frameless window that is still a window. A style mask is the set
    of bits an NSWindow is built from, and the one that puts a title bar on it is
    `titled` — so a mask with *no* bits is bare, and nothing else about the window has
    been given away. Measured on a Mac at 0 px of decoration against the control's 28,
    and its button was reached from the background.

    The obvious-looking alternative, an `NSPanel` with the `nonactivatingpanel` bit, is
    not available: Tk answers `cannot change the class after the mac window is created`
    even for a window that has never been mapped, and a `Toplevel` built with
    `class_="NSPanel"` is not one either — that argument names a Tk class, not an
    NSWindow one. It is also not needed. Nonactivating is about not stealing focus, and
    these windows do not take focus in the first place.

    Falls back rather than fails: `-stylemask` arrived in Tk 9, and a Mac on 8.6 should
    get the old behaviour rather than a window with a title bar on it.
    """
    if sys.platform == "darwin":
        try:
            win.wm_attributes("-stylemask", "")
            return
        except tk.TclError:
            pass  # Tk 8.6: no style masks. `overrideredirect` is all there is.
    win.overrideredirect(True)


def _shell_window(win, lite: bool, alpha: float) -> str:
    """Apply the window attributes every Flow window shares, and return its background.

    Two of the five are Windows-only Tk attributes. `-transparentcolor` is what keys the
    magenta out, so without it the keyed colour is not invisible — it is a magenta
    rectangle where the app should be — and `-toolwindow` does not exist off Windows at
    all. Asking for either is a `TclError` before anything is drawn, which is why the
    platform is part of the guard and not only `lite`.

    **It used to be only `lite`**, on the reasoning that `__main__` forces lite mode off
    Windows so the two can never come apart. They came apart the first time something
    other than `__main__` built a `Pill`: `scripts/mac_report.py` asked for full mode on
    a Mac and got `bad attribute "-transparentcolor"` out of Tk before a window existed.
    An invariant a caller has to know about is one a caller can miss, and this one is
    cheap to enforce where it is true.

    **On Aqua it is `_bare_window` that does this**, and not with `overrideredirect`:
    that line is what made Flow's windows there both deaf to clicks and gone the moment
    another app came forward. Two earlier attempts to help it were both harm.** A Mac reported the pill wearing a title bar, and the cause was not this
    line failing — it was `MacWindowStyle` being asked for *afterwards*, which put a
    frame back on and took the window out of the activation chain, so Send stopped taking
    clicks. Removing that call was the fix. A withdraw-and-remap cycle added alongside it,
    to "force Aqua to rebuild the NSWindow", was solving a problem the style call had
    created — and on a real machine it left the window hidden after the remap. Both are
    gone. What is left is the line that was always doing the work.

    The background is returned rather than left to the caller so a window cannot be given
    one that contradicts what was applied to it.
    """
    _bare_window(win)
    win.attributes("-topmost", True)
    win.attributes("-alpha", alpha)
    if lite or sys.platform != "win32":
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


#: `_tk_work_area`'s answer, measured once. A module global because the measurement
#: costs a window and `_sync_monitor` asks every frame — measuring per frame would open
#: and destroy a Toplevel thirty times a second.
_TK_WORK: tuple | None = None


#: How far down an Aqua window asked for `+0+0` can plausibly be pushed by the menu bar:
#: 30 px on an ordinary display, more on a notched one. Past this, the window manager
#: honoured the request literally — as Windows does — and the number means nothing here.
_AQUA_MENU_MAX = 80

#: How tall an Aqua title bar can plausibly be. 28 px measured; the cap is loose because
#: it only has to separate "a title bar" from "the window went somewhere else entirely".
_AQUA_TITLE_MAX = 60

#: Where the probe is put to measure its own title bar — far enough down that no menu bar
#: can be clamping it, so the whole difference from what was asked for is decoration.
_AQUA_FREE_Y = 300


def _aqua_work_area(win, sw: int, sh: int) -> tuple[int, int, int, int] | None:
    """The visible frame on macOS, or None if this build cannot say.

    **The maximise probe does not work here.** `state("zoomed")` on Aqua neither raises
    nor maximises. Asked to maximise a 200x120 window at +80+80, Tk 9.0.3 returned
    (80, 108, 280, 228) — the same window, the same size, the position it was already
    in, and no error. `_tk_work_area` rejected that and fell back to the whole screen,
    `bottom_centre` stood the pill 24 px above 878, and the pill spent its life inside
    the Dock. The close-up in the report was a picture of Dock icons.

    `wm maxsize` is the call that knows, and only on this platform: Tk's Aqua port
    answers it from `[NSScreen visibleFrame]`, which is the screen less the menu bar and
    the Dock. On Windows the same call answers with the whole screen even with a taskbar
    present, which is why `_tk_work_area` measures instead of asking — this is the one
    platform where the shortcut is the *better* instrument, not a lazier one.

    **Everything is measured from one probe, and that is the point.** `maxsize` gives a
    size and no origin, so the origin has to come from somewhere else — and the first
    version took it from a probe while taking the size from the caller's window. Those
    are not the same window. `maxsize` is a maximum *content* size, so it is short by
    whatever decoration its window wears: 735 from a titled probe against 763 from the
    `overrideredirect` pill, on the same display, differing by exactly the 28 px title
    bar. Adding one window's origin to another's size counted that title bar twice and
    put the work area 28 px too low — the pill moved off the Dock and back onto it.

    So one probe answers all three, and its own decoration cancels out:

      **its title bar** — asked for a y far below any menu bar, so the whole difference
      between what was asked and where the client area landed is decoration.

      **the menu bar** — asked for `+0+0`, where Aqua refuses to put a titled window;
      where it lands, less the title bar just measured, is the top of the visible frame.

      **the visible frame's height** — `maxsize` plus that same title bar, which is what
      turns a content size back into a frame size.

    Measured on a 14-inch MacBook Pro, Tk 9.0.3, a 1352x878 screen: a 28 px title bar, a
    `+0+0` client top of 58 giving a menu bar of 30, and `maxsize` 1352x735 giving a
    frame height of 763. The Dock's top edge is 30 + 763 = 793 and the Dock is 85 px
    tall. All three are Tk asking Tk, so they were checked against something that is not:
    `defaults read com.apple.dock tilesize` on the same machine says 69, and 69 plus
    Apple's padding is the 85 this leaves.

    **Nothing is trusted without a shape check.** A `maxsize` of the whole screen has
    told us nothing; a title bar or a menu bar outside the range one can be is a window
    manager that honoured a request literally rather than clamping it, as Windows does.
    Any of those and this returns None and the caller falls through to the maximise
    probe, so the worst case is exactly the old behaviour rather than a new way to be
    wrong.
    """
    probe = None
    try:
        probe = tk.Toplevel(win)
        probe.attributes("-alpha", 0.0)

        probe.geometry(f"200x120+80+{_AQUA_FREE_Y}")
        probe.update_idletasks()
        title = probe.winfo_rooty() - _AQUA_FREE_Y
        if not 0 <= title <= _AQUA_TITLE_MAX:
            return None

        probe.geometry("200x120+0+0")
        probe.update_idletasks()
        top = probe.winfo_rooty() - title
        if not 0 <= top <= _AQUA_MENU_MAX:
            return None

        mw, mh = probe.maxsize()
    except (tk.TclError, AttributeError, TypeError, ValueError):
        return None
    finally:
        if probe is not None:
            try:
                probe.destroy()
            except tk.TclError:
                pass

    height = mh + title
    if not (0 < mw <= sw and 0 < height < sh and top + height <= sh):
        return None  # it answered with the whole screen, or the parts disagree
    return 0, top, mw, top + height


def _tk_work_area(win, sw: int, sh: int) -> tuple[int, int, int, int]:
    """The usable area, measured by asking the window manager to maximise something.

    Reported from a Mac: the pill sat under the Dock. `_work_area` degrades to the whole
    screen off Windows, so bottom-centre placement stood the stack on the very bottom
    edge — behind the Dock on a default macOS desktop, behind the panel on a
    bottom-taskbar Linux.

    **Measured rather than asked, because asking does not work.** `wm_maxsize` is the
    obvious call and it is useless: on Windows it answers with the whole screen even
    with a taskbar present, so a fallback built on it would have been wrong in exactly
    the way it was meant to fix. What *is* reliable is maximising a window and looking
    at where the window manager put it — it has to honour its own panels to do that.
    Checked against `SystemParametersInfoW` on Windows, where the two agree exactly on
    left, right and bottom.

    **macOS is the exception and is handled before any of this**, in `_aqua_work_area`:
    there the maximise is accepted and ignored, and `wm maxsize` — useless on Windows —
    is the call that knows where the Dock is. That path returns None unless what it
    measured has the shape of a real work area, so this measurement stays the fallback.

    The probe is transparent while it is measured, so nothing flashes on screen.

    **`top` is taken as reported and is a title bar too low.** `winfo_rooty` is the
    client area, and the frame inset differs between a normal window and a maximised one
    — measuring the inset first and subtracting it made the answer worse, not better
    (−8 against a true 0). It is left alone because `top` feeds one thing, the ceiling
    in `bottom_centre`, where being conservative by a title bar costs nothing. The three
    edges that place the stack are exact.
    """
    global _TK_WORK
    if _TK_WORK is not None:
        return _TK_WORK
    if sys.platform == "darwin":
        aqua = _aqua_work_area(win, sw, sh)
        if aqua is not None:
            _TK_WORK = aqua
            return aqua
    fallback = (0, 0, sw, sh)
    asked_w, asked_h = 200, 120
    probe = None
    try:
        probe = tk.Toplevel(win)
        probe.attributes("-alpha", 0.0)
        probe.geometry(f"{asked_w}x{asked_h}+80+80")
        probe.state("zoomed")
        probe.update_idletasks()
        x, y = probe.winfo_rootx(), probe.winfo_rooty()
        w, h = probe.winfo_width(), probe.winfo_height()
        found = (x, y, x + w, y + h)
    except (tk.TclError, AttributeError, ValueError):
        # `zoomed` is documented for Windows and X11 and may not exist on this build.
        # The whole screen is the honest answer then: wrong by a Dock, rather than
        # wrong by whatever a broken measurement returned.
        found = fallback
    finally:
        if probe is not None:
            try:
                probe.destroy()
            except tk.TclError:
                pass
    if not _plausible_work_area(found, sw, sh, asked_w, asked_h):
        found = fallback
    _TK_WORK = found
    return found


def _plausible_work_area(rect, sw: int, sh: int, asked_w: int, asked_h: int) -> bool:
    """Whether a maximised probe actually got maximised.

    **The check that was missing, and the bug it let through.** On Aqua,
    `state("zoomed")` does not raise and does not maximise either — it is accepted and
    ignored. The probe stayed the 200x120 it was asked for, that rectangle passed a
    check which only asked "positive, and no bigger than the screen", and the pill was
    placed against a work area 200 px wide. It landed in the top-left corner of a
    1512-wide display, which is exactly where a Mac reported finding it.

    So the test is not "is this a rectangle" but "did the window manager do the thing".
    Two ways of asking, because either alone has a hole: a window that never grew is the
    direct evidence, and a rectangle far smaller than the display is what catches a
    window manager that grew it a little and stopped. A real work area is the screen
    minus a Dock or a taskbar — nowhere near half of it.
    """
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    if not (w > 0 and h > 0 and w <= sw and h <= sh):
        return False
    if w <= asked_w or h <= asked_h:
        return False  # it never grew: `zoomed` was accepted and ignored
    return w >= sw * 0.6 and h >= sh * 0.6


#: `MonitorFromPoint`'s "nearest monitor" flag, for a cursor that is briefly nowhere —
#: between two displays, or on a monitor that has just been unplugged.
_MONITOR_DEFAULTTONEAREST = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def _pointer_monitor(sw: int, sh: int, win=None) -> tuple[tuple, tuple]:
    """`(full, work)` for the monitor under the mouse, each `(left, top, right, bottom)`.

    **Two rectangles, because FluidVoice places against two.** `positionWindow` centres
    on `screen.frame` but sits the overlay on `screen.visibleFrame`, and the asymmetry is
    deliberate: centred on the *physical* display, so it lands where the eye expects it,
    but lifted clear of the Dock. Windows hands back exactly that pair — `rcMonitor` and
    `rcWork` — from one call, so the rule ports without being reinterpreted.

    **The monitor under the pointer, not the primary one.** `_work_area` asks
    `SystemParametersInfoW`, which only ever answers for the primary display, so on a
    two-monitor desk everything Flow draws lands on the wrong one whenever the user is
    working on the other. FluidVoice resolves this per presentation
    (`OverlayScreenResolver.screenForCurrentPointer`, and `preferredPresentationScreen`
    in the notch path does the same), and the pointer is the right proxy: it is where
    the user's attention is, and it costs nothing to ask.

    Falls back to the primary work area, then to the whole screen, so a machine where
    the call is unavailable places exactly where it placed before.
    """
    pt = _POINT()
    try:
        user32 = ctypes.windll.user32
        if user32.GetCursorPos(ctypes.byref(pt)):
            handle = user32.MonitorFromPoint(pt, _MONITOR_DEFAULTTONEAREST)
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if handle and user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                full = (info.rcMonitor.left, info.rcMonitor.top,
                        info.rcMonitor.right, info.rcMonitor.bottom)
                work = (info.rcWork.left, info.rcWork.top,
                        info.rcWork.right, info.rcWork.bottom)
                if full[2] > full[0] and work[2] > work[0]:
                    return full, work
    except (AttributeError, OSError):
        pass
    # Off Windows there is no `MonitorFromPoint` and no `rcWork`, so the two rectangles
    # collapse into the one Tk can answer for. `win` is optional because the fallback
    # has to keep working for the callers that have no window yet.
    work = _tk_work_area(win, sw, sh) if win is not None else _work_area(sw, sh)
    return work, work


#: `GetSystemMetrics` indices for the bounding box of every monitor together.
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN = 76, 77
_SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 78, 79

#: How far past the desktop a hidden panel is parked. FluidVoice's number
#: (`parkWindowOffscreen`), and generous on purpose: it has to clear whatever monitor
#: someone plugs in next, not merely the ones present when the window was hidden.
PARK_MARGIN = 1024


def _virtual_desktop(sw: int, sh: int) -> tuple[int, int, int, int]:
    """Every monitor's bounding box, which is what a parked window has to clear.

    The union rather than the current monitor, for the same reason FluidVoice unions
    `NSScreen.screens`: a window parked past the right edge of the *left* display in a
    two-monitor desk is parked in the middle of the right one, in full view.
    """
    try:
        metric = ctypes.windll.user32.GetSystemMetrics
        x, y = metric(_SM_XVIRTUALSCREEN), metric(_SM_YVIRTUALSCREEN)
        w, h = metric(_SM_CXVIRTUALSCREEN), metric(_SM_CYVIRTUALSCREEN)
        if w > 0 and h > 0:
            return x, y, x + w, y + h
    except (AttributeError, OSError):
        pass
    return 0, 0, sw, sh


def park_spot(w: int, h: int, desktop) -> tuple[int, int]:
    """Where a hidden panel waits: past the far corner of every monitor there is.

    **Parked rather than unmapped, which is the point.** FluidVoice never destroys or
    hides its overlay — `prepare()` builds it at launch and parks it, and `show` pulls
    it back — with the reason written on the method: it is paying the window-server
    surface cost once, so that appearing costs a move and nothing else. Under
    push-to-talk that is the difference that matters, because the overlay now has to be
    up between a key going down and somebody starting to talk, which is a tenth of a
    second on a fast day.

    Its own function so the arithmetic is testable without a window, and so the one
    thing that must never be true — a parked panel landing on a monitor somebody is
    looking at — is a property a test can state.
    """
    _left, _top, right, bottom = desktop
    return right + w + PARK_MARGIN, bottom + h + PARK_MARGIN


def park(win) -> None:
    """Hide `win` by moving it off every monitor, rather than by unmapping it.

    `withdraw()` was what the panels did, and it is the honest thing for a window nobody
    will want again soon. Push-to-talk made that untrue: a panel now has to be up between
    a key going down and somebody starting to speak, and a remap is work done in exactly
    that gap. Parking is FluidVoice's answer (`parkWindowOffscreen`, with `prepare()`
    paying the surface cost at launch), and it makes appearing a move and nothing else.

    A function rather than a method because `Bubble` and `ConversationCard` share no base
    class — they share a *job*, and this is the third thing they have both needed. The
    window is re-placed by `reposition` on the way back, which `_render` already calls,
    so there is no unparking step to forget.
    """
    w = max(1, win.width)
    h = max(1, getattr(win, "_h", 1))
    x, y = park_spot(w, h, _virtual_desktop(
        win.winfo_screenwidth(), win.winfo_screenheight()))
    win.geometry(f"{w}x{h}+{x}+{y}")


def bottom_centre(w: int, h: int, full, work, offset: int = 0) -> tuple[int, int]:
    """Where a panel of `w`×`h` goes, by FluidVoice's `positionWindow` arithmetic.

    Centred horizontally on `full` and stood `offset` above the bottom of `work`, then
    clamped into `work` with the same two buffers FluidVoice uses — 10 px off the bottom
    and 40 px off the top. The clamp is what makes the offset safe to expose as a
    setting: a number typed into a profile cannot push the panel off the screen, and a
    panel taller than the display lands against the bottom rather than above the top.

    The y arithmetic is flipped from the original and means the same thing. macOS
    measures up from the bottom, so `visibleFrame.minY + offset` is the panel's bottom
    edge; Windows measures down from the top, so the same edge is
    `work.bottom - h - offset`.
    """
    left, top, right, bottom = work
    x = (full[0] + full[2]) // 2 - w // 2
    y = bottom - h - int(offset)
    lowest = bottom - h - 10
    highest = top + 40
    if highest > lowest:
        # A panel too tall for the display it is on. The bottom is the edge worth
        # keeping: the top of a draft can run under the taskbar and still be read, and
        # the chips that act on it live at the bottom.
        y = lowest
    else:
        y = max(highest, min(y, lowest))
    x = max(left, min(x, right - w))
    return x, y


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


#: Bundled rather than system-installed, so a checkout runs the intended type without
#: asking anyone to install anything. `FR_PRIVATE` (0x10) is what keeps the registration
#: to this process — no admin prompt, nothing left behind for another app to see, and
#: nothing to uninstall if the file is just deleted.
_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
_FONT_FILES = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
)
_FR_PRIVATE = 0x10

#: The files actually registered, so `_unload_fonts` removes only what `_load_fonts`
#: added — never a guess at what might be there, on a machine this never ran on.
_loaded_fonts: list[str] = []


def _load_fonts() -> None:
    """Register the bundled IBM Plex weights, process-private, before any window exists.

    Each static weight is its own GDI family — measured on this machine, the files
    above resolve to "IBM Plex Sans", "IBM Plex Sans Medm", "IBM Plex Sans SmBld",
    "IBM Plex Mono" and "IBM Plex Mono Medm" (GDI's legacy name table truncates
    "Medium"/"SemiBold" rather than exposing them as a weight on the Regular family),
    which is why the font tuples below reference a family per weight instead of a
    "bold" flag. A machine missing a file, or off Windows entirely, still runs — Tk
    falls back to its platform default for whichever family did not resolve.
    """
    if sys.platform != "win32":
        return
    try:
        add = ctypes.windll.gdi32.AddFontResourceExW
    except (AttributeError, OSError):
        return
    for name in _FONT_FILES:
        path = str(_FONT_DIR / name)
        try:
            if add(path, _FR_PRIVATE, 0):
                _loaded_fonts.append(path)
        except OSError:
            pass


def _unload_fonts() -> None:
    """The other half of `_load_fonts`, run on the way out.

    `FR_PRIVATE` fonts are unregistered automatically when the process exits, so this
    is not load-bearing for correctness — but `quit_app` tears down explicitly rather
    than leaving anything to the OS to notice on its own.
    """
    if sys.platform != "win32" or not _loaded_fonts:
        return
    try:
        remove = ctypes.windll.gdi32.RemoveFontResourceExW
    except (AttributeError, OSError):
        return
    for path in _loaded_fonts:
        try:
            remove(path, _FR_PRIVATE, 0)
        except OSError:
            pass
    _loaded_fonts.clear()


TRANSPARENT = "#ff00fe"  # keyed out by -transparentcolor; unlikely in real content

#: v2 opaque surface palette (decisions.md 2026-08-09, "one object, three windows").
#: Every pixel here is fully opaque — no shadow, no alpha blend — so `SHELL` is both the
#: window background and the base fill a hairline ring sits inside.
SHELL = "#1A1D23"
TEXT = "#E6E8ED"  # primary text
MUTED = "#949AA6"  # secondary text — also idle/resting, which claims no state of its own
CHIP = "#22262E"  # secondary chip fill, and the base fill everything else insets into

#: The three-hairline elevation system that replaces a shadow no keyed-transparent window
#: could composite anyway. `RING_OUTER` is the toplevel's own 1 px border — the seam
#: against the desktop; `RING` traces a full inset rect just inside it; `RING_TOP` draws
#: one segment, the top edge only, as the implied light source. A docked pill and panel
#: share one `RING`-coloured seam where they meet, with no gap.
RING_OUTER = "#0B0D10"
RING = "#2E323B"
RING_TOP = "#3A404B"

#: Text tiers below `TEXT`/`MUTED`: `DIM` is tertiary text, `CODE` is the mono/code
#: accent (also the secondary chip's label colour), `PLACEHOLDER` marks held or
#: not-yet-final text (a draft still being spoken, a bubble past Send), and `DISABLED`
#: is what a chip's label dims to when the row is waiting rather than clickable.
DIM = "#656B78"
CODE = "#C7CBD4"
PLACEHOLDER = "#7E8590"
DISABLED = "#5C6270"

#: The primary chip — Send, Ask, Done, Bring it back — inverted from everything else on
#: purpose: everything around it is dark-on-dark, and the one action worth a second
#: look is the one that reads light-on-dark instead.
PRIMARY_FILL = "#EAECF1"
PRIMARY_TEXT = "#15171C"

#: R13: colour encodes state, so the pill reads at a glance without being looked at.
#: One colour, one job, never reused for two states — `REFINING` and `ASKING` still
#: share one because they are the same wait from the user's side, and the surface that
#: is showing already names which.
HEARING = "#3ECF8E"  # green  - capturing speech
#: Every indeterminate wait, wherever it is drawn: the pill's glyph and meter while a CLI
#: is out, and the panel's three marching dots for the same wait. Named rather than
#: written twice, because the dot used to be amber — one of the five unrelated jobs the
#: one amber was doing, which is why none of them read as emphasis.
WAITING = "#7AA2F7"  # blue   - waiting on a CLI
ACCENT = {
    State.IDLE: MUTED,  # resting, armed or not — claims no state of its own
    State.LISTENING: HEARING,
    State.DRAFT: MUTED,  # the held draft is a window, not a pill colour
    State.REFINING: WAITING,
    State.ASKING: WAITING,  # the same wait
}
ERROR = "#F2584A"

#: The one place amber appears in the whole app: the "Bring it back" undo-after-send
#: control. Not reused for a panel outline, a chip fill, or a loading dot elsewhere —
#: see decisions.md 2026-08-09 for why the draft bubble's border gave up amber.
RECOVER_ACCENT = "#E8A33D"

#: The conversation card's identity, and the reason it is a constant rather than a mood.
#:
#: The draft bubble no longer has one. `DRAFT_ACCENT` was `RECOVER_ACCENT` under a second
#: name, and between them they drew the panel outline, the primary chip, the editor ring
#: and the loading dot — the "amber means five things" finding, where a colour spent
#: everywhere emphasises nothing. Each of those went to the thing that actually describes
#: it: neutral chrome for the outline, `PRIMARY_FILL` for the chip, `WAITING` for the dot.
#: Amber is now spent once, on "Bring it back", the one control that undoes something
#: irreversible (decisions.md 2026-08-09).
CARD_ACCENT = "#B48EF5"  # violet - the conversation card

#: P9. The answer, distinct from the user's own words. One violet now carries converse
#: mode's whole identity — the mode-line label, the pill glyph, and this, the answer
#: text tint — because an outline can't also carry a word (decisions.md 2026-08-09).
REPLY = CARD_ACCENT

#: The type scale (decisions.md 2026-08-09). Sizes are negative — Tk pixels, not
#: points — because this app already thinks in pixels everywhere else (`PILL_W`,
#: `BUBBLE_W`, `PAD`…) and a point size would drift from the spec's own numbers on a
#: display at anything but 96 dpi. Weight is a family, not a flag — see `_load_fonts`.
#: Measured on the real canvas at these sizes: `FONT_BODY` lines at 18 px, ~6.7 px a
#: character; `FONT_NOTE` at 14 px, ~5.4 px a character — the two numbers
#: `tests/test_editor.py`'s `MeasuringCanvas` has to agree with.
FONT_SANS = "IBM Plex Sans"
FONT_SANS_MEDIUM = "IBM Plex Sans Medm"
FONT_SANS_SEMIBOLD = "IBM Plex Sans SmBld"
FONT_MONO = "IBM Plex Mono"

FONT_BODY = (FONT_SANS, -14)  # draft text, the answer, the hand editor
#: 11.5 px in the spec, floored rather than rounded to 12: a note is meant to read
#: smaller than a 12 px chip label, and rounding up would erase the one pixel that
#: says so. Also this file's one size for every muted/secondary line — a question
#: pinned above an answer, an elided-lines hint, the indicator label — where the old
#: code spread the same job across two point sizes (8 and 9) that never earned being
#: different from each other.
FONT_NOTE = (FONT_SANS, -11)
FONT_CHIP = (FONT_SANS_MEDIUM, -12)  # secondary chip label
FONT_CHIP_PRIMARY = (FONT_SANS_SEMIBOLD, -12)  # Send / Ask / Done / Bring it back
#: Trace/code text and the pill's bar label (§02, `Bar label · Plex Mono 11 · +.1em`).
#: The editor's key hints and `Pill._bar_label` are the two things drawn in it.
FONT_TRACE = (FONT_MONO, -11)
#: The live partial — muted italic, named so the probe that measures it and the call that
#: draws it cannot be given different fonts. They were never measured together at all, and
#: the flat 34 px that stood in for the measurement is what put a four-line partial through
#: the note below it. See `Bubble._partial_slot`.
FONT_PARTIAL = (*FONT_NOTE, "italic")

PILL_H = 40
#: Twelve, down from eighteen (decisions.md 2026-08-09). The meter answers one question —
#: *am I being heard* — and twelve bars answer it as well as eighteen did, in six bars
#: less of a widget that sits over somebody's editor all day. Six of the eighteen were
#: paying rent on a number nobody had chosen.
BARS = 12
BAR_W, BAR_GAP = 4, 2
DB_FLOOR, DB_CEIL = -58.0, -12.0  # level range mapped onto bar height

#: The meter's shape, taken from FluidVoice's `BottomWaveformView` (`visualizerPeakHeight`
#: and `updateBars`) rather than invented here.
#:
#: **This changed what the meter *is*.** Flow's bars used to be a scrolling history — a
#: level per frame, pushed through a deque, so the shape travelled right to left like a
#: seismograph. FluidVoice's are a symmetric bloom: every bar is driven by the *same*
#: current level and shaped by a fixed envelope that makes the middle ones tallest, so
#: the meter breathes in place instead of scrolling.
#:
#: The bloom is the better answer to the question R13 says this widget exists to answer —
#: *am I being heard right now*. A history answers "was I heard, recently", and the eye
#: has to read left to right to get at it; a bloom answers it in one glance with no
#: direction to follow. It is also what makes the meter read as one object rather than
#: twelve, which is the whole visual difference between the two apps.
#:
#: `_ENVELOPE_FLOOR`/`_ENVELOPE_SPAN`: `factor = max(0.18, 0.96 - distance * 0.78)`,
#: where distance is 0 at the centre bar and 1 at the ends. `_LEVEL_EXPONENT`: normal
#: speech should push the bars high, so the response is deliberately not linear.
#: `_BAR_VARIATION`: a per-bar wobble of ±8%, so a held tone is not twelve identical
#: rectangles.
_ENVELOPE_FLOOR, _ENVELOPE_SPAN, _ENVELOPE_MIN = 0.96, 0.78, 0.18
_LEVEL_EXPONENT = 0.55
_BAR_VARIATION_BASE, _BAR_VARIATION_SWING, _BAR_VARIATION_RATE = 0.92, 0.08, 1.45
#: Half-heights, in pixels, at the ends of the response. The minimum is what silence
#: draws — a flat line of stubs rather than an empty box, which is the one thing Flow's
#: old meter and FluidVoice's agree on.
BAR_MIN_H, BAR_MAX_H = 1.5, 12.0

#: Where the meter starts and how wide it ends up — named because the bar label has to
#: begin after it, and two places computing `BARS * (BAR_W + BAR_GAP)` is how the label
#: would come to be drawn through the twelfth bar the day one of them changed.
METER_X = 40
METER_W = BARS * (BAR_W + BAR_GAP) - BAR_GAP

#: §02's `+.1em`, at an 11 px em, rounded to the pixel Tk can actually place text on.
#: Tk has no letter-spacing, so `Pill._bar_label` positions each character itself.
LABEL_TRACK = 1
#: One character's advance in `FONT_TRACE`. A single number is enough because the family
#: is monospaced — which is also why the space in `NO INPUT` needs no special case.
LABEL_ADV = 7
LABEL_PITCH = LABEL_ADV + LABEL_TRACK
LABEL_GAP = 12  # between the meter's last bar and the label
LABEL_PAD = 12  # the mock's own right padding

#: What the label says, per state (§03's mocks: `idle`, `listening`, `held`, `working`,
#: `no input`, and §04's `speaking`). Upper-cased at 11 px mono with tracking, which is
#: what makes a nine-character word read as a status line rather than as prose.
#:
#: `REFINING` and `ASKING` share `WORKING` for the reason they share `WAITING`: from the
#: user's side they are one wait, and the panel that is up already names which.
BAR_LABELS = {
    State.IDLE: "IDLE",
    State.LISTENING: "LISTENING",
    State.DRAFT: "HELD",
    State.REFINING: "WORKING",
    State.ASKING: "WORKING",
}
LABEL_OFF = "OFF"  # disarmed: not a state of the session, a state of this pill
LABEL_SPEAKING = "SPEAKING"  # deaf because Flow is talking, not because nothing arrived
LABEL_EDITING = "EDITING"  # deaf because the draft is being edited by hand
LABEL_NO_INPUT = "NO INPUT"  # armed, and the device stopped

#: The label's slot, reserved at the widest label rather than fitted to the current one —
#: the rule §07 states for the Ask chip's countdown numeral, and for the same reason: a
#: slot that fits the word being shown moves the meter's right edge every time the state
#: changes. Computed over the labels themselves, so adding a longer one widens the pill
#: instead of quietly drawing through the twelfth bar. `tests/test_pill.py` measures the
#: result against the real font, which is the only thing that can tell `LABEL_ADV` it has
#: stopped being 7.
LABEL_SLOT_W = LABEL_PITCH * max(
    len(w) for w in (*BAR_LABELS.values(), LABEL_OFF, LABEL_SPEAKING,
                     LABEL_EDITING, LABEL_NO_INPUT)
) - LABEL_TRACK

#: The pill's own width at rest, derived rather than chosen: the glyph, the meter, and a
#: slot the widest label fits in.
#:
#: §03 heads its mock `168 idle`, and 168 is what this was — but 168 assumes the label
#: slot is `IDLE`-sized (28 px). The same mock draws the meter as `flex:1`, so in the
#: spec's own HTML a longer word simply eats bars; at `LISTENING` there is room for six
#: of the twelve. That trade is the wrong way round. The meter is the instrument that
#: answers *am I being heard*, and one that loses half its bars the moment you start
#: speaking is a worse lie than a wider pill — so the pill widens instead, which is the
#: resolution §03 itself reaches when the draft panel's chip row does not fit 380
#: ("the widest state … is worth more than the mock it came out of").
#:
#: The right edge is what `_sync_dock` pins, so the extra width appears on the left, in
#: the direction this window already grows every time a panel docks to it.
#:
#: `Pill.pill_w` is what actually draws and positions the window; this is the value it
#: falls back to when no panel is up (decisions.md 2026-08-09, "one object, three
#: windows").
PILL_W = METER_X + METER_W + LABEL_GAP + LABEL_SLOT_W + LABEL_PAD  # 205

#: The three marching dots that stand in for the meter while a CLI is out (§07): 4 px
#: across, opacity .25 → 1, staggered 150 ms, over a 1.2 s loop. In frames, because the
#: pill's own 30 ms tick is the only clock here — 1200/30 and 150/30.
DOT_R = 2
DOT_GAP = 6
DOTS_LOOP = 40
DOTS_STAGGER = 5
DOT_DIM = 0.25

#: The error flash's envelope (§07, `80 / 1200 / 600`) in frames of the same 30 ms tick:
#: the pill's hairline travels to red over 80 ms, holds for 1.2 s, and decays over 600.
#: One envelope for every call site — the 12/40/60 that used to be scattered across them
#: were three durations nobody had chosen, and the shortest was under a third of the hold
#: the spec names, which is how a warning could flash and be missed.
#:
#: Only the *pill* interpolates. A panel's ring is set red once and cleared once (§07,
#: "two repaints, not sixty"), which is why the surfaces test `Pill.flashing` rather than
#: reading the blended colour back out.
FLASH_ATTACK, FLASH_HOLD, FLASH_DECAY = 3, 40, 20
FLASH_FRAMES = FLASH_ATTACK + FLASH_HOLD + FLASH_DECAY

#: How long the glyph, meter and label take to travel between dictate's state colour and
#: converse's violet (§07, `180ms tint`) — six frames, "and that travel is the whole
#: continuity" of a mode switch that also takes one window down and puts another up.
TINT_FRAMES = 6

#: The level meter eases toward its target rather than jumping (§07, decisions.md
#: 2026-08-09): peaks fall slower than they rise, so a loud spike does not vanish in
#: the same 30 ms frame it arrived in. Both are one-pole exponential smoothing at the
#: 30 ms tick — `alpha = 1 - exp(-frame_ms / time_constant)` — hardcoded rather than
#: computed with `math.exp` at every frame for a value that never changes: rise 60 ms
#: gives 0.3935, fall 160 ms gives 0.1639.
LEVEL_RISE_ALPHA = 0.3935
LEVEL_FALL_ALPHA = 0.1639

#: How many frames the "not hearing" flat-line collapse sweeps over, left to right —
#: four frames at the 30 ms tick is ~120 ms. Short on purpose: the echo-guard defect
#: this meter was built to fix was an *eighteen*-frame (540 ms) false "hearing you"
#: while Flow's own voice scrolled off the bars, and this is under a quarter of that.
DEAF_COLLAPSE_FRAMES = 4

#: Disarmed and untouched this long, the pill fades — it is not capturing anything,
#: and eight seconds is long enough that "sitting there" and "working" stop looking
#: the same. Armed cancels it outright; hovering lifts it back (`HOVER_LIFT_SEC`).
IDLE_DIM_AFTER_SEC = 8.0
IDLE_DIM_ALPHA = 0.55
#: How long the lift back to full opacity takes once the pointer arrives.
HOVER_LIFT_SEC = 0.4

#: The ceiling on one push-to-talk hold, after which Flow stops capturing on its own.
#:
#: Not a limit on how long anybody may speak — it is a limit on how long a *missing
#: keystroke* may hold the microphone open. A keyup can genuinely fail to arrive: the OS
#: drops a low-level hook that overran `LowLevelHooksTimeout`, a lock screen or a UAC
#: prompt takes the input desktop mid-hold, an RDP session grabs the keyboard. Without
#: this the failure is a session recording a room until somebody notices.
#:
#: Two minutes because it has to sit clear of the longest hold anybody would make on
#: purpose without being so far out that the recording is a surprise. Whatever was said
#: is committed and kept, and the note says where it went — the one thing this must not
#: do is end a real dictation by discarding it.
PTT_MAX_HOLD_SEC = 120.0

#: How long the pill must be held before a press becomes a hold-to-talk rather than a
#: click, and how far the pointer may travel before it is a drag instead of either.
#:
#: **This is push-to-talk for everybody who has no chord**, which on a Mac is everybody:
#: `Chord` is a `WH_KEYBOARD_LL` hook and there is no such thing off Windows. The
#: gesture is the same one — press, speak, release, and the words are yours — but the
#: button is a window Flow already draws, so it costs no Accessibility permission, no
#: Input Monitoring, and no signed bundle to ask for them from. That is the one thing
#: Flow Lite can do that a native app driving a system hotkey cannot.
#:
#: 300 ms because three gestures now share one button and the other two are older: a
#: deliberate click is well under 200 ms, and a drag declares itself by moving. Slop is
#: 4 px rather than 0 because a hand resting on a mouse is not perfectly still, and a
#: hold that lost its nerve on one pixel of tremor would be a gesture nobody could rely
#: on.
PILL_HOLD_SEC = 0.30
PILL_DRAG_SLOP = 4

#: How long the release waits for the decode it is going to paste.
#:
#: The paste cannot be synchronous. A final decode measured 0.7-7 s on the machine this
#: was built for, and the release has to return to the frame loop long before that. So
#: the wait is a state, and this is its ceiling.
#:
#: Fifteen seconds is past the worst final in that trace by a wide margin, and the
#: behaviour at the ceiling is not a discard: the words are in the draft, on screen,
#: and the note points at the Send chip. A paste that lands a minute late would arrive
#: in whatever window the user has since moved to, which is worse than not pasting.
PTT_PASTE_WAIT_SEC = 15.0

#: Unified with `CARD_W` (decisions.md 2026-08-09, Phase 6): the widest state either
#: panel reaches is the draft's full rescue row — Refine, Continue, Edit, "Was a
#: command", Send, 345 px of chip width — and at the old 380 that left `chip_row_gap`
#: exactly 17 px of slack across four gaps, a rule that held only until a label grew.
#: At 420 the same row has 57 px, and the two panels that already dock to one pill at
#: one width (Phase 5) now share the width they draw at, too.
BUBBLE_W = 420
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

#: How tall the draft may draw before the rest of it goes above the fold.
#:
#: Live at the desk on 2026-08-02 a very long dictation sized this window **15 153 px tall
#: inside a 672 px work area**, which put the Send chip — the last exit still working, once
#: the mic had overflowed and the models had unloaded — twenty screens below the bottom of
#: the display. A draft must never disable its own exits, and the chip row is drawn from
#: `self._h`, so bounding the body is what keeps the chips reachable.
#:
#: 340 px is 20 lines at the 17 px the body font measures, and it is sized against the work
#: area rather than against taste: with a partial, an indicator and a two-line note above
#: the chips, the whole window comes to ~500 px on the 1280×672 desktop this was measured
#: on, which leaves the pill its own room underneath.
BODY_MAX_H = 340

#: The tallest a panel band may be, and no longer the height it always is.
#:
#: **This was a fixed height, and the reference says it should not be.** A demo of
#: FluidVoice, read frame by frame, settles it: the overlay's bottom edge is at y=554 in
#: every frame from idle through three lines of growth, and the box is *snug* around the
#: text in each one — two lines at 0:05, two at 0:08, three at 0:11. It never holds empty
#: space. Pinning the height bought stability at the price of a hole in the middle of the
#: window, which is the same complaint the resizing caused, wearing different clothes.
#:
#: What that overlay does instead is size to its content and *debounce* the resize —
#: `scheduleSizeAndPositionUpdate`, 80 ms, cancel-and-reschedule, with
#: `animationBehavior = .none`. Streaming partials coalesce into one step instead of
#: thirty resizes a second. Flow gets the same result without a timer, by snapping to
#: whole body lines (`_settled_h`): a height that can only change when the text gains or
#: loses a *line* changes a handful of times an utterance, and a timer that has to be
#: cancelled correctly from a render loop is a thing to get wrong.
#: The slot at the left of the row that names the window Flow is aimed at.
#:
#: **The name first, the icon later.** Asked for as an icon — "if i am on notepad i see
#: notepad icon and when i am on claude ide i see claude icon" — and the name is the half
#: that costs nothing: `_track_target` already resolves the foreground process for the
#: paste, on the edge rather than per frame, so `session.target_app` is sitting there
#: reading `claude.exe`. The picture needs `ExtractIconExW`, then `GetIconInfo` and
#: `GetDIBits` to get pixels into a `PhotoImage`, which is a different size of job.
#:
#: **Fixed width, so nothing moves.** A slot that sized itself to the name would shift
#: the mic, the meter and every icon each time you changed window — which is the motion
#: this surface spent a night removing. Names longer than it fits are cut, because a
#: layout that stays still is worth more than the tail of a process name.
#:
#: Reserved only where there is something to put in it: Lite does not track the
#: foreground window at all, so on a Mac the row is exactly what it was.
APP_SLOT_W = 72
APP_SLOT_GAP = 10

#: How many characters fit. Counted rather than measured, because `_draw` runs thirty
#: times a second and `bbox` on every frame to bound a string that changes a few times an
#: hour is a poor trade. Ten is conservative at the 11 px note font — the slot is 72 px
#: and ten characters of it measure under 60.
APP_NAME_CHARS = 10

#: The shell's corner radius.
#:
#: 8 px until somebody looked at it beside the thing it is modelled on and said "the
#: window currently it's square box". They were right: at 420x224 an 8 px corner is a
#: rounded rectangle in name only, and FluidVoice's overlay — the reference this surface
#: has been chasing all along — is visibly a soft-cornered slab.
#:
#: `PAD` stayed at 14, which was worth checking rather than assuming: at this radius the
#: curve only bites the first ~5 px of each edge, and the body's first line and the row's
#: app name both start below and right of that. The mock-up moved padding to 16 because
#: its corner is drawn by CSS on the frame itself; here the chrome is drawn *inside* the
#: canvas and the arc never reaches the text.
PANEL_R = 18

#: One hue per row icon, all at the same chroma and lightness in oklch so no control
#: shouts louder than another: `oklch(0.80 0.12 H)` at 85, 200 and 340.
#:
#: **Deliberately clear of every hue that already means something here.** Green is
#: capturing, blue is waiting, violet is the conversation card and red is an error — a
#: settings gear in Flow's green would read as "listening", which is the one thing a
#: control must never do. So the three sit in gaps the state palette does not use.
#:
#: The mic and the meter beside them stay on `accent`, because those two *are* the state
#: readout. Colour on the row means "this is a control"; colour on the meter means "this
#: is what Flow is doing".
ICON_SETTINGS = "#E1B75C"  # gold
ICON_VOICE = "#43D5DC"     # cyan
ICON_MODE = "#F19FD6"      # pink

#: Room for the three icons that sit between the meter and the status word: settings,
#: voice, mode.
#:
#: **They were a strip above the draft first, and the strip was wrong.** Written from
#: "Dictate and Converse for sure Then workspace and voices", it put a chip and two
#: labels across the top of the panel — and seeing it, the owner's answer was "Not
#: looking good instead after progress bar add settings icon ... and top you can remove
#: it". They were right. Words that name a setting are a *sentence about* the app; the
#: row is where the app already says what it is doing, with a drawn mic and a drawn
#: meter, and three more drawn marks belong there rather than in a band of prose.
#:
#: It also costs nothing when idle, which the strip could not: the row is on screen
#: either way.
ICON_SIZE = 16
ICON_GAP = 12

#: A glyph for every secondary command, so the row of words above the draft becomes a
#: cluster of marks in the corner.
#:
#: **They sit in a band of their own, above the text and right-aligned, not beside it.**
#: The first sketch put them next to the words, and drawing it made the flaw plain: a
#: cluster of four takes ~134 px, and a body column beside it loses a third of its width
#: on *every* line — the opposite of what moving them was supposed to buy. A band costs
#: 34 px of height once, and the draft keeps all 392 px of its column.
#:
#: Every glyph is drawn, like the mic and the meter: a font that is missing or
#: substituted turns a control into a box.
COMMAND_H = 26
COMMAND_GAP = 6

#: What the cluster costs the panel: the band, plus the air under it.
COMMAND_BAND = COMMAND_H + 8

#: The band of command marks is furniture, not content, so it goes *on top of* the
#: ceiling rather than out of the draft's share — the same call `SETTINGS_H` needed, and
#: the same failure if it is not made: the live partial's own cap is a flat 70 px, and on
#: a panel pegged at the old ceiling it runs straight through the note and the foot.
PANEL_MAX_H = 184 + COMMAND_BAND

#: The shortest a band gets, so a one-word draft still has a panel rather than a sliver.
PANEL_MIN_H = 96

#: What the body font measures per line — the number `BODY_MAX_H` is already built from
#: ("340 px is 20 lines at the 17 px the body font measures"). Named here because the
#: band now steps by it.
BODY_LINE_H = 17

#: What one line of `FONT_NOTE` measures. The note shares the chip row now, so this is
#: what decides where its baseline sits in a 26 px chip and how much a second line costs.
NOTE_LINE_H = 14

#: The live partial's own ceiling, and it needs one for the same reason the draft does:
#: it is wrapped to the full body column, so it is a multi-line block whose length nobody
#: chose. Five lines at the 14 px `FONT_NOTE` measures.
#:
#: Smaller than `BODY_MAX_H` because the two are not the same kind of text. The draft is
#: what you are working on; the partial is the sentence still arriving, and it becomes the
#: draft the moment it lands. Letting it grow to twenty lines would push the words already
#: settled off the top of the panel to make room for words that are about to be re-drawn
#: as body text anyway. Past this, `_partial_slot` keeps the **tail** — the newest words,
#: which are the ones being spoken and the only ones worth watching arrive.
PARTIAL_MAX_H = 70

#: The way back, beside the fact — the design pass asked for both in one breath. It sits
#: on the note's own row rather than in the chip row: the chips act on the draft as a
#: whole, and this acts on the one edit the sentence beside it is describing.
UNDO_LABEL = "Undo"
#: Its drawn width — 5.4 px a character at `FONT_NOTE`, the figure measured for the type
#: scale, plus two so a wrapped note never quite touches it. Arithmetic rather than a
#: canvas probe for the reason `chip_w` is: this is read while deciding a layout, and the
#: measuring fake the layout tests use answers `bbox` for height and not for width.
UNDO_W = int(len(UNDO_LABEL) * 5.4) + 2

#: Air below the partial, before the indicator or the note. Six, the same as the draft
#: body's — the two used to be a 34 px reservation against a 28 px advance, two numbers
#: for one gap that nothing made agree.
PARTIAL_GAP = 6

#: Characters a line of body text holds, measured on the real canvas at the body font and
#: the shipped 392 px column (`BUBBLE_W - 2 * PAD`): 3 160 characters of ordinary prose
#: wrapped to 51 lines, so 62.0. Two things read it, and neither may cost a layout — how
#: much draft is worth handing the canvas, and how many lines are above what it shows.
#:
#: **Rebound by `apply_panel_width` at launch**, because the column is a setting now.
#: This is the value at the shipped width, kept here so the module still reads straight
#: through and so a launch that never calls that function is the launch Flow always had.
#: The old 56 was measured at a 352 px column — `380 - 2 * PAD`, the bubble before
#: Phase 6 — and stayed one panel width behind until the measurement was re-taken; see
#: `_CHARS_PER_PX`.
BODY_CHARS_PER_LINE = 62

#: The window of draft actually laid out per event, and the reason render cost stops
#: growing: `BODY_MAX_H` holds 20 lines, this is enough characters for about 28 of them, so
#: the visible tail is always full even where the text wraps early — and a two-hour
#: dictation is laid out at the same cost as a two-minute one (invariant 7, extended to
#: rendering). Lines, not characters, are what is held constant here: the re-measured
#: column holds more per line, so the character count moved with it and the 28 did not.
#: Measured before and after on the real canvas at the 392 px column: 0.8 / 14.1 /
#: 221.3 ms at 1k / 10k / 50k characters, and flat at ~1.4 ms afterwards. (The older
#: 2.4 / 32.7 / 476.7 in this comment were the same shape on a slower machine.)
BODY_TAIL_CHARS = 1750

#: How far past the cut to look for a space before giving up and cutting mid-word.
#: Bounded, because a scan that can run the length of the draft is the cost being avoided.
BODY_BOUNDARY_SCAN = 200

#: The panel widths on offer, and why the list starts where it does rather than lower.
#:
#: 420 is a **floor**, not a default somebody liked. Two measured rows put it there:
#: the bubble's five-chip row runs to 345 px (`chip_row_gap`, which records that 380
#: clipped Send by half a label), and the card's runs to 377 of the same 420. A "small"
#: option would have to either drop a chip or ship a row that clips, so there is not
#: one — this is a setting for people who want the draft easier to read, and every
#: direction that helps with that is up.
#:
#: Named rather than free-form for the reason `KEYS` is: three widths that have each
#: been drawn are worth more than an integer nobody has rendered at.
PANEL_WIDTHS: dict[str, int] = {"regular": 420, "large": 520, "larger": 640}
PANEL_DEFAULT = "regular"

#: Where the stack sits. `"bottom"` is bottom-centre of the monitor under the pointer,
#: which is FluidVoice's placement (`BottomOverlayView.positionWindow`) and now Flow's
#: default; `"corner"` is the bottom-right Flow shipped. `Pill._placed` carries the
#: argument for the change. Named rather than free-form for `KEYS`' reason — a position
#: somebody has actually looked at beats a pair of coordinates nobody has rendered.
#: What each chord gesture is called in the menu. Phrased as what it *does* rather
#: than as its name, because "hold" and "toggle" are the words in the profile and this
#: is the row somebody reads once while deciding — the whole sentence is the label.
#: What each gesture is called wherever a user reads it: the Settings menu, the note
#: after a switch, and the startup line.
#:
#: "Push to talk" by name, and the owner asked for it by name — "I think I like the
#: wording push to talk the default so it's more clear". The label used to describe the
#: mechanics only ("Hold to talk, release to send"), which is accurate and makes somebody
#: work out what it is. Push-to-talk is a thing people already know from a decade of
#: voice chat, so naming it does the explaining, and the mechanics still follow it for
#: anyone who has not met the term.
GESTURE_LABELS = {
    "hold": "Push to talk - hold to speak, release to send",
    "toggle": "Toggle - press to start, press again to stop",
}

PLACES = ("bottom", "corner")
PLACE_DEFAULT = "bottom"
PLACE = PLACE_DEFAULT

#: How far above the work area's bottom edge the stack stands, in pixels.
#:
#: FluidVoice exposes this as `overlayBottomOffset` and so does Flow, for the reason
#: they do: the bottom of the screen is where a taskbar auto-hides, where a browser
#: puts its download shelf, and where some apps park a status bar, so the one number
#: that makes the overlay sit clear of all that is worth a setting. 24 rather than
#: their 0 because Flow's stack has a pill under the panel and the pill is the part
#: that would touch the edge.
PANEL_BOTTOM_OFFSET = 24


def apply_place(name: str) -> None:
    """Set where the stack sits. Call before the first draw, beside `apply_panel_width`.

    A module global for that function's reason and with the same concession behind it:
    the alternative is threading a placement through every window that positions itself,
    and rebinding one name before anything is drawn is the smaller change whose failure
    mode is visible immediately. Unknown names fall back rather than raising — this
    arrives from a hand-edited profile, and a typo should cost the setting, not the app.
    """
    global PLACE
    PLACE = name if name in PLACES else PLACE_DEFAULT

#: Body characters per line, per pixel of column. Kept as a *ratio* because the column
#: is no longer a fixed number: a wider panel holds proportionally more, and a
#: `BODY_CHARS_PER_LINE` frozen at one width would under-feed the canvas at 640 px and
#: quietly put the bottom of the draft below the fold.
#:
#: **Anchored at 420, which is now also where the measurement was taken.** The ratio
#: behind the old 56 came from a 352 px column — `380 - 2 * PAD`, the bubble *before*
#: Phase 6 took it to 420 — so it was one panel width behind, and the setting deliberately
#: reproduced it rather than smuggle a behaviour change into a size option. The
#: measurement has since been re-taken by the same method at the shipped 392 px column
#: (3 160 characters of prose to 51 lines, 62.0 a line), and this is that figure.
#:
#: Still written as `62 / 392` rather than the raw 0.1581 so the shipped width comes back
#: exactly, and so the number a reader can check against the canvas is the one in the
#: source.
_CHARS_PER_PX = 62 / (420 - 2 * PAD)

#: Lines of draft handed to the canvas per layout, which is what `BODY_TAIL_CHARS`
#: actually encodes: `BODY_MAX_H` shows 20, and about 28 are laid out so the visible
#: tail is full even where the text wraps early. Held constant across widths, so the
#: render-cost invariant (7) survives a wider panel instead of being re-measured.
_TAIL_LINES = 1750 / 62


def apply_panel_width(width: int) -> None:
    """Set the panel width and everything measured off it. Call before the first draw.

    Module globals rather than instance state, and that is a deliberate concession
    rather than a preference. `BUBBLE_W` and `CARD_W` are read from roughly twenty
    places across two window classes and the free functions that draw their chrome, and
    threading a width through all of them would be a large refactor whose only new
    behaviour is this one setting. Rebinding three derived numbers once, before anything
    is drawn, is the smaller change and the one whose failure mode is visible
    immediately.

    Clamped at the floor rather than trusted. The number can come from a hand-edited
    profile, and a panel narrower than its own chip row is a window whose Send button is
    half off the edge — the one control that must never be unreachable.
    """
    global BUBBLE_W, CARD_W, BODY_CHARS_PER_LINE, BODY_TAIL_CHARS
    BUBBLE_W = CARD_W = max(int(width), PANEL_WIDTHS[PANEL_DEFAULT])
    BODY_CHARS_PER_LINE = max(1, int((BUBBLE_W - 2 * PAD) * _CHARS_PER_PX))
    BODY_TAIL_CHARS = int(BODY_CHARS_PER_LINE * _TAIL_LINES)


def panel_width(name) -> int:
    """A width for a profile value, falling back to the shipped one.

    Anything unknown is the default rather than a refusal, which is the opposite of how
    `hotkey.parse` treats a bad combo — and the difference is what the two settings cost
    when wrong. A hotkey that silently fell back would leave somebody pressing keys that
    do nothing with no way to find out; a panel that falls back is a window that is
    visibly not the size they asked for, and the evidence is on the screen.
    """
    if isinstance(name, str):
        return PANEL_WIDTHS.get(name.strip().lower(), PANEL_WIDTHS[PANEL_DEFAULT])
    return PANEL_WIDTHS[PANEL_DEFAULT]


#: The line saying what is not in the window, at the note's font plus its gap. One number
#: for both of them — `… N earlier lines` above a draft and `… N more lines` below an
#: answer — because they are the same line in the same font pointing opposite ways.
BODY_ELIDED_H = 17

#: Air between the bubble and every edge of the work area — the same number the window is
#: bounded by and the number it is clamped with, because they have to agree and nothing but
#: this made them. It is what turns the clamp into a proof: with the height fitted to
#: `work − 2 × EDGE_AIR`, `max(top + air, min(y, bottom − h − air))` cannot put either edge
#: outside, at any pill position.
#:
#: The measurement that earned the fit: item 37 capped the *draft* body and left the reply
#: path alone, so a 4 000-character answer still sized the window **1 459 px** and a 12 000-
#: character artifact **4 179 px** — both pinned at `top + 8` on a 672 px desktop, at all
#: four pill corners, which put the chip row at screen y **1 427** and **4 147**. The cap
#: bounded one path's size; nothing bounded the window, so the exits went off the bottom of
#: the display exactly as they had off the draft.
EDGE_AIR = 8

#: The gutter the editor's scroll bar lives in, taken off the box's width.
#:
#: The bar is on the canvas rather than inside the `tk.Text` for one reason: dragging
#: inside a text box *selects*, and taking that away to add a scroll gesture would be
#: removing an editing action to add a reading one. So the wheel goes on the box, where
#: it costs nothing, and the drag goes on a gutter beside it.
EDIT_GUTTER = 12

#: How many times the window may be measured and shrunk before it is drawn. Each probe is
#: over at most `BODY_TAIL_CHARS`, so the ceiling on one render is a small multiple of a
#: fixed cost rather than anything to do with the draft. Two is what it takes in practice;
#: the third is there so the loop has an end that does not depend on the text.
BODY_PROBES = 3

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
#: Set just above what the whole sheet measures, so a display with the room shows all of
#: it and anything added past that scrolls rather than growing the window off the bottom
#: of the screen. Re-measured whenever the sheet grows, which is the maintenance this
#: number exists to need: 1025 px when the window was built, and **1174 px** since item
#: 71 added the colour legend permanently, and **1212 px** since the two note verbs
#: joined the command table — measured with all five hotkeys registered, which is the
#: tallest the sheet gets, because a machine where every combo was taken renders fewer
#: rows rather than more.
#:
#: Raised rather than paid for by trimming the sheet, which is the call item 71 made and
#: for the same reason: the content is what somebody came for, and a table that dropped a
#: verb to stay under a number would leave the router holding a command the sheet does
#: not admit to having.
HELP_MAX_H = 1228
#: Air left around the window inside the work area, so it reads as floating rather than
#: as a panel wedged against the edges.
HELP_MARGIN = 48

#: How much of one Recent entry a menu row carries. A native `TrackPopupMenu` row that
#: runs the width of the screen is a menu nobody can read down, and the tap copies the
#: whole thing anyway — the same bargain the answer window strikes.
RECENT_LABEL_MAX = 56

#: The conversation card. Level with the draft bubble now (`BUBBLE_W`, Phase 6) rather
#: than wider than it — both are the same window at different moments, docked to the
#: same pill, and 420 is what the draft's own widest state was already measured to
#: need. Still narrow enough to anchor beside a pill in a corner of a 1280-wide work
#: area.
CARD_W = 420

#: A card with nothing on it yet is still a window somebody has to be able to see and
#: reach the chips on.
CARD_MIN_H = 120

#: How much of one earlier turn is laid out in the history viewport. Read from the head,
#: because a turn is read from its beginning — the opposite of the draft, which is read
#: from the end. The bound is invariant 7: twenty turns of unbounded length laid out on
#: every partial is item 37's defect with a different name on it.
CARD_TURN_CHARS = 400

#: Air between one history turn and the next, and between the question and its answer.
CARD_GAP = 8

#: What the draft bubble says when a reply arrives into a mode that has moved on.
#:
#: Wide enough for both things that come through the reply slot: an answer from the CLI,
#: and a wrap-up document. "the answer" would be a lie about the second, and naming the
#: card is what makes the sentence actionable — it says where the words went and what to
#: press, rather than only that something happened.
ANSWER_HELD = "that landed on the conversation card - switch to converse to read it"

#: How long each dot of the indeterminate-wait animation holds.
#:
#: Three dots at this cadence is a 1.2 s cycle — visibly alive without being a strobe,
#: and slow enough that the bubble repaints about 2.5 times a second instead of the 33
#: it would take to redraw every frame of the 30 ms pump. The bubble renders on events
#: and a wait has no events, so the frame is computed and compared before anything is
#: drawn; same discipline as the auto-ask countdown, for the same reason.
DOT_SEC = 0.4


#: The widest label a chip's key can ever take, when that key carries a countdown.
#:
#: A chip's width follows its label, so `Ask` → `Ask 4s` → `Ask` moved the hit region
#: under the hand every second the countdown ran. Reserving the widest form makes the
#: region stable for the whole life of the chip, at the cost of a few pixels of air on
#: the chip that is not counting — which nobody has ever complained about, and a hit
#: region that moves is what three users did complain about.
COUNTDOWN_WIDEST = {"Ask": "Ask 00s", "Bring it back": "Bring it back 00s"}


def chip_w(key: str, label: str) -> int:
    """How wide this chip is drawn. Stable across a countdown, by construction."""
    return 20 + 7 * max(len(label), len(COUNTDOWN_WIDEST.get(key, "")))


#: The gap between chips, when the row has room to spare — which is every row the
#: card ever draws and most the bubble does too.
CHIP_GAP = 8

#: `_round_rect` draws a chip's box as a *smoothed* polygon, and the smoothing curves
#: past its own corner points — measured on the real canvas at ~1 px a side, 2 px a
#: chip. Read back with `canvas.bbox()` after the fix below, the last chip's box in a
#: tight row lands exactly on `BUBBLE_W` with the reserve folded in and one pixel
#: further without it — a margin of zero is not a margin. This is that pixel back.
CHIP_ROW_RESERVE = 4


def chip_row_gap(widths: list, budget: int) -> int:
    """The widest gap `widths` can take and still fit `budget`, capped at `CHIP_GAP`.

    Measured on the bubble's five-chip row — Refine, Continue, Edit, Was a command,
    Send, the full set `can_rescue` and a held draft put on screen together in dictate
    mode — at 345 px of chip width. That was what forced `BUBBLE_W` from 380 to 420
    (Phase 6): at 380, `CHIP_GAP` between each of the four gaps made 377, past the
    366 left once `PAD` came off the window — which clipped Send at the right edge,
    roughly half the label gone. At 420 the same row has 57 px of slack, `CHIP_GAP`
    fits everywhere, and this function's real job is the row nobody has measured yet
    that eventually runs long again.

    The gap is what has slack in every row that already fits, so it is what gives:
    shrunk just enough for a wide row to fit, `CHIP_ROW_RESERVE` included, left at
    `CHIP_GAP` everywhere else. Floored at 0 rather than let a wider row still push
    past the edge — touching chips are still each their own hit region; chips run off
    the window are not.
    """
    if len(widths) <= 1:
        return CHIP_GAP
    return max(0, min(CHIP_GAP,
                       (budget - CHIP_ROW_RESERVE - sum(widths)) // (len(widths) - 1)))


def chip_tag(key: str) -> str:
    """The canvas tag for a chip, from its key.

    Spaces are removed rather than tolerated. Tk parses a `tags` string as a Tcl *list*,
    so `tags="chip-Bring it back"` does not tag one item with one name — it tags it with
    three, `chip-Put`, `it` and `back`, and every later `find_withtag` and `tag_bind`
    for the whole name then matches nothing. That is not hypothetical: it is why the
    "Was a command" chip could be drawn and could not be clicked.
    """
    return "chip-" + key.replace(" ", "-")


def body_window(text: str, budget: int) -> tuple[str, int]:
    """The last `budget` characters of `text`, and how many lines were left above them.

    The cut walks forward to the next whitespace so the window opens on a whole word
    rather than mid-syllable, which is the difference between a draft that scrolled and
    one that looks corrupted.

    The line count is wraps plus explicit breaks, from `BODY_CHARS_PER_LINE` — a measured
    average, not a layout. Laying the head out to count it exactly is precisely the cost
    this function exists to avoid, and the number's job is to tell somebody how much is
    above them rather than to be re-derivable to the line.
    """
    if len(text) <= budget:
        return text, 0
    cut = len(text) - budget
    nudge = next((i for i, ch in enumerate(text[cut:cut + BODY_BOUNDARY_SCAN])
                  if ch.isspace()), -1)
    if nudge >= 0:
        cut += nudge + 1
    head = text[:cut]
    earlier = head.count("\n") + max(1, -(-len(head) // BODY_CHARS_PER_LINE))
    return text[cut:], earlier


def head_window(text: str, budget: int) -> str:
    """The first `budget` characters of `text`, cut back to a whole word.

    The mirror of `body_window`, and deliberately a **separate function** rather than that
    one with a direction argument: the two windows point opposite ways for different
    reasons, and one function with a flag is one call site away from a draft that windows
    its head — which is the defect item 37 fixed.

    A draft grows at the end and the newest words are the ones being worked on, so its
    window follows the tail. An answer is read from its first line and that is where triage
    happens, so its window holds the head.

    No line count comes back from here, unlike `body_window`. The reply's is *measured* off
    the canvas rather than estimated — see `ConversationCard._answer_slot` for why.
    """
    if len(text) <= budget:
        return text
    cut = budget
    nudge = next((i for i, ch in enumerate(text[cut:cut + BODY_BOUNDARY_SCAN])
                  if ch.isspace()), -1)
    if nudge >= 0:
        return text[:cut + nudge]
    # No whitespace within reach: walk back instead, so the window still closes on a word
    # rather than mid-syllable. A single unbroken run longer than the scan is a URL or a
    # token, and cutting one of those anywhere is the same amount of wrong.
    back = text.rfind(" ", max(0, cut - BODY_BOUNDARY_SCAN), cut)
    return text[:back] if back > 0 else text[:cut]


def _round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle via a smoothed polygon — no image assets, no dependency.

    `r` is one radius for all four corners, or `(top_left, top_right, bottom_right,
    bottom_left)` for a mix — a docked pill or panel squares off only the corners on
    the seam it shares, and a smoothed polygon squares a corner cleanly the moment its
    two control points collapse onto the corner itself (`r=0` there).
    """
    tl, tr, br, bl = (r, r, r, r) if isinstance(r, (int, float)) else r
    pts = [
        x1 + tl, y1, x2 - tr, y1, x2, y1, x2, y1 + tr, x2, y2 - br, x2, y2,
        x2 - br, y2, x1 + bl, y2, x1, y2, x1, y2 - bl, x1, y1 + tl, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


def _mix(a: str, b: str, t: float) -> str:
    """`a` at `t=0`, `b` at `t=1`, a `#rrggbb` blend of the two in between.

    Every §07 animation that changes a colour goes through here, and none of them can
    use alpha to do it: these windows are binary-transparent (decisions.md 2026-08-09,
    the reason the whole elevation is opaque hairlines), so "opacity .25" for a waiting
    dot means 25 % of the way from `SHELL` to the accent, not 25 % alpha over it.

    Clamped rather than asserted: `t` is a frame counter divided by a frame count, and a
    tick that runs long is not a reason to raise inside a repaint.

    The two ends return their own argument rather than a re-rendered blend of it, and
    that is not just the cheap path. Round-tripping `HEARING` through here produced
    `#3ecf8e` — the same colour, a different string — and every `accent == HEARING` in
    this file and its tests would have started answering False at rest, which is when
    the pill spends almost all of its life.
    """
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    return "#%02X%02X%02X" % tuple(
        round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t)
        for i in (1, 3, 5)
    )


def app_label(process: str) -> str:
    """`claude.exe` -> `Claude`. What the row shows for the window Flow is aimed at.

    The extension goes because it is noise in a name; the capital is added only when the
    stem is entirely lower case, so `Code` and `WindowsTerminal` keep the shape their
    authors gave them and `notepad` gets the one it deserves.

    Cut at the end, not the start. That is the opposite of what the draft body does, and
    for the opposite reason: a draft is windowed to its tail because the newest words are
    the ones being spoken, while an application is recognised by its *head* —
    `WindowsTe…` is obviously Windows Terminal and `…sTerminal` is obviously
    nothing.
    """
    # A non-string is no name. `session.target_app` is `""` until the first foreground
    # window resolves, and a `Mock` in any fixture that builds a pill with `__new__` —
    # neither of which should reach the string operations below.
    if not isinstance(process, str):
        return ""
    stem = process.rsplit(".", 1)[0].strip()
    if not stem:
        return ""
    if stem.islower():
        stem = stem[:1].upper() + stem[1:]
    if len(stem) > APP_NAME_CHARS:
        return stem[:APP_NAME_CHARS - 1] + "…"
    return stem


#: The gear's three radii, as fractions of `ICON_SIZE`: the tooth tip, the body it sits
#: on, and the hole in the middle.
_GEAR_TIP, _GEAR_BODY, _GEAR_HUB = 0.47, 0.34, 0.14

#: Half a tooth, in radians, at the body and at the tip. Narrower at the tip is what
#: makes a tooth a tooth rather than a spoke.
_GEAR_WIDE, _GEAR_NARROW = 0.21, 0.13


def _gear(c: tk.Canvas, cx: float, cy: float, colour: str, tags) -> None:
    """A settings gear, drawn rather than fonted.

    Same reasoning as the mic glyph beside it: a font that is missing, substituted or
    scaled differently turns a control into a box, and the one thing every control on
    this row has to be is recognisable.

    **The first version was spokes on a ring and it read as a sun.** Eight lines poking
    out of a circle is what an asterisk looks like; a gear is a solid body with
    *trapezoidal* teeth and a hole through the middle, and at sixteen pixels the hole is
    what carries it. So: eight tapered quads on a filled disc, then the hub punched back
    out in `SHELL`. Nothing here composites — the canvas has no alpha — so punching a
    hole means drawing the background colour over the middle, which is exact as long as
    the row's fill is the one behind it.
    """
    size = ICON_SIZE
    for i in range(8):
        a = math.pi * i / 4
        corners = []
        for radius, half in ((_GEAR_BODY, _GEAR_WIDE), (_GEAR_TIP, _GEAR_NARROW)):
            for side in (-1, 1):
                angle = a + side * half
                corners.append((cx + math.cos(angle) * radius * size,
                                cy + math.sin(angle) * radius * size))
        # body-left, body-right, tip-right, tip-left: a quad walked in order, so the
        # tooth is a trapezoid rather than a bow tie.
        c.create_polygon(*corners[0], *corners[1], *corners[3], *corners[2],
                         fill=colour, outline=colour, tags=tags)
    body = _GEAR_BODY * size
    c.create_oval(cx - body, cy - body, cx + body, cy + body,
                  fill=colour, outline=colour, tags=tags)
    hub = _GEAR_HUB * size
    c.create_oval(cx - hub, cy - hub, cx + hub, cy + hub,
                  fill=SHELL, outline=SHELL, tags=tags)


def _speaker(c: tk.Canvas, cx: float, cy: float, colour: str, muted: bool, tags) -> None:
    """A speaker, with a slash through it when replies are muted.

    The slash rather than a different colour or a missing icon: "off" has to be legible
    without remembering what "on" looked like, and an icon that disappears when a setting
    is off is a setting nobody can find their way back to.
    """
    r = ICON_SIZE / 2
    c.create_rectangle(cx - r, cy - 3, cx - r + 4, cy + 3,
                       fill=colour, outline=colour, tags=tags)
    c.create_polygon(cx - r + 4, cy - 3, cx - 1, cy - r, cx - 1, cy + r,
                     cx - r + 4, cy + 3, fill=colour, outline=colour, tags=tags)
    if muted:
        c.create_line(cx + 1, cy - 5, cx + r, cy + 5, fill=colour, width=2, tags=tags)
    else:
        for i in (0, 1):
            c.create_arc(cx - 1 + i * 4, cy - 5 - i * 3, cx + 5 + i * 4, cy + 5 + i * 3,
                         start=-60, extent=120, style=tk.ARC,
                         outline=colour, width=2, tags=tags)


def _mode_glyph(c: tk.Canvas, cx: float, cy: float, colour: str, converse: bool,
                tags) -> None:
    """Lines of text for dictate, a speech bubble for converse.

    The two modes differ in *where the words go* — into the window you were in, or to an
    agent that answers — so the marks are "text" and "a reply", not two abstractions
    somebody has to learn.
    """
    r = ICON_SIZE / 2
    if converse:
        _round_rect(c, cx - r, cy - r + 1, cx + r, cy + r - 4, 4,
                    fill="", outline=colour, tags=tags)
        c.create_line(cx - 2, cy + r - 4, cx - 4, cy + r, fill=colour, width=2,
                      tags=tags)
    else:
        for i, width in enumerate((r * 2, r * 2, r * 1.2)):
            y = cy - r + 3 + i * 5
            c.create_line(cx - r, y, cx - r + width, y, fill=colour, width=2, tags=tags)


def command_x(slot: int, right: float = None) -> float:
    """The right edge of the command mark in `slot`, counting from the rightmost as 0.

    Laid out right-to-left from the panel's right edge, and that is the whole reason this
    is a function worth naming. The set of secondaries changes constantly — Edit and
    Was a command come and go with what was said — so a cluster grown from the *left*
    would shift every mark under the hand each time the set changed. Anchored on the
    right, the rightmost mark is at a fixed address whatever is beside it, which is the
    argument the primary chip already won at the foot.
    """
    if right is None:
        right = BUBBLE_W - PAD
    return right - slot * (COMMAND_H + COMMAND_GAP)


def _glyph_refine(c, x, y, colour, tags) -> None:
    """A wand with a spark at its tip: this rewrites what you said.

    The first attempt was a stroke and two dots, and at sixteen pixels that reads as a
    slash with specks on it. A four-point spark — two crossed strokes, the vertical
    longer — is what carries "magic" at this size, so the wand got shorter to make room
    for it.
    """
    c.create_line(x + 2.5, y + 13.5, x + 9, y + 7, fill=colour, width=2, tags=tags)
    c.create_line(x + 11.5, y + 1.5, x + 11.5, y + 8.5, fill=colour, width=2, tags=tags)
    c.create_line(x + 8, y + 5, x + 15, y + 5, fill=colour, width=2, tags=tags)


def _glyph_continue(c, x, y, colour, tags) -> None:
    """A plus: keep going, and add to what is there."""
    c.create_line(x + 8, y + 3, x + 8, y + 13, fill=colour, width=2, tags=tags)
    c.create_line(x + 3, y + 8, x + 13, y + 8, fill=colour, width=2, tags=tags)


def _glyph_edit(c, x, y, colour, tags) -> None:
    """A pencil, nib down-left.

    The body is drawn as a thick stroke and the nib as a triangle *past* its end, which
    is the whole difference between a pencil and a diagonal line — the first version put
    a 2 px nib on a 2 px stroke and the two merged.
    """
    c.create_line(x + 5.5, y + 10.5, x + 12, y + 4, fill=colour, width=3, tags=tags)
    c.create_line(x + 10.5, y + 2.5, x + 13.5, y + 5.5, fill=colour, width=2, tags=tags)
    c.create_polygon(x + 2, y + 14, x + 3.4, y + 9.4, x + 6.6, y + 12.6,
                     fill=colour, outline=colour, tags=tags)


def _glyph_command(c, x, y, colour, tags) -> None:
    """The command loop — the owner's suggestion, and the right one.

    "for command universally we can use ⌘". It is the mark everybody already reads as
    *this was an instruction, not text*, which is exactly what the chip meant.

    Four open loops on the corners of a square, which is the knot itself: each arc
    starts and ends *on* the square's edges, so the two read as one continuous line.

    **The stroke is thinner than every other mark here, and that is the whole trick.** At
    2 px on a 6 px loop the hole is 2 px across and the glyph renders as a smudge — it
    did, twice, once as arcs and once as closed rings. 1.4 px on a 6.8 px loop leaves 4 px
    of air, which is what makes it read as ⌘ rather than as four blobs.

    Tk's arc angles are degrees counterclockwise from 3 o'clock. Each loop's 90° gap
    faces the square, so the top-left starts at 0 and sweeps 270 (east round to south),
    leaving the south-east quadrant open for the corner it joins.
    """
    r, ring = 3.4, 1.4
    for cx, cy, start_deg in ((5, 5, 0), (11, 5, 270), (5, 11, 90), (11, 11, 180)):
        c.create_arc(x + cx - r, y + cy - r, x + cx + r, y + cy + r,
                     start=start_deg, extent=270, style=tk.ARC,
                     outline=colour, width=ring, tags=tags)
    c.create_rectangle(x + 5, y + 5, x + 11, y + 11,
                       outline=colour, width=ring, fill="", tags=tags)


def _glyph_cancel(c, x, y, colour, tags) -> None:
    c.create_line(x + 4, y + 4, x + 12, y + 12, fill=colour, width=2, tags=tags)
    c.create_line(x + 12, y + 4, x + 4, y + 12, fill=colour, width=2, tags=tags)


def _glyph_take(c, x, y, colour, tags) -> None:
    """An arrow down into a line: put this answer into the draft."""
    c.create_line(x + 8, y + 2, x + 8, y + 9, fill=colour, width=2, tags=tags)
    c.create_line(x + 4.5, y + 6, x + 8, y + 9.5, fill=colour, width=2, tags=tags)
    c.create_line(x + 11.5, y + 6, x + 8, y + 9.5, fill=colour, width=2, tags=tags)
    c.create_line(x + 3, y + 13, x + 13, y + 13, fill=colour, width=2, tags=tags)


def _glyph_copy(c, x, y, colour, tags) -> None:
    """Two sheets, the near one offset — the mark every OS uses for copy."""
    c.create_rectangle(x + 2.5, y + 2.5, x + 9.5, y + 9.5,
                       outline=colour, width=2, fill="", tags=tags)
    c.create_rectangle(x + 6.5, y + 6.5, x + 13.5, y + 13.5,
                       outline=colour, width=2, fill=SHELL, tags=tags)


def _glyph_new(c, x, y, colour, tags) -> None:
    """A speech bubble with a plus: start the conversation again."""
    _round_rect(c, x + 2, y + 3, x + 14, y + 11, 3, fill="", outline=colour, tags=tags)
    c.create_line(x + 5, y + 11, x + 4, y + 14, fill=colour, width=2, tags=tags)
    c.create_line(x + 8, y + 5, x + 8, y + 9, fill=colour, width=2, tags=tags)
    c.create_line(x + 6, y + 7, x + 10, y + 7, fill=colour, width=2, tags=tags)


#: One hue per command, the four from the design canvas: `oklch(0.80 0.12 H)` at 85,
#: 200, 340 and 130. Shipped grey first, on a rule I invented — colour for settings, grey
#: for actions — and the reply was to point at the canvas: "This is what you build this is
#: what you promise". Fair. A design agreed and then quietly narrowed is worse than one
#: never shown.
COMMAND_COLOURS = {
    "Refine": "#E1B75C",
    "Continue": "#43D5DC",
    "Edit": "#F19FD6",
    "Was a command": "#A4CD79",
    "Cancel": "#F19FD6",
    "Use this": "#43D5DC",
    "Copy": "#E1B75C",
    "New conversation": "#A4CD79",
}

#: Key -> glyph. A command with no entry here keeps its word, which is the honest
#: fallback: a mark nobody can read is worse than a label that is merely longer.
COMMAND_GLYPHS = {
    "Refine": _glyph_refine,
    "Continue": _glyph_continue,
    "Edit": _glyph_edit,
    "Was a command": _glyph_command,
    "Cancel": _glyph_cancel,
    "Use this": _glyph_take,
    "Copy": _glyph_copy,
    "New conversation": _glyph_new,
}


def _row_icons(c: tk.Canvas, pill, x: float, mid: float, tags="row") -> float:
    """Settings, voice and mode, between the meter and the status word.

    Returns the x the caller may draw from next. Each is a hit region as well as a mark:
    the gear opens the same menu a right-click opens, the speaker toggles replies, and
    the mode glyph switches Dictate and Converse — the two settings the owner named as
    worth reaching without a right-click, plus the way to everything else.

    Voice is drawn only where something can speak. An icon that toggles nothing is worse
    than an absent one, and `session.speaker` is None whenever `--no-speak` or a missing
    voice engine has made replies impossible.
    """
    session = getattr(pill, "session", None)
    if session is None:
        return x
    converse = getattr(session, "mode", DICTATE) != DICTATE

    def hit(tag: str, command) -> None:
        c.tag_bind(tag, "<Button-1>", lambda _e: command())

    _gear(c, x + ICON_SIZE / 2, mid, ICON_SETTINGS, ("row-gear", tags))
    hit("row-gear", getattr(pill, "open_settings", lambda: None))
    x += ICON_SIZE + ICON_GAP

    if getattr(session, "speaker", None) is not None:
        _speaker(c, x + ICON_SIZE / 2, mid, ICON_VOICE,
                 bool(getattr(session, "muted", False)), ("row-voice", tags))
        hit("row-voice", getattr(session, "toggle_speech", lambda: None))
        x += ICON_SIZE + ICON_GAP

    _mode_glyph(c, x + ICON_SIZE / 2, mid, ICON_MODE, converse, ("row-mode", tags))
    hit("row-mode", getattr(session, "toggle_mode", lambda: None))
    return x + ICON_SIZE + ICON_GAP


def _panel_chrome(c: tk.Canvas, w: int, h: int, radius, ring_color: str,
                   tags="body", seam: str | None = None) -> None:
    """The opaque three-hairline elevation every v2 surface shares (decisions.md
    2026-08-09), replacing the single accent-coloured outline this app drew before.

    No shadow and no alpha blend — a colour-keyed window cannot composite either, so
    "elevated" is three insets instead: `ring_color` traces the outermost pixel (the
    window's own border — neutral except the one state that still earns a colour, an
    error), `RING` traces a full inset rect just inside it, and a straight line over
    that ring's top-left-to-top-right span in the brighter `RING_TOP` is the implied
    light source. Every pixel drawn is fully opaque.

    `radius` takes the same shapes `_round_rect` does — a scalar for every corner
    alike, or a `(tl, tr, br, bl)` mix for a docked pill or panel, which squares off
    only the two corners on the seam it shares with the other (Phase 5).

    `seam` says which edge, if any, this surface shares with a docked neighbour, and it
    is what makes the join read as an internal divider rather than as two windows that
    happen to touch. Squaring the corners was only half of it: both surfaces still drew
    their full chrome, so the 1 px join was actually **five** stacked lines — this
    panel's outer ring and inner ring, the neighbour's outer ring and inner ring, and
    whichever of them drew a `RING_TOP` highlight into the middle of it. The rings are
    closed outlines and cannot omit one side, so the seam edge is overpainted back to
    `SHELL` afterwards, and exactly one `RING` line is drawn by the surface *above* the
    join. The one below draws nothing there at all.
    """
    corners = (radius, radius, radius, radius) if isinstance(radius, (int, float)) \
        else tuple(radius)
    inner = tuple(max(0, r - 3) for r in corners)
    _round_rect(c, 1, 1, w - 1, h - 1, corners, fill=SHELL, outline=ring_color, tags=tags)
    _round_rect(c, 4, 4, w - 4, h - 4, inner, fill="", outline=RING, tags=tags)
    if seam != "top":
        # The light source, and never into a seam: a bright line down the middle of the
        # join is the one mark that makes two surfaces unmistakably two.
        c.create_line(4 + inner[0], 4, w - 4 - inner[1], 4, fill=RING_TOP, tags=tags)
    if seam == "top":
        # Through 5, not 4. The inner ring is drawn *at* y=4, so a fill that stopped
        # there left it standing — and a second hairline 3 px under the divider is
        # exactly the "two surfaces that happen to touch" this is here to prevent. It
        # went unseen while these were two windows, because a 1 px window gap was
        # already drawing a darker line in the same place.
        c.create_rectangle(0, 0, w, 5, fill=SHELL, outline="", tags=tags)
    elif seam == "bottom":
        c.create_rectangle(0, h - 4, w, h, fill=SHELL, outline="", tags=tags)
        c.create_line(0, h - 1, w, h - 1, fill=RING, tags=tags)


def _dark_menu(master, **kw) -> tk.Menu:
    """Every `tk.Menu` in this app, styled once rather than at each of the dozen call
    sites that build one.

    Cheap because a Tk popup menu here is already a plain `tk.Menu` — `_menu`'s own
    comment confirms the native `TrackPopupMenu` underneath it, borrowed and handed
    back rather than replaced — so the whole of "dark theme" is `-background` and
    `-activebackground` on the widget. No `MF_OWNERDRAW`, and nothing to fall back to
    if this had not worked, because it does.
    """
    return tk.Menu(
        master, tearoff=0,
        background=CHIP, foreground=TEXT,
        activebackground=RING, activeforeground=TEXT,
        disabledforeground=DISABLED, borderwidth=0,
        **kw,
    )


class Pill(tk.Tk):
    """The always-visible control. Click to arm/disarm, drag to move."""

    #: Declared on the class, not only assigned in `__init__`, and that is load-bearing:
    #: `tk.Misc.__getattr__` forwards an unknown attribute to `self.tk`, so on an instance
    #: built with `__new__` — which is how every UI test fixture in this suite builds one
    #: — a missing name recurses until the stack ends instead of defaulting (item 32 found
    #: exactly this as a `RecursionError`). A class attribute is a real lookup that never
    #: reaches `__getattr__`; `__init__` overrides it per instance.
    lite = False
    #: Same reason, same fix, for `_draw`'s new docking read: a bare fixture that never
    #: ran `__init__` — and so never built a `bubble`/`card` to dock to — draws exactly
    #: the idle pill this default describes, rather than recursing through `front`.
    _docked_w = PILL_W
    _shell_h = PILL_H
    #: Whether the window is parked with an icon standing in for it. Class-level for the
    #: reason `lite` is: a fixture built with `__new__` must not recurse into `self.tk`.
    _hidden = False
    _tray = None
    #: Where the window was when it was hidden, as (x, foot). Restored on the way back,
    #: because somebody who dragged Flow to the left of their screen did not ask for it
    #: to reappear in the middle.
    _home = None
    #: Same reason again, for `_draw`'s motion state (§07): a bare fixture draws the
    #: resting frame these describe — not hovered, not mid-collapse, opacity untouched.
    _pointer_in = False
    _deaf_frame = 0
    _disarmed_since: float | None = None
    _hover_since: float | None = None
    _drawn_alpha = 0.94
    #: Same reason a third time, for the two §07 animations `_draw` reads: the dots'
    #: position in their 1.2 s loop, and how far the glyph has travelled toward violet.
    _dots_frame = 0
    _tint = 0.0
    _flash = 0
    #: Same reason a fourth time, for push-to-talk's two clocks. These are read by
    #: `_toggle`, `_clear` and the mode switch — three paths a fixture drives directly
    #: without ever having held the chord — so the default has to be "no hold, nothing
    #: waiting" rather than a recursion. `None` is that in both cases.
    _ptt_since: float | None = None
    _ptt_wait: float | None = None
    #: And for the three gestures now sharing the left button: when it went down, where,
    #: whether it has travelled since, whether the press turned into an utterance, and
    #: the `after` id that would turn it into one. All idle here, which is the state a
    #: fixture that never touched a mouse should read as.
    _press_at: float | None = None
    _press_xy = (0, 0)
    _press_moved = False
    _press_talking = False
    _press_timer = None
    #: And once more for the settings menu's newest row, which asks the live chord what
    #: gesture it is. `--no-hotkeys` leaves this None for real, so the default is not a
    #: fixture convenience — it is the shipped value on one of the supported launches.
    hotkeys = None

    def __init__(
        self, session: Session, on_send=None, hotkeys=None, arm=False,
        settings_path=None, lite=False,
    ) -> None:
        _load_fonts()  # before the first Tk window exists, or a font object beats it here
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
        #: The level every bar is drawn from this frame, 0…1. One number, where this
        #: used to be a `deque` of `BARS` of them: the meter blooms from its own centre
        #: now rather than scrolling a history past, so there is no past to keep. See
        #: `_bar_half_height`. The eased value still lives in `_eased_level`; this is
        #: what the last frame actually drew, which `_flatten` needs to fade from.
        self._meter_level = 0.0
        #: The level actually drawn, eased toward `session.level_db` rather than
        #: jumping to it — rise 60 ms, fall 160 ms (§07), so peaks fall slower than
        #: they rise. Only the newest sample eases; everything already in `levels` is
        #: a settled historical value the meter has already scrolled past.
        self._eased_level = 0.0
        #: How many frames into a "not hearing" run this is, so the flat-line collapse
        #: sweeps left to right over four frames (~120 ms) instead of every bar
        #: dropping in the same frame. Reset the moment hearing resumes.
        self._deaf_frame = 0
        #: When this pill was last disarmed, for the 8 s idle dim (§07) — `None`
        #: while armed, since an actively-capturing pill never dims.
        self._disarmed_since: float | None = None
        #: When the pointer last entered the pill, for the 400 ms lift back to full
        #: opacity — read once, not advanced, while `_pointer_in` (nothing animates
        #: under the hand).
        self._hover_since: float | None = None
        self.armed = False
        self._disarmed_since = time.perf_counter()  # starts disarmed, so the clock does too
        #: When the current push-to-talk hold began, or None when no chord is held. The
        #: clock exists for `PTT_MAX_HOLD_SEC`: a release can be missed — a hook the OS
        #: drops for taking too long, a lock screen, an RDP session taking the keyboard —
        #: and a hold whose end never arrives is a microphone left open indefinitely.
        self._ptt_since: float | None = None
        #: When the release happened and Flow started waiting for the decode to land, or
        #: None when nothing is waiting. The paste cannot be synchronous: a final decode
        #: measured 0.7-7 s in this user's own trace, so the release arms a wait and the
        #: frame loop finishes the gesture.
        self._ptt_wait: float | None = None
        self._flash = 0  # frames remaining of the error flash, out of `FLASH_FRAMES`
        #: Where the three waiting dots are in their 1.2 s loop, and how far the pill has
        #: travelled toward converse's violet (0 = dictate, 1 = converse). Both advance
        #: in `_frame`, on the repaint it was going to do anyway — §07's rule is that no
        #: animation here gets a timer of its own.
        self._dots_frame = 0
        self._tint = 0.0
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
        #: The opacity last written to the window, so `_apply_idle_dim` only calls
        #: `attributes("-alpha", …)` when the target has actually changed.
        self._drawn_alpha = 0.94

        #: The monitor the stack is placed against, as the two rectangles FluidVoice
        #: places against — `full` for centring, `work` for standing on. Refreshed from
        #: the pointer's monitor in `_sync_monitor`; see `_pointer_monitor`.
        self.full, self.work = _pointer_monitor(
            self.winfo_screenwidth(), self.winfo_screenheight(), self)
        self.x, self.y = self._placed(PILL_W)
        self.geometry(f"{PILL_W}x{PILL_H}+{self.x}+{self.y}")
        #: The width last drawn, so `_sync_dock` can tell whether a panel appeared or
        #: went away since the last frame — and, holding the right edge fixed, by how
        #: much the left edge has to move to match. Neither panel exists yet at this
        #: point in `__init__`, so this starts at the same idle width just drawn above.
        self._docked_w = self.pill_w
        #: How tall the one window is right now — the pill row, plus a panel band when a
        #: panel is up. Compared in `_sync_shell` so a frame that changes nothing costs
        #: no `geometry` call.
        self._shell_h = PILL_H
        #: What the notification-area icon puts its clicks on, drained in `_frame`.
        #: Built here rather than with the icon, so `_drain_tray` has something to read
        #: on every frame whether or not anybody has ever hidden the window.
        self._tray_events: queue.Queue = queue.Queue()

        self.canvas = tk.Canvas(
            self, width=BUBBLE_W, height=PILL_H, bg=self.bg, highlightthickness=0
        )
        # `place`, not `pack`: this canvas is the *foot* of a window whose top edge moves
        # when a panel opens, so it has to be positioned rather than filled.
        self.canvas.place(x=0, y=0, width=BUBBLE_W, height=PILL_H)

        self.bubble = Bubble(self)
        #: P9's own surface (decisions.md 2026-08-03, "two surfaces, two jobs"). Built
        #: here beside the bubble rather than on first use like the help window, because
        #: it has to be styled in the same breath as the other two — see below.
        self.card = ConversationCard(self)
        #: The last draft that was on screen. When the draft empties into an ask, this
        #: is the question that went — read from what was displayed rather than from
        #: `session.thread`, whose trimming is about what the CLI is told and would
        #: otherwise decide what the user can still see.
        self._last_draft = ""
        #: Whether the question for the ask now in flight has already been put on the
        #: card. `card.ask` is not idempotent — it files the current question into
        #: history and starts a new one — so it must be called exactly once per ask, and
        #: the condition that calls it fires on an event that can arrive many times
        #: while one ask is outstanding. Cleared the moment the session leaves ASKING,
        #: so asking the same question twice on purpose still shows twice.
        self._asked = False
        self._bind_drag()
        # add="+", and that is not decoration: `<Button-1>` and `<ButtonPress-1>` are
        # the same Tk event, so binding this one without it replaced the whole binding
        # list and threw away the press handler that records where in the pill it was
        # grabbed. The pill dragged — it just snapped its top-left corner to the cursor
        # first, every time.
        # Press, motion and release rather than one `<Button-1>` handler, because the
        # button now carries three gestures — see `_on_press`. `add="+"` for the reason
        # the comment above gives, which has not changed: the drag handler is bound to
        # the same event and binding without it would replace the whole list.
        self.canvas.bind("<ButtonPress-1>", self._on_press, add="+")
        self.canvas.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.canvas.bind("<B1-Motion>", self._on_motion, add="+")
        self.canvas.bind("<Button-3>", self._menu)
        # Nothing animates under the hand (§07) — the same rule `Bubble`/
        # `ConversationCard` already keep, extended to the pill's own motion.
        self.canvas.bind("<Enter>", self._enter, add="+")
        self.canvas.bind("<Leave>", self._leave, add="+")
        # No <Escape> binding. It used to be here and it could not work once the windows
        # stopped taking focus — a shortcut that silently does nothing is worse than
        # none — so quit moved to the hotkey table, which does not need focus at all.

        # Both windows exist now, which is the earliest either has a handle to set a
        # style on. Reported rather than assumed: see `_no_activate`. Built as a list
        # first because `all()` over a generator stops at the first False — which would
        # mean a pill that failed silently took the bubble down with it, unstyled.
        applied = [_no_activate(win) for win in (self, self.bubble, self.card)]
        self.no_activate = all(applied)

        self._draw()
        # Arm after the first frame is painted, so a capture failure has somewhere
        # visible to report itself.
        if self._arm_on_start:
            self.after(120, self._toggle)
        self.after(160, self._welcome)
        self.after(30, self._tick)

    # -- interaction -------------------------------------------------------

    def _bind_drag(self) -> None:
        self._drag = (0, 0)

        def press(e):
            self._drag = (e.x_root - self.x, e.y_root - self.y)

        def drag(e):
            left, top, right, bottom = self.work
            w = self.pill_w
            self.x = max(left, min(e.x_root - self._drag[0], right - w))
            self.y = max(top, min(e.y_root - self._drag[1], bottom - PILL_H))
            self.geometry(f"{w}x{PILL_H}+{self.x}+{self.y}")
            self.bubble.reposition()

        self.canvas.bind("<B1-Motion>", drag)
        self.canvas.bind("<ButtonPress-1>", press, add="+")

    # -- one button, three gestures ----------------------------------------

    def _on_press(self, e) -> None:
        """Start the clock. Which gesture this is cannot be known yet.

        `_toggle` used to be bound straight to `<Button-1>`, which in Tk is the *press* —
        so arming happened before the button came back up, and **every drag of the pill
        also toggled listening**. That was there before hold-to-talk and is fixed by the
        same change: a click is judged on release, like a button anywhere else.
        """
        self._press_at = time.perf_counter()
        self._press_xy = (e.x_root, e.y_root)
        self._press_moved = False
        self._press_talking = False
        self._press_timer = self.after(int(PILL_HOLD_SEC * 1000), self._press_held)

    def _press_held(self) -> None:
        """`PILL_HOLD_SEC` has passed with the button down and the pointer still.

        Fired by a timer rather than checked on release, and that is the whole
        difference between this and a long-click: capture has to start *while the user
        is still holding*, because the hold is the utterance. Waiting for the release to
        notice would record nothing at all.
        """
        self._press_timer = None
        if self._press_at is None or self._press_moved:
            return
        self._press_talking = True
        self._talk_start()

    def _on_release(self, _e=None) -> None:
        """Decide what the press was, now that it is over.

        Three outcomes and one rule each: a hold ends the utterance and sends it, a
        still click toggles, and a drag has already done its own job and must not do a
        second one on the way out.
        """
        if self._press_timer is not None:
            self.after_cancel(self._press_timer)
            self._press_timer = None
        talking, moved = self._press_talking, self._press_moved
        self._press_at = None
        self._press_talking = False
        if talking:
            self._talk_end(send=True)
        elif not moved:
            self._toggle()

    def _on_motion(self, e) -> None:
        """Past the slop, this press is a drag — unless it is already an utterance.

        The order matters. Once capture is open the pointer is irrelevant: somebody
        talking into a held pill may well move the mouse, and cancelling their sentence
        for it would be the gesture betraying them. Before that, motion is the thing
        that tells a drag from a hold.
        """
        if self._press_at is None or self._press_talking:
            return
        x, y = self._press_xy
        if abs(e.x_root - x) > PILL_DRAG_SLOP or abs(e.y_root - y) > PILL_DRAG_SLOP:
            self._press_moved = True

    def _toggle(self, _e=None) -> None:
        if self._ptt_since is not None:
            # The toggle hotkey pressed with the chord still held. `pause()` below would
            # bump the capture generation, which is how a deliberate stop refuses a
            # decode from before it — and the utterance being spoken *right now* is
            # exactly what that would refuse. Ending the hold first commits it.
            #
            # Not sent, because a toggle is not a release: the user reached for the
            # other control mid-sentence, and pasting on their behalf is not what
            # either gesture asked for. The words land in the draft, where Send takes
            # them. The `return` is the rest of it — the hold has already stopped
            # capture, so falling through to `pause()` would do the damage anyway.
            self._talk_end(send=False)
            return
        if self.armed:
            self.armed = False
            self._disarmed_since = time.perf_counter()  # starts the 8 s idle dim
            self.session.pause()
        else:
            try:
                self.session.start()
            except Exception as exc:
                # No microphone, device in exclusive use, driver failure. Stay disarmed
                # and say so, rather than flipping to a green pill that captures nothing.
                self._flash = FLASH_FRAMES
                self.bubble.surface(f"could not start capture: {exc}")
                self._draw()
                return
            self.armed = True
            self._disarmed_since = None  # an actively-capturing pill never dims
        self._draw()

    # -- push to talk ------------------------------------------------------

    def _talk_start(self) -> None:
        """The chord's press-down: open the microphone for as long as it is held.

        Re-entrant on purpose. A hold that is already running must not restart capture —
        the OS repeats a held key in some configurations, and a second `talk` arriving
        mid-utterance would be indistinguishable from the user having spoken into a
        microphone that had just been reopened under them.
        """
        # Hidden Flow still hears the chord — the hook is global and does not care what
        # is on screen — and a hold that showed nothing would be an open microphone with
        # no way to tell it was open, which is what invariant 4 forbids. So the window
        # comes back for the utterance, before anything else here decides not to run.
        if self._hidden:
            self.show_from_tray()
        if self._ptt_since is not None:
            return
        if getattr(self.session, "editing", False):
            # The hand editor is open, and `_pump_audio` throws away every block while it
            # is. A hold here would open the microphone, capture nothing, and end with no
            # paste and no explanation — the silent deafness invariant 4 forbids. Said
            # instead, on the surface the editor is on.
            self.front.note("editing — close the editor to dictate")
            return
        # A hold that begins while a previous release is still waiting for its decode
        # supersedes it. Not dropped — `_ptt_wait` is only the *paste*, and abandoning it
        # leaves the earlier words in the draft where the next Send will take them.
        self._ptt_wait = None
        try:
            self.session.talk_start()
        except Exception as exc:
            # No microphone, a device held exclusively elsewhere, a session already
            # closing. Same refusal `_toggle` makes, for the same reason: a green pill
            # over a dead capture is the one lie this surface must not tell.
            self._flash = FLASH_FRAMES
            self.bubble.surface(f"could not start capture: {exc}")
            self._draw()
            return
        self._ptt_since = time.perf_counter()
        self.armed = True
        self._disarmed_since = None
        self._draw()

    def _talk_end(self, *, send: bool) -> None:
        """The release: stop capturing, and hand what was said to `send` if it was clean.

        `send=False` is the `ctrl+win+d` path. The words are still committed and still
        land in the draft — nothing spoken is ever dropped for the user's convenience
        (P2) — they simply do not paste themselves into whatever window a desktop switch
        just moved to. In the overwhelmingly common case there are no words at all: the
        gate never opened in the 50 ms before the third key, so the draft stays empty and
        the whole thing is invisible.

        Idempotent against a release with no hold behind it. The OS can deliver a keyup
        whose keydown this process never saw — a chord begun before Flow launched, or
        while a UAC prompt owned the input desktop — and that must not stop a capture the
        toggle hotkey started.
        """
        if self._ptt_since is None:
            return
        self._ptt_since = None
        pending = self.session.talk_end()
        # `talk_end` emits `disarm` when the hold was what opened the microphone, and the
        # event handler clears `armed`. It deliberately does not when the hold began
        # against an already-capturing session, and this must not either: the chord gives
        # back exactly what it took.
        if not pending:
            # Nothing was said into the hold. A tap, or a shortcut. Say nothing, do
            # nothing — a note here would fire on every `ctrl+win+arrow` on the machine.
            self._draw()
            return
        self._ptt_wait = time.perf_counter() if send else None
        self._draw()

    def _pump_talk(self) -> None:
        """Finish the two halves of the gesture that cannot finish on a keystroke.

        Called every frame, and both branches are timeouts. The first is the hold whose
        release never came; the second is the paste whose decode never landed. Neither is
        hypothetical — the second is the exact state the app was in when it wedged with a
        `state -> idle` and no `final` behind it, and a wait with no ceiling is how that
        turned into a microphone open on a session nobody could reach.
        """
        now = time.perf_counter()

        if self._ptt_since is not None and now - self._ptt_since >= PTT_MAX_HOLD_SEC:
            # Treated as a release and not as a break: the user was dictating, and the
            # thing that went missing is a keystroke, not their intent. What they said is
            # committed and the draft holds it; it is not pasted, because a paste this
            # far from the gesture would land somewhere they are no longer looking.
            self._talk_end(send=False)
            self.front.note(
                f"stopped after {PTT_MAX_HOLD_SEC / 60:.0f} min — the chord was still "
                "held. What you said is here; press Send when you want it")
            return

        if self._ptt_wait is None:
            return

        # The decode has to be *finished*, not merely started. `busy` covers the worker
        # queue and the partial in flight, so this waits out a final that is still being
        # transcribed rather than pasting the partial that preceded it.
        if not self.session.busy:
            text = self.session.draft.text
            self._ptt_wait = None
            if text:
                self._send()
            return

        if now - self._ptt_wait >= PTT_PASTE_WAIT_SEC:
            self._ptt_wait = None
            # Never a silent give-up, and never a discard: the words are on screen and
            # the chip that sends them is the one the user already knows.
            self.front.note(
                f"still decoding after {PTT_PASTE_WAIT_SEC:.0f}s — not pasting on my "
                "own this late. Press Send when it lands")

    def _enter(self, _e=None) -> None:
        self._pointer_in = True
        self._hover_since = time.perf_counter()

    def _leave(self, _e=None) -> None:
        self._pointer_in = False
        self._hover_since = None

    def _apply_idle_dim(self) -> None:
        """Fade to `IDLE_DIM_ALPHA` after `IDLE_DIM_AFTER_SEC` disarmed, lift back to
        full opacity over `HOVER_LIFT_SEC` once the pointer arrives (§07).

        The lift is the one animation this pill runs *because* the pointer is in,
        rather than one it freezes for that reason — hovering is what a fade-out is
        for. Armed cancels the dim outright (`_disarmed_since` is `None`) rather than
        fading a pill that is actively capturing something.
        """
        now = time.perf_counter()
        if self._disarmed_since is None or now - self._disarmed_since < IDLE_DIM_AFTER_SEC:
            target = 1.0
        elif self._hover_since is not None:
            lifted = min(1.0, (now - self._hover_since) / HOVER_LIFT_SEC)
            target = IDLE_DIM_ALPHA + (1.0 - IDLE_DIM_ALPHA) * lifted
        else:
            target = IDLE_DIM_ALPHA
        if target != self._drawn_alpha:
            self._drawn_alpha = target
            self.attributes("-alpha", target)

    def _menu(self, e) -> None:
        """The right-click menu: six rows, each showing its own current value.

        Cut from eleven to six (decisions.md 2026-08-09, the six-row menu). The three
        that were always one tap — Listen, mode, Clear — are state to *look at* now
        rather than verbs to read carefully: a checkbox that is either checked or not,
        a cascade named for the mode it is already in. What used to sit beside them —
        Copy, New from clipboard, Recent, Clear — collapsed into **Draft**, because they
        are the verbs that act on the words, and Settings and Help were already exactly
        this shape.

        **Send left the menu entirely.** It already has three ways in — a chip under
        the cursor, a global hotkey, a spoken word — and it is the one irreversible act
        in this app; a browsing surface a hand can slip on is a bad place for a fourth.
        (An earlier design worried a menu-triggered Send would paste into whatever the
        menu itself had just focused. Checked and found false: the menu borrows the
        foreground and hands it back, and `paste_target` only ever records a window
        that is not Flow's own — so this was never the reason to cut it.)

        **The correction offers left too**, for the panel that shows the words they are
        about — see `Bubble._context_menu`. Not moved and not added: **Was a command**.
        It is already one tap, as a chip on the bubble where the utterance it rescues is
        on screen — a menu copy would be a second control for one action, in the place
        least connected to what it acts on.
        """
        m = _dark_menu(self)
        # Knowingly a second control for one action — the pill click and the arm
        # hotkey both run `_toggle`. The difference is what is left when a VM console
        # holds the keyboard for its guest (Hyper-V was the report): every hotkey dies
        # at the console, the mouse still reaches Flow, and the pill click works but
        # carries no words saying it will. A checkbox rather than a verb that flips,
        # like the mode row below: state to read, not an action about to happen.
        self._listening_var = tk.BooleanVar(value=self.armed)
        m.add_checkbutton(
            label="Listening", variable=self._listening_var,
            onvalue=True, offvalue=False, command=self._toggle,
        )
        self._mode_menu(m)
        self._draft_menu(m)
        self._settings_menu(m)
        self._help_menu(m)
        m.add_separator()
        m.add_command(label="Quit Flow", command=self.quit_app)

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

    def _mode_menu(self, parent: tk.Menu) -> None:
        """Dictate or Converse, named for the state it is in rather than the flip.

        The row used to say "Converse mode" while in Dictate — a verb suggesting an
        action about to happen — which is exactly backwards from `Listening`'s new
        checkbox and just as easy to misread mid-glance. A cascade named for *where
        you are* and a radio pair inside it reads the same way both do: state first.

        `toggle_mode` is the session's only way to change it, and it unconditionally
        flips — so each radio calls it only when it would actually change something.
        Tapping the mode already showing is a no-op, the way selecting an already-
        ticked radio anywhere else in this app is.
        """
        sub = _dark_menu(parent)
        current = self.session.mode
        self._mode_var = tk.StringVar(value="Converse" if current != DICTATE else "Dictate")

        def choose(target) -> None:
            if self.session.mode != target:
                self.session.toggle_mode()

        for name, target in (("Dictate", DICTATE), ("Converse", CONVERSE)):
            sub.add_radiobutton(
                label=name, value=name, variable=self._mode_var,
                command=lambda t=target: choose(t),
            )
        parent.add_cascade(
            label="Converse" if current != DICTATE else "Dictate", menu=sub)

    def _draft_menu(self, parent: tk.Menu) -> None:
        """The verbs that act on the words, in one place instead of four rows.

        Copy, New from clipboard, Recent and Clear were all top-level before the six-row
        menu — one tap each, at the cost of a row each. They collapse into one cascade
        for the reason Settings already had: what is left at the top is what somebody
        reaches for mid-sentence, and none of these four is that. `Notes`'s two verbs
        join them for the same reason they were never really settings — they act on the
        words too, just the ones already sent to a note.
        """
        sub = _dark_menu(parent)
        # Renamed now that "draft" is the cascade's own name rather than a repeated
        # suffix on every row inside it.
        sub.add_command(label="Copy", command=self._copy_draft)
        sub.add_command(label="New from clipboard", command=self._paste_draft)
        self._notes_menu(sub)
        self._recent_menu(sub)
        sub.add_command(label="Clear", command=self._clear)
        parent.add_cascade(label="Draft", menu=sub)

    def _panel_menu(self, parent: tk.Menu) -> None:
        """How wide the draft panel draws, chosen from the widths that have been drawn.

        **Applied immediately rather than at next launch.** Every part of both windows
        reads `BUBBLE_W` and `CARD_W` while drawing a frame rather than caching them at
        construction, so rebinding them and forcing a redraw is a complete change — and
        a size you cannot see until you restart is one nobody can choose between.

        Saved on the way through, because this is the kind of setting somebody sets once
        and would be annoyed to set again. A save that fails is said out loud rather than
        swallowed: the width is still applied, so the session honours the choice and the
        note explains why the next one will not.
        """
        sub = _dark_menu(parent)
        here = BUBBLE_W

        def choose(name: str) -> None:
            apply_panel_width(panel_width(name))
            # Both windows, because they are one window at two moments and only one of
            # them is on screen to notice the change. `_frame` re-reads the width and
            # re-lays every item it draws, so re-anchoring is the whole of the update.
            for window in (self.bubble, self.card):
                window.reposition()
            profile = getattr(self.session, "profile", None)
            if profile is None:
                # `--no-profile`. The size is applied and lasts the session, which is
                # exactly what that flag asks for, so there is nothing to report.
                return
            profile.panel = name
            # The same shape `_set_trigger` uses, and for the same reason: this is a
            # setting somebody chooses once, so a save that failed has to be visible now
            # rather than discovered at the next launch.
            if profile.save():
                self.bubble.note(f"panel size: {name}")
            else:
                self._flash = FLASH_FRAMES
                self.bubble.note(f"could not save {profile.path}")

        for name, width in PANEL_WIDTHS.items():
            sub.add_command(
                label=name.capitalize() + ("   (current)" if width == here else ""),
                command=lambda n=name: choose(n),
            )
        parent.add_cascade(label="Panel size", menu=sub)

    def _gesture_menu(self, parent: tk.Menu) -> None:
        """What the chord does, switchable while Flow is running.

        This is here because shipping push-to-talk *instead of* the toggle took a
        working gesture away from everybody who had it, with no way back short of
        editing a file — and the two are not a preference between equals, they are good
        at different things. A hold needs no decision about when you are finished and
        cannot leave a microphone running; a toggle is the only one of the two that
        survives a paragraph, a long thought with pauses in it, or hands that cannot
        hold two keys down for a minute.

        **Applied to the live hook rather than at next launch**, and that is the whole
        reason `Chord.gesture` is a plain attribute the callback reads. Switching by
        rebuilding the chord would mean unhooking and re-installing a `WH_KEYBOARD_LL`
        hook, which is the one call in that file the OS is entitled to refuse — and
        being refused *while changing a setting* would leave somebody with no chord at
        all and no obvious way back. One string assignment cannot fail.

        Absent when there is no chord to describe: `--no-chord`, `"chord": ""`, or a
        hook the OS refused. Same rule the help sheet follows — the menu says what works
        on this machine this launch.
        """
        chord = getattr(self.hotkeys, "chord", None) if self.hotkeys else None
        if chord is None:
            return
        sub = _dark_menu(parent)

        def choose(name: str) -> None:
            chord.gesture = name
            # A gesture change mid-hold would leave the release with nothing to end:
            # `_talking` is latched inside the hook and the pill is holding a `_ptt_since`
            # for a capture the new gesture has no word for. Ending it here is the same
            # tidy-up `_toggle` does, and for the same reason — the words are kept.
            if self._ptt_since is not None:
                self._talk_end(send=False)
            profile = getattr(self.session, "profile", None)
            if profile is None:
                return  # `--no-profile`: applied for this session, which is what it asks
            profile.gesture = name
            if profile.save():
                self.front.note(f"chord: {GESTURE_LABELS[name]}")
            else:
                self._flash = FLASH_FRAMES
                self.front.note(f"could not save {profile.path}")

        for name in GESTURE_LABELS:
            sub.add_command(
                label=(GESTURE_LABELS[name]
                       + ("   (current)" if name == chord.gesture else "")),
                command=lambda n=name: choose(n),
            )
        parent.add_cascade(label=f"Chord ({chord.describe()})", menu=sub)

    def _effort_menu(self, parent: tk.Menu) -> None:
        """How hard the agent CLI may think, where it offers the choice.

        Lowest by default, and that is a judgement rather than a saving: these calls are
        a *rewrite* — take what was dictated and make it read like a written prompt — and
        effort buys deliberation the task has no use for, paid for in the one currency
        that counts here, which is the user watching a spinner between finishing a
        sentence and having their words.

        Offered anyway, per level, because "make it think harder about my prompt" is a
        reasonable thing to want from a model you know.
        """
        current = getattr(self.session, "cli_effort", EFFORT_DEFAULT)
        sub = _dark_menu(parent)
        for level in EFFORTS:
            sub.add_command(
                label=level + ("   (current)" if level == current else ""),
                command=lambda v=level: self.session.set_cli_effort(v),
            )
        parent.add_cascade(label=f"Effort ({current})", menu=sub)

    def _model_menu(self, parent: tk.Menu) -> None:
        """Which model to ask the CLI for, from the names that have been used before.

        **The menu is a list of what somebody has already typed, and cannot be anything
        else.** No CLI will enumerate its models — `codex exec --help` says `-m, --model
        <MODEL>` and stops — so the names cannot be discovered, and Flow has no text
        field anywhere to type one into. Settings is a menu, not a dialog, and the
        docstring above refuses a page for exactly this reason.

        So `--cli-model` is how a name arrives, once, and it is remembered; from then on
        it is a click. The menu hides itself entirely until there is a second thing to
        choose between, the same rule the CLI picker follows.
        """
        known = tuple(getattr(getattr(self.session, "profile", None), "cli_models", ()))
        current = getattr(self.session, "cli_model", "")
        if not known:
            return
        sub = _dark_menu(parent)

        def choice(label: str, value: str) -> None:
            sub.add_command(
                label=label + ("   (current)" if value == current else ""),
                command=lambda v=value: self.session.set_cli_model(v),
            )

        choice("The CLI's own default", "")
        for name in known:
            choice(name, name)
        parent.add_cascade(label=f"Model ({current or 'default'})", menu=sub)

    def _settings_menu(self, parent: tk.Menu) -> None:
        """Everything somebody sets once, in one place they can find it twice.

        Still not a settings dialog: every entry here writes to `profile.json` or
        `lexicon.txt`, the two files that were always the settings, and the menu is the
        way to reach them without an editor. What is refused is a *page* — a surface that
        invites options to be added to it.
        """
        sub = _dark_menu(parent)
        self._settings_items(sub)
        parent.add_cascade(label="Settings", menu=sub)

    def _settings_items(self, sub: tk.Menu) -> None:
        """Everything under Settings, filled into a menu somebody else owns.

        Split out from `_settings_menu` so the gear on the row can post *this* rather
        than a menu whose only entry is a `Settings` cascade — which is what it did, and
        what the owner saw: "Remove the layer settings as clicking on icon it can open
        directly". A shortcut that costs an extra hover is not a shortcut.

        The right-click still gets the cascade, because there it sits among Mode, Draft
        and Help and has to be one of them.
        """
        self._gesture_menu(sub)
        self._trigger_menu(sub)
        self._panel_menu(sub)
        # Also the CLI marker's refresh point: a CLI installed mid-session shows up here,
        # where a press is already paying for the PATH walk `_resolved` will not repeat.
        clis = self._clis = available()
        if len(clis) > 1:
            # Offered only when there is a choice to make. Automatic tries them in order,
            # but a fallback only runs after the first one has failed — which for a
            # timeout means paying the whole wait first. Anyone who already knows which
            # CLI is answering today should be able to say so without restarting.
            picker = _dark_menu(sub)
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
        self._effort_menu(sub)
        self._model_menu(sub)
        if tray.available():
            # Offered where the other once-and-forget settings are, and only where there
            # is a notification area to hide into. `hide_to_tray` refuses rather than
            # hides if the icon does not take, so this cannot strand anybody.
            sub.add_command(label="Hide to tray", command=self.hide_to_tray)
        self._workspace_menu(sub)
        if getattr(self.session, "speaker", None) is not None:
            sub.add_command(
                label="Mute replies" if not self.session.muted else "Speak replies",
                command=self.session.toggle_speech,
            )
            self._voice_menu(sub)
        if self.session.mode != DICTATE:
            sub.add_command(
                label=AUTO_ASK_OFF_LABEL if self.session.auto_ask
                else AUTO_ASK_ON_LABEL,
                command=self.session.toggle_auto_ask,
            )
        sub.add_command(label="Open settings folder", command=self._open_settings)

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
        sub = _dark_menu(parent)
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
            self._flash = FLASH_FRAMES
            self.bubble.note(f"could not save {profile.path}")

    #: What fits in a menu row. A path is the one label here the user's filesystem
    #: wrote, so it is cut like `edits.removed_text` cuts — and from the *left*,
    #: because a path's discriminating half is its tail.
    WORKSPACE_LABEL_MAX = 60

    #: The "(not set)" row's label *and* its radio value. A stored path can never
    #: equal it: every entry in the list went through `normpath`, and this is not a
    #: path anybody's `--cwd` resolves to.
    WORKSPACE_NOT_SET = "(not set)"

    def open_settings(self) -> None:
        """Post the settings menu on its own, from the gear on the row.

        The same items the right-click builds, not a second set: everything in them is a
        dispatcher onto the session or the profile, and two of anything is two things to
        keep in step. What the gear skips is the *cascade* — posting `_settings_menu`
        gave a menu whose only row was `Settings >`, so the shortcut cost an extra hover.
        """
        self._popup_menu(self._settings_items)

    def _popup_menu(self, build) -> None:
        """Post one of the settings submenus on its own, under the pointer.

        The strip's values open the menu that already exists rather than growing a second
        implementation of the same list — the workspace recents and the voice list are
        both built with a tick showing the current choice, and two of anything is two
        things to keep in step.

        `build` is one of the `_*_menu` methods, which add a cascade to a parent. A
        throwaway parent is that cascade's home for the moment it is on screen.
        """
        parent = _dark_menu(self)
        build(parent)
        if parent.index("end") is None:
            return  # nothing to choose between — see each builder's early return
        try:
            parent.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            parent.grab_release()

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
        sub = _dark_menu(parent)
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

    #: Engine key to the heading it is listed under, in the order the sections appear.
    #: The order matches `speak._legacy`, so what the menu puts at the top is what
    #: `--voice female` would have chosen — the list and the resolver agree, which is the
    #: same discipline `speak.host` keeps between enumerating and speaking. Piper leads
    #: for the reason `_legacy` gives: it is the engine nothing leaves the machine for.
    VOICE_SECTIONS = (
        ("piper", "Piper"),
        ("edge", "Microsoft Natural"),
        ("sapi", "Windows"),
    )

    #: Above this many voices an engine is nested behind gender cascades instead of
    #: listed inline. The natural voices are 47 rows; listed flat they filled the screen,
    #: pushed Piper's two off the bottom, and made the *shorter and better* list the one
    #: you had to scroll for. Piper and the Windows nine stay inline — nesting a list you
    #: can already see costs a click and buys nothing.
    VOICE_INLINE_MAX = 12

    #: Gender values a cascade is built for, in order, with the label to put on it.
    #: Anything else — Piper's `NotSet`, mostly — collects under the last one, so a voice
    #: can never be dropped from the menu by failing to declare something.
    VOICE_GENDER_GROUPS = (("female", "Female"), ("male", "Male"), (None, "Other"))

    def _voice_menu(self, parent: tk.Menu) -> None:
        """A submenu of the voices this machine actually has, grouped by engine.

        Listed rather than cycled: "next voice" is unusable when the good one is fourth
        of nine, and the whole reason this exists is that the engine's default is the
        oldest voice on the box and nobody had ever chosen it. A tick marks the one in
        use, so the answer to "which am I hearing" is on screen and not in a log line
        that scrolled away at startup.

        Grouped once there was more than one engine to group. A flat list mixed three
        kinds of voice that differ in ways the name does not show — one is local and
        instant, one is local and needs a model downloaded, one goes over the network —
        and "Piper en_GB-cori-high" next to "Microsoft Zira" told nobody which was which.

        **Short sections inline, long ones nested, and that split came from a screenshot.**
        Grouping alone was not enough: the natural voices are 47 rows, so the menu opened
        past the bottom of the screen with arrows at both ends, and Piper's two — the
        engine you would usually want — were somewhere below the fold. Headings stay
        disabled rows for the short sections, because nesting a list you can already read
        costs a click and buys nothing; anything over `VOICE_INLINE_MAX` becomes cascades
        instead, split by gender because that is the cut people make first and the service
        states it for every voice. So the natural voices cost two rows rather than
        forty-seven, and no section can push another off the screen.

        Sections with nothing in them are skipped entirely, which is the normal case:
        with no extras installed there is one section, and it looks like the old flat
        list with a heading on top.
        """
        voices = self.session.voices()
        if not voices:
            return
        sub = _dark_menu(parent)
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
        known = {key for key, _ in self.VOICE_SECTIONS}
        for key, heading in self.VOICE_SECTIONS:
            # An engine added later and not listed here still reaches the menu, under the
            # last heading, rather than vanishing from it. A voice nobody can select is
            # the one failure this menu must not have.
            group = [v for v in voices
                     if v.engine == key or (key == "sapi" and v.engine not in known)]
            if not group:
                continue
            sub.add_separator()
            if len(group) > self.VOICE_INLINE_MAX:
                self._voice_cascades(sub, heading, group)
            else:
                sub.add_command(label=heading, state="disabled")
                for v in group:
                    self._voice_row(sub, v)
        parent.add_cascade(label="Voice", menu=sub)

    def _ask_is_new(self) -> bool:
        """True once per ask — the first empty draft that lands while one is in flight.

        The draft emptying is how the UI learns a question has gone, and it is the right
        signal, but it is not a *unique* one: more than one empty-draft event can arrive
        while a single ask is outstanding, and a slow ask leaves a long window for them.
        `ConversationCard.ask` is deliberately not idempotent — it files the current
        question into history and starts a new one, which is what makes a second question
        push the first one up — so calling it twice for one ask puts the same question on
        screen twice.

        Measured from a real session: the diag log holds exactly one `ask` (82 chars, a
        20 s timeout), and the card showed the question three times. Two extra calls, two
        extra copies. The condition used to be "is the session asking", which is a level
        and stays true for the whole wait; this makes it an edge.

        `_asked` is cleared in `_pump` on the first frame the session is no longer
        ASKING, so asking the same question again really does show it again.
        """
        if self.session.state is not State.ASKING or self._asked:
            return False
        self._asked = True
        return True

    def _voice_row(self, menu: tk.Menu, v) -> None:
        """One selectable voice. Every row in every section goes through here.

        The radio variable is shared across the cascades as well as the inline rows, so
        the tick lands on the chosen voice wherever it lives — and `value=v.name` is why
        nothing else in Flow had to learn there are three engines.
        """
        menu.add_radiobutton(
            label=v.describe(), value=v.name, variable=self._voice_var,
            command=lambda name=v.name: self.session.set_voice(name),
        )

    def _voice_cascades(self, parent: tk.Menu, heading: str, group: list) -> None:
        """A long engine as `Heading — Female` / `Heading — Male` submenus.

        Flattened one level on purpose: the obvious shape is a single "Microsoft Natural"
        cascade holding Male and Female cascades, which puts three hops between the pill
        and a voice. Hanging the gender submenus straight off the Voice menu costs the
        same two rows and one hop fewer.

        A gender with nobody in it is not rendered, so this cannot produce an empty
        submenu — and `VOICE_GENDER_GROUPS` ends in a catch-all, so a voice that declares
        no gender still appears rather than falling out of the menu.
        """
        seen: set[str] = set()
        for want, label in self.VOICE_GENDER_GROUPS:
            if want is None:
                members = [v for v in group if v.name not in seen]
            else:
                members = [v for v in group if v.gender.lower() == want]
            if not members:
                continue
            seen.update(v.name for v in members)
            inner = _dark_menu(parent)
            for v in members:
                self._voice_row(inner, v)
            parent.add_cascade(label=f"{heading} — {label}", menu=inner)

    def _notes_menu(self, parent: tk.Menu) -> None:
        """P9's two note verbs, as taps. The floor under the spoken forms.

        **Why the menu and not a chip**, which is where "Use this" and "Copy" live and
        where a reader would expect these. Measured rather than argued: the card's chip
        row already runs to **377 px of `CARD_W`'s 420**, and one more chip at its
        narrowest ("Keep", 56 px) takes it to 433 — off the card. The row cannot take
        another member without something leaving it, and nothing there is worth less
        than this.

        The split that falls out of that is better than the row would have been, so it
        is written as the design rather than as a consolation. **Keep** is frequent,
        cheap and in-the-moment, and it is one tap here. **Wrap up** happens once, and
        it is the act that writes a file — a deliberate two-step is the right cost for
        the only thing in this app that puts the user's words on disk.

        Both rows are absent rather than inert when they would do nothing, the way
        `_recent_menu` is on an empty ring: a control that lies about having something
        behind it is worse than one that is not there. So "Keep this answer" appears
        only with an answer on screen, and "Wrap up" only with notes to wrap.
        """
        session = self.session
        if getattr(session, "can_take_reply", False):
            parent.add_command(label="Keep this answer", command=session.keep_note)
        # Typed, not truthiness — `_recent_menu`'s lesson, and the same trap: every UI
        # fixture in this suite hands a Mock, and `len()` of one raises rather than
        # returning nothing.
        notes = getattr(session, "notes", None)
        held = len(notes) if isinstance(notes, Notes) else 0
        if held:
            parent.add_command(
                label=f"Wrap up ({held} note" + ("" if held == 1 else "s") + ")",
                command=session.wrap_up,
            )

    def _recent_menu(self, parent: tk.Menu) -> None:
        """The last ~20 things, truncated to a row and copyable whole.

        The reference's lesson, and the one Flow was furthest from: recovery is a
        history, not a rescue chip (decisions.md 2026-08-03). "Was a command" reaches
        one utterance back and only while the draft it landed in is still there; this
        reaches the session.

        Absent rather than inert on an empty ring, the way the trigger submenu is absent
        under `--no-profile`: a submenu that opens onto nothing is a control that lies
        about having something behind it.

        The rows are truncated and the tap copies the **whole** text — the same bargain
        the reply window strikes, and through `_copy`, which is the one clipboard borrow
        this app has.
        """
        # A list, asked for as one: an embedding or a fake session may carry no ring at
        # all, and `getattr(..., None) or []` is not the guard it looks like when the
        # attribute is a Mock — which is what every UI fixture in this suite hands it.
        items = getattr(self.session, "recent", None)
        if not isinstance(items, list) or not items:
            return
        sub = _dark_menu(parent)
        for role, text in items:
            sub.add_command(
                label=f"{role}: {fit(text, RECENT_LABEL_MAX)}",
                command=lambda t=text: self._copy_recent(t),
            )
        parent.add_cascade(label="Recent", menu=sub)

    def _copy_recent(self, text: str) -> None:
        problem = self._copy(text)
        self.front.note(problem or f"copied {len(text)} characters")

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

    def _copy_draft(self) -> None:
        """The exit that needs no model, no decode and no target window.

        Lite built `_copy` for a body with no hands; full mode gets it because that is
        exactly what is left when a render stall has taken the microphone and the spoken
        triggers with it (decisions.md, "The long-draft incident"). One tap, and the words
        are somewhere else.

        Deliberately not `send()`: that clears the draft and hands it to the paste layer,
        and the whole value of this one is that it changes nothing. Reading the draft is
        the only thing it asks the session for.
        """
        draft = getattr(self.session, "draft", None)
        text = getattr(draft, "text", "") if draft is not None else ""
        if not text:
            # Surfaced rather than noted: with no draft there is no bubble to note into,
            # and a menu entry that does nothing visible reads as broken.
            self.bubble.surface("nothing to copy — the draft is empty")
            return
        problem = self._copy(text)
        self.bubble.note(problem or "draft copied — paste it where you need it")

    def _paste_draft(self) -> None:
        """The way in, opposite `Copy draft`, which is the only way out that needs nothing.

        Tk's own clipboard rather than `inject`'s Win32 one, matching `_copy`: it is the
        same three declared dependencies on every OS, and Lite has to be able to do this
        too — a body with no hands is precisely a body that starts from a paste.

        `TclError` is the ordinary case rather than an error case. Tk raises it for an
        *empty* clipboard and for one holding something that is not text — an image, a
        file list — and neither of those is a fault worth a stack trace. Both get the
        same sentence, because from where the user is standing they are the same fact:
        there is nothing here to start from.
        """
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        refused = self.session.paste_draft(text)
        if refused:
            # Surfaced rather than noted: this runs with an empty draft and a hidden
            # bubble, which is the state it exists for, and `note()` only paints on a
            # window that is already showing. A success needs nothing here — the draft
            # event opens the window on its own.
            self.front.surface(refused)

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

        **Every send goes through here, which is what makes one line enough to stop
        push-to-talk sending twice.** There are four ways to send — this chip, the
        `send` hotkey, the spoken trigger routed as a `send` event, and converse's
        auto-ask countdown — and a release that has armed a paste is a fifth thing
        waiting to do the same job. The collision is not hypothetical: hold the chord,
        say "…and that's the plan, boom", let go, and the trigger fires a send when the
        decode routes while the release is still waiting to fire its own.

        A hold owns *one* send, and whoever gets there first has it. Cancelling the wait
        here covers all four collisions at the one point they have in common, rather
        than four guards that would have to be kept in step — and it is the right way
        round, because a send that has already happened is the one thing that proves the
        wait has nothing left to do.
        """
        self._ptt_wait = None
        text = self.session.send()
        problem = ""
        if text and self.on_send:
            # The window is chosen here, on the UI thread, from what was polled before
            # the click — not inside `paste()` after it. The handler reports back what
            # went wrong rather than printing it somewhere nobody is looking.
            #
            # Passed only when it is true, the way `DecodeWorker` passes `hotwords`: a
            # handler predating this — `send_check.py`'s fixture is one — still works.
            extra = {"submit": True} if submit else {}
            problem = self.on_send(text, self.paste_target, **extra) or ""
        elif text and self.lite:
            # The fallback, not the Lite behaviour. A handler is offered wherever Flow
            # can actually put the words in the other window — Win32 injection, or
            # System Events on a Mac — and the copy is what is left when it cannot.
            # These two used to be the other way round, so a Mac that had grown a real
            # paste path would still have copied: `lite` is about hotkeys and window
            # handles, and it was standing in for "cannot send", which it is not.
            problem = self._copy(text)
        if getattr(self.session, "mode", DICTATE) != DICTATE:
            # Converse: send() returns "" and the answer is still coming, so the bubble
            # stays up to render it and there is nothing to linger over.
            return
        if problem:
            # Flashed whether the paste failed outright or merely could not be
            # guaranteed. A terminal that will run each line as it arrives is the
            # loudest thing Flow can cause, so both deserve to be looked at.
            self._flash = FLASH_FRAMES
            self.bubble.show_sent(text, problem)
        elif text:
            self.bubble.show_sent(text)
            if self.lite and self.on_send is None:
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
            self._flash = FLASH_FRAMES
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
        sub = _dark_menu(parent)
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
        self._help.show([
            *help_rows(
                hotkeys=self.hotkeys,
                send_words=self.session.send_words,
                workspace_note=resolve_workspace(
                    getattr(self.session, "workspace", None), None
                )[1],
                lite=self.lite,
            ),
            # Two quiet rows at the bottom, in the order of how much they are about this
            # machine. Both are short by construction so they clear `help.MAX_NOTE`
            # without being fitted; `test_version.py` and `test_stats.py` keep that true.
            ("gap", "", ""),
            # How much has been said today. `flow --stats` is the full answer and a GUI
            # user has no prompt open to type it into — the same gap the version row and
            # the welcome card were built for. Absent when nothing has been dictated
            # today, because a sheet is a reference to what this machine can do and a
            # zero is not one of those; `stats.today_note` argues that choice.
            *([("note", note, "")] if (note := today_note()) else []),
            # Last: the one row on the sheet that is not about this machine at all.
            # Startup names the version too, into a console a GUI user does not have open.
            ("note", f"Flow {version()}", ""),
        ])

    def _welcome(self) -> None:
        """The first minute, once (item 71).

        Every line on it was a `print()` before this: Flow says the combos it registered,
        the trigger word and that a pause sends a question — into a console a GUI user
        does not have open. Three outside users met the app without any of it
        (decisions.md 2026-08-03).

        Shown after the first frame rather than during construction, so the pill is on
        screen behind it and the card reads as belonging to something rather than as the
        whole application. `profile.welcomed` is written immediately, before anybody has
        read a word: a card shown twice is worse than one shown once, and a crash between
        showing and saving would do exactly that.
        """
        profile = getattr(self.session, "profile", None)
        if profile is None or getattr(profile, "welcomed", True):
            return
        profile.welcomed = True
        profile.save()
        if self._help is None:
            self._help = HelpWindow(self)
        self._help.show(
            welcome_rows(hotkeys=self.hotkeys, send_words=self.session.send_words,
                         lite=self.lite),
            title=WELCOME_TITLE, chip="Dismiss",
        )

    def _open_guide(self) -> None:
        try:
            open_guide()
        except OSError as exc:
            self._flash = FLASH_FRAMES
            self.bubble.note(f"could not open the guide: {exc}")

    def _clear(self) -> None:
        # Clear is the cheapest "stop" the user has, and with the microphone gated while
        # Flow talks it is one of the few ways left to cut a reply short. Doing that
        # first means one press does the obvious thing whichever is in progress.
        #
        # A pending push-to-talk paste is exactly such a thing in progress, and the
        # nastiest one to leave running: the draft is cleared here, the decode lands a
        # second later and refills it, and the wait pastes into the user's window the
        # words they just pressed a key to stop. Clear means clear.
        self._ptt_wait = None
        self.session.stop_speaking()
        self.session.draft.clear()
        self.bubble.hide()

    def hide_to_tray(self) -> bool:
        """Put Flow out of the way, with an icon to bring it back.

        The need, in the owner's words: "there are times where i wanted to dictate but at
        the same time i wanted to see but i don't want it to keep it on my screen". The
        chord still works while hidden — it is a global hook and does not care what is on
        screen — so dictating is unchanged and only the window goes.

        **The icon comes first, and hiding is conditional on it.** A window parked off the
        desktop with nothing in the notification area is a Flow that cannot be reached,
        configured or quit except through Task Manager. So `Tray.start()` is asked first
        and its answer is believed: no icon, no hiding, and a note saying so. Invariant 4
        in a new place — hidden must not mean gone.
        """
        if not tray.available():
            self.front.note("hiding needs the Windows notification area")
            return False
        if self._tray is None:
            self._tray = tray.Tray("Flow - press the chord to talk", self._tray_events)
        if not self._tray.start():
            self._flash = FLASH_FRAMES
            self.front.note("the notification area would not take an icon")
            return False
        # Where it was, as (x, foot) — the foot rather than the top, because that is
        # the edge the shell is anchored by and the one a reopened panel measures from.
        self._home = (self.x, self.y + self._shell_h)
        self._hidden = True
        park(self)
        return True

    def show_from_tray(self) -> None:
        """Bring the window back where the user left it.

        The icon stays. Somebody who hid Flow once will hide it again, and an icon that
        vanished on the first click would make the second one a trip through the menus.
        """
        if not self._hidden:
            return
        self._hidden = False
        if self._home is not None:
            x, foot = self._home
            self.x, self.y = x, foot - self._shell_h
        self._sync_shell()
        self.deiconify()
        self.lift()

    def _drain_tray(self) -> None:
        """What the icon decided, acted on from Tk's own thread.

        `tray.Tray` runs its window procedure on a thread of its own and puts strings on
        a queue rather than calling back, precisely so this is the only place Tk is
        touched — see that module's docstring for why that rule is the whole of the
        threading argument here.
        """
        while True:
            try:
                event = self._tray_events.get_nowait()
            except queue.Empty:
                return
            if event == tray.SHOW:
                self.show_from_tray()
            elif event == tray.QUIT:
                self.quit_app()

    def quit_app(self) -> None:
        # Idempotent, because ctrl+C reaches here down either of two paths and nothing
        # upstream can tell which one ran: caught in `_tick`, or escaping `mainloop` and
        # torn down by `__main__`. A second `destroy()` against an interpreter that is
        # already gone is a TclError raised while quitting — the one moment at which
        # nobody is left to act on it.
        if not self._alive:
            return
        # Cleared before anything is torn down, so a `_tick` already in flight does not
        # re-arm itself against a destroyed interpreter on its way out.
        self._alive = False
        try:
            # Before the hotkeys and before the window: an icon outliving its process is
            # a ghost in the notification area that only a hover clears, and the shell
            # gives no second chance to remove one whose window has already gone.
            if self._tray is not None:
                self._tray.stop()
            if self.hotkeys is not None:
                self.hotkeys.stop()
            self.session.close()
        finally:
            self.destroy()
            _unload_fonts()

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
        except KeyboardInterrupt:
            # ctrl+C in the terminal Flow was launched from, and it lands *here* for a
            # reason: Tcl's event loop is C, so a pending SIGINT is not raised until
            # Python bytecode runs again, and this callback is nearly all the bytecode
            # there is. The clause below cannot see it — `KeyboardInterrupt` is a
            # `BaseException` — so it used to escape into Tkinter, which prints
            # "Exception in Tkinter callback" and swallows it. That named whatever
            # `_draw` happened to be part-way through, as though the repaint had
            # crashed, and then the `finally` re-armed the loop and the pill carried on:
            # the one key everybody presses to stop a terminal program did nothing but
            # produce a traceback about polygons.
            #
            # Taken as the quit it was, and given the teardown ctrl+alt+Q gets, because
            # the alternative is not "exit slightly untidily" — it is a microphone still
            # open, a refine CLI whose `node` keeps billing for an answer nobody will
            # read, and the speaker's PowerShell left behind (`Session.close`).
            self.quit_app()
        except Exception as exc:
            self._flash = FLASH_FRAMES
            traceback.print_exc()
            # On the surface this mode owns, for the reason the reply branch is: opening
            # the bubble over a card is the same one-window rule broken, and a crash is
            # the worst moment to hand somebody a second window and no explanation of it.
            # Falling back rather than trusting it, because the surface is a plausible
            # thing to have just crashed — and a raise from *here* is what breaks the
            # `after()` chain this whole handler exists to protect.
            try:
                self.front.surface(f"{type(exc).__name__}: {exc}")
            except Exception:
                self.bubble.surface(f"{type(exc).__name__}: {exc}")
        finally:
            if self._alive:
                self.after(30, self._tick)

    @property
    def width(self) -> int:
        """This window's width, under the name `park` and the panels both use.

        The pill had no `width` while the panels did, so `park(self)` — the call that
        hides this window — reached `tk.Misc.__getattr__` and went looking for a Tcl
        command. "Hide to tray" did nothing at all, twice over: this, and a `_sync_shell`
        that put the window straight back.
        """
        return self.pill_w

    def band_h(self) -> int:
        """How tall the panel band is: `PANEL_H`, unless the desktop is smaller.

        The row's own height comes off the top of what is available, which the panels'
        `panel_h` did not do while they were windows of their own — they only had to fit
        the work area, and the pill fitted it separately. Sharing one window makes them
        one sum, and a 200 px-tall display was enough to put a 224 px shell 32 px past
        the bottom of it.
        """
        _left, top, _right, bottom = self.work
        room = (bottom - top) - 2 * EDGE_AIR - PILL_H
        return max(0, min(PANEL_MAX_H, room))

    def _placed(self, w: int) -> tuple[int, int]:
        """Where a stack `w` wide belongs on the current monitor, per `PLACE`.

        Two answers, and the setting picks between them rather than one being a
        degraded version of the other:

        `"bottom"` is FluidVoice's (`positionWindow`) — centred on the physical display,
        stood on the work area. It is the default because the corner has a problem the
        centre does not: the bottom-right of the screen is where Windows puts the tray,
        every toast notification, and most apps' own status chrome, so the one place
        Flow reserved for itself is the busiest real estate on the desktop. The centre
        is empty, it is where the eye already is, and it is the same place on every
        machine regardless of what is docked to which edge.

        `"corner"` is what Flow shipped, kept because somebody who has spent months
        with the pill in the bottom right should not have it moved by an upgrade.
        """
        if PLACE == "corner":
            _left, _top, right, bottom = self.work
            return right - w - 28, bottom - PILL_H - 24
        return bottom_centre(w, PILL_H, self.full, self.work, PANEL_BOTTOM_OFFSET)

    def _sync_monitor(self) -> None:
        """Follow the pointer's monitor, and re-place the stack when it changes.

        Flow read the work area **once, in `__init__`, from `SystemParametersInfoW`** —
        which only ever answers for the primary display. So on a two-monitor desk every
        window Flow drew was placed against a screen the user might not be looking at,
        and the clamps that keep panels on-screen were clamping to the wrong rectangle.
        That is the placement problem, and it was never a rounding error: it is the
        whole width of a monitor.

        Checked every frame and acted on only when the rectangle actually moves, which
        is the same shape `_track_target` uses for `classify` and for the same reason —
        the question is cheap, the answer changes a few times an hour, and doing the
        work unconditionally would be a `geometry` call per frame forever.
        """
        full, work = _pointer_monitor(
            self.winfo_screenwidth(), self.winfo_screenheight(), self)
        if (full, work) == (self.full, self.work):
            return
        self.full, self.work = full, work
        self.x, self.y = self._placed(self.pill_w)
        # The panels are placed *from* the pill, so moving it is the whole move — but
        # only for a panel that is up. `reposition` on a withdrawn window would place it
        # and leave it withdrawn, which is work nobody can see.
        self._sync_dock()
        for panel in (self.bubble, self.card):
            if getattr(panel, "_visible", False):
                panel.reposition()

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
            if hwnd != self.paste_target:
                # Only when the window actually changed. `classify` opens a process
                # handle, and this runs every frame — at 30 fps an `OpenProcess` per
                # frame is a cost paid forever to answer a question whose answer moves a
                # few times an hour. Resolved on the edge, remembered in between.
                self.session.target_app = classify(hwnd).process
            self.paste_target = hwnd

    @property
    def converse(self) -> bool:
        """Which job is on, and therefore which window owns the screen."""
        return getattr(self.session, "mode", DICTATE) == CONVERSE

    @property
    def front(self) -> object:
        """The surface this mode's words belong on.

        Notes, errors and partials are the three things both surfaces carry, so they go
        through one name instead of a branch at each of the four call sites — which is
        how the bubble came to be opened by a note while the card was the surface.
        """
        return self.card if self.converse else self.bubble

    def _swap_surfaces(self) -> None:
        """A mode switch is a surface switch: one window opens, the other closes.

        Exactly one is up afterwards, and the winner is opened rather than left to the
        next event — because the note that follows the mode event is the one that names
        the workshop, and `note()` only paints on a window that is already showing. That
        line has been load-bearing since item 36 and invisible whenever there was no
        draft on screen, which is most of the times somebody switches mode.
        """
        if self.converse:
            self.bubble.hide()
            self.card.show()
        else:
            self.card.close()
            self.bubble.surface("")

    def _frame(self) -> None:
        self._track_target()
        self._sync_monitor()

        # Same rule as the hotkeys below: another thread decided, this one acts.
        self._drain_tray()

        # Hotkeys arrive on their own thread; Tk is only ever touched from this one.
        if self.hotkeys is not None:
            for name in self.hotkeys.drain():
                if name == "toggle":
                    self._toggle()
                elif name == "warm":
                    # The chord's press-down, one put ahead of `talk`, so the models load
                    # during the hold instead of inside the first sentence.
                    self.session.warm()
                elif name == "talk":
                    self._talk_start()
                elif name == "talk-end":
                    self._talk_end(send=True)
                elif name == "talk-break":
                    # Windows meant `ctrl+win+d`. Stop, keep whatever was said, paste
                    # nothing — see `_talk_end`.
                    self._talk_end(send=False)
                elif name == "send":
                    self._send()
                elif name == "cancel":
                    self._clear()
                elif name == "mode":
                    # A pending paste belongs to the mode it was spoken in. Dictate
                    # pastes into a window and converse asks a CLI, so a wait armed in
                    # one and fired in the other does something the user never asked
                    # for — and the switch is one keypress away at all times. Dropped
                    # rather than translated: the words stay in the draft, and Send in
                    # the new mode does whatever it now means, deliberately.
                    self._ptt_wait = None
                    self.session.toggle_mode()
                elif name == "quit":
                    self.quit_app()
                    return

        if self.armed:
            self.session.tick()
            if getattr(self.session, "hearing", True):
                self._deaf_frame = 0
                self._meter_level = self._eased(self._norm(self.session.level_db))
            else:
                self._flatten()
        else:
            # Still collect what the CLI owes us. Disarming used to strand an answer
            # that was already on its way — the pill went quiet and nothing ever
            # arrived, because the code that collects a reply sat behind this check.
            self.session.pump_results()
            self._deaf_frame = 0
            self._meter_level = self._eased(0.0)

        self._pump_warnings()
        self._pump_events()
        # After `_pump_events`, so a draft the final decode just produced is on
        # `session.draft` by the time the wait looks for it — otherwise every paste
        # would cost one extra frame, and a decode that landed in the same frame as the
        # timeout would be reported as never having arrived.
        self._pump_talk()

        if self.converse:
            self.card.tick_countdown()
        else:
            self.bubble.tick_countdown()
            self.bubble.tick_activity()
            self.bubble.tick_sent()
        if self._flash:
            self._flash -= 1
        self._advance_motion()
        # Piggybacks on the repaint this frame was already doing (§07's rule) rather
        # than adding a second trigger — the same reason a panel's own `reposition`
        # also calls this, for the frame where a panel opens between two ticks.
        self._sync_dock()
        self._apply_idle_dim()
        self._draw()

    def _pump_events(self) -> None:
        """Draw everything the session said since the last frame onto the right surface.

        Its own method rather than a block inside `_frame` for the reason `_pump_warnings`
        is: the routing decisions here are the ones with an invariant on them — exactly
        one surface is up, and each event lands on the one this mode owns — and a rule
        that can only be exercised by driving a real Tk frame is a rule nothing tests.
        """
        # Cleared on the frame the ask ends, whether it answered or failed, so the next
        # one puts its question on the card — including the same question asked again.
        # Here rather than inside `_ask_is_new` because it has to run on every frame,
        # and that only runs when a draft event arrives.
        if self.session.state is not State.ASKING:
            self._asked = False
        for ev in self.session.events():
            if ev.kind == "draft":
                if ev.text:
                    self._last_draft = ev.text
                if self.converse:
                    # The forming question goes on the card, and the bubble stays shut:
                    # two surfaces, two jobs. When the draft empties into an ask, the
                    # words that were on screen are the words that went, so they pin.
                    if ev.text:
                        self.card.show_partial(ev.text)
                    elif self._ask_is_new():
                        self.card.ask(self._last_draft)
                elif ev.text:
                    self.bubble.show(ev.text)
                elif not self.bubble.showing_sent:
                    self.bubble.hide()
                # The other way the draft empties is Send, which puts the words on the
                # sent card in the same breath. Hiding on that event is what used to
                # take them straight back off the screen. The third way is an ask, and
                # that cannot reach here: `send()` only asks in converse mode, which is
                # the branch above.
            elif ev.kind == "partial":
                self.front.show_partial(ev.text)
            elif ev.kind == "error":
                self._flash = FLASH_FRAMES
                self.front.note(ev.text)
            elif ev.kind == "note":
                self.front.note(ev.text)
            elif ev.kind == "edit":
                # A note that came from an edit Flow made to the draft, which is the one
                # kind with a way back to offer. Its own event rather than a flag on
                # `note`, because the surfaces that show notes show a dozen other things
                # through the same door — an error, a workshop path, the exits list —
                # and none of them is undoable.
                self.front.note(ev.text, undoable=True)
            elif ev.kind == "reply":
                # Asked only in converse, by construction — `Session.send()` returns ""
                # in dictate mode and never asks. That was once read as "so this branch
                # is converse-only" and it is not: it constrains where a question
                # *leaves*, and says nothing about where the answer *arrives*, which is
                # 4-20 s of CLI later. Switch mode inside that window and this branch
                # used to deiconify the card on top of the draft bubble, breaking
                # `_swap_surfaces`' one-window rule from behind. Reported as "both modes
                # got activated", which is exactly what two windows look like.
                if ev.text:
                    self.card.answer(ev.text, surface=self.converse)
                    if not self.converse:
                        # `surface` rather than `note`, which paints only on a bubble
                        # that is already up: the case needing this line most is the one
                        # with nothing on screen at all, where an answer held off-screen
                        # and unannounced is the silence P2 forbids.
                        self.bubble.surface(ANSWER_HELD)
            elif ev.kind == "mode":
                self._swap_surfaces()
            elif ev.kind == "conversation":
                # Item 64's one act, reaching the surface half of it. The note that
                # follows lands on the cleared card, which is why this is an event
                # rather than something the chip does to the card directly: a
                # conversation cleared by a hotkey or by a spoken command later would
                # otherwise clear the session and leave the window showing the old one.
                self.card.clear()
            elif ev.kind == "send":
                # A spoken trigger. Handled here rather than in the session because the
                # paste belongs to this thread and to `paste_target` — the same button
                # the chip presses, arrived at by a different route.
                self._send(submit=ev.text == "enter")
            elif ev.kind == "drop":
                # Shown, not hidden: P2 is that a rejection is never silent. The
                # recovery affordance itself is Phase 3's rescue chip.
                self.front.note(ev.text)
            elif ev.kind == "disarm":
                # Capture has stopped and cannot start itself again — the input device
                # went away and did not come back inside `MIC_RETRIES`. `armed` belongs
                # to this thread, so this is the only way the session can stop a pill
                # claiming to listen with no microphone under it, which is the same lie
                # `_toggle` already refuses to tell when capture fails at startup. The
                # error event just before this one carries the reason and the flash.
                #
                # Deliberately not `session.pause()`: the session has already stopped
                # the device, and pausing would bump the capture generation and refuse
                # the decode of the words the loss cut short — which is the one thing
                # the recovery path went out of its way to keep.
                self.armed = False
                self._disarmed_since = time.perf_counter()  # starts the 8 s idle dim

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
            self._flash = FLASH_FRAMES
            self.bubble.note(line)

    def _flatten(self) -> None:
        """Collapse the meter toward a flat line over `DEAF_COLLAPSE_FRAMES` —
        newest bar first, oldest last.

        That is a deliberate reversal of §07's literal "left to right": the newest
        bar (drawn rightmost, the last one `_eased`/`.append` wrote) is the one most
        recently loud, and this fix exists because a stale loud bar reads as "hearing
        you" at the exact moment that is false. `Session.level_db` already reports
        silence while Flow is talking, so appending it would get here eventually —
        but "eventually" used to be eighteen frames (540 ms) of Flow's own voice
        sliding off the meter while it still claimed to hear someone. Newest-first
        means the most convincing bar is gone within a single frame, and the rest of
        the sweep is the ~120 ms of polish `DEAF_COLLAPSE_FRAMES` describes rather
        than a defect wearing a decay curve. Frozen while the pointer is in, like
        `_eased`.
        """
        if self._pointer_in:
            return
        self._deaf_frame = min(self._deaf_frame + 1, DEAF_COLLAPSE_FRAMES)
        self._eased_level = 0.0
        # Collapsed as one level rather than bar by bar from the right. Emptying the
        # right-hand bars first was the correct picture of a *scrolling* meter going
        # quiet — the silence arrived at one end and travelled. A bloom has no ends to
        # arrive at, so going deaf is the whole shape settling at once, which is also
        # what FluidVoice does while it is processing rather than listening.
        fade = 1.0 - self._deaf_frame / DEAF_COLLAPSE_FRAMES
        self._meter_level = max(0.0, self._meter_level * fade)

    def _advance_motion(self) -> None:
        """Step the two §07 animations that have to remember where they were.

        Frozen while the pointer is in, for the reason `_eased` and `_flatten` are:
        "nothing animates while the pointer is inside a window" is one rule, not three.
        The error flash is deliberately not among them — it decays on its own clock,
        because an error held indefinitely under a resting hand is the failure this whole
        surface exists to avoid.
        """
        if self._pointer_in:
            return
        # Reset rather than paused when the wait ends, so the next CLI call starts its
        # dots at the beginning of the loop instead of wherever the last one stopped.
        self._dots_frame = (self._dots_frame + 1) % DOTS_LOOP if self.waiting else 0
        target = 1.0 if self.converse else 0.0
        step = 1.0 / TINT_FRAMES
        self._tint = (
            min(target, self._tint + step) if self._tint < target
            else max(target, self._tint - step)
        )

    def _eased(self, target: float) -> float:
        """This frame's drawn level, one step closer to `target` than the last.

        Rise 60 ms, fall 160 ms (§07, `LEVEL_RISE_ALPHA`/`LEVEL_FALL_ALPHA`) — peaks
        fall slower than they rise. Frozen while the pointer is in: the meter holds
        the level it had already eased to rather than continuing to chase a new one,
        the same rule `Bubble`/`ConversationCard` apply to their own geometry.
        """
        if self._pointer_in:
            return self._eased_level
        alpha = LEVEL_RISE_ALPHA if target > self._eased_level else LEVEL_FALL_ALPHA
        self._eased_level += (target - self._eased_level) * alpha
        return self._eased_level

    @staticmethod
    def _norm(db: float) -> float:
        return max(0.0, min(1.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))

    @staticmethod
    def _bar_half_height(index: int, level: float) -> float:
        """Half the height of bar `index` at `level`, as FluidVoice shapes it.

        Three terms, and each is doing something the other two cannot:

        1. **The envelope** puts the peak in the middle. A bar's ceiling falls off with
           its distance from the centre, floored at 18% so the outermost bars still move
           rather than sitting dead at the ends.
        2. **The exponent** bends the response so ordinary speech reaches most of the
           way up. Linear is what made Flow's old meter look timid at conversational
           volume — the top half of the widget was reserved for shouting.
        3. **The variation** breaks the symmetry very slightly, so a sustained note draws
           a shape rather than a comb.

        Returns a half-height because the bars are mirrored about the pill's centre
        line: `PILL_H` is 40 and the meter has 8 px of air, so 12 px each way.
        """
        centre_distance = abs(index - (BARS - 1) / 2)
        normalised = min(centre_distance / max((BARS - 1) / 2, 1), 1.0)
        factor = max(_ENVELOPE_MIN, _ENVELOPE_FLOOR - normalised * _ENVELOPE_SPAN)
        peak = BAR_MIN_H + (BAR_MAX_H - BAR_MIN_H) * factor
        amplified = max(0.0, min(1.0, level)) ** _LEVEL_EXPONENT
        variation = (_BAR_VARIATION_BASE
                     + _BAR_VARIATION_SWING * math.cos(index * _BAR_VARIATION_RATE))
        height = BAR_MIN_H + (peak - BAR_MIN_H) * amplified * variation
        return max(BAR_MIN_H, min(BAR_MAX_H, height))

    # -- painting ----------------------------------------------------------

    @property
    def flashing(self) -> bool:
        """Whether an error is on this pill right now.

        The panels ask this rather than comparing `accent` to `ERROR`, and that is not
        a tidy-up: `accent` is interpolated now, so for most of a flash it is *near*
        `ERROR` without ever equalling it, and an identity test against it would have
        turned the panel rings red for a single frame in the middle of the hold.
        """
        return self._flash > 0

    @property
    def flash_t(self) -> float:
        """How far into red this frame is, 0…1 — §07's `80 / 1200 / 600` envelope.

        Attack, hold and decay are read off the one counter every call site sets to
        `FLASH_FRAMES`, so there is no second piece of state to get out of step with it.
        """
        if not self._flash:
            return 0.0
        elapsed = FLASH_FRAMES - self._flash
        if elapsed < FLASH_ATTACK:
            return (elapsed + 1) / FLASH_ATTACK
        if self._flash > FLASH_DECAY:
            return 1.0
        return self._flash / FLASH_DECAY

    @property
    def base_accent(self) -> str:
        """The state's own colour, before the mode tint and the error flash."""
        if not self.armed:
            return ACCENT[State.IDLE]
        return ACCENT.get(self.session.state, ACCENT[State.IDLE])

    @property
    def accent(self) -> str:
        """What the glyph, the meter and the label are painted this frame.

        Three layers, applied in the order they are allowed to override each other: the
        state's colour, then converse's violet travelling in over `TINT_FRAMES` (§07 —
        "the pill's glyph and label tint travel green ⇄ violet at frame rate, and that
        travel is the whole continuity"), then the error flash on top of both, because an
        error is true regardless of which mode raised it.
        """
        base = _mix(self.base_accent, CARD_ACCENT, self._tint)
        return _mix(base, ERROR, self.flash_t) if self._flash else base

    @property
    def waiting(self) -> bool:
        """Whether a CLI is out — the state whose dots stand in for the level meter."""
        return self.armed and self.session.state in (State.REFINING, State.ASKING)

    @property
    def ring_color(self) -> str:
        """The pill's own hairline ring: neutral, except the one state every surface
        still shares a colour for.

        The glyph and the level meter still travel through every state — `accent` is
        what draws them — but the ring is not a fourth place to repeat green, blue or
        violet. Only an error turns it, at the same moment the panel's ring turns too
        (decisions.md 2026-08-09, "BOTH pill and panel ring go red").

        This is the hairline §07 means by "goes red over 80 ms and decays over 600" — it
        interpolates. The panel's ring is the same red set once and cleared once, which
        is the whole difference between the surface that redraws every 30 ms and the one
        that does not.
        """
        return _mix(RING_OUTER, ERROR, self.flash_t) if self._flash else RING_OUTER

    @property
    def pill_w(self) -> int:
        """This pill's actual width right now: idle, or docked to the panel that is up.

        Widens only once there is something to dock to (decisions.md 2026-08-09) —
        `front` is chosen by mode, but the mode's own surface can still be hidden (an
        empty draft shows nothing), and an idle pill must not claim a panel's width it
        is not actually sitting under.
        """
        # The panel width, unconditionally, and that is the point. This used to answer
        # `PILL_W` while nothing was docked, so the pill jumped 205 -> 420 the moment a
        # draft appeared and back again when it went — the most visible motion on the
        # screen, on every single utterance. One width, whatever is happening.
        #
        # Read from the constant rather than through `self.front`, which is what it did
        # while the answer depended on which panel was up. It does not any more: the
        # bubble and the card are the same width by construction (`apply_panel_width`
        # sets both), and reaching through a window meant this could be asked before
        # there was one to ask.
        return BUBBLE_W

    def _sync_shell(self) -> None:
        """One window, sized for whatever band is up, with its bottom edge held still.

        **This was `_sync_dock`, and the dock is gone.** The pill and its panel were two
        windows the app kept adjacent by hand: a width they had to agree on, an
        above-or-below decision, a `_docked_above` flag so the pill knew which corners to
        square off, and an ordering rule saying whichever ran first left the other with
        nothing to do. `scripts/reel.py` once caught them 215 px apart for five seconds,
        because a resize had landed and the matching move had not — a failure only
        possible when two windows have to be moved in two calls the compositor is free to
        show a frame apart.

        There is one window now, so there is nothing to keep in step. What is left is a
        height: the pill row, plus the panel band when a panel is up.

        **The bottom edge is the anchor**, and that is the whole of "the controls do not
        move". A panel opening grows the window *upward* — the chip row, the meter and
        the Send button stay at the pixel they were at, because they are measured from a
        foot that never moves. Growing downward, or centring the growth, would move every
        control on the surface every time a draft appeared.

        Idempotent and cheap once nothing has changed, so it can run from the frame pump
        and from a panel's `reposition` without either caring which got there first.

        The geometry is compared against the *window* rather than against a remembered
        value, for the reason the dock learned the hard way: state that says the move
        happened is not evidence that it did, and comparing against the window means the
        next frame fixes whatever dropped it.
        """
        # The band's *actual* height, not the ceiling it is allowed. Asking `band_h()`
        # here made the shell 224 px tall around a 130 px band and left the row floating
        # 54 px below it — which the shots caught immediately, because a detached row is
        # exactly the two-boxes look this window was merged to end.
        # Parked, with an icon standing in for it. Re-asserting geometry here is what
        # dragged it straight back on screen the moment it was hidden — the frame pump
        # runs thirty times a second and this used to win every one of them.
        if self._hidden:
            return
        front = self.front
        band = min(self.band_h(), max(0, int(getattr(front, "_h", 0) or 0)))             if getattr(front, "_visible", False) else 0
        h = PILL_H + band
        w = self.pill_w
        left, top, right, bottom = self.work
        # **Where it is, not where it belongs.** This asked `_placed` for both, on every
        # frame, which meant a drag was undone before the hand had left the mouse: the
        # pill snapped back to centre and could not be moved at all. `_sync_dock` never
        # had the fault because it only recomputed x when the *width* changed, which was
        # rare; recomputing unconditionally is what the merge introduced.
        #
        # `_placed` is still the answer at startup and whenever the pointer changes
        # monitor — `_sync_monitor` asks it there, which is the one place a reposition is
        # actually wanted.
        foot = self.y + self._shell_h
        x = max(left, min(self.x, right - w))
        y = max(top + EDGE_AIR, min(foot - h, bottom - h))
        # The width is compared too, and leaving it out was a defect. `apply_panel_width`
        # rebinds `BUBBLE_W` while Flow is running — the panel-size setting — so `w`
        # changes without x, y or the height changing with it. The row then kept the
        # width it was built at while the band above it took the new one, which is two
        # boxes of different widths stacked in one window, and exactly what a screenshot
        # of "panel size: larger" showed. `_docked_w` is what `_draw` measures the row
        # against, so it has to move in the same breath as the canvas.
        if (self.x, self.y, self._shell_h, self._docked_w) != (x, y, h, w):
            self.x, self.y, self._shell_h, self._docked_w = x, y, h, w
            self.canvas.configure(width=w)
            self.canvas.place(x=0, y=h - PILL_H, width=w, height=PILL_H)
        if self.window_geometry() != (w, self.x, self.y):
            self.geometry(f"{w}x{h}+{self.x}+{self.y}")

    #: Kept under the old name because every caller in the app and the suite says it, and
    #: the two never meant different things — the dock *was* the shell, badly.
    _sync_dock = _sync_shell

    def window_geometry(self) -> tuple[int, int, int]:
        """Where this window actually is, as (width, x, y).

        Its own method so `_sync_dock` has one thing to compare against and a test has
        one thing to lie about. `winfo_*` lags the window manager by a frame or two
        after a move, which costs at worst one redundant `geometry` call with the
        values already asked for.
        """
        return (self.winfo_width(), self.winfo_rootx(), self.winfo_rooty())

    #: What fits beside the level bars. The baseline is at y 33 and the bars run to
    #: y 32 from x 40, so a wider token overlaps them rather than being clipped —
    #: `codex` and `claude` are 5 and 6, and anything longer falls back to the mode.
    #: A CLI whose name does not fit may carry a `marker` alias that does; the wall is
    #: this number either way, and `test_indicator.py` asserts it of every shipped entry.
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

        An entry may carry a shorter `marker` for this slot alone, and kiro-cli is why:
        8 characters fell back to `ASK` while it was the CLI about to answer, and the
        owner read that as Kiro not being captured at all. Only the slot is affected —
        the menu, the notes and the Help sheet name CLIs in prose, where the full name
        costs nothing and a nickname would be a second name for the same thing.
        """
        pinned = getattr(self.session, "cli", None)
        found = self._resolved()
        cli = pinned if pinned is not None else (found[0] if found else None)
        if cli is None:
            return "ASK"
        name = getattr(cli, "marker", "") or cli.name.lower()
        return name if len(name) <= self.MARKER_MAX else "ASK"

    def _draw(self) -> None:
        # `self._docked_w`, already resolved by `_sync_dock` (called from `_frame`,
        # once a frame, before this) — not a fresh `self.pill_w` here, so a bare
        # fixture that only ever calls `_draw` directly still draws the idle pill its
        # class defaults describe, rather than reaching for a `bubble`/`card` it never
        # built (the same `RecursionError` risk `lite`'s class default exists for).
        c = self.canvas
        c.delete("all")
        accent = self.accent
        w = self._docked_w
        seam = None
        if self._shell_h == PILL_H:
            radius = PILL_H // 2  # alone in the window: the capsule this has always been
        else:
            # Sharing the window with a panel band directly above. Squared on the join,
            # rounded on the free-standing foot, at the panel's own 8 px — one shape
            # language, not a capsule with a corner cut off.
            #
            # `_docked_above` used to decide this, because the panel was a window that
            # could end up on either side of the pill when there was no room above. There
            # is one window now and the band is always the top of it, so the answer is a
            # constant and the flag that carried it is gone.
            radius = (0, 0, PANEL_R, PANEL_R)
            # The row is the lower surface, so it draws nothing on the join — the band's
            # bottom carries the single line.
            seam = "top"
        _panel_chrome(c, w, PILL_H, radius, self.ring_color, seam=seam)

        # The window Flow is aimed at, named at the left of the row. A fixed-width slot
        # whether or not the name fills it, so changing window moves nothing — see
        # `APP_SLOT_W`. Zero in Lite, which tracks no foreground window, so the row there
        # is exactly what it always was.
        shift = self._row_shift()
        if shift:
            c.create_text(PAD, PILL_H // 2, anchor="w",
                          text=app_label(self.session.target_app),
                          fill=MUTED, font=FONT_NOTE)

        # Mic glyph: capsule + stand, drawn rather than fonted so there is no
        # dependency on an emoji font being present and correctly sized.
        cx, cy = 22 + shift, PILL_H // 2
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

        mid = PILL_H // 2
        if self.waiting:
            self._draw_dots(c, mid, accent)
        else:
            # Level bars (R13). Mirrored around the centre line so quiet reads as a
            # flat line rather than an empty box, and blooming from the middle rather
            # than scrolling — see `_bar_half_height` for what changed and why.
            #
            # `_meter_level` and not `self.levels[i]`: every bar reads the same level
            # now, and the shape between them is the envelope rather than the past.
            lvl = self._meter_level
            shade = accent if lvl > 0.04 else MUTED
            for i in range(BARS):
                h = self._bar_half_height(i, lvl)
                x = METER_X + shift + i * (BAR_W + BAR_GAP)
                # Rounded caps, radius half the bar width — FluidVoice draws its bars as
                # `RoundedRectangle(cornerRadius: barWidth / 2)`, and at four pixels wide
                # that is the difference between a meter and a bar chart. Squared off
                # when the bar is shorter than its own cap, where a smoothed polygon
                # would pinch into a lozenge.
                if h * 2 > BAR_W:
                    _round_rect(c, x, mid - h, x + BAR_W, mid + h, BAR_W / 2,
                                fill=shade, outline="")
                else:
                    c.create_rectangle(x, mid - h, x + BAR_W, mid + h,
                                       fill=shade, outline="")
        # After the meter and before the word, which is where the owner asked for them:
        # "after progress bar add settings icon ... next to that create icon for voice
        # and dictation". Only when there is room — a narrow pill would otherwise draw
        # them over the status word, and the word is the thing that says whether Flow is
        # listening.
        # Against the right edge, beside the status word, rather than trailing the meter.
        # Asked for that way — "settings and three icon aligh to right near help" — and
        # it is the better address: the meter's right edge is where the *bars* end, which
        # moves with nothing but is read as part of the meter, while the right edge is
        # the one landmark on this row that never moves at all.
        icons_w = 3 * ICON_SIZE + 2 * ICON_GAP
        icons_x = w - LABEL_PAD - LABEL_SLOT_W - LABEL_GAP - icons_w
        if icons_x >= METER_X + METER_W + shift + LABEL_GAP:
            _row_icons(c, self, icons_x, mid)
        self._draw_label(c, w, mid, accent)

    def _row_shift(self) -> int:
        """How far the mic, the meter and the icons move right for the app-name slot.

        Its own method because `_draw_dots` needs the same number and is called without
        it — the marching dots occupy the meter's place, so a shift applied to one and
        not the other would draw them under the app name.
        """
        if self.lite or not app_label(getattr(self.session, "target_app", "")):
            return 0
        return APP_SLOT_W + APP_SLOT_GAP

    def _draw_dots(self, c: tk.Canvas, mid: int, accent: str) -> None:
        """Three marching dots in the slot the meter vacates (§07).

        The meter is not merely hidden while a CLI is out — left up, it would be lying.
        Nothing is being captured during a refine, so bars moving there are the same
        false "hearing you" that `_flatten` exists to kill, one state along.

        "Opacity .25 → 1" is a blend from `SHELL`, not an alpha: these windows are
        binary-transparent and have nothing to composite against. See `_mix`.
        """
        span = 2 * DOT_R
        x = METER_X + self._row_shift() + (METER_W - (3 * span + 2 * DOT_GAP)) // 2
        for i in range(3):
            dx = x + i * (span + DOT_GAP) + DOT_R
            c.create_oval(dx - DOT_R, mid - DOT_R, dx + DOT_R, mid + DOT_R,
                          fill=_mix(SHELL, accent, self._dot_lit(i)), outline="")

    def _dot_lit(self, i: int) -> float:
        """How lit dot `i` is this frame — §07's "opacity .25 → 1", as a `_mix` weight.

        A triangle: each dot rises to full over half the loop and falls over the other
        half, `DOTS_STAGGER` frames behind the one to its left, so the bright point
        travels along the row.

        The first attempt was a sawtooth — snap to full, decay across the loop — chosen
        to guarantee the three are never the same shade. They are the same shade on two
        frames in forty, which is not worth what the sawtooth costs: full brightness
        lasts a *single* frame out of forty, so the peak that makes the row read as
        marching is invisible 97 % of the time. Two screenshots taken a third of a
        second apart both came back with the brightest dot at 68 % — a row of grey
        dots that happened to be at slightly different greys.
        """
        phase = ((self._dots_frame - i * DOTS_STAGGER) % DOTS_LOOP) / DOTS_LOOP
        return DOT_DIM + (1 - DOT_DIM) * (1 - abs(2 * phase - 1))

    def _draw_label(self, c: tk.Canvas, w: int, mid: int, accent: str) -> None:
        """The bar label, right-aligned in the slot `LABEL_SLOT_W` holds open for it.

        One `create_text` per character, because Tk has no letter-spacing and §02 asks
        for `+.1em`. That is nine calls in the worst state, on a canvas that already
        clears and repaints itself thirty times a second.

        Right-aligned against this window's *current* width rather than `PILL_W`, so the
        word stays at the pill's right edge when it widens to dock — the same edge
        `_sync_dock` pins, and therefore the one place on this pill where a word can sit
        still while everything to its left moves.
        """
        text = self._bar_label()
        x = w - LABEL_PAD - (len(text) * LABEL_PITCH - LABEL_TRACK)
        for i, ch in enumerate(text):
            c.create_text(x + i * LABEL_PITCH, mid, text=ch, fill=accent,
                          font=FONT_TRACE, anchor="w")

    def _bar_label(self) -> str:
        """The word in the pill's right-hand slot: what Flow is doing, in one token.

        Deafness gets three words rather than one, and that is the same distinction
        `Session.hearing` is careful about: "busy, still listening" and "busy, and deaf"
        are different promises, and *why* Flow has stopped hearing decides whether the
        user should keep talking. `SPEAKING` and `EDITING` say it will come back on its
        own; `NO INPUT` says the device is gone and nothing is coming back.

        Which of the first two it is comes off `editing`, not off `speaker.speaking`,
        and that is not arbitrary: `hearing` is defined as *neither of those two*, so
        one of them is enough to tell them apart — and it is the one that is a plain
        attribute rather than a reach through an object that is `None` whenever speech
        is switched off. Asking the speaker first labelled a spoken reply `EDITING`,
        which is the opposite advice.
        """
        if not self.armed:
            return LABEL_OFF
        mic = getattr(self.session, "mic", None)
        if mic is not None and not getattr(mic, "active", True):
            return LABEL_NO_INPUT
        if not getattr(self.session, "hearing", True):
            return LABEL_EDITING if getattr(self.session, "editing", False) \
                else LABEL_SPEAKING
        return BAR_LABELS.get(self.session.state, BAR_LABELS[State.IDLE])


class HelpWindow(tk.Toplevel):
    """Commands & shortcuts — and, once, the welcome card.

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

    #: Declared on the class as well as in `__init__`, for the reason `Pill.lite` is:
    #: `tk.Misc.__getattr__` forwards an unknown attribute to `self.tk`, so on an
    #: instance built with `__new__` — which is how the fixtures build one — a missing
    #: name recurses until the stack ends instead of defaulting.
    _title = TITLE_DEFAULT
    _chip = "Close"

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
        self._title, self._chip = TITLE_DEFAULT, "Close"
        self._top = 0  # index of the first row drawn
        self._drag_y: int | None = None
        self._drag_px = 0
        self._h = 200
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-1>", self._grab)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.withdraw()

    # -- content -----------------------------------------------------------

    def show(self, rows, title: str = TITLE_DEFAULT, chip: str = "Close") -> None:
        """Replace what is shown and bring the window up, back at the top.

        Replaced on every open rather than kept: the combos, the trigger words and the
        workshop are read at the moment the menu is tapped, and a window that reused the
        last render would be the stale help file this replaced, one surface along.

        `title` and `chip` because the welcome card is this window with different rows in
        it (item 71). A second `Toplevel` would be a second set of the things this one
        has already been made to get right — `WS_EX_NOACTIVATE`, a viewport with two ways
        to scroll, a row layout that cannot clip — and the welcome card needs every one.
        """
        self._rows = list(rows)
        self._title, self._chip = title, chip
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
        c.create_text(PAD, PAD + 2, anchor="nw", text=self._title, fill=TEXT,
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
        label = self._chip
        w = chip_w(label, label)
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


class ConversationCard(tk.Frame):
    """P9's surface: a question, the answer it produced, and the turns behind them.

    Converse mode used to share the draft bubble, and three outside users found every
    consequence of that at once (decisions.md 2026-08-03). A bubble is about the words
    being *worked on*; an exchange is about words that have already gone. Sharing one
    card made the two indistinguishable — most sharply on auto-ask, where a four-second
    pause sent the question, the send cleared the draft, and the screen went blank with
    no record of what had just been asked. "The prompt vanished, uncommanded" is that
    sentence, and the pinned question is the answer to it: the words stay on screen with
    the answer growing underneath them, so a premature send costs nothing.

    Built the way `HelpWindow` was, because that window already solved this one's
    problems: `WS_EX_NOACTIVATE` with the read-back reported rather than assumed, the
    shell palette, and a viewport that scrolls by wheel *and* by press-and-drag — the
    wheel reaches an unfocused window only through "Scroll inactive windows when I hover
    over them", which is a Windows default and a user preference, so the drag is the path
    that cannot be switched off.

    Anchored like the bubble rather than centred like the help sheet: this is the surface
    somebody is working in, so it belongs where their eye already is.

    Bounded like everything else. Each earlier turn is laid out from its head under
    `CARD_TURN_CHARS`, the answer takes `head_window` with `… N more lines` at its foot
    (item 45), and the measured heights of the history are cached and recomputed only
    when the history itself changes — because this card renders on every partial, which
    is where item 37's 476.7 ms came from.
    """


    #: Declared on the class as well as assigned in `__init__`, for the reason `lite` is:
    #: `tk.Misc.__getattr__` forwards an unknown attribute to `self.tk`, so on an
    #: instance built with `__new__` — which is how every UI fixture in this suite builds
    #: one — a missing name recurses until the stack ends instead of defaulting. Item 32
    #: found that as a `RecursionError`; item 66 found it again the moment `_render`
    #: started reading two new fields.
    _visible = False
    _pointer_in = False
    _chips_drawn: tuple | None = None

    def __init__(self, pill: Pill) -> None:
        super().__init__(pill)
        self.pill = pill
        # A `Frame` inside the pill's window, not a window of its own. Everything this
        # class draws is canvas-local and did not change; what went is the *window* -
        # its own shell, its own shadow, its own position, and all the arithmetic that
        # kept it touching the pill. See `Pill._sync_shell`.
        self.bg = pill.bg
        self.configure(bg=self.bg)
        self.canvas = tk.Canvas(self, bg=self.bg, highlightthickness=0)
        self.canvas.pack()
        self.no_activate = _no_activate(self)
        #: Exchanges already answered, oldest first, as `(kind, text)` with kind in
        #: `{"q", "a"}`. Its own list rather than a read of `session.thread`: the thread
        #: is what the *CLI* is told, trimmed to a character budget for that purpose,
        #: and a window that re-derived itself from it would change what is on screen
        #: whenever that budget moved.
        self._history: list[tuple[str, str]] = []
        self._heights: list[int] = []
        self._top = 0
        self._drag_y: int | None = None
        self._drag_px = 0
        self._question = ""
        self._answer = ""
        self._partial = ""
        self._note = ""
        self._visible = False
        self._h = CARD_MIN_H
        #: How tall the pinned block measured last render. Read by `_view_h`, which the
        #: scroll arithmetic goes through — and which can be asked before the first
        #: render, so it has a value from the start rather than an attribute error.
        self._pinned_h = 0
        #: Last auto-ask second painted, so the countdown repaints once a second rather
        #: than on every frame. Same discipline as `Bubble.tick_countdown`.
        self._countdown: int | None = None
        #: The chip row last drawn, and whether the hand is over this window. Both are
        #: item 66's — see `Bubble._lay_out` and `_frozen`.
        self._chips_drawn: tuple | None = None
        self._pointer_in = False
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-1>", self._grab)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<Enter>", self._enter, add="+")
        self.canvas.bind("<Leave>", self._leave, add="+")
        self.place_forget()

    # -- content -----------------------------------------------------------

    def ask(self, question: str) -> None:
        """A question has gone. The exchange it displaces becomes history."""
        if self._question:
            self._push(("q", self._question))
            if self._answer:
                self._push(("a", self._answer))
        self._question, self._answer, self._partial = question, "", ""
        self._top = self._max_top()
        self._show()

    def answer(self, text: str, *, surface: bool = True) -> None:
        """The reply, filed here whether or not this window is the one on screen.

        `surface=False` holds it without raising the card. An ask started in converse
        can land after the user has switched to dictate — the CLI takes 4-20 s and the
        mode is one keypress — and the two obvious moves there are both wrong: opening
        the card puts it over the draft the user is now working in, and dropping the
        answer throws away the seconds the CLI spent and a question that is spent with
        it. Holding it costs one mode switch to read, and `show()` renders it.
        """
        self._answer = text
        if surface or self._visible:
            self._show()

    def show_partial(self, text: str) -> None:
        """The words forming now, where the question they are becoming will sit.

        Named for the bubble's method rather than for itself: `Pill.front` hands notes
        and partials to whichever surface the mode owns, and a protocol with two names
        for one act is a protocol with a branch in every caller.
        """
        self._partial = text
        self._show()

    def note(self, msg: str, undoable: bool = False) -> None:
        """`undoable` is accepted and ignored: the Undo affordance belongs beside the
        draft it would restore, and this window is not showing one. Taking the argument
        anyway keeps `front.note(...)` a single call site rather than a branch on which
        surface happens to be up."""
        self._note = msg
        self._show()

    def surface(self, msg: str) -> None:
        """`note`, under the name the bubble gives it. Both surfaces answer to both.

        On this window they are genuinely the same act — a note brings the card up —
        while on the bubble `note` paints only what is already showing. The protocol
        `Pill.front` hands work to has to be complete, or every caller grows a branch.
        """
        self.note(msg)

    def clear(self) -> None:
        """Everything gone — history, question, answer, note. Item 64's one act."""
        self._history, self._heights = [], []
        self._question = self._answer = self._partial = self._note = ""
        self._top = 0
        if self._visible:
            self._render()

    def show(self) -> None:
        self._show()

    def close(self) -> None:
        self._visible = False
        # Give the band back rather than parking a window offscreen. `park` existed
        # because hiding a Toplevel on Windows cost a taskbar flicker and a restack;
        # there is no window here to hide, only a `place` to undo, and the pill's shell
        # shrinks to the row on the next `_sync_shell`.
        self.place_forget()
        self.pill._sync_shell()

    @property
    def showing(self) -> bool:
        # `state()` was a window's state, and this is no longer a window. A band is
        # showing when it has a place in the one it lives in.
        return bool(self.winfo_exists() and self.winfo_ismapped())

    def _push(self, row: tuple[str, str]) -> None:
        self._history.append(row)
        self._heights.append(self._row_h(row))
        # Bounded by the same number the thread is bounded by, and for the same reason:
        # a long session must cost what a short one costs (R8).
        while len(self._history) > 2 * THREAD_MAX_TURNS:
            self._history.pop(0)
            self._heights.pop(0)

    def _show(self) -> None:
        if not self._visible:
            self._visible = True
            self.pill._sync_shell()
        self._render()

    # -- scrolling ---------------------------------------------------------

    def _view_h(self) -> int:
        """What is left for the history once the pinned block and chips have theirs."""
        return max(0, self._h - PAD - COMMAND_BAND - self._pinned_h - HELP_FOOT_BAND)

    def _max_top(self) -> int:
        height = 0
        for i in range(len(self._history) - 1, -1, -1):
            height += self._heights[i] + CARD_GAP
            if height > self._view_h():
                return min(i + 1, len(self._history) - 1)
        return 0

    def _scroll(self, rows: int) -> None:
        top = max(0, min(self._top + rows, self._max_top()))
        if top != self._top:
            self._top = top
            self._render()

    def _wheel(self, e) -> None:
        self._scroll(-(e.delta // 120 or (1 if e.delta > 0 else -1)))

    def _grab(self, e) -> None:
        self._drag_y, self._drag_px = e.y, 0

    def _drag(self, e) -> None:
        if self._drag_y is None:
            return
        self._drag_px += self._drag_y - e.y
        self._drag_y = e.y
        # Content follows the hand, whole turns at a time. A turn is the unit here
        # rather than a line, because a turn is what the eye is looking for.
        steps, self._drag_px = divmod(self._drag_px, 40)
        if steps:
            self._scroll(steps)

    # -- geometry ----------------------------------------------------------

    def work_h(self) -> int:
        _left, top, _right, bottom = self.pill.work
        return bottom - top - 2 * EDGE_AIR

    def panel_h(self) -> int:
        """The tallest this band may be. Asked of the pill, which owns the window.

        The row shares that window, so the band's ceiling is what the desktop has left
        after the row has taken its 40 px.
        """
        return self.pill.band_h()

    def _settled_h(self, want: int) -> int:
        """`want`, rounded up to a whole body line and clamped to the band's ceiling.

        **The snap is what replaces FluidVoice's 80 ms debounce.** Its overlay sizes to
        its content and coalesces the resizes on a timer; sizing to content is right and
        the timer is a thing to get wrong from inside a render loop that already runs
        thirty times a second. A height that can only change when the text gains or loses
        a *line* changes a handful of times an utterance by construction — no cancelling,
        nothing to leak, and the same absence of thrash.

        The foot does not move whatever this returns: `Pill._sync_shell` grows the window
        upward from a fixed bottom edge, so a step here moves the top edge and nothing
        else.
        """
        want = max(PANEL_MIN_H, want)
        over = want - PANEL_MIN_H
        want = PANEL_MIN_H + -(-over // BODY_LINE_H) * BODY_LINE_H
        return max(PANEL_MIN_H, min(want, self.pill.band_h()))

    @property
    def width(self) -> int:
        """This window's own width — what a docked pill takes on (`Pill.pill_w`)."""
        return CARD_W

    def reposition(self) -> None:
        """Take the top band of the pill's window, or give it back.

        **This used to place a window.** It chose above-or-below against the work area,
        anchored to the pill's right edge, set `_docked_above` so the pill knew which of
        its corners to square off, and called `_sync_dock` first so the pill had already
        settled into the width the two were about to share. All of that existed to make
        two windows look like one, and none of it survives one window: the panel is the
        band above the pill row, at x=0, always.
        """
        self.pill._sync_shell()
        if self._visible:
            self.place(x=0, y=0, width=CARD_W, height=self._h)
        else:
            self.place_forget()


    # -- holding still under the hand --------------------------------------

    def _enter(self, _e=None) -> None:
        self._pointer_in = True

    def _leave(self, _e=None) -> None:
        self._pointer_in = False
        # Catch up on everything held back while the hand was here. Without this the
        # window keeps whatever size and chip row it had when the pointer arrived until
        # the next event happens to arrive, which on a settled draft is never.
        if self._visible:
            self._render()

    def _frozen(self) -> bool:
        """True while the pointer is over this window, so it must not move or resize.

        The other half of the lost-click defect, and the half a persistent chip row
        cannot fix on its own: the row can survive the redraw and still end up somewhere
        else on the screen, because `_render` re-measures the window and `reposition`
        re-places it on every partial, every countdown second and every activity frame.
        A note arriving is 30 px of height, which is more than a chip is tall.

        So the rule is the one every menu and tooltip already obeys: **nothing moves
        under the hand.** While the pointer is inside, the geometry is whatever it was
        when the pointer arrived; the body still redraws inside it, and the window
        catches up the moment the hand leaves. The window is bounded and its content is
        capped, so the worst a freeze costs is a line of body clipped for as long as
        somebody is hovering.
        """
        return self._pointer_in and self._visible

    # -- painting ----------------------------------------------------------

    def _probe_h(self, text: str, font) -> int:
        probe = self.canvas.create_text(
            PAD, PAD, anchor="nw", text=text or " ", fill=TEXT,
            font=font, width=CARD_W - 2 * PAD, tags="body")
        _x1, y1, _x2, y2 = self.canvas.bbox(probe)
        return y2 - y1

    def _row_h(self, row: tuple[str, str]) -> int:
        """Measured once, when the turn is pushed. Never on a render.

        This card draws on every partial, so a per-render walk of twenty wrapped turns
        would be item 37's 476.7 ms rebuilt on a different surface. The history only
        changes when a turn is added, so that is the only place it is measured.
        """
        return self._probe_h(self._row_text(row), FONT_NOTE)

    @staticmethod
    def _row_text(row: tuple[str, str]) -> str:
        _kind, text = row
        return head_window(text, CARD_TURN_CHARS)

    def _answer_slot(self, reply: str, cap: int) -> tuple[str, int, int]:
        """`Bubble._reply_slot`'s bargain, on this card's width.

        The head, not the tail, and `N` measured off the canvas rather than estimated —
        an answer is laid out once when it arrives, which is what makes an exact count
        affordable here and not in the draft.
        """
        font = FONT_BODY
        full_h = self._probe_h(reply, font)
        if full_h <= cap:
            return reply, 0, full_h
        shown, shown_h = reply, full_h
        for _ in range(BODY_PROBES):
            shown = head_window(reply, max(1, int(len(shown) * cap * 0.95 / shown_h)))
            shown_h = self._probe_h(shown, font)
            if shown_h <= cap:
                break
        line_h = max(1, self._probe_h("M", font))
        return shown, round(full_h / line_h) - round(shown_h / line_h), shown_h

    @property
    def accent(self) -> str:
        """Violet, always — this window's identity rather than a mood (item 63).

        The error flash still reaches it, because the message the flash belongs to is
        drawn on this card and a red pill beside a violet card would be two answers.
        """
        return ERROR if self.pill.flashing else CARD_ACCENT

    @property
    def ring_color(self) -> str:
        """The card's hairline ring: neutral, not violet.

        Violet's job moved onto the mode-line label, the answer text and the pill
        glyph — an outline can't also carry a word, so this stopped being where the
        colour was spent. Still turns red with `accent`, the one state every ring
        shares (decisions.md 2026-08-09).
        """
        return ERROR if self.accent == ERROR else RING_OUTER

    def _render(self) -> None:
        c = self.canvas
        accent = self.accent
        # `body`, not `all`: the chip row is drawn under its own tag and survives this,
        # because a chip torn down under a hand reaching for it is a lost click
        # (item 66). The measuring probes below carry the tag too, so they still go.
        c.delete("body")

        question = self._partial or self._question
        q_h = self._probe_h(question, FONT_NOTE) if question else 0
        note_h = self._probe_h(self._note, FONT_NOTE) if self._note else 0
        # The answer gets what the desktop has left after everything else on the card,
        # which is arithmetic rather than a constant — the same bargain `Bubble._render`
        # strikes, and the reason a 12 000-character artifact cannot size this window
        # past the bottom of the display.
        # Against the panel, not against the desktop. This asked `work_h()` while the
        # card was free to grow to it; with the card a fixed shape that let the answer be
        # sized for a 672 px window and drawn into a 184 px one, and the top of the card
        # — the "agent" label — was cut off by it.
        spare = (self.panel_h() - PAD - COMMAND_BAND - HELP_FOOT_BAND - q_h - CARD_GAP
                 - BODY_ELIDED_H - (note_h + 4 if self._note else 0))
        shown, more, a_h = "", 0, 0
        if self._answer:
            shown, more, a_h = self._answer_slot(self._answer,
                                                 max(BODY_ELIDED_H, spare))
        self._pinned_h = (
            q_h
            + (CARD_GAP if q_h and a_h else 0)
            + a_h
            + (BODY_ELIDED_H if more else 0)
            + (note_h + 4 if self._note else 0)
        )
        history_h = sum(h + CARD_GAP for h in self._heights)
        # Nothing moves or resizes under the hand — see `_frozen`.
        if not self._frozen():
            # Snug around what is on the card, stepping a line at a time — and the pill
            # row below it does not move when it steps, because the shell grows upward.
            self._h = self._settled_h(
                PAD + COMMAND_BAND + history_h + self._pinned_h + HELP_FOOT_BAND)
            c.configure(width=CARD_W, height=self._h)
            self.reposition()

        c.delete("body")
        # Squared on the seam it shares with the docked pill, rounded on the free
        # side — `reposition` is what decides above-vs-below, since it already has to.
        # Always the top band of the one window now: rounded head, squared foot on the
        # join it shares with the pill row below it.
        corners = (PANEL_R, PANEL_R, 0, 0)
        _panel_chrome(c, CARD_W, self._h, corners, self.ring_color,
                      seam="bottom")

        # -- the history, in what is left above the pinned block
        # Below the command band, which is furniture the history must not run under.
        y, floor = PAD + COMMAND_BAND, PAD + COMMAND_BAND + self._view_h()
        self._top = min(self._top, self._max_top())
        drawn = self._top
        for i in range(self._top, len(self._history)):
            kind, _text = self._history[i]
            h = self._heights[i]
            if y + h > floor:
                break
            c.create_text(
                PAD, y, anchor="nw", text=self._row_text(self._history[i]),
                fill=MUTED if kind == "q" else REPLY,
                font=FONT_NOTE, width=CARD_W - 2 * PAD, tags="body")
            y += h + CARD_GAP
            drawn += 1
        self._scrollbar(drawn)

        # -- the pinned block, foot-anchored so it cannot drift into the chips
        y = self._h - HELP_FOOT_BAND - self._pinned_h
        if self._history:
            c.create_line(PAD, y - CARD_GAP // 2, CARD_W - PAD, y - CARD_GAP // 2,
                          fill=CHIP, tags="body")
        if question:
            c.create_text(
                PAD, y, anchor="nw", text=question, fill=MUTED,
                font=FONT_NOTE, width=CARD_W - 2 * PAD, tags="body")
            y += q_h + (CARD_GAP if a_h else 0)
        if self._answer:
            c.create_text(
                PAD, y, anchor="nw", text=shown, fill=REPLY,
                font=FONT_BODY, width=CARD_W - 2 * PAD, tags="body")
            y += a_h
            if more:
                c.create_text(
                    PAD, y - 4, anchor="nw", text=f"… {more} more lines", fill=MUTED,
                    font=(*FONT_NOTE, "italic"), tags="body")
                y += BODY_ELIDED_H
        if self._note:
            c.create_text(
                PAD, y, anchor="nw", text=self._note, fill=MUTED,
                font=FONT_NOTE, width=CARD_W - 2 * PAD, tags="body")

        self._chips()
        # The row was created before this render's body, and a canvas draws in creation
        # order — so without this the fresh body sits on top of the chips and takes
        # their clicks. Found by the click storm reading 0/60 after the persistence
        # change that was supposed to fix it.
        c.tag_raise("chips")

    def _scrollbar(self, drawn: int) -> None:
        if self._top == 0 and drawn >= len(self._history):
            return
        c = self.canvas
        x = CARD_W - 9
        y1, y2 = PAD, PAD + self._view_h()
        c.create_rectangle(x, y1, x + 3, y2, fill=CHIP, outline="", tags="body")
        span = max(1, len(self._history))
        shown = max(1, drawn - self._top)
        height = max(24, int((y2 - y1) * shown / span))
        offset = int((y2 - y1 - height) * self._top / max(1, span - shown))
        c.create_rectangle(x, y1 + offset, x + 3, y1 + offset + height,
                           fill=MUTED, outline="", tags="body")

    def _chips(self) -> None:
        session = self.pill.session
        left = getattr(session, "auto_ask_in", None)
        specs = [("Ask", "Ask" if left is None else f"Ask {int(left) + 1}s",
                  self.pill._send)]
        if self._answer and getattr(session, "can_take_reply", False):
            specs.append(("Use this", "Use this", self._take_reply))
        if self._answer:
            specs.append(("Copy", "Copy", self._copy_answer))
        specs.append(("New conversation", "New conversation", self._new_conversation))
        c = self.canvas
        # Rebuilt only when the row has changed — see `Bubble._lay_out`. This card
        # renders on every partial too, so it inherits the same defect and the same fix.
        key_now = (tuple((k, l) for k, l, _c in specs), self._h, self.accent)
        if key_now == self._chips_drawn or (self._frozen() and self._chips_drawn):
            return
        self._chips_drawn = key_now
        c.delete("chips")

        # The same shape the bubble takes: the secondaries as marks in the top-right
        # corner, the primary alone at the foot. Two surfaces that laid their controls
        # out differently would be two things to learn, and the whole point of moving
        # them was one pattern — "commands to icon in pattern adopted for seemless
        # experience".
        for slot, (key, label, cmd) in enumerate(reversed(specs[1:])):
            glyph = COMMAND_GLYPHS.get(key)
            tag = chip_tag(key)
            x2 = command_x(slot, CARD_W - PAD)
            if glyph is None:
                width = chip_w(key, label)
                _round_rect(c, x2 - width, PAD, x2, PAD + COMMAND_H, 13,
                            fill=CHIP, outline="", tags=(tag, "chips"))
                c.create_text(x2 - width / 2, PAD + COMMAND_H / 2, text=label,
                              fill=CODE, font=FONT_CHIP, tags=(tag, "chips"))
            else:
                _round_rect(c, x2 - COMMAND_H, PAD, x2, PAD + COMMAND_H,
                            COMMAND_H // 2, fill=CHIP, outline="", tags=(tag, "chips"))
                glyph(c, x2 - COMMAND_H + (COMMAND_H - ICON_SIZE) / 2,
                      PAD + (COMMAND_H - ICON_SIZE) / 2,
                      COMMAND_COLOURS.get(key, CODE), (tag, "chips"))
            c.tag_bind(tag, "<Button-1>", lambda _e, f=cmd: f())

        key, label, cmd = specs[0]  # Ask, and it is always first
        width = chip_w(key, label)
        y2 = self._h - PAD
        y1 = y2 - CHIP_H
        tag = chip_tag(key)
        _round_rect(c, CARD_W - PAD - width, y1, CARD_W - PAD, y2, 13,
                    fill=PRIMARY_FILL, outline="", tags=(tag, "chips"))
        c.create_text(CARD_W - PAD - width / 2, (y1 + y2) / 2, text=label,
                      fill=PRIMARY_TEXT, font=FONT_CHIP_PRIMARY, tags=(tag, "chips"))
        c.tag_bind(tag, "<Button-1>", lambda _e, f=cmd: f())

    def tick_countdown(self) -> None:
        """Repaint when the auto-ask number changes, and only then."""
        left = getattr(self.pill.session, "auto_ask_in", None)
        shown = None if left is None else int(left) + 1
        if shown == self._countdown:
            return
        self._countdown = shown
        if self._visible:
            self._render()

    def _take_reply(self) -> None:
        if self.pill.session.take_reply():
            self._answer = ""
            self._render()

    def _copy_answer(self) -> None:
        """The whole answer, never the head that is drawn — item 45's promise."""
        problem = self.pill._copy(self._answer)
        self.note(problem or "answer copied")

    def _new_conversation(self) -> None:
        """The session's act, not this window's — item 64.

        It used to clear the card alone, which is the half-clear root 4 is about: the
        thread and the reply would have survived, so the next question would have
        inherited a conversation that was no longer on screen. The card is cleared by
        the `conversation` event coming back the other way.
        """
        self.pill.session.new_conversation()


class Bubble(tk.Frame):
    """The draft, floated above the pill (R14) with Refine / Continue / Send (R15)."""

    #: Copied from the pill at construction rather than read back off it, for the reason
    #: the class attribute exists at all: `self.pill` is a `Mock` in several fixtures, and
    #: `mock.lite` is a truthy Mock — so a bubble that asked its parent each time would
    #: quietly run every Lite branch in tests that are about the full body. Same class-
    #: attribute default as `Pill.lite`, and for the same `__getattr__` reason.
    lite = False

    #: Where the primary chip starts, so the note can end before it — they share a row.
    #: The default is the right edge, which is what an empty row means.
    _primary_x = BUBBLE_W - PAD

    #: Declared on the class as well as assigned in `__init__`, for the reason `lite` is:
    #: `tk.Misc.__getattr__` forwards an unknown attribute to `self.tk`, so on an
    #: instance built with `__new__` — which is how every UI fixture in this suite builds
    #: one — a missing name recurses until the stack ends instead of defaulting. Item 32
    #: found that as a `RecursionError`; item 66 found it again the moment `_render`
    #: started reading two new fields, and the Undo beside an edit note made it three.
    _visible = False
    _pointer_in = False
    _chips_drawn: tuple | None = None
    _note_undo = False

    def __init__(self, pill: Pill) -> None:
        super().__init__(pill)
        self.pill = pill
        self.lite = pill.lite
        # A `Frame` inside the pill's window, not a window of its own. Everything this
        # class draws is canvas-local and did not change; what went is the *window* -
        # its own shell, its own shadow, its own position, and all the arithmetic that
        # kept it touching the pill. See `Pill._sync_shell`.
        self.bg = pill.bg
        self.configure(bg=self.bg)
        self.canvas = tk.Canvas(self, bg=self.bg, highlightthickness=0)
        self.canvas.pack()
        self._visible = False
        self._text = ""
        self._note = ""
        #: Whether the note above the chips came from an edit, and so has a way back to
        #: offer beside it. Only the "edit" event sets it — see `Pill._frame`.
        self._note_undo = False
        self._partial = ""
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
        #: Where a drag on the editor's scroll bar was last seen.
        self._bar_y = 0
        self._h = 120
        #: The chip row last drawn, as `(keys+labels, height, accent)`. Compared before
        #: anything is torn down, so the row survives a body redraw — see `_lay_out`.
        self._chips_drawn: tuple | None = None
        #: True while the pointer is over this window. Nothing moves under the hand.
        self._pointer_in = False
        self.canvas.bind("<Enter>", self._enter, add="+")
        self.canvas.bind("<Leave>", self._leave, add="+")
        self.canvas.bind("<Button-3>", self._context_menu)
        self.place_forget()

    # -- content -----------------------------------------------------------

    def _context_menu(self, e) -> None:
        """Corrections, where the words being corrected actually are.

        Moved off the tray menu (decisions.md 2026-08-09, the six-row menu): "Add
        correction" and "Never offer" both act on the draft, not on Flow generally, and
        this window is what is showing the draft. `Pill._offer_pairs` and
        `Pill._dismiss_pair` do the actual reading and writing — this only borrows them,
        the way `_recent_menu` and `_notes_menu` are borrowed the other direction.

        Absent rather than empty when there is nothing to offer, the same rule every
        other conditional submenu in this app already follows: a right-click that pops
        up onto nothing is a control lying about having something behind it.
        """
        pill = self.pill
        m = _dark_menu(self)
        offered = pill._offer_pairs(m)
        if not offered:
            return
        never = _dark_menu(m)
        for wrong, right in offered:
            never.add_command(
                label=f"{wrong} → {right}",
                command=lambda w=wrong, r=right: pill._dismiss_pair(w, r),
            )
        m.add_cascade(label="Never offer", menu=never)
        previous = 0 if self.lite else foreground_hwnd()
        if not self.lite:
            _user32.SetForegroundWindow(toplevel_hwnd(self))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
            if previous:
                _user32.SetForegroundWindow(previous)

    @property
    def showing_sent(self) -> bool:
        """True while the bubble is holding the words Send just handed over."""
        return bool(self._sent)

    # `show_reply` was here, and with it `_reply`, `_reply_slot`, the reply rendering
    # and the `Use this` chip. They are gone rather than deprecated: this window is about
    # the words being worked on, and an answer is words that have already gone
    # (decisions.md 2026-08-03, "two surfaces, two jobs"). Every guarantee they carried —
    # the head window, the exact `… N more lines`, Copy and `Use this` reading the
    # session rather than the drawn string — is `ConversationCard`'s now, and asserted
    # there. P10 is not weakened by this; it moved.

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
        # Whatever edit the last note was about, its Undo would restore a draft this Send
        # has already taken away — and "Bring it back" is the chip for that now.
        self._note_undo = False
        if problem:
            self._note = problem
        if not self._visible:
            self._visible = True
            self.pill._sync_shell()
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
            self.pill._sync_shell()

    def show_partial(self, text: str) -> None:
        # Partials are dimmed: they contain hallucinated fragments on mid-word
        # boundaries, so "not final yet" has to be visible.
        self._partial, self._sent = text, ""
        self._for_activity = False
        if not self._visible:
            self._visible = True
            self.pill._sync_shell()
        self._render()

    def note(self, msg: str, undoable: bool = False) -> None:
        self._note = msg
        self._note_undo = bool(msg) and undoable
        if self._visible:
            self._render()

    def surface(self, msg: str) -> None:
        """Show a note even with no draft — used for errors, which must be seen."""
        self._note = msg
        # Errors and warnings are this door's traffic; neither is an edit to take back.
        self._note_undo = False
        self._for_activity = False
        if not self._visible:
            self._visible = True
            self.pill._sync_shell()
        self._render()

    def hide(self) -> None:
        # Clear and the cancel hotkey both come through here, and an editor left open
        # would leave `session.editing` true with the window gone — a microphone that
        # is off with nothing on screen to say why. Cancelled rather than committed:
        # the press that got here was somebody stopping, not somebody finishing.
        if self._editor is not None:
            self._cancel_edit()
        self._visible = False
        self._text = self._partial = self._note = self._sent = ""
        self._note_undo = False
        self._for_activity = False
        # Give the band back rather than parking a window offscreen. `park` existed
        # because hiding a Toplevel on Windows cost a taskbar flicker and a restack;
        # there is no window here to hide, only a `place` to undo, and the pill's shell
        # shrinks to the row on the next `_sync_shell`.
        self.place_forget()
        self.pill._sync_shell()

    # -- geometry ----------------------------------------------------------

    def work_h(self) -> int:
        """The tallest this window may be and still be placed inside the desktop.

        Read by `_render` before anything else sees `self._h`, so the height is *already*
        inside the work area by the time it is drawn from, placed with, or used to put the
        chip row at the foot. Bounding only what `reposition` places would leave the chips
        drawn below the visible window — which looks fixed and is not.
        """
        _left, top, _right, bottom = self.pill.work
        return bottom - top - 2 * EDGE_AIR

    def panel_h(self) -> int:
        """The tallest this band may be. Asked of the pill, which owns the window.

        The row shares that window, so the band's ceiling is what the desktop has left
        after the row has taken its 40 px.
        """
        return self.pill.band_h()

    def _settled_h(self, want: int) -> int:
        """`want`, rounded up to a whole body line and clamped to the band's ceiling.

        **The snap is what replaces FluidVoice's 80 ms debounce.** Its overlay sizes to
        its content and coalesces the resizes on a timer; sizing to content is right and
        the timer is a thing to get wrong from inside a render loop that already runs
        thirty times a second. A height that can only change when the text gains or loses
        a *line* changes a handful of times an utterance by construction — no cancelling,
        nothing to leak, and the same absence of thrash.

        The foot does not move whatever this returns: `Pill._sync_shell` grows the window
        upward from a fixed bottom edge, so a step here moves the top edge and nothing
        else.
        """
        want = max(PANEL_MIN_H, want)
        over = want - PANEL_MIN_H
        want = PANEL_MIN_H + -(-over // BODY_LINE_H) * BODY_LINE_H
        return max(PANEL_MIN_H, min(want, self.pill.band_h()))

    @property
    def width(self) -> int:
        """This window's own width — what a docked pill takes on (`Pill.pill_w`)."""
        return BUBBLE_W

    def reposition(self) -> None:
        """Take the top band of the pill's window, or give it back.

        **This used to place a window**, and it took a `lift` argument so `_float_up`
        could animate it in. Both are gone: the panel is the band above the pill row, at
        x=0, and there is nothing left to move it relative to.

        `_float_up` went with it. R14 asked for an appearance the eye could follow, and
        18 px of travel earned that when the bubble was a separate window arriving beside
        another one. Inside a single shell there is nothing to arrive *at* — the window
        itself grows upward from a bottom edge that never moves, which is the same cue
        with no motion under it.
        """
        self.pill._sync_shell()
        if self._visible:
            self.place(x=0, y=0, width=BUBBLE_W, height=self._h)
        else:
            self.place_forget()

    # -- holding still under the hand --------------------------------------

    def _enter(self, _e=None) -> None:
        self._pointer_in = True

    def _leave(self, _e=None) -> None:
        self._pointer_in = False
        # Catch up on everything held back while the hand was here. Without this the
        # window keeps whatever size and chip row it had when the pointer arrived until
        # the next event happens to arrive, which on a settled draft is never.
        if self._visible:
            self._render()

    def _frozen(self) -> bool:
        """True while the pointer is over this window, so it must not move or resize.

        The other half of the lost-click defect, and the half a persistent chip row
        cannot fix on its own: the row can survive the redraw and still end up somewhere
        else on the screen, because `_render` re-measures the window and `reposition`
        re-places it on every partial, every countdown second and every activity frame.
        A note arriving is 30 px of height, which is more than a chip is tall.

        So the rule is the one every menu and tooltip already obeys: **nothing moves
        under the hand.** While the pointer is inside, the geometry is whatever it was
        when the pointer arrived; the body still redraws inside it, and the window
        catches up the moment the hand leaves. The window is bounded and its content is
        capped, so the worst a freeze costs is a line of body clipped for as long as
        somebody is hovering.
        """
        return self._pointer_in and self._visible

    # -- painting ----------------------------------------------------------

    def _body_slot(self, body: str, max_h: int = BODY_MAX_H) -> tuple[str, int, int]:
        """What of the draft is drawn, how many lines are above it, and how tall it is.

        The two halves of the long-draft fix are one measurement, which is why they are
        one function. The bubble may not grow past `max_h` — the chip row is drawn
        from `self._h`, so an unbounded height is an unreachable Send — and the canvas may
        not be asked to lay out more than `BODY_TAIL_CHARS`, because that layout is what
        costs: 476.7 ms for a 50 000-character draft on this machine, on every partial,
        which is a stalled UI thread and then an overflowing microphone.

        `max_h` is `BODY_MAX_H` whenever the window is free to size itself to the
        answer, and the room actually left in it when it is not — see `_render`, where
        a frozen window used to be handed a body measured for a taller one.

        A window that overshoots the cap is shrunk in proportion and measured again,
        deliberately not a line at a time: the loop has to end in a fixed number of probes
        rather than in a number that depends on the draft, or the fix would carry the
        defect. 0.95 undershoots, so the second pass is the last one in practice.

        The height returned is the height that will be *drawn*, never a clamp — a clamped
        height with taller text under it is how a note came to land on the chip row.
        """
        c = self.canvas
        shown, earlier = body_window(body, BODY_TAIL_CHARS)
        text_h = 0
        for _ in range(BODY_PROBES):
            probe = c.create_text(
                PAD, PAD, anchor="nw", text=shown or " ", fill=TEXT,
                font=FONT_BODY, width=BUBBLE_W - 2 * PAD, tags="body")
            _x1, y1, _x2, y2 = c.bbox(probe)
            text_h = y2 - y1
            if text_h <= max_h:
                break
            shown, earlier = body_window(
                body, max(1, int(len(shown) * max_h * 0.95 / text_h))
            )
        return shown, earlier, text_h

    def _partial_slot(self, text: str) -> tuple[str, int]:
        """What of the live partial is drawn, and how tall it actually wraps.

        The partial had no measurement at all. It reserved a flat 34 px and advanced the
        cursor 28 — one line — while being drawn wrapped to the full body column, so the
        second line onward was height the window was never sized for. A long utterance
        put its tail straight through the note, the indicator and the chip row: the exact
        defect fixed for the note on 2026-08-02, on the one element beside it that never
        got the same treatment.

        The tail is kept rather than the head, and that is the behaviour rather than an
        implementation detail: this is the sentence still being spoken, so the words worth
        having on screen are the ones that just arrived. Bounded by `PARTIAL_MAX_H`, in a
        fixed number of probes, for the reasons `_body_slot` gives at length.
        """
        shown, height = text, 0
        for _ in range(BODY_PROBES):
            height = self._probe_h(shown, FONT_PARTIAL)
            if height <= PARTIAL_MAX_H:
                break
            shown, _earlier = body_window(
                text, max(1, int(len(shown) * PARTIAL_MAX_H * 0.95 / height)))
        return shown, height

    # -- the editor's viewport ---------------------------------------------

    def _view(self) -> tuple[float, float]:
        """Where the editor is scrolled to, as `(first, last)` fractions."""
        try:
            first, last = self._editor.yview()
            return float(first), float(last)
        except (AttributeError, TypeError, ValueError, tk.TclError):
            return 0.0, 1.0

    def _hidden_lines(self) -> int:
        """How many display lines of the draft are outside the box right now.

        Counted over the *viewport* and scaled up by how much of the draft that is,
        rather than counted over the whole document (2026-08-09). "The box has already
        laid the text out, so asking it costs one call" was the reasoning here and it
        was wrong: `count -displaylines` over `1.0 … end-1c` makes Tk lay out every
        display line in the widget, and it does not do that in linear time.

            1 000 chars     8.5 ms          8 000     1 097 ms
            2 000          35.5 ms         16 000     7 458 ms
            4 000         187.9 ms         32 000    54 824 ms

        Every doubling costs about six times as much, on the UI thread, inside
        `_render` — so opening a 30 000-character draft in the editor froze Flow for
        the best part of a minute and Windows offered to kill it. Reported from a real
        session, where the draft was a transcript. Worse than the open: `_edit` binds
        `<KeyRelease>` to `_render`, so the whole cost was paid again on every key.

        The viewport is a dozen lines whatever the draft is, which is the bound. What
        it buys back costs accuracy — `yview` fractions are coarse — and that is the
        same bargain the bubble's `… N earlier lines` already makes one window up. A
        hint that is a few lines out is worth a minute of frozen UI.

        Nothing is claimed before the box has a height: an unmapped widget would put
        the whole draft inside a one-pixel viewport and report a number with no
        relation to anything. `_edit` renders again on a timer once Tk has laid the
        box out, which is the render this answers.
        """
        first, last = self._view()
        shown = max(0.0, min(1.0, last - first))
        if shown >= 1.0 or shown <= 0.0:
            return 0
        try:
            height = int(self._editor.winfo_height())
            if height <= 1:
                return 0
            visible = int(self._editor.count(
                "@0,0", f"@0,{height}", "displaylines")[0])
        except (AttributeError, TypeError, IndexError, ValueError, tk.TclError):
            return 0
        return max(0, round(visible * (1.0 - shown) / shown))

    def _edit_hint(self, hint_y: int, box_y: int, height: int) -> None:
        """Say how much of the draft is outside the box, and draw the bar beside it.

        Drawn *after* the box, and that is the whole reason this is a method rather than
        four lines in `_render`: the numbers come off a widget that has to have been laid
        out to have them. `update_idletasks` is what performs that layout — idle tasks
        rather than a full `update`, for the reason `Pill._copy` gives: a full update
        services pending `after` callbacks and would re-enter the frame pump.

        The hint the editor used to suppress. Its old reasoning — "the box holds the
        whole draft and scrolls itself, so a line about what is above the fold would be
        about nothing" — was right about the words and wrong about the person: what is
        on screen is ~20 lines of a draft that may be ten times that, with nothing saying
        so and no bar to see it in.
        """
        # Deliberately no `update_idletasks()` here. It would run inside `_render`, and
        # idle time is where the follow-up render is queued — so the render would
        # re-enter itself, delete the body it is halfway through drawing, and finish
        # into a canvas another pass had already filled. The layout is waited for by the
        # timer `_edit` schedules instead, which is one place rather than every render.
        hidden = self._hidden_lines()
        if hidden:
            self.canvas.create_text(
                PAD, hint_y, anchor="nw",
                text=f"… {hidden} more lines in here — scroll, or drag the bar",
                fill=MUTED, font=(*FONT_NOTE, "italic"), tags="body")
        else:
            # The slot is reserved either way (`_render`'s height budget does not
            # know yet whether there will be anything above the fold to report), so
            # a draft that fits gets the keyboard hints here instead of a blank line
            # — printed where the hand already is, not only in a Help sheet somebody
            # has to already know to open (Phase 6, decisions.md 2026-08-09).
            self._keyboard_hint(hint_y)
        self._edit_bar(box_y, height)

    def _keyboard_hint(self, y: int) -> None:
        """Esc cancels, Ctrl+Enter keeps — as small mono tokens beside plain words."""
        c = self.canvas
        x = PAD
        for token, word in (("Esc", "cancel"), ("Ctrl+↵", "keep")):
            c.create_text(x, y, anchor="nw", text=token, fill=CODE,
                          font=FONT_TRACE, tags="body")
            x += 8 + 7 * len(token)
            c.create_text(x, y, anchor="nw", text=word, fill=MUTED,
                          font=FONT_NOTE, tags="body")
            x += 18 + 6 * len(word)

    def _edit_bar(self, top: int, height: int) -> None:
        """The bar beside the box: where you are, how much there is, and a way to move.

        The Help sheet's `_scrollbar` idiom, in the gutter `EDIT_GUTTER` reserves — on
        the canvas rather than inside the `tk.Text`, because a drag inside a text box
        selects, and trading an editing gesture for a reading one is not an upgrade.

        Drawn only when there is something off screen to point at, like the Help sheet's
        thumb and the draft's elision line. A bar on a box that fits is furniture.
        """
        first, last = self._view()
        if last - first >= 1.0:
            return
        c = self.canvas
        x = BUBBLE_W - PAD - EDIT_GUTTER + 4
        c.create_rectangle(x, top, x + 3, top + height, fill=CHIP, outline="",
                           tags=("body", "editbar"))
        thumb = max(24, int(height * (last - first)))
        offset = int((height - thumb) * first / max(1e-6, 1.0 - (last - first)))
        c.create_rectangle(x, top + offset, x + 3, top + offset + thumb,
                           fill=MUTED, outline="", tags=("body", "editbar"))
        # A wide invisible strip, because a 3 px target is a target nobody hits.
        c.create_rectangle(x - 5, top, x + 8, top + height, fill="", outline="",
                           tags=("body", "editbar"))
        c.tag_bind("editbar", "<ButtonPress-1>", self._bar_grab)
        c.tag_bind("editbar", "<B1-Motion>", lambda e: self._bar_drag(e, top, height))

    def _bar_grab(self, e) -> None:
        self._bar_y = e.y

    def _bar_drag(self, e, top: int, height: int) -> None:
        if self._editor is None or height <= 0:
            return
        moved = (e.y - getattr(self, "_bar_y", e.y)) / height
        self._bar_y = e.y
        first, _last = self._view()
        self._editor.yview_moveto(max(0.0, min(1.0, first + moved)))
        self._render()

    def _wheel_edit(self, e) -> None:
        """Three lines a notch, the Windows default.

        Bound explicitly rather than left to Tk's class binding: the class binding needs
        the widget to have the focus, and while `_edit` does take it, the wheel over an
        unfocused Flow window is exactly the case the Help sheet's docstring is about.
        """
        if self._editor is None:
            return
        self._editor.yview_scroll(-3 * (e.delta // 120 or (1 if e.delta > 0 else -1)),
                                  "units")
        self._render()

    def _probe_h(self, text: str, font=FONT_BODY, width: int | None = None) -> int:
        """How tall `text` wraps to, measured rather than estimated.

        `width` defaults to the full body column. The note passes a narrower one when it
        is sharing its row with an Undo, because a height measured at a width the text
        will not be drawn at is not a measurement.
        """
        probe = self.canvas.create_text(
            PAD, PAD, anchor="nw", text=text or " ", fill=TEXT, font=font,
            width=BUBBLE_W - 2 * PAD if width is None else width, tags="body")
        _x1, y1, _x2, y2 = self.canvas.bbox(probe)
        return y2 - y1

    @property
    def accent(self) -> str:
        """Error, or nothing of its own.

        This was amber — the window's identity, back when the identity was drawn as an
        outline. Nothing reads it as a colour any more: the chrome is neutral, the
        primary chip is `PRIMARY_FILL`, and the indicator's dot takes `WAITING`, which
        is the colour of the thing it is actually reporting. What is left is the one
        state every surface still shares, and the error flash has to keep coming through
        here because the note it belongs to is drawn on this window.

        `MUTED` rather than a fourth ring colour: "resting, claims no state of its own"
        is exactly the answer, and `ring_color` only asks whether this is `ERROR`.
        """
        return ERROR if self.pill.flashing else MUTED

    @property
    def ring_color(self) -> str:
        """The bubble's hairline ring: neutral, not amber.

        Amber's only job in the finished design is the "Bring it back" undo control —
        the panel's own border stopped being a mood the moment three windows needed
        one look (decisions.md 2026-08-09). Still turns red with `accent`, the one
        state every ring shares.
        """
        return ERROR if self.accent == ERROR else RING_OUTER

    def _render(self) -> None:
        c = self.canvas
        accent = self.accent
        # The sent card takes the body slot: it is the same words in the same place,
        # which is what makes "that went to the wrong window" readable at a glance.
        body = self._sent or self._text
        # `body`, not `all` — see `_lay_out`. The chip row outlives a redraw now.
        c.delete("body")

        # Everything that is not the body, measured first — because the body's budget is
        # what is left after them, and while the pointer is inside this window that
        # budget is a hard number rather than a preference. `_frozen` stops the window
        # growing, and until now nothing stopped the *content*: a body sized to
        # `BODY_MAX_H` was drawn into whatever height the window happened to have when
        # the hand arrived. Measured from the reported session — entered with the window
        # 182 px tall, the draft grew underneath and the body reached 355, straight
        # through the note and the chip row, which is the picture that came with it.
        #
        # The note gets measured too, and did not until 2026-08-02. It reserved a flat
        # 18 px — one line — and drew at a fixed offset from the foot with `anchor="nw"`,
        # so every line past the first grew *downward* into the chip row. An Ask that
        # failed on a Hyper-V VM put its reason across Refine / Continue / Ask and the
        # owner could read neither. Errors are the longest strings this ever shows and
        # the ones it is least acceptable to hide.
        #
        # The note gives up the Undo's width when there is one, rather than wrapping
        # under it: two items sharing a row have to agree who owns which half, and the
        # one that can wrap is the one that should be told.
        undo_w = UNDO_W if self._note_undo else 0
        # Ends where the primary chip begins, because they share a row now.
        note_right = getattr(self, "_primary_x", BUBBLE_W - PAD) - CHIP_GAP
        note_w = max(60, note_right - PAD - (undo_w + 8 if undo_w else 0))
        note_h = self._probe_h(self._note, FONT_NOTE, note_w) if self._note else 0
        # Measured for the same reason and never was — see `_partial_slot`. `shown_partial`
        # is what gets drawn below, so the number the window is sized by and the text it is
        # sized for cannot disagree.
        shown_partial, partial_h = ("", 0)
        if self._partial:
            shown_partial, partial_h = self._partial_slot(self._partial)

        # Only the tail of the draft is laid out, and that is the whole of the long-draft
        # fix — see `_body_slot`. The cap is `BODY_MAX_H` while the window is free to
        # size itself to the answer, and the room actually left in it while it is not.
        # `BODY_ELIDED_H` is counted in unconditionally here: a capped body always has
        # something above it to report, and guessing the other way is how a line lands
        # on a control.
        # Unconditional now, and it used to run only while `_frozen()`. That gate was
        # right when the window sized itself to the body: the room left in it was a hard
        # number only while something was stopping it from growing. The window is a fixed
        # shape now (`PANEL_H`), so the room left in it is *always* a hard number, and a
        # body still asking for `BODY_MAX_H` would draw 340 px of text through the note
        # and the chip row of a 184 px panel.
        # `SETTINGS_H` is in here for the reason everything else is: the body's budget is
        # what is left after the fixed furniture, and a strip the height did not know
        # about would be a strip drawn over the first line of the draft.
        # `COMMAND_BAND` joined the furniture when the secondaries moved to the corner.
        # A band the height did not know about is a band drawn over the first line.
        # A one-line note is free: it sits *on* the chip row rather than above it, so
        # only the lines past the first cost the panel anything.
        around = (74 + COMMAND_BAND + BODY_ELIDED_H
                  + (max(0, note_h - NOTE_LINE_H) + 4 if note_h else 0))
        if partial_h:
            around += partial_h + PARTIAL_GAP
        if self._sent:
            around += 16
        if self._act is not None:
            around += 20
        # Against the band's *ceiling*, not against the height it happens to be: the
        # height is about to be computed from this, so reading it here would let a short
        # frame pin the body short on the next one and never grow back.
        body_cap = max(BODY_ELIDED_H, min(BODY_MAX_H, self.panel_h() - around))
        shown, earlier, text_h = self._body_slot(body, body_cap)
        if not body:
            # `_body_slot` probes `shown or " "` so `bbox` always has something to answer
            # about, and that space measures a full line. Nothing draws it — the body is
            # behind `elif body:` — so it was a line's worth of height reserved for text
            # that does not exist, which is most of the "empty air where text will be"
            # the design pass found in the error and loading frames. The body sizes to
            # what it holds, and an empty one holds nothing (decisions.md 2026-08-09).
            text_h = 0
        # The box gets a floor of its own: a one-line draft measures ~18 px, and a
        # text box that size is a slot to squint into rather than something to work in.
        edit_h = max(text_h + 8, 44) if self._editor is not None else 0
        # What the window needs beyond the body itself. One block, counted once: there
        # were two of these, identical, and only the second was read — so the first was a
        # copy that could rot silently against the one that mattered.
        extra = 0
        if edit_h:
            # The hint's slot is reserved whether or not there is anything to say in it.
            # It has to be: the hint sits *above* the box and can only be measured once
            # the box has been laid out, so a layout that depended on the measurement
            # would be deciding the box's position from the box's position. Measured
            # first, it read `… 2484 more lines` for a 60-line draft and drew a bar on a
            # draft that fitted — both on the render before the widget existed.
            extra += edit_h - text_h + 8 + BODY_ELIDED_H
        elif earlier:
            # Outside the editor this counts what the *window* left out; inside it, the
            # line above the box counts what the *box* left out, and both are drawn.
            extra += BODY_ELIDED_H
        if self._sent:
            extra += 16  # the "sent" label above the words
        if partial_h:
            extra += partial_h + PARTIAL_GAP
        if self._act is not None:
            extra += 20
        if self._note:
            extra += note_h + 4
        # Fitted to the desktop before anything reads it. `BODY_MAX_H` bounds what the
        # *draft* asks for; this bounds what the window may be whatever asked — which is
        # the reply path, whose full-text probe is unchanged and is what sizes a 12 000-
        # character artifact to 4 179 px on a 672 px desktop.
        # Nothing moves or resizes under the hand — see `_frozen`.
        if not self._frozen():
            # Snug around the draft again, stepping a line at a time rather than
            # tracking every frame — see `_settled_h`.
            self._h = self._settled_h(text_h + extra + 74 + COMMAND_BAND)
            c.configure(width=BUBBLE_W, height=self._h)
            self.reposition()

        c.delete("body")
        # Squared on the seam it shares with the docked pill, rounded on the free
        # side — `reposition` is what decides above-vs-below, since it already has to.
        # Always the top band of the one window now: rounded head, squared foot on the
        # join it shares with the pill row below it.
        corners = (PANEL_R, PANEL_R, 0, 0)
        _panel_chrome(c, BUBBLE_W, self._h, corners, self.ring_color,
                      seam="bottom")
        y = PAD + COMMAND_BAND
        if self._sent:
            c.create_text(
                PAD, y, anchor="nw", text="sent", fill=MUTED,
                font=("Segoe UI", 8, "bold"), tags="sent",
            )
            y += 16
        hint_y = box_y = 0
        if self._editor is not None:
            hint_y = y
            y += BODY_ELIDED_H
            # The box takes the body's slot rather than opening below it, so the words
            # do not move under the cursor at the moment somebody reaches for them.
            box_y = y
            c.create_window(
                PAD, y, anchor="nw", window=self._editor,
                width=BUBBLE_W - 2 * PAD - EDIT_GUTTER, height=edit_h, tags="body")
            y += edit_h + 6
        elif body:
            if earlier:
                # Said rather than implied: a window with nothing above it reads as the
                # whole draft, and somebody would go looking for words that are there.
                c.create_text(
                    PAD, y, anchor="nw", text=f"… {earlier} earlier lines", fill=MUTED,
                    font=(*FONT_NOTE, "italic"), tags="body")
                y += BODY_ELIDED_H
            # Muted once it has gone: these are no longer the words being worked on.
            #
            # `draft` is a second tag on the live text only, and it is what makes
            # `help.exits_note`'s promise true: that note has said "click the draft to
            # edit" since item 38, and nothing was bound to the body — the one exit named
            # in the sentence somebody reads when the microphone has died. Only the text,
            # so the chips keep their own clicks and the empty card is not a hit region;
            # and not on the sent card, where the words have already gone and `Put it
            # back` is the action.
            c.create_text(
                PAD, y, anchor="nw", text=shown, fill=MUTED if self._sent else TEXT,
                font=FONT_BODY, width=BUBBLE_W - 2 * PAD,
                tags="body" if self._sent else ("body", "draft"))
            if not self._sent:
                c.tag_bind("draft", "<Button-1>", lambda _e: self._edit())
            y += text_h + 6
        if partial_h:
            c.create_text(
                PAD, y, anchor="nw", text=shown_partial, fill=MUTED,
                font=FONT_PARTIAL, width=BUBBLE_W - 2 * PAD, tags="body")
            y += partial_h + PARTIAL_GAP
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
            # On the chip row, not above it. The design put the note and Send on one
            # line — "This is what you build this is what you promise" — and stacking
            # them cost a whole band for a sentence that fits beside the button.
            # Centred on the row: its bottom is half the difference between the chip's
            # height and a line of note text.
            note_baseline = self._h - PAD - (CHIP_H - NOTE_LINE_H) / 2
            c.create_text(
                PAD, note_baseline, anchor="sw", text=self._note,
                fill=MUTED, font=FONT_NOTE, width=note_w, tags="body")
            if self._note_undo:
                # Right-aligned on the note's own last line, in `CODE` so it reads as
                # something to press against the muted sentence it belongs to. Its own
                # tag: `chip_tag` exists because a Tcl tag list splits on spaces, and
                # this one has none, but going through it keeps one rule for one job.
                tag = chip_tag(UNDO_LABEL)
                c.create_text(
                    note_right, note_baseline, anchor="se", text=UNDO_LABEL,
                    fill=CODE, font=FONT_NOTE, tags=(tag, "body"))
                c.tag_bind(tag, "<Button-1>", lambda _e: self._undo_edit())

        if self._editor is not None:
            self._edit_hint(hint_y, box_y, edit_h)

        self._chips()
        # Above the body this render just drew — see the card's `_render` for the
        # measurement that found it.
        c.tag_raise("chips")

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
            specs = [("Bring it back", f"Bring it back {self._linger_left()}s",
                      self._put_back)]
            self._lay_out(specs)
            return
        if getattr(self.pill.session, "editing", False):
            # The whole row, because every other chip acts on a draft that is currently
            # two things at once — what the session holds and what is in the box. One
            # decision to make, so one pair of chips to make it with. Cancel sits to
            # the left of Done — further from the thumb, and not the chip styled to
            # draw the eye — because Done is the safe, committing action and Cancel is
            # the one more easily mis-clicked right beside it (Phase 6).
            self._lay_out([
                ("Cancel", "Cancel", self._cancel_edit),
                ("Done", "Done", self._commit_edit),
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

    #: Every key that draws as the primary chip — light fill, dark text — rather than
    #: window-accent fill the way it used to (Phase 6, decisions.md 2026-08-09): the
    #: one action worth a second look reads the same on every surface now, instead of
    #: inheriting whichever mood the bubble happened to be drawing in.
    PRIMARY_KEYS = ("Send", "Ask", "Bring it back", "Done")

    def _lay_out(self, specs) -> None:
        """Draw the chip row: secondaries packed from the left, the primary pinned right.

        **The primary's right edge is a fixed address.** It used to be wherever the row
        happened to end, so it moved whenever the chip set did — "Was a command" appears
        and Send slides; the clipping fix shrank the gaps and Send slid 342 → 326. The
        one control in this app you cannot take back was the one with no reliable
        position, under a hand already travelling toward where it was a moment ago. So
        the slack lives in the gap *before* the primary and the secondaries absorb every
        change (decisions.md 2026-08-09).

        **Only when the row has actually changed.** The body is deleted and redrawn on
        every partial, every countdown second and every activity frame; the chips are
        not, because a chip that is destroyed and rebuilt under a hand reaching for it
        is the click three users reported losing. `_render` deletes the `body` tag now,
        so this row survives a redraw and is torn down only when its keys, its labels,
        the height it hangs off, or whether it is waiting on a CLI have moved.
        """
        c = self.canvas
        # Waiting on the CLI dims the row rather than hiding it — same geometry, same
        # hit regions, just not the thing to reach for while nothing here can act yet.
        dim = bool(self._act is not None and self._act.waiting)
        # Published before the early return, because the note shares this row now and has
        # to know where it ends — and a frame that skips the rebuild still draws the note.
        primary = next((s for s in specs if s[0] in self.PRIMARY_KEYS), None)
        self._primary_x = (BUBBLE_W - PAD - chip_w(primary[0], primary[1])
                           if primary else BUBBLE_W - PAD)
        key_now = (tuple((k, l) for k, l, _c in specs), self._h, self.accent, dim)
        if key_now == self._chips_drawn or (self._frozen() and self._chips_drawn):
            return
        self._chips_drawn = key_now
        c.delete("chips")

        # The *last* primary, so a row is still laid out sensibly if one ever carries two.
        pinned = max((i for i, (k, _l, _c) in enumerate(specs)
                      if k in self.PRIMARY_KEYS), default=None)
        heads = [i for i in range(len(specs)) if i != pinned]

        # -- the secondaries, as a cluster of marks in the top-right corner ------------
        #
        # They were a row of words along the foot, sharing it with the primary. Asked for
        # as icons — "those commands to go as icon on top right and send" — and the move
        # earns more than tidiness: the foot now holds one control, so the one thing you
        # cannot take back has a row to itself.
        #
        # Right-aligned and laid out right-to-left, so the *rightmost* mark is at a fixed
        # address whatever the set is. The set changes constantly — Edit and Was a command
        # come and go with what was said — and a cluster that grew leftward from the left
        # edge would move every icon under the hand each time.
        right = BUBBLE_W - PAD
        for slot, i in enumerate(reversed(heads)):
            key, label, cmd = specs[i]
            glyph = COMMAND_GLYPHS.get(key)
            tag = chip_tag(key)
            x2 = command_x(slot, right)
            y1 = PAD
            if glyph is None:
                # No mark for this one, so it keeps its word. A glyph nobody can read is
                # worse than a label that is merely longer.
                width = chip_w(key, label)
                _round_rect(c, x2 - width, y1, x2, y1 + COMMAND_H, 13,
                            fill=CHIP, outline="", tags=(tag, "chips"))
                c.create_text(x2 - width / 2, y1 + COMMAND_H / 2, text=label,
                              fill=DISABLED if dim else CODE, font=FONT_CHIP,
                              tags=(tag, "chips"))
                right -= width - COMMAND_H  # this one is wider than a slot
            else:
                _round_rect(c, x2 - COMMAND_H, y1, x2, y1 + COMMAND_H, COMMAND_H // 2,
                            fill=CHIP, outline="", tags=(tag, "chips"))
                glyph(c, x2 - COMMAND_H + (COMMAND_H - ICON_SIZE) / 2,
                      y1 + (COMMAND_H - ICON_SIZE) / 2,
                      DISABLED if dim else COMMAND_COLOURS.get(key, CODE),
                      (tag, "chips"))
            c.tag_bind(tag, "<Button-1>", lambda _e, f=cmd: f())

        # -- the primary, alone at the foot, exactly where it always was ---------------
        if pinned is not None:
            key, label, cmd = specs[pinned]
            width = chip_w(key, label)
            y2 = self._h - PAD
            y1 = y2 - CHIP_H
            tag = chip_tag(key)
            lit = not dim
            _round_rect(c, BUBBLE_W - PAD - width, y1, BUBBLE_W - PAD, y2, 13,
                        fill=PRIMARY_FILL if lit else CHIP, outline="",
                        tags=(tag, "chips"))
            c.create_text(BUBBLE_W - PAD - width / 2, (y1 + y2) / 2, text=label,
                          fill=PRIMARY_TEXT if lit else DISABLED,
                          font=FONT_CHIP_PRIMARY, tags=(tag, "chips"))
            c.tag_bind(tag, "<Button-1>", lambda _e, f=cmd: f())

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
            self.pill._sync_shell()
        elif act is None and self._for_activity and not (
            self._text or self._partial or self._note
        ):
            self.hide()
            return
        if self._visible:
            self._render()
        if surfacing:
            # After the render, not before: `reposition` places the band against
            # `self._h`, which is what the render computes.
            self.reposition()

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
                    # `WAITING`, not this window's accent: the dot reports the same wait
                    # the pill's glyph is reporting, and one state gets one colour. It
                    # was amber, which said "draft bubble" about a fact that has nothing
                    # to do with which window is drawing it.
                    fill=WAITING if lit else CHIP, outline="",
                    tags=("body", "waiting"),
                )
        else:
            c.create_line(x, y + 8, x + 24, y + 8, fill=MUTED, width=2,
                          tags=("body", "waiting"))
        c.create_text(
            x + 34, y, anchor="nw", text=self._act.label, fill=MUTED,
            # `body` as well as `indicator`, because `_render` deletes by the first and
            # everything looks for it by the second. Without it the dots and the label
            # outlived every redraw and stacked up — found by the selfdrive harness,
            # which reads the *oldest* matching item and so quietly reported a state
            # that had been gone for seconds.
            font=FONT_NOTE, tags=("body", "indicator"),
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

    def _undo_edit(self) -> None:
        """Take back the edit the note is describing.

        Holds the auto-ask clock for the same reason every chip does: somebody
        disagreeing with a correction is still working on this draft, and having it sent
        out from under them mid-disagreement is the worst possible moment for it.
        """
        self.pill.session.hold_auto_ask()
        self.pill.session.undo_edit()

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
        # Neutral, not `self.accent`: amber's only remaining job is the "Bring it back"
        # chip, and an editing box is not that (Phase 6, decisions.md 2026-08-09).
        box = self._editor = tk.Text(
            self, bg=SHELL, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightbackground=RING,
            highlightcolor=RING, wrap="word",
            font=FONT_BODY, undo=True, padx=6, pady=4,
        )
        box.insert("1.0", text)
        # Escape cancels and Ctrl+Enter commits; a bare Enter is a newline, because a
        # prompt is not a single line and the chips are the discoverable way out anyway.
        box.bind("<Escape>", lambda _e: (self._cancel_edit(), "break")[1])
        box.bind("<Control-Return>", lambda _e: (self._commit_edit(), "break")[1])
        # The wheel over the box, and a repaint after every key, so the bar and the
        # count beside it follow the cursor instead of describing where it used to be.
        box.bind("<MouseWheel>", self._wheel_edit)
        box.bind("<KeyRelease>", lambda _e: self._render(), add="+")
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
            return
        # A second render on a timer, because the first render is what *created* the
        # box: a widget Tk has not laid out yet cannot say how many of its lines are off
        # screen. Measured, and each cheaper answer was tried and failed — rendered once,
        # the hint read `… 2484 more lines` for a 60-line draft, which is a character
        # count wearing a line count's label; called directly a second time it drew
        # nothing; `after_idle` drew nothing, because the geometry manager had still not
        # run. One frame is the first moment the box knows its own size, and it is
        # imperceptible. Scheduled after the verification, so nothing sits between
        # `focus_force` and the check that reads what the focus did.
        self.after(20, self._render)

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
