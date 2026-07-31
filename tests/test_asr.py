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
    FINAL_BEAM,
    FINAL_TEMPERATURES,
    PARTIAL_BEAM,
    PARTIAL_TEMPERATURES,
    WhisperTranscriber,
    decode_options,
)

AUDIO = np.zeros(1600, dtype=np.float32)


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

    def test_empty_audio_never_reaches_the_model(self):
        fake = mock.Mock()
        with mock.patch("faster_whisper.WhisperModel", return_value=fake):
            asr = WhisperTranscriber("base.en")
            self.assertEqual(asr.text(np.zeros(0, dtype=np.float32)), "")
        fake.transcribe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
