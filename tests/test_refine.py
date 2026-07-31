"""Tests for the CLI adapter's guards (R11).

These guards are the reason the agent CLI cannot hurt the user: bounded input, hard
timeout, and a refusal to paste commentary into their text. All of them only matter in
failure cases, which is exactly the code least likely to be exercised by hand.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.refine import MAX_CHARS, Cli, _split_tail, refine  # noqa: E402

CLI = Cli("codex", ("codex", "exec"))


def fake_proc(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


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
        with mock.patch("subprocess.run", return_value=fake_proc("REVISED")):
            out, note = refine(text, "shorten this", cli=CLI)
        self.assertEqual(note, "codex")
        self.assertEqual(out, head + "REVISED")
        self.assertNotIn("REVISED", head)

    def test_commentary_is_refused(self):
        # A ballooning reply is the model explaining itself, not revising.
        chatty = "Certainly! Here is the revised version you asked for. " * 40
        with mock.patch("subprocess.run", return_value=fake_proc(chatty)):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("commentary", note)

    def test_timeout_is_non_destructive(self):
        with mock.patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 20)
        ):
            out, note = refine("ship it", "make it formal", cli=CLI, timeout=20)
        self.assertIsNone(out)
        self.assertIn("timed out", note)

    def test_nonzero_exit_is_reported(self):
        with mock.patch(
            "subprocess.run", return_value=fake_proc("", 1, "not logged in\nmore")
        ):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("not logged in", note)

    def test_empty_output_is_refused(self):
        with mock.patch("subprocess.run", return_value=fake_proc("   \n")):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("nothing", note)

    def test_code_fences_are_stripped(self):
        with mock.patch("subprocess.run", return_value=fake_proc("```\nShip it.\n```")):
            out, _note = refine("ship it", "make it formal", cli=CLI)
        self.assertEqual(out, "Ship it.")

    def test_stdin_is_closed(self):
        """codex blocks reading stdin; without DEVNULL the call hangs to the timeout."""
        with mock.patch("subprocess.run", return_value=fake_proc("ok")) as run:
            refine("ship it", "make it formal", cli=CLI)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_missing_cli_is_reported_not_raised(self):
        with mock.patch("flow.refine.available", return_value=[]):
            out, note = refine("ship it", "make it formal")
        self.assertIsNone(out)
        self.assertIn("no agent CLI", note)


if __name__ == "__main__":
    unittest.main()
