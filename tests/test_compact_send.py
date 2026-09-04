"""The compact release's wait: what arms it, what fires it, what it says.

The shipped surface solved this shape once and wrote down why
(`Pill._talk_end` and `_pump_talk`, flow/ui.py:2803-2877). This file pins the
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
