"""Tests for the long-session upkeep added in stage 9 (R8).

These cover the parts of "handle long running" that are logic rather than endurance:
bounded undo history, dropping the model when idle, and noticing a dead input device.
The endurance question — does memory actually stay flat over ten minutes — is
scripts/soak.py, because no unit test can answer it.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import session as session_mod  # noqa: E402
from flow.session import Draft, Session  # noqa: E402


class TrackingAsr:
    def __init__(self) -> None:
        self.loaded = False
        self.unloads = 0

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False
        self.unloads += 1

    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        return ""


class StubMic:
    def __init__(self, active: bool = True) -> None:
        self._active = active
        self.restarts = 0
        self.level_db = -60.0

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def drain(self) -> list[np.ndarray]:
        return []

    @property
    def active(self) -> bool:
        return self._active

    def restart(self) -> None:
        self.restarts += 1
        self._active = True


class TestDraftHistory(unittest.TestCase):
    def test_history_is_bounded_by_count(self):
        d = Draft()
        for i in range(100):
            d.set(f"draft {i}")
        self.assertLessEqual(len(d._history), Draft.MAX_HISTORY)

    def test_history_is_bounded_by_total_characters(self):
        """30 snapshots of a huge draft is where undo quietly becomes megabytes."""
        d = Draft()
        chunk = "x" * 50_000
        for i in range(20):
            d.set(chunk + str(i))
        total = sum(len(h) for h in d._history)
        self.assertLessEqual(total, Draft.MAX_HISTORY_CHARS + len(chunk))
        self.assertGreaterEqual(len(d._history), 1, "undo must not be emptied entirely")

    def test_undo_still_works_after_trimming(self):
        d = Draft()
        d.set("first")
        d.set("second")
        self.assertTrue(d.undo())
        self.assertEqual(d.text, "first")


class TestIdleUnload(unittest.TestCase):
    def test_model_is_dropped_after_idle(self):
        asr = TrackingAsr()
        s = Session(asr=asr, mic=StubMic())
        s.start()
        self.assertTrue(asr.loaded)
        with mock.patch.object(session_mod, "IDLE_UNLOAD_SEC", 0.0):
            s.tick()
        self.assertFalse(asr.loaded)
        self.assertEqual(asr.unloads, 1)
        s.close()

    def test_a_warm_holds_the_models_against_an_idle_that_is_already_due(self):
        # The race the grace window exists for. `_last_activity` is moved by Flow's own
        # milestones, so somebody who has just reached for the chord is still idle by
        # that measure — and the health pump runs every tick, so without this it is free
        # to unload between the press-down and the release that arms.
        asr = TrackingAsr()
        s = Session(asr=asr, mic=StubMic())
        s.start()
        s.warm()
        with mock.patch.object(session_mod, "IDLE_UNLOAD_SEC", 0.0):
            s.tick()
        self.assertTrue(asr.loaded)
        self.assertEqual(asr.unloads, 0)
        s.close()

    def test_and_lets_go_once_the_grace_is_spent(self):
        # A window, not a veto. `ctrl+win` is also Windows' desktop-switch prefix, so a
        # warm that reset the idle clock outright would mean anybody who switches
        # desktops through the day never unloads at all — the setting would quietly stop
        # existing for exactly the people using their machine most.
        asr = TrackingAsr()
        s = Session(asr=asr, mic=StubMic())
        s.start()
        s.warm()
        with mock.patch.object(session_mod, "IDLE_UNLOAD_SEC", 0.0), \
                mock.patch.object(session_mod, "WARM_GRACE_SEC", 0.0):
            s.warm()
            s.tick()
        self.assertFalse(asr.loaded)
        self.assertEqual(asr.unloads, 1)
        s.close()

    def test_a_session_nobody_warmed_is_not_holding_anything_off(self):
        # Zero is the state every session starts in and mostly stays in, so the guard
        # must not be what decides the ordinary case.
        s = Session(asr=TrackingAsr(), mic=StubMic())
        self.assertEqual(s._warm_until, 0.0)
        s.close()

    def test_the_idle_threshold_is_the_gaps_in_a_day_and_not_five_minutes(self):
        # Stated as a number because it is a judgement and not an accident: five minutes
        # was inside the gaps of an ordinary working session, so the common case was not
        # reclaiming memory from somebody who left, it was paying a reload in the middle
        # of their first sentence back.
        self.assertEqual(session_mod.IDLE_UNLOAD_SEC, 1800.0)

    def test_model_is_kept_while_a_draft_is_held(self):
        # Unloading mid-draft would make the next correction pay a reload for nothing.
        asr = TrackingAsr()
        s = Session(asr=asr, mic=StubMic())
        s.start()
        s.draft.set("something the user is still working on")
        with mock.patch.object(session_mod, "IDLE_UNLOAD_SEC", 0.0):
            s.tick()
        self.assertTrue(asr.loaded)
        self.assertEqual(asr.unloads, 0)
        s.close()


class TestDeviceLoss(unittest.TestCase):
    def test_dead_device_is_reopened(self):
        """And on the frame it dies, not on the next five-second heartbeat.

        The patch this used to need (`MIC_CHECK_SEC` down to zero) is gone with the
        constant: `Pa_IsStreamActive` costs 0.43 us, so the check runs every tick and
        the first reopen happens in the frame that noticed.
        """
        mic = StubMic(active=False)
        s = Session(asr=TrackingAsr(), mic=mic)
        s.start()
        s.tick()
        self.assertEqual(mic.restarts, 1)
        self.assertTrue(any("microphone stopped" in e.text for e in s.events()))
        s.close()

    def test_paused_mic_is_not_reopened(self):
        """A deliberate pause must not be helpfully undone by the health check."""
        mic = StubMic(active=True)
        s = Session(asr=TrackingAsr(), mic=mic)
        s.start()
        s.pause()
        mic._active = False
        s.tick()
        self.assertEqual(mic.restarts, 0)
        s.close()


class CountingMic(StubMic):
    """A mic that can report having thrown blocks away, the way the real one does."""

    def __init__(self, active: bool = True) -> None:
        super().__init__(active)
        self.dropped = 0


class TestOverflowIsSurfaced(unittest.TestCase):
    """The queue drops the oldest block when it is full, and only counted it.

    That counter was read by nothing in the app, so the one case invariant 4 could not
    cover was the microphone: audio the user spoke went in the bin with no event, no
    note and no number. It takes a ~16 s stall of the reader to reach — the queue holds
    256 blocks — and the right-click menu's modal `TrackPopupMenu` loop is the one known
    way to produce it, which is precisely the case where the user is not watching the
    pill and cannot tell that anything went.
    """

    def _session(self):
        mic = CountingMic()
        s = Session(asr=TrackingAsr(), mic=mic)
        s.start()
        s.events()
        return s, mic

    def _notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_blocks_that_went_missing_are_reported(self):
        s, mic = self._session()
        mic.dropped = 5
        s.tick()
        self.assertIn("overflow", self._notes(s))
        s.close()

    def test_the_note_says_how_much_audio_that_was(self):
        # 5 blocks x 64 ms. A count of blocks means nothing to the person who spoke them.
        s, mic = self._session()
        mic.dropped = 5
        s.tick()
        self.assertIn("320 ms", self._notes(s))
        s.close()

    def test_a_long_stall_is_reported_in_seconds(self):
        # A full queue is 256 blocks, which is the shape this actually arrives in.
        s, mic = self._session()
        mic.dropped = 256
        s.tick()
        self.assertIn("16.4 s", self._notes(s))
        s.close()

    def test_a_steady_counter_says_nothing(self):
        s, mic = self._session()
        mic.dropped = 5
        s.tick()
        s.events()
        for _ in range(10):
            s.tick()
        self.assertEqual(self._notes(s), "", "it repeated itself with nothing to say")
        s.close()

    def test_a_second_overflow_is_reported_again(self):
        s, mic = self._session()
        mic.dropped = 5
        s.tick()
        s.events()
        mic.dropped = 9
        s.tick()
        self.assertIn("256 ms", self._notes(s), "only the new loss should be reported")
        s.close()

    def test_the_session_keeps_a_running_total(self):
        # For the diagnostics trace: one number for the whole session, not per event.
        s, mic = self._session()
        mic.dropped = 5
        s.tick()
        mic.dropped = 9
        s.tick()
        self.assertEqual(s.mic_dropped, 9)
        s.close()

    def test_a_counter_that_starts_over_is_not_a_loss(self):
        # A replaced device brings a fresh counter with it. Going backwards is not
        # audio arriving; it is a different mic.
        s, mic = self._session()
        mic.dropped = 40
        s.tick()
        s.events()
        mic.dropped = 0
        s.tick()
        self.assertEqual(self._notes(s), "")
        self.assertEqual(s.mic_dropped, 40)
        s.close()

    def test_a_mic_that_cannot_count_is_not_a_crash(self):
        # Every fake in the suite predates the counter, and Mic is injectable on purpose.
        s = Session(asr=TrackingAsr(), mic=StubMic())
        s.start()
        s.tick()
        self.assertEqual(s.mic_dropped, 0)
        s.close()


class FakeHotkeys:
    """What registered this launch, which is the only thing worth naming to a user."""

    def __init__(self, chosen: dict | None = None) -> None:
        self.chosen = chosen if chosen is not None else {"send": "ctrl+alt+enter"}
        self.failed: list[str] = []


class TestWhenVoiceGoesDownFlowSaysWhatStillWorks(unittest.TestCase):
    """The half of the long-draft incident that had nothing to do with rendering.

    Once the stall had overflowed the microphone, every *spoken* rescue was impossible:
    "boom" needs a decode, a decode needs the models, and the models needed the mic the
    render had killed. The one thing that still worked — the send hotkey — had been
    announced once, at startup, in a console the user was not looking at. So the moment
    Flow stops being able to hear is the moment it has to say what is left.
    """

    def _session(self, hotkeys=None):
        mic = CountingMic()
        s = Session(asr=TrackingAsr(), mic=mic)
        s.hotkeys = hotkeys if hotkeys is not None else FakeHotkeys()
        s.start()
        s.events()
        return s, mic

    def _notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_an_overflow_with_a_draft_names_the_exits(self):
        s, mic = self._session()
        s.draft.set("a long dictation nobody wants to lose")
        mic.dropped = 256
        s.tick()
        notes = self._notes(s)
        self.assertIn("voice is down", notes)
        # Beside the loss, not instead of it: invariant 4 owns "how much audio went",
        # and this answers a different question.
        self.assertIn("16.4 s", notes)
        s.close()

    def test_an_overflow_with_no_draft_says_nothing_extra(self):
        # Nothing to rescue. A warning about a draft that does not exist is the noise
        # that teaches people to ignore the real one.
        s, mic = self._session()
        mic.dropped = 256
        s.tick()
        notes = self._notes(s)
        self.assertIn("overflow", notes)
        self.assertNotIn("voice is down", notes)
        s.close()

    def test_it_is_said_once_and_not_on_every_tick(self):
        s, mic = self._session()
        s.draft.set("still here")
        mic.dropped = 5
        s.tick()
        s.events()
        mic.dropped = 40
        for _ in range(5):
            s.tick()
        self.assertNotIn("voice is down", self._notes(s))
        s.close()

    def test_the_next_draft_gets_its_own_warning(self):
        # The latch clears when there is nothing left to rescue, so a second incident in
        # the same session is a second incident rather than a silence.
        s, mic = self._session()
        s.draft.set("first")
        mic.dropped = 5
        s.tick()
        s.events()
        s.draft.set("")
        s.tick()
        s.draft.set("second")
        mic.dropped = 40
        s.tick()
        self.assertIn("voice is down", self._notes(s))
        s.close()

    def test_models_gone_under_a_held_draft_is_the_same_announcement(self):
        """The other way voice dies, and it is a *state* rather than a call site.

        `_pump_health` refuses to unload while a draft is held, so the idle path cannot
        produce this today — which is exactly why the check reads the condition instead
        of hanging off that branch. Whatever takes the models away, a draft with nothing
        left to decode it is the thing the user has to be told about.
        """
        s, _mic = self._session()
        s.draft.set("something worth keeping")
        s.asr.unload()
        s.tick()
        self.assertIn("voice is down", self._notes(s))
        s.close()

    def test_the_note_carries_the_combo_that_actually_registered(self):
        # The defect item 30 exists to prevent, one layer along: `ctrl+alt+enter` is the
        # *first alternative* in DEFAULT_BINDINGS, not necessarily what the OS accepted.
        s, mic = self._session(FakeHotkeys({"send": "ctrl+shift+enter"}))
        s.draft.set("a draft")
        mic.dropped = 5
        s.tick()
        notes = self._notes(s)
        self.assertIn("ctrl+shift+enter", notes)
        self.assertNotIn("ctrl+alt+enter", notes)
        s.close()

    def test_no_hotkeys_still_names_something_to_press(self):
        # Lite, and `--no-hotkeys`. A sentence with the useful half missing is worse
        # than no sentence: it reads as the app having nothing to offer.
        s, mic = self._session(FakeHotkeys({}))
        s.draft.set("a draft")
        mic.dropped = 5
        s.tick()
        notes = self._notes(s)
        self.assertIn("voice is down", notes)
        self.assertIn("Send chip", notes)
        s.close()

    def test_a_session_nobody_wired_hotkeys_into_does_not_crash(self):
        # Every fake in the suite predates the attribute; `Session` is built before the
        # hotkeys exist, which is why `main()` assigns it afterwards.
        mic = CountingMic()
        s = Session(asr=TrackingAsr(), mic=mic)
        s.start()
        s.events()
        s.draft.set("a draft")
        mic.dropped = 5
        s.tick()
        self.assertIn("voice is down", self._notes(s))
        s.close()


if __name__ == "__main__":
    unittest.main()
