"""Put the finished draft into the app the user was working in (R1).

Not "whatever has focus", which is what this said and what it did, and the difference
is the whole of stage 12: at the moment Send runs, the click that ran it may already
have moved the focus. The caller says which window it meant; `resolve()` is where that
is reconciled with what the OS reports.

Clipboard + Ctrl-V rather than typing the text character by character: pasting is one
event regardless of length, survives IME and autocomplete, and does not race with the
target app's input handling.

stdlib `ctypes` only — no `pyautogui`, no `pywin32`, no `keyboard` (R16).
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Every signature below is declared explicitly, and that is not stylistic. ctypes
# defaults an undeclared restype to C `int` — 32 bits — so on x64 a returned HANDLE or
# pointer is silently truncated. The first version of this file omitted them and
# dereferencing the truncated GlobalLock pointer crashed the interpreter outright
# (access violation, exit 0xC0000005).
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
VK_CONTROL, VK_V = 0x11, 0x56


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def _key(vk: int, up: bool = False) -> INPUT:
    return INPUT(
        type=INPUT_KEYBOARD,
        u=_UNION(ki=KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP if up else 0)),
    )


def _send(*inputs: INPUT) -> int:
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def get_clipboard_text() -> str | None:
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.c_wchar_p(ptr).value
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(ptr, ctypes.create_unicode_buffer(text), size)
        finally:
            kernel32.GlobalUnlock(handle)
        # Ownership transfers to the clipboard only on success; on failure it is still
        # ours to free, or it leaks for the life of the process.
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


#: Warnings raised by the last paste, drained by the UI. A module-level queue rather
#: than a return value because `paste` already returns success, and a caller that
#: ignores the warning must still see it — the whole point is that the user is told.
_WARNINGS: list[str] = []


def take_warnings() -> list[str]:
    out = list(_WARNINGS)
    _WARNINGS.clear()
    return out


def paste(text: str, *, hwnd: int | None = None, restore_clipboard: bool = True) -> bool:
    """Place `text` on the clipboard and send Ctrl-V to the window it is aimed at.

    `hwnd` is the window the caller believes it is pasting into, and passing one is
    strongly preferred: see `resolve()` for why asking the OS at this moment is not a
    question that can be trusted.

    Returns False if the paste was refused or the clipboard could not be taken — another
    process can hold it briefly, and silently doing nothing would look like the Send
    button is broken. Every False leaves a line in `take_warnings()` saying which.

    Known limitation: an elevated target window will not accept synthetic input from a
    non-elevated process (UIPI). The text is still on the clipboard, so a manual Ctrl-V
    works — which is why the clipboard is written before the keystroke is attempted.
    """
    # P7: the target decides what is safe to send. Classified *before* the clipboard
    # is touched, because knowing the target is what tells us whether the trailing
    # newline would press Enter in a shell.
    target = resolve(hwnd)
    if target.is_flow:
        # Invariant: Flow does not paste into itself. Reaching here means the click
        # took the foreground after all, so the Ctrl-V is going to land on a Tk canvas
        # whatever this function believes — and that is a defect to report, not a paste
        # to attempt. This is exactly the state that used to return True.
        _WARNINGS.append(
            "not pasted: Flow had the focus, not the window you were aiming at"
        )
        return False

    payload, warning = prepare(text, target)
    if warning:
        _WARNINGS.append(warning)

    previous = get_clipboard_text() if restore_clipboard else None
    if not set_clipboard_text(payload):
        _WARNINGS.append("not pasted: could not take the clipboard")
        return False

    _send(_key(VK_CONTROL), _key(VK_V), _key(VK_V, up=True), _key(VK_CONTROL, up=True))

    if previous is not None:
        def restore() -> None:
            # Let the target app read the clipboard before handing it back.
            time.sleep(0.6)
            set_clipboard_text(previous)

        threading.Thread(target=restore, daemon=True).start()
    return True


# -- P7: knowing what you are pasting into ---------------------------------

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = wintypes.DWORD

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

#: Window classes that are a console, whoever is hosting them.
TERMINAL_CLASSES = {
    "consolewindowclass",  # conhost: cmd.exe, legacy PowerShell
    "cascadia_hosting_window_class",  # Windows Terminal
    "mintty",  # Git Bash
    "vtwin32class",
}

#: Process names that are a terminal even when the window class is generic.
TERMINAL_PROCESSES = {
    "windowsterminal.exe", "wt.exe", "conhost.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "mintty.exe", "bash.exe", "alacritty.exe", "wezterm-gui.exe",
    "kitty.exe", "hyper.exe", "conemu64.exe", "conemu.exe", "cmder.exe",
}

#: Terminals that implement bracketed paste, so the *shell* receives a multi-line
#: paste as literal text instead of running each line as it arrives. The terminal adds
#: the markers itself on Ctrl-V — Flow must not add them to the clipboard, or the app
#: would see a second, literal pair.
BRACKETED_PASTE = {
    "windowsterminal.exe", "wt.exe", "mintty.exe", "alacritty.exe",
    "wezterm-gui.exe", "kitty.exe", "hyper.exe", "conemu64.exe", "conemu.exe",
}


class Target:
    """What is about to be pasted into, and what that means for the payload."""

    def __init__(
        self, window_class: str = "", process: str = "", is_flow: bool = False
    ) -> None:
        self.window_class = window_class
        self.process = process
        #: This window belongs to Flow. Decided by process id rather than by name,
        #: because Flow is a `python.exe` like any other and the target might be too.
        self.is_flow = is_flow

    @property
    def is_terminal(self) -> bool:
        return (
            self.window_class.lower() in TERMINAL_CLASSES
            or self.process.lower() in TERMINAL_PROCESSES
        )

    @property
    def brackets_paste(self) -> bool:
        return self.process.lower() in BRACKETED_PASTE

    def __repr__(self) -> str:
        return (f"Target(class={self.window_class!r}, process={self.process!r}"
                + (", flow" if self.is_flow else "") + ")")


def _pid_of(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def owned_by_flow(hwnd) -> bool:
    """True when `hwnd` is one of Flow's own windows.

    By process id, which covers the pill, the bubble and the right-click menu without
    any of them having to register themselves anywhere.
    """
    try:
        return bool(hwnd) and _pid_of(hwnd) == kernel32.GetCurrentProcessId()
    except OSError:
        return False


def foreground_hwnd() -> int:
    """Whatever has the foreground right now, or 0. Never raises."""
    try:
        return user32.GetForegroundWindow() or 0
    except OSError:
        return 0


def _process_name(hwnd) -> str:
    pid = _pid_of(hwnd)
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(handle)


def classify(hwnd) -> Target:
    """Classify one window. Never raises: an unknown target is treated as ordinary,
    which is the behaviour Flow had before any of this existed."""
    try:
        if not hwnd:
            return Target()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return Target(buf.value, _process_name(hwnd), is_flow=owned_by_flow(hwnd))
    except OSError:
        return Target()


def foreground_target() -> Target:
    """Classify whatever has the foreground."""
    return classify(foreground_hwnd())


def resolve(hwnd: int | None = None) -> Target:
    """Decide what is being pasted into, given what the caller was aiming at.

    Two windows are consulted and they answer different questions.

    The **live foreground** is who will physically receive the keystroke, so if that is
    Flow, no belief of the caller's can make the paste land anywhere else. It is checked
    first and it is a refusal, not a target.

    Otherwise the **caller's window wins**, and that is the fix rather than a nicety.
    `GetForegroundWindow()` at paste time is a question asked after the click that
    started the Send, and for the whole life of this app the answer was Flow's own
    window — so `prepare()` classified a Tk canvas, decided it was not a terminal, and
    skipped the newline strip that is P7's one guarantee. The caller polls the same
    question 30 ms earlier and keeps the last answer that was not Flow, which is the
    only version of it worth acting on.
    """
    live = classify(foreground_hwnd())
    if live.is_flow or not hwnd:
        return live
    return classify(hwnd)


def prepare(text: str, target: Target) -> tuple[str, str]:
    """(payload, warning) for pasting `text` into `target`.

    Two rules, and only the first is a guarantee:

    **Never submit for the user.** A draft ending in a newline pastes as text plus
    Enter, which in a shell runs it. The trailing newline is always stripped for a
    terminal; the user presses Enter when they mean to.

    **Say so when the rest cannot be guaranteed.** Interior newlines are the terminal's
    business, not Flow's: a terminal with bracketed paste hands the whole block to the
    shell as literal text, and one without runs each line as it arrives. Flow cannot
    change that from outside — adding the bracket markers to the clipboard would be
    doubly wrong, since the terminal adds its own. So it reports it instead of pretending.
    """
    if not target.is_terminal:
        return text, ""
    payload = text.rstrip("\r\n")
    multiline = "\n" in payload
    if multiline and not target.brackets_paste:
        return payload, (
            f"{target.process or 'this terminal'} may run each line as it arrives - "
            "paste is not bracketed here"
        )
    return payload, ""
