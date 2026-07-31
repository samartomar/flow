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

from asr_bench import median, summarise_gate, wer  # noqa: E402


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


class TestWer(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(wer("hello there", "Hello, there!"), 0.0)

    def test_one_substitution_in_four(self):
        self.assertAlmostEqual(wer("a b c d", "a b x d"), 0.25)

    def test_empty_hypothesis_is_total_loss(self):
        self.assertEqual(wer("a b c", ""), 1.0)


if __name__ == "__main__":
    unittest.main()
