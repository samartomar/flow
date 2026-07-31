"""System-wide hotkeys via `RegisterHotKey` (stdlib ctypes).

tkinter can only see keystrokes when it has focus, and the whole point of a dictation
pill is that focus is somewhere else. `RegisterHotKey` needs a message loop on the
thread that registered, so registration lives on its own thread and presses are handed
back through a queue for the UI thread to drain — Tk must only ever be touched from the
thread that created it.

This is why no `keyboard`/`pynput` dependency is needed (R16).
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Declared for the same reason as in inject.py: an undeclared ctypes signature passes
# and returns 32-bit ints, which silently corrupts 64-bit WPARAM/LPARAM values.
user32.RegisterHotKey.argtypes = [
    wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

VK_SPACE, VK_RETURN, VK_ESCAPE = 0x20, 0x0D, 0x1B


_MOD_NAMES = ((MOD_CONTROL, "ctrl"), (MOD_ALT, "alt"), (MOD_SHIFT, "shift"), (MOD_WIN, "win"))
_VK_NAMES = {0x20: "space", 0x0D: "enter", 0x1B: "esc", 0xDC: "backslash", 0xBA: "semicolon"}


def describe(mods: int, vk: int) -> str:
    parts = [name for bit, name in _MOD_NAMES if mods & bit]
    parts.append(_VK_NAMES.get(vk, f"vk{vk:#x}"))
    return "+".join(parts)


class Hotkeys:
    """Registers combos and reports presses by name.

    Each action gets an ordered list of alternatives, because a combo can already be
    owned by another process — measured on this machine, where ctrl+alt+space was taken
    and would otherwise have been a dead shortcut with no explanation.
    """

    def __init__(self, bindings: dict[str, list[tuple[int, int]]]) -> None:
        self.bindings = bindings
        self.presses: queue.Queue[str] = queue.Queue()
        self.failed: list[str] = []
        #: action name -> the combo that actually registered, e.g. "ctrl+alt+space"
        self.chosen: dict[str, str] = {}
        self._ids: dict[int, str] = {}
        self._tid: int | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="hotkeys")

    def start(self, timeout: float = 2.0) -> bool:
        self._thread.start()
        return self._ready.wait(timeout)

    def stop(self) -> None:
        if self._tid is not None:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def drain(self) -> list[str]:
        out = []
        while True:
            try:
                out.append(self.presses.get_nowait())
            except queue.Empty:
                return out

    def _run(self) -> None:
        self._tid = kernel_thread_id()
        next_id = 1
        for name, alternatives in self.bindings.items():
            for mods, vk in alternatives:
                if user32.RegisterHotKey(None, next_id, mods | MOD_NOREPEAT, vk):
                    self._ids[next_id] = name
                    self.chosen[name] = describe(mods, vk)
                    next_id += 1
                    break
            else:
                # Every alternative is owned by another app. Report it rather than
                # leaving the user wondering why a shortcut silently does nothing.
                self.failed.append(name)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                name = self._ids.get(msg.wParam)
                if name:
                    self.presses.put(name)
        for i in self._ids:
            user32.UnregisterHotKey(None, i)


def kernel_thread_id() -> int:
    return kernel32.GetCurrentThreadId()


VK_BACKSLASH, VK_SEMICOLON = 0xDC, 0xBA
VK_M = 0x4D  # P9 mode toggle

#: Ordered alternatives per action. ctrl+alt+space is first because it is the most
#: natural, but it was already taken on the development machine, so toggle in
#: particular needs somewhere to fall back to.
DEFAULT_BINDINGS: dict[str, list[tuple[int, int]]] = {
    "toggle": [
        (MOD_CONTROL | MOD_ALT, VK_SPACE),
        (MOD_CONTROL | MOD_SHIFT, VK_SPACE),
        (MOD_CONTROL | MOD_ALT, VK_BACKSLASH),
        (MOD_WIN | MOD_ALT, VK_SPACE),
    ],
    "send": [
        (MOD_CONTROL | MOD_ALT, VK_RETURN),
        (MOD_CONTROL | MOD_SHIFT, VK_RETURN),
    ],
    "cancel": [
        (MOD_CONTROL | MOD_ALT, VK_ESCAPE),
        (MOD_CONTROL | MOD_SHIFT, VK_ESCAPE),
    ],
    # P9: dictate <-> converse. "One action" is the acceptance criterion, so it gets a
    # binding of its own rather than a menu item only.
    "mode": [
        (MOD_CONTROL | MOD_ALT, VK_M),
        (MOD_CONTROL | MOD_SHIFT, VK_M),
    ],
}
