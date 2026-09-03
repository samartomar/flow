"""Photograph the compact pill in every state it can draw, against a fake session.

`shots.py` does this for the shipped design; this is the same discipline for the
second one. The real `CompactPill` drives against `shots.FakeSession` — no
microphone, no model, no CLI, no hotkeys — and each state the pill has a colour
for is captured as a PNG, so "it renders" is a set of pictures and not a claim:

  rest      disarmed: no ring, the mode's glyph, a flat meter
  hearing   armed + LISTENING: green ring, live bars
  waiting   armed + REFINING: blue ring
  error     a flash frame: red ring, whatever the state
  ask       CONVERSE: violet glyph under the green ring
  menu      the right-click, the only menu the design allows

The gestures (tap cycles, hold talks) are logic, pinned headless in
`tests/test_ui_compact.py`; what only pixels can prove is that the ring, the
tint and the meter land where `design/compact/Main.dc.html` says they do.

    uv run --with pillow python scripts/compact_shots.py
"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from PIL import ImageGrab  # noqa: E402

import flow.ui as ui  # noqa: E402
import shots  # noqa: E402  — the capture machinery and the fake session
from flow.session import CONVERSE, DICTATE, State  # noqa: E402
from flow.ui_compact import FLASH_FRAMES, CompactPill  # noqa: E402


def shot(pill, name: str, margin: int = 26) -> None:
    """`shots.shot` for a surface with one window: the compact pill has no
    bubble, card or help to walk, so the box is its own."""
    pill.lift()
    pill.update_idletasks()
    x, y = pill.winfo_rootx(), pill.winfo_rooty()
    shots._grab((x - margin, y - margin,
                 x + pill.winfo_width() + margin,
                 y + pill.winfo_height() + margin), name)


def main() -> None:
    sess = shots.FakeSession()
    pill = CompactPill(sess)

    back = tk.Toplevel(pill)
    back.overrideredirect(True)
    back.configure(bg="#23262b")
    back.geometry(f"{pill.winfo_screenwidth()}x{pill.winfo_screenheight()}+0+0")
    ui._no_activate(back)
    back.attributes("-topmost", True)
    back.update_idletasks()
    back.lower(pill)

    # Park the cursor inside the work area, as shots.py does and for its reason:
    # a pointer left over the pill — or over the taskbar — is a thing the capture
    # walk then photographs, or worse, a window the synthetic click reaches first.
    from ctypes import wintypes
    import ctypes
    user32 = ctypes.windll.user32
    home = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(home))
    sw, sh = pill.winfo_screenwidth(), pill.winfo_screenheight()
    user32.SetCursorPos(8, sh - 60)

    def state(st, mode=DICTATE, armed=True):
        def fn():
            sess.state, sess.mode = st, mode
            pill.armed = armed
        return fn

    def menu():
        pill.lift()
        pill.update_idletasks()
        x, y = pill.winfo_rootx(), pill.winfo_rooty()
        rect = (x, y, x + pill.winfo_width(), y + pill.winfo_height())
        done = threading.Event()
        k = shots._ratio(ImageGrab.grab(all_screens=True))
        threading.Thread(
            target=shots.menu_worker,
            args=(rect, (x + 40, y + pill.winfo_height() // 2),
                  ui.toplevel_hwnd(pill), k, ["06-compact-menu"], done),
            daemon=True).start()
        return done

    steps = [
        (900, state(State.IDLE, armed=False)),
        (600, lambda: shot(pill, "01-compact-rest")),
        (0, state(State.LISTENING)),
        (900, lambda: shot(pill, "02-compact-hearing")),
        (0, state(State.REFINING)),
        (600, lambda: shot(pill, "03-compact-waiting")),
        (0, lambda: setattr(pill, "_flash", FLASH_FRAMES)),
        (200, lambda: shot(pill, "04-compact-error")),
        (0, lambda: setattr(pill, "_flash", 0)),
        (0, state(State.LISTENING, mode=CONVERSE)),
        (600, lambda: shot(pill, "05-compact-ask")),
        (0, state(State.IDLE, armed=False)),
        (400, menu),
    ]

    def run(i=0):
        if i >= len(steps):
            user32.SetCursorPos(home.x, home.y)
            pill.after(300, pill.quit_app)
            return
        delay, fn = steps[i]

        def go():
            gate = None
            try:
                gate = fn()
            except Exception:
                import traceback
                traceback.print_exc()
            if isinstance(gate, threading.Event):
                end = time.time() + 60

                def poll():
                    if gate.is_set() or time.time() > end:
                        run(i + 1)
                    else:
                        pill.after(150, poll)
                poll()
            else:
                run(i + 1)

        pill.after(delay, go)

    pill.after(60_000, pill.quit_app)  # hard stop, whatever happens
    run()
    pill.mainloop()
    print(f"\n{len(shots._taken)} shots in {shots.OUT}")


if __name__ == "__main__":
    main()
