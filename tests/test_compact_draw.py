"""The compact surface repaints only when the picture has changed.

`_draw` rebuilds every item and hands `UpdateLayeredWindow` a whole bitmap.
Measured on a real window at 300 %: 0.78 ms a frame with the pill alone and
4.53 ms with the panel open — 15 % of the 30 ms budget, spent drawing the same
picture as the frame before. `_draw_key` is the shipped surface's answer
(`Pill._draw_key`, flow/ui.py:4973) brought here.

The fixtures are `test_ui_compact`'s own — `__new__` plus class defaults, never
`__init__` — because what is under test is which frames draw, and a recording
canvas counts that exactly.
"""

import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui_compact as uc  # noqa: E402
from flow.session import CONVERSE, DICTATE, State  # noqa: E402
from test_ui_compact import Canvas, pill, session  # noqa: E402


def drawn(p) -> int:
    """How many shapes are on the recording canvas. The capsule, the meter's
    bars and the mic are all polygons, so the count moves every time the frame
    is drawn and never when it is skipped."""
    return len(p.canvas.polys)


class TestAnUnchangedFrameIsNotDrawnTwice(unittest.TestCase):
    def test_two_identical_frames_draw_once(self):
        p = pill(State.IDLE, armed=True)
        p._frame()
        first = drawn(p)
        self.assertGreater(first, 0)  # it drew at all
        p._frame()
        self.assertEqual(drawn(p), first)

    def test_ten_idle_frames_are_still_one_drawing(self):
        p = pill(State.IDLE, armed=True)
        p._frame()
        first = drawn(p)
        for _ in range(9):
            p._frame()
        self.assertEqual(drawn(p), first)

    def test_the_pump_still_runs_on_a_frame_that_is_not_drawn(self):
        # Only the drawing is skipped. The session is still ticked, its events
        # still drained and the press still pumped — a pill that stopped
        # pulling would be a pill that never noticed anything had changed.
        p = pill(State.IDLE, armed=True)
        p._frame()
        drew = drawn(p)
        p._frame()
        self.assertEqual(drawn(p), drew)
        self.assertEqual(p.session.tick.call_count, 2)
        self.assertEqual(p.session.events.call_count, 2)

    def test_the_first_frame_of_all_is_drawn(self):
        # `_drawn_key` defaults to None, which no key can equal: nothing has
        # been composited yet, whatever the state happens to be.
        p = pill(State.IDLE, armed=True)
        self.assertIsNone(uc.CompactPill._drawn_key)
        p._frame()
        self.assertGreater(drawn(p), 0)


class TestWhatMakesTheNextFrameDraw(unittest.TestCase):
    def redraws(self, p, change) -> None:
        """`change` must put something new on the canvas next frame."""
        p._frame()
        before = drawn(p)
        p._frame()
        self.assertEqual(drawn(p), before, "settled first")
        change()
        p._frame()
        self.assertGreater(drawn(p), before)

    def test_a_level_that_moves_redraws_the_meter(self):
        # Through `level_db`, not `_meter_level`: the pump owns the eased
        # level and rewrites it every frame from the session's own number.
        p = pill(State.LISTENING, armed=True)
        self.redraws(p, lambda: setattr(p.session, "level_db", -20.0))

    def test_a_state_that_lights_the_ring_redraws(self):
        p = pill(State.IDLE, armed=True)
        self.redraws(p, lambda: setattr(p.session, "state", State.LISTENING))

    def test_a_mode_switch_redraws_the_glyph(self):
        p = pill(State.IDLE, armed=True, mode=DICTATE)
        self.redraws(p, lambda: setattr(p.session, "mode", CONVERSE))

    def test_a_notice_appearing_redraws(self):
        p = pill(State.IDLE, armed=True)
        self.redraws(p, lambda: p._say("copied — press Ctrl+V"))

    def test_the_notice_running_out_redraws(self):
        # The frame it reaches zero on is a frame the strip comes off, which
        # is why the countdowns are in the key as booleans.
        p = pill(State.IDLE, armed=True, _notice=2,
                 _notice_text="something worth reading")
        p._frame()
        before = drawn(p)
        p._frame()  # 1 -> 0: the strip goes
        self.assertGreater(drawn(p), before)

    def test_a_resize_redraws(self):
        # What `_sync_shell` leaves behind: it only reaches the painter after
        # `(w, h)` has changed, and it recreates the bitmap when it does — so
        # the shell size being in the key is what forces the frame after a
        # resize to draw onto the new one, with no second mechanism.
        p = pill(State.IDLE, armed=True)

        def resized():
            p._shell_w, p._shell_h = uc.PANEL_W, uc.PANEL_H + uc.PILL_H
        self.redraws(p, resized)

    def test_the_panel_opening_redraws(self):
        p = panelled()

        def open_panel():
            p._panel_open = True
            p._panel_mode = CONVERSE
        self.redraws(p, open_panel)

    def test_an_answer_arriving_in_the_panel_redraws(self):
        p = panelled(_panel_open=True, _panel_mode=CONVERSE,
                     _panel_heard="a question")
        self.redraws(p, lambda: setattr(p, "_panel_result", "an answer"))


def panelled(**attrs):
    """A fixture whose open panel does not poll the *test runner's* mouse —
    `_outside_click_now` is two live Win32 reads, and a button held anywhere
    on this machine while the suite runs would close the panel mid-test."""
    p = pill(State.IDLE, armed=True, **attrs)
    p._outside_click_now = mock.Mock(return_value=False)
    return p


class TestComingBackFromTheTray(unittest.TestCase):
    """A remapped layered window shows nothing until it is presented again,
    and hiding changes no key — so `show_from_tray` clears it by hand. The
    box learned the same thing on `<Map>` (`_open_box`)."""

    def hidden(self):
        p = pill(State.IDLE, armed=True)
        p.deiconify = mock.Mock()
        p.lift = mock.Mock()
        p.geometry = mock.Mock()
        p._hidden = True
        return p

    def test_the_next_frame_after_a_show_draws(self):
        p = self.hidden()
        p._hidden = False
        p._frame()
        before = drawn(p)
        p._frame()
        self.assertEqual(drawn(p), before, "settled first")
        p._hidden = True
        p.show_from_tray()
        p._frame()
        self.assertGreater(drawn(p), before)

    def test_showing_clears_the_key_itself(self):
        p = self.hidden()
        p._drawn_key = ("whatever", "was", "on", "screen")
        p.show_from_tray()
        self.assertIsNone(p._drawn_key)
        p.deiconify.assert_called_once_with()

    def test_a_window_that_was_never_hidden_is_left_alone(self):
        # Idempotent, like every other show/close on this surface: the tray
        # queue can hand the same SHOW twice.
        p = self.hidden()
        p._hidden = False
        p._drawn_key = ("a", "drawn", "frame")
        p.show_from_tray()
        self.assertEqual(p._drawn_key, ("a", "drawn", "frame"))
        p.deiconify.assert_not_called()


class TestTheClassDefaultsAKeyNeeds(unittest.TestCase):
    """The key is built from the same reads the drawing makes, so anything
    `_draw` can be given on a `__new__` fixture the key can be given too —
    `TestTheClassDefaultsADrawNeeds`'s rule, one method along."""

    def test_a_bare_instance_can_be_keyed(self):
        p = uc.CompactPill.__new__(uc.CompactPill)
        p.paint = p.canvas = Canvas()
        p.session = session()
        key = p._draw_key()
        self.assertIsInstance(key, tuple)
        # And it is the key of what a bare fixture actually draws: at rest,
        # with no ring.
        self.assertEqual(key[0], "")

    def test_the_key_is_hashable_and_comparable(self):
        # It is compared with `==` every frame and never mutated; a list or a
        # set in it would make an unchanged frame look changed.
        p = uc.CompactPill.__new__(uc.CompactPill)
        p.paint = p.canvas = Canvas()
        p.session = session()
        self.assertEqual(p._draw_key(), p._draw_key())
        hash(p._draw_key())

    def test_every_attribute_the_key_reads_is_a_class_attribute(self):
        for name in ("_drawn_key", "armed", "_flash", "_recover", "_mic_gone",
                     "_meter_level", "_panel_open", "_panel_mode",
                     "_panel_heard", "_panel_heard_final", "_panel_result",
                     "_panel_failed", "_notice", "_notice_text", "_notice_w",
                     "_shell_w", "_shell_h"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(uc.CompactPill, name), name)


if __name__ == "__main__":
    unittest.main()
