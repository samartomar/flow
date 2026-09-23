"""Open Flow Home as a window of its own, and bring an open one forward.

On Windows that window is Microsoft Edge in app mode: `--app=<url>` draws the page with
no tabs, no address bar and no browser chrome, and Edge ships with Windows 11 — so Flow
gets a real application window without a single new Python dependency (decisions.md
2026-09-22, "Flow Home"). Its own `--user-data-dir` under `~/.flow/home` keeps it apart
from the person's browsing: no extensions, no history mixed into theirs, no sign-in.

Everywhere else — Lite on a Mac or Linux, or a Windows without Edge — the page opens in
the default browser, which is the same page in a tab.
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

#: Where Edge keeps this window's profile. Flow's own folder, so deleting `~/.flow`
#: removes it with everything else Flow wrote.
PROFILE_DIR = Path.home() / ".flow" / "home"

#: The page's `<title>`, which is what Edge puts on the window — and so what `focus`
#: looks for.
TITLE = "Flow"

#: The first size the window opens at. Edge remembers where somebody moved it.
SIZE = (1200, 800)


def _edge_candidates() -> list[str]:
    """Where Edge lives, most authoritative first: the registry's App Paths, then the
    two install folders every current Edge uses."""
    found: list[str] = []
    if sys.platform == "win32":
        try:
            import winreg

            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                                              r"\App Paths\msedge.exe") as key:
                        value, _ = winreg.QueryValueEx(key, "")
                        if value:
                            found.append(value)
                except OSError:
                    continue
        except ImportError:
            pass
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                found.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    return found


def find_edge() -> str | None:
    """The path to msedge.exe, or None when this is not Windows or Edge is not there."""
    for path in _edge_candidates():
        if path and Path(path).is_file():
            return path
    return None


def edge_args(edge: str, url: str) -> list[str]:
    """The command line that opens `url` as an app window. Its own function so the flags
    can be read — and tested — without starting a browser."""
    width, height = SIZE
    return [
        edge,
        f"--app={url}",
        f"--user-data-dir={PROFILE_DIR}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
    ]


def launch(url: str) -> bool:
    """Open `url` as a Flow Home window. True when something was started."""
    edge = find_edge()
    if edge is not None:
        try:
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            flags = 0
            if sys.platform == "win32":
                # Edge must outlive a console Flow was started from, and must not
                # inherit it: its own process group, and no console window of its own.
                flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                         | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            subprocess.Popen(edge_args(edge, url), close_fds=True, creationflags=flags,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def focus() -> bool:
    """Bring an open Flow Home window to the front. True if one was found.

    Windows only: a top-level window of Chromium's class with exactly the page's title.
    Restored first if it was minimised. Windows may still refuse the foreground to a
    process the user did not just click — the window then flashes in the taskbar, which
    is the OS's own answer to "somebody wants your attention".
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        title = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, title, 128)
        if title.value == TITLE:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(proc(visit), 0)
    if not found:
        return False
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True
