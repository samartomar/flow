"""Tests for the edit/append router — the piece that keeps the CLI off the hot path.

Worth testing properly because the router is the one component whose failures are
silent: a mis-route does not crash, it just quietly appends "change Tuesday to
Wednesday" into the user's text as if it were dictation.

    uv run python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.edits import apply_local, plan  # noqa: E402

DRAFT = "Call Bob today. The meeting is on Tuesday afternoon at nasa."


class TestRouting(unittest.TestCase):
    def test_plain_dictation_appends(self):
        for s in (
            "I will see you on Tuesday.",
            "The report needs three more sections.",
            "Change management is hard.",  # 'Change' as a noun, no connective
            # Edit-shaped but the target is not in the draft, so it is dictation:
            "Delete key handling is broken.",
            "Remove the packaging before use.",
        ):
            self.assertEqual(plan(s, DRAFT).kind, "append", s)

    def test_literal_corrections_route_local(self):
        for s in (
            "change Tuesday to Wednesday",
            "no, change Bob to Alice",
            "actually, swap Tuesday for Friday",
            "Replace Bob with Carol.",
            "delete afternoon",
            "capitalize nasa",
            "delete the last two words",
            "new paragraph",
        ):
            self.assertEqual(plan(s, DRAFT).kind, "local", s)

    def test_semantic_requests_route_to_cli(self):
        for s in (
            "make it more formal",
            "shorten this",
            "turn it into bullet points",
            "fix the grammar",
            "rewrite that as a question",
            "proofread this",
        ):
            self.assertEqual(plan(s, DRAFT).kind, "semantic", s)

    def test_strong_shape_with_absent_target_escalates_to_cli(self):
        # "change X to Y" is hard to say by accident, so an unfindable target means
        # the user did ask for something — hand it to the CLI rather than append it.
        p = plan("change Friday to Monday", DRAFT)
        self.assertEqual(p.kind, "semantic")

    def test_undo(self):
        for s in ("scratch that", "undo that", "never mind", "Strike that."):
            self.assertEqual(plan(s, DRAFT).kind, "undo", s)


class TestApply(unittest.TestCase):
    def test_replace_hits_last_occurrence(self):
        # A spoken correction refers to what was just said, not the first mention.
        text = "Call Bob today and tell Bob the news."
        out, ok = apply_local(text, plan("change Bob to Alice", text))
        self.assertTrue(ok)
        self.assertEqual(out, "Call Bob today and tell Alice the news.")

    def test_replace_is_case_insensitive_on_target(self):
        text = "Meeting on tuesday."
        out, ok = apply_local(text, plan("change Tuesday to Thursday", text))
        self.assertTrue(ok)
        self.assertEqual(out, "Meeting on Thursday.")

    def test_delete_collapses_double_space(self):
        text = "Send the final draft today."
        out, ok = apply_local(text, plan("delete final", text))
        self.assertTrue(ok)
        self.assertEqual(out, "Send the draft today.")

    def test_delete_last_words(self):
        text = "one two three four five"
        out, ok = apply_local(text, plan("delete the last two words", text))
        self.assertTrue(ok)
        self.assertEqual(out, "one two three")

    def test_delete_last_sentence(self):
        text = "First thing. Second thing. Third thing."
        out, ok = apply_local(text, plan("delete the last sentence", text))
        self.assertTrue(ok)
        self.assertEqual(out, "First thing. Second thing.")

    def test_delete_more_than_exists_is_refused(self):
        text = "only two"
        out, ok = apply_local(text, plan("delete the last five words", text))
        self.assertFalse(ok)
        self.assertEqual(out, "only two")

    def test_capitalize_is_title_case_not_shouting(self):
        # "capitalize john" -> "John". Mapping capitalize onto upper-case gave "JOHN",
        # which is the more jarring of the two possible mistakes.
        text = "tell john it is ready."
        out, ok = apply_local(text, plan("capitalize john", text))
        self.assertTrue(ok)
        self.assertEqual(out, "tell John it is ready.")

    def test_all_caps_uppercases(self):
        text = "we work at nasa now."
        out, ok = apply_local(text, plan("all caps nasa", text))
        self.assertTrue(ok)
        self.assertEqual(out, "we work at NASA now.")

    def test_lowercase_both_phrasings(self):
        text = "send the REPORT today."
        for utterance in ("lowercase REPORT", "make REPORT lowercase"):
            out, ok = apply_local(text, plan(utterance, text))
            self.assertTrue(ok, utterance)
            self.assertEqual(out, "send the report today.", utterance)

    def test_replace_all_hits_every_occurrence(self):
        text = "Bob called, then Bob left, and Bob returned."
        out, ok = apply_local(text, plan("replace all Bob with Alice", text))
        self.assertTrue(ok)
        self.assertEqual(out, "Alice called, then Alice left, and Alice returned.")

    def test_insert_before_and_after(self):
        text = "send the report."
        out, ok = apply_local(text, plan("insert final before report", text))
        self.assertTrue(ok)
        self.assertEqual(out, "send the final report.")

        out, ok = apply_local(text, plan("add today after report", text))
        self.assertTrue(ok)
        self.assertEqual(out, "send the report today.")

    def test_delete_range(self):
        text = "Keep this, drop everything in between, keep the end."
        out, ok = apply_local(text, plan("delete from drop to between", text))
        self.assertTrue(ok)
        # Removing a phrase framed by commas must not leave both commas behind.
        self.assertEqual(out, "Keep this, keep the end.")

    def test_delete_range_refuses_reversed_markers(self):
        # "to" marker appears only before the "from" marker: no valid range.
        text = "alpha beta gamma"
        out, ok = apply_local(text, plan("delete from gamma to alpha", text))
        self.assertFalse(ok)
        self.assertEqual(out, text)

    def test_pronoun_targets_go_to_the_cli(self):
        text = "some existing draft text"
        self.assertEqual(plan("make it lowercase", text).kind, "semantic")

    def test_new_paragraph(self):
        out, ok = apply_local("First part.", plan("new paragraph", "First part."))
        self.assertTrue(ok)
        self.assertEqual(out, "First part.\n\n")


if __name__ == "__main__":
    unittest.main()
