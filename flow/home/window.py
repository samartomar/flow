"""Open Flow Home as a window of its own, and bring an open one forward.

On Windows that window is Microsoft Edge in app mode: `--app=<url>` draws the page with
no tabs, no address bar and no browser chrome, and Edge ships with Windows 11 — so Flow
gets a real application window without a single new Python dependency (decisions.md
2026-09-22, "Flow Home"). Its own `--user-data-dir` under `~/.flow/home` keeps it apart
from the person's browsing: no extensions, no history mixed into theirs, no sign-in.

Without Edge, the same isolated window comes from another Chromium browser — Chrome, then
Brave, then Chromium — found where each installs itself on Windows, macOS and Linux. Only
when none is there does the page open in the default browser, and that is said rather
than done quietly: the address carries Home's token in its fragment, and the extensions of
somebody's everyday browser can read every page it opens (decisions.md 2026-11-08).
"""

from __future__ import annotations

import os
import shutil
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

#: What `launch` says it did. Truthy both, so a caller asking "did a window open?" still
#: gets a yes for either; `SHARED` is the one that has to be said out loud.
ISOLATED = "window"
SHARED = "browser"

#: What the person is told when only `SHARED` was possible. The pill shows it.
SHARED_NOTICE = ("Flow Home opened in your default browser - its extensions can see the "
                 "page. Install Edge or Chrome to keep it in a window of its own.")

#: The other Chromium browsers, after Edge, by the name their profile folder takes and
#: where each puts itself. Chromium because `--app`, `--user-data-dir` and
#: `--disable-extensions` are Chromium's flags; Firefox has no equivalent of the first.
_WINDOWS = {  # (App Paths name, path under %ProgramFiles%, (x86) and %LOCALAPPDATA%)
    "chrome": ("chrome.exe", r"Google\Chrome\Application\chrome.exe"),
    "brave": ("brave.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe"),
    "chromium": (None, r"Chromium\Application\chrome.exe"),
}
_MACOS = {
    "edge": "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "chrome": "Google Chrome.app/Contents/MacOS/Google Chrome",
    "brave": "Brave Browser.app/Contents/MacOS/Brave Browser",
    "chromium": "Chromium.app/Contents/MacOS/Chromium",
}
_LINUX = {
    "edge": ("microsoft-edge", "microsoft-edge-stable"),
    "chrome": ("google-chrome", "google-chrome-stable"),
    "brave": ("brave-browser", "brave"),
    "chromium": ("chromium", "chromium-browser"),
}


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


def _app_path(exe: str) -> str | None:
    """What the registry's App Paths says `exe` is, or None."""
    try:
        import winreg
    except ImportError:
        return None
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                                      "\\App Paths\\" + exe) as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value:
                    return value
        except OSError:
            continue
    return None


def _other_candidates() -> list[tuple[str, str]]:
    """Every other Chromium browser's likely path, as (name, path), in preference order:
    Edge where the platform has it outside Windows, then Chrome, Brave, Chromium."""
    found: list[tuple[str, str]] = []
    if sys.platform == "win32":
        bases = [b for b in (os.environ.get("ProgramFiles"),
                             os.environ.get("ProgramFiles(x86)"),
                             os.environ.get("LOCALAPPDATA")) if b]
        for name, (exe, rel) in _WINDOWS.items():
            if exe and (registered := _app_path(exe)):
                found.append((name, registered))
            found += [(name, str(Path(base) / rel)) for base in bases]
    elif sys.platform == "darwin":
        for name, rel in _MACOS.items():
            for apps in (Path("/Applications"), Path.home() / "Applications"):
                found.append((name, str(apps / rel)))
    else:
        for name, commands in _LINUX.items():
            found += [(name, path) for c in commands if (path := shutil.which(c))]
    return found


def find_browser() -> tuple[str, str] | None:
    """A Chromium browser to open Home's isolated window with, as (name, path): Edge
    first, then the others in `_other_candidates`' order. None when there is none."""
    edge = find_edge()
    if edge is not None:
        return "edge", edge
    for name, path in _other_candidates():
        if path and Path(path).is_file():
            return name, path
    return None


def profile_dir(name: str) -> Path:
    """Each browser's own profile folder. Edge keeps the one it always had; the others
    get a sibling, because one browser's profile is not another's to open."""
    return PROFILE_DIR if name == "edge" else PROFILE_DIR.with_name(f"home-{name}")


def edge_args(edge: str, url: str, profile: Path | None = None) -> list[str]:
    """The command line that opens `url` as an app window, for Edge or any Chromium
    browser. Its own function so the flags can be read — and tested — without starting
    a browser. The profile and `--disable-extensions` are the isolation: nothing the
    person installed into their own browser runs beside Home's token."""
    width, height = SIZE
    return [
        edge,
        f"--app={url}",
        f"--user-data-dir={profile or PROFILE_DIR}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
    ]


def launch(url: str) -> str:
    """Open `url` as a Flow Home window: `ISOLATED` when a Chromium browser was started
    with Home's own profile, `SHARED` when only the default browser could take it, and
    "" when nothing opened at all."""
    browser = find_browser()
    if browser is not None:
        name, path = browser
        profile = profile_dir(name)
        try:
            profile.mkdir(parents=True, exist_ok=True)
            flags = 0
            if sys.platform == "win32":
                # Edge must outlive a console Flow was started from, and must not
                # inherit it: its own process group, and no console window of its own.
                flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                         | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            subprocess.Popen(edge_args(path, url, profile), close_fds=True,
                             creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ISOLATED
        except OSError:
            pass
    # The last resort, and a weaker one: the person's own browser, extensions and all.
    # Kept because a Home that cannot open is worse, but the caller says it happened.
    try:
        return SHARED if webbrowser.open(url) else ""
    except Exception:
        return ""


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
