"""Tests for the constrained re-decode of a suspected mis-heard command.

"change Sameer to Samir" whose target is nowhere in the draft is far likelier to be a
mis-hearing than a request for judgement. Re-decoding that same audio biased toward
the trigger verbs and the draft's own words costs about a second; the CLI costs seven,
and would be asked to edit text that does not contain the word.

The important tests are the ones about *not* rescuing: a genuine rewrite request must
still go to the CLI immediately, and a rescue that finds nothing must not swallow the
user's instruction.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.edits import command_bias, plan  # noqa: E402
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


class BiasAwareAsr:
    """Returns one text normally and another when biased — a stand-in for a decoder
    that gets the command right once it knows what to listen for."""

    def __init__(self, finals: list[str], rescued: str = "") -> None:
        self.finals = list(finals)
        self.rescued = rescued
        self.bias_seen: list[str] = []

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


def run(finals, rescued="", refine_result=("REWRITTEN", "codex")):
    mic = ScriptedMic()
    asr = BiasAwareAsr(finals, rescued)
    s = Session(asr=asr, mic=mic)
    s.start()
    with mock.patch("flow.session.refine", return_value=refine_result) as refine:
        for _ in finals:
            mic.utterance()
            s.wait_idle(timeout=5.0)
        # The rescue is submitted from inside routing, so pump again for its result.
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
    return s, asr, refine


class TestCommandBias(unittest.TestCase):
    def test_it_carries_the_verbs_and_the_drafts_own_words(self):
        bias = command_bias("Meeting on Tuesday with Sameer about the release.")
        self.assertIn("delete", bias)
        self.assertIn("replace", bias)
        self.assertIn("Sameer", bias)
        self.assertIn("Tuesday", bias)

    def test_it_is_bounded(self):
        long_draft = " ".join(f"word{i:04d}" for i in range(500))
        self.assertLessEqual(len(command_bias(long_draft).split()), 48)

    def test_short_words_are_not_worth_the_prompt_space(self):
        self.assertNotIn(" the ", f" {command_bias('the cat sat on the mat')} ")


class TestRescue(unittest.TestCase):
    def test_a_mis_heard_command_is_re_decoded_and_applied_locally(self):
        s, asr, refine = run(
            ["Meeting on Tuesday.", "change Blarg to Friday"],
            rescued="change Tuesday to Friday",
        )
        self.assertEqual(s.draft.text, "Meeting on Friday.")
        refine.assert_not_called()
        self.assertTrue(asr.bias_seen, "the rescue decode never ran")
        self.assertIn("Tuesday", asr.bias_seen[0])
        s.close()

    def test_the_note_says_what_happened(self):
        s, _asr, _refine = run(
            ["Meeting on Tuesday.", "change Blarg to Friday"],
            rescued="change Tuesday to Friday",
        )
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("re-listening" in n for n in notes), notes)
        self.assertTrue(any("re-heard as" in n for n in notes), notes)
        s.close()

    def test_a_rescue_that_finds_nothing_still_reaches_the_cli(self):
        s, _asr, refine = run(
            ["Meeting on Tuesday.", "change Zorblat to Friday"],
            rescued="change Zorblat to Friday",  # second read is no better
        )
        refine.assert_called_once()
        self.assertEqual(s.draft.text, "REWRITTEN")
        s.close()

    def test_a_genuine_rewrite_request_never_pays_for_a_rescue(self):
        s, asr, refine = run(
            ["Meeting on Tuesday.", "make it more formal"],
            rescued="should not be used",
        )
        self.assertEqual(asr.bias_seen, [], "a rewrite request was re-decoded")
        refine.assert_called_once()
        s.close()

    def test_an_empty_rescue_result_falls_back_rather_than_losing_the_request(self):
        s, _asr, refine = run(
            ["Meeting on Tuesday.", "change Blarg to Friday"], rescued=""
        )
        refine.assert_called_once()
        s.close()

    def test_the_draft_is_untouched_while_the_rescue_is_in_flight(self):
        # The user's text must not flicker: nothing is applied until the second read
        # comes back and turns out to be a command.
        mic = ScriptedMic()
        asr = BiasAwareAsr(["Meeting on Tuesday.", "change Blarg to Friday"],
                           rescued="change Tuesday to Friday")
        s = Session(asr=asr, mic=mic)
        s.start()
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "Meeting on Tuesday.")
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertIn(s.draft.text, ("Meeting on Tuesday.", "Meeting on Friday."))
        s.close()


class TestPlanMarksEscalations(unittest.TestCase):
    """Only an unfound *target* is a suspected mis-hearing."""

    DRAFT = "Meeting on Tuesday with Sameer."

    def test_unfound_target_is_marked(self):
        p = plan("change Friday to Monday", self.DRAFT)
        self.assertEqual(p.kind, "semantic")
        self.assertTrue(p.escalated)
        self.assertEqual(p.target, "Friday")

    def test_a_real_rewrite_request_is_not(self):
        for utterance in ("make it more formal", "shorten this", "fix the grammar"):
            with self.subTest(utterance=utterance):
                p = plan(utterance, self.DRAFT)
                self.assertEqual(p.kind, "semantic")
                self.assertFalse(p.escalated)

    def test_a_found_target_stays_local(self):
        p = plan("change Tuesday to Friday", self.DRAFT)
        self.assertEqual(p.kind, "local")
        self.assertFalse(p.escalated)


if __name__ == "__main__":
    unittest.main()
