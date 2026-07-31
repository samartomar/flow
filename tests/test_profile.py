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
from flow.audio import (  # noqa: E402
    BLOCK,
    FLOOR_MAX_DB,
    FLOOR_MIN_DB,
    SpeechGate,
)
from flow.calibrate import apply, measure  # noqa: E402
from flow.clean import (  # noqa: E402
    LOW_CONFIDENCE,
    confidence_floor,
    invented_reason,
)
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


class TestPerSpeakerConfidence(unittest.TestCase):
    """P8: the drop filter's second signal, made relative to the speaker.

    `avg_logprob` is not comparable between speakers, so one absolute bar means
    different things to different people — measured, -0.8 sits 0.5 below a typical
    speaker's baseline and only 0.18 below a Spanish-accented one.
    """

    def test_no_calibration_keeps_the_shipped_bar(self):
        self.assertEqual(confidence_floor(None), LOW_CONFIDENCE)

    def test_a_lower_baseline_relaxes_the_bar(self):
        # The whole point: the accent that scored worst stops being filtered hardest.
        self.assertLess(confidence_floor(-0.62), LOW_CONFIDENCE)

    def test_calibration_can_never_tighten_the_bar(self):
        # A speaker whose clean speech reads -0.19 would otherwise get -0.69 and start
        # losing words they never used to lose. Measuring yourself buys leniency; it
        # cannot cost you.
        for baseline in (-0.193, -0.05, 0.0, -0.29):
            self.assertEqual(confidence_floor(baseline), LOW_CONFIDENCE, baseline)

    def test_the_filter_uses_it(self):
        # Only reachable once no_speech_prob has already fired: one signal never drops.
        self.assertEqual(
            invented_reason("some real words", 0.9, -0.95), "unconfident"
        )
        self.assertIsNone(
            invented_reason("some real words", 0.9, -0.95, baseline=-0.62)
        )

    def test_confident_speech_is_never_dropped_either_way(self):
        self.assertIsNone(invented_reason("some real words", 0.2, -0.95))

    def test_the_transcriber_carries_the_baseline(self):
        from flow.asr import WhisperTranscriber

        self.assertEqual(WhisperTranscriber(baseline=-0.62).baseline, -0.62)
        self.assertIsNone(WhisperTranscriber().baseline)


class TestCalibrationRefusesDigitalSilence(unittest.TestCase):
    """A muted or noise-gated mic emits exact zeros, and they are not a room.

    The gate already refuses to learn its floor from digital silence. Calibration did
    not, so it would store -180 dB and `apply` would push that straight past the very
    guard the gate has — leaving a gate that opens on anything. Found by calibrating on
    synthesised speech, which pads with exact zeros between sentences.
    """

    def test_zero_blocks_do_not_become_the_floor(self):
        rng = np.random.default_rng(4)
        voice = [rng.normal(0, 10 ** (-45 / 20), BLOCK).astype(np.float32)
                 for _ in range(200)]
        room = [rng.normal(0, 10 ** (-70 / 20), BLOCK).astype(np.float32)
                for _ in range(60)]
        digital = [np.zeros(BLOCK, dtype=np.float32) for _ in range(60)]
        c = measure(ReplayMic(digital + room + voice), seconds=0.0)
        self.assertGreater(c.floor_db, -120.0)

    def test_the_floor_stays_inside_the_gate_s_own_bounds(self):
        # A stored profile must never describe a gate the gate would refuse to become.
        rng = np.random.default_rng(9)
        blocks = [np.zeros(BLOCK, dtype=np.float32) for _ in range(40)]
        blocks += [rng.normal(0, 10 ** (-30 / 20), BLOCK).astype(np.float32)
                   for _ in range(200)]
        c = measure(ReplayMic(blocks), seconds=0.0)
        self.assertGreaterEqual(c.floor_db, FLOOR_MIN_DB)
        self.assertLessEqual(c.floor_db, FLOOR_MAX_DB)

    def test_an_all_silent_reading_is_not_usable(self):
        digital = [np.zeros(BLOCK, dtype=np.float32) for _ in range(120)]
        self.assertFalse(measure(ReplayMic(digital), seconds=0.0).usable)


class TestLearningUsesTheRemovedText(unittest.TestCase):
    """The confusion pair comes from the two drafts, not from the spoken command.

    "change sameer to Samir" is transcribed "change Samir to Samir": the spoken target
    and the payload are homophones, which is exactly *why* the correction was needed.
    Learning from the plan therefore threw away precisely the corrections worth
    learning — every pair it kept was one where the model had already heard both sides
    correctly.
    """

    DRAFT = "hi priya, sameer is writing the release notes."

    def _session(self, profile):
        from flow.session import Session

        class NoAsr:
            def load(self, final=None): ...

            def text(self, a, *, final=False, hotwords=""):
                return ""

        class Dead:
            level_db = -70.0

            def start(self): ...

            def stop(self): ...

            @property
            def active(self):
                return True

            def restart(self): ...

            def drain(self):
                return []

        return Session(asr=NoAsr(), mic=Dead(), profile=profile)

    def test_a_homophone_correction_is_still_learned(self):
        p = tmp_profile()
        s = self._session(p)
        for _ in range(2):
            s.draft.set(self.DRAFT)
            # What the transcriber produces for "change sameer to Samir".
            s._route("change Samir to Samir")
        self.assertEqual(p.learned_terms(), ["Samir"])

    def test_the_wrong_reading_is_the_one_that_was_removed(self):
        p = tmp_profile()
        s = self._session(p)
        s.draft.set(self.DRAFT)
        s._route("change Samir to Samir")
        self.assertIn("sameer -> Samir", p.pairs)

    def test_an_edit_that_removes_nothing_teaches_nothing(self):
        p = tmp_profile()
        s = self._session(p)
        s.draft.set("hi priya, Samir is writing the notes.")
        s._route("change Samir to Samir")
        self.assertFalse(p.pairs)
