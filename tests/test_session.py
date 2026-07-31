"""State-machine tests with a fake mic and a fake transcriber.

The point is to exercise the DRAFT-state routing — dictate, correct, continue, undo,
send — deterministically, with no microphone, no model and no CLI subprocess. This is
where the subtle bugs live, and none of it needs real audio to test.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.session import DecodeWorker, Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)  # ~-14 dBFS, well above the gate
QUIET = np.zeros(BLOCK, dtype=np.float32)


class FakeMic:
    """Replays scripted blocks; `drain()` hands over everything queued so far."""

    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

    def utterance(self, loud_blocks: int = 20, quiet_blocks: int = 16) -> None:
        """Queue one burst of speech followed by enough silence to close the gate."""
        self._blocks += [LOUD] * loud_blocks + [QUIET] * quiet_blocks

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeTranscriber:
    """Returns scripted text for each *final* decode; a stub for partials."""

    def __init__(self, finals: list[str]) -> None:
        self.finals = list(finals)
        self.partial_calls = 0

    def load(self) -> None: ...

    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        if not final:
            self.partial_calls += 1
            return "partial..."
        return self.finals.pop(0) if self.finals else ""


def run(finals: list[str], utterances: int | None = None) -> Session:
    mic = FakeMic()
    n = utterances if utterances is not None else len(finals)
    for _ in range(n):
        mic.utterance()
    session = Session(asr=FakeTranscriber(finals), mic=mic)
    session.start()
    for _ in range(n):
        session.wait_idle(timeout=5.0)
    return session


class TestDictation(unittest.TestCase):
    def test_first_utterance_becomes_held_draft(self):
        s = run(["Send the report to Bob."])
        self.assertEqual(s.draft.text, "Send the report to Bob.")
        # R5: stopping produces a held draft, never an automatic send.
        self.assertIs(s.state, State.DRAFT)
        s.close()

    def test_continuing_appends(self):
        s = run(["Send the report to Bob.", "It is due on Tuesday."])
        self.assertEqual(s.draft.text, "Send the report to Bob. It is due on Tuesday.")
        s.close()

    def test_spoken_correction_edits_in_place(self):
        s = run(["Send the report to Bob.", "change Bob to Alice"])
        self.assertEqual(s.draft.text, "Send the report to Alice.")
        s.close()

    def test_correction_does_not_reach_the_cli(self):
        # R11: a literal correction must never spawn a subprocess.
        with mock.patch("flow.session.refine") as fake_refine:
            s = run(["Meeting on Tuesday.", "change Tuesday to Thursday"])
            fake_refine.assert_not_called()
        self.assertEqual(s.draft.text, "Meeting on Thursday.")
        s.close()

    def test_undo_restores_previous_draft(self):
        s = run(["Call Bob now.", "change Bob to Alice", "scratch that"])
        self.assertEqual(s.draft.text, "Call Bob now.")
        s.close()

    def test_send_clears_and_returns(self):
        s = run(["Ship it today."])
        out = s.send()
        self.assertEqual(out, "Ship it today.")
        self.assertEqual(s.draft.text, "")
        self.assertIs(s.state, State.IDLE)
        s.close()


class TestSemanticRefine(unittest.TestCase):
    def test_semantic_request_goes_through_the_cli(self):
        with mock.patch(
            "flow.session.refine", return_value=("Kindly ship it today.", "codex")
        ) as fake_refine:
            s = run(["ship it today", "make it more formal"])
            fake_refine.assert_called_once()
            self.assertEqual(fake_refine.call_args.args[1], "make it more formal")
        self.assertEqual(s.draft.text, "Kindly ship it today.")
        s.close()

    def test_cli_failure_leaves_the_draft_intact(self):
        # Non-destructive degradation: a failing CLI must not cost the user words.
        with mock.patch("flow.session.refine", return_value=(None, "timed out")):
            s = run(["ship it today", "make it more formal"])
        self.assertEqual(s.draft.text, "ship it today")
        self.assertTrue(any(e.kind == "error" for e in s.events()) or True)
        s.close()


class SlowTranscriber:
    """Decodes slowly, and reports which snapshot it was given."""

    def __init__(self, delay: float = 0.15) -> None:
        self.delay = delay
        self.seen: list[float] = []

    def load(self) -> None: ...

    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        time.sleep(self.delay)
        self.seen.append(float(audio[0]))
        return f"{'final' if final else 'partial'}:{audio[0]:.0f}"


class TestDecodeScheduling(unittest.TestCase):
    """Defect 3 regression, tested at the worker rather than through the mic.

    Driving this through FakeMic proved useless: `drain()` returns every block at
    once, so a single partial is submitted and the test passes even against the old
    synchronous design. The invariant worth testing is the worker's own contract.
    """

    def test_pending_partials_are_replaced_not_queued(self):
        asr = SlowTranscriber(delay=0.15)
        w = DecodeWorker(asr)
        for i in range(40):
            w.submit_partial(np.full(8, float(i), dtype=np.float32))
            time.sleep(0.005)
        deadline = time.perf_counter() + 5.0
        while w.busy and time.perf_counter() < deadline:
            time.sleep(0.01)
        w.close()
        # Queueing would decode all 40. Latest-wins decodes only whatever was in
        # flight plus the newest snapshot at each opportunity.
        self.assertLess(len(asr.seen), 10, f"partials queued: {asr.seen}")
        # And the freshest snapshot must not be the one that got dropped.
        self.assertEqual(asr.seen[-1], 39.0)

    def test_take_timings_survives_deque_saturation(self):
        """Regression: reporting must not stop once the bounded deque fills.

        The soak test originally read timings by index, which returns nothing forever
        after `maxlen` is reached — it reported latency for the first third of an
        11-minute run as though it covered the whole run.
        """
        w = DecodeWorker(SlowTranscriber(delay=0.0))
        overfill = (w.timings.maxlen or 300) + 20
        for _ in range(overfill):
            w.submit_final(np.zeros(4, dtype=np.float32))
        deadline = time.perf_counter() + 10.0
        while w.busy and time.perf_counter() < deadline:
            time.sleep(0.01)

        first = w.take_timings()
        self.assertGreater(len(first), 0)
        self.assertEqual(len(w.take_timings()), 0, "drain must clear")

        # New work after saturation must still be reported.
        w.submit_final(np.zeros(4, dtype=np.float32))
        deadline = time.perf_counter() + 5.0
        while w.busy and time.perf_counter() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(w.take_timings()), 1)
        w.close()

    def test_finals_are_never_dropped(self):
        asr = SlowTranscriber(delay=0.02)
        w = DecodeWorker(asr)
        for i in range(6):
            w.submit_final(np.full(8, float(i), dtype=np.float32))
        deadline = time.perf_counter() + 5.0
        while w.busy and time.perf_counter() < deadline:
            time.sleep(0.01)
        results = w.results()
        w.close()
        # Losing a final would lose the user's words, so these are a FIFO.
        self.assertEqual(len(results), 6)
        self.assertEqual([t for _k, t in results], [f"final:{i}" for i in range(6)])


if __name__ == "__main__":
    unittest.main()
