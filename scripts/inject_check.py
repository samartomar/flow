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
