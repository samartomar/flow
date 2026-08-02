"""P8 — what Flow measures and learns about one person, on their machine (R9).

Three mechanisms, each of which exists because a shipped constant was measured wrong
for somebody: the room, the voice, and the words.
"""

import json
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
from flow.profile import MAX_WORKSPACES, Profile, path_key  # noqa: E402


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


class TestCorrectionsTeachVocabularyOnTheFly(unittest.TestCase):
    """P4: a spoken correction is a labelled confusion pair, so it should be the way a
    name enters the decode bias — no file to edit, no restart.

    It mostly was not. Three separate gaps meant the corrections people actually make
    taught nothing: case fixes were discarded as no-ops, punctuation split the counter
    so a name corrected twice never reached the promotion threshold, and the case
    operations were not in the learnable set at all despite "capitalize sameer" being
    how anyone fixes a name — it is item 3 on the recording sheet.
    """

    DRAFT = "hi priya, sameer is writing the notes."
    OTHER = "I told priya about the migration."

    def _learn(self, pairs):
        """Drive the real router and the real learning path over (utterance, draft)."""
        from flow.edits import added_text, apply_local, plan, removed_text
        from flow.session import LEARNABLE

        p = tmp_profile()
        for utterance, draft in pairs:
            planned = plan(utterance, draft)
            if planned.kind != "local":
                continue
            new, applied = apply_local(draft, planned)
            if applied and planned.op in LEARNABLE:
                gone = removed_text(draft, new).split(" … ")[0]
                got = added_text(draft, new).split(" … ")[0]
                p.learn_pair(gone, got or planned.payload)
        return p

    def test_capitalising_a_name_teaches_it(self):
        p = self._learn([("capitalize sameer", self.DRAFT)] * 2)
        self.assertEqual(p.learned_terms(), ["Sameer"])

    def test_punctuation_does_not_split_the_counter(self):
        # "priya," in one sentence and "priya" in the next is the same name. Kept as
        # two keys, each is stuck at one and neither is ever promoted.
        p = self._learn([
            ("change priya to Priya", self.DRAFT),
            ("change priya to Priya", self.OTHER),
        ])
        self.assertEqual(p.learned_terms(), ["Priya"])

    def test_two_different_phrasings_of_the_same_fix_agree(self):
        p = self._learn([
            ("capitalize priya", self.DRAFT),
            ("change priya to Priya", self.OTHER),
        ])
        self.assertEqual(p.learned_terms(), ["Priya"])

    def test_an_acronym_is_learned(self):
        p = self._learn([("all caps nasa", "i work at nasa today.")] * 2)
        self.assertEqual(p.learned_terms(), ["NASA"])

    def test_lower_casing_teaches_nothing(self):
        # Formatting, not vocabulary. Biasing the decoder toward a common phrase is the
        # measured harm in flow/lexicon.py, not the benefit.
        p = self._learn([("lowercase RELEASE NOTES", "the RELEASE NOTES are ready.")] * 2)
        self.assertEqual(p.learned_terms(), [])

    def test_an_all_lower_case_identifier_is_still_learned(self):
        # The guard above tests the *pair*, not the case of the result: "kubectl" is
        # not a case variant of "cube cuttle", and it is worth biasing toward.
        p = self._learn([("change cube cuttle to kubectl", "run cube cuttle apply now.")] * 2)
        self.assertEqual(p.learned_terms(), ["kubectl"])

    def test_one_correction_is_not_enough(self):
        # Once is as likely to be the user changing their mind as the model mishearing.
        p = self._learn([("capitalize sameer", self.DRAFT)])
        self.assertEqual(p.learned_terms(), [])

    def test_a_learned_term_reaches_the_decoder_without_a_lexicon_file(self):
        p = self._learn([("capitalize sameer", self.DRAFT)] * 2)
        lx = Lexicon(NUL_PATH, learned=p.learned_terms)
        self.assertEqual(lx.hotwords(), "Sameer")


class TestTheAutoAskChoiceIsRemembered(unittest.TestCase):
    """P9's countdown can be switched off, and switching it off lasted until you quit.

    Auto-ask is the one setting in this app that decides whether the user's words leave
    the machine without a press. Somebody who turns it off has said something about how
    they want to work, and asking them to say it again every launch is the app not
    listening — the same argument `set_voice` already makes for saving immediately
    rather than at the next Send.

    The default stays on. The field is additive and absent reads as on, so nobody who
    already has a profile gets a preference they never expressed.
    """

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

        s = Session(asr=NoAsr(), mic=Dead(), profile=profile)
        self.addCleanup(s.close)
        return s

    def test_a_fresh_profile_has_it_on(self):
        self.assertTrue(tmp_profile().auto_ask)

    def test_a_session_starts_from_what_the_profile_says(self):
        p = tmp_profile()
        p.auto_ask = False
        self.assertFalse(self._session(p).auto_ask)

    def test_a_session_without_a_profile_is_still_on(self):
        self.assertTrue(self._session(None).auto_ask)

    def test_turning_it_off_is_on_disk_before_the_next_send(self):
        # Saved through the same path a voice is, and for the same reason: someone who
        # switches it off and closes the app has still made the choice.
        p = tmp_profile()
        self._session(p).toggle_auto_ask()
        self.assertFalse(Profile(p.path).auto_ask, "the choice did not survive")

    def test_and_turning_it_back_on_is_too(self):
        p = tmp_profile()
        p.auto_ask = False
        s = self._session(p)
        s.toggle_auto_ask()
        self.assertTrue(Profile(p.path).auto_ask)

    def test_a_profile_written_before_this_existed_reads_as_on(self):
        p = tmp_profile()
        p.save()
        raw = json.loads(p.path.read_text(encoding="utf-8"))
        del raw["auto_ask"]
        p.path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertTrue(Profile(p.path).auto_ask)

    def test_a_null_reads_as_on_as_well(self):
        # `bool(None)` is False, which would turn "this key was never written" into a
        # preference for off — the one reading the default may not have.
        p = tmp_profile()
        p.save()
        raw = json.loads(p.path.read_text(encoding="utf-8"))
        raw["auto_ask"] = None
        p.path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertTrue(Profile(p.path).auto_ask)

    def test_the_schema_did_not_move(self):
        # Every read has a fallback, so an older Flow ignores a key it does not know and
        # a newer Flow reads an older file. A bump would throw both of those away, and
        # with them somebody's calibration.
        p = tmp_profile()
        p.save()
        self.assertEqual(json.loads(p.path.read_text(encoding="utf-8"))["schema"], 1)


class NamedMic:
    """A mic that knows what it is, and can come back as a different one.

    `becomes` is the unplug: the health check finds the stream dead, reopens it, and
    what it reopens onto is whatever the system now calls the default input.
    """

    def __init__(self, name: str = "USB Condenser") -> None:
        self.device_name = name
        self.level_db = -70.0
        self.restarts = 0
        self.becomes: str | None = None
        self._active = True

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return self._active

    def restart(self) -> None:
        self.restarts += 1
        self._active = True
        if self.becomes is not None:
            self.device_name = self.becomes

    def drain(self):
        return []


class TestCalibrationRemembersItsMicrophone(unittest.TestCase):
    """A calibration measures a room *through a device*, and said so nowhere.

    Floor, margin and this speaker's confidence baseline all move with the microphone:
    the room that broke the shipped gate read −96.7 dB on a good USB mic, and a laptop's
    built-in array in the same room does not read anything like that. Applying one
    device's numbers to another applies numbers that describe nothing, and until now
    swapping microphones produced no sign of it at all.

    Advisory, deliberately. A stored calibration is still better than the shipped
    default, and refusing it because a device name changed would punish someone for
    plugging in a headset.
    """

    def _session(self, profile, mic):
        from flow.session import Session

        class NoAsr:
            def load(self, final=None): ...

            def text(self, a, *, final=False, hotwords=""):
                return ""

        s = Session(asr=NoAsr(), mic=mic, profile=profile)
        self.addCleanup(s.close)
        return s

    def _calibrated(self, device="USB Condenser"):
        p = tmp_profile()
        p.record_calibration(-96.7, -50.0, -0.41, device=device)
        return p

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_a_fresh_profile_names_no_device(self):
        self.assertIsNone(tmp_profile().calibrated_device)

    def test_the_device_round_trips(self):
        p = self._calibrated()
        p.save()
        self.assertEqual(Profile(p.path).calibrated_device, "USB Condenser")

    def test_a_profile_written_before_this_existed_still_loads(self):
        p = self._calibrated()
        p.save()
        raw = json.loads(p.path.read_text(encoding="utf-8"))
        del raw["calibrated_device"]
        p.path.write_text(json.dumps(raw), encoding="utf-8")
        again = Profile(p.path)
        self.assertTrue(again.calibrated, "the rest of the calibration was lost")
        self.assertIsNone(again.calibrated_device)

    def test_the_same_microphone_says_nothing(self):
        s = self._session(self._calibrated(), NamedMic("USB Condenser"))
        s.start()
        self.assertNotIn("calibrat", self.notes(s))

    def test_a_different_microphone_is_pointed_out(self):
        s = self._session(self._calibrated(), NamedMic("Laptop Array"))
        s.start()
        note = self.notes(s)
        self.assertIn("USB Condenser", note)
        self.assertIn("Laptop Array", note)

    def test_the_calibration_is_still_applied(self):
        # Advisory only: the numbers are still better than the shipped defaults.
        from flow.calibrate import apply

        p = self._calibrated()
        s = self._session(p, NamedMic("Laptop Array"))
        s.start()
        self.assertTrue(apply(p, s.gate))
        self.assertEqual(s.gate.floor_db, -96.7)

    def test_it_is_said_once_and_not_every_health_tick(self):
        s = self._session(self._calibrated(), NamedMic("Laptop Array"))
        s.start()
        s.events()
        for _ in range(20):
            s.tick()
        self.assertNotIn("calibrat", self.notes(s))

    def test_a_restart_onto_a_different_device_is_pointed_out(self):
        from flow import session as session_mod

        mic = NamedMic("USB Condenser")
        mic.becomes = "Laptop Array"
        s = self._session(self._calibrated(), mic)
        s.start()
        s.events()
        mic._active = False  # the USB mic was unplugged mid-session
        with mock.patch.object(session_mod, "MIC_CHECK_SEC", 0.0):
            s.tick()
        self.assertEqual(mic.restarts, 1, "the health check never reopened it")
        self.assertIn("Laptop Array", self.notes(s))

    def test_an_uncalibrated_profile_says_nothing(self):
        s = self._session(tmp_profile(), NamedMic("Laptop Array"))
        s.start()
        self.assertNotIn("calibrat", self.notes(s))

    def test_a_profile_calibrated_before_devices_were_recorded_says_nothing(self):
        # Nothing to compare against is not evidence of a mismatch.
        s = self._session(self._calibrated(device=None), NamedMic("Laptop Array"))
        s.start()
        self.assertNotIn("calibrat", self.notes(s))

    def test_a_mic_that_cannot_name_itself_says_nothing(self):
        mic = NamedMic("")
        s = self._session(self._calibrated(), mic)
        s.start()
        self.assertNotIn("calibrat", self.notes(s))

    def test_calibrating_records_the_microphone_it_measured(self):
        from flow.calibrate import run

        p = tmp_profile()
        mic = ReplayMic(room_and_voice(-96.7, -45.0))
        mic.device_name = "USB Condenser"
        self.assertTrue(run(mic, p, seconds=0.0, log=lambda *_a: None))
        self.assertEqual(p.calibrated_device, "USB Condenser")

    def test_a_mic_the_platform_will_not_name_stores_nothing(self):
        from flow.calibrate import run

        p = tmp_profile()
        self.assertTrue(run(ReplayMic(room_and_voice(-96.7, -45.0)), p,
                            seconds=0.0, log=lambda *_a: None))
        self.assertIsNone(p.calibrated_device)


class TestTheMicCanNameItself(unittest.TestCase):
    def test_an_impossible_device_index_is_reported_as_unknown(self):
        # By name and never by index: indexes are assigned in enumeration order and
        # move when something is plugged in, so a stored index would come to mean a
        # different microphone — the exact confusion this exists to catch.
        from flow.audio import Mic

        self.assertEqual(Mic(device=99_999).device_name, "")


class TestTheWorkspaceRecents(unittest.TestCase):
    """Item 36: every path that arrives via --cwd joins a bounded recents list.

    Additive like `voice` and `workspace` before it — an older profile loads with an
    empty list and the schema stays 1. The dedup key is the OS's own idea of path
    identity, so a relaunch with the same flag spelled differently moves the entry to
    the front instead of growing the list, and the cap is the menu-stall budget that
    already bounds the offers and the presets: the submenu must not grow with usage.
    """

    def test_a_path_joins_the_list_exactly_once(self):
        p = tmp_profile()
        p.note_workspace(r"D:\dev\acme")
        p.note_workspace(r"D:\dev\acme")
        self.assertEqual(p.workspaces, [r"D:\dev\acme"])

    def test_a_respelt_path_is_the_same_workspace(self):
        # Separators, case and a trailing slash are spelling, not identity, on this
        # OS — and the stored form is the canonical spelling of the latest arrival.
        p = tmp_profile()
        p.note_workspace(r"D:\dev\acme")
        p.note_workspace("D:/DEV/acme/")
        self.assertEqual(p.workspaces, [r"D:\DEV\acme"])

    def test_most_recent_first_and_the_sixth_evicts_the_oldest(self):
        p = tmp_profile()
        for i in range(MAX_WORKSPACES + 1):
            p.note_workspace(rf"D:\dev\p{i}")
        self.assertEqual(len(p.workspaces), MAX_WORKSPACES)
        self.assertEqual(p.workspaces[0], rf"D:\dev\p{MAX_WORKSPACES}")
        self.assertNotIn(r"D:\dev\p0", p.workspaces)

    def test_a_re_noted_workspace_moves_to_the_front_rather_than_duplicating(self):
        # A tap is a use: the daily driver must not be evicted by one-off flags.
        p = tmp_profile()
        for name in ("a", "b", "c"):
            p.note_workspace(rf"D:\dev\{name}")
        p.note_workspace(r"D:\dev\a")
        self.assertEqual(p.workspaces[0], r"D:\dev\a")
        self.assertEqual(len(p.workspaces), 3)

    def test_the_list_survives_a_reload(self):
        p = tmp_profile()
        p.note_workspace(r"D:\dev\acme")
        self.assertTrue(p.save())
        self.assertEqual(Profile(p.path).workspaces, [r"D:\dev\acme"])

    def test_an_older_profile_loads_with_an_empty_list(self):
        p = tmp_profile()
        p.path.write_text('{"schema": 1}', encoding="utf-8")
        self.assertTrue(p.load())
        self.assertEqual(p.workspaces, [])

    def test_a_hand_grown_file_is_bounded_on_load_not_just_on_save(self):
        # The cap is a menu-stall budget, so it has to hold against the file too — a
        # list grown by hand must not buy a longer menu than the flag can.
        p = tmp_profile()
        p.path.write_text(json.dumps({
            "schema": 1,
            "workspaces": [rf"D:\dev\p{i}" for i in range(20)],
        }), encoding="utf-8")
        self.assertTrue(p.load())
        self.assertEqual(len(p.workspaces), MAX_WORKSPACES)

    def test_blank_never_joins(self):
        p = tmp_profile()
        p.note_workspace("")
        p.note_workspace("   ")
        self.assertEqual(p.workspaces, [])

    def test_path_key_is_the_os_identity_and_none_stays_none(self):
        self.assertEqual(path_key(r"D:\dev\X"), path_key("D:/DEV/x/"))
        self.assertIsNone(path_key(None))
        self.assertIsNone(path_key(""))
