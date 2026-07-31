"""Tests for the post-hoc "that was a command" rescue.

A misroute costs the user two utterances today: undo, then say it again — and the
second attempt is no likelier to be heard correctly than the first. This takes one
short phrase and re-reads audio Flow already has.

The tests that matter are the ones about failure: if the re-read finds no command, the
user's words must come back exactly where they were. Losing dictation to a failed guess
would be worse than the misroute.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.edits import plan  # noqa: E402
from flow.session import Session  # noqa: E402

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


class BiasAwareAsr:
    def __init__(self, finals, rescued=""):
        self.finals = list(finals)
        self.rescued = rescued
        self.bias_seen = []

    def load(self) -> None: ...
    def unload(self) -> None: ...
    loaded = True

    def text(self, audio, *, final: bool = False, hotwords: str = "") -> str:
        if hotwords:
            self.bias_seen.append(hotwords)
            return self.rescued
        if not final:
            return ""
        return self.finals.pop(0) if self.finals else ""


def session_with(finals, rescued="", force_append_from=None):
    """Run `finals` through a session, one utterance at a time.

    `force_append_from` presses Continue before that index, which is how a misroute is
    staged: the override has to be set *before* the utterance is routed, not after.
    """
    mic = ScriptedMic()
    asr = BiasAwareAsr(finals, rescued)
    s = Session(asr=asr, mic=mic)
    s.start()
    for i in range(len(finals)):
        if force_append_from is not None and i >= force_append_from:
            s.force_next = "append"
        mic.utterance()
        s.wait_idle(timeout=5.0)
    return s, asr, mic


class TestTrigger(unittest.TestCase):
    DRAFT = "Meeting on Tuesday. delete Tuesday"

    def test_the_phrases_people_would_actually_say(self):
        for utterance in (
            "that was a command",
            "that was an instruction",
            "that was an edit",
            "no, that was a command",
            "i meant that as a command",
            "please, that was a command",
        ):
            with self.subTest(utterance=utterance):
                self.assertEqual(plan(utterance, self.DRAFT).kind, "rescue")

    def test_ordinary_speech_is_not_a_trigger(self):
        for utterance in (
            "that was a long meeting",
            "that was an interesting point",
            "the command line is broken",
        ):
            with self.subTest(utterance=utterance):
                self.assertNotEqual(plan(utterance, self.DRAFT).kind, "rescue")


class TestPostHocRescue(unittest.TestCase):
    def test_a_misrouted_command_is_taken_back_and_applied(self):
        # "delete Tuesday" landed as dictation; the words as transcribed *are* a
        # command once the draft is restored to what it was.
        s, _asr, _mic = session_with(
            ["Meeting on Tuesday.", "delete Tuesday"], force_append_from=1
        )
        self.assertTrue(s.draft.text.endswith("delete Tuesday"), s.draft.text)

        self.assertTrue(s.rescue_last_append())
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "Meeting on.")
        s.close()

    def test_the_re_read_uses_the_audio_when_the_words_are_not_a_command(self):
        s, asr, _mic = session_with(
            ["Meeting on Tuesday.", "the lead toosdai"],
            rescued="delete Tuesday", force_append_from=1,
        )
        self.assertTrue(s.draft.text.endswith("the lead toosdai"))
        s.rescue_last_append()
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        self.assertTrue(asr.bias_seen, "the biased re-read never ran")
        self.assertEqual(s.draft.text, "Meeting on.")
        s.close()

    def test_a_failed_re_read_gives_the_words_back(self):
        s, _asr, _mic = session_with(
            ["Meeting on Tuesday.", "and then we discussed the budget"],
            rescued="and then we discussed the budget", force_append_from=1,
        )
        before = s.draft.text
        s.rescue_last_append()
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        self.assertEqual(s.draft.text, before, "dictation was lost to a failed guess")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("could not re-read" in n for n in notes), notes)
        s.close()

    def test_nothing_to_rescue_is_said_rather_than_ignored(self):
        s, _asr, _mic = session_with([])
        self.assertFalse(s.rescue_last_append())
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("nothing to re-read" in n for n in notes), notes)
        s.close()

    def test_can_rescue_reflects_whether_there_is_anything_to_take_back(self):
        s, _asr, _mic = session_with([])
        self.assertFalse(s.can_rescue)
        s.close()

        s, _asr, _mic = session_with(["Meeting on Tuesday."])
        self.assertTrue(s.can_rescue)
        s.close()

    def test_the_spoken_trigger_reaches_the_rescue(self):
        s, _asr, mic = session_with(
            ["Meeting on Tuesday.", "delete Tuesday"], force_append_from=1
        )
        # Now say the trigger as a third utterance.
        s.asr.finals.append("that was a command")
        mic.utterance()
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        self.assertEqual(s.draft.text, "Meeting on.")
        s.close()

    def test_a_rescue_does_not_fire_twice_on_the_same_utterance(self):
        s, _asr, _mic = session_with(
            ["Meeting on Tuesday.", "delete Tuesday"], force_append_from=1
        )
        self.assertTrue(s.rescue_last_append())
        s.wait_idle(timeout=5.0)
        after_first = s.draft.text
        self.assertFalse(s.rescue_last_append())
        self.assertEqual(s.draft.text, after_first)
        s.close()


if __name__ == "__main__":
    unittest.main()
