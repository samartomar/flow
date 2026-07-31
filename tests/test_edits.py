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


HARD = "Meeting on Tuesday with Sameer about the release."


class TestPoliteAndHedgedCommands(unittest.TestCase):
    """The lead-in a non-native speaker actually uses, on every pattern.

    Politeness was the missing half: "can you delete Tuesday" was routed as dictation
    and appended into the draft verbatim.
    """

    def test_politeness_on_each_pattern(self):
        cases = [
            ("can you change Tuesday to Wednesday", "replace"),
            ("could you please delete Tuesday", "delete"),
            ("please capitalize sameer", "capitalize"),
            ("would you replace all Tuesday with Friday", "replace_all"),
            ("can you insert urgent before release", "insert_before"),
            ("please delete the last word", "delete_last"),
            ("could you lowercase Sameer", "lower"),
        ]
        for utterance, op in cases:
            with self.subTest(utterance=utterance):
                p = plan(utterance, HARD)
                self.assertEqual(p.kind, "local", f"{utterance!r} -> {p.kind}")
                self.assertEqual(p.op, op)

    def test_stacked_hedges(self):
        # "no, sorry, can you ..." is one utterance, not three.
        p = plan("no, sorry, can you delete Tuesday", HARD)
        self.assertEqual((p.kind, p.op), ("local", "delete"))

    def test_polite_undo(self):
        self.assertEqual(plan("okay, scratch that", HARD).kind, "undo")

    def test_politeness_does_not_invent_commands(self):
        # No verb, so it is still ordinary dictation.
        self.assertEqual(plan("can you believe the release date", HARD).kind, "append")


class TestVerbSnapping(unittest.TestCase):
    """Mis-heard trigger verbs, which is defect 4's first half."""

    def test_fuzzy_verb_within_one_edit(self):
        for utterance in ("delet Tuesday", "deleet Tuesday", "remov Tuesday"):
            with self.subTest(utterance=utterance):
                p = plan(utterance, HARD)
                self.assertEqual((p.kind, p.op), ("local", "delete"))

    def test_verb_suffixes_are_stripped(self):
        p = plan("deleting Tuesday", HARD)
        self.assertEqual((p.kind, p.op), ("local", "delete"))

    def test_alias_table_reaches_what_distance_cannot(self):
        # "the lead" is three edits from "delete" and would never snap by distance.
        p = plan("the lead Tuesday", HARD)
        self.assertEqual((p.kind, p.op), ("local", "delete"))
        p = plan("stop Tuesday with Friday", HARD)
        self.assertEqual((p.kind, p.op), ("local", "replace"))

    def test_snapping_only_promotes_when_the_target_is_real(self):
        # The safety property. "stop" is an ordinary word; it may only become "swap"
        # when the words after it are genuinely in the draft.
        self.assertEqual(plan("stop the build and go home", HARD).kind, "append")
        self.assertEqual(plan("the lead is buried", HARD).kind, "append")
        self.assertEqual(plan("at the conference", HARD).kind, "append")

    def test_snapping_never_overrides_a_good_exact_reading(self):
        # "add urgent before release" parses exactly; snapping must not touch it.
        p = plan("add urgent before release", HARD)
        self.assertEqual((p.kind, p.op), ("local", "insert_before"))

    def test_undo_is_promoted_only_from_the_alias_table(self):
        # A spurious undo throws away real work, so edit distance is not enough.
        self.assertEqual(plan("scratch hat", HARD).kind, "undo")
        self.assertEqual(plan("scratch mat", HARD).kind, "append")

    def test_long_utterances_are_never_snapped(self):
        # Found by scripts/command_bench.py: without a length guard, suffix stripping
        # turned two sentence-opening gerunds into commands. Both are dictation, and
        # both are long — every command in the inventory is five words or fewer.
        text = "deleting a branch does not delete the history"
        self.assertEqual(plan("Deleting a branch does not delete the history.", text).kind,
                         "append")
        text2 = "changing Tuesday to Wednesday broke the booking"
        self.assertEqual(plan("Changing Tuesday to Wednesday broke the booking.", text2).kind,
                         "append")

    def test_the_guard_measures_length_after_the_lead_in(self):
        # "could you please" is politeness, not content, so it must not push a real
        # command over the limit.
        p = plan("could you please deleting Tuesday", HARD)
        self.assertEqual((p.kind, p.op), ("local", "delete"))

    def test_short_words_are_matched_exactly(self):
        # At three characters one edit reaches too far: "but" must not become "cut".
        self.assertEqual(plan("but Tuesday", HARD).kind, "append")
        self.assertEqual(plan("cup Tuesday", HARD).kind, "append")


class TestReplaceAllPayloadIsLiteral(unittest.TestCase):
    """The payload is the user's words, not a regex template."""

    def test_backreference_in_the_payload_is_not_expanded(self):
        text = "the foo and the foo again"
        out, ok = apply_local(text, plan(r"replace all foo with \1", text))
        self.assertTrue(ok)
        self.assertEqual(out, r"the \1 and the \1 again")

    def test_windows_path_payload_survives(self):
        text = "save it to the temp folder"
        out, ok = apply_local(text, plan(r"replace all temp with C:\news\temp", text))
        self.assertTrue(ok)
        self.assertIn(r"C:\news\temp", out)

    def test_target_with_regex_characters_is_matched_literally(self):
        text = "the rate is 5.5 percent"
        out, ok = apply_local(text, plan("replace all 5.5 with 6.0", text))
        self.assertTrue(ok)
        self.assertEqual(out, "the rate is 6.0 percent")


if __name__ == "__main__":
    unittest.main()
