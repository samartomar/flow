"""Failure-path tests.

An always-on widget that dies silently is worse than one that crashes loudly: the pill
stays on screen looking fine while doing nothing. These tests cover the paths that
produce that outcome — a raise inside the frame pump, a mic that will not open, a model
that will not load, two threads racing to load one, and the input device going away in
the middle of a session.

That last group is the largest, and it is the one that never touches hardware: the mic
is either a fake with the real `Mic`'s attribute names on it, or the real `Mic` driven
over a fake `sounddevice`. Nothing here opens a stream, so it runs the same on the
ubuntu and macos CI legs as it does at the desk.
"""

import gc
import sys
import threading
import time
import tkinter as tk
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import audio  # noqa: E402
from flow import session as session_mod  # noqa: E402
from flow.asr import WhisperTranscriber  # noqa: E402
from flow.audio import BLOCK, STALL_SEC  # noqa: E402
from flow.session import MIC_RETRIES, DICTATE, Event, Session, State  # noqa: E402


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


# -- the input device going away mid-session ---------------------------------------
#
# Flow was already honest at *startup*: capture that will not open leaves the pill slate
# with the reason on it. What had never been exercised is the device disappearing while
# somebody is talking — a headset unplugged, a Bluetooth link dropping, Windows moving
# the default out from under an open stream — which is the failure that dominates every
# dictation app's bug tracker. The behaviour that used to produce is pinned first, in
# `TestADeadStreamNeverLooksLive`.

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)
QUIET = np.full(BLOCK, 0.0005, dtype=np.float32)  # room tone, not digital silence
SILENT = np.zeros(BLOCK, dtype=np.float32)


class SayingAsr:
    """Decodes every final to one fixed sentence, and counts them."""

    def __init__(self, said: str = "what I was saying") -> None:
        self.loaded = True
        self.finals = 0
        self._said = said

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def text(self, audio_in: np.ndarray, *, final: bool = False, **_kw) -> str:
        if not final:
            return ""
        self.finals += 1
        return self._said


class DyingMic:
    """The `Mic` surface a session actually uses, with the failure injected.

    Deliberately not a `mock.Mock`: `not Mock()` is False, so a bare mock answers "yes,
    working" to every liveness question and no test in this section could fail. The
    attribute names are the real ones — `trouble`, `pinned`, `opened_name` — because a
    fake that drifts from them is a fake that keeps passing while the app is broken.
    """

    def __init__(self, *, pinned: int | None = None, name: str = "USB Condenser",
                 becomes: str | None = None, reopens: bool = True,
                 raises: Exception | None = None) -> None:
        self.pinned = pinned
        self.opened_name = name
        self.becomes = becomes
        self.reopens = reopens
        self.raises = raises
        self.trouble = ""
        self.level_db = -70.0
        self.dropped = 0
        self.overflows = 0
        self.starts = 0
        self.stops = 0
        self.restarts = 0
        self.blocks: list[np.ndarray] = []

    # -- the failure -------------------------------------------------------
    def die(self, reason: str = "the stream stopped running") -> None:
        self.trouble = reason

    # -- the Mic surface ---------------------------------------------------
    def start(self) -> None:
        self.starts += 1
        self.trouble = ""

    def stop(self) -> None:
        self.stops += 1

    def drain(self) -> list[np.ndarray]:
        out, self.blocks = self.blocks, []
        return out

    @property
    def active(self) -> bool:
        return not self.trouble

    def restart(self) -> None:
        self.restarts += 1
        if self.raises is not None:
            raise self.raises
        if self.reopens:
            self.trouble = ""
            if self.becomes is not None:
                self.opened_name = self.becomes


class FakeStream:
    """`sd.InputStream`'s surface, plus the two ways a real one dies.

    `abort()` is what sounddevice does when a callback raises `CallbackAbort` and what a
    host API does when it gives up on a device that has been removed: the stream stops
    being active and `finished_callback` fires, with nobody having called `stop()`.
    """

    def __init__(self, **kw) -> None:
        self.kw = kw
        self.device = kw.get("device")
        self.callback = kw.get("callback")
        self.finished_callback = kw.get("finished_callback")
        self.active = False
        self.closed = False
        self.raise_on_active: Exception | None = None

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False
        if self.finished_callback is not None:
            self.finished_callback()

    def close(self) -> None:
        self.closed = True

    def abort(self) -> None:
        """The device went, or the callback did. Nobody here asked for this."""
        self.stop()

    def __getattribute__(self, name):
        # `active` is a plain attribute except when a test wants it to throw, which is
        # what a stream whose device is being pulled out can really do.
        if name == "active":
            boom = object.__getattribute__(self, "raise_on_active")
            if boom is not None:
                raise boom
        return object.__getattribute__(self, name)


class Flags:
    """`sd.CallbackFlags`: truthy when anything is set, with the flag named."""

    def __init__(self, input_overflow: bool = False) -> None:
        self.input_overflow = input_overflow

    def __bool__(self) -> bool:
        return self.input_overflow


class FakeSD:
    """The four things `flow.audio` asks of sounddevice, and nothing else.

    `plug()` stages a hardware change the way the machine really presents one: the new
    device and the new default exist, and PortAudio cannot see either until something
    terminates and re-initialises it. That staleness is the whole reason
    `audio.refresh_devices` exists, so the fake has to reproduce it or the test proves
    nothing.
    """

    def __init__(self, names=("Laptop Array",), default: int = 0) -> None:
        self.names = list(names)
        self.default = types.SimpleNamespace(device=[default, 0])
        self.streams: list[FakeStream] = []
        self.fail_next = 0
        self.terminated = 0
        self._staged: tuple[list[str], int] | None = None

    def plug(self, names, default: int) -> None:
        self._staged = (list(names), default)

    def InputStream(self, **kw) -> FakeStream:
        if self.fail_next:
            self.fail_next -= 1
            raise OSError("Error opening InputStream: Invalid device")
        stream = FakeStream(**kw)
        self.streams.append(stream)
        return stream

    def query_devices(self, index):
        return {"name": self.names[index]}

    def _terminate(self) -> None:
        self.terminated += 1

    def _initialize(self) -> None:
        if self._staged is not None:
            self.names, self.default.device[0] = self._staged
            self._staged = None


def notes_of(events) -> str:
    return " | ".join(e.text for e in events if e.kind in ("note", "error"))


class DeviceLossCase(unittest.TestCase):
    """Shared wiring: a session with an injectable microphone and no model."""

    def session(self, mic, asr=None, **kw) -> Session:
        s = Session(asr=asr or SayingAsr(), mic=mic, **kw)
        self.addCleanup(s.close)
        s.start()
        s.events()  # drop the arming events; every test here is about what follows
        return s

    def speak(self, s, mic, blocks: int = 4) -> None:
        """Put the session mid-utterance, the way a Bluetooth drop finds it."""
        mic.blocks = [QUIET] * 4 + [LOUD] * blocks
        s.tick()
        assert s.state is State.LISTENING, s.state


class TestADeadStreamNeverLooksLive(DeviceLossCase):
    """The defect this whole path exists to close, pinned before the fix.

    What used to happen, traced: the liveness check ran on a five-second heartbeat and
    did one thing, reopen. Pull the headset **mid-utterance** and `_pump_audio` drains an
    empty queue, so the gate never hears the quiet that would close it, `_finalise` is
    never reached, and `State.LISTENING` stands. That is the one state `ui.ACCENT` paints
    `HEARING` green, and green means "capturing speech" — so the pill sat there green,
    recording nothing, for as long as the session lasted. The audio already captured sat
    in `_utter` undecoded, and if the device did come back the next blocks were
    concatenated straight onto it, splicing one utterance across the missing seconds.
    """

    def test_listening_ends_on_the_frame_the_device_dies(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        self.speak(s, mic)
        mic.die()
        s.tick()
        self.assertIsNot(s.state, State.LISTENING,
                         "the pill is still painted green over a dead microphone")

    def test_no_state_the_pill_paints_green_survives_the_loss(self):
        # Asserted against the colour table rather than against one state name, so a
        # future state that is also green cannot slip through this.
        from flow.ui import ACCENT, HEARING

        mic = DyingMic(reopens=False)
        s = self.session(mic)
        self.speak(s, mic)
        mic.die()
        s.tick()
        self.assertNotEqual(ACCENT.get(s.state), HEARING)

    def test_the_loss_is_said_out_loud_with_a_reason(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die("PortAudio ended the stream")
        s.tick()
        note = notes_of(s.events())
        self.assertIn("microphone stopped", note)
        self.assertIn("PortAudio ended the stream", note)

    def test_the_retry_is_bounded_rather_than_forever(self):
        # The old check reopened on every heartbeat for the life of the session: a note
        # and an error every five seconds, indefinitely, over a pill still claiming to
        # be armed.
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(40):
                s.tick()
        self.assertEqual(mic.restarts, MIC_RETRIES)


class TestTheMicKnowsWhenItIsDead(unittest.TestCase):
    """`Mic.trouble`, over a fake sounddevice — the real object, no hardware.

    Every branch reads a signal PortAudio itself produces. None of them reads the audio,
    which is the point: silence is a working microphone in a quiet room.
    """

    def mic(self, sd=None, device=None):
        sd = sd or FakeSD()
        patch = mock.patch.object(audio, "sd", sd)
        patch.start()
        self.addCleanup(patch.stop)
        m = audio.Mic(device=device)
        self.addCleanup(m.stop)
        return m, sd

    def test_a_running_stream_reports_no_trouble(self):
        m, _sd = self.mic()
        m.start()
        self.assertEqual(m.trouble, "")
        self.assertTrue(m.active)

    def test_an_unopened_mic_is_not_pretending_otherwise(self):
        m, _sd = self.mic()
        self.assertEqual(m.trouble, "capture is not open")
        self.assertFalse(m.active)

    def test_a_callback_abort_is_detected(self):
        # sounddevice aborts the stream when a callback raises `CallbackAbort`, and a
        # host API does the same to a device that has been removed. Either way the
        # stream finishes with nobody here having asked.
        m, sd = self.mic()
        m.start()
        sd.streams[-1].abort()
        self.assertEqual(m.trouble, "PortAudio ended the stream")

    def test_a_stream_that_simply_stops_running_is_detected(self):
        m, sd = self.mic()
        m.start()
        # Inactive without the finished callback: the shape a host API leaves behind
        # when it marks a stream dead and tells nobody.
        sd.streams[-1].active = False
        self.assertEqual(m.trouble, "the stream stopped running")

    def test_an_accessor_that_raises_is_a_death_signal_too(self):
        m, sd = self.mic()
        m.start()
        sd.streams[-1].raise_on_active = OSError("device unplugged")
        self.assertIn("could not be read", m.trouble)
        self.assertIn("OSError", m.trouble)

    def test_delivery_going_quiet_is_death(self):
        # The backstop for a host API that reports a dead stream as active. Time is
        # rewound rather than waited out: `STALL_SEC` is two seconds and no unit test
        # should sleep for them.
        m, _sd = self.mic()
        m.start()
        m._last_block = time.monotonic() - STALL_SEC - 0.1
        self.assertIn("no blocks arrived", m.trouble)

    def test_actual_silence_is_not_death(self):
        """The line this whole detector is drawn on.

        A quiet room delivers blocks of near-zero samples at exactly the rate a loud one
        does. Feeding the callback nothing but digital silence must leave the stream as
        healthy as feeding it speech.
        """
        m, _sd = self.mic()
        m.start()
        m._last_block = time.monotonic() - STALL_SEC - 0.1
        m._callback(SILENT.reshape(-1, 1), BLOCK, None, None)
        self.assertEqual(m.trouble, "")

    def test_an_input_overflow_is_loss_and_not_death(self):
        # There is no status flag that means "the device is gone". What the flags do
        # report is audio the driver dropped before Flow was offered it, which is a loss
        # invariant 4 has to say out loud rather than a reason to tear the stream down.
        m, _sd = self.mic()
        m.start()
        m._callback(SILENT.reshape(-1, 1), BLOCK, None, Flags(input_overflow=True))
        self.assertEqual(m.trouble, "")
        self.assertEqual(m.overflows, 1)

    def test_our_own_stop_is_not_a_device_failure(self):
        # `finished_callback` fires from inside `stream.stop()`, so a deliberate stop
        # would otherwise file itself as a fault and the next arm would inherit it.
        m, _sd = self.mic()
        m.start()
        m.stop()
        m.start()
        self.assertEqual(m.trouble, "")


class TestReopeningFollowsTheMachineAsItIsNow(unittest.TestCase):
    """PortAudio takes its device list once and never looks again.

    Without a terminate/initialise round, "reopen against the current default" reopens
    against the default as it was at launch — which is guaranteed wrong in the one case
    that matters, because the reason for reopening is that the hardware changed.
    """

    def mic(self, sd, device=None):
        patch = mock.patch.object(audio, "sd", sd)
        patch.start()
        self.addCleanup(patch.stop)
        m = audio.Mic(device=device)
        self.addCleanup(m.stop)
        return m

    def test_the_device_list_really_is_stale_until_it_is_refreshed(self):
        sd = FakeSD(["Laptop Array", "USB Condenser"], default=0)
        m = self.mic(sd)
        m.start()
        sd.plug(["Laptop Array", "USB Condenser", "Headset"], default=2)
        self.assertEqual(m.device_name, "Laptop Array",
                         "the fake has to reproduce the staleness or it proves nothing")

    def test_an_unpinned_mic_reopens_onto_the_new_default(self):
        sd = FakeSD(["Laptop Array", "USB Condenser"], default=0)
        m = self.mic(sd)
        m.start()
        self.assertEqual(m.opened_name, "Laptop Array")
        sd.plug(["Laptop Array", "USB Condenser", "Headset"], default=2)
        m.restart()
        self.assertEqual(m.opened_name, "Headset")
        self.assertEqual(sd.terminated, 1, "PortAudio was never asked to look again")

    def test_a_pinned_index_is_re_read_from_the_fresh_list(self):
        # A pin is an index, and indexes are handed out in enumeration order: unplug
        # something below this one and the number names a different microphone.
        sd = FakeSD(["Laptop Array", "USB Condenser"], default=0)
        m = self.mic(sd, device=1)
        m.start()
        self.assertEqual(m.opened_name, "USB Condenser")
        sd.plug(["Laptop Array", "Webcam Mic"], default=0)
        m.restart()
        self.assertEqual(m.pinned, 1, "the pin must survive the reopen")
        self.assertEqual(m.opened_name, "Webcam Mic")

    def test_a_refresh_that_throws_is_not_the_reopen_failing(self):
        # Best-effort, like every other diagnosis on a recovery path: the reopen behind
        # it is simply working from the older list.
        sd = FakeSD(["Laptop Array"], default=0)
        sd._terminate = mock.Mock(side_effect=OSError("no host api"))
        m = self.mic(sd)
        m.start()
        m.restart()
        self.assertEqual(m.trouble, "")

    def test_arming_lets_portaudio_look_again_first(self):
        # Otherwise the re-arm the give-up path offers opens the default *as it was at
        # launch*, which is the one answer certain to be wrong when the reason for
        # re-arming is that the hardware changed.
        sd = FakeSD(["Laptop Array"], default=0)
        m = self.mic(sd)
        s = Session(asr=SayingAsr(), mic=m)
        self.addCleanup(s.close)
        s.start()
        self.assertEqual(sd.terminated, 1)

    def test_arming_does_not_terminate_portaudio_under_a_playing_reply(self):
        # `Pa_Terminate` closes every stream in the process, and a spoken reply is
        # playing through one (`flow/piper.py`, `flow/edge.py`).
        sd = FakeSD(["Laptop Array"], default=0)
        m = self.mic(sd)
        s = Session(asr=SayingAsr(), mic=m, speaker=mock.Mock(speaking=True))
        self.addCleanup(s.close)
        s.start()
        self.assertEqual(sd.terminated, 0)

    def test_a_fake_microphone_never_terminates_the_real_portaudio(self):
        # The `getattr` is what keeps 1 800 tests from tearing PortAudio down and
        # building it again: a fake has no `refresh`, so the arm skips it entirely.
        self.assertFalse(hasattr(DyingMic(), "refresh"))

    def test_a_session_sees_a_real_mic_die_through_the_fake_sounddevice(self):
        # End to end over the real `Mic`: the wiring from a PortAudio-level death to a
        # note on screen, with no stub in the middle to be wrong about it.
        sd = FakeSD(["Laptop Array"], default=0)
        m = self.mic(sd)
        s = Session(asr=SayingAsr(), mic=m)
        self.addCleanup(s.close)
        s.start()
        s.events()
        sd.streams[-1].abort()
        sd.fail_next = MIC_RETRIES
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        events = s.events()
        self.assertIn("PortAudio ended the stream", notes_of(events))
        self.assertIn("disarm", [e.kind for e in events])


class TestRecoveryWhenTheDeviceComesBack(DeviceLossCase):
    def test_a_successful_reopen_says_so_and_stays_armed(self):
        mic = DyingMic(name="USB Condenser")
        s = self.session(mic)
        mic.die()
        s.tick()
        events = s.events()
        self.assertEqual(mic.restarts, 1)
        self.assertIn("microphone stopped and reopened", notes_of(events))
        self.assertNotIn("disarm", [e.kind for e in events],
                         "a recovered device must not disarm the pill")
        self.assertTrue(s._mic_started)

    def test_the_note_names_the_device_that_answered(self):
        mic = DyingMic(name="USB Condenser", becomes="Headset (Poly BT700)")
        s = self.session(mic)
        mic.die()
        s.tick()
        self.assertIn("Headset (Poly BT700)", notes_of(s.events()))

    def test_the_first_attempt_is_made_in_the_frame_that_noticed(self):
        # The commonest real failure is the default moving rather than a device dying,
        # and the replacement is already there: an immediate attempt usually ends the
        # incident before the user has finished looking down at the pill.
        mic = DyingMic()
        s = self.session(mic)
        mic.die()
        s.tick()
        self.assertEqual(mic.restarts, 1)

    def test_a_blip_that_recovers_in_one_frame_is_one_complete_sentence(self):
        # The commonest real version of this: the default moved, the replacement was
        # already there, and the whole thing is over inside 30 ms. Announcing the loss
        # first would put two notes on a surface that shows one at a time, the second
        # overwriting the first — and the first is the one carrying the cut.
        mic = DyingMic(name="Laptop Array", becomes="Headset")
        s = self.session(mic)
        self.speak(s, mic)
        mic.die()
        s.tick()
        said = [e.text for e in s.events() if e.kind in ("note", "error")]
        self.assertEqual(len(said), 1, said)
        self.assertIn("microphone stopped and reopened", said[0])
        self.assertIn("already captured is being decoded", said[0])

    def test_a_second_incident_is_reported_as_a_second_incident(self):
        mic = DyingMic()
        s = self.session(mic)
        mic.die()
        s.tick()
        first = notes_of(s.events())
        mic.die()
        s.tick()
        self.assertIn("microphone stopped and reopened", first)
        self.assertIn("microphone stopped and reopened", notes_of(s.events()))

    def test_every_incident_says_at_least_one_thing(self):
        # The loss note is deferred, so the shape to guard against is an incident that
        # resolves quietly and explains nothing.
        for reopens in (True, False):
            with self.subTest(reopens=reopens):
                mic = DyingMic(reopens=reopens)
                s = self.session(mic)
                mic.die()
                with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
                    for _ in range(MIC_RETRIES + 2):
                        s.tick()
                self.assertTrue(notes_of(s.events()))

    def test_a_pinned_index_that_became_a_different_microphone_is_named(self):
        mic = DyingMic(pinned=3, name="USB Condenser", becomes="Webcam Mic")
        s = self.session(mic)
        mic.die()
        s.tick()
        note = notes_of(s.events())
        self.assertIn("--device 3", note)
        self.assertIn("Webcam Mic", note)
        self.assertIn("USB Condenser", note)

    def test_an_unpinned_swap_is_not_reported_as_a_substitution(self):
        # Following the default *is* the feature when nobody pinned anything: plug in a
        # headset and Flow moves to it. Only the recovery line is owed.
        mic = DyingMic(name="Laptop Array", becomes="Headset")
        s = self.session(mic)
        mic.die()
        s.tick()
        self.assertNotIn("--device", notes_of(s.events()))


class TestGivingUpHonestly(DeviceLossCase):
    def _exhaust(self, mic, s):
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        return s.events()

    def test_the_retries_are_spaced_rather_than_spun(self):
        # 200 frames is six seconds of UI at 30 ms, and must not be 200 attempts at a
        # device that is not there.
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        for _ in range(200):
            s.tick()
        self.assertEqual(mic.restarts, 1)

    def test_it_ends_disarmed_the_way_a_failed_startup_does(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        events = self._exhaust(mic, s)
        self.assertEqual(mic.restarts, MIC_RETRIES)
        self.assertIn("disarm", [e.kind for e in events])
        self.assertFalse(s._mic_started)
        self.assertIs(s.state, State.IDLE)

    def test_the_device_is_actually_closed_on_the_way_out(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        self._exhaust(mic, s)
        self.assertGreaterEqual(mic.stops, 1)

    def test_a_close_that_throws_does_not_take_the_give_up_with_it(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.stop = mock.Mock(side_effect=OSError("already gone"))
        mic.die()
        events = self._exhaust(mic, s)
        self.assertIn("disarm", [e.kind for e in events])

    def test_a_pinned_device_is_named_and_never_substituted(self):
        mic = DyingMic(pinned=3, reopens=False, raises=OSError("Invalid device"))
        s = self.session(mic)
        mic.die()
        note = notes_of(self._exhaust(mic, s))
        self.assertIn("--device 3", note)
        self.assertIn("does not move to another microphone", note)
        self.assertIn("relaunch without --device", note)

    def test_an_unpinned_failure_offers_the_pill(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        note = notes_of(self._exhaust(mic, s))
        self.assertIn("could not reopen the microphone", note)
        self.assertIn("click the pill", note)

    def test_the_reason_carries_the_exception_that_was_raised(self):
        mic = DyingMic(reopens=False, raises=OSError("Invalid device [PaErrorCode -9996]"))
        s = self.session(mic)
        mic.die()
        self.assertIn("PaErrorCode -9996", notes_of(self._exhaust(mic, s)))

    def test_a_held_draft_is_told_what_still_works(self):
        # Invariant 4's second half: every spoken rescue needs a decode, a decode needs
        # audio, and there is none. The send hotkey still works and had been named once,
        # at startup, in a console nobody is looking at.
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        s.draft.set("a paragraph nobody wants to lose")
        mic.die()
        self.assertIn("voice is down", notes_of(self._exhaust(mic, s)))

    def test_re_arming_after_a_failure_tries_the_device_again(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        self._exhaust(mic, s)
        opened = mic.starts
        mic.reopens = True  # the headset is plugged back in
        s.start()
        self.assertEqual(mic.starts, opened + 1)
        self.assertTrue(s._mic_started)

    def test_re_arming_restores_the_whole_retry_budget(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        self._exhaust(mic, s)
        s.start()
        s.events()
        mic.die()
        events = self._exhaust(mic, s)
        self.assertIn("microphone stopped", notes_of(events),
                      "a second incident must be announced afresh")
        self.assertEqual(mic.restarts, MIC_RETRIES * 2)


class TestTheUtteranceInFlightWhenTheDeviceDied(DeviceLossCase):
    """Decoded, not discarded — and the note says the words were cut.

    The alternative was a note reading "N seconds of what you just said is gone", which
    is both a worse sentence to have to write and an unrecoverable one to read. Whisper
    handles a truncated utterance; that bargain is already struck at `MAX_UTTERANCE_SEC`,
    where the 24 s cut lands on an audio block rather than on a word.
    """

    def test_the_captured_audio_reaches_the_decoder(self):
        mic = DyingMic(reopens=False)
        asr = SayingAsr("half a sentence")
        s = self.session(mic, asr=asr)
        self.speak(s, mic)
        mic.die()
        s.tick()
        s.wait_idle(timeout=5.0)
        self.assertEqual(asr.finals, 1)
        self.assertEqual(s.draft.text, "half a sentence")

    def test_the_note_says_how_much_was_cut(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        self.speak(s, mic, blocks=16)
        mic.die()
        s.tick()
        self.assertIn("already captured is being decoded", notes_of(s.events()))

    def test_nothing_extra_is_claimed_when_nobody_was_talking(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.die()
        s.tick()
        self.assertNotIn("already captured", notes_of(s.events()))

    def test_the_next_device_does_not_continue_the_old_utterance(self):
        # The splice the old code produced: audio from either side of the dead seconds
        # concatenated into one utterance, with the gap silently removed.
        mic = DyingMic()
        s = self.session(mic)
        self.speak(s, mic)
        mic.die()
        s.tick()
        self.assertFalse(s.gate.speaking)
        self.assertEqual(s._utter, [])

    def test_the_words_survive_the_disarm(self):
        # `pause()` would have been the tidy way to stop capturing and would have thrown
        # these away: it bumps the capture generation, and the decode of the cut-off
        # words is in flight at exactly that moment.
        mic = DyingMic(reopens=False)
        asr = SayingAsr("the last thing I said")
        s = self.session(mic, asr=asr)
        self.speak(s, mic)
        mic.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "the last thing I said")


class TestDeafnessAndDeathAreDifferentThings(DeviceLossCase):
    """The two deliberate deafnesses must not hide a device that actually went.

    While the hand editor is open and while a reply is being read aloud, `_pump_audio`
    drains the device and throws every block away. Neither is a fault, both say so — and
    neither may be allowed to swallow one.
    """

    def test_a_device_dying_behind_the_editor_still_ends_disarmed(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        s.draft.set("something being typed")
        s.begin_edit()
        s.events()
        mic.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        events = s.events()
        self.assertIn("disarm", [e.kind for e in events])
        self.assertTrue(s.editing, "the editor is the user's, not the device's")
        self.assertEqual(s.draft.text, "something being typed")

    def test_the_editor_still_commits_afterwards(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        s.draft.set("before")
        s.begin_edit()
        mic.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        s.commit_edit("after")
        self.assertEqual(s.draft.text, "after")
        self.assertFalse(s.editing)

    def test_a_device_dying_mid_reply_does_not_cut_the_reply_off(self):
        # Disarming is one of the ways to say "enough" to a reply, which is why
        # `pause()` stops the speaker. Losing the microphone is not that: the answer has
        # nothing to do with whether Flow can still hear.
        speaker = mock.Mock(speaking=True)
        mic = DyingMic(reopens=False)
        s = self.session(mic, speaker=speaker)
        mic.die()
        s.tick()
        speaker.stop.assert_not_called()
        self.assertIsNot(s.state, State.LISTENING, "the pill is still green")

    def test_recovery_is_held_while_flow_is_talking(self):
        """Not spent, and not skipped: the attempts wait for the reply to finish.

        Two reasons that agree. Reopening mid-reply feeds a device straight into the
        half-duplex guard, which discards every block — and reopening has to terminate
        PortAudio to see the machine again, which closes *every* stream in the process,
        including the `RawOutputStream` `flow/piper.py` is playing the reply through.
        """
        speaker = mock.Mock(speaking=True)
        mic = DyingMic(reopens=False)
        s = self.session(mic, speaker=speaker)
        mic.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        self.assertEqual(mic.restarts, 0, "PortAudio was terminated under the reply")
        self.assertNotIn("disarm", [e.kind for e in s.events()])

        speaker.speaking = False  # the answer finished
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        self.assertEqual(mic.restarts, MIC_RETRIES)
        self.assertIn("disarm", [e.kind for e in s.events()])

    def test_the_incident_opens_even_though_the_retries_wait(self):
        # Held retries must not mean a held *diagnosis*: the pill reads `NO INPUT` off
        # `mic.active` from the first frame, whether or not anything can be done yet.
        speaker = mock.Mock(speaking=True)
        mic = DyingMic(reopens=False)
        s = self.session(mic, speaker=speaker)
        mic.die()
        s.tick()
        self.assertTrue(s._mic_trouble, "the incident was not even opened")
        self.assertFalse(s.mic.active)

    def test_the_level_meter_stops_claiming_to_hear_anybody(self):
        # `Mic._level` is whatever the last block that ever arrived measured, so a
        # stream that stops mid-word leaves the meter frozen at that word's loudness —
        # bars dancing to prove Flow is listening for the whole two seconds a recovery
        # takes. The same lie the speaking guard already floors.
        mic = DyingMic(reopens=False)
        s = self.session(mic)
        mic.level_db = -14.0  # mid-word, near the top of the meter
        self.assertEqual(s.level_db, -14.0)
        mic.die()
        s.tick()
        self.assertEqual(s.level_db, session_mod.DEAF_DB)

    def test_the_meter_comes_back_with_the_device(self):
        mic = DyingMic()
        s = self.session(mic)
        mic.level_db = -30.0
        mic.die()
        s.tick()
        self.assertEqual(s.level_db, -30.0, "a recovered device is evidence again")

    def test_a_paused_session_is_left_alone(self):
        # `pause()` is how somebody says "stop capturing". A health check that helpfully
        # reopened it would be arguing with them.
        mic = DyingMic()
        s = self.session(mic)
        s.pause()
        mic.die()
        for _ in range(10):
            s.tick()
        self.assertEqual(mic.restarts, 0)


class TestTheDeviceNotesArePrintable(DeviceLossCase):
    """Every line this path emits, through `str.encode`.

    A note is also a thing that gets printed, and a redirected stdout on a legacy
    console code page cannot encode what it cannot encode — the constraint
    `__main__.say` documents. Device names are the live hazard here: they come off the
    machine's own hardware, in the machine's own language, and go straight into a note,
    which is why `session.plain` exists and why the fakes below are named in Polish and
    Spanish with a registered-trademark sign in the middle.

    **One line in these sequences is exempt, and it is measured rather than waved past.**
    `help.exits_note` carries an em dash, predates this rule, and lives in a module this
    change does not touch; `test_it_is_the_only_line_that_predates_the_rule` pins that it
    is the only one, so the gap cannot quietly grow.
    """

    #: `_say_exits` emits `help.exits_note` verbatim. Matched on its opening words.
    PREDATES = "voice is down"

    def _all_lines(self) -> list[str]:
        lines: list[str] = []

        # 1. Loss, recovery, and a pinned index that became something else — with a
        #    device name no ASCII terminal can print.
        mic = DyingMic(pinned=2, name="Mikrofon (Realtek® Audio)",
                       becomes="Micróphone — USB")
        s = self.session(mic)
        self.speak(s, mic)
        mic.die("the stream could not be read (PortAudioError)")
        s.tick()
        lines += self._events(s)

        # 2. Giving up, pinned, with a driver's own exception text in the reason.
        gone = DyingMic(pinned=2, reopens=False,
                        raises=OSError("Invalid device — [PaErrorCode -9996]"))
        s2 = self.session(gone)
        s2.draft.set("a held draft, so the exits are named too")
        gone.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s2.tick()
        lines += self._events(s2)

        # 3. Giving up unpinned.
        auto = DyingMic(reopens=False)
        s3 = self.session(auto)
        auto.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s3.tick()
        lines += self._events(s3)

        # 4. The driver's own overflow report.
        blown = DyingMic()
        s4 = self.session(blown)
        blown.overflows = 3
        s4.tick()
        lines += self._events(s4)
        return [line for line in lines if line]

    def _events(self, s) -> list[str]:
        return [e.text for e in s.events() if e.kind in ("note", "error")]

    def _mine(self) -> list[str]:
        return [line for line in self._all_lines() if self.PREDATES not in line]

    def test_every_line_is_ascii(self):
        for line in self._mine():
            with self.subTest(line=line):
                line.encode("ascii")

    def test_every_line_survives_a_cp437_console(self):
        for line in self._mine():
            with self.subTest(line=line):
                line.encode("cp437")

    def test_it_is_the_only_line_that_predates_the_rule(self):
        # The exemption is a measurement, not a licence: anything else that turns up
        # unprintable here is this change's own and has to be fixed rather than listed.
        stubborn = []
        for line in self._all_lines():
            try:
                line.encode("cp437")
            except UnicodeEncodeError:
                stubborn.append(line)
        self.assertTrue(all(self.PREDATES in line for line in stubborn), stubborn)

    def test_the_lines_really_were_produced(self):
        # A guard on the guard: an encoding test over an empty list passes loudly.
        lines = self._mine()
        self.assertGreaterEqual(len(lines), 6)
        self.assertTrue(any("microphone stopped" in line for line in lines))
        self.assertTrue(any("stopped listening" in line for line in lines))
        self.assertTrue(any("Realtek? Audio" in line for line in lines),
                        "a device name with a non-ASCII character was not made printable")


class TestTheDriverDroppingAudioIsSaidOutLoud(DeviceLossCase):
    """`Mic.dropped` is Flow's queue; `Mic.overflows` is the driver, upstream of it.

    The second one was counted nowhere and read by nobody, which left invariant 4 with a
    hole on the far side of the API: audio the hardware threw away before Flow was ever
    offered it.
    """

    def test_growth_is_reported(self):
        mic = DyingMic()
        s = self.session(mic)
        mic.overflows = 2
        s.tick()
        self.assertIn("dropped 2 buffers", notes_of(s.events()))

    def test_one_buffer_is_not_pluralised(self):
        mic = DyingMic()
        s = self.session(mic)
        mic.overflows = 1
        s.tick()
        self.assertIn("dropped 1 buffer -", notes_of(s.events()))

    def test_a_steady_counter_says_nothing(self):
        mic = DyingMic()
        s = self.session(mic)
        mic.overflows = 2
        s.tick()
        s.events()
        for _ in range(5):
            s.tick()
        self.assertEqual(notes_of(s.events()), "")

    def test_no_duration_is_invented(self):
        # The flag says a buffer was lost, not how long it was. A number derived from
        # the block size would be a figure with nothing behind it.
        mic = DyingMic()
        s = self.session(mic)
        mic.overflows = 2
        s.tick()
        note = notes_of(s.events())
        self.assertNotIn(" ms", note)
        self.assertNotIn(" s of", note)

    def test_a_mic_that_cannot_count_them_is_not_a_crash(self):
        # Every fake that predates the counter, which is most of the suite.
        class Old:
            level_db = -70.0
            active = True

            def start(self): ...
            def stop(self): ...
            def drain(self): return []
            def restart(self): ...

        s = self.session(Old())
        s.tick()
        self.assertEqual(notes_of(s.events()), "")


class TestTheDisarmEventTakesThePillOff(unittest.TestCase):
    """The one thing the session cannot do for itself.

    `armed` belongs to the UI thread. A session that has stopped capturing and cannot
    start itself again has to ask, or the pill goes on claiming to listen with no
    microphone under it — the exact lie `_toggle` already refuses to tell when capture
    fails at startup.
    """

    def _pill(self, events):
        import flow.ui as ui

        p = ui.Pill.__new__(ui.Pill)
        p.armed = True
        p._disarmed_since = None
        p._flash = 0
        p._asked = False
        p._last_draft = ""
        p.lite = False
        p.bubble = mock.Mock()
        p.card = mock.Mock()
        p.session = mock.Mock(mode=DICTATE, state=State.IDLE)
        p.session.events.return_value = events
        return p

    def test_a_disarm_event_drops_the_armed_flag(self):
        p = self._pill([Event("disarm", "microphone")])
        p._pump_events()
        self.assertFalse(p.armed)
        self.assertIsNotNone(p._disarmed_since, "the 8 s idle dim never started")

    def test_the_error_beside_it_flashes_and_is_shown(self):
        p = self._pill([Event("error", "could not reopen the microphone"),
                        Event("disarm", "microphone")])
        p._pump_events()
        self.assertGreater(p._flash, 0)
        p.bubble.note.assert_called_once_with("could not reopen the microphone")
        self.assertFalse(p.armed)

    def test_nothing_else_disarms_the_pill(self):
        p = self._pill([Event("note", "microphone back - listening again")])
        p._pump_events()
        self.assertTrue(p.armed)


class TestLiteIsUnharmed(DeviceLossCase):
    """Lite is the same brain: `lite` is read in exactly one place, the send note.

    Recovery must therefore behave identically, and this is the check that it has not
    quietly grown a Windows-shaped dependency.
    """

    def test_a_lite_session_recovers_the_same_way(self):
        mic = DyingMic(name="Built-in Microphone")
        s = self.session(mic, lite=True)
        mic.die()
        s.tick()
        events = s.events()
        self.assertIn("microphone stopped and reopened", notes_of(events))
        self.assertNotIn("disarm", [e.kind for e in events])

    def test_a_lite_session_gives_up_the_same_way(self):
        mic = DyingMic(reopens=False)
        s = self.session(mic, lite=True)
        mic.die()
        with mock.patch.object(session_mod, "MIC_RETRY_SEC", 0.0):
            for _ in range(MIC_RETRIES + 2):
                s.tick()
        self.assertIn("disarm", [e.kind for e in s.events()])
        self.assertFalse(s._mic_started)


if __name__ == "__main__":
    unittest.main()
