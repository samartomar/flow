"""Tests for the decode parameters themselves.

These are one-line settings with measured, load-bearing consequences — an uncapped
temperature ladder cost 2.40 s on a 1 s accented prefix against a 1.5 s budget, and
7.6 s on 5 s of room noise. Settings that expensive are worth a test that fails when
someone "tidies" them.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.asr import (  # noqa: E402
    DROP_HISTORY,
    FINAL_BEAM,
    FINAL_TEMPERATURES,
    LOG_PROB_THRESHOLD,
    NO_SPEECH_THRESHOLD,
    PARTIAL_BEAM,
    PARTIAL_TEMPERATURES,
    WhisperTranscriber,
    decode_options,
)

AUDIO = np.zeros(1600, dtype=np.float32)


class FakeSegment:
    def __init__(self, text, no_speech_prob=0.01, avg_logprob=-0.2):
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob


def transcribe_with(segments, final=True):
    """Run text() over canned segments and return (text, transcriber)."""
    fake = mock.Mock()
    fake.transcribe.return_value = (iter(segments), None)
    with mock.patch("faster_whisper.WhisperModel", return_value=fake):
        asr = WhisperTranscriber("base.en")
        out = asr.text(AUDIO, final=final)
    return out, asr


def call_kwargs(final: bool) -> dict:
    fake = mock.Mock()
    fake.transcribe.return_value = ([], None)
    with mock.patch("faster_whisper.WhisperModel", return_value=fake):
        WhisperTranscriber("base.en").text(AUDIO, final=final)
    return fake.transcribe.call_args.kwargs


class TestDecodeOptions(unittest.TestCase):
    def test_partials_never_retry(self):
        # The whole point: a partial is replaced within seconds, so it must not buy
        # quality with latency. One temperature means one decode, always.
        self.assertEqual(decode_options(final=False)["temperature"], (0.0,))
        self.assertEqual(len(PARTIAL_TEMPERATURES), 1)

    def test_finals_retry_but_only_three_times(self):
        self.assertEqual(decode_options(final=True)["temperature"], (0.0, 0.2, 0.4))
        self.assertLessEqual(len(FINAL_TEMPERATURES), 3)
        self.assertEqual(FINAL_TEMPERATURES[0], 0.0)

    def test_partials_are_greedy_and_finals_are_not(self):
        self.assertEqual(decode_options(final=False)["beam_size"], PARTIAL_BEAM)
        self.assertEqual(decode_options(final=True)["beam_size"], FINAL_BEAM)
        self.assertLess(PARTIAL_BEAM, FINAL_BEAM)

    def test_language_is_pinned_and_vad_stays_off(self):
        for final in (False, True):
            opts = decode_options(final)
            self.assertEqual(opts["language"], "en")
            self.assertIs(opts["vad_filter"], False)
            self.assertIs(opts["condition_on_previous_text"], False)


class TestOptionsReachTheModel(unittest.TestCase):
    """decode_options() is only useful if text() actually passes it through."""

    def test_partial_call(self):
        kw = call_kwargs(final=False)
        self.assertEqual(kw["temperature"], PARTIAL_TEMPERATURES)
        self.assertEqual(kw["beam_size"], PARTIAL_BEAM)

    def test_final_call(self):
        kw = call_kwargs(final=True)
        self.assertEqual(kw["temperature"], FINAL_TEMPERATURES)
        self.assertEqual(kw["beam_size"], FINAL_BEAM)

    def test_the_library_filter_is_turned_off_explicitly(self):
        # Defect 2: with a threshold set, faster-whisper deletes segments before Flow
        # sees them. 5 of 9 measured silent deletions happened there.
        for final in (False, True):
            self.assertIsNone(decode_options(final)["no_speech_threshold"])
        self.assertIsNone(NO_SPEECH_THRESHOLD)
        self.assertIsNone(call_kwargs(final=True)["no_speech_threshold"])

    def test_low_confidence_alone_never_triggers_a_retry(self):
        # Retrying because the model was unsure is what cost 3.66s on a 5s noise clip
        # while buying no measurable accuracy. Degenerate output still retries, via
        # the library's compression_ratio_threshold, which stays at its default.
        for final in (False, True):
            self.assertIsNone(decode_options(final)["log_prob_threshold"])
        self.assertIsNone(LOG_PROB_THRESHOLD)
        self.assertNotIn("compression_ratio_threshold", decode_options(True))

    def test_empty_audio_never_reaches_the_model(self):
        fake = mock.Mock()
        with mock.patch("faster_whisper.WhisperModel", return_value=fake):
            asr = WhisperTranscriber("base.en")
            self.assertEqual(asr.text(np.zeros(0, dtype=np.float32)), "")
        fake.transcribe.assert_not_called()


class TestDropLog(unittest.TestCase):
    """P2: a rejection is allowed; an unexplained one is not."""

    def test_a_dropped_segment_is_recorded_with_its_signals(self):
        out, asr = transcribe_with([FakeSegment("You", 0.9, -0.95)])
        self.assertEqual(out, "")
        drops = asr.take_drops()
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0].text, "You")
        self.assertEqual(drops[0].reason, "filler")
        self.assertAlmostEqual(drops[0].no_speech_prob, 0.9)
        self.assertAlmostEqual(drops[0].avg_logprob, -0.95)
        self.assertTrue(drops[0].final)

    def test_kept_segments_are_not_recorded(self):
        out, asr = transcribe_with([FakeSegment("send the report to the team")])
        self.assertEqual(out, "send the report to the team")
        self.assertEqual(asr.take_drops(), [])

    def test_partial_survivors_and_drops_coexist(self):
        out, asr = transcribe_with([
            FakeSegment("You", 0.9, -0.95),
            FakeSegment("the real sentence"),
        ])
        self.assertEqual(out, "the real sentence")
        self.assertEqual([d.reason for d in asr.take_drops()], ["filler"])

    def test_describe_carries_the_evidence(self):
        _, asr = transcribe_with([FakeSegment("You", 0.9, -0.95)], final=False)
        line = asr.take_drops()[0].describe()
        for fragment in ("'You'", "filler", "ns=0.90", "lp=-0.95", "partial"):
            self.assertIn(fragment, line)

    def test_taking_drops_clears_them(self):
        _, asr = transcribe_with([FakeSegment("You", 0.9, -0.95)])
        self.assertEqual(len(asr.take_drops()), 1)
        self.assertEqual(asr.take_drops(), [])

    def test_the_log_is_bounded(self):
        # R8: a long session costs what a short one costs, even one that drops a lot.
        _, asr = transcribe_with(
            [FakeSegment("You", 0.9, -0.95) for _ in range(DROP_HISTORY + 50)]
        )
        self.assertEqual(len(asr.take_drops()), DROP_HISTORY)


if __name__ == "__main__":
    unittest.main()
