"""The compact pill's whole vocabulary: two colours, a meter, three gestures.

Everything here goes through `CompactPill._draw` and `_frame` on a fake canvas
and a fake session rather than through a real window, for the reason
`test_pill.py` does: a desktop is expensive and both methods are pure — given
a session state and a press, they write a fixed set of shapes and make a fixed
set of calls. The fixture idiom is test_pill's own: `__new__` plus class
defaults, never `__init__`.

Pinned: the glyph tint per mode, the ring colour per state, tap vs hold, the
class-attribute defaults `_draw` depends on, and the pump's pull contract.
"""

import time
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.ui_compact as uc  # noqa: E402
from flow.session import CONVERSE, DICTATE, State  # noqa: E402


class Canvas:
    """Records the primitives `CompactPill._draw` uses, with their geometry.

    The same shape test_pill's fake has — `polys`, `items` of ovals, rects,
    arcs, lines, and the `bindings` a `tag_bind` would make — so either pill
    can be drawn onto it. Rects record their outline too: the ring is the one
    thing this pill draws as a stroke, and it is the thing half these tests
    assert on.
    """

    def __init__(self) -> None:
        self.ovals: list[tuple[float, float, float, float, str]] = []
        self.rects: list[tuple[float, float, float, float, str, str]] = []
        self.lines: list[tuple[tuple, str]] = []
        self.arcs: list[tuple] = []
        self.polys: list[tuple] = []
        self.bindings: list[tuple] = []

    def delete(self, *a, **kw) -> None: ...

    def tag_bind(self, tag, sequence, callback) -> None:
        self.bindings.append((tag, sequence, callback))

    def create_oval(self, x1, y1, x2, y2, **kw) -> None:
        self.ovals.append((x1, y1, x2, y2, kw.get("fill", "")))

    def create_rectangle(self, x1, y1, x2, y2, **kw) -> None:
        self.rects.append(
            (x1, y1, x2, y2, kw.get("fill", ""), kw.get("outline", "")))

    def create_line(self, *a, **kw) -> None:
        self.lines.append((a, kw.get("fill", "")))

    def create_arc(self, *a, **kw) -> None:
        self.arcs.append((a, kw.get("outline", "")))

    def create_polygon(self, *a, **kw) -> None:
        self.polys.append((a, kw.get("fill", ""), kw.get("outline", "")))


def session(mode=DICTATE, state=State.IDLE, hearing=True, busy=False,
            level_db=-120.0, draft_text=""):
    """A session Mock with real values for everything the pill reads.

    The values are set rather than left as auto-created Mocks for test_pill's
    reason: `not Mock()` is `False`, so a bare Mock would silently answer
    "yes, hearing" and no rest-state test here could ever fail. `events`
    returns a real list, because `_pump_events` iterates it.
    """
    s = mock.Mock(mode=mode, state=state, hearing=hearing, busy=busy,
                  level_db=level_db)
    s.draft = mock.Mock(text=draft_text)
    s.events.return_value = []
    return s


def pill(state=State.IDLE, *, armed=True, mode=DICTATE, **attrs):
    """A compact pill with a fake canvas and no Tk, built the way
    test_pill builds one: `__new__`, so every attribute `_draw` reads has to
    come from a class default or from here."""
    p = uc.CompactPill.__new__(uc.CompactPill)
    p.canvas = Canvas()
    p.armed = armed
    p.session = session(state=state, mode=mode)
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


def rings(p) -> list[str]:
    """The outlines drawn this frame — the ring is the only stroked polygon."""
    return [outline for *_g, outline in p.canvas.polys if outline]


def shell_fill(p) -> str:
    """The capsule body's fill: the one filled polygon, under everything else."""
    (body,) = [fill for _a, fill, outline in p.canvas.polys if not outline]
    return body


def glyph_fill(p) -> str:
    """The mic capsule's fill: the pill's only oval."""
    (only,) = p.canvas.ovals
    return only[4]


class TestTheGlyphCarriesTheMode(unittest.TestCase):
    def test_type_is_white(self):
        p = pill(State.LISTENING, mode=DICTATE)
        p._draw()
        self.assertEqual(glyph_fill(p), uc.MODE_TINT[DICTATE])
        # White, as the README's "white Type" says — ui.py's own near-white.
        self.assertEqual(uc.MODE_TINT[DICTATE], uc.TEXT)

    def test_ask_is_violet(self):
        p = pill(State.LISTENING, mode=CONVERSE)
        p._draw()
        self.assertEqual(glyph_fill(p), uc.MODE_TINT[CONVERSE])
        self.assertEqual(uc.MODE_TINT[CONVERSE], "#B48EF5")

    def test_refines_gold_is_declared_but_nowhere_on_the_map(self):
        # The session has two modes; the spec's third hue waits for it.
        self.assertEqual(uc.REFINE_GOLD, "#E1B75C")
        self.assertNotIn(uc.REFINE_GOLD, uc.MODE_TINT.values())


class TestTheRingCarriesTheState(unittest.TestCase):
    def test_hearing_is_green(self):
        p = pill(State.LISTENING)
        p._draw()
        self.assertEqual(rings(p), ["#3ECF8E"])

    def test_a_cli_out_is_blue(self):
        for state in (State.REFINING, State.ASKING):
            with self.subTest(state=state):
                p = pill(state)
                p._draw()
                self.assertEqual(rings(p), ["#7AA2F7"])

    def test_an_error_is_red_whatever_the_state(self):
        p = pill(State.LISTENING, _flash=uc.FLASH_FRAMES)
        p._draw()
        self.assertEqual(rings(p), ["#F2584A"])

    def test_rest_is_no_ring(self):
        for state in (State.IDLE, State.DRAFT):
            with self.subTest(state=state):
                p = pill(state)
                p._draw()
                self.assertEqual(rings(p), [])

    def test_disarmed_is_rest_whatever_the_session_thinks(self):
        p = pill(State.LISTENING, armed=False)
        p._draw()
        self.assertEqual(rings(p), [])


class TestTheCapsuleIsFilled(unittest.TestCase):
    """The body is drawn, not just the furniture on it.

    `scripts/compact_shots.py` caught the version without it: `-transparentcolor`
    keys the canvas background out, and on Windows a keyed pixel is click-through —
    the pill was a glyph and some bars floating over the desktop, and the
    right-click meant for the menu fell through to whatever was behind.
    """

    def test_the_shell_covers_the_pill(self):
        p = pill(State.IDLE, armed=False)
        p._draw()
        self.assertEqual(shell_fill(p), uc.SHELL)


class TestTapAndHoldShareOneButton(unittest.TestCase):
    def test_a_tap_cycles_the_mode(self):
        p = pill()
        p._on_press()
        p._on_release()
        p.session.toggle_mode.assert_called_once_with()
        p.session.talk_start.assert_not_called()
        p.session.talk_end.assert_not_called()

    def test_a_hold_talks(self):
        p = pill()
        with mock.patch.object(uc.time, "perf_counter", return_value=100.0):
            p._on_press()
        # Past the threshold, the next frame turns the press into an
        # utterance — the frame is the only clock, not an `after` timer.
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=100.0 + uc.PILL_HOLD_SEC + 0.01):
            p._pump_press()
        p.session.talk_start.assert_called_once_with()
        p._on_release()
        p.session.talk_end.assert_called_once_with()
        p.session.toggle_mode.assert_not_called()

    def test_a_short_press_the_frame_never_saw_is_a_tap(self):
        p = pill()
        p._on_press()
        p._pump_press()  # inside the threshold: nothing happens
        p.session.talk_start.assert_not_called()
        p._on_release()
        p.session.toggle_mode.assert_called_once_with()

    def test_a_drag_is_neither(self):
        p = pill()
        p._on_press(mock.Mock(x_root=0, y_root=0))
        p._on_motion(mock.Mock(x_root=uc.PILL_DRAG_SLOP + 1, y_root=0))
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=time.perf_counter() + uc.PILL_HOLD_SEC + 0.01):
            p._pump_press()
        p.session.talk_start.assert_not_called()
        p._on_release()
        p.session.toggle_mode.assert_not_called()


class TestTheClassDefaultsADrawNeeds(unittest.TestCase):
    """Every attribute `_draw` reads must exist on the class, so a fixture
    built with `__new__` draws instead of recursing through `tk.Misc.__getattr__`
    into `self.tk` — the RecursionError flow/ui.py:2345 cites."""

    def test_a_bare_instance_draws_the_resting_pill(self):
        p = uc.CompactPill.__new__(uc.CompactPill)
        p.canvas = Canvas()
        p.session = session()
        p._draw()
        # Rest: no ring, and the meter is there in its muted shade.
        self.assertEqual(rings(p), [])
        bars = [r for r in p.canvas.rects if not r[5]]
        self.assertEqual(len(bars), uc.BARS)
        self.assertTrue(all(b[4] == uc.MUTED for b in bars))

    def test_every_drawn_attribute_is_a_class_attribute(self):
        for name in ("armed", "_flash", "_meter_level", "_eased_level",
                     "lite", "hotkeys", "on_send", "_press_at", "_press_xy",
                     "_press_moved", "_press_talking", "_menu", "_alive",
                     "no_activate"):
            with self.subTest(name=name):
                # On the class, not only assigned in `__init__` — an
                # instance-only attribute is exactly the RecursionError case.
                self.assertTrue(hasattr(uc.CompactPill, name), name)


class TestThePumpPulls(unittest.TestCase):
    def test_armed_ticks_disarmed_collects_and_both_drain(self):
        p = pill(State.LISTENING, armed=True)
        p._frame()
        p.session.tick.assert_called_once_with()
        p.session.pump_results.assert_not_called()
        p.session.events.assert_called_once_with()

        p2 = pill(State.IDLE, armed=False)
        p2._frame()
        p2.session.pump_results.assert_called_once_with()
        p2.session.tick.assert_not_called()
        p2.session.events.assert_called_once_with()

    def test_an_error_event_flashes_the_ring_red(self):
        s = session(state=State.IDLE)
        from flow.session import Event
        s.events.return_value = [Event("error", "no microphone")]
        p = pill(armed=False)
        p.session = s
        p._frame()
        self.assertEqual(p._flash, uc.FLASH_FRAMES - 1)  # one frame counted down
        self.assertEqual(p._ring_colour(), "#F2584A")

    def test_a_disarm_event_stops_the_pill_claiming_armed(self):
        from flow.session import Event
        s = session(state=State.IDLE)
        s.events.return_value = [Event("disarm", "")]
        p = pill(armed=False)
        p.session = s
        p.armed = True
        p._frame()
        self.assertFalse(p.armed)

    def test_the_hotkey_queue_is_drained_like_the_full_pills(self):
        p = pill()
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["warm", "talk", "talk-end", "mode"]
        self.assertTrue(p._drain_hotkeys())
        p.session.warm.assert_called_once_with()
        p.session.talk_start.assert_called_once_with()
        p.session.talk_end.assert_called_once_with()
        p.session.toggle_mode.assert_called_once_with()

    def test_no_hotkeys_is_a_fine_answer(self):
        p = pill()
        self.assertIsNone(p.hotkeys)
        self.assertTrue(p._drain_hotkeys())


if __name__ == "__main__":
    unittest.main()
