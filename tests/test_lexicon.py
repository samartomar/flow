"""Tests for the personal lexicon (P4).

The file is edited by a user mid-task, so the parsing has to be forgiving of exactly
what people type into a text file — trailing spaces, blank lines, a comment, the same
name twice — and the cap has to drop whole terms rather than half of one.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.asr import WhisperTranscriber, decode_options  # noqa: E402
from flow.lexicon import (  # noqa: E402
    MAX_TERM_CHARS,
    MAX_TERMS,
    NUL_PATH,
    Lexicon,
    as_hotwords,
    parse,
)


class TestParse(unittest.TestCase):
    def test_one_term_per_line(self):
        self.assertEqual(parse("Kubernetes\nkubectl\nGrafana"),
                         ["Kubernetes", "kubectl", "Grafana"])

    def test_comments_blank_lines_and_stray_whitespace(self):
        text = "# my terms\n\n  Grafana  \n\nkubectl # the cli\n   \n"
        self.assertEqual(parse(text), ["Grafana", "kubectl"])

    def test_duplicates_go_case_insensitively(self):
        self.assertEqual(parse("Grafana\ngrafana\nGRAFANA"), ["Grafana"])

    def test_multi_word_terms_are_kept_whole(self):
        # "Elastic Beanstalk" is one thing, and the user typed it on one line.
        self.assertEqual(parse("Elastic Beanstalk\nSamir"),
                         ["Elastic Beanstalk", "Samir"])

    def test_absurdly_long_lines_are_skipped(self):
        text = "x" * (MAX_TERM_CHARS + 1) + "\nSamir"
        self.assertEqual(parse(text), ["Samir"])

    def test_the_cap_drops_whole_terms_from_the_end(self):
        terms = parse("\n".join(f"term{i}" for i in range(MAX_TERMS + 20)))
        self.assertEqual(len(terms), MAX_TERMS)
        self.assertEqual(terms[0], "term0")
        self.assertEqual(terms[-1], f"term{MAX_TERMS - 1}")


class TestAsHotwords(unittest.TestCase):
    def test_terms_join_with_spaces(self):
        self.assertEqual(as_hotwords(["Grafana", "kubectl"]), "Grafana kubectl")

    def test_empty_is_none_not_empty_string(self):
        # An empty string still makes the library build a prompt prefix.
        self.assertIsNone(as_hotwords([]))
        self.assertIsNone(as_hotwords(["", "  "]))


class TestLexiconFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "lexicon.txt"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_file_is_not_an_error(self):
        lex = Lexicon(self.path)
        self.assertEqual(lex.terms(), [])
        self.assertIsNone(lex.hotwords())

    def test_reads_the_file(self):
        self.path.write_text("Grafana\nkubectl\n", encoding="utf-8")
        self.assertEqual(Lexicon(self.path).hotwords(), "Grafana kubectl")

    def test_picks_up_an_edit_without_a_restart(self):
        self.path.write_text("Grafana\n", encoding="utf-8")
        lex = Lexicon(self.path)
        self.assertEqual(lex.hotwords(), "Grafana")
        # Same mtime resolution on some filesystems, so the size change is what this
        # asserts is also being watched.
        self.path.write_text("Grafana\nSamir\n", encoding="utf-8")
        self.assertEqual(lex.hotwords(), "Grafana Samir")

    def test_a_deleted_file_clears_the_terms(self):
        self.path.write_text("Grafana\n", encoding="utf-8")
        lex = Lexicon(self.path)
        self.assertEqual(lex.terms(), ["Grafana"])
        self.path.unlink()
        self.assertEqual(lex.terms(), [])

    def test_undecodable_bytes_do_not_crash(self):
        self.path.write_bytes(b"Grafana\n\xff\xfe\nSamir\n")
        self.assertIn("Grafana", Lexicon(self.path).terms())


class TestDisabled(unittest.TestCase):
    def test_the_nul_path_never_exists(self):
        # --no-lexicon points here, so it must stay absent whatever the install layout.
        self.assertFalse(NUL_PATH.exists())
        self.assertEqual(Lexicon(NUL_PATH).terms(), [])
        self.assertIsNone(Lexicon(NUL_PATH).hotwords())


class TestDecodeOptionsCarryHotwords(unittest.TestCase):
    def test_absent_by_default(self):
        for final in (False, True):
            self.assertNotIn("hotwords", decode_options(final))

    def test_present_when_given(self):
        opts = decode_options(True, "Grafana kubectl")
        self.assertEqual(opts["hotwords"], "Grafana kubectl")
        # And the rest of the config is untouched.
        self.assertEqual(opts["beam_size"], decode_options(True)["beam_size"])

    def test_empty_hotwords_are_not_passed(self):
        self.assertNotIn("hotwords", decode_options(True, ""))
        self.assertNotIn("hotwords", decode_options(True, None))


class TestTranscriberUsesTheLexicon(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "lexicon.txt"

    def tearDown(self):
        self.dir.cleanup()

    def _kwargs(self, final):
        fake = mock.Mock()
        fake.transcribe.return_value = ([], None)
        with mock.patch("faster_whisper.WhisperModel", return_value=fake):
            asr = WhisperTranscriber(lexicon=Lexicon(self.path))
            asr.text(np.zeros(1600, dtype=np.float32), final=final)
        return fake.transcribe.call_args.kwargs

    def test_both_tiers_are_biased(self):
        # The partial should show the user's spelling too, not only the final: the
        # measured cost is +6% on a partial with a full lexicon.
        self.path.write_text("Grafana\nSamir\n", encoding="utf-8")
        for final in (False, True):
            self.assertEqual(self._kwargs(final)["hotwords"], "Grafana Samir")

    def test_no_lexicon_means_no_prompt_prefix(self):
        for final in (False, True):
            self.assertNotIn("hotwords", self._kwargs(final))


if __name__ == "__main__":
    unittest.main()
