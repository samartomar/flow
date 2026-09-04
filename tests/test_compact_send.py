"""The compact release's wait: what arms it, what fires it, what it says.

The shipped surface solved this shape once and wrote down why
(`Pill._talk_end` / `_pump_talk` / `_fast_tick`, flow/ui.py:2803-2877 and
4415-4460; decisions.md 2026-09-01, the felt-latency pass). This file pins the
same contract for `CompactPill`, against the two ways the compact surface got
it wrong: a release whose decode had *already* landed armed nothing, and a
release whose decode was still landing fired on the first half of it.

The fixtures are `test_ui_compact`'s own — imported the way that file imports
`FakeMenu` from `test_menu`, so the session Mock, the recording `Canvas` and
the `__new__`-built pill are one idiom across both files rather than two.
"""

import time
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui_compact as uc  # noqa: E402
from flow.session import CONVERSE, Event, REFINE, State  # noqa: E402
from test_ui_compact import panel_pill, pill, session  # noqa: E402


def sending_pill(s, sent, problem=""):
    """A pill whose `on_send` records what it was asked to paste — the same
    helper `TestTypeSendsEndToEnd` uses, over a session the caller owns."""
    p = pill(on_send=lambda text, target=None: sent.append(text) or problem)
    p.session = s
    return p


class TestAReleaseAfterAPauseStillPastes(unittest.TestCase):
    """The canvas's opening line — "Hold the pill. Speak. Let go."
    (design/compact/README.md) — for the hold that has a pause in it.

    `Gate`'s 800 ms hangover closes mid-hold whenever the speaker pauses, so
    `_finalise` runs, the final decodes, and the `draft` event arrives while
    the button is still down. At the release `talk_end` finds `_utter` empty
    and reports False. Believing it alone left the words in the draft and
    nothing pasted, said or shown: "push to talk does nothing", which is the
    exact class of report this surface has drawn six times.
    """

    def test_a_release_after_a_trailing_pause_pastes_exactly_once(self):
        sent = []
        s = session(state=State.LISTENING)
        s.send.return_value = "make the pill not show any controls"
        p = sending_pill(s, sent)
        p._talk_start()
        # The pause: the gate closed, the decode landed, and the event arrives
        # with the button still down.
        s.draft.text = "make the pill not show any controls"
        s.events.return_value = [
            Event("draft", "make the pill not show any controls")]
        p._pump_events()
        p._pump_send()
        self.assertEqual(sent, [])  # nothing is armed yet: this is mid-hold
        # The release. `_utter` is empty, so there is nothing "in flight" —
        # and the words are on `session.draft`, which is the other witness.
        s.events.return_value = []
        s.talk_end.return_value = False
        p._talk_end(send=True)
        self.assertTrue(p._send_pending)
        for _ in range(5):
            p._pump_events()
            p._pump_send()
        self.assertEqual(sent, ["make the pill not show any controls"])
        s.send.assert_called_once_with()
        self.assertFalse(p._send_pending)
        self.assertIsNone(p._send_since)

    def test_an_ask_release_after_a_trailing_pause_still_asks(self):
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p._talk_start()
        p.session.draft.text = "where does the pill decide?"
        p.session.events.return_value = [
            Event("draft", "where does the pill decide?")]
        p._pump_events()
        p._pump_send()
        p.session.send.assert_not_called()
        p.session.events.return_value = []
        p.session.talk_end.return_value = False
        p._talk_end(send=True)
        self.assertTrue(p._ask_pending)
        # The band the hold raised stays up: there are words, so this is not
        # the silent hold States.dc.html takes back down.
        self.assertTrue(p._panel_open)
        p._pump_send()
        p.session.send.assert_called_once_with()
        self.assertEqual(p._panel_heard, "where does the pill decide?")
        self.assertTrue(p._panel_heard_final)
        self.assertFalse(p._ask_pending)


class TestASplitUtteranceGoesWhole(unittest.TestCase):
    """A hold long enough to queue two finals is one utterance, and P2's
    "nothing spoken is ever dropped" is about all of it.

    `session.busy` is the condition — "is the decoder still working", the
    question `Session.busy` (flow/session.py:1272) exists to answer for exactly
    this paste.
    """

    def test_the_wait_holds_for_the_decoder_and_pastes_the_whole_draft(self):
        sent = []
        s = session(state=State.LISTENING, busy=True)
        p = sending_pill(s, sent)
        s.talk_end.return_value = True
        p._talk_end(send=True)
        self.assertTrue(p._send_pending)
        # The first final of two. Firing here pasted half a sentence and
        # stranded the rest in a draft nothing came back for.
        s.draft.text = "first half"
        s.events.return_value = [Event("draft", "first half")]
        p._pump_events()
        p._pump_send()
        self.assertEqual(sent, [])
        self.assertTrue(p._send_pending)
        # The second lands and the queue drains.
        s.busy = False
        s.draft.text = "first half and the rest of it"
        s.send.return_value = "first half and the rest of it"
        s.events.return_value = [Event("draft", "first half and the rest of it")]
        p._pump_events()
        p._pump_send()
        self.assertEqual(sent, ["first half and the rest of it"])
        s.send.assert_called_once_with()

    def test_a_refine_release_waits_out_the_decoder_too(self):
        p = panel_pill(State.LISTENING, mode=REFINE)
        p._talk_start()
        p.session.talk_end.return_value = True
        p.session.busy = True
        p._talk_end(send=True)
        self.assertTrue(p._ask_pending)
        p.session.draft.text = "the first half"
        p._pump_send()
        # Half a prompt is not a prompt: the CLI gets the whole draft or waits.
        p.session.send.assert_not_called()
        p.session.busy = False
        p.session.draft.text = "the first half and the rest of it"
        p._pump_send()
        p.session.send.assert_called_once_with()
        self.assertEqual(p._panel_heard, "the first half and the rest of it")

    def test_the_heard_block_shows_the_draft_not_the_last_event(self):
        # `_last_draft` is the last *event*, which on a split utterance is only
        # its second half. The panel shows what the CLI was handed.
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p._ask_pending = True
        p._last_draft = "and the rest of it"
        p.session.draft.text = "the first half and the rest of it"
        p._pump_send()
        self.assertEqual(p._panel_heard, "the first half and the rest of it")


class TestTheWaitEndsWithoutPasting(unittest.TestCase):
    """The two ways a wait ends with nothing sent: silence, and the ceiling.

    Silence is a normal thing to do with a push-to-talk button (States.dc.html,
    third case: straight back to grey, no panel, no toast). The ceiling is
    `PTT_PASTE_WAIT_SEC` — flow/ui.py:1050-1060's number and its rule, that the
    behaviour there is not a discard.
    """

    def test_an_empty_draft_at_fire_time_ends_the_wait_silently(self):
        sent = []
        s = session(state=State.LISTENING)
        p = sending_pill(s, sent)
        s.talk_end.return_value = True
        p._talk_end(send=True)
        s.draft.text = "   "  # the gate opened on a cough
        p._pump_send()
        self.assertFalse(p._send_pending)
        self.assertIsNone(p._send_since)
        s.send.assert_not_called()
        self.assertEqual(sent, [])
        # No toast and no flash: nothing went wrong.
        self.assertEqual(p._notice, 0)
        self.assertEqual(p._flash, 0)

    def test_the_ceiling_says_so_on_the_strip_and_keeps_the_words(self):
        sent = []
        s = session(state=State.LISTENING, busy=True)
        p = sending_pill(s, sent)
        s.talk_end.return_value = True
        with mock.patch.object(uc.time, "perf_counter", return_value=100.0):
            p._talk_end(send=True)
        s.draft.text = "a long thing the decoder is still chewing on"
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=100.0 + uc.PTT_PASTE_WAIT_SEC - 0.1):
            p._pump_send()
        self.assertTrue(p._send_pending)  # under the ceiling: still waiting
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=100.0 + uc.PTT_PASTE_WAIT_SEC):
            p._pump_send()
        self.assertFalse(p._send_pending)
        # Never a silent give-up (P2), and never a late paste.
        self.assertIn("still decoding", p._notice_text)
        self.assertEqual(p._notice, uc.COPIED_FRAMES)
        self.assertEqual(sent, [])
        s.send.assert_not_called()
        self.assertEqual(s.draft.text,
                         "a long thing the decoder is still chewing on")

    def test_the_send_hotkey_during_a_wait_does_not_paste_twice(self):
        # `_send` is the one choke point, and clearing the wait there is what
        # covers every collision at once (flow/ui.py:3781-3793).
        sent = []
        s = session(state=State.LISTENING, draft_text="the words")
        s.send.return_value = "the words"
        p = sending_pill(s, sent)
        s.talk_end.return_value = True
        p._talk_end(send=True)
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["send"]
        p._drain_hotkeys()
        self.assertEqual(sent, ["the words"])
        self.assertFalse(p._send_pending)
        self.assertIsNone(p._send_since)
        # The draft went with them; the pump has nothing left to fire.
        s.draft.text = ""
        p._pump_send()
        s.send.assert_called_once_with()
        self.assertEqual(sent, ["the words"])

    def test_the_send_hotkey_clears_an_armed_ask_as_well(self):
        # In a panel mode the hotkey has already put the draft to the CLI; an
        # ask still armed behind it would ask the emptied draft.
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p.session.draft.text = "a question"
        p.session.send.return_value = ""  # converse asks and returns nothing
        p._ask_pending = True
        p._send_since = time.perf_counter()
        p._send()
        self.assertFalse(p._ask_pending)
        self.assertIsNone(p._send_since)
        p.session.draft.text = ""
        p._pump_send()
        p.session.send.assert_called_once_with()

    def test_a_silent_hold_does_not_paste_what_a_break_kept_back(self):
        # `ctrl+win+d` commits the words and deliberately does not paste them
        # into whatever window the desktop switch moved to. A later hold with
        # nothing said into it is not the gesture that changes that — which is
        # why the release measures what the draft *gained*, not whether it is
        # empty.
        sent = []
        s = session(state=State.LISTENING, draft_text="what the break kept")
        p = sending_pill(s, sent)
        p._talk_start()
        s.talk_end.return_value = False  # nothing was said into this one
        p._talk_end(send=True)
        self.assertFalse(p._send_pending)
        p._pump_send()
        self.assertEqual(sent, [])
        s.send.assert_not_called()
        # And the hold that does say something takes them all.
        p._talk_start()
        s.draft.text = "what the break kept, and the rest"
        s.send.return_value = "what the break kept, and the rest"
        s.talk_end.return_value = True
        p._talk_end(send=True)
        p._pump_send()
        self.assertEqual(sent, ["what the break kept, and the rest"])

    def test_a_new_hold_supersedes_the_wait_and_keeps_the_words(self):
        sent = []
        s = session(state=State.LISTENING)
        p = sending_pill(s, sent)
        s.talk_end.return_value = True
        p._talk_end(send=True)
        self.assertTrue(p._send_pending)
        p._talk_start()
        self.assertFalse(p._send_pending)
        self.assertIsNone(p._send_since)
        # Not dropped: the wait was only the paste. The words stay in the
        # draft, and this hold's own release sends them all.
        s.draft.text = "what was said before"
        p._pump_send()
        s.send.assert_not_called()
        self.assertEqual(sent, [])

    def test_the_waits_attributes_are_class_attributes(self):
        # The same rule as `_draw`'s attributes: only a class attribute never
        # reaches `tk.Misc.__getattr__` on a bare fixture.
        self.assertIsNone(uc.CompactPill._send_since)
        self.assertEqual(uc.CompactPill._draft_at_hold, "")


class TestABrokenFrameStillRepaints(unittest.TestCase):
    """NEEDS_YOU.md's "an exception in the frame pump leaves the row painted at
    the last width, under a window that has already been resized" — the
    compact half of it, where the layered path makes it worse: nothing is on
    screen but the last presented bitmap until a frame succeeds.
    """

    def broken(self, **attrs):
        p = panel_pill(State.LISTENING, mode=CONVERSE, **attrs)
        p.after = mock.Mock()
        p._pump_events = mock.Mock(side_effect=RuntimeError("the pump fell over"))
        return p

    def test_a_frame_whose_pump_raises_still_draws(self):
        p = self.broken()
        with mock.patch.object(uc.traceback, "print_exc") as printed:
            p._tick()
        printed.assert_called_once_with()
        self.assertEqual(p._flash, uc.FLASH_FRAMES)
        # The capsule reached the canvas: the frame's last line ran after all.
        self.assertTrue(p.canvas.polys)
        self.assertTrue(any(fill == uc.SHELL for _c, fill, _o in p.canvas.polys))
        p.after.assert_called_once_with(30, p._tick)

    def test_a_draw_that_also_raises_leaves_the_clock_running(self):
        p = self.broken()
        p._draw = mock.Mock(side_effect=RuntimeError("and the painter, too"))
        with mock.patch.object(uc.traceback, "print_exc"):
            p._tick()  # must not raise, must not recurse
        p._draw.assert_called_once_with()
        # One dead frame is a stale pill; a broken `after` chain is a dead one.
        p.after.assert_called_once_with(30, p._tick)


class TestTheFastClock(unittest.TestCase):
    """`_fast_tick` / `_quicken`, `Pill`'s (flow/ui.py:4415-4460) on this
    surface: the release and the decode landing are acted on in 5 ms rather
    than at the next 30 ms repaint — the 2026-09-01 felt-latency pass's
    measurement, and the reason it refused to leave them on the frame."""

    def quick(self, s, sent=None):
        p = sending_pill(s, sent if sent is not None else [])
        p.after = mock.Mock()
        p._fast_ticking = True
        return p

    def test_the_wait_fires_between_frames(self):
        sent = []
        s = session(state=State.LISTENING, draft_text="the words")
        s.send.return_value = "the words"
        p = self.quick(s, sent)
        p._send_pending = True
        p._send_since = time.perf_counter()
        p._fast_tick()
        self.assertEqual(sent, ["the words"])
        s.pump_results.assert_called_once_with()
        # Nothing left in flight: the clock stops rather than idling.
        p.after.assert_not_called()
        self.assertFalse(p._fast_ticking)

    def test_it_pumps_the_session_before_it_looks_at_the_draft(self):
        order = []
        s = session(state=State.LISTENING)
        s.pump_results.side_effect = lambda: order.append("pump_results")
        p = self.quick(s)
        p._send_pending = True
        p._pump_events = lambda: order.append("_pump_events")
        p._pump_send = lambda: order.append("_pump_send")
        p._fast_tick()
        self.assertEqual(order, ["pump_results", "_pump_events", "_pump_send"])

    def test_a_busy_decoder_is_left_alone_and_the_clock_keeps_running(self):
        sent = []
        s = session(state=State.LISTENING, busy=True, draft_text="the words")
        p = self.quick(s, sent)
        p._send_pending = True
        p._send_since = time.perf_counter()
        p._fast_tick()
        s.pump_results.assert_not_called()
        s.send.assert_not_called()
        self.assertEqual(sent, [])
        p.after.assert_called_once_with(uc.FAST_TICK_MS, p._fast_tick)
        self.assertTrue(p._fast_ticking)

    def test_it_drains_the_hotkeys_that_end_the_hold(self):
        sent = []
        s = session(state=State.LISTENING, draft_text="the words")
        s.talk_end.return_value = True
        s.send.return_value = "the words"
        p = self.quick(s, sent)
        p._press_talking = True
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["talk-end"]
        p._fast_tick()
        s.talk_end.assert_called_once_with()
        # The release and the paste inside one 5 ms tick, which is the whole
        # of what this clock buys: neither waited for a repaint.
        self.assertEqual(sent, ["the words"])

    def test_a_hold_keeps_the_clock_and_an_idle_pill_stops_it(self):
        p = self.quick(session())
        p._press_talking = True
        p._fast_tick()
        p.after.assert_called_once_with(uc.FAST_TICK_MS, p._fast_tick)
        p._press_talking = False
        p.after.reset_mock()
        p._fast_tick()
        p.after.assert_not_called()
        self.assertFalse(p._fast_ticking)

    def test_a_quit_books_no_next_tick(self):
        p = self.quick(session())
        p._press_talking = True
        p._alive = False
        p._fast_tick()
        p.after.assert_not_called()
        self.assertFalse(p._fast_ticking)

    def test_an_exception_flashes_and_the_clock_survives_it(self):
        p = self.quick(session())
        p._press_talking = True
        p._drain_hotkeys = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(uc.traceback, "print_exc") as printed:
            p._fast_tick()
        printed.assert_called_once_with()
        self.assertEqual(p._flash, uc.FLASH_FRAMES)
        p.after.assert_called_once_with(uc.FAST_TICK_MS, p._fast_tick)

    def test_the_hold_and_the_release_both_start_the_clock(self):
        s = session(state=State.LISTENING)
        s.talk_end.return_value = True
        p = self.quick(s)
        p._fast_ticking = False
        p._talk_start()
        p.after.assert_called_once_with(uc.FAST_TICK_MS, p._fast_tick)
        self.assertTrue(p._fast_ticking)
        p._fast_ticking = False
        p.after.reset_mock()
        p._talk_end(send=True)
        p.after.assert_called_once_with(uc.FAST_TICK_MS, p._fast_tick)

    def test_quicken_starts_one_clock_and_only_one(self):
        p = self.quick(session())
        p._fast_ticking = False
        p._quicken()
        p._quicken()
        p.after.assert_called_once_with(uc.FAST_TICK_MS, p._fast_tick)
        self.assertTrue(p._fast_ticking)

    def test_quicken_on_a_bare_fixture_does_nothing(self):
        # The RecursionError guard this module's class defaults exist for: a
        # `__new__`-built pill has no clock and no `after`, and `getattr` here
        # would go looking for both through `tk.Misc.__getattr__`.
        p = pill()
        self.assertNotIn("_fast_ticking", p.__dict__)
        p._quicken()
        self.assertNotIn("_fast_ticking", p.__dict__)

    def test_the_real_constructor_puts_the_flag_where_quicken_looks(self):
        # `_quicken` reads `__dict__`, which never sees a class attribute — so
        # the class default alone would leave the clock unstartable on a real
        # window. Read off the constructor rather than by building one: a real
        # Tk window is what this whole fixture idiom exists to avoid.
        self.assertIn("_fast_ticking",
                      uc.CompactPill.__init__.__code__.co_names)

    def test_the_clocks_own_flag_is_a_class_attribute_too(self):
        # Read by `_fast_tick`'s `finally` on a fixture that never had an
        # `__init__` to set it — the same guard as every default above it.
        self.assertFalse(uc.CompactPill._fast_ticking)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
