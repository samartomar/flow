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

    def test_thin_alone_is_named(self):
        # The one-signal drop the roadmap calls defect 3: short but confident.
        self.assertEqual(invented_reason("delete that line", 0.9, -0.3), "thin")

    def test_unconfident_alone_is_named(self):
        self.assertEqual(
            invented_reason("this is a longer stretch of speech", 0.9, -0.95),
            "unconfident",
        )

    def test_both_signals_are_named_together(self):
        self.assertEqual(invented_reason("You", 0.9, -0.95), "thin+unconfident")

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


if __name__ == "__main__":
    unittest.main()
