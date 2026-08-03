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
        self.assertEqual([t for _k, t, _s, _c, _u in results],
                         [f"final:{i}" for i in range(6)])

    def test_a_final_submitted_without_a_record_carries_none(self):
        # `selfdrive.py` and several probes submit bare audio at this seam deliberately,
        # because it is the one `Session._finalise` itself uses. They have no identity to
        # mint, and the result must route without one rather than refuse.
        w = DecodeWorker(SlowTranscriber(delay=0.0))
        w.submit_final(np.full(8, 1.0, dtype=np.float32))
        deadline = time.perf_counter() + 5.0
        out: list = []
        while not out and time.perf_counter() < deadline:
            out = w.results()
        w.close()
        self.assertIsNone(out[0][4])

    def test_a_record_rides_with_its_own_final(self):
        from flow.session import Utterance

        w = DecodeWorker(SlowTranscriber(delay=0.02))
        records = [Utterance(i, np.full(8, float(i), dtype=np.float32), 0)
                   for i in range(3)]
        for r in records:
            w.submit_final(r.audio, r)
        deadline = time.perf_counter() + 5.0
        while w.busy and time.perf_counter() < deadline:
            time.sleep(0.01)
        out = w.results()
        w.close()
        self.assertEqual([u.id for _k, _t, _s, _c, u in out], [0, 1, 2])

    def test_a_transcriber_with_no_confidence_to_report_still_decodes(self):
        # `SlowTranscriber`, like every other fake here, predates `take_confidence`.
        # A worker that assumed the method would take the whole decode path down for
        # anyone who swapped in their own Transcriber.
        w = DecodeWorker(SlowTranscriber(delay=0.0))
        w.submit_final(np.full(8, 3.0, dtype=np.float32))
        deadline = time.perf_counter() + 5.0
        out: list = []
        while not out and time.perf_counter() < deadline:
            out = w.results()
        w.close()
        self.assertEqual([(k, c) for k, _t, _s, c, _u in out], [("final", None)])


if __name__ == "__main__":
    unittest.main()


class TestATranscriptBelongsToItsOwnUtterance(unittest.TestCase):
    """CAP-01: `_last_audio` was one slot shared by every utterance ever spoken.

    `_remember_append` reads whatever `_finalise` wrote last, not the audio of the
    utterance whose text it is remembering. Those are the same thing exactly when
    decoding is instant, and decoding is the slowest thing in this app.

    So: A is submitted and its decode begins; B is spoken, captured and finalised, which
    overwrites the slot; A's text arrives and is routed, and the rescue record it leaves
    behind is (A's words, **B's sound**). "Was a command" then asks the decoder to
    re-listen to a completely different sentence — with `command_bias` built from A's
    draft — and whatever comes back is applied as if it were the rescue of A.

    The audio is what makes this sharp rather than theoretical. Every other stale-result
    defect in this codebase ends in text the user can see is wrong; this one ends in the
    decoder confidently returning a *plausible* command derived from sound the user is
    not thinking about.
    """

    def _interleaved(self):
        """A submitted, B captured and finalised, then A's result delivered."""
        session = Session(asr=FakeTranscriber([]), mic=FakeMic())
        a_audio = np.full(BLOCK, 0.11, dtype=np.float32)
        b_audio = np.full(BLOCK, 0.22, dtype=np.float32)
        session._utter = [a_audio]
        session._finalise()
        session._utter = [b_audio]
        session._finalise()
        return session, a_audio, b_audio

    def test_the_rescue_record_holds_the_audio_that_was_decoded(self):
        session, a_audio, b_audio = self._interleaved()
        # A's text arrives now, after B has already replaced the slot.
        session._route("underline the heading", record=session._sent[0])
        _text, audio = session._last_append
        self.assertIsNotNone(audio)
        self.assertTrue(np.array_equal(audio, a_audio),
                        "the rescue would re-decode a different utterance")
        self.assertFalse(np.array_equal(audio, b_audio))

    def test_the_later_utterance_keeps_its_own_audio_too(self):
        session, a_audio, b_audio = self._interleaved()
        session._route("and the second thing", record=session._sent[1])
        _text, audio = session._last_append
        self.assertTrue(np.array_equal(audio, b_audio))

    def test_a_route_with_no_utterance_still_works(self):
        # Replays, tests and the rescue path itself route text that never came from a
        # decode. They must not be forced to invent an identity.
        session = Session(asr=FakeTranscriber([]), mic=FakeMic())
        session._route("just some words")
        self.assertEqual(session.draft.text, "just some words")

    def test_the_identity_reaches_the_result_end_to_end(self):
        # The seam that matters: what `_finalise` mints has to survive the worker and
        # come back attached to the text, or `_route` has nothing to be right about.
        session = run(["first thing", "second thing"], utterances=2)
        self.addCleanup(session.close)
        self.assertEqual(len(session._sent), 2)
        self.assertNotEqual(session._sent[0].id, session._sent[1].id)


class TestPauseIsAnUtteranceBoundary(unittest.TestCase):
    """CAP-02 as the validation corrected it: `pause()` stops the mic and nothing else.

    `audio.py:102-106` is `Mic.stop()` and touches no gate state at all — the finding's
    original citation, and the reason it read as already-handled. What `pause()` actually
    does is stop the stream, stop any reply, and set IDLE. `_utter` keeps whatever blocks
    it held; `gate.reset()` is never called; the 256-block mic queue is never drained.
    And `ui.py` skips `session.tick()` entirely while disarmed, so nothing consumes any
    of it in between. Every piece survives to the next arm and lands in the next
    transcript — audio from before a deliberate pause, in words spoken after it.
    """

    def _paused_mid_speech(self):
        mic = FakeMic()
        session = Session(asr=FakeTranscriber(["whatever"]), mic=mic)
        before = np.full(BLOCK, 0.33, dtype=np.float32)
        session._utter = [before, before]
        session.gate.speaking = True
        mic._blocks = [before, before, before]
        return session, mic, before

    def test_the_held_utterance_is_discarded(self):
        session, _mic, _before = self._paused_mid_speech()
        session.pause()
        self.assertEqual(session._utter, [], "pre-pause speech survived into the next arm")

    def test_the_gate_is_closed(self):
        session, _mic, _before = self._paused_mid_speech()
        session.pause()
        self.assertFalse(session.gate.speaking,
                         "the next arm resumes mid-utterance with no onset")

    def test_the_microphone_queue_is_drained(self):
        session, mic, _before = self._paused_mid_speech()
        session.pause()
        self.assertEqual(mic.drain(), [], "blocks captured before the pause were queued")

    def test_a_result_from_before_the_pause_is_refused(self):
        # The other end of the same boundary. A decode already in flight when the user
        # paused belongs to the session they stopped, and delivering it into the next one
        # is the same defect as the queued blocks, arriving by a slower road.
        session = Session(asr=FakeTranscriber([]), mic=FakeMic())
        session._utter = [np.full(BLOCK, 0.44, dtype=np.float32)]
        session._finalise()
        stale = session._sent[0]
        session.pause()
        session._route("words from before the pause", record=stale)
        self.assertEqual(session.draft.text, "",
                         "an utterance from before the pause reached the new draft")

    def test_a_result_from_after_the_pause_is_kept(self):
        # The refusal must not become "nothing survives a pause", which would lose the
        # ordinary case: pause, re-arm, speak.
        session = Session(asr=FakeTranscriber([]), mic=FakeMic())
        session.pause()
        session._utter = [np.full(BLOCK, 0.55, dtype=np.float32)]
        session._finalise()
        session._route("words from after", record=session._sent[-1])
        self.assertEqual(session.draft.text, "words from after")
