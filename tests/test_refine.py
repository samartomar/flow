"""Tests for the CLI adapter's guards (R11), and for saying what they did.

These guards are the reason the agent CLI cannot hurt the user: bounded input, hard
timeout, and a refusal to paste commentary into their text. All of them only matter in
failure cases, which is exactly the code least likely to be exercised by hand.

The bound on input is the one the user can *feel* without being told — a long draft is
refined only at the end, and from outside that looks like the CLI ignoring most of what
was asked. The last class here is about that being said out loud.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.refine import MAX_CHARS, Cli, _split_tail, refine  # noqa: E402
from flow.session import Session  # noqa: E402

CLI = Cli("codex", ("codex", "exec"))


def fake_proc(stdout: str = "", returncode: int = 0, stderr: str = "", *,
              hang: bool = False):
    """A `Popen` with the surface `_invoke` uses, and nothing else.

    `hang=True` never completes, which is how a timeout is reproduced without waiting
    for one. `poll` reports an exit either way, so the guard that kills a live tree is
    not asked to kill a mock. What that guard does to a real process tree is measured
    in `test_lifecycle.py`, which is the only place a real one is started.
    """
    proc = mock.Mock(returncode=returncode, pid=0)
    if hang:
        proc.communicate.side_effect = subprocess.TimeoutExpired("codex", 0)
    else:
        proc.communicate.return_value = (stdout, stderr)
    proc.poll.return_value = returncode
    return proc


class TestTailSplit(unittest.TestCase):
    def test_short_text_is_sent_whole(self):
        head, tail = _split_tail("short enough")
        self.assertEqual(head, "")
        self.assertEqual(tail, "short enough")

    def test_long_text_sends_only_the_tail(self):
        text = "A sentence. " * 400  # ~4800 chars
        head, tail = _split_tail(text)
        self.assertLessEqual(len(tail), MAX_CHARS)
        self.assertEqual(head + tail, text, "splitting must be lossless")

    def test_split_lands_on_a_sentence_boundary(self):
        text = "Alpha. " * 500
        _head, tail = _split_tail(text)
        self.assertTrue(tail.startswith("Alpha"), f"fragment: {tail[:20]!r}")


class TestGuards(unittest.TestCase):
    def test_head_is_preserved_and_tail_replaced(self):
        text = "Old sentence. " * 300
        head, tail = _split_tail(text)
        with mock.patch("subprocess.Popen", return_value=fake_proc("REVISED")):
            out, note = refine(text, "shorten this", cli=CLI)
        self.assertEqual(note, "codex")
        self.assertEqual(out, head + "REVISED")
        self.assertNotIn("REVISED", head)

    def test_commentary_is_refused(self):
        # A ballooning reply is the model explaining itself, not revising.
        chatty = "Certainly! Here is the revised version you asked for. " * 40
        with mock.patch("subprocess.Popen", return_value=fake_proc(chatty)):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("commentary", note)

    def test_timeout_is_non_destructive(self):
        with mock.patch("subprocess.Popen", return_value=fake_proc(hang=True)):
            out, note = refine("ship it", "make it formal", cli=CLI, timeout=0.2)
        self.assertIsNone(out)
        self.assertIn("timed out", note)

    def test_nonzero_exit_is_reported(self):
        with mock.patch(
            "subprocess.Popen", return_value=fake_proc("", 1, "not logged in\nmore")
        ):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("not logged in", note)

    def test_empty_output_is_refused(self):
        with mock.patch("subprocess.Popen", return_value=fake_proc("   \n")):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("nothing", note)

    def test_code_fences_are_stripped(self):
        with mock.patch("subprocess.Popen", return_value=fake_proc("```\nShip it.\n```")):
            out, _note = refine("ship it", "make it formal", cli=CLI)
        self.assertEqual(out, "Ship it.")

    def test_stdin_is_closed(self):
        """codex blocks reading stdin; without DEVNULL the call hangs to the timeout."""
        with mock.patch("subprocess.Popen", return_value=fake_proc("ok")) as popen:
            refine("ship it", "make it formal", cli=CLI)
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_missing_cli_is_reported_not_raised(self):
        with mock.patch("flow.refine.available", return_value=[]):
            out, note = refine("ship it", "make it formal")
        self.assertIsNone(out)
        self.assertIn("no agent CLI", note)


class Silent:
    """No mic, no model. These tests are about what the session *says*."""

    level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        return []

    @property
    def active(self) -> bool:
        return True

    def load(self) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


#: Long enough to be cut, and made of sentences so the cut lands on a boundary rather
#: than at exactly MAX_CHARS — which is what makes the reported number worth checking.
LONG = "Alpha bravo charlie. " * 300


class TestTheBoundOnInputIsVisible(unittest.TestCase):
    """R11 caps what the CLI is handed, and that used to happen in silence.

    A Refine keeps the head verbatim and reattaches it, so nothing is lost — but "I
    asked it to shorten this and it only shortened the end" is a defect report waiting
    to be filed unless the app says which part it sent. An Ask is worse: the head of an
    over-long question is never sent at all, so the answer is to a question the user did
    not ask, and nothing anywhere said so.
    """

    def session(self) -> Session:
        s = Session(asr=Silent(), mic=Silent())
        self.addCleanup(s.close)
        return s

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def refined(self, text: str) -> str:
        s = self.session()
        s.draft.set(text)
        with mock.patch("flow.session.refine", return_value=("REVISED", "codex")):
            s._start_refine("make it formal")
        return self.notes(s)

    def asked(self, text: str) -> str:
        s = self.session()
        with mock.patch("flow.session.ask", return_value=("answer", "codex")):
            s._start_ask(text)
        return self.notes(s)

    def test_a_short_draft_says_nothing_about_length(self):
        self.assertNotIn("characters", self.refined("ship it on Friday"))

    def test_a_long_draft_says_how_much_of_it_went(self):
        self.assertIn("characters", self.refined(LONG))

    def test_and_says_the_rest_is_left_alone(self):
        # The head is reattached verbatim, so this is a promise, not a hedge.
        self.assertIn("left as it is", self.refined(LONG))

    def test_the_number_is_the_real_cut_not_the_constant(self):
        # `_split_tail` walks forward to a sentence boundary, so the tail is shorter
        # than MAX_CHARS. A note quoting 2000 would be a guess dressed as a measurement.
        note = self.refined(LONG)
        sent = int(next(w for w in note.replace("—", " ").split() if w.isdigit()))
        self.assertEqual(sent, len(_split_tail(LONG)[1]))
        self.assertLess(sent, MAX_CHARS)

    def test_a_short_question_says_nothing_about_length(self):
        self.assertNotIn("characters", self.asked("how do I widen a column"))

    def test_an_over_long_question_says_the_start_never_went(self):
        note = self.asked(LONG)
        self.assertIn("characters", note)
        self.assertIn("never saw", note)

    def test_the_two_notes_do_not_make_the_same_promise(self):
        # A Refine keeps what it did not send; an Ask discards it. Saying the same
        # thing about both would make one of them a lie.
        self.assertNotIn("left as it is", self.asked(LONG))


class TestTailSent(unittest.TestCase):
    def test_a_short_text_goes_whole(self):
        from flow.refine import tail_sent

        self.assertEqual(tail_sent("short enough"), len("short enough"))

    def test_a_long_text_reports_only_what_the_cli_sees(self):
        from flow.refine import tail_sent

        self.assertEqual(tail_sent(LONG), len(_split_tail(LONG)[1]))
        self.assertLessEqual(tail_sent(LONG), MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
