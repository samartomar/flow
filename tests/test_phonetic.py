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


class TestExactMeansTheWordNotTheLetters(unittest.TestCase):
    """DRAFT-01: the *confident* path was the destructive one.

    `find_span` and `find_spans` tried an unrestricted substring scan first, so "art"
    matched inside "cart" and the planner — which asks `in_draft` the same way — read that
    as a literal correction it could apply for free. The fuzzy fallback underneath has
    always thought in whitespace-delimited word windows and was never the problem.

    That inversion is what makes this the sharpest finding in the audit. Every other
    matching defect ends in an escalation to the CLI, which costs seven seconds and no
    text. This one ends in a silent, confident, destructive edit: `delete art` turning
    "the cart is red" into "the c is red" while the router records a clean `local` route.

    Three reproductions, all from the validation, all as negative tests here.
    """

    def test_delete_does_not_carve_a_word_open(self):
        # Not `assertIsNone`, which is what this asserted first and was the wrong
        # question. The exact path does refuse — but "art" and "cart" score 0.857 against
        # a 0.82 threshold, so the *fuzzy* fallback then matches "cart" as a whole word,
        # which is that path doing its documented job (the two genuinely sound alike, and
        # a mis-dictation between them is exactly what it exists for).
        #
        # The invariant worth pinning is therefore the one that holds of both paths: a
        # span is a whole word, never letters carved out of one. Before, this returned
        # (5, 8) — "art" cut out of the middle of "cart", leaving "c".
        span = find_span("the cart is red", "art")
        self.assertEqual(span, (4, 8))
        self.assertEqual("the cart is red"[span[0]:span[1]], "cart")

    def test_replace_all_leaves_unrelated_words_whole(self):
        self.assertEqual(find_spans("cart art cart", "art"), [(5, 8)])

    def test_capitalize_does_not_reach_inside_a_longer_word(self):
        self.assertIsNone(find_span("please concatenate the list", "cat"))

    def test_the_word_itself_still_matches(self):
        # The guard must not become "exact matching never fires", which is the failure
        # mode a boundary rule invites and the reason every negative has a positive here.
        self.assertEqual(find_span("the art is red", "art"), (4, 7))

    def test_the_last_occurrence_is_still_preferred(self):
        # Documented behaviour, unchanged: a spoken correction refers to what was just
        # said. The boundary walk searches backwards for exactly this reason.
        self.assertEqual(find_span("art and more art", "art"), (13, 16))

    def test_it_skips_a_mid_word_hit_to_reach_a_real_one(self):
        # The case that decides whether the rule was implemented as a filter or as a
        # veto: the *last* substring hit is inside "cart", and there is a genuine word
        # earlier. A veto returns None and escalates; a filter finds the real one.
        self.assertEqual(find_span("the art is in the cart", "art"), (4, 7))

    def test_punctuation_around_the_word_is_still_a_boundary(self):
        self.assertEqual(find_span("Meeting on Tuesday.", "Tuesday"), (11, 18))
        self.assertEqual(find_span('he said "art" loudly', "art"), (9, 12))

    def test_a_target_carrying_its_own_full_stop_still_matches(self):
        self.assertEqual(find_span("Meeting on Tuesday.", "Tuesday."), (11, 19))

    def test_a_possessive_is_not_carved_open(self):
        # An apostrophe is word-internal in English, so "art" must not match inside
        # "art's" and leave the user with "'s". Refused here, and the fuzzy fallback is
        # what recovers the genuinely-quoted case one line below.
        self.assertIsNone(find_span("the art's colour", "art"))

    def test_a_multi_word_target_needs_boundaries_at_both_ends(self):
        self.assertIsNone(find_span("the shortcart artichoke", "cart artichoke"[:12]))
        self.assertEqual(find_span("send the art file", "the art"), (5, 12))

    def test_replace_all_still_finds_every_real_occurrence(self):
        self.assertEqual(find_spans("art and art again", "art"), [(0, 3), (8, 11)])


class TestTheBoundaryRuleReachesThePlanner(unittest.TestCase):
    """`in_draft` asks `find_span`, so the routing gate moves with it.

    This is the half that matters to the user. With no span, "delete art" is no longer a
    confident local edit against a word that is not there — it becomes dictation, which
    is recoverable with one undo. The audit's phrase for the old behaviour was
    "destructive silent text corruption", and the word doing the work is *silent*.
    """

    def test_delete_art_no_longer_leaves_a_severed_word(self):
        # "the c is red" was the audit's headline reproduction, and the damage in it is
        # the orphan "c" — a fragment no undo history explains and no reader can parse.
        # The fuzzy path now takes "cart" whole instead, which is a deletion the user can
        # see and undo in one word. Whether it should match at all is a threshold
        # question and is in NEEDS_YOU; it is not this item's, which is the substring
        # scan.
        text = "the cart is red"
        p = plan("delete art", text)
        new, applied = apply_local(text, p)
        self.assertTrue(applied)
        self.assertNotEqual(new, "the c is red")
        self.assertNotIn(" c ", new, "a word was severed rather than removed")
        self.assertEqual(new, "the is red")

    def test_replace_all_art_no_longer_corrupts_cart(self):
        text = "cart art cart"
        p = plan("replace all art with x", text)
        new, _applied = apply_local(text, p)
        self.assertNotEqual(new, "cx x cx")
        self.assertIn("cart", new)

    def test_capitalize_cat_no_longer_reaches_concatenate(self):
        text = "please concatenate the list"
        p = plan("capitalize cat", text)
        new, _applied = apply_local(text, p)
        self.assertNotIn("conCatenate", new)

    def test_a_real_correction_still_applies_for_free(self):
        text = "the art is red"
        p = plan("delete art", text)
        self.assertEqual(p.kind, "local", "a genuine correction escalated to the CLI")
        new, applied = apply_local(text, p)
        self.assertTrue(applied)
        self.assertEqual(new, "the is red")

    def test_a_real_replace_all_still_applies(self):
        text = "art and art again"
        p = plan("replace all art with sketch", text)
        new, applied = apply_local(text, p)
        self.assertTrue(applied)
        self.assertEqual(new, "sketch and sketch again")
