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
  ask long  the same band grown to a ten-line answer, footer moved with it
  asking    the same, mid-ask: heard only, the ring wraps the foot
  closed    120 wide again immediately after the close, proving it returns
  refine    REFINE at rest: the gold glyph, no ring
  refine panel  the heard block grey, the result under its gold tag, Send
  refine bullets  Refine.dc.html's own worked example: a lead line, a blank
                  line and three bullets, one of them indented
  palette   Switch workspace, mid-search: the query field, the top hit lit
  no-cli    States.dc.html 1: no agent CLI on PATH — grey, not red
  mic-gone  States.dc.html 2: slashed glyph, persistent red ring
  silence   States.dc.html 3: held, nothing said — straight back to grey
  refine-failed  States.dc.html 4: the raw dictation, the CLI's last line
  recover   States.dc.html 5: the workspace is gone — amber, once
  copied    States.dc.html 6: Lite — `copied — press Ctrl+V` under the pill
  menu      the right-click, the only menu the design allows
  email     Refine in a mail window: the dictation, and the email it became
            under "written as an email" (flow/kinds.py)
  writing   the same panel while the CLI is out: what is being written, by
            whom, and for how long
  asking-n  Ask's wait, with its seconds
  mode      the line a tap puts under the pill: the mode, and what it will do
  failed    a failure, said under its flash
  needs-cli a tap with no agent CLI: what the other two modes need

Everything above the last six is the panel flow, which since 2026-11-22 is a setting
(`Profile.panel_flows`) and is photographed with it on. The last six are the product:

  flow-rewriting  "make it an email", said after the words landed: the pill, and
                  under it what is being written and for how long
  flow-landed     it went in where the words were, and the way back
  flow-fallback   the CLI did not answer: the words as said went in instead
  flow-asking     a question out: the pill and a line, nothing risen
  flow-answer     the answer card: the question, the answer, Copy and the way to
                  the conversation - up until it is closed
  flow-keys       a tap on the pill, with keys to hold: what the keys are

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

from flow import kinds, paint  # noqa: E402

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

    def ask_long():
        # The band grown to a real answer. The fixed 200 px showed two lines
        # of this and dropped the other eight on the floor; the band is as
        # tall as its text now, up to `RESULT_LINES_MAX`, and the footer
        # travels with its bottom edge.
        sess.state, sess.mode = State.IDLE, CONVERSE
        pill.armed = False
        pill._panel_mode = CONVERSE
        pill._panel_heard = "How does the compact surface get antialiased?"
        pill._panel_heard_final = True
        pill._panel_result = (
            "Tk 8.6's canvas has no antialiasing, and these windows are "
            "colour-keyed, so transparency is binary: a pixel is either "
            "wholly the pill or wholly see-through.\n"
            "\n"
            "So flow/paint.py's GdiCanvas draws with GDI+ into a "
            "premultiplied BGRA bitmap and presents it with "
            "UpdateLayeredWindow, which is the per-pixel-alpha path — and it "
            "wears tk.Canvas's own vocabulary, so one body of drawing code "
            "serves it.")
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

    def refine_bullets():
        # Refine.dc.html's own worked example, which the panel could not draw
        # until `_fit` stopped collapsing the text with `text.split()`: a lead
        # line, a blank line, and three bullets — the middle one indented, the
        # way spoken "tab dash fix the tests" resolves. Send has always pasted
        # this shape; this is the first time the panel shows it.
        sess.state, sess.mode = State.IDLE, REFINE
        pill.armed = False
        pill._panel_mode = REFINE
        pill._panel_heard = ("make the pill not show any controls just the mic "
                             "press enter press enter then tab dash fix the "
                             "tests")
        pill._panel_heard_final = True
        pill._panel_failed = False
        pill._panel_result = (
            "Strip every control from the push-to-talk pill in flow/ui.py — "
            "leave the mic glyph and the meter.\n"
            "\n"
            "- On release, inject the draft into the window that held focus "
            "before the pill, not the clipboard.\n"
            "    - fix the tests\n"
            "- Keep the 34 px height and the PILL_HOLD_SEC threshold as they "
            "are.")
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

    # (The Workbench setup box used to be photographed here. It left the
    # product when Flow Home took its three lines, and this step went on
    # calling `_open_setup` into an AttributeError the walk swallowed.)

    def flow(on: bool):
        """Which flow the pill is in for the steps that follow (see the docstring)."""
        def fn():
            pill.panel_flows = on
        return fn

    def flow_rewriting():
        # Type, the words already on the page, and "make it an email" out with the
        # CLI. `_pump_waiting` puts the line there on the pill's own frames.
        pill._close_panel()
        sess.mode, sess.state = DICTATE, State.REFINING
        sess.target_app, sess.refine_kind = "OUTLOOK.EXE", kinds.EMAIL
        sess.refine_doing = kinds.KINDS[kinds.EMAIL].doing
        sess.waited = 4.3
        pill.armed = False

    def flow_landed():
        sess.state, sess.waited = State.IDLE, 0.0
        pill._say(f"{kinds.KINDS[kinds.EMAIL].tag} - {kinds.UNDO_HINT}")

    def flow_fallback():
        pill._flash = FLASH_FRAMES
        pill._say(uc._clip("no rewrite - your words went in as you said them: "
                           "claude timed out after 20s"), uc.ERROR_FRAMES)

    def flow_asking():
        pill._flash = 0
        sess.mode, sess.state, sess.waited = CONVERSE, State.ASKING, 9.4
        pill.armed = False

    def flow_answer():
        # Driven the way the app drives it: the release, then the reply event.
        sess.state, sess.waited = State.IDLE, 0.0
        pill._panel_mode = CONVERSE
        pill._panel_failed = False
        pill._panel_heard = "which file decides what kind of writing refine produces"
        pill._panel_heard_final = True
        pill._panel_result = ("That is flow/kinds.py: resolve() takes your own choice "
                              "for a program first, then your default, then reads "
                              "the window. flow/refine.py holds the brief each kind "
                              "is written from.")
        pill._open_panel()

    def flow_keys():
        from types import SimpleNamespace as NS

        pill._close_panel()
        sess.mode, sess.state = DICTATE, State.IDLE
        pill.hotkeys = NS(chord=NS(describe=lambda: "ctrl+win"),
                          ask_chord=NS(describe=lambda: "ctrl+alt+win"),
                          drain=lambda: [], hook=None)
        pill._tap()

    def flow_done():
        pill.hotkeys = None
        pill._notice = 0
        pill._sync_shell()

    PRIYA = ("hey so um I need to write to Priya about the the release we were "
             "supposed to ship on Thursday but uh the migration is not done so "
             "I think we should move it to next Tuesday and also can you ask "
             "her to to let the QA team know and say sorry for the late notice")

    def refine_email():
        # What `claude` returned for exactly these words through the email
        # brief on 2026-11-22, with a name set - not a mock-up of it.
        sess.state, sess.mode = State.IDLE, REFINE
        sess.target_app, sess.refine_kind = "OUTLOOK.EXE", kinds.EMAIL
        pill.armed = False
        pill._panel_mode = REFINE
        pill._panel_failed = False
        pill._panel_heard = PRIYA
        pill._panel_heard_final = True
        pill._panel_result = (
            "Hi Priya,\n"
            "\n"
            "I think we should move the release from Thursday to next "
            "Tuesday. The migration is not done.\n"
            "\n"
            "Could you let the QA team know? Sorry for the late notice.\n"
            "\n"
            "Thanks,\n"
            "Samar")
        pill._open_panel()

    def refine_writing():
        # Mid-refine: the words are in, the CLI is out, and the tag's row says
        # what is happening instead of leaving a blue ring to carry it.
        sess.state, sess.mode = State.REFINING, REFINE
        sess.target_app, sess.refine_kind = "OUTLOOK.EXE", kinds.EMAIL
        sess.waited = 6.4
        pill.armed = True
        pill._panel_mode = REFINE
        pill._panel_failed = False
        pill._panel_heard = PRIYA
        pill._panel_heard_final = True
        pill._panel_result = ""
        pill._open_panel()

    def asking_counted():
        sess.state, sess.mode = State.ASKING, CONVERSE
        sess.waited = 14.2
        pill.armed = True
        pill._panel_mode = CONVERSE
        pill._panel_failed = False
        pill._panel_heard = "which file draws the pill and how does it pick the ring colour"
        pill._panel_heard_final = True
        pill._panel_result = ""
        pill._open_panel()

    def mode_line():
        # A tap onto Refine with Outlook in front.
        pill._close_panel()
        sess.state, sess.mode, sess.waited = State.IDLE, REFINE, 0.0
        sess.target_app = "OUTLOOK.EXE"
        pill.armed = False
        pill._say(pill._mode_line())

    def failure_line():
        sess.mode, sess.state = DICTATE, State.IDLE
        pill._flash = FLASH_FRAMES
        pill._say(uc._clip(
            "skipping codex - see Flow Home, Models: exited 1: The 'gpt-6.2-astra' "
            "model is not supported when using Codex with a ChatGPT account."),
            uc.ERROR_FRAMES)

    def needs_cli():
        pill._flash = 0
        sess._provider = lambda: ""
        sess.mode, sess.state = DICTATE, State.IDLE
        pill._cycle_mode()

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
        #
        # Closed first, because the case this photographs is the band the
        # *hold* raised. Since 2026-09-04 a silent hold over an exchange that
        # is already on screen leaves it exactly as it was (a hold no longer
        # wipes the answer at the press), so without this the shot after the
        # refine panel was a picture of that other, also-correct case.
        sess.mode = CONVERSE
        pill._close_panel()
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
        #
        # Through `_say`, which is what raises the strip. This set `_copied`,
        # an attribute the `_say`/`_notice` rework of 2026-09-04 removed — and
        # since a `__new__`-shy real pill just takes the assignment, nothing
        # complained: `19-compact-copied.png` was a photograph of a bare pill
        # with no line under it at all, standing in for the one state this
        # shot exists to prove.
        pill._recover = 0
        pill.on_send = None
        pill._say(uc.COPIED_TEXT, COPIED_FRAMES)

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
        # The panel flow, for every picture down to the last six.
        (0, flow(True)),
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
        (0, ask_long),
        (700, lambda: shot(pill, "07b-compact-ask-long")),
        # `asking_panel` clears the result, so 08 also proves the band comes
        # back down to its floor when the text it grew for goes away.
        (0, asking_panel),
        (500, lambda: shot(pill, "08-compact-asking")),
        (0, lambda: pill._close_panel()),
        (500, lambda: shot(pill, "09-compact-closed")),
        (0, state(State.IDLE, mode=REFINE, armed=False)),
        (600, lambda: shot(pill, "10-compact-refine")),
        (0, refine_panel),
        (700, lambda: shot(pill, "11-compact-refine-panel")),
        (0, refine_bullets),
        (700, lambda: shot(pill, "11b-compact-refine-bullets")),
        (0, lambda: pill._close_panel()),
        (0, palette_open),
        (600, lambda: box_shot(pill, "12-compact-palette")),
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
        # What the pill says in words, 2026-11-22.
        (0, refine_email),
        (700, lambda: shot(pill, "22-compact-refine-email")),
        (0, refine_writing),
        (700, lambda: shot(pill, "23-compact-refine-writing")),
        (0, asking_counted),
        (700, lambda: shot(pill, "24-compact-asking-counted")),
        (0, mode_line),
        (600, lambda: shot(pill, "25-compact-mode-line")),
        (0, failure_line),
        (300, lambda: shot(pill, "26-compact-failure-line")),
        (0, reset_fallbacks),
        (0, needs_cli),
        (500, lambda: shot(pill, "27-compact-needs-cli")),
        (0, reset_fallbacks),
        # The product's flow, 2026-11-22: nothing rises while you talk.
        (0, flow(False)),
        (0, flow_rewriting),
        (700, lambda: shot(pill, "30-flow-rewriting")),
        (0, flow_landed),
        (400, lambda: shot(pill, "31-flow-landed")),
        (0, flow_fallback),
        (300, lambda: shot(pill, "32-flow-fallback")),
        (0, flow_asking),
        (700, lambda: shot(pill, "33-flow-asking")),
        (0, flow_answer),
        (700, lambda: shot(pill, "34-flow-answer")),
        (0, flow_keys),
        (500, lambda: shot(pill, "35-flow-keys")),
        (0, flow_done),
        (0, flow(True)),
        (0, reset_fallbacks),
        (0, lambda: setattr(sess, "target_app", "claude.exe")),
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
