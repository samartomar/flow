"""The macOS on-device decoder, and the rule that decides when Flow reaches for it.

The engine decides what Flow can *hear*, so the interesting tests here are not about
Swift — none of this compiles a helper — they are about the choice. Two properties carry
it:

  **`auto` never switches a working machine.** Apple's recogniser is a different engine,
  not a spare one: no `no_speech_prob`, so `clean.py` falls to the narrow filler check it
  documents for exactly that; one quality tier where Whisper has two; no hotword biasing
  for the rescue path. Reaching for it on a machine where Whisper was fine would change
  what Flow hears for a reason nobody asked about.

  **Every refusal says why.** "Not available" is four different sentences — wrong
  platform, no toolchain, a build that failed, a permission declined — and a user who
  cannot see which one has a feature that is missing for no stated reason.

The subprocess is faked at `Popen`, so the framing this file cares about — a
length-prefixed block of float32 out, one line of text back — is asserted against the
bytes actually written rather than against a Mac nobody in CI has.
"""

import struct
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.native as native  # noqa: E402
from flow.__main__ import _engine, _models_present  # noqa: E402


def args(engine="auto"):
    return mock.Mock(engine=engine)


def _only(present):
    """A `Path.exists` that is true for exactly one path.

    `mock.patch.object` cannot patch an attribute on a `Path` *instance* — they are
    read-only — so the class method is replaced and told which path is meant to be
    there. Which is the distinction under test: the helper source exists, the built
    binary does not, so a build is attempted.
    """
    return lambda self: self == present


class TestTheEngineChoice(unittest.TestCase):
    """`_engine`, which is the whole feature — the rest is plumbing."""

    def test_asking_for_whisper_gets_whisper_and_asks_nothing(self):
        # No probe, no build, no subprocess: somebody who named the engine has already
        # answered the question this function exists to ask.
        with mock.patch.object(native, "available") as probe:
            self.assertEqual(_engine(args("whisper"), "base.en", "small.en"),
                             ("whisper", ""))
        probe.assert_not_called()

    def test_auto_keeps_whisper_when_the_models_are_on_the_machine(self):
        # The property that matters most. A working machine is never switched.
        with mock.patch("flow.__main__._models_present", return_value=True), \
                mock.patch.object(native, "available") as probe:
            self.assertEqual(_engine(args(), "base.en", "small.en"), ("whisper", ""))
        probe.assert_not_called()

    def test_auto_reaches_for_native_only_when_whisper_has_nothing_to_run(self):
        # The situation this was written for: a network that blocks huggingface.co,
        # where the alternative is not a worse engine but no dictation at all.
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("flow.__main__._models_present", return_value=False), \
                mock.patch.object(native, "available", return_value=(True, "")):
            engine, why = _engine(args(), "base.en", "small.en")
        self.assertEqual(engine, "native")
        self.assertIn("models not found", why)

    def test_and_says_so_on_the_startup_line(self):
        # A silent engine change would be the one thing nobody could check.
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("flow.__main__._models_present", return_value=False), \
                mock.patch.object(native, "available", return_value=(True, "")):
            _engine, why = _engine_result()
        self.assertTrue(why.strip())

    def test_neither_engine_available_still_returns_whisper_and_names_the_reason(self):
        # Whisper will fail its own way, with its own message. What this must not do is
        # return an engine that is not there, or fail silently between the two.
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("flow.__main__._models_present", return_value=False), \
                mock.patch.object(native, "available",
                                  return_value=(False, "Dictation is off")):
            engine, why = _engine(args(), "base.en", "small.en")
        self.assertEqual(engine, "whisper")
        self.assertIn("Dictation is off", why)

    def test_asking_for_native_off_a_mac_is_refused_out_loud(self):
        said = []
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("flow.__main__.say", said.append):
            self.assertEqual(_engine(args("native"), "base.en", "small.en"),
                             ("whisper", ""))
        self.assertIn("macOS only", " ".join(said))

    def test_asking_for_native_on_a_mac_that_cannot_reports_the_reason(self):
        said = []
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("flow.__main__.say", said.append), \
                mock.patch.object(native, "available",
                                  return_value=(False, "no Swift toolchain")):
            self.assertEqual(_engine(args("native"), "base.en", "small.en"),
                             ("whisper", ""))
        self.assertIn("no Swift toolchain", " ".join(said))


def _engine_result():
    return _engine(args(), "base.en", "small.en")


class TestAutoNeverPaysForAnEngineItMayNotUse(unittest.TestCase):
    """The regression CI found, pinned so it cannot come back.

    Asking `available()` unconditionally at startup took the macOS CI leg from **35
    seconds to 643**. Every launch on a Mac without Whisper models was compiling Swift
    and then sitting on `--probe` until it timed out, because the probe waits for an
    authorization dialog a headless machine never answers.

    A user's first launch would have done the same thing: a full minute of nothing
    before a pill appeared, on a machine that had asked for none of it. So `auto` uses
    what is *ready*, and naming the engine is what builds it.
    """

    def test_auto_will_not_compile_anything(self):
        seen = {}

        def fake(compile_if_missing=True, timeout=60.0):
            seen["compile"] = compile_if_missing
            seen["timeout"] = timeout
            return False, "not built yet"

        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("flow.__main__._models_present", return_value=False), \
                mock.patch.object(native, "available", fake):
            _engine(args(), "base.en", "small.en")
        self.assertFalse(seen["compile"])

    def test_and_will_not_wait_a_minute_on_a_permission_dialog(self):
        seen = {}

        def fake(compile_if_missing=True, timeout=60.0):
            seen["timeout"] = timeout
            return False, "not built yet"

        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("flow.__main__._models_present", return_value=False), \
                mock.patch.object(native, "available", fake):
            _engine(args(), "base.en", "small.en")
        self.assertLessEqual(seen["timeout"], 15.0)

    def test_naming_the_engine_is_what_builds_it(self):
        # The other half of the rule. Somebody who typed `--engine native` has asked for
        # the compile and is willing to wait for it.
        seen = {}

        def fake(compile_if_missing=True, timeout=60.0):
            seen["compile"] = compile_if_missing
            return True, ""

        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(native, "available", fake):
            self.assertEqual(_engine(args("native"), "base.en", "small.en")[0],
                             "native")
        self.assertTrue(seen["compile"])

    def test_an_unbuilt_helper_says_how_to_build_it(self):
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(Path, "exists", return_value=False):
            ok, why = native.available(compile_if_missing=False)
        self.assertFalse(ok)
        self.assertIn("--engine native", why)

    def test_a_probe_that_hangs_is_named_as_the_dialog_it_is(self):
        # "probe failed: TimeoutExpired" is true and useless. The fix is a click, and
        # the sentence should say so.
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(native, "_run",
                                  side_effect=subprocess.TimeoutExpired("probe", 10)):
            ok, why = native.available(timeout=10.0)
        self.assertFalse(ok)
        self.assertIn("Speech Recognition", why)

    def test_every_reason_survives_the_console_the_startup_line_prints_to(self):
        # `say()` writes to a cp437 console on Windows, and these strings reach it
        # through `_engine`. An em dash here is a launch that dies on its own
        # explanation — which is exactly how this was found.
        for reason in ("not built yet", "no Swift toolchain", "probe timed out"):
            with self.subTest(reason=reason):
                pass
        import inspect

        source = inspect.getsource(native)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or '"' not in line:
                continue
            for chunk in line.split('"')[1::2]:
                with self.subTest(chunk=chunk[:40]):
                    chunk.encode("cp437")


class TestTheModelPresenceCheckNeverDownloads(unittest.TestCase):
    """It is asked *because* the network may be unusable; it must not use it."""

    def test_a_directory_holding_a_model_counts_without_asking_the_hub(self):
        # What `--model /some/path` gives. Nothing to look up.
        with mock.patch.object(Path, "exists", return_value=True):
            with mock.patch.dict(sys.modules, {"huggingface_hub": None}):
                self.assertTrue(_models_present("/somewhere/base.en"))

    def test_a_hub_lookup_is_made_offline(self):
        seen = {}
        fake = mock.Mock()

        def snapshot(repo, local_files_only=False):
            import os
            seen["offline"] = os.environ.get("HF_HUB_OFFLINE")
            seen["local_only"] = local_files_only
            return "/cache"

        fake.snapshot_download = snapshot
        with mock.patch.object(Path, "exists", return_value=False), \
                mock.patch.dict(sys.modules, {"huggingface_hub": fake}):
            self.assertTrue(_models_present("base.en"))
        self.assertEqual(seen["offline"], "1")
        self.assertTrue(seen["local_only"])

    def test_a_missing_model_is_absent_rather_than_an_exception(self):
        fake = mock.Mock()
        fake.snapshot_download = mock.Mock(side_effect=OSError("not cached"))
        with mock.patch.object(Path, "exists", return_value=False), \
                mock.patch.dict(sys.modules, {"huggingface_hub": fake}):
            self.assertFalse(_models_present("base.en"))

    def test_the_environment_is_left_as_it_was_found(self):
        # It sets HF_HUB_OFFLINE to ask its question. A launch that then downloaded
        # nothing for the rest of the session would be this function's fault.
        import os

        fake = mock.Mock()
        fake.snapshot_download = mock.Mock(return_value="/cache")
        was = os.environ.get("HF_HUB_OFFLINE")
        with mock.patch.object(Path, "exists", return_value=False), \
                mock.patch.dict(sys.modules, {"huggingface_hub": fake}):
            _models_present("base.en")
        self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), was)


class TestItRefusesOffAMacWithAReason(unittest.TestCase):
    """Pinned to a non-Mac platform rather than reading the runner's.

    These assert the *refusal*, and on a macOS runner there is nothing to refuse — it
    would go and build a real binary instead, which is a different test and a slow one.
    The suite runs on both platforms, so a test that means one thing on Windows and
    another on macOS is a test that is only half run wherever it passes.
    """

    def test_build_names_the_platform(self):
        with mock.patch.object(sys, "platform", "win32"):
            with self.assertRaises(native.NotAvailable) as caught:
                native.build()
        self.assertIn("macOS", str(caught.exception))

    def test_available_answers_false_and_why_rather_than_raising(self):
        # `available()` is called during startup. A raise there is a launch that dies
        # over a feature the machine was never going to have.
        with mock.patch.object(sys, "platform", "win32"):
            ok, why = native.available()
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_a_missing_toolchain_is_named_with_the_command_that_fixes_it(self):
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(Path, "exists", _only(native.SOURCE)), \
                mock.patch.object(native, "_run",
                                  return_value=mock.Mock(returncode=1)):
            ok, why = native.available()
        self.assertFalse(ok)
        self.assertIn("xcode-select --install", why)

    def test_a_build_error_carries_the_compilers_last_word(self):
        fail = mock.Mock(returncode=1, stderr="flow_stt.swift:9: error: no such module",
                         stdout="")
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(Path, "exists", _only(native.SOURCE)), \
                mock.patch.object(Path, "mkdir", lambda *a, **k: None), \
                mock.patch.object(native, "_run",
                                  side_effect=[mock.Mock(returncode=0), fail]):
            ok, why = native.available()
        self.assertFalse(ok)
        self.assertIn("no such module", why)


class TestTheWireFormat(unittest.TestCase):
    """A length-prefixed block of float32 out, one line of text back.

    Asserted against the bytes actually written, because the Swift on the other end is
    reading them with `load(as: UInt32.self).littleEndian` and a disagreement about
    endianness or element size is a silent mis-decode rather than an error.
    """

    def transcriber(self, reply=b"hello there\n"):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.stdout.readline.return_value = reply
        proc.stdin = mock.Mock()
        a = native.NativeTranscriber(binary=Path("/fake/flow-stt"))
        a._proc = proc
        return a, proc

    def test_it_writes_a_little_endian_count_then_the_samples(self):
        a, proc = self.transcriber()
        audio = np.arange(4, dtype=np.float32)
        a.text(audio)
        count, payload = [c[0][0] for c in proc.stdin.write.call_args_list]
        self.assertEqual(count, struct.pack("<I", 4))
        self.assertEqual(payload, audio.tobytes())

    def test_it_returns_the_line_stripped(self):
        a, _ = self.transcriber(b"  hello there  \n")
        self.assertEqual(a.text(np.zeros(4, dtype=np.float32)), "hello there")

    def test_empty_audio_never_reaches_the_helper(self):
        a, proc = self.transcriber()
        self.assertEqual(a.text(np.zeros(0, dtype=np.float32)), "")
        proc.stdin.write.assert_not_called()

    def test_audio_is_coerced_to_contiguous_float32(self):
        # A slice of a larger array is not contiguous, and `tobytes()` on it would send
        # the right numbers in the wrong order.
        a, proc = self.transcriber()
        a.text(np.arange(20, dtype=np.float64)[::2])
        payload = proc.stdin.write.call_args_list[1][0][0]
        self.assertEqual(len(payload), 10 * 4)

    def test_final_and_hotwords_are_accepted_and_ignored(self):
        # Apple's recogniser has one quality tier and no biasing. Accepting both keeps
        # `submit_rescue` and the two-tier worker working rather than raising at them.
        a, _ = self.transcriber()
        got = a.text(np.zeros(4, dtype=np.float32), final=True, hotwords="Systran")
        self.assertEqual(got, "hello there")

    def test_a_helper_that_dies_mid_utterance_reports_its_stderr(self):
        a, proc = self.transcriber(reply=b"")
        proc.stderr.read.return_value = b"flow-stt: recognizer went away\n"
        with self.assertRaises(native.NotAvailable) as caught:
            a.text(np.zeros(4, dtype=np.float32))
        self.assertIn("recognizer went away", str(caught.exception))
        self.assertIsNone(a._proc)   # so the next decode restarts it

    def test_a_broken_pipe_is_named_and_clears_the_process(self):
        a, proc = self.transcriber()
        proc.stdin.write.side_effect = OSError("broken pipe")
        with self.assertRaises(native.NotAvailable):
            a.text(np.zeros(4, dtype=np.float32))
        self.assertIsNone(a._proc)


class TestItLooksLikeATranscriberToTheSession(unittest.TestCase):
    """The protocol is one method wide, and the session reads the rest through getattr."""

    def test_it_satisfies_the_three_names_the_session_uses(self):
        a = native.NativeTranscriber(binary=Path("/fake/flow-stt"))
        for name in ("text", "load", "unload"):
            self.assertTrue(callable(getattr(a, name)), name)
        self.assertIn("loaded", dir(a))

    def test_it_reports_nothing_it_cannot_measure(self):
        # `clean.py` documents the narrow path for an engine with no `no_speech_prob`,
        # and `Session` reads `take_confidence`/`take_drops` through getattr. Absent is
        # the honest answer; a fabricated 0.0 would feed the filters a lie.
        a = native.NativeTranscriber(binary=Path("/fake/flow-stt"))
        self.assertIsNone(getattr(a, "take_confidence", None))
        self.assertIsNone(getattr(a, "take_drops", None))

    def test_unload_closes_the_helper_by_asking_first(self):
        a = native.NativeTranscriber(binary=Path("/fake/flow-stt"))
        proc = mock.Mock()
        proc.poll.return_value = 0
        a._proc = proc
        a.unload()
        proc.stdin.close.assert_called_once()
        proc.kill.assert_not_called()
        self.assertFalse(a.loaded)

    def test_a_helper_that_will_not_leave_is_killed(self):
        a = native.NativeTranscriber(binary=Path("/fake/flow-stt"))
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired("flow-stt", 2.0)
        a._proc = proc
        a.unload()
        proc.kill.assert_called_once()

    def test_unloading_twice_is_not_an_error(self):
        a = native.NativeTranscriber(binary=Path("/fake/flow-stt"))
        a.unload()
        a.unload()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
