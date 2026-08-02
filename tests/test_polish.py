"""Tests for the prompt-polish verb (P5).

Dictating a prompt and writing one are different acts: spoken thought arrives as
context, correction and afterthought in the order it occurred to the speaker. "Make it
a proper prompt" asks for one specific transformation, so it gets its own verb rather
than being handed to the CLI as free text to interpret.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling helpers

from flow.audio import BLOCK  # noqa: E402
from flow.edits import plan  # noqa: E402
from flow.refine import _POLISH_PROMPT, refine  # noqa: E402
from flow.session import Session, State  # noqa: E402
from cli_env import cli_on_path  # noqa: E402


def fake_popen(stdout: str = "", returncode: int = 0, stderr: str = ""):
    """A `Popen` with the surface `_invoke` uses: one `communicate` and an exit code."""
    proc = mock.Mock(returncode=returncode, pid=0)
    proc.communicate.return_value = (stdout, stderr)
    proc.poll.return_value = returncode
    return proc


RAMBLE = (
    "so the login is broken when you use SSO, it throws a five hundred, "
    "um, this is on version 2.3.1, and I need you to find the root cause"
)


class TestVerb(unittest.TestCase):
    def test_the_phrasings_people_use(self):
        for utterance in (
            "make it a proper prompt",
            "make this a prompt",
            "make that a better prompt",
            "turn it into a proper prompt",
            "polish this prompt",
            "clean up this prompt",
            "make it prompt ready",
            "please make it a proper prompt",
        ):
            with self.subTest(utterance=utterance):
                p = plan(utterance, RAMBLE)
                self.assertEqual(p.kind, "semantic")
                self.assertEqual(p.op, "polish", utterance)

    def test_other_rewrites_are_not_polish(self):
        for utterance in ("make it more formal", "shorten this", "fix the grammar"):
            with self.subTest(utterance=utterance):
                p = plan(utterance, RAMBLE)
                self.assertEqual(p.kind, "semantic")
                self.assertNotEqual(p.op, "polish")

    def test_a_local_edit_is_still_local(self):
        # "make X lowercase" must not be swallowed by a pattern starting "make it".
        text = "send the REPORT today"
        self.assertEqual(plan("make REPORT lowercase", text).kind, "local")


class TestPrompt(unittest.TestCase):
    def test_it_says_request_not_ask(self):
        # "Ask" is a product surface (P9 converse mode); the Refine instruction must
        # not borrow the word as the name of a structural part. "asked for" as a verb
        # is fine — it is the noun that collides.
        low = _POLISH_PROMPT.lower()
        self.assertIn("request", low)
        for noun in (" the ask", "specific ask", "the ask.", "ask first"):
            self.assertNotIn(noun, low)

    def test_the_request_comes_first(self):
        # Decision 1: a reader must see what is being asked for without hunting.
        low = _POLISH_PROMPT.lower()
        self.assertIn("request first", low)
        self.assertIn("first line", low)

    def test_it_says_which_requirements_belong_in_the_request(self):
        # Decision 2: defining requirements fold in, standing prohibitions do not.
        low = _POLISH_PROMPT.lower()
        self.assertIn("independently actionable", low)
        self.assertIn("nullable", low)  # the reviewer's own worked example
        self.assertIn("separate constraints", low)

    def test_normalisation_is_scoped_to_the_certain_cases(self):
        # Decision 3, and the tension it creates with "verbatim": details are kept
        # verbatim *apart from* the normalisations, and an ambiguous number is left
        # as spoken rather than guessed.
        low = _POLISH_PROMPT.lower()
        self.assertIn("http 500", low)
        self.assertIn("postgresql 15", low)
        self.assertIn("2.3.1", low)
        self.assertIn("keep the speaker's words", low)
        self.assertIn("apart from those normalisations", low)
        self.assertIn("verbatim", low)

    def test_the_instruction_names_the_structure_and_forbids_invention(self):
        low = _POLISH_PROMPT.lower()
        for required in ("context", "constraint", "request", "invent nothing",
                         "verbatim"):
            self.assertIn(required, low, required)

    def test_it_forbids_preamble(self):
        self.assertIn("no preamble", _POLISH_PROMPT.lower())

    def test_polish_ignores_the_spoken_instruction(self):
        # The user said "make it a proper prompt"; that phrase must not end up inside
        # the prompt sent to the CLI, or the CLI is being asked to interpret it.
        fake = fake_popen("POLISHED", stderr="")
        with cli_on_path(), mock.patch("subprocess.Popen", return_value=fake) as run:
            out, note = refine(RAMBLE, "make it a proper prompt", polish=True)
        sent = run.call_args.args[0][-1]
        self.assertEqual(out, "POLISHED")
        self.assertNotIn("make it a proper prompt", sent)
        self.assertIn(RAMBLE, sent)

    def test_a_normal_refine_still_carries_its_instruction(self):
        fake = fake_popen("REVISED", stderr="")
        with cli_on_path(), mock.patch("subprocess.Popen", return_value=fake) as run:
            refine(RAMBLE, "make it more formal")
        self.assertIn("make it more formal", run.call_args.args[0][-1])

    def test_growth_is_allowed_where_a_revision_would_be_refused(self):
        # Structure costs words. Sized so the *multiplier* decides rather than the
        # slack: a revision may grow 4x + 200, a polish 8x + 600.
        short = "fix the login bug " * 20  # 360 chars
        grown = "Context: " + "x" * (5 * len(short))
        fake = fake_popen(grown, stderr="")
        with cli_on_path(), mock.patch("subprocess.Popen", return_value=fake):
            polished, _ = refine(short, "make it a proper prompt", polish=True)
            revised, reason = refine(short, "make it more formal")
        self.assertEqual(polished, grown)
        self.assertIsNone(revised)
        self.assertIn("commentary", reason)

    def test_runaway_output_is_still_refused(self):
        fake = fake_popen("y" * 20000, stderr="")
        with cli_on_path(), mock.patch("subprocess.Popen", return_value=fake):
            out, reason = refine("fix the login bug", "x", polish=True)
        self.assertIsNone(out)
        self.assertIn("commentary", reason)


class ScriptedMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

    def utterance(self) -> None:
        self._blocks += [np.full(BLOCK, 0.2, dtype=np.float32)] * 20
        self._blocks += [np.zeros(BLOCK, dtype=np.float32)] * 16

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self):
        out, self._blocks = self._blocks, []
        return out


class ScriptedAsr:
    def __init__(self, finals):
        self.finals = list(finals)

    def load(self) -> None: ...
    def unload(self) -> None: ...
    loaded = True

    def text(self, audio, *, final: bool = False, hotwords: str = "") -> str:
        if not final:
            return ""
        return self.finals.pop(0) if self.finals else ""


class TestSessionRoutesPolish(unittest.TestCase):
    def test_the_session_asks_for_a_polish_not_a_revision(self):
        mic = ScriptedMic()
        s = Session(asr=ScriptedAsr([RAMBLE, "make it a proper prompt"]), mic=mic)
        s.start()
        with mock.patch("flow.session.refine", return_value=("SHAPED", "codex")) as r:
            mic.utterance()
            s.wait_idle(timeout=5.0)
            mic.utterance()
            s.wait_idle(timeout=5.0)
            for _ in range(3):
                s.tick()
        self.assertTrue(r.called)
        self.assertIs(r.call_args.kwargs.get("polish"), True)
        self.assertEqual(s.draft.text, "SHAPED")
        s.close()

    def test_a_failed_polish_keeps_the_dictation(self):
        mic = ScriptedMic()
        s = Session(asr=ScriptedAsr([RAMBLE, "make it a proper prompt"]), mic=mic)
        s.start()
        with mock.patch("flow.session.refine", return_value=(None, "codex timed out")):
            mic.utterance()
            s.wait_idle(timeout=5.0)
            mic.utterance()
            s.wait_idle(timeout=5.0)
            for _ in range(3):
                s.tick()
        self.assertEqual(s.draft.text, RAMBLE)
        self.assertIs(s.state, State.DRAFT)
        s.close()


if __name__ == "__main__":
    unittest.main()
