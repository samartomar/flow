"""The latency work of 2026-09-01, pinned.

Each of these is one measured gap from the performance audit and the mechanism that
closed it: a final no longer waits behind a partial it has made stale, a spoken send
trigger the partial decoder heard fires on the silence after it rather than after a
second decode, the trace writes from its own thread, and the gate can say how long the
speaker has been quiet. The push-to-talk half — the stream that lingers between holds —
is in `tests/test_talk.py`, beside the gesture it belongs to.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import SpeechGate  # noqa: E402
from flow.diag import Diag  # noqa: E402
from flow.session import (  # noqa: E402
    BLOCK, TRIGGER_MAX_SEC, TRIGGER_QUIET_BLOCKS, DecodeWorker, Session,
)

LOUD = np.full(BLOCK, 0.3, dtype=np.float32)
QUIET = np.zeros(BLOCK, dtype=np.float32)


class FakeMic:
    def __init__(self) -> None:
        self.active = False
        self.dropped = 0
        self.device_name = "fake"
        self._blocks: list[np.ndarray] = []

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def drain(self) -> list:
        out, self._blocks = self._blocks, []
        return out

    def alive(self) -> bool:
        return self.active


class SlowPartialAsr:
    """A partial that takes a moment, and records whether it was offered a cancel."""

    cancellable = True
    loaded = True
    loading = False

    def __init__(self) -> None:
        self.calls: list[tuple[bool, bool]] = []  # (final, offered cancel)
        self.saw_cancel = threading.Event()

    def load(self, final=None) -> None: ...

    def unload(self) -> None: ...

    def text(self, audio, *, final=False, hotwords="", cancelled=None) -> str:
        self.calls.append((final, cancelled is not None))
        if not final:
            deadline = time.perf_counter() + 0.5
            while time.perf_counter() < deadline:
                if cancelled is not None and cancelled():
                    self.saw_cancel.set()
                    return ""
                time.sleep(0.005)
            return "partial text"
        return "final text"


class TestAFinalMakesTheRunningPartialStale(unittest.TestCase):
    def test_the_partial_is_told_to_stop_and_its_result_is_not_shown(self):
        asr = SlowPartialAsr()
        w = DecodeWorker(asr)
        self.addCleanup(w.close)
        w.submit_partial(LOUD)
        time.sleep(0.05)  # the partial is inside `text()` now
        w.submit_final(LOUD)
        deadline = time.perf_counter() + 3.0
        while w.busy and time.perf_counter() < deadline:
            time.sleep(0.01)
        self.assertTrue(asr.saw_cancel.is_set(), "the running partial was never asked")
        kinds = [kind for kind, *_ in w.results()]
        self.assertEqual(kinds, ["final"], "a stale partial reached the results")
        self.assertEqual([c for c in asr.calls], [(False, True), (True, False)])

    def test_a_partial_nobody_overtook_arrives_as_before(self):
        asr = SlowPartialAsr()
        w = DecodeWorker(asr)
        self.addCleanup(w.close)
        w.submit_partial(LOUD)
        deadline = time.perf_counter() + 3.0
        while w.busy and time.perf_counter() < deadline:
            time.sleep(0.01)
        self.assertEqual([(k, t) for k, t, *_ in w.results()], [("partial", "partial text")])


class TriggerAsr:
    """Hears the send word early: every partial is "boom"."""

    loaded = True
    loading = False

    def __init__(self, partial: str = "boom") -> None:
        self.partial = partial
        self.finals = 0

    def load(self, final=None) -> None: ...

    def unload(self) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        if final:
            self.finals += 1
            return "the final said something else"
        return self.partial


class TestTheSendWordFiresOnTheSilenceAfterIt(unittest.TestCase):
    def setUp(self) -> None:
        self.mic = FakeMic()
        self.asr = TriggerAsr()
        self.s = Session(asr=self.asr, mic=self.mic)
        self.addCleanup(self.s.close)
        self.s.start()
        self.s.draft.set("hello there")
        self.s.events()  # the arm's own events are not under test

    def speak(self, blocks: int) -> None:
        self.mic._blocks = [LOUD] * blocks
        self.s.tick()

    def settle(self) -> None:
        # Not `wait_idle`: that waits for the utterance to end too, and the whole point
        # here is that it has not — the gate is open and the speaker has only paused.
        deadline = time.perf_counter() + 3.0
        while self.s.worker.busy and time.perf_counter() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.s.worker.busy, "the decode never landed")
        self.s.tick()  # collects the partial: `_hear_trigger` runs here

    def kinds(self) -> list[str]:
        return [e.kind for e in self.s.events()]

    def test_boom_pastes_after_three_quiet_blocks_and_no_final_decode(self):
        self.speak(12)  # 0.77 s: past PARTIAL_MIN_GROWTH_SEC, a partial goes out
        self.settle()
        self.assertEqual(self.s._trigger_pending, "boom")
        self.mic._blocks = [QUIET] * TRIGGER_QUIET_BLOCKS
        self.s.tick()
        self.assertIn("send", self.kinds())
        self.assertEqual(self.asr.finals, 0, "the final decode ran anyway")
        self.assertEqual(self.s._utter, [], "the utterance was not spent")
        self.assertFalse(self.s.gate.speaking)
        self.assertIsNone(self.s._trigger_pending)

    def test_it_waits_for_the_speaker_to_actually_stop(self):
        # Two quiet blocks is a breath, not an end. "boom" can also be the first
        # syllable of a sentence about boom boxes.
        self.speak(12)
        self.settle()
        self.mic._blocks = [QUIET] * (TRIGGER_QUIET_BLOCKS - 1)
        self.s.tick()
        self.assertNotIn("send", self.kinds())
        self.assertEqual(self.s._trigger_pending, "boom")

    def test_a_long_utterance_that_reads_as_the_word_is_not_a_trigger(self):
        blocks = int(TRIGGER_MAX_SEC * 16_000 / BLOCK) + 2
        self.speak(blocks)
        self.settle()
        self.assertIsNone(self.s._trigger_pending)

    def test_no_draft_means_nothing_to_send_so_nothing_is_heard(self):
        self.s.draft.clear()
        self.speak(12)
        self.settle()
        self.assertIsNone(self.s._trigger_pending)

    def test_the_hangover_ending_the_utterance_first_clears_it(self):
        # The gate closes on its own after 800 ms of quiet — a release, a pause and a
        # hangover all end the utterance, and the final then decides as it always did.
        self.speak(12)
        self.settle()
        self.mic._blocks = [QUIET] * self.s.gate.hang_blocks
        # Deliberately: the quiet count reaches the hangover inside one tick, and the
        # `stopped` edge finalises before the trigger check runs.
        self.s.gate._quiet_blocks = self.s.gate.hang_blocks - 1
        self.s.tick()
        self.assertIsNone(self.s._trigger_pending)
        self.assertTrue(self.s.wait_idle(3.0))
        self.assertEqual(self.asr.finals, 1)

    def test_a_partial_that_is_not_the_word_is_left_alone(self):
        self.asr.partial = "hello again"
        self.speak(12)
        self.settle()
        self.assertIsNone(self.s._trigger_pending)
        self.mic._blocks = [QUIET] * TRIGGER_QUIET_BLOCKS
        self.s.tick()
        self.assertNotIn("send", self.kinds())


class TestTheGateCountsItsQuiet(unittest.TestCase):
    def test_quiet_blocks_only_count_while_the_gate_is_open(self):
        g = SpeechGate()
        self.assertEqual(g.quiet_blocks, 0)
        g.push(LOUD)
        self.assertTrue(g.speaking)
        g.push(QUIET)
        g.push(QUIET)
        self.assertEqual(g.quiet_blocks, 2)
        g.push(LOUD)
        self.assertEqual(g.quiet_blocks, 0)
        g.reset()
        self.assertEqual(g.quiet_blocks, 0)


class TestTheTraceWritesFromItsOwnThread(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "diag.jsonl"

    def test_a_background_trace_lands_on_disk_by_flush(self):
        d = Diag(self.path, background=True)
        for i in range(50):
            d.write("test", n=i)
        self.assertTrue(d.flush(2.0))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 50)
        d.close()
        d.close()  # idempotent

    def test_the_default_is_still_synchronous(self):
        d = Diag(self.path)
        d.write("test", n=1)
        self.assertEqual(len(self.path.read_text(encoding="utf-8").splitlines()), 1)
        self.assertTrue(d.flush())


class TestTheProfileSaveIsPaidAfterThePaste(unittest.TestCase):
    class Profile:
        path = "profile.json"

        def __init__(self) -> None:
            self.saves = 0
            self.dictated: list[tuple[int, float]] = []

        def save(self) -> bool:
            self.saves += 1
            return True

        def note_dictation(self, words: int, seconds: float) -> None:
            self.dictated.append((words, seconds))

    def test_send_owes_a_save_and_the_next_pump_pays_it(self):
        profile = self.Profile()
        s = Session(asr=TriggerAsr(), mic=FakeMic(), profile=profile)
        self.addCleanup(s.close)
        s.draft.set("words to paste")
        self.assertEqual(s.send(), "words to paste")
        self.assertEqual(profile.saves, 0, "saved in front of the paste")
        s.pump_results()
        self.assertEqual(profile.saves, 1)
        s.pump_results()
        self.assertEqual(profile.saves, 1, "paid twice")


if __name__ == "__main__":
    unittest.main()
