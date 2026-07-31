"""Interaction tests across the pieces added in different iterations.

The unit tests cover each module. These cover the seams — where the hallucination
filter meets the state machine, where the router meets undo, where a filtered utterance
meets the pill's colour. Two real bugs came out of writing them.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.session import Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)
QUIET = np.zeros(BLOCK, dtype=np.float32)


class ScriptedMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

    def utterance(self) -> None:
        self._blocks += [LOUD] * 20 + [QUIET] * 16

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class ScriptedAsr:
    def __init__(self, finals: list[str]) -> None:
        self.finals = list(finals)

    def load(self) -> None: ...
    def unload(self) -> None: ...
    loaded = True

    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        if not final:
            return ""
        return self.finals.pop(0) if self.finals else ""


def run(finals: list[str]) -> Session:
    mic = ScriptedMic()
    for _ in range(len(finals)):
        mic.utterance()
    s = Session(asr=ScriptedAsr(finals), mic=mic)
    s.start()
    for _ in range(len(finals)):
        s.wait_idle(timeout=5.0)
    return s


class TestFilteredUtterance(unittest.TestCase):
    def test_fully_filtered_utterance_returns_to_idle(self):
        """A hallucination rejected by clean.py must not leave a green pill.

        The transcriber returning "" is exactly what happens when the filter drops
        everything. Before this was handled, the state machine stayed on LISTENING and
        the pill sat green with nothing in flight.
        """
        s = run([""])
        self.assertEqual(s.draft.text, "")
        self.assertIs(s.state, State.IDLE)
        s.close()

    def test_filtered_utterance_between_real_ones_keeps_the_draft(self):
        s = run(["Send the report.", "", "It is due Tuesday."])
        self.assertEqual(s.draft.text, "Send the report. It is due Tuesday.")
        self.assertIs(s.state, State.DRAFT)
        s.close()

    def test_empty_partials_are_not_emitted(self):
        # An empty partial would pop a blank bubble open on screen.
        s = run(["Something real."])
        partials = [e for e in s.events() if e.kind == "partial"]
        self.assertEqual(partials, [])
        s.close()


class TestRouterAndUndoTogether(unittest.TestCase):
    def test_new_local_ops_reach_the_draft_without_the_cli(self):
        with mock.patch("flow.session.refine") as refine:
            s = run([
                "Call Bob and tell Bob it is ready.",
                "replace all Bob with Alice",
            ])
            refine.assert_not_called()
        self.assertEqual(s.draft.text, "Call Alice and tell Alice it is ready.")
        s.close()

    def test_undo_reverses_a_replace_all(self):
        s = run([
            "Call Bob and tell Bob it is ready.",
            "replace all Bob with Alice",
            "scratch that",
        ])
        self.assertEqual(s.draft.text, "Call Bob and tell Bob it is ready.")
        s.close()

    def test_insert_then_send_hands_off_the_edited_text(self):
        s = run(["send the report.", "insert final before report"])
        self.assertEqual(s.draft.text, "send the final report.")
        out = s.send()
        self.assertEqual(out, "send the final report.")
        self.assertEqual(s.draft.text, "")
        self.assertIs(s.state, State.IDLE)
        s.close()

    def test_forced_append_beats_the_heuristic(self):
        """The Continue chip must win even when the utterance looks like an edit.

        Audio is fed one utterance at a time on purpose. Queueing both up front lets
        `drain()` hand over everything in a single tick, so both are routed before
        `force_next` can be set — which is how the first version of this test
        "discovered" a bug that was really just its own scripting.
        """
        mic = ScriptedMic()
        s = Session(asr=ScriptedAsr(["Meeting on Tuesday.", "delete Tuesday"]), mic=mic)
        s.start()

        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "Meeting on Tuesday.")

        s.force_next = "append"
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "Meeting on Tuesday. delete Tuesday")
        s.close()

    def test_without_the_override_the_same_words_are_an_edit(self):
        """The counterpart: proves the override above actually changed the outcome."""
        mic = ScriptedMic()
        s = Session(asr=ScriptedAsr(["Meeting on Tuesday.", "delete Tuesday"]), mic=mic)
        s.start()
        mic.utterance()
        s.wait_idle(timeout=5.0)
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "Meeting on.")
        s.close()


if __name__ == "__main__":
    unittest.main()
