"""Push-to-talk at the session: what `talk_start` and `talk_end` owe whichever pill calls them.

Ported from `tests/test_talk.py` (decisions.md 2026-11-23, "One surface", stage 2). That
file drives the Classic `Pill`'s own dispatch, and most of what it pins is that pill's -
its paste wait, its two ceilings, its mouse gestures - which goes when the class goes.
These are the assertions in it that were about the session all along: the stream that
lingers after a release, the hold that gives back exactly what it took, and the words a
release commits whether or not anything pastes them. The compact pill calls the same two
methods, so they are asserted here against a real `Session` and no window at all.

The microphone and the decoder are fakes. Each test is the `test_talk.py` case it names,
with the Classic dispatch replaced by the session call that dispatch made.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.session import BLOCK, Session  # noqa: E402


class FakeMic:
    """Counts opens and closes, because the gesture is judged on them (test_talk.py's)."""

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.active = False
        self.dropped = 0
        self.device_name = "fake"
        self._blocks: list[np.ndarray] = []

    def start(self) -> None:
        self.starts += 1
        self.active = True

    def stop(self) -> None:
        self.stops += 1
        self.active = False

    def drain(self) -> list:
        out, self._blocks = self._blocks, []
        return out

    def alive(self) -> bool:
        return self.active


class FakeAsr:
    loading = False
    loaded = False

    def load(self, final=None) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


def let_linger_expire(session: Session) -> None:
    """Wind the lingering stream's clock past `MIC_LINGER_SEC` and pump once."""
    session._linger_until = 0.0
    session.pump_results()


class Talk(unittest.TestCase):
    """A real session over the fakes, and the three moves a hold is made of."""

    def setUp(self) -> None:
        self.mic = FakeMic()
        self.s = Session(asr=FakeAsr(), mic=self.mic)
        self.addCleanup(self.s.close)

    def press(self) -> None:
        # The chord's press is two words, `warm` then `talk`; both pills dispatch them
        # to these two calls.
        self.s.warm()
        self.s.talk_start()

    def speak(self, seconds: float = 1.0) -> None:
        """Put audio in the utterance buffer the way `_pump_audio` would."""
        blocks = max(1, int(seconds * 16000 / BLOCK))
        self.s._utter = [np.zeros(BLOCK, dtype=np.float32)] * blocks

    def notes(self) -> list[str]:
        return [e.text for e in self.s.events() if e.kind == "note"]


class TestTheHoldOpensAndTheReleaseCloses(Talk):
    def test_the_press_opens_the_microphone_and_the_release_stops_reading_it(self):
        self.press()
        self.assertTrue(self.mic.active)
        self.speak()
        self.s.talk_end()
        # Nothing reads it now, but the stream is held open for the next hold
        # (`MIC_LINGER_SEC`), so that one starts at the first word.
        self.assertFalse(self.s._mic_started)
        self.assertTrue(self.s._mic_lingering)
        self.assertTrue(self.mic.active)
        let_linger_expire(self.s)
        self.assertFalse(self.mic.active)
        self.assertFalse(self.s._mic_lingering)

    def test_the_next_hold_reuses_the_stream_the_last_one_left_open(self):
        self.press()
        self.speak()
        self.s.talk_end()
        self.assertEqual(self.mic.starts, 1)
        self.press()
        self.assertEqual(self.mic.starts, 1)
        self.assertEqual(self.mic.stops, 0)
        self.assertTrue(self.s._mic_started)
        self.assertFalse(self.s._mic_lingering)

    def test_what_arrived_while_nobody_was_reading_is_not_the_next_hold(self):
        # Blocks the lingering stream captured between two holds belong to nobody, and
        # the queue's overflow while it was unread is not announced as lost audio.
        self.press()
        self.speak()
        self.s.talk_end()
        self.s.events()
        self.mic._blocks = [np.zeros(BLOCK, dtype=np.float32)] * 5
        self.mic.dropped = 40
        self.press()
        self.assertEqual(self.mic._blocks, [])
        self.s.tick()
        self.assertFalse(any("overflowed" in n for n in self.notes()))

    def test_the_press_warms_before_it_captures(self):
        # The reason the warm is a separate word: the load overlaps the utterance
        # instead of following it.
        self.assertFalse(self.s.asr.loaded)
        self.press()
        self.assertTrue(self.s.asr.loaded)


class TestTheHoldGivesBackExactlyWhatItTook(Talk):
    def test_a_hold_over_an_already_capturing_session_leaves_it_capturing(self):
        # Armed with the toggle hotkey for long-form dictation, then the chord: the
        # release does not switch off the microphone that was turned on another way.
        self.s.start()
        opens = self.mic.starts
        self.press()
        self.assertEqual(self.mic.starts, opens)
        self.speak()
        self.s.talk_end()
        self.assertTrue(self.mic.active)
        self.assertEqual(self.mic.stops, 0)
        self.assertNotIn("disarm", [e.kind for e in self.s.events()])

    def test_and_a_hold_that_opened_it_disarms_and_closes_it(self):
        # `armed` belongs to the surface, so the session asks for it with `disarm`;
        # the Classic harness cleared `armed` on exactly that event.
        self.press()
        self.speak()
        self.s.talk_end()
        self.assertIn("disarm", [e.kind for e in self.s.events()])
        self.assertFalse(self.s._mic_started)
        let_linger_expire(self.s)
        self.assertEqual(self.mic.stops, 1)


class TestWhatWasSaidSurvivesTheRelease(Talk):
    """P2, on the one path with the most reason to cut a corner (test_talk.py's)."""

    def test_the_release_does_not_refuse_the_decode_it_just_asked_for(self):
        before = self.s._capture_generation
        self.press()
        self.speak()
        self.s.talk_end()
        self.assertEqual(self.s._capture_generation, before)

    def test_the_utterance_reaches_the_decoder(self):
        # Committed, not abandoned - and on the break path (`ctrl+win+d`) too, which
        # calls the same `talk_end`: whether the words paste is the surface's question.
        self.press()
        self.speak(2.0)
        self.assertTrue(self.s._utter)
        self.assertTrue(self.s.talk_end())
        self.assertFalse(self.s._utter)
        self.assertTrue(self.s._sent)

    def test_a_hold_nobody_spoke_into_commits_nothing_and_says_nothing(self):
        # The common case for a desktop switch: the gate let nothing through in the
        # 50 ms before the third key, so there is nothing to keep and nothing to say.
        self.press()
        self.assertFalse(self.s.talk_end())
        self.assertFalse(self.s._sent)
        self.assertEqual(self.notes(), [])


class TestNothingIsHeardBetweenHolds(Talk):
    """The stream stays open for a minute after a release so the next hold starts at
    once, and what it delivers in that minute is nobody's (test_talk.py's, as was)."""

    LOUD = np.full(BLOCK, 0.2, dtype=np.float32)

    def test_a_tick_after_the_release_hears_nothing(self):
        s = self.s
        s.talk_start()
        s.talk_end()
        self.assertTrue(s._mic_lingering)
        for _ in range(5):
            self.mic._blocks += [self.LOUD] * 4
            s.tick()
        self.assertEqual(s._utter, [])
        self.assertNotEqual(s.state.value, "listening")
        self.assertEqual(s.draft.text, "")

    def test_the_next_hold_hears_again(self):
        s = self.s
        s.talk_start()
        s.talk_end()
        s.talk_start()
        self.mic._blocks += [self.LOUD] * 4
        s.tick()
        self.assertTrue(s._utter)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
