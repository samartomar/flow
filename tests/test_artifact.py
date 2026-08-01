"""P9 response profiles: an answer is not the same thing as a piece of work.

`ASK_SENTENCES` protects the conversational case — three sentences is what a reply
read over a pill can carry. But the request this product exists to serve is "give me
the prompt", and a prompt, a plan or a list cannot fit that ceiling. So the profile is
chosen from the *request*, never guessed from the answer, and the spoken half changes
with it: half-duplex (invariant 6) means a long reply read aloud deafens Flow for
minutes, so an artifact is rendered whole and spoken as a one-line pointer.

The false-positive cost is accepted and pinned here: a mis-detected conversational
question gets an essay, which is annoying; a mis-detected artifact request gets its
work truncated to three sentences, which is the product failing at its own point.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.edits import is_artifact_request  # noqa: E402
from flow.refine import ASK_MAX_CHARS, Cli, ask  # noqa: E402
from flow.session import Session  # noqa: E402

CLI = Cli("codex", ("codex", "exec"))


class FakeMic:
    level_db = -60.0

    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def restart(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeAsr:
    loading = False

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


class FakeSpeaker:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.speaking = False

    def say(self, text: str) -> None:
        self.said.append(text)

    def stop(self) -> None: ...


def converse_session(speaker=None) -> Session:
    s = Session(asr=FakeAsr(), mic=FakeMic(), speaker=speaker)
    s.toggle_mode()
    return s


class TestTheRequestChoosesTheProfile(unittest.TestCase):
    """Detection reads the request. It never sees the answer."""

    ARTIFACTS = [
        "give me a complete reusable prompt for this",
        "based on our conversation, give me the full prompt",
        "write me a dockerfile for this setup",
        "draft a commit message for these changes",
        "list all the edge cases we discussed",
        "give me a summary as a table",
        "okay just give me the checklist",
    ]

    CONVERSATION = [
        "how do I widen a column",
        "is this a good idea",
        "what does a five hundred mean here",
        "give me a second to think about the plan",
        "why did the test fail",
        "does postgres fifteen support that",
    ]

    def test_work_requests_are_recognised(self):
        for u in self.ARTIFACTS:
            self.assertTrue(is_artifact_request(u), f"missed: {u!r}")

    def test_questions_stay_conversational(self):
        for u in self.CONVERSATION:
            self.assertFalse(is_artifact_request(u), f"over-matched: {u!r}")


class TestTheArtifactPromptDropsTheCeiling(unittest.TestCase):
    def test_the_conversation_prompt_carries_the_sentence_cap(self):
        with mock.patch("flow.refine._invoke", return_value=("fine.", "")) as spy:
            ask("how do I widen a column", cli=CLI)
        prompt = spy.call_args[0][1]
        self.assertIn("at most 3 sentences", prompt)

    def test_the_artifact_prompt_has_no_sentence_ceiling(self):
        with mock.patch("flow.refine._invoke", return_value=("the work", "")) as spy:
            ask("give me the full prompt", cli=CLI, artifact=True)
        prompt = spy.call_args[0][1]
        self.assertNotIn("sentences", prompt,
                         "an artifact request must not carry the conversational cap")

    def test_the_artifact_cap_is_wider_than_the_conversational_one(self):
        long = "x" * (ASK_MAX_CHARS + 500)
        with mock.patch("flow.refine._invoke", return_value=(long, "")):
            conversational, _ = ask("q", cli=CLI)
            artifact, _ = ask("q", cli=CLI, artifact=True)
        self.assertLess(len(conversational), len(long),
                        "the conversational cap should still truncate")
        self.assertEqual(artifact, long,
                         "an artifact someone asked for in full must arrive in full")


LONG_WORK = "\n".join(f"line {i}: a requirement worth keeping" for i in range(1, 13))


class TestArtifactAnswersAreShownWholeAndSpokenShort(unittest.TestCase):
    def test_an_artifact_request_reaches_ask_with_the_flag(self):
        s = converse_session()
        s.draft.set("give me a complete reusable prompt for this")
        with mock.patch("flow.session.ask", return_value=("done", "codex")) as spy:
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertTrue(spy.call_args.kwargs.get("artifact"))

    def test_a_question_reaches_ask_without_it(self):
        s = converse_session()
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("ALTER TABLE.", "codex")) as spy:
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertFalse(spy.call_args.kwargs.get("artifact"))

    def test_a_long_artifact_is_rendered_whole_and_spoken_as_a_pointer(self):
        sp = FakeSpeaker()
        s = converse_session(speaker=sp)
        s.draft.set("give me a complete reusable prompt for this")
        with mock.patch("flow.session.ask", return_value=(LONG_WORK, "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(s.reply, LONG_WORK, "the bubble gets every line")
        self.assertEqual(len(sp.said), 1)
        self.assertIn("12", sp.said[0], "the pointer says how much is on screen")
        self.assertNotIn("requirement worth keeping", sp.said[0],
                         "the work itself must not be read aloud")

    def test_a_short_artifact_is_just_spoken(self):
        sp = FakeSpeaker()
        s = converse_session(speaker=sp)
        s.draft.set("draft a commit message for these changes")
        with mock.patch("flow.session.ask",
                        return_value=("Fix the tail split.", "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(sp.said, ["Fix the tail split."])

    def test_a_long_conversational_answer_is_still_spoken_whole(self):
        sp = FakeSpeaker()
        s = converse_session(speaker=sp)
        s.draft.set("how do I widen a column")
        long_answer = "You use ALTER TABLE. " * 30
        with mock.patch("flow.session.ask", return_value=(long_answer, "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(sp.said, [long_answer],
                         "the conversational path must not change")


if __name__ == "__main__":
    unittest.main()
