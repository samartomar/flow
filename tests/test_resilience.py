"""Failure-path tests.

An always-on widget that dies silently is worse than one that crashes loudly: the pill
stays on screen looking fine while doing nothing. These tests cover the paths that
produce that outcome — a raise inside the frame pump, a mic that will not open, a model
that will not load, and two threads racing to load one.
"""

import gc
import sys
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.asr import WhisperTranscriber  # noqa: E402
from flow.session import Event, Session, State  # noqa: E402


def tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        del root
        # Tcl aborts the whole process with "async handler deleted by the wrong thread"
        # if a Tk object is finalised on a thread other than the one that created it.
        # Other tests in this file start background threads, so every Tk object is
        # collected deterministically on the main thread instead of being left to chance.
        gc.collect()
        return True
    except Exception:
        return False


HAVE_TK = tk_available()


class StubDraft:
    def __init__(self) -> None:
        self.text = ""

    def clear(self) -> str:
        out, self.text = self.text, ""
        return out


class StubSession:
    """Minimal Session surface, with injectable failures."""

    def __init__(self, fail_start: bool = False, fail_tick: bool = False) -> None:
        self.fail_start = fail_start
        self.fail_tick = fail_tick
        self.state = State.IDLE
        self.draft = StubDraft()
        self.force_next = None
        self.level_db = -60.0
        self.mic = mock.Mock()
        self.started = 0
        self.paused = 0
        self.tick_calls = 0

    def start(self) -> None:
        if self.fail_start:
            raise OSError("no default input device")
        self.started += 1

    def pause(self) -> None:
        self.paused += 1

    def close(self) -> None: ...

    def tick(self) -> None:
        self.tick_calls += 1
        if self.fail_tick:
            raise RuntimeError("decoder exploded")

    def events(self) -> list[Event]:
        return []

    def send(self) -> str:
        return self.draft.clear()


@unittest.skipUnless(sys.platform == "win32", "Windows-only: ctypes.WinDLL")
@unittest.skipUnless(HAVE_TK, "no display available")
class TestPumpNeverDies(unittest.TestCase):
    def _pill(self, session):
        from flow.ui import Pill

        pill = Pill(session)

        def teardown() -> None:
            # Cancel pending `after` callbacks first. _tick reschedules itself, so a
            # queued callback outlives the widget and Tcl later complains
            # "invalid command name ..._tick" while some other root pumps events.
            try:
                for aid in pill.tk.eval("after info").split():
                    try:
                        pill.after_cancel(aid)
                    except Exception:
                        pass
            except Exception:
                pass
            # Then tear down child-first, drop the reference, and collect on *this*
            # (main) thread. Leaving it to the GC risks finalisation on a worker thread,
            # which makes Tcl abort the interpreter mid-suite.
            for step in (pill.bubble.destroy, pill.destroy):
                try:
                    step()
                except Exception:
                    pass
            gc.collect()

        self.addCleanup(teardown)
        return pill

    def test_a_raise_in_tick_does_not_escape_or_stop_the_loop(self):
        session = StubSession(fail_tick=True)
        pill = self._pill(session)
        pill.armed = True

        # The traceback print is wanted in production (visible when launched from a
        # terminal) but only noise here.
        with mock.patch.object(pill, "after") as after, mock.patch(
            "flow.ui.traceback.print_exc"
        ):
            pill._tick()  # must not raise
            # Rescheduling happens in `finally`, so the loop survives the failure.
            after.assert_called_once()
            self.assertEqual(after.call_args.args[0], 30)

        self.assertGreater(pill._flash, 0, "failure must be visible on the pill")

    def test_failing_mic_leaves_the_pill_disarmed(self):
        session = StubSession(fail_start=True)
        pill = self._pill(session)
        pill._toggle()
        # A green pill that captures nothing would be a lie about the app's state.
        self.assertFalse(pill.armed)
        self.assertEqual(session.started, 0)
        self.assertGreater(pill._flash, 0)

    def test_toggle_off_pauses_rather_than_closing(self):
        session = StubSession()
        pill = self._pill(session)
        pill._toggle()
        self.assertTrue(pill.armed)
        pill._toggle()
        self.assertFalse(pill.armed)
        self.assertEqual(session.paused, 1)


class TestSlimInstallContract(unittest.TestCase):
    """Guards the assumptions scripts/slim.py relies on to drop ~100 MB.

    Both removals are safe only because of a specific choice in `asr.py`. If that choice
    ever changes, a slimmed install breaks at runtime with an ImportError that would be
    baffling to debug — so the coupling is asserted here rather than left as a comment.
    """

    def test_vad_filter_is_never_enabled(self):
        # onnxruntime exists purely for Silero VAD and slim.py removes it.
        fake_model = mock.Mock()
        fake_model.transcribe.return_value = ([], None)
        with mock.patch("faster_whisper.WhisperModel", return_value=fake_model):
            asr = WhisperTranscriber("base.en")
            asr.text(np.zeros(1600, dtype=np.float32), final=True)
        self.assertIs(fake_model.transcribe.call_args.kwargs["vad_filter"], False)

    def test_audio_is_passed_as_an_array_never_a_path(self):
        # `av` exists purely to decode audio files, and slim.py stubs it out. Passing a
        # path here would route into decode_audio() and hit the stub.
        fake_model = mock.Mock()
        fake_model.transcribe.return_value = ([], None)
        audio = np.zeros(1600, dtype=np.float32)
        with mock.patch("faster_whisper.WhisperModel", return_value=fake_model):
            asr = WhisperTranscriber("base.en")
            asr.text(audio, final=True)
        passed = fake_model.transcribe.call_args.args[0]
        self.assertIsInstance(passed, np.ndarray)


class TestModelLoad(unittest.TestCase):
    def test_start_does_not_block_on_the_model(self):
        """First run includes a ~141 MB download; awaiting it froze the UI."""
        slow = threading.Event()

        class SlowAsr:
            loaded = False

            def load(self_inner) -> None:
                slow.wait(5.0)

            def text(self_inner, audio, *, final=False) -> str:
                return ""

        mic = mock.Mock()
        mic.drain.return_value = []
        mic.active = True
        session = Session(asr=SlowAsr(), mic=mic)

        t0 = time.perf_counter()
        session.start()
        elapsed = time.perf_counter() - t0
        slow.set()
        session.close()

        self.assertLess(elapsed, 1.0, f"start() blocked for {elapsed:.2f}s")
        mic.start.assert_called_once()

    def test_model_load_failure_becomes_an_event_not_a_crash(self):
        class BrokenAsr:
            loaded = False

            def load(self_inner) -> None:
                raise RuntimeError("could not reach huggingface.co")

            def text(self_inner, audio, *, final=False) -> str:
                return ""

        mic = mock.Mock()
        mic.drain.return_value = []
        mic.active = True
        session = Session(asr=BrokenAsr(), mic=mic)
        session.start()

        deadline = time.perf_counter() + 3.0
        errors: list[Event] = []
        while time.perf_counter() < deadline and not errors:
            errors = [e for e in session.events() if e.kind == "error"]
            time.sleep(0.02)
        session.close()

        self.assertTrue(errors, "load failure produced no error event")
        self.assertIn("could not reach", errors[0].text)

    def test_concurrent_loads_build_exactly_one_model_per_tier(self):
        """The preload thread and the decode worker can both call load().

        Two tiers now, so two builds — and not one more, however many threads race.
        """
        def slow_ctor(*_a, **_kw):
            time.sleep(0.05)
            return object()

        with mock.patch("faster_whisper.WhisperModel", side_effect=slow_ctor) as ctor:
            asr = WhisperTranscriber("base.en", "small.en")
            threads = [threading.Thread(target=asr.load) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5.0)

        self.assertEqual(ctor.call_count, 2, "a model was built more than once")
        self.assertEqual(
            sorted(c.args[0] for c in ctor.call_args_list), ["base.en", "small.en"]
        )
        self.assertTrue(asr.loaded)

    def test_a_partial_never_loads_the_finals_model(self):
        """The whole point of the split: partials must not wait on the big model."""
        with mock.patch("faster_whisper.WhisperModel") as ctor:
            asr = WhisperTranscriber("base.en", "small.en")
            ctor.return_value.transcribe.return_value = ([], None)
            asr.text(np.zeros(1600, dtype=np.float32), final=False)
        self.assertEqual([c.args[0] for c in ctor.call_args_list], ["base.en"])

    def test_a_final_loads_the_finals_model(self):
        with mock.patch("faster_whisper.WhisperModel") as ctor:
            asr = WhisperTranscriber("base.en", "small.en")
            ctor.return_value.transcribe.return_value = ([], None)
            asr.text(np.zeros(1600, dtype=np.float32), final=True)
        self.assertEqual([c.args[0] for c in ctor.call_args_list], ["small.en"])

    def test_unload_releases_both_tiers(self):
        with mock.patch("faster_whisper.WhisperModel"):
            asr = WhisperTranscriber("base.en", "small.en")
            asr.load()
            self.assertTrue(asr.loaded)
            asr.unload()
        self.assertFalse(asr.loaded)


if __name__ == "__main__":
    unittest.main()
