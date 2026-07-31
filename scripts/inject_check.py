"""Smoke-check the clipboard and hotkey plumbing without side effects.

Deliberately does NOT call inject.paste(): that sends a real Ctrl-V into whatever
window currently has focus, which would type into the user's editor.

    uv run python scripts/inject_check.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.hotkey import DEFAULT_BINDINGS, Hotkeys  # noqa: E402
from flow.inject import get_clipboard_text, set_clipboard_text  # noqa: E402

MARKER = "flow-clipboard-roundtrip-check"


def main() -> None:
    original = get_clipboard_text()
    print(f"clipboard before: {(original or '')[:40]!r}")

    ok = set_clipboard_text(MARKER)
    got = get_clipboard_text()
    print(f"set={ok} readback={got!r} match={got == MARKER}")

    # Put the user's clipboard back exactly as it was.
    if original is not None:
        set_clipboard_text(original)
        print(f"restored: {get_clipboard_text() == original}")

    hk = Hotkeys(DEFAULT_BINDINGS)
    started = hk.start()
    print(f"hotkey thread started: {started}")
    for action, combo in hk.chosen.items():
        print(f"  {action:8s} -> {combo}")
    print(f"unavailable (every alternative taken): {hk.failed or 'none'}")
    hk.stop()


if __name__ == "__main__":
    main()


# -- P7: how the paste classifier reads the windows actually open ----------

def survey_targets() -> None:
    """Classify every visible top-level window on this machine.

    A classifier is only worth what it does on real windows, so this enumerates them
    rather than asserting against a table of names someone imagined.
    """
    import ctypes
    from ctypes import wintypes

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from flow.inject import Target, _process_name, prepare, user32

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int

    found: list[Target] = []

    def visit(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            found.append(Target(buf.value, _process_name(hwnd)))
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)

    terminals = [t for t in found if t.is_terminal]
    bracketed = [t for t in terminals if t.brackets_paste]
    print(f"\nvisible top-level windows: {len(found)}")
    print(f"  classified as a terminal: {len(terminals)}")
    print(f"  ...of which bracket paste: {len(bracketed)}")
    for t in terminals:
        payload, warning = prepare("one\ntwo\n", t)
        print(f"    {t.process:<24} {t.window_class:<34} "
              f"{'bracketed' if t.brackets_paste else 'WARNS'}"
              f"{'' if payload.endswith('two') else ' (newline kept?!)'}")
    others = sorted({t.process for t in found if not t.is_terminal})
    print(f"  non-terminals ({len(others)}): {', '.join(others[:12])}"
          + (" ..." if len(others) > 12 else ""))
