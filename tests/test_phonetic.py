"""Tests for phonetic target matching (defect 4, second half).

The failure this fixes is quiet and expensive: the user says "change Sameer to Samir",
the draft says "summer" because the same voice was transcribed the same way a moment
earlier, the exact matcher finds nothing, and a free local edit becomes a 7 s CLI call
over text that does not contain the word.

The tests that matter most are the negative ones. A phonetic matcher that is too eager
rewrites the wrong words silently, which is worse than escalating.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.edits import apply_local, plan  # noqa: E402
from flow.phonetic import (  # noqa: E402
    MATCH_THRESHOLD,
    double_metaphone,
    find_span,
    find_spans,
    similarity,
    sounds_like,
)


class TestKeys(unittest.TestCase):
    def test_the_case_this_exists_for(self):
        self.assertEqual(double_metaphone("Sameer")[0], "SMR")
        self.assertEqual(double_metaphone("Samir")[0], "SMR")
        self.assertEqual(double_metaphone("summer")[0], "SMR")

    def test_spelling_variants_share_a_key(self):
        for a, b in [
            ("Smith", "Smyth"), ("Katherine", "Catherine"), ("phone", "fone"),
            ("night", "nite"), ("Nakamura", "Nakamora"), ("release", "realease"),
        ]:
            with self.subTest(pair=(a, b)):
                self.assertTrue(sounds_like(a, b), f"{a} / {b}")

    def test_different_words_do_not(self):
        for a, b in [
            ("delete", "complete"), ("report", "support"), ("Bob", "Alice"),
            ("cat", "dog"), ("Tuesday", "Thursday"),
        ]:
            with self.subTest(pair=(a, b)):
                self.assertFalse(sounds_like(a, b), f"{a} / {b}")

    def test_empty_and_vowel_only_input(self):
        self.assertEqual(double_metaphone(""), ("", ""))
        self.assertEqual(double_metaphone("!!!"), ("", ""))
        # A word encoding to nothing must not match everything.
        self.assertFalse(sounds_like("", "anything"))

    def test_alternate_reading_exists_where_english_is_ambiguous(self):
        primary, alternate = double_metaphone("chair")
        self.assertNotEqual(primary, alternate)

    def test_similarity_is_bounded_and_identity_is_one(self):
        self.assertEqual(similarity("Sameer", "Sameer"), 1.0)
        self.assertEqual(similarity("", "x"), 0.0)
        for a, b in [("Sameer", "summer"), ("cat", "dog"), ("delete", "complete")]:
            with self.subTest(pair=(a, b)):
                self.assertGreaterEqual(similarity(a, b), 0.0)
                self.assertLessEqual(similarity(a, b), 1.0)


class TestFindSpan(unittest.TestCase):
    DRAFT = "Meeting on Tuesday with summer about the release notes."

    def test_exact_match_still_wins_and_is_the_last_occurrence(self):
        text = "Call Bob today and tell Bob the news."
        span = find_span(text, "Bob")
        self.assertEqual(text[span[0]:span[1]], "Bob")
        self.assertEqual(span[0], text.rfind("Bob"))

    def test_the_mis_transcribed_name(self):
        span = find_span(self.DRAFT, "Sameer")
        self.assertIsNotNone(span)
        self.assertEqual(self.DRAFT[span[0]:span[1]], "summer")

    def test_a_lost_word_boundary(self):
        text = "Call some ear tomorrow about the deploy."
        span = find_span(text, "Sameer")
        self.assertIsNotNone(span)
        self.assertEqual(text[span[0]:span[1]], "some ear")

    def test_absent_targets_return_nothing(self):
        for target in ("deployment", "Alice", "Friday", "parser"):
            with self.subTest(target=target):
                self.assertIsNone(find_span(self.DRAFT, target))

    def test_empty_inputs(self):
        self.assertIsNone(find_span("", "Sameer"))
        self.assertIsNone(find_span(self.DRAFT, ""))
        self.assertIsNone(find_span(self.DRAFT, "   "))

    def test_threshold_is_the_measured_one(self):
        # Swept in scripts/command_bench.py: 10/10 recall, 4 false spans in 354.
        self.assertEqual(MATCH_THRESHOLD, 0.82)

    def test_find_spans_returns_every_occurrence_left_to_right(self):
        text = "summer called, then some ear replied, and summer left."
        spans = find_spans(text, "Sameer")
        self.assertGreaterEqual(len(spans), 2)
        self.assertEqual(spans, sorted(spans))
        for begin, end in spans:
            self.assertIn(text[begin:end].strip(" .,"), {"summer", "some ear"})

    def test_find_spans_does_not_overlap(self):
        text = "summer summer summer"
        spans = find_spans(text, "Sameer")
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            self.assertLessEqual(b1, a2)


class TestPhoneticEditsEndToEnd(unittest.TestCase):
    """The point of all of it: a correction lands locally instead of paying for a CLI."""

    def test_replace_finds_the_mis_transcribed_target(self):
        text = "Meeting on Tuesday with summer about the release."
        p = plan("change Sameer to Samir", text)
        self.assertEqual(p.kind, "local", "should not have escalated to the CLI")
        out, ok = apply_local(text, p)
        self.assertTrue(ok)
        self.assertEqual(out, "Meeting on Tuesday with Samir about the release.")

    def test_delete_finds_it_too(self):
        text = "Send the realease notes today."
        out, ok = apply_local(text, plan("delete release", text))
        self.assertTrue(ok)
        self.assertEqual(out, "Send the notes today.")

    def test_case_ops_transform_the_drafts_own_spelling(self):
        text = "tell nakamora it is ready."
        out, ok = apply_local(text, plan("capitalize Nakamura", text))
        self.assertTrue(ok)
        self.assertEqual(out, "tell Nakamora it is ready.")

    def test_replace_all_covers_variant_spellings(self):
        text = "summer called and some ear replied."
        out, ok = apply_local(text, plan("replace all Sameer with Samir", text))
        self.assertTrue(ok)
        self.assertEqual(out, "Samir called and Samir replied.")

    def test_an_absent_target_still_escalates(self):
        # The escape hatch has to keep working: "change X to Y" with no findable X is
        # an instruction for the CLI, not a local edit on whatever sounded closest.
        text = "Meeting on Tuesday with Sameer."
        self.assertEqual(plan("change Friday to Monday", text).kind, "semantic")

    def test_delete_range_uses_sound_at_both_ends(self):
        text = "Keep this, drop everything in between, keep the end."
        out, ok = apply_local(text, plan("delete from drop to betwene", text))
        self.assertTrue(ok)
        self.assertEqual(out, "Keep this, keep the end.")


if __name__ == "__main__":
    unittest.main()
