"""A notification-area icon, so Flow can be out of the way without being lost.

The need, in the owner's words: "there are times where i wanted to dictate but at the
same time i wanted to see but i don't want it to keep it on my screen". The overlay can
already be parked off the desktop — `ui.park` does it — and parking alone is a trap. A
Flow with no window and no icon is a process you cannot reach, cannot configure and
cannot quit except through Task Manager, which is invariant 4's problem wearing a
different hat: hidden must not mean gone.

So hiding gets an icon, and the icon is the way back.

**Win32 through ctypes, no new dependency** (R16 holds at three). `Shell_NotifyIconW`
needs a window to send its click messages to, and Tk will not give us one — its window
procedure is Tcl's, and subclassing it to intercept a custom message would put our code
on the path of every event Tk handles. So this creates its own **message-only window**
(`HWND_MESSAGE`), which has no pixels, never draws and exists purely to receive.

**It runs its own message loop on its own thread**, for the same reason. `GetMessageW`
blocks, and Tk's loop is not ours to block. The two never touch: the window procedure
runs on this thread, and everything it learns is put on a `queue.Queue` that the UI
drains from its own frame pump. Nothing here calls into Tk, which is the rule that makes
threading here safe rather than merely tested.

**Stock icon, deliberately.** `IDI_APPLICATION` rather than an `.ico` shipped in the
package: an icon file is a binary asset in a repository that has none, and a tray icon
that is obviously a placeholder is more honest than one that took a build step to look
official. It is a line to change when Flow has artwork.
"""

import ctypes
import queue
import sys
import threading
from ctypes import wintypes

#: What the icon puts on the queue. Strings rather than callbacks, because the callback
#: would then run on this module's thread — and the one rule here is that nothing this
#: file owns ever touches Tk.
SHOW = "show"
QUIT = "quit"

#: The message the shell sends us for every click on the icon. `WM_APP` and above are
#: reserved for an application's own use, which is exactly what this is.
_WM_APP = 0x8000
_WM_TRAY = _WM_APP + 1

#: Menu command ids. Any positive int the popup can return; they mean nothing outside it.
_ID_SHOW = 1
_ID_QUIT = 2

_WM_DESTROY = 0x0002
_WM_RBUTTONUP = 0x0205
_WM_LBUTTONUP = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_COMMAND = 0x0111

_NIM_ADD, _NIM_DELETE = 0x0, 0x2
_NIF_MESSAGE, _NIF_ICON, _NIF_TIP = 0x1, 0x2, 0x4
_IDI_APPLICATION = 32512
_IMAGE_ICON = 1
_LR_SHARED = 0x8000
_HWND_MESSAGE = -3
_MF_STRING = 0x0
_TPM_RETURNCMD = 0x0100
_TPM_RIGHTBUTTON = 0x0002

_LRESULT = ctypes.c_ssize_t

#: **Defined only on Windows, because `ctypes.WINFUNCTYPE` exists only there.**
#:
#: Everything else in this file reaches Win32 from inside a function, so it was safe to
#: import anywhere and inert off Windows — which is what `available()` promises and what
#: every caller relies on. These two were the exception: a callback type built at module
#: scope, and the structure that embeds it in a field list evaluated at class-definition
#: time. Importing this module on a Mac therefore raised `AttributeError: module
#: 'ctypes' has no attribute 'WINFUNCTYPE'` before a single line of it could run.
#:
#: The cost was out of all proportion to the cause. `ui.py` imports `tray`
#: unconditionally, so the failure was not "no tray icon on a Mac" — it was **every test
#: that touches `flow.ui` erroring on import**: 208 of them, one root cause, and a macOS
#: CI leg that had never been green. Found by that leg on 2026-09-01.
#:
#: A `getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)` fallback would also import, and
#: is refused: it would manufacture a callback type with the wrong calling convention and
#: keep it in a variable named for the right one, so the next person to use it off
#: Windows gets a crash somewhere else entirely. Nothing off Windows may have these,
#: because nothing off Windows may use them.
if sys.platform == "win32":
    _WNDPROC = ctypes.WINFUNCTYPE(
        _LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", _WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]


class _NOTIFYICONDATAW(ctypes.Structure):
    """The shell's icon record.

    `szTip` is 128 wide characters in every version since Windows 2000 and `cbSize` is
    how the shell knows which layout it is being handed — so it is `sizeof` this struct
    and never a number typed in.
    """

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


def _declare() -> None:
    """Give ctypes the signatures, rather than letting it guess.

    Without this every call is assumed to return `c_int`, and a 64-bit `HWND` does not
    fit in one: `CreateWindowExW` came back as `OverflowError: int too long to convert`
    from inside the tray thread, where nothing was watching. The handle-returning calls
    are the ones that matter, and the parent handle has to be a real `HWND` too —
    `HWND_MESSAGE` is -3, which is only meaningful once ctypes knows it is a pointer.
    """
    u = ctypes.windll.user32
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    u.DefWindowProcW.restype = _LRESULT
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM]
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.TrackPopupMenu.restype = wintypes.BOOL
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                 wintypes.LPVOID]
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                               wintypes.WPARAM, wintypes.LPARAM]
    ctypes.windll.kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    ctypes.windll.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


class Tray:
    """One notification-area icon, or nothing at all if the shell refuses.

    Every failure is reported rather than raised. A tray icon is a convenience on top of
    a working app, and an app that will not start because the notification area was busy
    would be a worse trade than an app with no icon — `start()` answers False and the
    caller keeps the pill on screen, which is the state everybody had before this file.
    """

    def __init__(self, title: str = "Flow", events: queue.Queue | None = None) -> None:
        self.title = title
        #: What the icon's clicks arrive on. Owned by the caller when it passes one, so
        #: a UI can drain this and its own events from the same place.
        self.events: queue.Queue = events if events is not None else queue.Queue()
        self.hwnd = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._ok = False
        #: The window procedure, kept alive here on purpose. ctypes callbacks are garbage
        #: like anything else, and one collected while Windows still holds its address is
        #: an access violation in a thread nobody is watching.
        self._proc = _WNDPROC(self._on_message)
        self._class = f"FlowTray{id(self):x}"

    # -- the thread that owns the window ------------------------------------

    def start(self) -> bool:
        """Put the icon in the notification area. Returns whether it is actually there.

        Blocks until the answer is known — at most a moment, and worth waiting for: a
        caller that hid its window on the strength of an icon that never appeared would
        have hidden it for good.
        """
        if self._thread is not None:
            return self._ok
        self._thread = threading.Thread(target=self._serve, name="flow-tray",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        return self._ok

    def stop(self) -> None:
        """Take the icon away. Safe to call twice, and safe to call if it never worked."""
        if not self.hwnd:
            return
        try:
            _shell().Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._icon_data()))
            ctypes.windll.user32.DestroyWindow(self.hwnd)
        except OSError:
            pass
        self.hwnd = 0

    def _icon_data(self, with_icon: bool = False) -> _NOTIFYICONDATAW:
        data = _NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        data.uCallbackMessage = _WM_TRAY
        if with_icon:
            # `MAKEINTRESOURCE`: a stock icon is identified by an integer squeezed
            # into a string pointer, which is what `LPCWSTR(id)` builds here.
            data.hIcon = ctypes.windll.user32.LoadImageW(
                None, wintypes.LPCWSTR(_IDI_APPLICATION), _IMAGE_ICON, 0, 0,
                _LR_SHARED)
        data.szTip = self.title
        return data

    def _serve(self) -> None:
        """Register, create, add the icon, then pump messages until the window dies."""
        try:
            self._ok = self._build()
        except OSError:
            self._ok = False
        finally:
            self._ready.set()
        if not self._ok:
            return
        msg = wintypes.MSG()
        user32 = ctypes.windll.user32
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _build(self) -> bool:
        _declare()
        user32 = ctypes.windll.user32
        cls = _WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        cls.lpfnWndProc = self._proc
        cls.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        cls.lpszClassName = self._class
        if not user32.RegisterClassExW(ctypes.byref(cls)):
            return False
        # `HWND_MESSAGE` as the parent: a window with no pixels, no place on the desktop
        # and no chance of being shown by accident. It exists to be sent to.
        self.hwnd = user32.CreateWindowExW(
            0, self._class, self.title, 0, 0, 0, 0, 0,
            wintypes.HWND(_HWND_MESSAGE), None, cls.hInstance, None)
        if not self.hwnd:
            return False
        return bool(_shell().Shell_NotifyIconW(
            _NIM_ADD, ctypes.byref(self._icon_data(with_icon=True))))

    # -- what the shell tells us --------------------------------------------

    def _on_message(self, hwnd, message, wparam, lparam) -> int:
        """The window procedure. Runs on this module's thread and never touches Tk.

        Everything it decides goes on the queue; the UI acts on it from its own loop.
        """
        if message == _WM_TRAY:
            event = lparam & 0xFFFF
            try:
                if event in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                    self.events.put(SHOW)
                elif event == _WM_RBUTTONUP:
                    self._popup()
            except Exception as exc:  # pragma: no cover - belt for a callback
                # Nothing may escape a ctypes callback: Windows called us, and an
                # exception unwinding into its stack is undefined at best. Printed
                # rather than swallowed, because a tray that silently stops answering
                # is the failure this file exists to prevent.
                print(f"flow: tray click failed: {exc}", file=sys.stderr, flush=True)
            return 0
        if message == _WM_DESTROY:
            ctypes.windll.user32.PostQuitMessage(0)
            return 0
        return ctypes.windll.user32.DefWindowProcW(
            wintypes.HWND(hwnd), wintypes.UINT(message),
            wintypes.WPARAM(wparam), wintypes.LPARAM(lparam))

    def _popup(self) -> None:
        """The right-click menu: the two things a hidden app has to offer.

        `SetForegroundWindow` first, and the `PostMessage` after, are both from the
        documented recipe: a popup owned by a window that is not foreground never
        receives the click that dismisses it, and stays on screen until something else
        is clicked.
        """
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            user32.AppendMenuW(menu, _MF_STRING, _ID_SHOW, "Show Flow")
            user32.AppendMenuW(menu, _MF_STRING, _ID_QUIT, "Quit Flow")
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(self.hwnd)
            chosen = user32.TrackPopupMenu(
                menu, _TPM_RETURNCMD | _TPM_RIGHTBUTTON,
                point.x, point.y, 0, self.hwnd, None)
            # `PostMessageW`, with the W. There is no bare `PostMessage` export in
            # user32 — the name is a macro in C that resolves to one of the two — so
            # asking for it raised `AttributeError: function 'PostMessage' not found`
            # *after* the menu had been chosen from and before anything acted on the
            # choice. Right-clicking the icon showed the menu and then did nothing.
            user32.PostMessageW(self.hwnd, 0, 0, 0)
        finally:
            user32.DestroyMenu(menu)
        if chosen == _ID_SHOW:
            self.events.put(SHOW)
        elif chosen == _ID_QUIT:
            self.events.put(QUIT)


def _shell():
    return ctypes.windll.shell32


def available() -> bool:
    """Whether this platform has a notification area at all.

    Windows-only by construction. macOS has a menu bar item and Linux has whatever the
    desktop environment offers, and neither is `Shell_NotifyIcon` — so this says no
    rather than pretending, and the caller keeps its window on screen.
    """
    return sys.platform == "win32"
