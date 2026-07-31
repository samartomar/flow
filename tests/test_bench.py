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
