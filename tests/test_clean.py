"""Tests for hallucination filtering.

The asymmetry matters more than the accuracy here: dropping a real word is worse than
admitting a stray invented one, because a user can delete text they can see but cannot
recover text that was never shown. So the "must not drop real speech" tests are the
important half of this file.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.clean import (  # noqa: E402
    collapse_phrase_repeats,
    collapse_repeats,
    invented_reason,
    is_invented,
    normalise,
    strip_markers,
)

REAL = "I need to send an email to the team about the quarterly review meeting."


class TestMeasuredCases(unittest.TestCase):
    """The exact observations from scripts/hallucination_probe.py."""

    def test_silence_hallucination_is_dropped(self):
        self.assertTrue(is_invented("You", 0.6907023787498474, -0.7108760923147202))

    def test_hiss_hallucination_is_dropped(self):
        self.assertTrue(is_invented("You", 0.8994780778884888, -0.9186075925827026))

    def test_genuine_short_fragment_is_kept(self):
        # 0.099 no_speech_prob — a real clipped word, must survive.
        self.assertFalse(is_invented("I need...", 0.09941279143095016, -0.914198656876882))

    def test_real_speech_is_kept(self):
        self.assertFalse(is_invented(REAL, 0.00017106968152802438, -0.18341238610446453))


class TestDoesNotEatRealSpeech(unittest.TestCase):
    def test_long_utterance_survives_high_no_speech_prob(self):
        # One borderline signal is not enough to discard content this substantial.
        self.assertFalse(is_invented(REAL, 0.95, -0.2))

    def test_filler_words_inside_real_speech_survive(self):
        self.assertFalse(is_invented("Thank you for sending the report yesterday.", 0.01, -0.2))

    def test_short_but_confident_utterance_survives(self):
        self.assertFalse(is_invented("Send it now.", 0.05, -0.3))

    def test_genuine_word_repetition_is_untouched(self):
        text = "it was very very very good and really really nice"
        self.assertEqual(collapse_repeats(text), text)


class TestArtefacts(unittest.TestCase):
    def test_degenerate_punctuation_repeats_collapse(self):
        # Observed in stage 3 partials: 'bring // // // // //'.
        out = collapse_repeats("bring // // // // // // their updated figures")
        self.assertEqual(out, "bring // // // their updated figures")

    def test_markers_are_removed(self):
        self.assertEqual(normalise("[BLANK_AUDIO] hello there"), "hello there")
        self.assertEqual(normalise("hello (silence) there"), "hello there")
        self.assertEqual(strip_markers("music ♪ here").strip(), "music   here".strip())

    def test_empty_after_cleaning_counts_as_invented(self):
        self.assertTrue(is_invented("[BLANK_AUDIO]", 0.01, -0.1))
        self.assertTrue(is_invented("   ", None))

    def test_whitespace_is_normalised(self):
        self.assertEqual(normalise("too   many    spaces"), "too many spaces")


class TestNoProbabilityAvailable(unittest.TestCase):
    """A non-Whisper engine gives no probabilities; fall back narrowly."""

    def test_bare_filler_is_dropped(self):
        self.assertTrue(is_invented("Thank you.", None))
        self.assertTrue(is_invented("You", None))

    def test_real_text_is_kept(self):
        self.assertFalse(is_invented(REAL, None))
        self.assertFalse(is_invented("Send the report.", None))


class TestSingleTokenLoops(unittest.TestCase):
    """The gap between the two collapse rules, found on the short-clip slice."""

    def test_the_measured_okay_loop(self):
        # 0.55 s of audio, reference "UM", decoded as 29 segments of "Okay." — one
        # word, so the phrase rule (>= 2 words) never saw it, and five characters, so
        # the old two-character rule never saw it either.
        self.assertEqual(normalise("Okay. " * 29), "Okay. Okay. Okay.")

    def test_a_long_word_can_still_repeat_like_speech_does(self):
        text = "it was very very very good and really really nice"
        self.assertEqual(normalise(text), text)

    def test_punctuation_runs_still_collapse(self):
        self.assertEqual(
            normalise("bring // // // // // // their updated figures"),
            "bring // // // their updated figures",
        )


class TestPhraseRepeats(unittest.TestCase):
    """The repetition loops the capped temperature ladder no longer breaks."""

    def test_the_measured_spanish_loop(self):
        # One clip of the 300-clip accent slice, capped ladder: 30 copies, 87 edits
        # against a four-word reference.
        text = "So what they do? " + "I'm so sorry. " * 30
        out = collapse_phrase_repeats(text.strip())
        self.assertEqual(out, "So what they do? I'm so sorry. I'm so sorry.")

    def test_the_measured_japanese_loop(self):
        text = "We're going to start with " + "the rest of " * 6 + "the rest."
        out = collapse_phrase_repeats(text)
        self.assertEqual(
            out, "We're going to start with the rest of the rest of the rest."
        )

    def test_the_measured_indian_loop_is_seven_words_long(self):
        # 2.6 s of speech, one segment, the same seven words twenty-two times: 207
        # edits against a twelve-word reference. A six-word window missed this.
        text = "Yeah " + "I read on the bit of course " * 22
        out = collapse_phrase_repeats(text.strip())
        self.assertEqual(
            out, "Yeah I read on the bit of course I read on the bit of course"
        )

    def test_real_speech_is_untouched(self):
        for text in (
            "I need to send an email to the team about the quarterly review meeting.",
            "change Tuesday to Wednesday please",
            "it was very very good",
            "no no no that is not what I said",
            "bye bye bye bye",  # two reps of a two-word phrase: at the limit, kept
        ):
            with self.subTest(text=text):
                self.assertEqual(collapse_phrase_repeats(text), text)

    def test_short_input_is_returned_unchanged(self):
        self.assertEqual(collapse_phrase_repeats("hi there"), "hi there")
        self.assertEqual(collapse_phrase_repeats(""), "")

    def test_repetition_after_real_content_keeps_the_content(self):
        out = collapse_phrase_repeats("the deploy failed " + "oh no " * 5)
        self.assertEqual(out, "the deploy failed oh no oh no")

    def test_normalise_applies_it(self):
        self.assertEqual(
            normalise("go on " + "and then " * 4 + "stop"), "go on and then and then stop"
        )


class TestInventedReason(unittest.TestCase):
    """Every drop has to say which rule ate the speech, not just that one did."""

    def test_kept_text_has_no_reason(self):
        self.assertIsNone(invented_reason(REAL, 0.01, -0.2))

    def test_empty_after_markers(self):
        self.assertEqual(invented_reason("[BLANK_AUDIO]", 0.1, -0.2), "empty")

    def test_shortness_alone_no_longer_drops_anything(self):
        # Defect 3, fixed: a short, confident spoken correction survives even when the
        # model doubts it was speech at all. This is the case the rule exists for.
        self.assertIsNone(invented_reason("delete that line", 0.9, -0.3))
        self.assertIsNone(invented_reason("scratch that", 0.95, -0.5))
        self.assertIsNone(invented_reason("send it", 0.9, -0.79))

    def test_unconfident_alone_is_named(self):
        self.assertEqual(
            invented_reason("this is a longer stretch of speech", 0.9, -0.95),
            "unconfident",
        )

    def test_the_filler_list_is_the_second_signal(self):
        # 'You' is what Whisper emits into silence, so it dies on the filler rule
        # whatever its length or confidence.
        self.assertEqual(invented_reason("You", 0.9, -0.95), "filler")
        self.assertEqual(invented_reason("You", 0.6907, -0.7109), "filler")
        self.assertEqual(invented_reason("Thank you.", 0.9, -0.2), "filler")

    def test_filler_without_probabilities(self):
        self.assertEqual(invented_reason("Thank you.", None), "filler")
        self.assertIsNone(invented_reason(REAL, None))

    def test_reason_and_boolean_never_disagree(self):
        cases = [
            (REAL, 0.01, -0.2), ("You", 0.69, -0.71), ("okay", 0.9, None),
            ("[BLANK_AUDIO]", 0.1, -0.2), ("Thank you.", None, None),
            ("delete that line", 0.9, -0.3), ("a much longer utterance here", 0.7, -0.9),
        ]
        for text, ns, lp in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    is_invented(text, ns, lp), invented_reason(text, ns, lp) is not None
                )


class TestTheSignOffHallucinationInFrontOfRealSpeech(unittest.TestCase):
    """Whisper's YouTube sign-off, prefixed to words that were actually said.

    Reported from this machine: *"So when this works"* came back as
    *"Thank you for watching. So when this works"*. Two separate gaps let it through,
    and fixing either alone would have left the report standing.

    **The whole-utterance list was never consulted.** `_FILLER_ONLY` is only asked about
    the entire output, so a hallucination with real dictation behind it sails past by
    construction — which is why the second half of this file matters as much as the
    first.

    **And the string was not on the list anyway.** It holds *"thanks for watching"* and
    *"thank you."* as two entries; the model emits *"thank you for watching"* as a third,
    which was in neither.
    """

    #: The reported case, and the stacked form the model actually produced.
    def test_the_reported_case(self):
        self.assertEqual(
            normalise("Thank you for watching. So when this works"), "So when this works")

    def test_it_stacks_and_one_pass_would_leave_the_second(self):
        # "Thanks for watching. Thank you for watching." measured on the same recording,
        # so a single substitution removes the first and leaves the second in front of
        # the user's sentence.
        self.assertEqual(
            normalise("Thanks for watching. Thank you for watching. So when this works"),
            "So when this works")

    def test_it_covers_both_spellings(self):
        # `thanks?` matches "thanks", not "thank you" — the first attempt at this
        # pattern handled the wrong half of the pair and the reported phrase sailed
        # through. Measured, not reasoned: the regex was tried against both.
        for lead in ("Thanks for watching.", "Thank you for watching."):
            with self.subTest(lead=lead):
                self.assertEqual(normalise(f"{lead} Run the tests"), "Run the tests")

    def test_the_trailing_punctuation_goes_with_it(self):
        # Leaving ". So when this works" would put a full stop at the head of every
        # dictated sentence, which reads as a sentence break the user never made.
        self.assertFalse(normalise("Thanks for watching. Hello").startswith("."))

    # -- the half that matters more: nothing real may be lost --------------------

    def test_thanks_inside_a_real_sentence_survives(self):
        for text in ("Thanks for the detailed report",
                     "Thank you for the fix, it works",
                     "I will thank you for watching the demo later"):
            with self.subTest(text=text):
                self.assertEqual(normalise(text), text)

    def test_bye_is_only_a_sign_off_at_the_end_and_never_in_front(self):
        # The one place this got it wrong twice: `bye` is an ordinary English word, and
        # a bare `^bye` cut "Bye then, I will call back" down to "then, I will call
        # back". A trailing-only anchor is the difference between a sign-off and a word.
        self.assertEqual(normalise("Bye then, I will call back"), "Bye then, I will call back")
        self.assertEqual(normalise("By the way the tests pass"), "By the way the tests pass")

    def test_the_ordinary_fillers_are_untouched(self):
        # `okay`, `so` and `yeah` are in `_FILLER_ONLY` for the *whole-utterance* check,
        # which is the right place for them. None of them may be cut from a sentence.
        for text in ("Okay so the build passes now", "Yeah I think that works"):
            with self.subTest(text=text):
                self.assertEqual(normalise(text), text)

    def test_a_whole_utterance_sign_off_is_still_rejected(self):
        # The list fix, which is a different mechanism and has to hold on its own: these
        # now name the spelling the model actually produced.
        for text in ("Thank you for watching", "Thank you for watching.",
                     "Thank you for watching!", "Thanks for listening"):
            with self.subTest(text=text):
                self.assertIsNotNone(invented_reason(text, None))


if __name__ == "__main__":
    unittest.main()
