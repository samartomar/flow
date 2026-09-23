"""Flow Home's Voice page: the dictionary, what Flow learned, tuning, and the accuracy check.

Pinned here:

- **accuracy** scores a sentence word by word and keeps the path, so the page can show
  exactly which words were missed;
- **the dictionary file** gains two writes, both on an explicit tap — add a word, remove
  one entry — and a removal returns every other byte exactly as it was;
- **what Flow learned** can be seen, declared, declined or forgotten;
- **tuning** can stop early once it has enough, and says when it is measuring;
- **the microphone is lent**, never shared: the pill refuses to arm while a Voice task
  listens, says why rather than drawing a dead microphone, and gets it back whatever
  happens;
- **the two tasks** run end to end over the demo's pretend microphone and decoder.

Nothing here opens a real microphone, loads a model or touches the real `~/.flow`.
"""

import collections
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow import accuracy, calibrate, lexicon  # noqa: E402
from flow.home import Home  # noqa: E402
from flow.home.demo import FakeSession, ReadingMic  # noqa: E402
from flow.home.voice import worth_offering  # noqa: E402
from flow.profile import Profile  # noqa: E402
from flow.session import Session  # noqa: E402


class Pumped:
    """A Home over the demo's FakeSession, pumped on a thread as a pill's frames would."""

    def __init__(self, test: unittest.TestCase, rate: float = 1.0) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="flow-voice-test-"))
        self.profile = Profile(self.folder / "profile.json")
        self.session = FakeSession(self.profile)
        self.session.asr._takes = 0
        self._stop = threading.Event()
        threading.Thread(target=self._pump, daemon=True).start()
        test.addCleanup(self._stop.set)
        self.home = Home(self.session, profile=self.profile, hotkeys=None, lite=False,
                         lexicon_path=self.folder / "lexicon.txt",
                         trace_path=self.folder / "diag.jsonl")
        self.home.mic_factory = lambda: ReadingMic(rate=rate)
        test.addCleanup(self.home.close)

    def _pump(self) -> None:
        while not self._stop.is_set():
            self.session.run_posted()
            time.sleep(0.005)

    def call(self, path: str, body: dict | None = None, method: str = "POST"):
        return self.home.api.handle(method, path, body or {})

    def wait(self, task, states, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if task.state in states:
                return task.state
            time.sleep(0.02)
        raise AssertionError(f"{type(task).__name__} stuck in {task.state}")


# ------------------------------------------------------------------------------ scoring


class TestTheScore(unittest.TestCase):
    def test_words_are_compared_plainly(self):
        self.assertEqual(accuracy.words("Set-up the Kubernetes logs, please!"),
                         ["set", "up", "the", "kubernetes", "logs", "please"])
        self.assertEqual(accuracy.words("don't"), ["don't"])

    def test_a_perfect_read_has_no_errors(self):
        s = accuracy.align("Ask Priya to check the logs.", "ask priya to check the logs")
        self.assertEqual((s.errors, s.total), (0, 6))
        self.assertEqual(s.missed, [])

    def test_a_substitution_an_insertion_and_a_deletion(self):
        s = accuracy.align("Please review the pull request", "please we view the request")
        ops = [st.op for st in s.steps]
        self.assertEqual(ops.count("ok"), 3)
        self.assertEqual(s.errors, 3)
        self.assertEqual(s.total, 5)
        # The reference's own spelling comes back, capitals and all.
        s = accuracy.align("Ask Priya to check", "ask pria to check")
        self.assertEqual(s.missed, ["Priya"])

    def test_per_hundred_pools_every_sentence(self):
        a = accuracy.align("one two three four", "one two three four")
        b = accuracy.align("five six seven eight", "five six seven")
        self.assertEqual(accuracy.per_hundred([a, b]), 12.5)
        self.assertIsNone(accuracy.per_hundred([]))

    def test_only_names_are_offered_for_the_dictionary(self):
        # Biasing common words is the measured harm; a missed name is the measured help.
        self.assertEqual(worth_offering("Ask Priya to check the Kubernetes logs.",
                                        ["Ask", "Priya", "check", "Kubernetes"]),
                         ["Priya", "Kubernetes"])

    def test_the_sentences_are_short_and_carry_names(self):
        self.assertEqual(len(accuracy.SENTENCES), 5)
        for s in accuracy.SENTENCES:
            self.assertLessEqual(len(accuracy.words(s)), 14)


# ------------------------------------------------------------------------------ the file


class TestTheDictionaryFile(unittest.TestCase):
    def path(self, text=None) -> Path:
        p = Path(tempfile.mkdtemp()) / "lexicon.txt"
        if text is not None:
            p.write_bytes(text.encode("utf-8"))
        return p

    def test_a_word_is_appended_and_the_rest_kept(self):
        p = self.path("# mine\nSamir")
        self.assertEqual(lexicon.append_term(p, "  Grafana  "), "")
        self.assertEqual(p.read_text(encoding="utf-8"), "# mine\nSamir\nGrafana\n")

    def test_a_word_that_is_there_or_cannot_be_a_line_is_refused(self):
        p = self.path("Samir\n")
        self.assertIn("already", lexicon.append_term(p, "samir"))
        self.assertIn("#", lexicon.append_term(p, "a#b"))
        self.assertIn("#", lexicon.append_term(p, "a -> b"))
        self.assertIn("40", lexicon.append_term(p, "x" * 41))
        self.assertEqual(p.read_text(encoding="utf-8"), "Samir\n")

    def test_a_missing_file_starts_from_the_template(self):
        p = self.path()
        self.assertEqual(lexicon.append_term(p, "Priya"), "")
        text = p.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(lexicon.TEMPLATE))
        self.assertEqual(lexicon.entries(text)[0], ["Priya"])

    def test_the_cap_is_refused_not_trimmed(self):
        p = self.path("".join(f"term{i}\n" for i in range(lexicon.MAX_TERMS)))
        self.assertIn("full", lexicon.append_term(p, "one-more"))

    def test_a_correction_for_a_word_already_corrected_is_refused(self):
        p = self.path("semir -> Samir\n")
        self.assertIn("already", lexicon.append_pair(p, "Semir", "Sameer"))
        self.assertIn("same", lexicon.append_pair(p, "Priya", "Priya"))

    def test_removing_a_word_leaves_every_other_byte(self):
        original = "# my words\r\nSamir\r\n\r\nGrafana  # the dashboards\r\nsemir -> Samir\r\nPriya"
        p = self.path(original)
        self.assertEqual(lexicon.remove_entry(p, term="grafana"), "")
        self.assertEqual(p.read_bytes().decode("utf-8"),
                         "# my words\r\nSamir\r\n\r\nsemir -> Samir\r\nPriya")

    def test_removing_a_correction_by_its_left_side(self):
        p = self.path("Samir\nsemir -> Samir\nSEMIR -> Samir\n")
        self.assertEqual(lexicon.remove_entry(p, wrong="Semir"), "")
        self.assertEqual(p.read_text(encoding="utf-8"), "Samir\n")

    def test_a_word_named_like_a_correction_is_not_removed_as_one(self):
        p = self.path("semir\nsemir -> Samir\n")
        self.assertEqual(lexicon.remove_entry(p, term="semir"), "")
        self.assertEqual(p.read_text(encoding="utf-8"), "semir -> Samir\n")

    def test_an_entry_that_is_not_there_changes_nothing(self):
        p = self.path("Samir\n")
        self.assertIn("not in the file", lexicon.remove_entry(p, term="Priya"))
        self.assertEqual(p.read_text(encoding="utf-8"), "Samir\n")

    def test_a_file_that_is_not_utf8_is_left_alone(self):
        p = Path(tempfile.mkdtemp()) / "lexicon.txt"
        p.write_bytes(b"Samir\n\xff\xfe junk\n")
        self.assertIn("by hand", lexicon.remove_entry(p, term="Samir"))
        self.assertEqual(p.read_bytes(), b"Samir\n\xff\xfe junk\n")

    def test_one_kind_at_a_time(self):
        with self.assertRaises(ValueError):
            lexicon.remove_entry(self.path("x\n"), term="x", wrong="x")


class TestWhatFlowLearned(unittest.TestCase):
    def profile(self):
        p = Profile(Path(tempfile.mkdtemp()) / "profile.json")
        p.pairs.update({"cube control -> kubectl": 3, "semir -> Samir": 2, "tuesday -> Tue": 1})
        return p

    def test_the_learned_list_carries_its_evidence(self):
        self.assertEqual(self.profile().learned_pairs(),
                         [("cube control", "kubectl", 3), ("semir", "Samir", 2)])

    def test_forgetting_takes_the_bias_with_it(self):
        p = self.profile()
        self.assertTrue(p.forget_pair("Cube Control", "kubectl"))
        self.assertNotIn("kubectl", p.learned_terms())
        self.assertFalse(p.forget_pair("nothing", "here"))


# ------------------------------------------------------------------------------ tuning


class FakeMicFeed:
    """Blocks on demand: `speech` seconds of voice then quiet, as fast as asked."""

    def __init__(self, blocks):
        self.blocks = list(blocks)

    def drain(self):
        out, self.blocks = self.blocks[:8], self.blocks[8:]
        return out


class TestTuningCanStopEarly(unittest.TestCase):
    def feed(self):
        import numpy as np

        from flow.audio import BLOCK

        rng = np.random.default_rng(1)
        loud = [(rng.standard_normal(BLOCK) * 0.08).astype(np.float32) for _ in range(400)]
        quiet = [(rng.standard_normal(BLOCK) * 0.001).astype(np.float32) for _ in range(120)]
        return FakeMicFeed(quiet[:60] + loud + quiet[60:])

    def test_stop_ends_the_listening_and_decode_is_announced(self):
        calls = []
        started = time.monotonic()
        result = calibrate.measure(self.feed(), seconds=30, stop=lambda: len(calls) > 3 or
                                   bool(calls.append(1)), on_decode=lambda: calls.append("d"))
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn("d", calls)
        self.assertGreater(result.speech_sec, 0)

    def test_enough_is_what_usable_will_say(self):
        self.assertFalse(calibrate.enough([-40.0] * 10))
        levels = [-70.0] * 80 + [-25.0] * 300
        self.assertTrue(calibrate.enough(levels))


# ------------------------------------------------------------------------------ the loan


class TestTheMicrophoneIsLentNotShared(unittest.TestCase):
    def session(self, started=False, talking=False):
        s = Session.__new__(Session)
        s._mic_on_loan = ""
        s._mic_started = started
        s._mic_lingering = False
        s._events = collections.deque()
        s._posted = queue.SimpleQueue()
        s.pause = mock.Mock()
        s._end_linger = mock.Mock()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(Session, "talking", new_callable=mock.PropertyMock,
                          return_value=talking).start()
        return s

    def test_lending_stops_capture_and_says_so(self):
        s = self.session(started=True)
        self.assertEqual(s.lend_mic("Flow is being tuned"), "")
        s.pause.assert_called_once()
        kinds = [(e.kind, e.text) for e in s._events]
        # "lent", so a surface does not draw a microphone that went away.
        self.assertIn(("disarm", "lent"), kinds)
        self.assertEqual(s.mic_on_loan, "Flow is being tuned")

    def test_the_pill_cannot_arm_while_it_is_lent(self):
        s = self.session()
        s._lifecycle = threading.Lock()
        s._closed = False
        s.lend_mic("Flow is being tuned")
        with self.assertRaises(RuntimeError) as caught:
            s.start()
        self.assertIn("Flow is being tuned", str(caught.exception))

    def test_not_while_a_reply_plays_and_not_twice(self):
        self.assertIn("reply", self.session(talking=True).lend_mic("x"))
        s = self.session()
        s.lend_mic("tuning")
        self.assertIn("tuning", s.lend_mic("the check"))

    def test_giving_it_back(self):
        s = self.session()
        s.lend_mic("tuning")
        s.return_mic()
        self.assertEqual(s.mic_on_loan, "")
        self.assertIn("back", s._events[-1].text)


class TestTheCompactPillSaysWhyItCannotListen(unittest.TestCase):
    def pill(self):
        import flow.ui_compact as uc

        p = uc.CompactPill.__new__(uc.CompactPill)
        p.session = mock.Mock(mic_on_loan="Flow is being tuned")
        p.session.talk_start.side_effect = RuntimeError(
            "Flow is being tuned - the pill listens again when it is done")
        p._say = mock.Mock()
        p._send_pending = p._ask_pending = False
        p._send_since = None
        return p

    def test_a_hold_while_it_is_lent_says_why_and_draws_no_dead_microphone(self):
        p = self.pill()
        p._mic_gone = False
        p._talk_start()
        p._say.assert_called_once()
        self.assertIn("tuned", p._say.call_args.args[0])
        self.assertFalse(p._mic_gone)


# ------------------------------------------------------------------------------ end to end


class TestTheAccuracyCheckEndToEnd(unittest.TestCase):
    def test_five_takes_scored_and_the_microphone_back(self):
        h = Pumped(self, rate=8.0)
        self.assertEqual(h.call("/api/voice/check", {"action": "start"})[0], 200)
        self.assertTrue(h.session.mic_on_loan)
        check = h.home.voice.check
        for _ in accuracy.SENTENCES:
            self.assertEqual(h.call("/api/voice/check", {"action": "record"})[0], 200)
            h.wait(check, ("ready", "done", "failed"))
        self.assertEqual(check.state, "done")
        page = h.call("/api/voice", method="GET")[1]
        self.assertIsNotNone(page["check"]["per_hundred"])
        self.assertEqual(page["check"]["offers"], ["Priya", "Samir"])
        deadline = time.time() + 2
        while h.session.mic_on_loan and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(h.session.mic_on_loan, "")

    def test_a_name_once_added_is_no_longer_offered(self):
        h = Pumped(self, rate=8.0)
        h.call("/api/voice/check", {"action": "start"})
        for _ in accuracy.SENTENCES:
            h.call("/api/voice/check", {"action": "record"})
            h.wait(h.home.voice.check, ("ready", "done"))
        h.call("/api/voice/word", {"term": "Priya"})
        self.assertEqual(h.call("/api/voice", method="GET")[1]["check"]["offers"], ["Samir"])

    def test_cancel_gives_the_microphone_back(self):
        h = Pumped(self)
        h.call("/api/voice/check", {"action": "start"})
        h.call("/api/voice/check", {"action": "cancel"})
        deadline = time.time() + 2
        while h.session.mic_on_loan and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(h.session.mic_on_loan, "")
        self.assertEqual(h.home.voice.check.state, "idle")

    def test_one_task_at_a_time(self):
        h = Pumped(self)
        h.call("/api/voice/check", {"action": "start"})
        status, body = h.call("/api/voice/tune", {"action": "start"})
        self.assertEqual(status, 400)
        self.assertIn("check", body["error"])


class TestTuningEndToEnd(unittest.TestCase):
    def test_a_finished_tuning_is_saved_and_applied_to_the_live_gate(self):
        h = Pumped(self, rate=20.0)
        h.home.voice.tune.seconds = 3.0
        self.assertEqual(h.call("/api/voice/tune", {"action": "start"})[0], 200)
        h.wait(h.home.voice.tune, ("done", "failed"))
        self.assertEqual(h.home.voice.tune.state, "done", h.home.voice.tune.error)
        saved = Profile(h.profile.path)
        self.assertTrue(saved.calibrated)
        self.assertEqual(saved.calibrated_device, "Yeti Nano")
        self.assertEqual(h.session.gate.floor_db, saved.floor_db)
        page = h.call("/api/voice", method="GET")[1]
        self.assertIsNotNone(page["tune"]["last"])

    def test_cancel_saves_nothing(self):
        h = Pumped(self, rate=20.0)
        h.home.voice.tune.seconds = 3.0
        h.call("/api/voice/tune", {"action": "start"})
        h.call("/api/voice/tune", {"action": "cancel"})
        h.wait(h.home.voice.tune, ("idle", "failed", "done"))
        self.assertFalse(Profile(h.profile.path).calibrated)

    def test_no_profile_means_nowhere_to_save_and_it_says_so(self):
        h = Pumped(self)
        h.home.profile = None
        status, body = h.call("/api/voice/tune", {"action": "start"})
        self.assertEqual(status, 400)
        self.assertIn("--no-profile", body["error"])
        self.assertEqual(h.session.mic_on_loan, "")


class TestTheDictionaryThroughThePage(unittest.TestCase):
    def test_add_and_remove_a_word_and_a_correction(self):
        h = Pumped(self)
        self.assertEqual(h.call("/api/voice/word", {"term": "Grafana"})[0], 200)
        self.assertEqual(h.call("/api/voice/correction", {"wrong": "semir", "right": "Samir"})[0], 200)
        d = h.call("/api/voice", method="GET")[1]["dictionary"]
        self.assertEqual(d["terms"], ["Grafana"])
        self.assertEqual(d["corrections"], [{"wrong": "semir", "right": "Samir"}])
        self.assertEqual(d["used"], 2)
        h.call("/api/voice/word/remove", {"term": "grafana"})
        h.call("/api/voice/correction/remove", {"wrong": "SEMIR"})
        d = h.call("/api/voice", method="GET")[1]["dictionary"]
        self.assertEqual((d["terms"], d["corrections"]), ([], []))
        # And the template Flow wrote is still there, byte for byte.
        self.assertEqual((h.folder / "lexicon.txt").read_text(encoding="utf-8"), lexicon.TEMPLATE)

    def test_a_learned_pair_is_fixed_declined_or_forgotten(self):
        h = Pumped(self)
        h.profile.pairs.update({"cube control -> kubectl": 3, "post gress -> Postgres": 2})
        rows = {r["wrong"]: r for r in h.call("/api/voice", method="GET")[1]["dictionary"]["learned"]}
        self.assertEqual(rows["cube control"]["status"], "offer")
        h.call("/api/voice/learned", {"wrong": "cube control", "right": "kubectl", "action": "fix"})
        h.call("/api/voice/learned", {"wrong": "post gress", "right": "Postgres", "action": "never"})
        rows = {r["wrong"]: r for r in h.call("/api/voice", method="GET")[1]["dictionary"]["learned"]}
        self.assertEqual(rows["cube control"]["status"], "fixed")
        self.assertEqual(rows["post gress"]["status"], "declined")
        h.call("/api/voice/learned", {"wrong": "post gress", "right": "Postgres", "action": "forget"})
        rows = {r["wrong"] for r in h.call("/api/voice", method="GET")[1]["dictionary"]["learned"]}
        self.assertEqual(rows, {"cube control"})
        self.assertNotIn("post gress -> Postgres", Profile(h.profile.path).pairs)

    def test_no_lexicon_means_the_dictionary_says_it_is_off(self):
        h = Pumped(self)
        h.home.lexicon_path = lexicon.NUL_PATH
        d = h.call("/api/voice", method="GET")[1]["dictionary"]
        self.assertFalse(d["enabled"])
        status, body = h.call("/api/voice/word", {"term": "Grafana"})
        self.assertEqual(status, 400)
        self.assertIn("--no-lexicon", body["error"])

    def test_the_page_lists_what_can_be_said(self):
        h = Pumped(self)
        page = h.call("/api/voice", method="GET")[1]
        says = [c["say"] for c in page["commands"]]
        self.assertIn("scratch that", says)
        self.assertEqual(page["send"]["word"], "boom")


if __name__ == "__main__":
    unittest.main()
