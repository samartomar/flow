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
user32.GetClipboardSequenceNumber.argtypes = []
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD

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
VK_CONTROL, VK_V, VK_RETURN = 0x11, 0x56, 0x0D

#: How many events each burst is, so `SendInput`'s return value can be read as an answer
#: rather than discarded. It reports how many it *inserted*, and a short count is not a
#: slow paste — it is a refused one. UIPI is the ordinary way to get a zero: a
#: non-elevated process cannot synthesise input into an elevated window, and Windows says
#: so only here. Both numbers are the length of their own literal argument list below;
#: named because a check against a magic 4 is a check nobody can verify by reading it.
PASTE_KEYS = 4
SUBMIT_KEYS = 2


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


def clipboard_sequence() -> int:
    """Windows' clipboard change counter, or 0 if it will not say. Never raises.

    The only way to ask "does the clipboard still hold what Flow put there" without
    reading the contents — which would not answer it anyway, since the user could have
    copied the same text, and reading costs an `OpenClipboard` that can fail.
    """
    try:
        return int(user32.GetClipboardSequenceNumber())
    except OSError:
        return 0


#: How long the target app gets to read the clipboard before Flow hands it back. The
#: paste is asynchronous — `SendInput` queues a keystroke, it does not wait for the app
#: to process it — so restoring immediately would put the old text back before the new
#: text had been read.
RESTORE_DELAY_SEC = 0.6

class _Borrowed:
    """The single clipboard transaction: what Flow owes back, and who gives it.

    Two sends inside `RESTORE_DELAY_SEC` used to be two independent borrowings, and the
    second one asked the *clipboard* what it owed — at a moment when the clipboard held
    Flow's own payload from the first send. So B restored A's text and the user's real
    clipboard was gone permanently, with nothing on screen about it, because from B's
    point of view nothing anomalous had happened.

    `clipboard_sequence` cannot catch this and it is worth saying why, since it looks
    like exactly the guard for it: the counter *did* move between A's write and B's
    read. It moved because of Flow. A stamp answers "is this still mine", not "was the
    thing I found also mine".

    So the borrowing happens once per burst. A send arriving while a restore is pending
    inherits what is already owed rather than reading; the last send to arrive sets the
    deadline; one worker wakes, re-reads that deadline, and commits when it has finally
    passed. That also retires the thread-per-send — the audit measured 300 sleeping
    threads for 300 rapid pastes, and this reproduces at 100 for 100.
    """

    def __init__(self) -> None:
        # Re-entrant because the commit path holds it across `set_clipboard_text`, which
        # keeps a restore and a `paste` from interleaving inside one clipboard.
        self.lock = threading.RLock()
        #: What the user had before Flow's *first* borrow of this burst, or None when
        #: nothing is owed. Not a stack: Flow owes the user one clipboard, not one per
        #: send it made in between.
        self.owed: str | None = None
        #: The counter reading from the most recent send, so a copy made during the
        #: pause is still detected — that guard is unchanged and pre-dates this.
        self.stamp = 0
        self.due = 0.0
        self.worker: threading.Thread | None = None


_BORROWED = _Borrowed()


#: Warnings raised by the last paste, drained by the UI. A module-level queue rather
#: than a return value because `paste` already returns success, and a caller that
#: ignores the warning must still see it — the whole point is that the user is told.
#:
#: Locked because the restore runs on its own thread, `RESTORE_DELAY_SEC` after `paste`
#: has returned. `list.append` is atomic, but `take_warnings` copies and then clears,
#: and a line appended between those two statements would be dropped without trace —
#: which is the one thing a warning queue may not do.
_WARNINGS: list[str] = []
_WARNINGS_LOCK = threading.Lock()


def _warn(line: str) -> None:
    with _WARNINGS_LOCK:
        _WARNINGS.append(line)


def take_warnings() -> list[str]:
    with _WARNINGS_LOCK:
        out = list(_WARNINGS)
        _WARNINGS.clear()
        return out


def _borrow(restore: bool) -> str | None:
    """Register one send against the transaction, and answer what it owes back."""
    with _BORROWED.lock:
        if restore and _BORROWED.owed is None:
            # Only ever asked when nothing is pending. This single condition is the
            # whole fix: while a restore is outstanding the clipboard holds Flow's text,
            # so reading it here is what mistook send A's payload for the user's.
            _BORROWED.owed = get_clipboard_text()
        return _BORROWED.owed if restore else None


def _release() -> None:
    """Give the transaction up without restoring — the payload is staying, deliberately.

    Every refusal below leaves Flow's text on the clipboard and says so, because the
    recovery on offer is the user pressing Ctrl-V. Once that has been said, owing the old
    clipboard back is a debt that must not be paid: the next send, possibly an hour
    later, would restore over the very text they were told to paste by hand.
    """
    with _BORROWED.lock:
        _BORROWED.owed = None


def _schedule_restore(stamp: int) -> None:
    """Arm — or re-arm — the one restore worker."""
    with _BORROWED.lock:
        _BORROWED.stamp = stamp
        _BORROWED.due = time.monotonic() + RESTORE_DELAY_SEC
        if _BORROWED.worker is not None and _BORROWED.worker.is_alive():
            return  # it re-reads `due` when it wakes; a second thread would add nothing
        _BORROWED.worker = threading.Thread(
            target=_restore_worker, daemon=True, name="clipboard-restore"
        )
        _BORROWED.worker.start()


def _restore_worker() -> None:
    while True:
        with _BORROWED.lock:
            wait = _BORROWED.due - time.monotonic()
            if wait <= 0:
                previous, stamp = _BORROWED.owed, _BORROWED.stamp
                _BORROWED.owed = None
                _BORROWED.worker = None
                if previous is None:
                    return
                now = clipboard_sequence()
                if stamp and now and now != stamp:
                    # Somebody copied something during that pause. Putting the old text
                    # back now would not be a restore — it would be Flow deleting a thing
                    # the user did *after* the paste, which is the one clipboard write
                    # nobody could explain. A zero on either reading means the counter was
                    # unavailable, not that nothing happened, so it is not taken as proof.
                    _warn("kept what you copied since - the clipboard Flow borrowed was "
                          "not put back")
                    return
                set_clipboard_text(previous)
                return
        time.sleep(wait)


def paste(
    text: str,
    *,
    hwnd: int | None = None,
    restore_clipboard: bool = True,
    submit: bool = False,
) -> bool:
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
        _warn("not pasted: Flow had the focus, not the window you were aiming at")
        return False
    if target.stale:
        # Same refusal, one window over: something took the foreground between the poll
        # and the click, so the Ctrl-V would land there — carrying a payload prepared
        # for the window the user was actually aiming at.
        _warn(
            "not pasted: the target window changed before Send"
            + (f" - {target.process} has the focus now" if target.process else "")
        )
        return False

    payload, warning = prepare(text, target)

    # Text only, and that is a real limit rather than an oversight: a clipboard holding
    # an image or a file list reads as None here, so there is nothing to put back — and
    # `set_clipboard_text` empties it on the way in, so what was there is gone rather
    # than restored. Capturing arbitrary formats means enumerating and copying every one
    # of them, which is a great deal of ctypes for a path that ends with Flow owning a
    # copy of the user's screenshot.
    previous = _borrow(restore_clipboard)
    if not set_clipboard_text(payload):
        _warn("not pasted: could not take the clipboard")
        # Nothing was written, so nothing is owed by *this* send — but an earlier send in
        # the same burst may still have a restore pending, and that one is still owed.
        # Leaving the transaction alone is what keeps it.
        return False
    if runs_on_arrival(payload, target):
        # P7's second half, and it is a refusal rather than the warning it used to be.
        # The Ctrl-V *is* the execution here — a bare terminal runs line one while line
        # two is still arriving — so a message about it is written after the fact by
        # construction, however promptly the bubble paints it.
        #
        # Refused *after* the clipboard write, which is the whole recovery: pasting by
        # hand is the same keystroke Flow just declined to synthesise, and doing it
        # deliberately is exactly the difference between the two. Flow does not get to
        # decide that a script may never be pasted into cmd.exe — only that it will not
        # be the one to press the key. No restore, for the same reason it is skipped on a
        # refused insertion: it would take away the thing the hand needs.
        _warn(f"not pasted: {warning} - the text is on the clipboard, so Ctrl-V is yours")
        _release()
        return False

    if warning:
        _warn(warning)

    # Stamped the moment Flow's own text lands, so anything that moves the counter from
    # here on is somebody else.
    stamp = clipboard_sequence()

    inserted = _send(
        _key(VK_CONTROL), _key(VK_V), _key(VK_V, up=True), _key(VK_CONTROL, up=True)
    )
    if inserted != PASTE_KEYS:
        # The count was always computed and always thrown away, which is how an Enter
        # could follow a Ctrl-V that inserted nothing — into a shell, running whatever
        # was already on the prompt. That is the failure P7 exists to prevent, arriving
        # one layer below where P7 looks.
        #
        # Returning here also means the clipboard is *not* put back, and that is the
        # point rather than an oversight: the recovery this function's docstring promises
        # for the UIPI case is the user pressing Ctrl-V themselves, and a restore would
        # take away the thing they need to press it on.
        _warn(
            f"not pasted: Windows took {inserted} of {PASTE_KEYS} keystrokes - the text "
            f"is on the clipboard, so Ctrl-V puts it in"
        )
        _release()
        return False

    if submit:
        # After the paste and never instead of it. Every refusal above has already run,
        # so an Enter can only be sent into a window that took the text — a stray one
        # would run whatever was already sitting on a shell prompt.
        #
        # This is the only place Flow presses Enter, and it does so *because it was
        # asked to*, which is what keeps P7 intact rather than breaking it: the payload
        # still lost its trailing newline above, so there is exactly one submit and the
        # user is the one who called for it. Under bracketed paste the block stays inert
        # until this keystroke, which is deliberate execution done deliberately.
        #
        # Asked again, because those refusals ran before a clipboard write and a
        # `SendInput` round trip. A window arriving inside that gap would receive a bare
        # Enter with nothing pasted under it, which is the same defect the count above
        # catches reached by a different road.
        again = resolve(hwnd)
        if again.is_flow:
            _warn("pasted, but not submitted: Flow took the focus back")
        elif again.stale:
            _warn(
                "pasted, but not submitted: the window changed after the paste"
                + (f" - {again.process} has the focus now" if again.process else "")
            )
        else:
            entered = _send(_key(VK_RETURN), _key(VK_RETURN, up=True))
            if entered != SUBMIT_KEYS:
                # A different failure from the one above and reported as one: the text is
                # in the window, so the Send worked and only the submit is missing. Saying
                # "not pasted" here would send the user looking for text that is already
                # in front of them.
                _warn(
                    f"pasted, but Enter did not go in ({entered} of {SUBMIT_KEYS}) - "
                    f"press it yourself"
                )

    if previous is not None:
        _schedule_restore(stamp)
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
        self, window_class: str = "", process: str = "", is_flow: bool = False,
        stale: bool = False,
    ) -> None:
        self.window_class = window_class
        self.process = process
        #: This window belongs to Flow. Decided by process id rather than by name,
        #: because Flow is a `python.exe` like any other and the target might be too.
        self.is_flow = is_flow
        #: The caller named a window and a different one holds the foreground now, so
        #: this describes who would actually receive the keystroke rather than who was
        #: aimed at. Like `is_flow`, a refusal rather than a target.
        self.stale = stale

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
                + (", flow" if self.is_flow else "")
                + (", stale" if self.stale else "") + ")")


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

    The **caller's window** is what gets classified, and that is the fix rather than a
    nicety. `GetForegroundWindow()` at paste time is a question asked after the click
    that started the Send, and for the whole life of this app the answer was Flow's own
    window — so `prepare()` classified a Tk canvas, decided it was not a terminal, and
    skipped the newline strip that is P7's one guarantee. The caller polls the same
    question 30 ms earlier and keeps the last answer that was not Flow.

    But it is a claim to check, not an answer to trust. Flow was the only foreground
    this refused for; anything else that took focus in those 30 ms — a notification, a
    switcher, an installer finishing — got the keystroke, prepared for a window it was
    never going to reach. So a live foreground that is neither Flow nor the window the
    caller named is the third refusal. A foreground of `0` is not: that is the OS
    declining to say, and refusing on the absence of evidence would break the hotkey
    path for no gain.
    """
    live_hwnd = foreground_hwnd()
    live = classify(live_hwnd)
    if live.is_flow or not hwnd:
        return live
    if live_hwnd and live_hwnd != hwnd:
        return Target(live.window_class, live.process, stale=True)
    return classify(hwnd)


def runs_on_arrival(payload: str, target: Target) -> bool:
    """True when pasting `payload` into `target` executes something as it lands.

    A terminal with bracketed paste hands the whole block to the shell as literal text;
    one without runs each line the moment it arrives. So an interior newline aimed at a
    bare terminal is not a risk of execution, it *is* execution, and it happens during
    the `SendInput` rather than after it.

    One predicate, asked by both `prepare` — which describes the hazard for the probe
    scripts that print it — and `paste`, which refuses on it. Two copies of this rule
    would drift the day a terminal joins `BRACKETED_PASTE`, leaving one half of the pair
    still acting on the old answer.
    """
    return target.is_terminal and not target.brackets_paste and "\n" in payload


def prepare(text: str, target: Target) -> tuple[str, str]:
    """(payload, warning) for pasting `text` into `target`.

    Two rules, and both are now guarantees — the second one was not, and that is what
    changed on 2026-08-03:

    **Never submit for the user.** A draft ending in a newline pastes as text plus
    Enter, which in a shell runs it. The trailing newline is always stripped for a
    terminal; the user presses Enter when they mean to.

    **Never let a bare terminal execute interior lines on arrival.** This used to say
    "report it instead of pretending", and reporting is what it did: the warning goes
    into `take_warnings()` and reaches the bubble on the pill's next frame, by which time
    the shell has run the first line. `paste` refuses on `runs_on_arrival` now; this
    function still returns the sentence, because that sentence is the reason, and the two
    probe scripts print it without pasting anything.

    Flow still does not rewrite the text to make it safe. Adding bracket markers to the
    clipboard would be doubly wrong — the terminal adds its own — and stripping interior
    newlines would be Flow editing a draft to fit a window.
    """
    if not target.is_terminal:
        return text, ""
    payload = text.rstrip("\r\n")
    if runs_on_arrival(payload, target):
        return payload, (
            f"{target.process or 'this terminal'} runs each line as it arrives - "
            "paste is not bracketed here"
        )
    return payload, ""
