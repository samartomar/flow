"""Choosing the speech engine live: `Session.set_engine`, and the profile that remembers it.

What is pinned, in the order a switch meets it:

  **It refuses while anything is using the transcriber**, with a reason — the microphone
  open, speech being gated, a decode queued or running, a reply playing — and nothing is
  built, swapped or unloaded when it does.

  **No decode is ever handed a transcriber that has been unloaded.** The new engine is
  loaded off the session's thread, the swap is made under the decode worker's own lock
  only if nothing is queued, and the old engine is unloaded *after* the worker points at
  the new one. If the person started talking while it loaded, the switch is abandoned and
  the engine just loaded is released.

  **The choice is remembered only once it has happened**, and a bad value in the profile
  is a named fault rather than a crash.
"""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import parakeet  # noqa: E402
from flow.profile import ENGINES, Profile  # noqa: E402
from flow.session import DecodeWorker, Session  # noqa: E402


class FakeMic:
    def __init__(self) -> None:
        self.level_db = -60.0

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def drain(self):
        return []


class FakeEngine:
    """A transcriber that records what was done to it."""

    def __init__(self, engine: str, load_gate: threading.Event | None = None,
                 variant: str = "") -> None:
        self.engine = engine
        if variant:
            self.variant = variant
        self.loaded = False
        self.calls: list[str] = []
        self._gate = load_gate

    def load(self, final=None) -> None:
        if self._gate is not None:
            self._gate.wait(5)
        self.loaded = True
        self.calls.append("load")

    def warmup(self) -> None:
        self.calls.append("warmup")

    def unload(self) -> None:
        self.loaded = False
        self.calls.append("unload")

    def text(self, audio, *, final=False, hotwords="") -> str:
        if not self.loaded:
            raise AssertionError(f"{self.engine} decoded while unloaded")
        return self.engine


def reloaded(path) -> Profile:
    p = Profile(path)
    p.load()
    return p


def pump(session, until, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        session.pump_results()
        if until():
            return True
        time.sleep(0.01)
    return False


def notes(session):
    return [e.text for e in session._events if e.kind == "note"]


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.profile = Profile(Path(self._tmp.name) / "profile.json")
        self.whisper = FakeEngine("whisper")
        self.whisper.loaded = True
        self.session = Session(asr=self.whisper, mic=FakeMic(), profile=self.profile)
        self.addCleanup(self.session.close)
        self.built: list[FakeEngine] = []
        self.gate: threading.Event | None = None

        def factory(name, variant=None):
            engine = FakeEngine(name, self.gate, variant or "")
            self.built.append(engine)
            return engine

        self.session.engine_factory = factory
        # Parakeet is installed and downloaded, unless a test says otherwise.
        for target, value in (("runtime_installed", (True, "")),
                              ("model_present", True)):
            patch = mock.patch.object(parakeet, target, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def switch(self, name="parakeet", variant=None):
        self.assertTrue(self.session.set_engine(name, variant))
        self.assertTrue(pump(self.session, lambda: not self.session._switching_engine))


class TestSwitching(_Case):
    def test_it_loads_the_new_engine_swaps_it_in_and_unloads_the_old_one(self):
        self.switch()
        new = self.built[0]
        self.assertEqual(self.session.engine, "parakeet")
        self.assertIs(self.session.asr, new)
        self.assertIs(self.session.worker._asr, new)  # the decoder follows
        self.assertEqual(new.calls, ["load", "warmup"])
        self.assertEqual(self.whisper.calls[-1], "unload")
        self.assertIn("speech engine: parakeet (fp32)", notes(self.session))

    def test_the_choice_is_remembered_in_the_profile_once_it_has_happened(self):
        self.assertEqual(self.profile.engine, "whisper")
        self.switch()
        self.assertEqual(reloaded(self.profile.path).engine, "parakeet")

    def test_switching_back_reuses_the_engine_it_already_has(self):
        self.switch("parakeet")
        self.switch("whisper")
        self.assertIs(self.session.asr, self.whisper)
        self.assertEqual(len(self.built), 1)  # the factory was only needed once
        self.assertEqual(self.profile.engine, "whisper")

    def test_the_engine_in_use_is_a_no_op(self):
        self.assertTrue(self.session.set_engine("whisper"))
        self.assertEqual(self.built, [])

    def test_a_decode_after_the_switch_runs_on_the_new_engine(self):
        self.switch()
        self.session.worker.submit_final(np.zeros(1600, dtype=np.float32))
        self.assertTrue(pump(self.session, lambda: "parakeet" in self.session.draft.text))

    def test_an_engine_that_will_not_load_leaves_the_old_one_running(self):
        def boom(name, variant=None):
            engine = FakeEngine(name)
            engine.load = mock.Mock(side_effect=RuntimeError("no memory"))
            return engine

        self.session.engine_factory = boom
        self.assertTrue(self.session.set_engine("parakeet"))
        self.assertTrue(pump(self.session, lambda: not self.session._switching_engine))
        self.assertIs(self.session.asr, self.whisper)
        self.assertTrue(self.whisper.loaded)
        self.assertEqual(self.profile.engine, "whisper")
        self.assertTrue(any("did not load" in n for n in notes(self.session)))

    def test_a_factory_that_raises_is_a_note_and_not_a_crash(self):
        self.session.engine_factory = mock.Mock(side_effect=RuntimeError("bad"))
        self.assertFalse(self.session.set_engine("parakeet"))
        self.assertIn("could not start", notes(self.session)[-1])
        self.assertFalse(self.session._switching_engine)


class TestSwitchingBetweenBuilds(_Case):
    """fp32 and int8 are different transcribers, so a build change is an engine change."""

    def test_the_build_is_made_and_remembered(self):
        self.switch("parakeet", "int8")
        self.assertEqual((self.session.engine, self.session.engine_variant),
                         ("parakeet", "int8"))
        self.assertEqual(self.built[0].variant, "int8")
        self.assertEqual(reloaded(self.profile.path).parakeet_model, "int8")

    def test_the_other_build_goes_through_the_same_swap_and_unloads_the_first(self):
        self.switch("parakeet", "int8")
        first = self.session.asr
        self.switch("parakeet", "fp32")
        self.assertEqual(self.session.engine_variant, "fp32")
        self.assertIs(self.session.worker._asr, self.session.asr)
        self.assertEqual(first.calls[-1], "unload")
        self.assertEqual(self.profile.parakeet_model, "fp32")

    def test_the_build_already_running_is_a_no_op(self):
        self.switch("parakeet", "int8")
        built = len(self.built)
        self.assertTrue(self.session.set_engine("parakeet", "int8"))
        self.assertEqual(len(self.built), built)

    def test_going_back_to_a_build_reuses_the_instance(self):
        self.switch("parakeet", "int8")
        int8 = self.session.asr
        self.switch("parakeet", "fp32")
        self.switch("parakeet", "int8")
        self.assertIs(self.session.asr, int8)
        self.assertEqual(len(self.built), 2)

    def test_no_variant_means_the_profiles_choice(self):
        self.profile.parakeet_model = "int8"
        self.switch("parakeet")
        self.assertEqual(self.session.engine_variant, "int8")

    def test_the_build_must_be_downloaded_and_must_exist(self):
        parakeet.model_present.side_effect = lambda key, model_dir=None: key == "fp32"
        self.assertFalse(self.session.set_engine("parakeet", "int8"))
        self.assertIn("download it first", notes(self.session)[-1])
        self.assertFalse(self.session.set_engine("parakeet", "fp16"))
        self.assertIn("does not know", notes(self.session)[-1])
        self.assertEqual(self.built, [])

    def test_a_build_change_is_refused_while_decoding_like_any_engine_change(self):
        self.switch("parakeet", "fp32")
        with mock.patch.object(type(self.session.worker), "busy",
                               new_callable=mock.PropertyMock, return_value=True):
            self.assertFalse(self.session.set_engine("parakeet", "int8"))
        self.assertEqual(self.session.engine_variant, "fp32")


class TestRefusals(_Case):
    def refused(self, why_part, name="parakeet"):
        self.assertFalse(self.session.set_engine(name))
        self.assertIn(why_part, notes(self.session)[-1])
        self.assertEqual(self.built, [])
        self.assertIs(self.session.asr, self.whisper)
        self.assertEqual(self.whisper.calls, [])  # not unloaded, not touched
        self.assertEqual(self.profile.engine, "whisper")

    def test_while_the_microphone_is_open(self):
        with mock.patch.object(Session, "capturing", new_callable=mock.PropertyMock,
                               return_value=True):
            self.refused("stop listening")

    def test_while_speech_is_being_gated(self):
        self.session.gate.speaking = True
        self.refused("stop listening")

    def test_while_a_decode_is_queued(self):
        with mock.patch.object(type(self.session.worker), "busy",
                               new_callable=mock.PropertyMock, return_value=True):
            self.refused("decoded")

    def test_while_a_reply_is_playing(self):
        with mock.patch.object(Session, "talking", new_callable=mock.PropertyMock,
                               return_value=True):
            self.refused("finish the reply")

    def test_an_unknown_engine(self):
        self.refused("does not know", name="deepgram")

    def test_a_session_with_no_factory_cannot_switch(self):
        self.session.engine_factory = None
        self.refused("cannot switch")

    def test_parakeet_without_its_runtime_says_how_to_get_it(self):
        parakeet.runtime_installed.return_value = (False, "missing")
        self.refused("Parakeet add-on")
        self.assertIn('.[parakeet]', notes(self.session)[-1])

    def test_parakeet_without_its_model_says_to_download_it(self):
        parakeet.model_present.return_value = False
        self.refused("download it first")

    def test_a_second_switch_while_one_is_loading(self):
        self.gate = threading.Event()
        self.assertTrue(self.session.set_engine("parakeet"))
        self.assertFalse(self.session.set_engine("whisper"))
        self.assertIn("already switching", notes(self.session)[-1])
        self.gate.set()
        self.assertTrue(pump(self.session, lambda: not self.session._switching_engine))

    def test_whisper_is_always_allowed_when_idle(self):
        self.assertEqual(self.session.engine_refusal("whisper"), "")


class TestTheSwitchIsAbandonedIfTheyStartTalking(_Case):
    def test_speech_during_the_load_keeps_the_old_engine_and_releases_the_new(self):
        self.gate = threading.Event()
        self.assertTrue(self.session.set_engine("parakeet"))
        new = self.built[0]
        self.session.gate.speaking = True  # they started talking while it loaded
        self.gate.set()
        self.assertTrue(pump(self.session, lambda: not self.session._switching_engine))
        self.assertIs(self.session.asr, self.whisper)
        self.assertTrue(self.whisper.loaded)
        self.assertNotIn("unload", self.whisper.calls)
        self.assertEqual(new.calls[-1], "unload")
        self.assertEqual(self.profile.engine, "whisper")
        self.assertIn("kept whisper", notes(self.session)[-1])

    def test_a_decode_queued_during_the_load_blocks_the_swap_itself(self):
        # The worker's own lock is the last line: even if the busy check were skipped, a
        # queued decode refuses the swap rather than being handed another transcriber.
        worker = DecodeWorker(self.whisper)
        self.addCleanup(worker.close)
        with worker._cv:
            worker._finals.append((np.zeros(10, dtype=np.float32), None))
            self.assertFalse(worker.swap(FakeEngine("parakeet")))
            worker._finals.clear()
            self.assertTrue(worker.swap(FakeEngine("parakeet")))

    def test_closing_during_the_load_releases_what_was_loaded(self):
        self.gate = threading.Event()
        self.assertTrue(self.session.set_engine("parakeet"))
        new = self.built[0]
        self.session._closed = True
        self.gate.set()
        self.assertTrue(pump(self.session, lambda: not self.session._switching_engine))
        self.assertEqual(new.calls[-1], "unload")
        self.assertIs(self.session.asr, self.whisper)


class TestTheEngineIsAProfileSetting(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "profile.json"

    def test_it_defaults_to_whisper_which_leaves_auto_as_it_was(self):
        self.assertEqual(Profile(self.path).engine, "whisper")
        self.assertEqual(ENGINES, ("whisper", "parakeet"))

    def test_it_round_trips(self):
        p = Profile(self.path)
        p.engine = "parakeet"
        p.save()
        q = reloaded(self.path)
        self.assertEqual(q.engine, "parakeet")
        self.assertNotIn("engine", q.faults)

    def test_a_bad_value_is_a_named_fault_and_falls_back_to_whisper(self):
        self.path.write_text(json.dumps({"schema": 1, "engine": "deepgram"}),
                             encoding="utf-8")
        q = reloaded(self.path)
        self.assertEqual(q.engine, "whisper")
        self.assertIn("engine", q.faults)

    def test_a_wrong_type_is_a_fault_too(self):
        self.path.write_text(json.dumps({"schema": 1, "engine": 7}), encoding="utf-8")
        q = reloaded(self.path)
        self.assertEqual(q.engine, "whisper")

    def test_the_parakeet_build_round_trips_and_defaults_to_auto(self):
        p = Profile(self.path)
        self.assertEqual(p.parakeet_model, "auto")
        p.parakeet_model = "int8"
        p.save()
        self.assertEqual(reloaded(self.path).parakeet_model, "int8")

    def test_a_bad_parakeet_build_is_a_named_fault(self):
        self.path.write_text(json.dumps({"schema": 1, "parakeet_model": "fp16"}),
                             encoding="utf-8")
        q = reloaded(self.path)
        self.assertEqual(q.parakeet_model, "auto")
        self.assertIn("parakeet_model", q.faults)

    def test_the_profiles_choices_match_the_engines(self):
        from flow.profile import PARAKEET_MODELS

        self.assertEqual(PARAKEET_MODELS, parakeet.VARIANT_CHOICES)

    def test_an_older_profile_without_it_launches_as_before(self):
        self.path.write_text(json.dumps({"schema": 1, "decode_device": "cpu"}),
                             encoding="utf-8")
        q = reloaded(self.path)
        self.assertEqual(q.engine, "whisper")
        self.assertNotIn("engine", q.faults)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
