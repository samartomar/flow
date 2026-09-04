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
  ask panel the 400 px band on its foot: strip, heard, result, footer
  asking    the same, mid-ask: heard only, the ring wraps the foot
  closed    120 wide again immediately after the close, proving it returns
  refine    REFINE at rest: the gold glyph, no ring
  refine panel  the heard block grey, the result under its gold tag, Send
  palette   Switch workspace, mid-search: the query field, the top hit lit
  setup     Workbench setup: mic, CLI, where it pastes
  no-cli    States.dc.html 1: no agent CLI on PATH — grey, not red
  mic-gone  States.dc.html 2: slashed glyph, persistent red ring
  silence   States.dc.html 3: held, nothing said — straight back to grey
  refine-failed  States.dc.html 4: the raw dictation, the CLI's last line
  recover   States.dc.html 5: the workspace is gone — amber, once
  copied    States.dc.html 6: Lite — `copied — press Ctrl+V` under the pill
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

from flow import paint  # noqa: E402

# Before any window: awareness is fixed for the process the moment the
# first one exists, and these shots are the record of what the surface
# looks like on the machine taking them. Photographed unaware, every one
# of them was a third-size image the compositor had stretched.
paint.make_dpi_aware()

import flow.ui as ui  # noqa: E402
import flow.ui_compact as uc  # noqa: E402
import shots  # noqa: E402  — the capture machinery and the fake session
from flow.session import CONVERSE, DICTATE, REFINE, State  # noqa: E402
from flow.ui_compact import (  # noqa: E402
    COPIED_FRAMES, FLASH_FRAMES, RECOVER_FRAMES, CompactPill,
)


def shot(pill, name: str, margin: int = 26) -> None:
    """`shots.shot` for a surface with one window: the compact pill has no
    bubble, card or help to walk, so the box is its own."""
    pill.lift()
    pill.update_idletasks()
    x, y = pill.winfo_rootx(), pill.winfo_rooty()
    w, h = pill.winfo_width(), pill.winfo_height()
    if w <= 1 or h <= 1:
        # A window caught between two geometries reports 1x1, and a box built
        # from that crops to nothing — which aborted the whole walk on the
        # frame after a panel closed rather than costing it one picture.
        print(f"  ! {name} skipped: window is {w}x{h}", flush=True)
        return
    shots._grab((x - margin, y - margin,
                 x + w + margin, y + h + margin), name)


def box_shot(pill, name: str, margin: int = 26) -> None:
    """The standalone box (palette, setup), captured the same way."""
    box = pill._box
    box.lift()
    box.update_idletasks()
    x, y = box.winfo_rootx(), box.winfo_rooty()
    shots._grab((x - margin, y - margin,
                 x + box.winfo_width() + margin,
                 y + box.winfo_height() + margin), name)


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

    def ask_panel():
        # The answered Ask: heard final, result in, pill back at rest — the
        # state talk_end's disarm leaves it in.
        sess.state, sess.mode = State.IDLE, CONVERSE
        pill.armed = False
        pill._panel_mode = CONVERSE
        pill._panel_heard = "Where does the pill decide it was a hold and not a tap?"
        pill._panel_heard_final = True
        pill._panel_result = ("PILL_HOLD_SEC in flow/ui.py — 0.30 s, with a 4 px "
                              "drag slop beside it so a nudge while holding is "
                              "not read as a move.")
        pill._open_panel()

    def asking_panel():
        # Mid-ask: the question asked, the CLI still working — the ring says
        # so, and wraps the foot.
        sess.state = State.ASKING
        pill.armed = True
        pill._panel_heard = "…and keep it under twenty words this time"
        pill._panel_heard_final = True
        pill._panel_result = ""

    def refine_panel():
        # The answered Refine: the raw dictation in grey, the shaped text
        # under its gold tag, and the footer Ask does not have — Send.
        sess.state, sess.mode = State.IDLE, REFINE
        pill.armed = False
        pill._panel_mode = REFINE
        pill._panel_heard = ("make the pill not show any controls just the mic "
                             "and when i let go it should paste in the window "
                             "i was in before")
        pill._panel_heard_final = True
        pill._panel_result = ("Strip every control from the push-to-talk pill in "
                              "flow/ui.py — leave the mic glyph and the meter. "
                              "On release, inject the draft into the window "
                              "that held focus before the pill.")
        pill._open_panel()

    def loading(on):
        def fn():
            sess.asr.loading = on
            pill.armed = False
        return fn

    def mic_open():
        """Held, open, and hearing a silent room: `IDLE` with the ring lit."""
        def fn():
            sess.state, sess.capturing = State.IDLE, True
            pill.armed = True
        return fn

    def loading(on):
        def fn():
            sess.asr.loading = on
            pill.armed = False
        return fn

    def mic_open():
        """Held, open, and hearing a silent room: `IDLE` with the ring lit."""
        def fn():
            sess.state, sess.capturing = State.IDLE, True
            pill.armed = True
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

    def palette_open():
        # Mid-search: three recorded folders, "flo" typed, the top hit lit.
        sess.profile.workspaces = ["~/dev/products/flow",
                                   "~/dev/products/flow-lite-notes",
                                   "~/work/riverflow"]
        pill._open_palette()
        for ch in "flo":
            pill._palette.type(ch)
        pill._sync_box()

    def setup_open():
        # The three answers a real machine would have found — all native to
        # the fake now (shots.py's FakeSession carries them).
        pill._open_setup()

    def no_cli():
        # States.dc.html 1: Type still works, the other two are not offered —
        # and nothing about the resting pill says so but grey.
        sess._provider = lambda: ""
        sess.mode, sess.state = DICTATE, State.IDLE
        pill.armed = False

    def silence():
        # States.dc.html 3: held, nothing said — the band the hold raised
        # goes straight back down with no toast. FakeSession.talk_end answers
        # "nothing pending", which is what a silent hold is.
        sess.mode = CONVERSE
        pill._talk_start()
        pill._talk_end(send=True)

    def refine_failed():
        # States.dc.html 4: the panel holds the raw dictation, the CLI's own
        # last line is the message, and Send still works.
        sess.state, sess.mode = State.IDLE, REFINE
        pill.armed = False
        pill._panel_mode = REFINE
        pill._panel_heard = ("make the pill not show any controls just the mic "
                             "and when i let go it should paste in the window "
                             "i was in before")
        pill._panel_heard_final = True
        pill._panel_failed = True
        pill._panel_result = "refine failed (timed out after 20s) — draft unchanged"
        pill._open_panel()

    def recover():
        # States.dc.html 5: the workspace the profile remembers is gone —
        # amber, once. Type mode, as the artboard has it.
        sess.mode = DICTATE
        pill._recover = RECOVER_FRAMES

    def copied():
        # States.dc.html 6: Lite — the clipboard, and the line under the pill.
        # Its own clean shot: the amber notice from the case before is done.
        pill._recover = 0
        pill.on_send = None
        pill._copied = COPIED_FRAMES
        pill._sync_shell()

    def reset_fallbacks():
        pill._recover = 0
        pill._notice = 0
        pill._mic_gone = False
        sess.capturing = False
        sess.asr.loading = False
        pill._sync_shell()
        # `del`, not a fresh lambda: the no-CLI step shadowed the fake's own
        # method with an instance attribute, and the menu shot wants the fake.
        # Guarded, because the walk resets more than once now and the second
        # `del` of the same shadow is an AttributeError that ends the run.
        if "_provider" in vars(sess):
            del sess._provider

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
        (0, ask_panel),
        (700, lambda: shot(pill, "07-compact-ask-panel")),
        (0, asking_panel),
        (500, lambda: shot(pill, "08-compact-asking")),
        (0, lambda: pill._close_panel()),
        (500, lambda: shot(pill, "09-compact-closed")),
        (0, state(State.IDLE, mode=REFINE, armed=False)),
        (600, lambda: shot(pill, "10-compact-refine")),
        (0, refine_panel),
        (700, lambda: shot(pill, "11-compact-refine-panel")),
        (0, lambda: pill._close_panel()),
        (0, palette_open),
        (600, lambda: box_shot(pill, "12-compact-palette")),
        (0, setup_open),
        (600, lambda: box_shot(pill, "13-compact-setup")),
        (0, lambda: pill._close_box()),
        (0, no_cli),
        (500, lambda: shot(pill, "14-compact-no-cli")),
        (0, lambda: setattr(pill, "_mic_gone", True)),
        (500, lambda: shot(pill, "15-compact-mic-gone")),
        (0, lambda: setattr(pill, "_mic_gone", False)),
        (0, silence),
        (500, lambda: shot(pill, "16-compact-silence")),
        (0, refine_failed),
        (600, lambda: shot(pill, "17-compact-refine-failed")),
        (0, lambda: pill._close_panel()),
        (0, recover),
        (500, lambda: shot(pill, "18-compact-recover")),
        (0, copied),
        (500, lambda: shot(pill, "19-compact-copied")),
        (0, reset_fallbacks),
        # The three the pill learned to say after "push to talk does not do
        # anything, I cannot explain the failure to you" — which is what a
        # surface with no feedback produces: not a wrong description, but none
        # available at all.
        (0, loading(True)),
        (500, lambda: shot(pill, "20-compact-loading")),
        (0, loading(False)),
        (0, mic_open()),
        (500, lambda: shot(pill, "21-compact-mic-open")),
        (0, state(State.IDLE, armed=False)),
        (0, reset_fallbacks),
        # The three the pill learned to say after "push to talk does not do
        # anything, I cannot explain the failure to you" — which is what a
        # surface with no feedback produces: not a wrong description, but none
        # available at all.
        (0, loading(True)),
        (500, lambda: shot(pill, "20-compact-loading")),
        (0, loading(False)),
        (0, mic_open()),
        (500, lambda: shot(pill, "21-compact-mic-open")),
        (0, state(State.IDLE, armed=False)),
        (0, reset_fallbacks),
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
