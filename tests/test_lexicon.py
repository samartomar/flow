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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from flow.asr import WhisperTranscriber, decode_options  # noqa: E402
from flow.edits import plan  # noqa: E402
from flow.lexicon import (  # noqa: E402
    MAX_TERM_CHARS,
    MAX_TERMS,
    NUL_PATH,
    TEMPLATE,
    Lexicon,
    as_hotwords,
    ensure,
    pairs,
    parse,
    substitute,
)
from live_check import DRAFT  # noqa: E402


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


class _Segment:
    """One kept segment, shaped like faster-whisper's, with confident scores."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.no_speech_prob = 0.01
        self.avg_logprob = -0.2


class TestCorrectionsParseAlongsideTerms(unittest.TestCase):
    """A line with an arrow is a correction, not a term.

    The two live in one file because the user owns one file. What separates them is
    what they *do*: a term biases the decoder toward a spelling, an arrow rewrites the
    decoder's output. Parsing them apart is the whole reason a correction can exist at
    all — as ordinary terms, `semir -> Samir` would bias the decoder toward "semir",
    the spelling the user is trying to get rid of.
    """

    def test_terms_and_corrections_coexist(self):
        text = "Samir\nsemir -> Samir\nkubectl"
        self.assertEqual(parse(text), ["Samir", "kubectl"])
        self.assertEqual(pairs(text), [("semir", "Samir")])

    def test_the_arrow_side_never_becomes_a_hotword(self):
        # The measured harm of biasing (14-38% relative WER on term-free speech) is why
        # a correction is a substitution instead. Adding either side as a hotword would
        # buy the cost back.
        self.assertEqual(parse("semir -> Samir"), [])
        self.assertIsNone(as_hotwords(parse("semir -> Samir")))

    def test_comments_still_work_on_a_correction_line(self):
        self.assertEqual(pairs("semir -> Samir  # my name, every time"),
                         [("semir", "Samir")])

    def test_spacing_around_the_arrow_is_the_users_business(self):
        for line in ("semir->Samir", "semir ->Samir", "semir   ->   Samir"):
            self.assertEqual(pairs(line), [("semir", "Samir")], line)

    def test_a_correction_can_be_more_than_one_word(self):
        self.assertEqual(pairs("cube cuttle -> kubectl"), [("cube cuttle", "kubectl")])

    def test_a_half_written_line_is_ignored_rather_than_guessed_at(self):
        self.assertEqual(pairs("-> Samir\nsemir ->\n->"), [])
        self.assertEqual(parse("-> Samir\nsemir ->\n->"), [])

    def test_an_identical_pair_is_a_no_op_but_a_case_fix_is_not(self):
        self.assertEqual(pairs("samir -> samir"), [])
        # "priya" -> "Priya" is the commonest correction there is; see profile.learn_pair.
        self.assertEqual(pairs("priya -> Priya"), [("priya", "Priya")])

    def test_the_first_spelling_of_a_left_side_wins(self):
        self.assertEqual(pairs("semir -> Samir\nSEMIR -> Sameer"), [("semir", "Samir")])

    def test_an_absurdly_long_side_is_skipped(self):
        long = "x" * (MAX_TERM_CHARS + 1)
        self.assertEqual(pairs(f"{long} -> Samir\nsemir -> {long}"), [])

    def test_the_cap_counts_terms_and_corrections_together(self):
        # One prompt budget, one file, one cap: 64 corrections must not buy the user
        # 64 more hotwords than the cap allows.
        text = "\n".join(
            f"term{i}" if i % 2 else f"wrong{i} -> Right{i}" for i in range(MAX_TERMS * 2)
        )
        self.assertEqual(len(parse(text)) + len(pairs(text)), MAX_TERMS)


class TestSubstitution(unittest.TestCase):
    """What a declared correction does to a line of decoded text."""

    PAIRS = [("semir", "Samir"), ("cube cuttle", "kubectl")]

    def test_the_right_side_is_written_verbatim(self):
        self.assertEqual(substitute("Change Semir to me", self.PAIRS),
                         "Change Samir to me")

    def test_the_left_side_ignores_case(self):
        for heard in ("semir", "Semir", "SEMIR", "SeMiR"):
            self.assertEqual(substitute(heard, self.PAIRS), "Samir")

    def test_nothing_fires_inside_a_word(self):
        # The user declared a word, not a substring. "semiramis" is not their name.
        self.assertEqual(substitute("semiramis and cassemir", self.PAIRS),
                         "semiramis and cassemir")

    def test_punctuation_is_a_boundary(self):
        self.assertEqual(substitute("Hi, semir. Ask semir?", self.PAIRS),
                         "Hi, Samir. Ask Samir?")

    def test_a_multi_word_left_side_matches_as_a_phrase(self):
        self.assertEqual(substitute("run cube cuttle get pods", self.PAIRS),
                         "run kubectl get pods")

    def test_one_pass_only_so_corrections_cannot_chain(self):
        # a -> b -> c would make the file's meaning depend on line order in a way
        # nobody typing it intends, and a cycle would not terminate.
        self.assertEqual(substitute("a b", [("a", "b"), ("b", "c")]), "b c")

    def test_no_corrections_is_the_identity(self):
        self.assertEqual(substitute("nothing to do here", []), "nothing to do here")

    def test_regex_metacharacters_in_the_file_are_literal(self):
        self.assertEqual(substitute("what c++ is", [("c++", "cpp")]), "what cpp is")


class TestTheFileCarriesCorrections(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "lexicon.txt"

    def tearDown(self):
        self.dir.cleanup()

    def test_no_file_means_no_corrections_and_apply_is_the_identity(self):
        lex = Lexicon(self.path)
        self.assertEqual(lex.pairs(), [])
        self.assertEqual(lex.apply("Change Semir to Samir"), "Change Semir to Samir")

    def test_an_edit_lands_on_the_next_utterance(self):
        self.path.write_text("Grafana\n", encoding="utf-8")
        lex = Lexicon(self.path)
        self.assertEqual(lex.apply("ask semir"), "ask semir")
        self.path.write_text("Grafana\nsemir -> Samir\n", encoding="utf-8")
        self.assertEqual(lex.apply("ask semir"), "ask Samir")
        self.assertEqual(lex.hotwords(), "Grafana")


class TestTheDecodersOutputIsCorrected(unittest.TestCase):
    """The substitution has to land before anything reads the text.

    Routing, the undo stack and the paste all see whatever `text()` returns, so this is
    the one place a correction is worth applying — after `normalise`, so a pair matches
    tidied words rather than raw decoder markers.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "lexicon.txt"

    def tearDown(self):
        self.dir.cleanup()

    def _decode(self, heard: str) -> str:
        fake = mock.Mock()
        fake.transcribe.return_value = ([_Segment(heard)], None)
        with mock.patch("faster_whisper.WhisperModel", return_value=fake):
            asr = WhisperTranscriber(lexicon=Lexicon(self.path))
            return asr.text(np.zeros(1600, dtype=np.float32), final=True)

    def test_the_pair_is_applied_to_what_the_model_wrote(self):
        self.path.write_text("semir -> Samir\n", encoding="utf-8")
        self.assertEqual(self._decode("Change Semir to Samir"), "Change Samir to Samir")

    def test_a_correction_only_file_biases_nothing(self):
        self.path.write_text("semir -> Samir\n", encoding="utf-8")
        fake = mock.Mock()
        fake.transcribe.return_value = ([], None)
        with mock.patch("faster_whisper.WhisperModel", return_value=fake):
            asr = WhisperTranscriber(lexicon=Lexicon(self.path))
            asr.text(np.zeros(1600, dtype=np.float32), final=True)
        self.assertNotIn("hotwords", fake.transcribe.call_args.kwargs)


class TestTheLiveCheckReplay(unittest.TestCase):
    """Live run 1 (commit `5649ee3`), stage D item 2, verbatim from live-check.json.

    Prompted "change sameer to Samir"; decoded "Change Semir to Samir". The name never
    survived decoding, so the target was a word the draft does not contain, and the
    router escalated to a ~7 s CLI call to apply a rewrite the user could have had
    locally. This is the failure the feature is for.
    """

    HEARD = "Change Semir to Samir"

    def test_today_a_mis_heard_name_escalates_to_the_cli(self):
        self.assertEqual(plan(self.HEARD, DRAFT).kind, "semantic")

    def test_the_declared_pair_routes_it_locally(self):
        corrected = substitute(self.HEARD, [("semir", "Samir")])
        self.assertEqual(corrected, "Change Samir to Samir")
        p = plan(corrected, DRAFT)
        self.assertEqual((p.kind, p.op), ("local", "replace"))


@unittest.skipUnless(sys.platform == "win32", "Windows-only: os.startfile")
class TestTheSettingsFolderOpens(unittest.TestCase):
    """The menu entry, and the template it writes the first time.

    Driven without a Tk window, the way `_pump_warnings` is: the method under test is
    a file write and one shell call, and a real pill would need a desktop.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "settings" / "lexicon.txt"

    def tearDown(self):
        self.dir.cleanup()

    def _pill(self):
        import flow.ui as ui

        pill = ui.Pill.__new__(ui.Pill)
        pill.bubble = mock.Mock()
        pill._flash = 0
        pill.settings_path = self.path
        return pill

    def test_the_first_open_writes_the_template_and_shows_the_folder(self):
        pill = self._pill()
        with mock.patch("os.startfile") as started:
            pill._open_settings()
        self.assertTrue(self.path.exists())
        started.assert_called_once_with(self.path.parent)

    def test_the_template_says_what_all_three_settings_are_for(self):
        self.assertIn("->", TEMPLATE)          # corrections
        self.assertIn("profile.json", TEMPLATE)  # preferences that have a value
        # The measured cost of biasing is stated where someone is about to add terms.
        self.assertRegex(TEMPLATE, r"\d+-\d+%")

    def test_the_template_is_all_comments_so_the_lexicon_stays_opt_in(self):
        # Creating the file must not switch biasing on for someone who only opened
        # the folder: the whole feature is opt-in because the harm is measured.
        self.assertEqual(parse(TEMPLATE), [])
        self.assertEqual(pairs(TEMPLATE), [])

    def test_a_second_open_keeps_what_the_user_wrote(self):
        ensure(self.path)
        self.path.write_text("semir -> Samir\n", encoding="utf-8")
        with mock.patch("os.startfile"):
            self._pill()._open_settings()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "semir -> Samir\n")

    def test_a_shell_that_refuses_says_so_instead_of_killing_the_frame(self):
        pill = self._pill()
        with mock.patch("os.startfile", side_effect=OSError("no handler")):
            pill._open_settings()
        pill.bubble.note.assert_called_once()
        self.assertIn(str(self.path.parent), pill.bubble.note.call_args.args[0])


class TestTheMenuOffersIt(unittest.TestCase):
    """The entry has to be *in* the menu, not merely implemented.

    `_menu` builds a native popup, so the menu itself is faked; what this pins is that
    the command exists, is labelled, and calls the opener.
    """

    def test_open_settings_folder_is_a_menu_command(self):
        import tkinter as tk

        import flow.ui as ui

        pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(mode=ui.DICTATE, speaker=None, profile=None)
        pill.settings_path = Path(tempfile.mkdtemp()) / "lexicon.txt"
        pill.armed = False  # the Listen row reads it for its label
        commands: dict = {}

        class FakeMenu:
            def __init__(self, *a, **kw):
                pass

            def add_command(self, label="", command=None, **kw):
                commands[label] = command

            def add_separator(self):
                pass

            def add_cascade(self, label="", menu=None, **kw):
                pass

            def tk_popup(self, *a):
                pass

            def grab_release(self):
                pass

        with mock.patch.object(tk, "Menu", FakeMenu), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0), \
                mock.patch.object(ui, "_user32"), \
                mock.patch.object(ui.Pill, "_open_settings") as opener:
            pill._menu(mock.Mock(x_root=0, y_root=0))
        self.assertIn("Open settings folder", commands)
        commands["Open settings folder"]()
        opener.assert_called_once()


if __name__ == "__main__":
    unittest.main()
