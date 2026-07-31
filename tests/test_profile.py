"""P8 — what Flow measures and learns about one person, on their machine (R9).

Three mechanisms, each of which exists because a shipped constant was measured wrong
for somebody: the room, the voice, and the words.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import SAMPLE_RATE  # noqa: E402
from flow.audio import BLOCK, SpeechGate  # noqa: E402
from flow.calibrate import apply, measure  # noqa: E402
from flow.lexicon import NUL_PATH, Lexicon  # noqa: E402
from flow.profile import Profile  # noqa: E402


def tmp_profile() -> Profile:
    d = tempfile.mkdtemp()
    return Profile(Path(d) / "profile.json")


class ReplayMic:
    """Hands over a scripted stretch of audio in one go, then nothing.

    All at once so the tests can pass `seconds=0.0` and rely on `measure`'s final
    drain, rather than sleeping through a real minute per case.
    """

    def __init__(self, blocks):
        self._blocks = list(blocks)

    def drain(self):
        out, self._blocks = self._blocks, []
        return out


def room_and_voice(room_db, voice_db, room_blocks=40, voice_blocks=200, seed=3):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(room_blocks):
        out.append(rng.normal(0, 10 ** (room_db / 20), BLOCK).astype(np.float32))
    for _ in range(voice_blocks):
        out.append(rng.normal(0, 10 ** (voice_db / 20), BLOCK).astype(np.float32))
    return out


class TestPersistence(unittest.TestCase):
    def test_a_missing_profile_is_the_normal_first_run(self):
        p = tmp_profile()
        self.assertFalse(p.calibrated)
        self.assertEqual(p.learned_terms(), [])

    def test_it_round_trips(self):
        p = tmp_profile()
        p.record_calibration(-96.7, -55.0, -0.41)
        p.learn_pair("sameer", "Samir")
        p.learn_pair("sameer", "Samir")
        self.assertTrue(p.save())
        again = Profile(p.path)
        self.assertEqual(again.floor_db, -96.7)
        self.assertEqual(again.confidence, -0.41)
        self.assertEqual(again.learned_terms(), ["Samir"])

    def test_a_corrupt_file_degrades_to_defaults(self):
        p = tmp_profile()
        p.path.parent.mkdir(parents=True, exist_ok=True)
        p.path.write_text("{not json", encoding="utf-8")
        self.assertFalse(Profile(p.path).calibrated)


class TestLearnedWords(unittest.TestCase):
    def test_one_correction_is_not_yet_a_pattern(self):
        # A single "change X to Y" is as likely to be a change of mind as a mishearing.
        p = tmp_profile()
        p.learn_pair("sameer", "Samir")
        self.assertEqual(p.learned_terms(), [])

    def test_a_repeated_correction_becomes_a_hotword(self):
        p = tmp_profile()
        for _ in range(2):
            p.learn_pair("sameer", "Samir")
        self.assertEqual(p.learned_terms(), ["Samir"])

    def test_only_the_target_is_learned(self):
        # The wrong reading is what the model already produces unaided; feeding it back
        # as a hotword would bias toward the mistake.
        p = tmp_profile()
        for _ in range(3):
            p.learn_pair("some ear", "Sameer")
        self.assertNotIn("some ear", p.learned_terms())

    def test_a_sentence_is_not_a_hotword(self):
        p = tmp_profile()
        for _ in range(3):
            p.learn_pair("x", "the entire second paragraph about the migration")
        self.assertEqual(p.learned_terms(), [])

    def test_a_no_op_correction_is_ignored(self):
        p = tmp_profile()
        p.learn_pair("Samir", "samir")
        self.assertFalse(p.pairs)

    def test_the_lexicon_merges_them_after_the_file_terms(self):
        p = tmp_profile()
        for _ in range(2):
            p.learn_pair("sameer", "Samir")
        lx = Lexicon(NUL_PATH, learned=p.learned_terms)
        self.assertEqual(lx.terms(), ["Samir"])

    def test_learning_that_raises_cannot_break_decoding(self):
        lx = Lexicon(NUL_PATH, learned=lambda: 1 / 0)
        self.assertEqual(lx.terms(), [])


class TestMisrouteTelemetry(unittest.TestCase):
    def test_it_records_the_opening_words_only(self):
        # Storing whole utterances would make this a transcript of everything the user
        # regretted saying.
        p = tmp_profile()
        p.note_misroute("delete the standup line from the message please")
        self.assertEqual(list(p.misroutes), ["delete the standup"])

    def test_a_repeated_signature_is_reported_for_review(self):
        p = tmp_profile()
        for _ in range(2):
            p.note_misroute("scratch that last bit")
        self.assertEqual(p.suspected_aliases(), ["scratch that last"])

    def test_it_is_a_report_and_not_an_automatic_rule(self):
        # Adding to _ALIASES changes what a word means for every future utterance, and
        # "this was a command twice" cannot establish "this is never dictation".
        from flow.edits import _ALIASES

        p = tmp_profile()
        for _ in range(5):
            p.note_misroute("believe the last sentence")
        self.assertNotIn("believe the last", _ALIASES)


class TestCalibration(unittest.TestCase):
    def test_it_separates_the_room_from_the_voice(self):
        c = measure(ReplayMic(room_and_voice(-96.7, -45.0)), seconds=0.0)
        self.assertLess(c.floor_db, -80.0)
        self.assertGreater(c.speech_db, -55.0)

    def test_silence_alone_is_not_a_calibration(self):
        c = measure(ReplayMic(room_and_voice(-96.7, -96.5, voice_blocks=0)), seconds=0.0)
        self.assertFalse(c.usable)

    def test_the_margin_is_derived_from_the_measured_gap(self):
        p = tmp_profile()
        p.record_calibration(-96.7, -45.0, None)  # a 51.7 dB gap
        self.assertEqual(p.margin_db(), 18.0)  # clamped
        p.record_calibration(-60.0, -48.0, None)  # a 12 dB gap
        self.assertEqual(p.margin_db(), 6.0)  # clamped the other way

    def test_an_uncalibrated_profile_keeps_the_shipped_default(self):
        self.assertEqual(tmp_profile().margin_db(), 10.0)

    def test_applying_it_moves_a_live_gate(self):
        p = tmp_profile()
        p.record_calibration(-96.7, -50.0, None)
        gate = SpeechGate()
        self.assertTrue(apply(p, gate))
        self.assertEqual(gate.floor_db, -96.7)
        self.assertGreater(gate.margin_db, 6.0)

    def test_applying_nothing_changes_nothing(self):
        gate = SpeechGate()
        before = (gate.floor_db, gate.margin_db)
        self.assertFalse(apply(tmp_profile(), gate))
        self.assertEqual((gate.floor_db, gate.margin_db), before)

    def test_the_calibrated_gate_opens_on_the_voice_it_measured(self):
        # The whole point: the room that broke the shipped gate must work after this.
        blocks = room_and_voice(-96.7, -55.0)
        c = measure(ReplayMic(blocks), seconds=0.0)
        p = tmp_profile()
        p.record_calibration(c.floor_db, c.speech_db, None)
        gate = SpeechGate()
        apply(p, gate)
        rng = np.random.default_rng(5)
        voice = rng.normal(0, 10 ** (-55.0 / 20), BLOCK).astype(np.float32)
        self.assertTrue(gate.push(voice)[0])


class TestConfidenceReading(unittest.TestCase):
    def test_it_reads_the_speaker_s_own_confidence(self):
        class Asr:
            def text(self, audio, *, final=False, hotwords=""):
                self.seen = audio
                return "the deploy failed again this morning"

            def take_confidence(self):
                return -0.62

        asr = Asr()
        c = measure(ReplayMic(room_and_voice(-96.7, -45.0)), asr=asr, seconds=0.0)
        self.assertEqual(c.confidence, -0.62)
        # Only the speech reaches the model, and only the last 30 s of it.
        self.assertLessEqual(len(asr.seen), 30 * SAMPLE_RATE)

    def test_an_asr_without_the_hook_is_fine(self):
        class Old:
            def text(self, audio, *, final=False, hotwords=""):
                return "hello"

        c = measure(ReplayMic(room_and_voice(-96.7, -45.0)), asr=Old(), seconds=0.0)
        self.assertIsNone(c.confidence)


if __name__ == "__main__":
    unittest.main()
