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

from flow.edits import (  # noqa: E402
    _MISHEARD_PROMPT,
    apply_local,
    describe_change,
    plan,
    removed_text,
)

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


REAL = ("hi priya, the deploy is scheduled for Tuesday afternoon. sameer is writing "
        "the RELEASE NOTES and running the migration. I attached the summary from the "
        "standup. tell me if Tuesday still works.")


class TestReferentialTargets(unittest.TestCase):
    """Naming a target by pointing at it, not by quoting it.

    From the first volunteer recording: ten of eleven commands routed correctly and
    this was the one that did not. The phonetic matcher already resolved "stand up" to
    "standup" at 0.97 — the target simply had "the bit about" on the front of it.
    """

    def test_the_utterance_that_was_actually_said(self):
        p = plan("Delete the bit about the stand up", REAL)
        self.assertEqual((p.kind, p.op), ("local", "delete"))
        self.assertTrue(p.referential)

    def test_the_other_ways_people_point_at_things(self):
        for utterance in (
            "delete the part about the migration",
            "remove the sentence about the standup",
            "cut the line about the migration",
            "delete the bit mentioning the standup",
        ):
            with self.subTest(utterance=utterance):
                self.assertEqual(plan(utterance, REAL).kind, "local")

    def test_a_referential_delete_takes_the_whole_sentence(self):
        # Deleting only the thing pointed at left "I attached the summary from."
        out, ok = apply_local(REAL, plan("delete the bit about the stand up", REAL))
        self.assertTrue(ok)
        self.assertNotIn("I attached", out)
        self.assertIn("tell me if Tuesday still works", out)
        self.assertIn("sameer is writing", out)

    def test_a_quoted_target_is_still_surgical(self):
        # Without the referential head, delete means exactly what it says.
        p = plan("delete the standup", REAL)
        self.assertFalse(p.referential)
        out, ok = apply_local(REAL, p)
        self.assertTrue(ok)
        self.assertIn("I attached the summary", out)

    def test_pointing_at_something_absent_is_still_dictation(self):
        # The safety property: stripping the head only happens when it makes the
        # target findable, so a wrong guess costs nothing.
        self.assertEqual(plan("delete the bit about the weather", REAL).kind, "append")
        self.assertEqual(plan("the part about the budget was unclear", REAL).kind,
                         "append")


class TestHedgesFromRecordings(unittest.TestCase):
    """Lead-in forms the first recorded session produced, which used to route as text.

    Whisper punctuates a pause as a sentence end, so a speaker who hesitates gets
    "Wait. Undo that." — the hedge terminated by a full stop rather than a comma. The
    old lead-in only accepted a comma, so the whole utterance was typed into the
    draft as the words "wait undo that" instead of undoing anything.
    """

    DRAFT = "Meeting on Tuesday with Sameer about the release notes."

    def test_a_hedge_ended_by_a_full_stop_is_still_a_hedge(self):
        self.assertEqual(plan("Wait. Undo that.", self.DRAFT).kind, "undo")

    def test_the_comma_form_still_works(self):
        self.assertEqual(plan("wait, undo that", self.DRAFT).kind, "undo")

    def test_oh_and_hey_open_corrections_too(self):
        self.assertEqual(plan("oh, delete the last sentence", self.DRAFT).op,
                         "delete_last")
        self.assertEqual(plan("Hey, undo that.", self.DRAFT).kind, "undo")

    def test_hedges_still_stack(self):
        self.assertEqual(plan("oh no, sorry, can you undo that", self.DRAFT).kind,
                         "undo")

    def test_a_hedge_word_that_opens_real_dictation_is_not_stripped_into_a_command(self):
        # "Well" and "right" begin ordinary sentences far more often than corrections.
        for text in ("Well the deploy failed again this morning.",
                     "Right now the connection pool is exhausted."):
            self.assertEqual(plan(text, self.DRAFT).kind, "append", text)


class TestRescueFrame(unittest.TestCase):
    """Rescue is a whole utterance, and it survives one observed mis-hearing.

    "comment" is not a synonym for "command" — it is what the final model returned
    when a recorded speaker said "command". Admitting it is only safe because the
    frame now has to be the entire utterance.
    """

    DRAFT = "Meeting on Tuesday with Sameer about the release notes."

    def test_the_observed_mis_hearing_rescues(self):
        self.assertEqual(plan("That was a comment.", self.DRAFT).kind, "rescue")

    def test_trailing_words_mean_it_was_dictation(self):
        for text in ("that was a comment on the pull request",
                     "that was a command on the PR"):
            self.assertEqual(plan(text, self.DRAFT).kind, "append", text)

    def test_the_canonical_forms_still_rescue(self):
        for text in ("that was a command", "no, that was a command",
                     "I meant that as an instruction", "that was meant as an edit"):
            self.assertEqual(plan(text, self.DRAFT).kind, "rescue", text)


class TestReplaceAllPhrasings(unittest.TestCase):
    """The whole-draft replacement, in the ways people actually ask for it.

    It used to accept exactly one phrasing — "replace all X with Y" — which is the one
    nobody says. Every natural form fell through to the single-target replace, took
    "all Tuesday" as its target, failed to find it and escalated to a 7 s CLI call.
    Found because the recording sheet's own example for this item did not do what the
    sheet said it did.
    """

    DRAFT = ("hi priya, the deploy is scheduled for Tuesday afternoon. sameer is "
             "writing the RELEASE NOTES. tell me if Tuesday still works.")

    def test_the_natural_phrasings_all_reach_replace_all(self):
        for text in ("change every Tuesday to Wednesday",
                     "change all Tuesdays to Wednesday",
                     "change all the Tuesdays to Wednesday",
                     "change every mention of Tuesday to Wednesday",
                     "swap all Tuesday for Wednesday",
                     "replace every instance of sameer with Samir",
                     "can you please change every Tuesday to Wednesday"):
            p = plan(text, self.DRAFT)
            self.assertEqual((p.kind, p.op), ("local", "replace_all"), text)

    def test_the_original_phrasing_still_works(self):
        p = plan("replace all Tuesday with Wednesday", self.DRAFT)
        self.assertEqual((p.kind, p.op), ("local", "replace_all"))

    def test_it_replaces_every_occurrence_including_from_a_plural_target(self):
        for text in ("change every Tuesday to Wednesday",
                     "change all the Tuesdays to Wednesday"):
            out, ok = apply_local(self.DRAFT, plan(text, self.DRAFT))
            self.assertTrue(ok, text)
            self.assertNotIn("Tuesday", out, text)
            self.assertEqual(out.count("Wednesday"), 2, text)

    def test_a_missing_target_still_escalates_rather_than_guessing(self):
        p = plan("change every Thursday to Friday", self.DRAFT)
        self.assertEqual(p.kind, "semantic")
        self.assertTrue(p.escalated)

    def test_the_connectiveless_frame_is_left_alone(self):
        # "make all the tests pass" has the same shape as "make all the Tuesdays
        # Wednesday". Turning that into a replacement is worse than not catching it.
        self.assertEqual(plan("make all the tests pass", self.DRAFT).kind, "append")


class TestDestructiveEditsAreNamed(unittest.TestCase):
    """A deleted sentence must never vanish unexplained (P2, extended to deletions).

    `describe()` reports what was *asked for* — "delete_last('sentence')" — which is
    exactly the message that lets words disappear without the user knowing which ones.
    Only the two texts know what actually went.
    """

    DRAFT = ("hi priya, the deploy is scheduled for Tuesday afternoon. sameer is "
             "writing the RELEASE NOTES. I attached the summary from the standup. "
             "tell me if Tuesday still works.")

    def _apply(self, utterance):
        p = plan(utterance, self.DRAFT)
        new, ok = apply_local(self.DRAFT, p)
        self.assertTrue(ok, utterance)
        return p, new

    def test_delete_last_names_the_sentence_it_took(self):
        p, new = self._apply("delete the last sentence")
        self.assertIn("tell me if Tuesday still works.",
                      describe_change(p, self.DRAFT, new))

    def test_a_referential_delete_names_the_whole_sentence_it_widened_to(self):
        p, new = self._apply("delete the bit about the standup")
        self.assertIn("I attached the summary from the standup.",
                      describe_change(p, self.DRAFT, new))

    def test_removals_are_reported_in_words_not_characters(self):
        # A character diff of Tuesday->Wednesday reports "Tu … Tu", which is noise.
        p, new = self._apply("change every Tuesday to Wednesday")
        self.assertEqual(removed_text(self.DRAFT, new), "Tuesday … Tuesday")

    def test_a_case_fix_names_both_spellings(self):
        # The op this used to be exempt from naming, and the one where the plan is least
        # able to: "capitalize sameer" carries a target and no payload, so the corrected
        # spelling exists nowhere except in the resulting draft.
        p, new = self._apply("capitalize sameer")
        self.assertEqual(describe_change(p, self.DRAFT, new),
                         "changed “sameer” to “Sameer”")

    def test_the_note_is_a_sentence_and_not_a_trace_line(self):
        # The defect the copy rewrite was for: `local: replace('thursday' -> 'Tuesday')`
        # printed at somebody who wanted to know what happened to their words.
        p, new = self._apply("change priya to Samar")
        said = describe_change(p, self.DRAFT, new)
        self.assertEqual(said, "changed “priya,” to “Samar,”")
        for syntax in ("replace(", "->", "_", "'"):
            self.assertNotIn(syntax, said)

    def test_one_word_changed_twice_is_reported_once(self):
        # `removed_text` reports the span per occurrence — "Tuesday … Tuesday" — which is
        # the right answer to "what went" and the wrong one to show a person.
        p, new = self._apply("change every Tuesday to Wednesday")
        self.assertEqual(describe_change(p, self.DRAFT, new),
                         "changed every “Tuesday” to “Wednesday”")

    def test_a_deletion_says_removed_rather_than_changed(self):
        p, new = self._apply("delete the last sentence")
        self.assertTrue(describe_change(p, self.DRAFT, new).startswith("removed “"))

    def test_the_note_is_bounded(self):
        long_draft = " ".join(f"word{i}" for i in range(400)) + "."
        p = plan("delete the last sentence", long_draft)
        new, ok = apply_local(long_draft, p)
        self.assertTrue(ok)
        self.assertLessEqual(len(removed_text(long_draft, new)), 60)


class TestTheFollowUpParticleCanBeElided(unittest.TestCase):
    """"follow and ..." is a follow-up; "follow the ..." is dictation.

    Live run 1 said "follow up and mention the rollback plan" and the decoder dropped the
    unstressed "up" between two stressed words — "roleback" itself scored 0.938 against
    the draft and was never the problem. So this is an elision, the same kind of thing
    `_LOWER` handles by carrying `lower\\s?case` in the pattern rather than as a table
    entry, and it lives in the pattern for the same reason.

    Bare "follow" stays out, permanently: "follow the steps in the README" is dictation
    and admitting it would cost a sentence to save a particle. The two cases sit in one
    class because they are one diff apart, and the whole question is whether that diff
    can tell them apart.
    """

    DRAFT = "Ship the release notes on Tuesday. Mention the rollback plan."

    def routed(self, text: str) -> str:
        p = plan(text, self.DRAFT)
        return f"{p.kind}/{p.op}"

    def test_the_elision_is_a_follow_up(self):
        self.assertEqual(self.routed("follow and mention the rollback plan"),
                         "followup/")

    def test_and_carries_the_rest_of_the_turn_like_the_spelled_form(self):
        # "follow up, and add the logs" has always been one turn rather than two; the
        # elided form must not become the exception that makes the user pause.
        self.assertEqual(plan("follow and mention the rollback plan", self.DRAFT).payload,
                         plan("follow up and mention the rollback plan",
                              self.DRAFT).payload)

    def test_a_comma_between_them_is_the_same_utterance(self):
        self.assertEqual(self.routed("follow, and add the logs"), "followup/")

    def test_bare_follow_is_still_dictation(self):
        for s in (
            "follow the steps in the README",
            "follow up on this later",  # 'follow up' with no 'and' still matches
            "follow Bob on the thread",
            "follow along with the recording",
        ):
            with self.subTest(s=s):
                expected = "followup/" if s.startswith("follow up") else "append/"
                self.assertEqual(self.routed(s), expected)

    def test_and_a_sentence_that_merely_contains_it_is_dictation(self):
        # The pattern is anchored, so "follow and" mid-sentence is prose.
        self.assertEqual(
            self.routed("the tests follow and then the deploy runs"), "append/")

    def test_the_spelled_forms_are_untouched(self):
        for s in ("follow up and mention the rollback plan",
                  "follow-up, and add the logs",
                  "following up and add the logs",
                  "also mention the rollback plan"):
            with self.subTest(s=s):
                self.assertEqual(self.routed(s), "followup/")


class TestTakingTheAnswerCanBeSpoken(unittest.TestCase):
    """An exact small set, whole-utterance only — item 20's discipline exactly.

    "use that answer in the summary" is prose and must stay dictation, which is what
    whole-utterance matching buys: the phrase is a command only when it is the entire
    thing said, so a false fire needs the speaker to have said nothing else.
    """

    DRAFT = "Ship the release notes on Tuesday."

    def routed(self, text: str) -> str:
        p = plan(text, self.DRAFT)
        return f"{p.kind}/{p.op}"

    def test_the_exact_forms_route_to_the_take(self):
        for s in ("use that answer", "use that reply", "Use that answer.",
                  "use the answer", "take that answer"):
            with self.subTest(s=s):
                self.assertEqual(self.routed(s), "take/")

    def test_a_hedge_in_front_is_still_the_same_utterance(self):
        # `_LEAD` already carries "okay", "so", "please" everywhere else in this file.
        self.assertEqual(self.routed("okay, use that answer"), "take/")

    def test_the_same_words_inside_a_sentence_are_dictation(self):
        for s in ("use that answer in the summary",
                  "use that reply as the opening paragraph",
                  "I will use that answer tomorrow",
                  "we should use the answer from the other thread"):
            with self.subTest(s=s):
                self.assertEqual(self.routed(s), "append/")

    def test_and_neighbouring_phrases_are_not_swept_in(self):
        for s in ("use that", "answer that", "use it"):
            with self.subTest(s=s):
                self.assertNotEqual(self.routed(s), "take/")


class TestRescueMatchesItsOwnButton(unittest.TestCase):
    """The chip is labelled "Was a command", so that phrase has to work when spoken.

    The first person to say it aloud had it typed into their draft: the grammar
    demanded "*that* was a command". A label the grammar rejects is the worst kind of
    defect, because the user did exactly what the product told them to.
    """

    DRAFT = "Meeting on Tuesday with Sameer about the release notes."

    def test_the_button_label_works_as_speech(self):
        self.assertEqual(plan("Was a command", self.DRAFT).kind, "rescue")

    def test_every_natural_subject_works(self):
        for text in ("was a command", "that was a command", "it was a command",
                     "this was a command", "was meant to be a command",
                     "I meant that as an instruction", "sorry, that was a command"):
            self.assertEqual(plan(text, self.DRAFT).kind, "rescue", text)

    def test_it_is_still_the_whole_utterance_or_nothing(self):
        for text in ("that was a comment on the pull request",
                     "was a command line tool that we used",
                     "the command failed"):
            self.assertEqual(plan(text, self.DRAFT).kind, "append", text)


class TestTheMisHeardPromptTable(unittest.TestCase):
    """One frame, and every noun the decoder has put where "prompt" was said.

    The `--takes 3` run (2026-08-01) spoke "make it a proper prompt" three times into
    the same microphone and got back "brown", "prompt" and **"font"**. Two of the three
    carry no instruction the CLI can act on, and the frame around them survived intact
    each time — which is what makes a table of heard nouns the right shape and a
    similarity bar the wrong one: "font" scores 0.400 against "prompt", still under half
    of `MATCH_THRESHOLD`, while "proper" (0.667), "problem" (0.615) and "drop" (0.600)
    all sit above it and all mean something else in the very same frame.

    The bounds are unchanged from the entry that came first: consulted only after the
    exact reading fails, only inside `_POLISH_FRAME`, and it changes *which* instruction
    a semantic plan carries, never whether one is sent. The other half of the bargain is
    the rest of this class — fonts are an ordinary thing to talk about, and a table
    keyed on the word must not reach the speech that means it.
    """

    DRAFT = "Meeting on Tuesday with Sameer about the release notes."

    def routed(self, text: str) -> str:
        p = plan(text, self.DRAFT)
        return f"{p.kind}/{p.op}"

    def test_the_newly_heard_noun_inside_the_frame_is_a_polish(self):
        self.assertEqual(self.routed("Make it a proper font."), "semantic/polish")

    def test_and_so_is_every_reading_recorded_before_it(self):
        for s in ("Make it a proper prompt.", "Make it a proper brown."):
            with self.subTest(s=s):
                self.assertEqual(self.routed(s), "semantic/polish")

    def test_talking_about_fonts_outside_the_frame_is_untouched(self):
        # Both of these route exactly where they routed before the entry existed: the
        # frame is what keeps the table off ordinary speech, not the noun.
        self.assertEqual(self.routed("make the font bigger"), "append/")
        self.assertEqual(self.routed("change the font to Arial"), "semantic/")

    def test_and_a_different_request_in_the_same_frame_is_still_free_text(self):
        for s in ("Make it a proper sentence.", "Make it a proper email.",
                  "Make it a proper font size."):
            with self.subTest(s=s):
                p = plan(s, self.DRAFT)
                self.assertEqual((p.kind, p.op), ("semantic", ""), s)

    def test_the_table_stops_growing_before_five(self):
        # LOOP_PLAN item 26's escalation tripwire, written as a check rather than a
        # note so it cannot be forgotten: the edit that would make this five entries is
        # the edit that must stop and write a NEEDS_YOU entry instead. At that size the
        # mis-heard-noun family is measured to be open — three nouns from three takes of
        # one sentence — and the honest fix is decode-time command bias, whose
        # acceptance fixtures already wait in tests/test_live_replay.py.
        self.assertLess(len(_MISHEARD_PROMPT), 5,
                        "five heard nouns is Phase 3's evidence, not a sixth entry")
