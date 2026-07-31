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
        mic = StubMic(active=False)
        s = Session(asr=TrackingAsr(), mic=mic)
        s.start()
        with mock.patch.object(session_mod, "MIC_CHECK_SEC", 0.0):
            s.tick()
        self.assertEqual(mic.restarts, 1)
        self.assertTrue(any("device went away" in e.text for e in s.events()))
        s.close()

    def test_paused_mic_is_not_reopened(self):
        """A deliberate pause must not be helpfully undone by the health check."""
        mic = StubMic(active=True)
        s = Session(asr=TrackingAsr(), mic=mic)
        s.start()
        s.pause()
        mic._active = False
        with mock.patch.object(session_mod, "MIC_CHECK_SEC", 0.0):
            s.tick()
        self.assertEqual(mic.restarts, 0)
        s.close()


if __name__ == "__main__":
    unittest.main()
