"""What happens to the draft while a CLI call is in flight.

One measured number sets up every test here: a refine costs ~7 s. The microphone is
open for all of it, the router keeps running, and the draft the CLI was handed stops
being the draft on screen. So a result carries no authority by itself — it is an answer
to a question about a version of the text, and the only safe thing to do with an answer
whose question has expired is to say so and throw it away.

The compound case at the bottom is the one that reaches the user: in converse mode a
stale rewrite could reappear as a fresh draft, re-arm the countdown, and be asked with
no press. Undo recovers words; nothing recalls a question.
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.session import AUTO_ASK_SEC, Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)


class FakeMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

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
    def load(self) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


class Held:
    """A CLI call the test decides the duration of.

    The race needs the call to still be running while the test edits the draft, and
    `time.sleep` in a worker thread would make that a guess about scheduling. `started`
    says the call is genuinely in flight; `release` ends it.
    """

    def __init__(self, result) -> None:
        self.result = result
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def __call__(self, text, *args, **kwargs):
        self.calls.append(text)
        self.started.set()
        self.release.wait(5.0)
        return self.result


def session(**kw) -> Session:
    return Session(asr=FakeAsr(), mic=FakeMic(), **kw)


def notes(s) -> str:
    return " | ".join(e.text for e in s.events() if e.kind == "note")


class RefineInFlight(unittest.TestCase):
    """Set up the shared position: a draft, a rewrite of it running, more speech."""

    def setUp(self) -> None:
        self.slow = Held(("REVISED", "codex"))
        self.patch = mock.patch("flow.session.refine", self.slow)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.slow.release.set)

    def arm(self, converse: bool = False) -> Session:
        s = session()
        if converse:
            s.toggle_mode()
        s.draft.set("widen the column")
        s._after_draft_change()
        s._route("make it more formal")
        self.assertTrue(self.slow.started.wait(2.0), "the rewrite never started")
        s.events()
        return s

    def finish(self, s) -> None:
        """Let the call return, then pump its result in.

        Deliberately not conditioned on `state`: the defect under test is that the
        state stops saying a rewrite is out, so a wait that watched it would return
        before the result existed and the test would pass by not looking.
        """
        self.slow.release.set()
        for _ in range(500):
            with s._refine_lock:
                if s._refine_result is not None:
                    break
            time.sleep(0.01)
        s.pump_results()


class TestAStaleRewriteNeverLands(RefineInFlight):
    def test_speech_during_a_rewrite_keeps_the_words_that_arrived_after_it(self):
        # The rewrite was computed from "widen the column". Applying it now would
        # delete a sentence the user spoke while the CLI was thinking.
        s = self.arm()
        s._route("and use the users table")
        self.finish(s)
        self.assertEqual(s.draft.text, "widen the column and use the users table")

    def test_discarding_a_rewrite_is_said_out_loud(self):
        s = self.arm()
        s._route("and use the users table")
        s.events()
        self.finish(s)
        self.assertIn("stale rewrite", notes(s))

    def test_an_untouched_draft_still_gets_its_rewrite(self):
        # The guard has to be about the draft moving, not about time passing.
        s = self.arm()
        self.finish(s)
        self.assertEqual(s.draft.text, "REVISED")

    def test_a_result_for_an_operation_nobody_is_waiting_for_is_ignored(self):
        # The identity half of the guard: a thread whose call was abandoned still has
        # a result to hand back, and `_refine_result` is the seam it hands it through.
        s = session()
        s.draft.set("widen the column")
        s._after_draft_change()
        with s._refine_lock:
            s._refine_result = (999, s.draft.revision, ("REVISED", "codex"))
        s._pump_refine()
        self.assertEqual(s.draft.text, "widen the column")


class TestTheDraftIsNotFreeWhileTheCliHasIt(RefineInFlight):
    """`_after_draft_change` used to set DRAFT unconditionally, and everything that
    reads `state` believed it: Send stopped refusing, and the countdown re-armed."""

    def test_speaking_during_a_rewrite_does_not_clear_the_refining_state(self):
        s = self.arm()
        s._route("and use the users table")
        self.assertIs(s.state, State.REFINING)

    def test_send_still_refuses_after_speech_during_a_rewrite(self):
        s = self.arm()
        s._route("and use the users table")
        s.events()
        self.assertEqual(s.send(), "")
        self.assertIn("still rewriting", notes(s))
        self.assertEqual(s.draft.text, "widen the column and use the users table")

    def test_the_countdown_does_not_run_while_a_rewrite_is_in_flight(self):
        s = self.arm(converse=True)
        s._route("and use the users table")
        self.assertIsNone(s.auto_ask_in)

    def test_a_second_rewrite_is_refused_rather_than_stacked(self):
        s = self.arm()
        s._route("rewrite it in one sentence")
        self.assertEqual(len(self.slow.calls), 1)
        self.assertIn("still rewriting", notes(s))


class TestTheCompoundRace(RefineInFlight):
    """The one that reaches the user, end to end.

    Converse mode, a rewrite in flight, speech appended, the countdown armed by the
    stomped state, the question sent unrewritten — and then the stale result arriving
    as a fresh draft with a fresh countdown behind it.
    """

    def test_nothing_is_asked_while_the_rewrite_is_still_out(self):
        s = self.arm(converse=True)
        asked = []
        with mock.patch("flow.session.ask",
                        side_effect=lambda q, **kw: (asked.append(q), ("ok", "codex"))[1]):
            s._route("and use the users table")
            s._settled_at -= AUTO_ASK_SEC + 0.1
            s._pump_auto_ask()
            self.assertEqual(asked, [])
            self.finish(s)
            self.assertEqual(asked, [])
        self.assertEqual(s.draft.text, "widen the column and use the users table")


class TestAnAnswerDoesNotOwnTheDraftItCameBackTo(unittest.TestCase):
    """The mirror of the refine case. `_pump_ask` set IDLE unconditionally, so a draft
    spoken while waiting for an answer was reported as nothing held — and the countdown
    that had been running on it stopped without saying anything."""

    def test_a_draft_built_while_waiting_survives_the_answer(self):
        s = session()
        s.toggle_mode()
        held = Held(("Use ALTER TABLE.", "codex"))
        self.addCleanup(held.release.set)
        with mock.patch("flow.session.ask", held):
            s.draft.set("how do I widen a column")
            s.send()
            self.assertTrue(held.started.wait(2.0), "the ask never started")
            s._route("and use the users table")
            self.assertIs(s.state, State.ASKING, "the pending answer stopped showing")
            held.release.set()
            for _ in range(200):
                s.pump_results()
                if s.reply:
                    break
                time.sleep(0.01)
        self.assertEqual(s.reply, "Use ALTER TABLE.")
        self.assertEqual(s.draft.text, "and use the users table")
        self.assertIs(s.state, State.DRAFT, "a held draft was reported as idle")
        self.assertIsNotNone(s.auto_ask_in, "the countdown never came back")


if __name__ == "__main__":
    unittest.main()
