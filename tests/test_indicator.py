"""What Flow is doing right now, and whether it can still hear.

Two things are pinned here. The first is a defect: the level meter is driven by
`Mic._level`, which the PortAudio callback writes on every block it receives — and it
knows nothing about the echo guard in `_pump_audio`. So while a converse-mode reply
played, the guard discarded every block *and the eighteen bars kept dancing to Flow's
own voice*, which is the pill's way of saying "I am hearing you" at the one moment it
was guaranteed not to be. Measured before the fix: 30 blocks discarded, meter at 83% of
full scale.

The second is the indicator itself. `Session.activity` is a single value read every
frame rather than an event, because a wait has no edges — it is a condition that holds
for a while — and the states it covers (a decode, a model load, a CLI call, a reply
playing) were previously invisible or, in the speaking case, actively misreported.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.asr import WhisperTranscriber  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.session import DEAF_DB, Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)

#: What the pill maps onto its eighteen bars. Duplicated from `flow.ui` on purpose:
#: importing it would pull tkinter into a headless test run.
DB_FLOOR, DB_CEIL = -58.0, -12.0


def bar_height(db: float) -> float:
    """0.0 is a flat line, 1.0 is a full-height bar."""
    return max(0.0, min(1.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))


class FakeMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        #: Loud, and it stays loud: a real mic keeps reporting the room even when
        #: nobody is reading its blocks.
        self.level_db = -20.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeAsr:
    loading = False

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return "" if not final else "how do I widen a column"


class SlowAsr(FakeAsr):
    """Blocks inside `text` so a decode can be observed while it is still running."""

    def __init__(self) -> None:
        self.release = False

    def text(self, audio, *, final=False, hotwords="") -> str:
        while not self.release:
            time.sleep(0.005)
        return "widen a column"


class FakeSpeaker:
    def __init__(self) -> None:
        self.speaking = False

    def say(self, text: str) -> bool:
        self.speaking = True
        return True

    def stop(self) -> None:
        self.speaking = False


def session(**kw) -> Session:
    return Session(asr=kw.pop("asr", None) or FakeAsr(), mic=FakeMic(), **kw)


class TestTheMeterDoesNotClaimToHear(unittest.TestCase):
    """The defect. The bars are the only thing on screen that answers "am I being
    heard", and while Flow talks the honest answer is no."""

    def test_the_level_is_the_microphone_when_nothing_is_playing(self):
        s = session(speaker=FakeSpeaker())
        self.assertEqual(s.level_db, -20.0)
        self.assertGreater(bar_height(s.level_db), 0.5)

    def test_the_level_reads_silent_while_a_reply_plays(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        sp.say("Yes, we can hear you.")
        self.assertEqual(s.level_db, DEAF_DB)
        self.assertEqual(bar_height(s.level_db), 0.0)

    def test_the_meter_agrees_with_the_blocks_actually_being_thrown_away(self):
        # The two halves of the same fact, which is what came apart: the guard was
        # already discarding audio and the meter was already animating to it.
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.start()
        sp.say("Yes, we can hear you.")
        s.mic._blocks.extend([LOUD] * 30)
        s.tick()
        self.assertEqual(s.echo_blocks, 30, "the guard did not discard anything")
        self.assertEqual(bar_height(s.level_db), 0.0,
                         "every block was discarded and the meter still moved")

    def test_the_meter_comes_back_when_the_reply_ends(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        sp.say("a long answer")
        sp.speaking = False
        self.assertEqual(s.level_db, -20.0)

    def test_a_session_with_no_speech_engine_always_hears(self):
        s = session()
        self.assertTrue(s.hearing)
        self.assertEqual(s.level_db, -20.0)


class TestWhatFlowIsDoing(unittest.TestCase):
    def test_nothing_to_report_when_idle(self):
        self.assertIsNone(session().activity)

    def test_nothing_to_report_for_a_held_draft(self):
        # Already said by the pill's colour and by the countdown on the Ask button. An
        # indicator that is always on is one nobody reads.
        s = session()
        s.draft.set("the deploy failed")
        s._set_state(State.DRAFT)
        self.assertIsNone(s.activity)

    def test_a_reply_playing_says_it_is_not_listening(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        sp.say("Word Error Rate.")
        act = s.activity
        self.assertIn("not listening", act.label)
        self.assertFalse(act.waiting, "a steady state should not animate")

    def test_speaking_outranks_everything_else(self):
        # It is the only one of these that means "stop talking" rather than "wait a
        # moment", so it has to win however busy Flow also is.
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s._set_state(State.ASKING)
        sp.say("Word Error Rate.")
        self.assertIn("not listening", s.activity.label)

    def test_a_question_with_the_cli_says_asking(self):
        s = session()
        s._set_state(State.ASKING)
        self.assertEqual(s.activity, ("asking", True))

    def test_a_rewrite_with_the_cli_says_refining(self):
        s = session()
        s._set_state(State.REFINING)
        self.assertEqual(s.activity, ("refining", True))

    def test_a_model_build_is_named_as_one(self):
        # A first decode of a tier is a model build with a decode behind it, and those
        # are about a second apart. Reporting both as "decoding" is how the first
        # utterance of a session came to look like the app had hung.
        asr = FakeAsr()
        asr.loading = True
        s = session(asr=asr)
        self.assertEqual(s.activity, ("loading the model", True))

    def test_the_model_build_outranks_the_decode_it_is_holding_up(self):
        asr = SlowAsr()
        asr.loading = True
        s = session(asr=asr)
        try:
            s.worker.submit_final(LOUD)
            self.assertTrue(self._until(lambda: s.worker.busy))
            self.assertEqual(s.activity.label, "loading the model")
        finally:
            asr.release = True
            s.close()

    def test_a_decode_in_flight_is_visible(self):
        asr = SlowAsr()
        s = session(asr=asr)
        try:
            s.worker.submit_final(LOUD)
            self.assertTrue(self._until(lambda: s.worker.busy))
            self.assertEqual(s.activity, ("decoding", True))
        finally:
            asr.release = True
            s.close()

    def test_a_decode_is_not_announced_while_the_user_is_mid_sentence(self):
        # Partials run continuously while the gate is open, so this would be lit
        # permanently and would say nothing. The bars carry that moment.
        asr = SlowAsr()
        s = session(asr=asr)
        try:
            s.worker.submit_partial(LOUD)
            self.assertTrue(self._until(lambda: s.worker.busy))
            s.gate.speaking = True
            self.assertIsNone(s.activity)
        finally:
            asr.release = True
            s.close()

    def test_every_indeterminate_wait_animates(self):
        s = session()
        for state in (State.ASKING, State.REFINING):
            s._set_state(state)
            self.assertTrue(s.activity.waiting, state)

    @staticmethod
    def _until(check, timeout: float = 2.0) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if check():
                return True
            time.sleep(0.005)
        return False


class TestTheWholeExchangeIsAccountedFor(unittest.TestCase):
    """No silent stretch: every step of a converse round trip names itself."""

    def test_asking_then_speaking_then_quiet(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode()
        s.draft.set("what does WER stand for")
        with mock.patch("flow.session.ask",
                        return_value=("Word Error Rate.", "codex")):
            s.send()
            self.assertEqual(s.activity.label, "asking")
            self.assertTrue(s.hearing, "asking is a wait, not a deafness")
            s.wait_idle(timeout=5.0)
        # The answer arrived and is being read aloud: the promise changes from "wait a
        # moment" to "stop talking", and the microphone really is shut.
        self.assertTrue(sp.speaking)
        self.assertFalse(s.hearing)
        self.assertIn("not listening", s.activity.label)
        sp.speaking = False
        self.assertIsNone(s.activity)


class TestTheModelReportsItsOwnLoad(unittest.TestCase):
    def test_a_fresh_transcriber_is_not_loading(self):
        self.assertFalse(WhisperTranscriber().loading)

    def test_loading_is_true_while_a_tier_is_built_and_false_after(self):
        # No model is downloaded here: the build is replaced, and what is under test is
        # the flag around it, which is what the UI reads.
        asr = WhisperTranscriber()
        seen = []

        class FakeModel:
            def __init__(self, *a, **kw):
                seen.append(asr.loading)

        with mock.patch.dict(
            sys.modules, {"faster_whisper": mock.Mock(WhisperModel=FakeModel)}
        ):
            asr.load(final=False)
        self.assertEqual(seen, [True], "the flag was not up during the build")
        self.assertFalse(asr.loading, "the flag never came down")
        self.assertTrue(asr.loaded)

    def test_the_flag_comes_down_even_if_the_build_fails(self):
        # A failed load must not leave the indicator claiming a load forever.
        asr = WhisperTranscriber()

        def boom(*a, **kw):
            raise RuntimeError("no such model")

        with mock.patch.dict(
            sys.modules, {"faster_whisper": mock.Mock(WhisperModel=boom)}
        ):
            with self.assertRaises(RuntimeError):
                asr.load(final=False)
        self.assertFalse(asr.loading)


if __name__ == "__main__":
    unittest.main()
