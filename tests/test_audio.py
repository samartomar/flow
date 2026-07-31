"""Tests for the speech gate, and specifically for what it throws away.

A gate opens only after hearing something loud, so the quiet head of the word that
opened it is already past. In an accent that head is often the consonant — the
unaspirated stop, the soft fricative — and losing it turns "delete" into "leet".
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK, PREROLL_BLOCKS, SpeechGate  # noqa: E402
from flow.session import Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)
QUIET = np.full(BLOCK, 0.0005, dtype=np.float32)  # room tone, not digital silence
SILENT = np.zeros(BLOCK, dtype=np.float32)


class TestPreroll(unittest.TestCase):
    def test_the_blocks_before_the_gate_opened_are_kept(self):
        gate = SpeechGate(preroll_blocks=4)
        for _ in range(10):
            gate.push(QUIET)
        started, _ = gate.push(LOUD)
        self.assertTrue(started)
        pre = gate.take_preroll()
        self.assertEqual(len(pre), 4, "the ring should be full")

    def test_the_opening_block_is_not_in_the_preroll(self):
        # The session appends that block itself; duplicating it would repeat audio.
        gate = SpeechGate(preroll_blocks=4)
        for _ in range(4):
            gate.push(QUIET)
        gate.push(LOUD)
        for block in gate.take_preroll():
            self.assertFalse(np.array_equal(block, LOUD))

    def test_taking_the_preroll_drains_it(self):
        gate = SpeechGate(preroll_blocks=4)
        for _ in range(4):
            gate.push(QUIET)
        gate.push(LOUD)
        self.assertEqual(len(gate.take_preroll()), 4)
        self.assertEqual(gate.take_preroll(), [])

    def test_a_second_utterance_does_not_begin_with_the_first(self):
        gate = SpeechGate(preroll_blocks=4, hang_ms=128.0)
        for _ in range(4):
            gate.push(QUIET)
        gate.push(LOUD)
        first = gate.take_preroll()
        self.assertEqual(len(first), 4)
        # Talk, stop, then start again with only one quiet block in between.
        for _ in range(5):
            gate.push(LOUD)
        for _ in range(5):
            gate.push(QUIET)
        self.assertFalse(gate.speaking)
        gate.push(LOUD)
        self.assertLessEqual(len(gate.take_preroll()), 5)

    def test_reset_clears_it(self):
        gate = SpeechGate(preroll_blocks=4)
        for _ in range(4):
            gate.push(QUIET)
        gate.reset()
        gate.push(LOUD)
        self.assertEqual(gate.take_preroll(), [])

    def test_zero_disables_it(self):
        gate = SpeechGate(preroll_blocks=0)
        for _ in range(4):
            gate.push(QUIET)
        gate.push(LOUD)
        self.assertEqual(gate.take_preroll(), [])

    def test_the_default_is_the_measured_one(self):
        # 256 ms. Measured: without pre-roll the gate drops 2.6% of the audio and
        # costs ~2.5% relative WER; any setting from 128 ms up restores it.
        self.assertEqual(PREROLL_BLOCKS, 4)
        self.assertEqual(SpeechGate()._preroll.maxlen, 4)

    def test_digital_silence_does_not_train_the_floor(self):
        # Regression: the pre-roll rearranged this branch, and the clamp that stops a
        # silent stretch making the gate hypersensitive lives inside it.
        gate = SpeechGate()
        before = gate.floor_db
        for _ in range(50):
            gate.push(SILENT)
        self.assertEqual(gate.floor_db, before)


class RecordingAsr:
    """Captures how much audio each final actually received."""

    def __init__(self):
        self.final_samples = []

    def load(self) -> None: ...
    def unload(self) -> None: ...
    loaded = True

    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        if final:
            self.final_samples.append(len(audio))
            return "captured"
        return ""


class ScriptedMic:
    def __init__(self, blocks):
        self._blocks = list(blocks)
        self.level_db = -60.0

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self):
        out, self._blocks = self._blocks, []
        return out


class TestSessionKeepsTheOnset(unittest.TestCase):
    @staticmethod
    def _captured(preroll: int) -> int:
        """Samples the decoder received for one utterance at this pre-roll setting."""
        blocks = [QUIET] * 6 + [LOUD] * 10 + [QUIET] * 16
        asr = RecordingAsr()
        s = Session(asr=asr, mic=ScriptedMic(blocks))
        s.gate = SpeechGate(preroll_blocks=preroll)
        s.start()
        s.wait_idle(timeout=5.0)
        s.close()
        assert len(asr.final_samples) == 1, asr.final_samples
        return asr.final_samples[0]

    def test_the_utterance_gains_exactly_the_preroll(self):
        # Asserted as a difference rather than an absolute: the captured audio also
        # contains the hangover blocks, and pinning that total here would make this
        # test fail for a reason it is not about.
        without = self._captured(0)
        with_preroll = self._captured(PREROLL_BLOCKS)
        self.assertEqual(with_preroll - without, PREROLL_BLOCKS * BLOCK)

    def test_the_draft_still_arrives(self):
        blocks = [QUIET] * 6 + [LOUD] * 10 + [QUIET] * 16
        asr = RecordingAsr()
        s = Session(asr=asr, mic=ScriptedMic(blocks))
        s.start()
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "captured")
        self.assertIs(s.state, State.DRAFT)
        s.close()


if __name__ == "__main__":
    unittest.main()
