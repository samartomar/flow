"""Tests for the measurement harnesses themselves.

A benchmark that scores wrongly is worse than no benchmark: it produces a number
people then design against. `summarise_gate` decides whether a model is allowed to
become the default, so its two judgement calls — worst case not median, and no
operating point above a breach — are pinned here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from accent_bench import (  # noqa: E402
    LIB_LOG_PROB,
    LIB_NO_SPEECH,
    apply_filters,
    norm_words,
    wer_counts,
)
from asr_bench import median, summarise_gate, wer  # noqa: E402
from ingest_recordings import (  # noqa: E402
    find_boundaries,
    free_end,
    number_at,
)


def seg(text, ns, lp):
    return {"text": text, "ns": ns, "lp": lp}


class TestMedian(unittest.TestCase):
    def test_odd_length(self):
        self.assertEqual(median([3.0, 1.0, 2.0]), 2.0)

    def test_even_length_averages_the_middle(self):
        self.assertEqual(median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_empty(self):
        self.assertEqual(median([]), 0.0)


class TestGateSummary(unittest.TestCase):
    def test_all_under_budget_passes(self):
        s = summarise_gate([(1, 0.4), (1, 0.5), (2, 0.6), (2, 0.7)], budget=1.5)
        self.assertEqual(s["verdict"], "PASS")
        self.assertEqual(s["longest_pass"], 2)

    def test_worst_case_decides_not_median(self):
        # Median 0.5 s, one sample at 1.6 s: the user feels the 1.6.
        s = summarise_gate([(3, 0.5), (3, 0.5), (3, 1.6)], budget=1.5)
        self.assertEqual(s["verdict"], "FAIL")
        self.assertIsNone(s["longest_pass"])
        self.assertEqual(s["per_length"][0]["median"], 0.5)
        self.assertAlmostEqual(s["per_length"][0]["max"], 1.6)

    def test_longest_pass_stops_at_the_first_breach(self):
        # 8 s happens to come in fast, but 5 s already breached — 8 s is not a usable
        # operating point, because reaching it means passing through 5 s.
        s = summarise_gate([(1, 0.3), (2, 0.6), (5, 2.0), (8, 0.9)], budget=1.5)
        self.assertEqual(s["verdict"], "FAIL")
        self.assertEqual(s["longest_pass"], 2)

    def test_counts_are_reported_per_length(self):
        s = summarise_gate([(1, 0.3), (1, 0.4), (2, 0.6)], budget=1.5)
        self.assertEqual([r["n"] for r in s["per_length"]], [2, 1])

    def test_no_samples_is_not_a_pass(self):
        s = summarise_gate([], budget=1.5)
        self.assertEqual(s["verdict"], "FAIL")
        self.assertIsNone(s["longest_pass"])

    def test_lengths_are_ordered_by_duration(self):
        s = summarise_gate([(12, 1.0), (2, 0.4), (8, 0.9)], budget=1.5)
        self.assertEqual([r["secs"] for r in s["per_length"]], [2, 8, 12])


class TestApplyFilters(unittest.TestCase):
    """The false-reject number P2 is bounded by comes out of here, so it is pinned."""

    def test_clean_speech_survives_both_filters(self):
        f = apply_filters([seg("change Tuesday to Wednesday", 0.01, -0.2)])
        self.assertEqual(f["app_text"], "change Tuesday to Wednesday")
        self.assertEqual(f["legacy_text"], "change Tuesday to Wednesday")
        self.assertEqual((f["lib_skipped"], f["clean_dropped"]), (0, 0))

    def test_the_shipped_build_attributes_what_the_library_used_to_eat(self):
        # flow/asr.py passes no_speech_threshold=None, so this segment now reaches
        # Flow's filter. Flow still drops it — but as a *named* rule with its signals
        # recorded, rather than vanishing inside the library.
        f = apply_filters([seg("some ordinary words here", 0.7, -1.2)])
        self.assertEqual(f["lib_skipped"], 0)
        self.assertEqual(f["app_text"], "")
        self.assertEqual(f["reasons"], {"unconfident": 1})

    def test_the_library_skip_was_always_redundant(self):
        # Worth pinning because it corrects the audit: the library skips on
        # ns > 0.6 AND lp < -1.0, and lp < -1.0 implies lp < -0.8, so every segment it
        # ate was already failing Flow's own rule. Turning it off changes attribution,
        # not which words survive — verified on all 681 segments of the short slice.
        for ns, lp in ((0.61, -1.01), (0.9, -1.5), (0.7, -2.0)):
            with self.subTest(ns=ns, lp=lp):
                text = "a longer stretch of ordinary words"
                old = apply_filters([seg(text, ns, lp)], LIB_NO_SPEECH, LIB_LOG_PROB)
                new = apply_filters([seg(text, ns, lp)])
                self.assertEqual(old["lib_skipped"], 1)
                self.assertEqual(new["lib_skipped"], 0)
                self.assertEqual(old["app_text"], new["app_text"])

    def test_the_pre_fix_build_can_still_be_scored(self):
        # Passing the library's own defaults reproduces the build measured before the
        # fix, which is the counterfactual every P2 number is quoted against.
        f = apply_filters([seg("some ordinary words here", 0.7, -1.2)],
                          LIB_NO_SPEECH, LIB_LOG_PROB)
        self.assertEqual(f["lib_skipped"], 1)
        self.assertEqual(f["app_text"], "")

    def test_library_skip_needed_both_of_its_signals(self):
        # ns above 0.6 but logprob above -1.0: even the old build kept it.
        f = apply_filters([seg("some ordinary words here", 0.7, -0.5)],
                          LIB_NO_SPEECH, LIB_LOG_PROB)
        self.assertEqual(f["lib_skipped"], 0)

    def test_the_spoken_correction_the_old_rule_deleted(self):
        # Short, confident, high no-speech: exactly a spoken correction. The shipped
        # rule keeps it; the rule it replaced dropped it for being short.
        f = apply_filters([seg("delete that line", 0.9, -0.3)])
        self.assertEqual(f["app_text"], "delete that line")
        self.assertEqual(f["legacy_text"], "")
        self.assertEqual(f["reasons"], {})

    def test_both_rules_still_drop_the_hiss_hallucination(self):
        # The measured hiss hallucination from clean.py's table.
        f = apply_filters([seg("You", 0.899, -0.919)])
        self.assertEqual(f["app_text"], "")
        self.assertEqual(f["legacy_text"], "")
        self.assertEqual(f["reasons"], {"filler": 1})

    def test_the_silence_hallucination_survives_the_rule_change(self):
        # The trap this change had to avoid: the digital-silence 'You' (ns 0.691,
        # logprob -0.711) is short but NOT unconfident, so a naive "require two
        # signals" would have re-admitted the exact thing the filter exists for.
        # The filler list is what still catches it.
        f = apply_filters([seg("You", 0.6907, -0.7109)])
        self.assertEqual(f["app_text"], "")
        self.assertEqual(f["reasons"], {"filler": 1})

    def test_drops_are_annotated_in_place(self):
        segs = [seg("You", 0.9, -0.95), seg("kept text here", 0.01, -0.2)]
        apply_filters(segs)
        self.assertEqual(segs[0]["drop"], "filler")
        self.assertNotIn("drop", segs[1])

    def test_partial_survival_is_not_a_false_reject(self):
        f = apply_filters([seg("You", 0.9, -0.9), seg("the real sentence", 0.01, -0.2)])
        self.assertEqual(f["app_text"], "the real sentence")
        self.assertEqual(f["clean_dropped"], 1)


class TestNormWords(unittest.TestCase):
    def test_fillers_drop_from_both_sides(self):
        self.assertEqual(norm_words("um so uh yes"), ["so", "yes"])

    def test_annotation_tags_are_not_words(self):
        self.assertEqual(norm_words("HELLO <LAUGH> THERE"), ["hello", "there"])

    def test_digits_become_words(self):
        self.assertEqual(norm_words("21"), ["twenty", "one"])

    def test_wer_counts_returns_its_denominator(self):
        self.assertEqual(wer_counts("a b c", "a b"), (1, 3))


class TestWer(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(wer("hello there", "Hello, there!"), 0.0)

    def test_one_substitution_in_four(self):
        self.assertAlmostEqual(wer("a b c d", "a b x d"), 0.25)

    def test_empty_hypothesis_is_total_loss(self):
        self.assertEqual(wer("a b c", ""), 1.0)


if __name__ == "__main__":
    unittest.main()


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


class TestFindBoundaries(unittest.TestCase):
    """The splitter that turns one continuous recording into scored clips.

    It has no labels to work from — only the order of the spoken numbers — so every
    way that order can be violated is a way to mislabel every clip after it.
    """

    def test_returns_number_start_and_speech_start_separately(self):
        # The number is scaffolding. A clip that opens with "two" is not a command,
        # and the first scoring run routed 10 of 11 to dictation for exactly that.
        words = [w("One.", 0.0, 0.4), w(" delete", 0.4, 0.9), w(" that", 0.9, 1.2),
                 w(" Two.", 2.0, 2.4), w(" undo", 2.4, 2.8)]
        b = find_boundaries(words, 2)
        self.assertEqual(b[1][0], 0.0)
        self.assertGreater(b[1][1], 0.0)
        self.assertLessEqual(b[1][1], 0.4)

    def test_speech_start_is_padded_not_clamped_to_the_number_end(self):
        # Whisper reports word ends late and contiguous with the next start, so
        # clamping to the number's end silently zeroed the pad and ate the verb.
        words = [w("One.", 0.0, 1.0), w(" delete", 1.0, 1.6)]
        self.assertLess(find_boundaries(words, 1)[1][1], 1.0)

    def test_last_occurrence_wins_because_that_is_a_retake(self):
        words = [w("One.", 0.0, 0.3), w(" delete", 0.3, 0.7),
                 w(" One.", 1.0, 1.3), w(" delete", 1.3, 1.7), w(" that", 1.7, 2.0)]
        self.assertEqual(find_boundaries(words, 1)[1][0], 1.0)

    def test_a_number_word_in_ordinary_speech_cannot_capture_a_later_slot(self):
        # "delete the last two words" contains "two". If that opened item 2, every
        # label after it would shift by one.
        words = [w("One.", 0.0, 0.3), w(" delete", 0.3, 0.6), w(" the", 0.6, 0.8),
                 w(" last", 0.8, 1.0), w(" two", 1.0, 1.2), w(" words", 1.2, 1.5),
                 w(" Two.", 3.0, 3.3), w(" undo", 3.3, 3.6)]
        self.assertEqual(find_boundaries(words, 2)[2][0], 3.0)

    def test_a_skipped_item_does_not_shift_the_rest(self):
        words = [w("One.", 0.0, 0.3), w(" delete", 0.3, 0.6),
                 w(" Three.", 2.0, 2.3), w(" undo", 2.3, 2.6)]
        b = find_boundaries(words, 3)
        self.assertNotIn(2, b)
        self.assertEqual(b[3][0], 2.0)

    def test_digits_and_words_are_both_numbers(self):
        self.assertEqual(number_at("Seven."), 7)
        self.assertEqual(number_at(" 7,"), 7)
        self.assertIsNone(number_at("deploy"))


class TestFreeEnd(unittest.TestCase):
    """Where the last prompted command stops and the free-speech window begins.

    Only needed for recordings made before the sheet numbered the free window. In the
    first real one, no silence and no full stop marked the seam, so the boundary is
    the end of the known wording — matched phonetically, because these recordings
    exist precisely because the wording arrives accented.
    """

    def test_finds_the_end_of_the_known_phrase(self):
        words = [w("Eleven.", 0.0, 0.4), w(" that", 0.5, 0.7), w(" was", 0.7, 0.9),
                 w(" a", 0.9, 1.0), w(" command", 1.0, 1.5),
                 w(" fix", 1.5, 1.8), w(" the", 1.8, 2.0), w(" spelling", 2.0, 2.5)]
        self.assertAlmostEqual(free_end(words, 0.0, "that was a command"), 1.5)

    def test_matches_through_a_mis_hearing(self):
        words = [w("Eleven.", 0.0, 0.4), w(" that", 0.5, 0.7), w(" was", 0.7, 0.9),
                 w(" a", 0.9, 1.0), w(" comment", 1.0, 1.5), w(" fix", 1.5, 1.8),
                 w(" the", 1.8, 2.0), w(" spelling", 2.0, 2.5)]
        self.assertAlmostEqual(free_end(words, 0.0, "that was a command"), 1.5)

    def test_returns_none_when_the_phrase_is_not_there(self):
        words = [w("Eleven.", 0.0, 0.4), w(" fix", 0.5, 0.8),
                 w(" the", 0.8, 1.0), w(" spelling", 1.0, 1.5)]
        self.assertIsNone(free_end(words, 0.0, "that was a command"))


class TestTheKitTeachesTheTriggerWords(unittest.TestCase):
    """Item 70. The six presets became recorded items, so cross-accent recognition of
    the send word stops being a claim about one microphone.

    The four-leg gate in `test_triggers.py` prices *false fires* — 0/580 on real speech —
    and structurally cannot price recognition: a word nobody says by accident may also be
    a word the decoder never hears. This is the other half, and until these clips exist
    "the six presets decode" is true of exactly one voice (NEEDS_YOU, 2026-08-02).
    """

    def kit(self) -> str:
        return (Path(__file__).resolve().parent.parent / "docs" / "recording-kit.md"
                ).read_text(encoding="utf-8")

    def page(self) -> str:
        return (Path(__file__).resolve().parent.parent / "docs" / "record.html"
                ).read_text(encoding="utf-8")

    def test_every_shipped_preset_is_an_item(self):
        from flow.edits import SEND_WORD_PRESETS
        from ingest_recordings import TRIGGER_WORDS

        self.assertEqual(sorted(TRIGGER_WORDS.values()), sorted(SEND_WORD_PRESETS))

    def test_the_numbers_are_contiguous_and_end_before_the_free_window(self):
        from ingest_recordings import EXPECTED, FREE_ITEM, TRIGGER_WORDS

        self.assertEqual(sorted(TRIGGER_WORDS), list(range(12, 18)))
        self.assertEqual([n for n, _op, _note in EXPECTED], list(range(1, 18)))
        self.assertEqual(FREE_ITEM, 18)

    def test_a_number_word_exists_for_every_item(self):
        # The spoken number is the only boundary marker that survived a phone speaker, a
        # room and a phone mic; tones, silence and punctuation did not.
        from ingest_recordings import FREE_ITEM, WORDS, number_at

        for n in range(1, FREE_ITEM + 1):
            with self.subTest(n=n):
                self.assertIn(n, WORDS.values())
        self.assertEqual(number_at("eighteen"), 18)
        self.assertEqual(number_at("eight"), 8, "eighteen swallowed eight")

    def test_the_trigger_rows_carry_the_word_they_were_asked_for(self):
        # A scorer has to compare `said` against what the speaker was *asked* to say, and
        # deriving that from `SEND_WORD_PRESETS` at read time would silently relabel an
        # old clip the day a preset is swapped.
        from ingest_recordings import EXPECTED, TRIGGER_WORDS

        for num, word in TRIGGER_WORDS.items():
            with self.subTest(word=word):
                self.assertEqual(EXPECTED[num - 1][1], "trigger")
                self.assertIn(word, EXPECTED[num - 1][2])

    def test_the_eleven_corrections_did_not_move(self):
        # An older recording ingests unchanged: its items are still 1..11, and only the
        # free window needs the newer sheet to be found by number.
        from ingest_recordings import EXPECTED

        self.assertEqual([op for _n, op, _note in EXPECTED[:11]],
                         ["replace_all", "replace", "capitalize", "lower", "delete",
                          "delete_last", "insert_before", "undo", "polish", "followup",
                          "rescue"])

    def test_the_sheet_names_all_six_and_the_new_free_number(self):
        from flow.edits import SEND_WORD_PRESETS

        kit = self.kit()
        for word in SEND_WORD_PRESETS:
            with self.subTest(word=word):
                self.assertIn(word, kit)
        self.assertIn("## 18 —", kit)
        self.assertIn("eighteen", kit)

    def test_and_says_why_a_volunteer_is_being_asked_for_them(self):
        # The one thing a volunteer is owed here: these are not another correction, and
        # the reason they exist is that recognition was measured at one microphone.
        kit = self.kit().lower()
        self.assertIn("sends the message", kit)
        self.assertIn("one microphone", kit)

    def test_the_guided_page_carries_them_too(self):
        # `record.html` is the page volunteers are actually walked through, so a sheet
        # the page does not match is a sheet nobody follows.
        from flow.edits import SEND_WORD_PRESETS

        page = self.page()
        for word in SEND_WORD_PRESETS:
            with self.subTest(word=word):
                self.assertIn(f'"{word}"', page)
        self.assertIn("eighteen", page)
        self.assertNotIn('Say &ldquo;twelve&rdquo;', page)
