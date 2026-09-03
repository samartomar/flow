"""Photograph every surface Flow draws, against a fake session.

`ui_probe.py` next door renders the pill and the bubble so a person can look at
them. This goes the rest of the way: it walks *every* state, in both modes,
opens the real right-click menus, and writes a PNG per surface — so a UI change
can be reviewed as a set of pictures rather than as a diff, and so "it renders"
stops being a claim nobody checked.

Same discipline as `ui_probe`: the real `Pill`, `Bubble`, `ConversationCard` and
`HelpWindow` drive against a `Session` stand-in. No microphone is opened, no
model is loaded, no CLI is called, no hotkey is registered, and nothing is ever
pasted — `Session.send()` here just clears a string. A full-screen neutral
backdrop sits behind Flow so the captures show the app and not the desktop
behind it.

    uv run --with pillow python scripts/shots.py
    uv run --with pillow python scripts/shots.py --out docs/shots

Pillow is a `--with`, not a dependency: it is fetched into the run and never
enters the venv, so R16 still holds at three (`pyproject.toml` says why that
number is defended). It is here for `ImageGrab` alone — capturing a *menu*
means capturing pixels Tk did not draw, because a Tk popup on Windows is a
native `#32768` window that no canvas dump can reach.

Two things this had to learn about running under Windows, both handled rather
than assumed:

  **DPI.** The ratio between the framebuffer and the coordinate space Tk speaks
  is measured at capture time, not hardcoded — on a 4K display with a
  virtualized process it is 3, and on a 1:1 display it is 1.

  **Menu rows.** Row offsets are *found*, not counted. Earlier versions carried
  measured pixel offsets for the eleven-row menu; the menu became six rows and
  every one of them pointed at the wrong thing while still capturing a
  plausible-looking picture. `_find_cascades` instead walks the cursor down the
  open menu and records where each submenu actually unfolds, so the walk
  survives the next time a row is added.
"""

from __future__ import annotations

import argparse
import ctypes
import math
import sys
import threading
import time
import tkinter as tk
import traceback
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PIL import ImageGrab  # noqa: E402

import flow.ui as ui  # noqa: E402
from flow.session import CONVERSE, DICTATE, Activity, Event, State  # noqa: E402
from flow.ui import Pill  # noqa: E402

DRAFT = (
    "Hey Samar, I wanted to check whether we are still good for the review on Tuesday "
    "afternoon, and whether you had a chance to look at the updated figures."
)
#: One line at the body width, so the window it sizes is short enough for a long partial
#: to overrun — see the `03b` step.
SHORT_DRAFT = "seconds, send the question. No auto-ask to press it yourself."

#: Transcribed the way a partial actually arrives mid-sentence — no capitals, no final
#: stop. Five lines at the body width, which is past the four it takes to reach the note:
#: at three it still fits by a couple of pixels, and a repro that only just passes is one
#: that stops reproducing the next time a font metric moves.
LONG_PARTIAL = (
    "part key towel control sipped space voice the ask button puts the drop to the "
    "agency ally and the reply goes on so pause up the four second the question no "
    "auto ask found open code not just yet verified see nest you voice natural yes "
    "and the workshop is not set so ask runs without a project mode dictate send "
    "pastes into the focused window click the pill to arm right click for the menu"
)
QUESTION = ("what is my prompt for the rollback plan still missing before "
            "I hand it to the agent")
ANSWER = (
    "It never says which environment the rollback targets, so name staging or "
    "production explicitly. It should also state what \"done\" looks like - the "
    "health check that proves the rollback worked. Add the deploy tag you are "
    "rolling back from, and the prompt stands on its own."
)

user32 = ctypes.windll.user32


# -- the session stand-in ------------------------------------------------------

class FakeMic:
    #: Read by `Pill._bar_label`, which says `NO INPUT` when the device has gone —
    #: distinct from `SPEAKING`/`EDITING`, where the microphone comes back on its own.
    active = True

    def stop(self) -> None: ...


class FakeDraft:
    def __init__(self) -> None:
        self.text = ""

    def clear(self) -> str:
        out, self.text = self.text, ""
        return out


class FakeProfile:
    path = Path.home() / ".flow" / "profile.json"
    send_word = "boom"
    send_enter_word = "enter boom"
    welcomed = True
    auto_ask = True

    def __init__(self) -> None:
        self.workspaces = [str(REPO)]

    def save(self) -> bool:
        return True

    def offered_pairs(self, declared=()):
        return [("semir", "Samir")]

    def dismiss_pair(self, wrong, right) -> None: ...


class FakeVoice:
    def __init__(self, name, gender):
        self.engine, self.name, self.gender = "sapi", name, gender

    def describe(self) -> str:
        return self.name


class FakeSession:
    """Just enough of the `Session` surface for every UI window to drive.

    Deliberately hand-written rather than a `Mock`: a Mock answers every
    attribute, so a UI that started reading something new would still render and
    the shot would quietly stop being a picture of the real thing.
    """

    def __init__(self) -> None:
        self.draft = FakeDraft()
        self.mic = FakeMic()
        self.force_next = None
        self.mode = DICTATE
        self.state = State.IDLE
        self.activity = None
        self.hearing = True
        self.profile = FakeProfile()
        self.workspace = str(REPO)
        self.send_words = ("boom", "enter boom")
        self.recent = [
            ("sent", "hi Samar, the deploy is scheduled for Tuesday afternoon."),
            ("asked", QUESTION),
        ]
        self.speaker = SimpleNamespace(voice="Microsoft Susan")
        self.muted = False
        self.cli = None
        self.auto_ask = True
        self.auto_ask_in = None
        self.editing = False
        self.can_rescue = False
        self.can_take_reply = False
        #: Read by the mic view's resting frame, and by the full row's app slot.
        self.target_app = "claude.exe"
        #: Read by `_pump_talk` while a paste is waiting.
        self.busy = False
        self._events: list[Event] = []
        self._t0 = time.perf_counter()

    def start(self) -> None: ...
    def close(self) -> None: ...
    def tick(self) -> None: ...
    def pump_results(self) -> None: ...
    def pause(self) -> None: ...
    def stop_speaking(self) -> None: ...
    def hold_auto_ask(self) -> None: ...
    def rescue_last_append(self) -> None: ...
    def toggle_mode(self) -> None: ...
    def toggle_speech(self) -> None: ...
    def toggle_auto_ask(self) -> None: ...
    def set_cli(self, cli) -> None: ...
    def set_voice(self, name) -> None: ...
    def set_workspace(self, path) -> None: ...
    def keep_note(self, text: str = "") -> bool: return True
    def wrap_up(self) -> None: ...
    def new_conversation(self) -> None: ...
    def take_reply(self) -> bool: return True

    def voices(self):
        return [FakeVoice("Microsoft Susan", "female"),
                FakeVoice("Microsoft George", "male"),
                FakeVoice("Microsoft Hazel Desktop", "female")]

    def events(self):
        out, self._events = self._events, []
        return out

    def push(self, kind: str, text: str = "") -> None:
        self._events.append(Event(kind, text))

    def send(self) -> str:
        return self.draft.clear()

    def recall(self) -> None:
        self.draft.text = DRAFT
        self.push("draft", DRAFT)

    def begin_edit(self) -> str:
        self.editing = True
        return self.draft.text

    def cancel_edit(self) -> None:
        self.editing = False

    def commit_edit(self, text: str) -> None:
        self.editing, self.draft.text = False, text

    @property
    def level_db(self) -> float:
        """The same envelope `ui_probe` uses, floored the way the session floors
        it — so the meter in a shot is one the app could actually produce."""
        if not self.hearing:
            return -120.0
        t = time.perf_counter() - self._t0
        env = 0.5 + 0.5 * math.sin(t * 5.0)
        return -58.0 + 46.0 * max(0.0, min(1.0, 0.55 * env + 0.25 * math.sin(t * 23.0)))


# -- capture -------------------------------------------------------------------

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN = 76, 77, 78
OUT = REPO / ".shots"
_taken: list[str] = []


def _ratio(img) -> float:
    """Framebuffer pixels per unit of the coordinate space Tk and Win32 speak.

    Measured every grab rather than assumed: a DPI-virtualized process on a 4K
    display reports 1280x720 while `ImageGrab` returns 3840x2160, and the same
    code has to work unchanged where the two agree.
    """
    return img.width / max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))


def _grab(bbox, name: str) -> None:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    img = ImageGrab.grab(all_screens=True)
    k = _ratio(img)
    left, top, right, bottom = bbox
    img = img.crop((max(0, int((left - vx) * k)), max(0, int((top - vy) * k)),
                    min(img.width, int((right - vx) * k)),
                    min(img.height, int((bottom - vy) * k))))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.png")
    _taken.append(name)
    print(f"  {name}.png  {img.width}x{img.height}", flush=True)


def _visible(pill):
    out = [pill]
    for w in (pill.bubble, pill.card, pill._help):
        if w is not None and w.winfo_viewable():
            out.append(w)
    return out


def _front(pill) -> None:
    """Put Flow's own windows back on top of the backdrop before a capture.

    The backdrop has to be `-topmost` to cover the desktop at all, which puts it in the
    same z-band as every window Flow draws — and the ordering inside that band is not
    stable across a run. Left alone it silently swallowed the pill: the panel above it
    still captured, so the shots looked plausible and were missing the one window the
    set is named after. It took the right-click with it, which is why the menu walk
    reported no menu on the same run.
    """
    for w in _visible(pill):
        try:
            w.lift()
        except tk.TclError:  # withdrawn between the check and the lift
            pass


def shot(pill, name: str, margin: int = 26) -> None:
    _front(pill)
    pill.update_idletasks()
    boxes = [(w.winfo_rootx(), w.winfo_rooty(),
              w.winfo_rootx() + w.winfo_width(),
              w.winfo_rooty() + w.winfo_height()) for w in _visible(pill)]
    _grab((min(b[0] for b in boxes) - margin, min(b[1] for b in boxes) - margin,
           max(b[2] for b in boxes) + margin, max(b[3] for b in boxes) + margin),
          name)


# -- native menus (worker thread; never touches Tk) ----------------------------

KEYEVENTF_KEYUP, VK_ESC = 0x0002, 0x1B
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
WM_CANCELMODE = 0x001F
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _menu_rects():
    """Every visible native popup-menu window, topmost-first."""
    rects = []

    @WNDENUMPROC
    def cb(hwnd, _l):
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value == "#32768" and user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            rects.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumWindows(cb, 0)
    return rects


def _cap_menu(name: str, anchor) -> None:
    boxes = _menu_rects() + [anchor]
    _grab((min(b[0] for b in boxes) - 26, min(b[1] for b in boxes) - 26,
           max(b[2] for b in boxes) + 26, max(b[3] for b in boxes) + 26), name)


def _close_menus(hwnd) -> None:
    user32.PostMessageW(hwnd, WM_CANCELMODE, 0, 0)
    end = time.time() + 3
    while _menu_rects() and time.time() < end:
        time.sleep(0.1)
    tries = 0
    while _menu_rects() and tries < 8:  # Escape only ever while a menu is up
        user32.keybd_event(VK_ESC, 0, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(VK_ESC, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.16)
        tries += 1
    time.sleep(0.8)


def _right_click(x: int, y: int, k: float):
    """Right-click at a point, trying both coordinate spaces.

    `SetCursorPos` speaks the virtualized space and `mouse_event` follows it, but
    which one lands depends on the process's DPI awareness at the moment of the
    call — so try the logical point, and fall back to the scaled one.
    """
    for ax, ay in ((x, y), (int(x * k), int(y * k))):
        user32.SetCursorPos(ax, ay)
        time.sleep(0.10)
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        end = time.time() + 1.5
        while time.time() < end and not _menu_rects():
            time.sleep(0.05)
        if _menu_rects():
            return _menu_rects()[0]
    return None


#: Longer than Windows' submenu open delay (`MenuShowDelay`, 400 ms by default).
#: This is the whole reason an earlier version of `_find_cascades` found nothing:
#: it stepped every 120 ms, so the cursor never once rested on a row long enough
#: for the submenu to unfold, and the walk cheerfully captured five identical
#: pictures of the parent menu.
MENU_DWELL = 0.55


def _find_cascades(main, on_open, limit=4, step=6):
    """Walk down an open menu, calling `on_open(index, rect)` as each cascade
    unfolds — top to bottom, which for the pill's menu is Mode, Draft, Settings,
    Help. Returns how many were found.

    The callback fires *during* the walk, and that is the point: only one
    submenu is open at a time, so collecting them into a list and photographing
    afterwards yields N copies of whichever one happened to be open last.

    Found rather than counted, deliberately. The offsets this replaced were
    measured against the eleven-row menu; when the menu became six rows they all
    still pointed *somewhere*, so the walk kept producing confident pictures of
    the wrong rows. Hovering and watching is slower and cannot drift.
    """
    left, top, _r, bottom = main
    found, seen = 0, set()
    y = top + 6
    while y < bottom - 4 and found < limit:
        # Two positions, because `SetCursorPos` to where the cursor already is
        # posts no `WM_MOUSEMOVE` — and a native menu opens a cascade on the move,
        # not on the position.
        user32.SetCursorPos(int(left + 24), int(y))
        user32.SetCursorPos(int(left + 30), int(y))
        time.sleep(MENU_DWELL)
        subs = [r for r in _menu_rects() if (r[0], r[1]) != (main[0], main[1])]
        if subs:
            key = (subs[0][0], subs[0][1])
            if key not in seen:
                seen.add(key)
                on_open(found, subs[0])
                found += 1
        y += step
    return found


def menu_worker(pill_rect, click_xy, hwnd, k, names, done: threading.Event):
    """Photograph a menu tree from a worker thread.

    On the worker because `tk_popup` runs a modal loop that owns the UI thread
    until the menu closes — so the thread that opens it cannot also drive it.
    Nothing here touches a Tk object; it is all Win32 against window handles.
    """
    try:
        home = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(home))
        main = _right_click(*click_xy, k)
        if main is None:
            print("  ! menu never opened", file=sys.stderr)
            return
        # Park the cursor beside the rows so the first shot has nothing hovered.
        user32.SetCursorPos(max(0, main[0] - 80), main[1])
        time.sleep(0.45)
        _cap_menu(names[0], pill_rect)

        def on_open(i, _sub):
            if i + 1 < len(names):
                _cap_menu(names[i + 1], pill_rect)

        got = _find_cascades(main, on_open, limit=max(0, len(names) - 1))
        if got < len(names) - 1:
            print(f"  ! {names[0]}: {got} of {len(names) - 1} cascades opened",
                  file=sys.stderr)
        _close_menus(hwnd)
        user32.SetCursorPos(home.x, home.y)
    except Exception:
        traceback.print_exc()
        _close_menus(hwnd)
    finally:
        done.set()


# -- the walk ------------------------------------------------------------------

def build(pill, sess):
    """The script, as (delay_ms, action) pairs. An action returning an Event gates."""
    def state(st, activity=None, hearing=True, armed=True):
        def fn():
            sess.state, sess.activity, sess.hearing = st, activity, hearing
            pill.armed = armed
            # What `_toggle` does either side of the same flag, and leaving it out was
            # quietly costing every shot after the first eight seconds: `_apply_idle_dim`
            # kept counting from the disarmed pill this walk starts with, so the window
            # faded to `IDLE_DIM_ALPHA` and stayed there. Sampled off `06-refining`, the
            # accent came back (83, 106, 155) against `WAITING`'s (122, 162, 247) — 55 %
            # of the colour, on a page of images whose whole job is to be believed.
            pill._disarmed_since = None if armed else time.perf_counter()
        return fn

    def menu(names, target):
        def fn():
            w = target()
            _front(pill)          # the click has to reach Flow, not the backdrop
            pill.update_idletasks()
            x, y = w.winfo_rootx(), w.winfo_rooty()
            rect = (x, y, x + w.winfo_width(), y + w.winfo_height())
            done = threading.Event()
            k = _ratio(ImageGrab.grab(all_screens=True))
            threading.Thread(
                target=menu_worker,
                args=(rect, (x + 40, y + w.winfo_height() // 2),
                      ui.toplevel_hwnd(pill), k, names, done),
                daemon=True).start()
            return done
        return fn

    held = lambda: (setattr(sess.draft, "text", DRAFT),          # noqa: E731
                    setattr(sess, "can_rescue", True),
                    sess.push("draft", DRAFT),
                    # An "edit" event, not a "note": it is what the router emits after a
                    # local correction, and the kind that earns an Undo beside it.
                    sess.push("edit", "changed “thursday” to “Tuesday”"))

    return [
        # -- dictate ----------------------------------------------------------
        (900, state(State.IDLE, armed=False)),
        (600, lambda: shot(pill, "01-pill-idle")),
        (0, state(State.LISTENING)),
        (1300, lambda: shot(pill, "02-pill-listening")),
        (0, lambda: sess.push("partial", DRAFT[:64] + " and whether you had a")),
        (900, lambda: shot(pill, "03-partial")),
        # A long partial over a *short* draft, with a note under it. The short draft is
        # the point and not an accident: the note is anchored to the panel's foot, so a
        # long draft makes the window tall enough to hide the collision entirely. The
        # window is sized from the draft, the partial then overruns the slot it was
        # given, and the two meet in the middle. This is the shape that was reported.
        (0, lambda: (setattr(sess.draft, "text", SHORT_DRAFT),
                     sess.push("draft", SHORT_DRAFT),
                     sess.push("edit", "changed “thursday” to “Tuesday”"),
                     sess.push("partial", LONG_PARTIAL))),
        (900, lambda: shot(pill, "03b-partial-long")),
        (0, lambda: setattr(pill.bubble, "_partial", "")),
        (0, held),
        (0, state(State.DRAFT)),
        (900, lambda: shot(pill, "04-draft-held")),
        (0, state(State.LISTENING, Activity("decoding", True))),
        (900, lambda: shot(pill, "05-decoding")),
        (0, state(State.REFINING, Activity("refining", True))),
        (900, lambda: shot(pill, "06-refining")),
        # The same wait a third of a second later. Two frames, because the meter's slot
        # is holding three marching dots here and a single still cannot tell a wave
        # passing along them from three dots that are simply painted at fixed shades.
        (330, lambda: shot(pill, "06b-refining-later")),
        (0, state(State.DRAFT, Activity("editing - not listening", False),
                  hearing=False)),
        (200, lambda: pill.bubble._edit()),
        (900, lambda: shot(pill, "07-editor")),
        (0, lambda: pill.bubble._cancel_edit()),
        (0, state(State.DRAFT)),
        (400, lambda: pill._send()),
        (900, lambda: shot(pill, "08-sent")),
        (0, lambda: pill.bubble.hide()),
        # §03's own error frame, and the finding it comes with: "deafness is a flat
        # line, never coloured bars — today's error frame paints eighteen loud red bars
        # in the one state where nothing is being heard". Photographing that needs the
        # device actually gone, not just a red flash over a full meter.
        (300, lambda: (setattr(pill, "_flash", ui.FLASH_FRAMES),
                       setattr(sess.mic, "active", False),
                       setattr(sess, "hearing", False),
                       pill.bubble.surface("could not start capture: the input "
                                           "device is already in exclusive use"))),
        (400, lambda: shot(pill, "09-error")),
        (0, lambda: (setattr(pill, "_flash", 0), setattr(sess.mic, "active", True),
                     setattr(sess, "hearing", True), pill.bubble.hide())),
        (0, state(State.IDLE, Activity("loading the model", True))),
        (900, lambda: shot(pill, "10-loading")),
        (0, state(State.IDLE)),
        # -- the mic view ------------------------------------------------------
        # Photographed because it cannot be reviewed any other way. Every test for it
        # drives `_draw` against a recording canvas, which says what was asked of Tk and
        # nothing about what Tk did — and the bug that shipped past those tests was a
        # name overrunning the mic glyph, which is only a bug once it is pixels.
        # Both frames, because the press swaps what is drawn and neither half is the
        # other's default.
        (300, lambda: (setattr(pill, "mic_view_on", True),
                       state(State.LISTENING)())),
        (600, lambda: shot(pill, "10a-mic-rest")),
        (200, lambda: (setattr(pill, "_ptt_since", time.perf_counter()),
                       setattr(pill, "_meter_level", 0.75),
                       setattr(pill, "_eased_level", 0.75))),
        (400, lambda: shot(pill, "10b-mic-talking")),
        (0, lambda: (setattr(pill, "_ptt_since", None),
                     setattr(pill, "_meter_level", 0.0))),
        # The longest name the row can be handed, against the one thing beside it.
        (300, lambda: setattr(sess, "target_app", "WindowsTerminal.exe")),
        (400, lambda: shot(pill, "10c-mic-long-name")),
        (0, lambda: setattr(sess, "target_app", "claude.exe")),
        # The grow-back: with no panels there is nowhere for a note to land, so the view
        # stands down for as long as one is up. The picture is the proof it is one
        # window and not a 90 px row parked under a 400 px panel.
        (300, lambda: pill.bubble.surface("could not reach the CLI - is claude "
                                          "on PATH?")),
        (600, lambda: shot(pill, "10d-mic-note-growback")),
        (0, lambda: pill.bubble.hide()),
        (400, lambda: shot(pill, "10e-mic-shrunk-again")),
        (0, lambda: (setattr(pill, "mic_view_on", False), state(State.IDLE)())),
        # The full row's app slot has the same overrun the mic view's did, and it was
        # written off as one this row never shows. It does: 69 px of `WindowsTe…` from
        # x=10, against a mic arc starting at 61. Photographed so the write-off cannot
        # be made twice.
        (300, lambda: setattr(sess, "target_app", "WindowsTerminal.exe")),
        (400, lambda: shot(pill, "10f-full-row-long-name")),
        (0, lambda: setattr(sess, "target_app", "claude.exe")),
        # -- windows ----------------------------------------------------------
        (300, lambda: pill._open_commands()),
        (900, lambda: shot(pill, "11-help-commands")),
        (0, lambda: pill._help.close()),
        (200, lambda: (setattr(sess.profile, "welcomed", False), pill._welcome())),
        (900, lambda: shot(pill, "12-welcome")),
        (0, lambda: pill._help.close()),
        # -- menus ------------------------------------------------------------
        (500, menu(["13-menu", "14-menu-mode", "15-menu-draft",
                    "16-menu-settings", "17-menu-help"], lambda: pill)),
        # The correction offers moved off the pill menu onto the panel showing the
        # words they are about, so that is where they have to be photographed.
        (400, lambda: (held(), state(State.DRAFT)())),
        (600, menu(["18-draft-context"], lambda: pill.bubble)),
        # -- converse ----------------------------------------------------------
        (400, lambda: (setattr(sess, "mode", CONVERSE), sess.push("mode"),
                       sess.push("note", f"workshop: {REPO}"))),
        (0, state(State.LISTENING)),
        # Caught inside the 180 ms the glyph and the label take to travel from green to
        # violet — the one thing that is continuous across a switch that takes one
        # window down and puts another up. The next shot is the same pill arrived.
        #
        # Which fraction it catches is a lottery: the frame that swaps two windows runs
        # long, so during this stretch the 30 ms tick actually lands about 90 ms apart.
        # 120 ms in has come back at `#65B9B0`, a third of the way. The travel itself is
        # pinned frame-by-frame in `tests/test_pill.py`; this only has to show that it
        # is a travel and not a jump.
        (120, lambda: shot(pill, "19a-converse-mid-tint")),
        (900, lambda: shot(pill, "19-converse")),
        (0, lambda: (setattr(sess, "auto_ask_in", 2.2),
                     pill.card.show_partial(QUESTION))),
        (700, lambda: shot(pill, "20-converse-countdown")),
        (0, lambda: (setattr(sess, "auto_ask_in", None), pill.card.ask(QUESTION))),
        (0, state(State.ASKING, Activity("asking", True))),
        (900, lambda: shot(pill, "21-converse-asking")),
        (0, lambda: (setattr(sess, "can_take_reply", True), sess.push("reply", ANSWER))),
        (0, state(State.IDLE)),
        (900, lambda: shot(pill, "22-converse-answer")),
        (0, state(State.IDLE, Activity("speaking - not listening", False),
                  hearing=False)),
        (900, lambda: shot(pill, "23-converse-speaking")),
    ]


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT,
                    help=f"where the PNGs land (default {OUT})")
    ap.add_argument("--no-backdrop", action="store_true",
                    help="capture over the real desktop instead of a flat panel")
    args = ap.parse_args()
    OUT = args.out.resolve()

    sess = FakeSession()
    hotkeys = SimpleNamespace(
        chosen={"toggle": "ctrl+alt+space", "send": "ctrl+alt+enter",
                "cancel": "ctrl+alt+esc", "mode": "ctrl+alt+M",
                "quit": "ctrl+alt+Q"},
        # A chord, because two things read one: the Settings menu names the gesture in
        # its own row, and the mic view is offered only while that gesture is the hold.
        # Without it both are absent from the walk and the shots stop covering them.
        chord=SimpleNamespace(gesture="hold", action="toggle",
                              describe=lambda: "Ctrl+Win"),
        failed=[], stop=lambda: None, drain=lambda: [])
    pill = Pill(sess, hotkeys=hotkeys)
    # The editor checks it really holds the foreground before taking keystrokes;
    # a probe has no click to have earned it with, so let it trust our own
    # windows. Affects nothing else in the walk.
    ui.owned_by_flow = lambda _h: True

    if not args.no_backdrop:
        back = tk.Toplevel(pill)
        back.overrideredirect(True)
        back.configure(bg="#23262b")
        back.geometry(f"{pill.winfo_screenwidth()}x{pill.winfo_screenheight()}+0+0")
        ui._no_activate(back)
        # Topmost so it rises over the desktop's own windows — a plain lift() is
        # refused and the desktop shows through — then dropped just under the
        # pill so every Flow window still sits in front of it.
        back.attributes("-topmost", True)
        back.update_idletasks()
        back.lower(pill)

    # Both panels freeze their redraw while the pointer is inside them, so chips
    # are never rebuilt under a hand reaching for one. A cursor left parked over
    # the panel freezes every chip row mid-walk — so move it away, and put it
    # back at the end.
    #
    # Away means the bottom-left, not the top-left this used to use. A panel that
    # has been deiconified but not yet positioned sits at 0,0, so 60,60 is *inside*
    # it — and the freeze is what stops `_render` calling `reposition`, so a panel
    # parked under the cursor at the origin never leaves it. `scripts/reel.py`,
    # sampling every 40 ms rather than after a settle, held the conversation card
    # at 0,0 for 31 frames of 223 that way. This walk has been lucky rather than
    # safe: each shot follows a pause long enough for the placement to have already
    # happened before the pointer could matter.
    #
    # Inside the *work area*, so it lands above the taskbar rather than on it — a
    # hover there raises a preview flyout, and this script spends its whole life
    # photographing whatever is on top.
    home = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(home))
    user32.SetCursorPos(pill.work[0] + 8, pill.work[3] - 8)

    steps = build(pill, sess)
    print(f"walking {len(steps)} steps -> {OUT}", flush=True)

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
                traceback.print_exc()
            if isinstance(gate, threading.Event):
                end = time.time() + 120

                def poll():
                    if gate.is_set() or time.time() > end:
                        run(i + 1)
                    else:
                        pill.after(150, poll)
                poll()
            else:
                run(i + 1)

        pill.after(delay, go)

    pill.after(5 * 60 * 1000, pill.quit_app)  # hard stop, whatever happens
    run()
    pill.mainloop()
    print(f"\n{len(_taken)} shots in {OUT}")


if __name__ == "__main__":
    main()
