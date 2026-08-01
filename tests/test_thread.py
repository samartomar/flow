"""Tests for thread continuity (P6).

Send used to erase, which is right for a typewriter and wrong for the thing people do
with one: a prompt is rarely finished on the first send. The store is bounded twice
over, and the tests that matter are the ones proving a long session cannot grow it and
that recall never destroys what is already on screen.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.edits import plan  # noqa: E402
from flow.refine import refine  # noqa: E402
from flow.session import Session  # noqa: E402
from flow.thread import CONTEXT_CHARS, MAX_CHARS, MAX_TURNS, Thread  # noqa: E402


def fake_popen(stdout: str = "", returncode: int = 0, stderr: str = ""):
    """A `Popen` with the surface `_invoke` uses: one `communicate` and an exit code."""
    proc = mock.Mock(returncode=returncode, pid=0)
    proc.communicate.return_value = (stdout, stderr)
    proc.poll.return_value = returncode
    return proc


class TestThreadStore(unittest.TestCase):
    def test_turns_are_kept_in_order(self):
        t = Thread()
        t.add("first")
        t.add("second")
        self.assertEqual(t.turns, ["first", "second"])
        self.assertEqual(t.last, "second")

    def test_blank_sends_are_not_turns(self):
        t = Thread()
        t.add("   ")
        t.add("")
        self.assertEqual(len(t), 0)
        self.assertEqual(t.last, "")

    def test_bounded_by_turn_count(self):
        t = Thread()
        for i in range(MAX_TURNS + 15):
            t.add(f"turn {i}")
        self.assertEqual(len(t), MAX_TURNS)
        self.assertEqual(t.last, f"turn {MAX_TURNS + 14}")

    def test_bounded_by_characters(self):
        # R8: a long session must cost what a short one costs.
        t = Thread()
        for i in range(MAX_TURNS):
            t.add("x" * 5000)
        self.assertLessEqual(t.chars, MAX_CHARS)
        self.assertGreaterEqual(len(t), 1)

    def test_one_oversized_turn_is_kept_whole(self):
        # "Bring back my last prompt" has to work even for a long prompt.
        t = Thread()
        huge = "y" * (MAX_CHARS * 2)
        t.add(huge)
        self.assertEqual(t.last, huge)

    def test_tail_returns_whole_turns_within_the_budget(self):
        t = Thread()
        for i in range(10):
            t.add(f"turn {i} " + "z" * 400)
        tail = t.tail(CONTEXT_CHARS)
        self.assertTrue(tail)
        self.assertLessEqual(sum(len(x) for x in tail), CONTEXT_CHARS + 400)
        self.assertEqual(tail[-1], t.last)
        for turn in tail:
            self.assertIn(turn, t.turns)  # never a fragment

    def test_tail_of_an_empty_thread(self):
        self.assertEqual(Thread().tail(), [])


class TestVerbs(unittest.TestCase):
    def test_recall_phrasings(self):
        for utterance in (
            "bring back my last prompt",
            "bring back the last prompt",
            "restore the previous prompt",
            "recall my last message",
            "get back my last draft",
        ):
            with self.subTest(utterance=utterance):
                self.assertEqual(plan(utterance, "").kind, "recall")

    def test_followup_phrasings_and_their_payload(self):
        self.assertEqual(plan("follow up", "").kind, "followup")
        self.assertEqual(plan("one more thing", "").kind, "followup")
        p = plan("follow up: and add the logs", "")
        self.assertEqual((p.kind, p.payload), ("followup", "and add the logs"))
        p = plan("also add the logs", "")
        self.assertEqual((p.kind, p.payload), ("followup", "add the logs"))

    def test_ordinary_speech_is_not_a_thread_verb(self):
        for utterance in ("bring back the milk", "follow the instructions",
                          "restore the database from backup"):
            with self.subTest(utterance=utterance):
                self.assertNotIn(plan(utterance, "").kind, ("recall", "followup"))


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


def run(finals):
    mic = ScriptedMic()
    s = Session(asr=ScriptedAsr(finals), mic=mic)
    s.start()
    return s, mic


class TestSessionThread(unittest.TestCase):
    def test_send_keeps_the_prompt_instead_of_erasing_it(self):
        s, mic = run(["write the migration"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        sent = s.send()
        self.assertEqual(sent, "write the migration")
        self.assertEqual(s.draft.text, "")
        self.assertEqual(s.thread.last, "write the migration")
        s.close()

    def test_recall_brings_it_back(self):
        s, mic = run(["write the migration", "bring back my last prompt"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        s.send()
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "write the migration")
        s.close()

    def test_recall_by_button_is_the_same_act_as_saying_it(self):
        """The bubble's "Put it back" chip after a Send calls `Session.recall()`.

        Down the same path as the spoken form on purpose: the chip exists because a
        Send that lands in the wrong window used to cost the whole utterance, and a
        second implementation of "put it back" would be a second thing to keep working.
        """
        s, mic = run(["write the migration"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        s.send()
        self.assertEqual(s.draft.text, "")
        s.recall()
        self.assertEqual(s.draft.text, "write the migration")
        s.close()

    def test_recall_never_destroys_what_is_on_screen(self):
        s, mic = run(["first prompt", "second thought", "bring back my last prompt"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        s.send()
        mic.utterance()  # starts a new draft
        s.wait_idle(timeout=5.0)
        mic.utterance()  # recall
        s.wait_idle(timeout=5.0)
        self.assertIn("second thought", s.draft.text)
        self.assertIn("first prompt", s.draft.text)
        s.close()

    def test_recall_with_nothing_sent_says_so(self):
        s, mic = run(["bring back my last prompt"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("nothing sent yet" in n for n in notes), notes)
        self.assertEqual(s.draft.text, "")
        s.close()

    def test_a_followup_carries_its_own_words(self):
        s, mic = run(["write the migration", "follow up: and add a rollback"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        s.send()
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "and add a rollback")
        self.assertTrue(s.following_up)
        s.close()

    def test_a_followup_with_nothing_sent_is_just_dictation(self):
        s, mic = run(["follow up: and add a rollback"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "and add a rollback")
        self.assertFalse(s.following_up)
        s.close()

    def test_the_cli_sees_the_thread_only_on_a_followup(self):
        # The realistic sequence: send, open a follow-up, dictate into it, then ask
        # for a rewrite. The follow-up's own words are dictation, not an instruction.
        s, mic = run([
            "write the migration",
            "follow up: and add a rollback",
            "make it more formal",
        ])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        s.send()
        mic.utterance()  # the follow-up
        s.wait_idle(timeout=5.0)
        with mock.patch("flow.session.refine", return_value=("OK", "codex")) as r:
            mic.utterance()  # the rewrite
            s.wait_idle(timeout=5.0)
            for _ in range(3):
                s.tick()
        self.assertTrue(r.called)
        self.assertEqual(r.call_args.kwargs.get("context"), ["write the migration"])
        s.close()

    def test_an_ordinary_rewrite_carries_no_thread_context(self):
        s, mic = run(["write the migration", "make it more formal"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        with mock.patch("flow.session.refine", return_value=("OK", "codex")) as r:
            mic.utterance()
            s.wait_idle(timeout=5.0)
            for _ in range(3):
                s.tick()
        self.assertEqual(r.call_args.kwargs.get("context"), [])
        s.close()

    def test_send_ends_the_followup(self):
        s, mic = run(["write the migration", "follow up: and a rollback"])
        mic.utterance()
        s.wait_idle(timeout=5.0)
        s.send()
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertTrue(s.following_up)
        s.send()
        self.assertFalse(s.following_up)
        self.assertEqual(len(s.thread), 2)
        s.close()


class TestContextInThePrompt(unittest.TestCase):
    def test_prior_turns_are_labelled_background(self):
        fake = fake_popen("REVISED", stderr="")
        with mock.patch("subprocess.Popen", return_value=fake) as run_:
            refine("and a rollback", "make it formal",
                   context=["write the migration"])
        sent = run_.call_args.args[0][-1]
        self.assertIn("write the migration", sent)
        self.assertIn("background only", sent)
        self.assertIn("do not repeat or rewrite", sent)

    def test_no_context_means_no_extra_prompt(self):
        fake = fake_popen("REVISED", stderr="")
        with mock.patch("subprocess.Popen", return_value=fake) as run_:
            refine("and a rollback", "make it formal")
        self.assertNotIn("EARLIER IN THIS THREAD", run_.call_args.args[0][-1])


if __name__ == "__main__":
    unittest.main()
