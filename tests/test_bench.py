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

from accent_bench import apply_filters, norm_words, wer_counts  # noqa: E402
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
        self.assertEqual(f["two_signal_text"], "change Tuesday to Wednesday")
        self.assertEqual((f["lib_skipped"], f["clean_dropped"]), (0, 0))

    def test_library_skip_needs_both_of_its_signals(self):
        # ns above 0.6 but logprob above -1.0: the library keeps it, clean.py judges it.
        f = apply_filters([seg("some ordinary words here", 0.7, -0.5)])
        self.assertEqual(f["lib_skipped"], 0)
        f = apply_filters([seg("some ordinary words here", 0.7, -1.2)])
        self.assertEqual(f["lib_skipped"], 1)
        self.assertEqual(f["app_text"], "")

    def test_thin_drop_is_recovered_by_the_two_signal_rule(self):
        # Short, confident, high no-speech: exactly a spoken correction, and exactly
        # what defect 3 deletes today.
        f = apply_filters([seg("delete that line", 0.9, -0.3)])
        self.assertEqual(f["app_text"], "")
        self.assertEqual(f["two_signal_text"], "delete that line")
        self.assertEqual(f["reasons"], {"thin": 1})

    def test_two_signal_rule_still_drops_the_confident_hallucination(self):
        # The measured hiss hallucination (clean.py's table): thin AND unconfident,
        # so it dies under either rule.
        f = apply_filters([seg("You", 0.899, -0.919)])
        self.assertEqual(f["app_text"], "")
        self.assertEqual(f["two_signal_text"], "")
        self.assertEqual(f["reasons"], {"thin+unconfident": 1})

    def test_two_signal_rule_re_admits_the_silence_hallucination(self):
        # The cost of the proposed fix, pinned so it cannot be discovered later: the
        # digital-silence 'You' (ns 0.691, logprob -0.711) is thin but NOT unconfident
        # — -0.711 sits above the -0.8 line — so dropping the thin rule lets it back
        # in. Phase 1 needs a third signal (the whole-utterance filler list) rather
        # than simply deleting the thin test.
        f = apply_filters([seg("You", 0.6907, -0.7109)])
        self.assertEqual(f["app_text"], "")
        self.assertEqual(f["reasons"], {"thin": 1})
        self.assertEqual(f["two_signal_text"], "You")

    def test_drops_are_annotated_in_place(self):
        segs = [seg("delete that line", 0.9, -0.3), seg("kept text here", 0.01, -0.2)]
        apply_filters(segs)
        self.assertEqual(segs[0]["drop"], "thin")
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
