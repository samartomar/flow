"""The trace must never become a transcript.

A voice app's log is the one log that can quietly turn into a record of everything
somebody dictated, and that is worse than having no diagnostics at all. So the central
test here is not "does it record the right things" but "can the user's words get in" —
driven by pushing one sentinel string through every path a session has and then reading
the whole file back looking for it.

The second question is size. A trace that grows without limit is the same defect as an
unbounded queue, one file away.
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.diag import FIELDS, NEVER, REFUSED, Diag, NullDiag  # noqa: E402
from flow.session import CONVERSE, Session  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)

#: One improbable string, put everywhere the user's words can reach: what they said,
#: what was drafted, what a rewrite returned, what the CLI answered, what they taught
#: it, and what the transcriber invented. If any path writes content, this comes out.
SENTINEL = "zarquon-flimflam-93471"


class SentinelAsr:
    def __init__(self) -> None:
        self.calls = 0

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        self.calls += 1
        return f"{SENTINEL} the deploy failed" if final else SENTINEL


class SentinelMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0
        self.dropped = 0
        self.device_name = f"{SENTINEL} Microphone"

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class SentinelSpeaker:
    def __init__(self) -> None:
        self.speaking = False
        self.said: list[str] = []

    def say(self, text: str) -> bool:
        self.said.append(text)
        self.speaking = True
        return True

    def stop(self) -> None:
        self.speaking = False


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "diag.jsonl"

    def lines(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(ln) for ln in
                self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestTheWordsCannotGetIn(Temp):
    def drive(self) -> str:
        """Run one sentinel through every path a session has, and return the file."""
        diag = Diag(self.path)
        asr, mic = SentinelAsr(), SentinelMic()
        s = Session(asr=asr, mic=mic, diag=diag, speaker=SentinelSpeaker())
        s.start()

        # Speech, decoded to the sentinel, routed, appended.
        for _ in range(8):
            mic._blocks.append(LOUD)
        s.tick()
        for _ in range(20):
            mic._blocks.append(np.zeros(BLOCK, dtype=np.float32))
        s.wait_idle(timeout=5.0)

        # A local correction, which is also what the profile learns from.
        s.draft.set(f"{SENTINEL} needs a rewrite")
        s._route(f"change {SENTINEL} to {SENTINEL}-two")

        # A rewrite, and a rewrite that fails.
        with mock.patch("flow.session.refine",
                        return_value=(f"{SENTINEL} revised", "codex")):
            s._start_refine(f"make it {SENTINEL}")
            s.wait_idle(timeout=5.0)
        with mock.patch("flow.session.refine",
                        return_value=(None, f"codex exited 1: {SENTINEL} not found")):
            s._start_refine(f"make it {SENTINEL} again")
            s.wait_idle(timeout=5.0)

        # A question and its answer, spoken aloud.
        s.toggle_mode()
        self.assertEqual(s.mode, CONVERSE)
        s.draft.set(f"what is {SENTINEL}")
        with mock.patch("flow.session.ask", return_value=(f"{SENTINEL} is a word", "codex")):
            s.send()
            s.wait_idle(timeout=5.0)

        # An overflow, a device restart, and a stale rewrite discarded.
        mic.dropped = 40
        s.tick()
        s.draft.set(f"{SENTINEL} again")
        with s._refine_lock:
            s._refine_op = 999
            s._refine_result = (999, -1, (f"{SENTINEL} stale", "codex"))
        s.pump_results()

        s.close()
        return self.path.read_text(encoding="utf-8")

    def test_the_sentinel_never_reaches_the_file(self):
        body = self.drive()
        self.assertNotIn(SENTINEL, body)

    def test_and_the_file_is_not_empty_which_would_prove_nothing(self):
        # A trace that recorded nothing would pass the test above for the wrong reason.
        self.drive()
        kinds = {r["kind"] for r in self.lines()}
        for expected in ("state", "decode", "route", "refine", "ask", "overflow"):
            self.assertIn(expected, kinds)

    def test_every_key_written_is_one_that_was_agreed(self):
        self.drive()
        for record in self.lines():
            for key in record:
                self.assertIn(key, FIELDS, f"{key} was written but is not allowed")

    def test_nothing_was_quietly_refused_either(self):
        # A REFUSED marker means a caller passed something that is not a token, which
        # is a defect in the caller even though the guard held.
        self.drive()
        for record in self.lines():
            self.assertNotIn(REFUSED, record.values(), f"a value was refused: {record}")


class TestTheGuard(Temp):
    def test_a_field_nobody_agreed_to_is_dropped_and_counted(self):
        d = Diag(self.path)
        d.write("test", draft="the user's words")
        self.assertEqual(d.rejected, 1)
        self.assertEqual(self.lines()[0], {"t": mock.ANY, "kind": "test"})

    def test_a_sentence_in_an_allowed_field_is_still_refused(self):
        # The allow-list is about provenance; this is the belt underneath it.
        d = Diag(self.path)
        d.write("test", reason="the deploy failed again this morning")
        self.assertEqual(self.lines()[0]["reason"], REFUSED)

    def test_the_records_own_fields_cannot_be_overwritten(self):
        d = Diag(self.path)
        d.write("test", **{"kind": "something-else"})
        self.assertEqual(self.lines()[0]["kind"], "test")
        self.assertEqual(d.rejected, 1)

    def test_the_words_are_named_and_kept_off_the_allow_list(self):
        self.assertFalse(FIELDS & NEVER)

    def test_numbers_and_booleans_go_through_untouched(self):
        d = Diag(self.path)
        d.write("test", ms=1234, ok=True, op=7, provider=None)
        self.assertEqual(
            {k: v for k, v in self.lines()[0].items() if k != "t"},
            {"kind": "test", "ms": 1234, "ok": True, "op": 7, "provider": None},
        )

    def test_an_unwritable_path_is_not_a_crash(self):
        # A diagnostics writer that can raise takes the app down with it.
        Diag(self.dir / "no" / "such" / "dir" / "x.jsonl").write("test", ms=1)


class TestItStaysBounded(Temp):
    def test_it_rotates_once_and_stops_growing(self):
        d = Diag(self.path, max_bytes=2_000)
        for i in range(2_000):
            d.write("test", n=i, ms=i, op=i, chars=i)
        live = self.path.stat().st_size
        backup = self.path.with_suffix(".jsonl.1").stat().st_size
        self.assertLessEqual(live, 2_000)
        self.assertLessEqual(backup, 2_000)
        self.assertEqual(len(list(self.dir.iterdir())), 2, "a log directory appeared")

    def test_the_newest_records_are_the_ones_kept(self):
        # Rotating the wrong way round would keep the beginning of a long session and
        # throw away the part containing whatever just went wrong.
        d = Diag(self.path, max_bytes=2_000)
        for i in range(2_000):
            d.write("test", n=i)
        self.assertEqual(self.lines()[-1]["n"], 1_999)


class TestTracingIsSomethingTheAppTurnsOn(unittest.TestCase):
    def test_a_session_traces_nothing_by_default(self):
        # The tests build sessions in their hundreds. A default that wrote to
        # `~/.flow/diag.jsonl` would fill the real user's trace with runs that were
        # never theirs — which is exactly what the first version of this did.
        s = Session(asr=SentinelAsr(), mic=SentinelMic())
        self.addCleanup(s.close)
        self.assertIsInstance(s.diag, NullDiag)
        self.assertIsNone(s.diag.path)


if __name__ == "__main__":
    unittest.main()


class TestWhatProducedAMeasurement(Temp):
    """Half the numbers in the architecture doc are latencies and error rates, and
    every one belongs to a build. A ctranslate2 release changes the arithmetic and a
    model revision changes the weights; neither announces itself, so a result six
    months old could only be compared to a fresh one by hoping."""

    def record(self) -> dict:
        from flow.diag import record_identity

        diag = Diag(self.path)
        record_identity(diag, models=("base.en",))
        return {r["component"]: r["version"] for r in self.lines()}

    def test_the_packages_that_decide_the_numbers_are_named(self):
        got = self.record()
        for component in ("faster-whisper", "ctranslate2", "numpy", "python", "os"):
            self.assertIn(component, got)
            self.assertTrue(got[component], f"{component} recorded empty")

    def test_the_model_is_recorded_as_a_revision_not_a_name(self):
        # "base.en" names a model, not a build of one. Two runs of that name months
        # apart are not necessarily the same weights.
        got = self.record()
        self.assertIn("model:base.en", got)

    def test_an_absent_package_is_recorded_as_absent_rather_than_omitted(self):
        # A missing line reads as "nobody looked". This has to read as "it was not here".
        from flow.diag import _packages

        with mock.patch("importlib.metadata.version", side_effect=Exception("nope")):
            self.assertTrue(all(v == "absent" for _n, v in _packages()))

    def test_an_uncached_model_says_so(self):
        from flow.diag import model_revision

        self.assertEqual(model_revision("no-such-model-flow-test"), "")

    def test_every_value_survives_the_redaction_guard(self):
        # Versions and hashes are tokens; a path or a banner line would not be, and
        # would land in the file as <refused> instead.
        for version in self.record().values():
            self.assertNotEqual(version, REFUSED)

    def test_a_broken_probe_cannot_stop_the_app_starting(self):
        from flow.diag import record_identity

        with mock.patch("flow.diag.identity", side_effect=OSError("no")):
            record_identity(Diag(self.path), models=())
        self.assertEqual(self.lines(), [])
