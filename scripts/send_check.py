"""Does a pressed Send actually reach the window it was aimed at?

Every other harness in this repo can be green while Send does nothing at all, and for
the whole life of the project it was: neither toplevel carried `WS_EX_NOACTIVATE`, so
clicking the chip made Flow the foreground window and the target lost it — and
`inject.paste()` then asked the OS what had focus *after* the theft. The Ctrl-V went to
a Tk canvas that ignores it, `prepare()` classified Flow's own window instead of the
terminal, and `paste()` returned True regardless. Nothing on screen said otherwise.

So this measures the three things no unit test can see:

  (default)  read `WS_EX_NOACTIVATE` back off both toplevels. A `SetWindowLongPtr` that
             silently did nothing looks exactly like one that worked, and this is a call
             that can fail and still return a plausible value.

  --live     open a real window and a real console, click Send **with the mouse** at the
             coordinates the chip is drawn at, and read back what arrived in each. This
             moves the pointer and opens two windows, which is why it is behind a flag —
             `inject_check.py` next door keeps the same discipline.

The ordinary-window leg is a plain Win32 edit control this script opens itself, and not
Notepad, which is the obvious choice and the wrong one: Windows 11 ships Notepad as a
single-instance tabbed app, so a probe that opened one and then closed it would be
operating windows in the same process as whatever the person running it already had open
and unsaved. The measurement does not need Notepad; it needs a window in another process
that takes Ctrl-V, and this is one, readable in a single message.

The console leg measures P7 as well as the paste. The draft ends in a newline, so if the
newline survived, the command runs the instant it lands. The check is that the marker
file is absent until this script presses Enter itself, and present afterwards.

    uv run python scripts/send_check.py
    uv run python scripts/send_check.py --live
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.inject import paste, take_warnings  # noqa: E402
from flow.session import Session  # noqa: E402
from flow.ui import (  # noqa: E402
    PILL_H,
    WS_EX_NOACTIVATE,
    Pill,
    toplevel_hwnd,
)

#: This probe's own handle. `ctypes.WinDLL` hands back a fresh object, and that matters:
#: the first version of this file imported `inject.user32` and redeclared `SendInput` on
#: it to describe a mouse event — which changed the signature under `inject.paste()` and
#: broke the very call being measured. A probe that modifies what it measures measures
#: nothing.
_u = ctypes.WinDLL("user32", use_last_error=True)
_k = ctypes.WinDLL("kernel32", use_last_error=True)

GWL_EXSTYLE = -20
_get_long = getattr(_u, "GetWindowLongPtrW", None) or _u.GetWindowLongW
_get_long.argtypes = [wintypes.HWND, ctypes.c_int]
_get_long.restype = ctypes.c_ssize_t

_u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_u.GetForegroundWindow.restype = wintypes.HWND
_u.SetForegroundWindow.argtypes = [wintypes.HWND]
_u.BringWindowToTop.argtypes = [wintypes.HWND]
_u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_u.IsWindowVisible.argtypes = [wintypes.HWND]
_u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
_u.GetWindowThreadProcessId.restype = wintypes.DWORD
_u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_u.SendMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p
]
_u.SendMessageW.restype = ctypes.c_ssize_t
_k.GetCurrentThreadId.restype = wintypes.DWORD

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL, VK_A, VK_C, VK_RETURN, VK_ESCAPE = 0x11, 0x41, 0x43, 0x0D, 0x1B
WM_GETTEXT, WM_CLOSE = 0x000D, 0x0010

#: Unique enough to find by title, and obviously ours if one is ever left behind.
#:
#: By title and not by process id, which is the obvious way and does not work here: the
#: venv's `python.exe` is a trampoline, so `Popen.pid` is not the process that ends up
#: owning the window — and a console window belongs to its host rather than to the
#: `cmd.exe` inside it. Titles are what both of these can actually be found by.
EDIT_TITLE = "flow-send-check target window"
CONSOLE_TITLE = "flow-send-check console"

BENCH = Path(__file__).resolve().parent.parent / ".bench"


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _U(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


_u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]


def _emit(*items: _INPUT) -> None:
    arr = (_INPUT * len(items))(*items)
    _u.SendInput(len(items), arr, ctypes.sizeof(_INPUT))


def _mouse(flags: int) -> _INPUT:
    return _INPUT(type=INPUT_MOUSE, u=_U(mi=_MOUSEINPUT(dwFlags=flags)))


def _key(vk: int, up: bool = False) -> _INPUT:
    return _INPUT(
        type=INPUT_KEYBOARD,
        u=_U(ki=_KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP if up else 0)),
    )


def chord(*vks: int) -> None:
    """Press keys in order and release them in reverse — `chord(VK_CONTROL, VK_A)`."""
    _emit(*[_key(v) for v in vks], *[_key(v, up=True) for v in reversed(vks)])


def click_at(x: int, y: int) -> None:
    """A real mouse click at a screen position — the thing that steals the foreground.

    `event_generate` cannot measure this. It hands Tk an event directly and Windows is
    never involved, so the focus change the whole defect is made of never happens.
    """
    _u.SetCursorPos(x, y)
    time.sleep(0.12)  # let the move land before the button goes down
    _emit(_mouse(MOUSEEVENTF_LEFTDOWN))
    time.sleep(0.05)
    _emit(_mouse(MOUSEEVENTF_LEFTUP))


def right_click_at(x: int, y: int) -> None:
    _u.SetCursorPos(x, y)
    time.sleep(0.12)
    _emit(_mouse(MOUSEEVENTF_RIGHTDOWN))
    time.sleep(0.05)
    _emit(_mouse(MOUSEEVENTF_RIGHTUP))


def drag(x1: int, y1: int, x2: int, y2: int, pump=None) -> None:
    """Press, move in steps, settle on the destination, release.

    In steps because one jump is one `WM_MOUSEMOVE`, and a drag Tk never sees moving is
    not a drag. The settle at the end is what makes it measurable: intermediate moves
    can be coalesced or dropped, but the last position is the one the window must end
    up agreeing with.
    """
    _u.SetCursorPos(x1, y1)
    time.sleep(0.1)
    _emit(_mouse(MOUSEEVENTF_LEFTDOWN))
    time.sleep(0.05)
    for i in range(1, 9):
        _u.SetCursorPos(x1 + (x2 - x1) * i // 8, y1 + (y2 - y1) * i // 8)
        time.sleep(0.04)
        if pump is not None:
            pump()
    deadline = time.perf_counter() + 0.5
    while time.perf_counter() < deadline:
        _u.SetCursorPos(x2, y2)
        if pump is not None:
            pump()
        time.sleep(0.03)
    _emit(_mouse(MOUSEEVENTF_LEFTUP))
    time.sleep(0.1)
    if pump is not None:
        pump()


def own_windows() -> set[int]:
    """Every top-level window this process owns. The right-click menu is one of them."""
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    mine: set[int] = set()
    me = _k.GetCurrentProcessId()

    def visit(hwnd, _lp):
        owner = wintypes.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == me and _u.IsWindowVisible(hwnd):
            mine.add(hwnd)
        return True

    _u.EnumWindows(proc(visit), 0)
    return mine


def exstyle(hwnd: int) -> int:
    return _get_long(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def window_titled(title: str, timeout: float = 10.0) -> int:
    """The first visible top-level window whose title contains `title`.

    By title rather than by process id, which is what the first version did and what
    does not work: Windows 11 hands `notepad.exe` to a running instance, and a console
    window belongs to its *host* — Windows Terminal here — not to the `cmd.exe` inside.
    """
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        found: list[int] = []

        def visit(hwnd, _lp):
            if _u.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(512)
                _u.GetWindowTextW(hwnd, buf, 512)
                if title in buf.value:
                    found.append(hwnd)
                    return False
            return True

        _u.EnumWindows(proc(visit), 0)
        if found:
            return found[0]
        time.sleep(0.2)
    return 0


def _wait_front(hwnd: int, pill: Pill | None, seconds: float) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if pill is not None:
            pill.update()
        if _u.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def bring_to_front(hwnd: int, pill: Pill | None = None) -> bool:
    """Put `hwnd` in front, pumping Tk while it happens.

    The pump is the point: `Pill._tick` is what records the last non-Flow foreground
    window, and a target that was never in front while the pill was running is a target
    the pill was never told about.

    Windows refuses `SetForegroundWindow` from a process that is not already in front,
    which is a real restriction and not one worth fighting in the product — a person
    puts a window in front by clicking it. A probe has to do it without a person, so it
    borrows the foreground thread's input queue, which is the documented way.
    """
    _u.ShowWindow(hwnd, 5)  # SW_SHOW
    _u.SetForegroundWindow(hwnd)
    if _wait_front(hwnd, pill, 1.0):
        return True
    mine = _k.GetCurrentThreadId()
    front = _u.GetWindowThreadProcessId(_u.GetForegroundWindow(), None)
    _u.AttachThreadInput(mine, front, True)
    try:
        _u.BringWindowToTop(hwnd)
        _u.SetForegroundWindow(hwnd)
    finally:
        _u.AttachThreadInput(mine, front, False)
    return _wait_front(hwnd, pill, 3.0)


def _kill_tree(pid: int) -> None:
    """Kill a process *and its children*, by id.

    `Popen.terminate()` is not enough for either of these: the venv's `python.exe` is a
    trampoline whose real interpreter is a child, and killing a `cmd.exe` by image name
    is out of the question when the console it lives in may be the same terminal the
    person running this is reading. By pid, with the tree, is the narrow way.
    """
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def edit_text(hwnd: int) -> str:
    """Read an edit control's contents, across the process boundary.

    `GetWindowTextW` is documented to return only the *caption* for a window owned by
    another process. `WM_GETTEXT` is one of the messages the system marshals, so it
    genuinely crosses.
    """
    buf = ctypes.create_unicode_buffer(4096)
    _u.SendMessageW(hwnd, WM_GETTEXT, 4096, ctypes.cast(buf, ctypes.c_void_p))
    return buf.value


# -- the window under test ---------------------------------------------------

def run_target_window() -> None:
    """`--target`: a plain top-level Win32 edit control, and a message loop.

    Re-launches this same file rather than shipping a second script, and lives in
    another process because that is the whole point — a target in *this* process is one
    Flow is now required to refuse.
    """
    WS_OVERLAPPEDWINDOW, WS_VISIBLE = 0x00CF0000, 0x10000000
    ES_MULTILINE, ES_AUTOVSCROLL, ES_WANTRETURN = 0x0004, 0x0040, 0x1000
    _u.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _u.CreateWindowExW.restype = wintypes.HWND
    _u.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    _u.GetMessageW.restype = ctypes.c_int

    # The caption of a top-level EDIT *is* its contents, so the window starts out
    # holding its own title. That is not a problem as long as the reader remembers it:
    # the check compares against what was in there before the click, not against empty.
    hwnd = _u.CreateWindowExW(
        0, "EDIT", EDIT_TITLE,
        WS_OVERLAPPEDWINDOW | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN,
        80, 80, 620, 260, None, None, None, None,
    )
    if not hwnd:
        raise SystemExit(f"CreateWindowExW failed: {ctypes.get_last_error()}")
    _u.SetForegroundWindow(hwnd)
    _u.SetFocus(hwnd)
    msg = wintypes.MSG()
    while _u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        _u.TranslateMessage(ctypes.byref(msg))
        _u.DispatchMessageW(ctypes.byref(msg))


# -- the fixture -------------------------------------------------------------

class _Dead:
    level_db = -70.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list:
        return []


class _NoAsr:
    def load(self, final=None) -> None: ...

    def text(self, a, *, final=False, hotwords="") -> str:
        return ""


class Fixture:
    """A pill over a dead session, with a seeded draft and a real Send wired up."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.refusals: list[str] = []
        self.pill = Pill(Session(asr=_NoAsr(), mic=_Dead(), profile=None),
                         on_send=self._on_send, hotkeys=None)

    def _on_send(self, text: str, target: int | None = None) -> str:
        # Takes the target as an optional second argument on purpose: before the fix the
        # pill called this with the text alone and there was no target to hand over, so
        # one script measures both sides of the change.
        ok = paste(text, hwnd=target) if target else paste(text)
        self.warnings.extend(take_warnings())
        if not ok:
            self.refusals.append("paste refused")
        return "" if ok else "could not paste"

    def arm(self, draft: str) -> None:
        self.pill.session.draft.set(draft)
        self.pill.bubble.show(draft)
        self.pill.update()

    def click_send(self) -> None:
        canvas = self.pill.bubble.canvas
        x1, y1, x2, y2 = canvas.bbox("chip-Send")
        _, _, pos = self.pill.bubble.geometry().partition("+")
        bx, _, by = pos.partition("+")
        click_at(int(bx) + (x1 + x2) // 2, int(by) + (y1 + y2) // 2)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            self.pill.update()
            time.sleep(0.02)

    def close(self) -> None:
        self.pill.destroy()


# -- the legs ----------------------------------------------------------------

def check_styles(fixture: Fixture, report) -> None:
    """Read the extended styles back off both toplevels."""
    pill = fixture.pill
    # Read *after* a float-up has run to the end, not before. Tk sets -alpha by way of
    # the extended style word on every step of that animation, so a style applied at
    # startup and clobbered on first show would look perfect to a check made too early.
    pill.bubble.show("measuring")
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        pill.update()
        time.sleep(0.02)
    for name, win in (("pill", pill), ("bubble", pill.bubble)):
        bits = exstyle(toplevel_hwnd(win))
        report(f"{name}: WS_EX_NOACTIVATE is set", bool(bits & WS_EX_NOACTIVATE),
               f"exstyle {bits:#010x}")
    report("the pill agrees the call took", getattr(pill, "no_activate", False),
           f"pill.no_activate={getattr(pill, 'no_activate', None)}")


def check_window(fixture: Fixture, report) -> None:
    """Click Send with the mouse into an ordinary window in another process."""
    marker = "flow-send-check-window-marker"
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--target"])
    try:
        hwnd = window_titled(EDIT_TITLE)
        report("the target window opened", bool(hwnd), f"hwnd {hwnd:#x}")
        if not hwnd:
            return
        before = edit_text(hwnd)
        fixture.arm(marker)
        report("the target is in front before the click",
               bring_to_front(hwnd, fixture.pill), "")
        target = getattr(fixture.pill, "paste_target", None)
        report("Flow is aimed at the window, not at itself",
               bool(target) and target == hwnd,
               f"tracked {None if target is None else hex(target)}, "
               f"target window {hwnd:#x}")

        fixture.click_send()
        time.sleep(1.0)  # the clipboard-restore thread runs 0.6 s after the paste
        got = edit_text(hwnd)
        report("the words arrived in the window", marker in got,
               repr(got[:60]) if got != before else "unchanged - nothing arrived")
        report("Send did not refuse", not fixture.refusals, str(fixture.refusals))
    finally:
        _kill_tree(proc.pid)


def check_pill(fixture: Fixture, report) -> None:
    """What a window that refuses the focus costs: the menu, and dragging.

    Both are things `WS_EX_NOACTIVATE` could plausibly have broken, so both are measured
    rather than reasoned about. The menu is the awkward one: a popup menu runs a modal
    message loop *inside this process*, so the thread that opens it cannot also be the
    thread that watches it or the one that closes it. Hence a watcher and a timer.
    """
    pill = fixture.pill
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--target"])
    try:
        target = window_titled(EDIT_TITLE)
        if not target or not bring_to_front(target, pill):
            report("a window to lose the focus to", False, "could not stage the target")
            return

        baseline = own_windows()
        seen: dict[str, object] = {"menu": 0, "held": False}
        # Resolved here and passed in as an integer: `toplevel_hwnd` calls `winfo_id`,
        # and Tk is touched from one thread. The watcher is not that thread.
        pill_hwnd = toplevel_hwnd(pill)

        def watch() -> None:
            end = time.perf_counter() + 2.5
            while time.perf_counter() < end:
                seen["menu"] = max(seen["menu"], len(own_windows() - baseline))
                if _u.GetForegroundWindow() == pill_hwnd:
                    seen["held"] = True
                time.sleep(0.05)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        threading.Timer(1.2, lambda: chord(VK_ESCAPE)).start()
        # `pill.pill_w`, not the idle `PILL_W`: by the time this runs, the earlier
        # checks have left a draft on screen, and a pill with something to dock to is
        # wider than one alone (Phase 5) — the old fixed-width centre point landed
        # outside a docked pill entirely.
        right_click_at(pill.x + pill.pill_w // 2, pill.y + PILL_H // 2)
        end = time.perf_counter() + 3.0
        while time.perf_counter() < end:
            pill.update()
            time.sleep(0.02)
        watcher.join(1.0)

        report("the right-click menu opens and dismisses", seen["menu"] >= 1,
               f"{seen['menu']} window(s) appeared, and the pump came back")
        report("it holds the foreground while it is up", seen["held"],
               "which is what a native popup menu needs to receive input at all")
        report("and gives it straight back", _u.GetForegroundWindow() == target,
               f"foreground {_u.GetForegroundWindow():#x}, target {target:#x}")
        report("with nothing left on screen", not (own_windows() - baseline),
               f"{len(own_windows() - baseline)} left behind")

        # Dragging is the other thing a non-activating window could have lost, and the
        # pill is a window whose only handle is dragging it. Checked against where the
        # mouse ended up, not against a distance: the pill has to *track* the cursor.
        was = (pill.x, pill.y)
        cx = pill.x + pill.pill_w // 2
        drag(cx, pill.y + PILL_H // 2, cx - 90, pill.y + PILL_H // 2 - 40,
             pump=pill.update)
        report("the pill still drags", abs(pill.x - (was[0] - 90)) <= 2
               and abs(pill.y - (was[1] - 40)) <= 2,
               f"{was} -> {(pill.x, pill.y)}, wanted {(was[0] - 90, was[1] - 40)}")
        report("and dragging it did not take the focus",
               _u.GetForegroundWindow() == target,
               f"foreground {_u.GetForegroundWindow():#x}, target {target:#x}")
    finally:
        _kill_tree(proc.pid)


def check_console(fixture: Fixture, report) -> None:
    """Click Send with the mouse into a real console, and check P7 on the way.

    The draft is a command with a trailing newline. If the newline survived, the command
    runs on arrival; the guarantee is that nothing runs until a person presses Enter.
    """
    BENCH.mkdir(parents=True, exist_ok=True)
    landed = BENCH / "send-check-console.txt"
    landed.unlink(missing_ok=True)
    # Terminated by pid at the end, never taskkill'd by image name: the console window
    # belongs to the host, and on this machine the host is the same Windows Terminal the
    # person running this is reading the output in.
    proc = subprocess.Popen(["cmd.exe", "/K", f"title {CONSOLE_TITLE}"],
                            creationflags=subprocess.CREATE_NEW_CONSOLE)
    try:
        hwnd = window_titled(CONSOLE_TITLE)
        report("a console opened", bool(hwnd), f"hwnd {hwnd:#x}")
        if not hwnd:
            return
        fixture.arm(f'echo landed>"{landed}"\n')
        report("the console is in front before the click",
               bring_to_front(hwnd, fixture.pill), "")
        fixture.click_send()
        time.sleep(1.0)

        report("P7 held: nothing ran on arrival", not landed.exists(),
               "the trailing newline was stripped" if not landed.exists()
               else "THE COMMAND RAN BY ITSELF")

        bring_to_front(hwnd)
        time.sleep(0.3)
        chord(VK_RETURN)  # the person presses Enter; Flow never does
        time.sleep(1.0)
        report("the words arrived in the console", landed.exists(),
               "the pasted command ran once Enter was pressed" if landed.exists()
               else "there was nothing there to run")
    finally:
        _kill_tree(proc.pid)


def main() -> None:
    if "--target" in sys.argv:
        run_target_window()
        return

    live = "--live" in sys.argv
    results: list[tuple[bool, str, str]] = []

    def report(what: str, ok: bool, detail: str = "") -> None:
        results.append((ok, what, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {what}", flush=True)
        if detail:
            print(f"        {detail}", flush=True)

    # One pill for the whole run, and one Tk root with it. Two roots in one interpreter
    # end in "Tcl_AsyncDelete: async handler deleted by the wrong thread" — the same
    # property of the harness that makes `selfdrive.py` run its Tk scenarios isolated.
    # It is also the more faithful arrangement: one app, several targets.
    fixture = Fixture()
    cursor = wintypes.POINT()
    _u.GetCursorPos(ctypes.byref(cursor))
    try:
        print("== styles", flush=True)
        check_styles(fixture, report)

        if live:
            print("\n== an ordinary window (the mouse will move)", flush=True)
            check_window(fixture, report)
            print("\n== a console (the mouse will move)", flush=True)
            check_console(fixture, report)
            print("\n== the pill itself (the mouse will move)", flush=True)
            check_pill(fixture, report)
        else:
            print("\n(styles only - pass --live to click Send into a real window "
                  "and a real console)", flush=True)
    finally:
        _u.SetCursorPos(cursor.x, cursor.y)
        fixture.close()

    bad = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed", flush=True)
    for _, what, detail in bad:
        print(f"  FAILED  {what}\n          {detail}", flush=True)
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
