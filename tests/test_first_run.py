"""The first run (decisions.md 2026-09-23, "The first run").

Pinned here:

- **it opens once, for a profile that has not been through it**, and never under
  `--no-profile`; finishing or skipping it writes `profile.welcomed`, and the Classic
  pill's welcome card it replaced is gone;
- **the microphone test** says "heard" only for a voice, never for a room, and closes
  its stream before a microphone switch refreshes PortAudio;
- **the models** it downloads are the ones the session will use, fetched without
  pinning them, and the session is warmed when they land; the smaller pair is a choice
  and is saved as one;
- **a launch never starts a silent multi-gigabyte download** while the first run is on
  screen to show it with progress;
- **Paste last** is on alt+shift+Z — see tests/test_history.py.

Nothing here opens a real microphone, loads a model, starts a download or opens a window.
"""

import contextlib
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow import SAMPLE_RATE  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.home import Home  # noqa: E402
from flow.home import voice as voice_mod  # noqa: E402
from flow.home.demo import FakeSession, ReadingMic  # noqa: E402
from flow.profile import Profile  # noqa: E402


class QuietMic:
    """A room with nobody in it: steady, low noise for as long as it is read."""

    device_name = "Room Mic"
    want = None

    def __init__(self) -> None:
        self._t0 = None
        self._sent = 0

    def start(self) -> None:
        self._t0 = time.monotonic()

    def stop(self) -> None:
        self._t0 = None

    def drain(self):
        if self._t0 is None:
            return []
        due = int((time.monotonic() - self._t0) * SAMPLE_RATE / BLOCK)
        rng = np.random.default_rng(self._sent)
        out = []
        while self._sent < due:
            out.append((rng.standard_normal(BLOCK) * 0.002).astype(np.float32))
            self._sent += 1
        return out


class Pumped:
    def __init__(self, test: unittest.TestCase, mic=ReadingMic) -> None:
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.profile = Profile(self.folder / "profile.json")
        self.session = FakeSession(self.profile)
        test.addCleanup(self.session.history.flush)
        self._stop = threading.Event()
        threading.Thread(target=self._pump, daemon=True).start()
        test.addCleanup(self._stop.set)
        self.home = Home(self.session, profile=self.profile, hotkeys=None, lite=False,
                         lexicon_path=self.folder / "lexicon.txt",
                         trace_path=self.folder / "diag.jsonl")
        self.home.mic_factory = mic
        test.addCleanup(self.home.close)

    def _pump(self) -> None:
        while not self._stop.is_set():
            self.session.run_posted()
            time.sleep(0.005)

    def call(self, path: str, body: dict | None = None, method: str = "POST"):
        return self.home.api.handle(method, path, body or {})


def wait_for(test, check, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return
        time.sleep(0.02)
    test.fail("it never happened")


# ------------------------------------------------------------------------------ the mic test


class TestTheMicrophoneTest(unittest.TestCase):
    def test_a_voice_is_heard(self):
        h = Pumped(self)
        code, page = h.call("/api/start/listen", {"action": "start"})
        self.assertEqual(code, 200, page)
        self.assertEqual(h.session.mic_on_loan, voice_mod.Listen.WHY)
        wait_for(self, lambda: h.home.voice.listen.heard)
        _c, page = h.call("/api/start", method="GET")
        self.assertTrue(page["mic"]["listen"]["heard"])
        h.call("/api/start/listen", {"action": "stop"})
        self.assertEqual(h.home.voice.listen.state, "idle")
        # Given back, and the pill may arm again.
        wait_for(self, lambda: h.session.mic_on_loan == "")

    def test_a_silent_room_is_never_heard(self):
        # The one lie this step exists to prevent: "Hearing you" said over silence.
        levels = [-62.0 + (i % 5) * 0.8 for i in range(200)]
        self.assertEqual(voice_mod.voice_seconds(levels), 0.0)
        h = Pumped(self, mic=QuietMic)
        h.call("/api/start/listen", {"action": "start"})
        time.sleep(1.2)
        self.assertFalse(h.home.voice.listen.heard)
        h.call("/api/start/listen", {"action": "stop"})

    def test_a_microphone_switch_closes_the_test_stream_first(self):
        # `Mic.use` refreshes PortAudio, which frees every open stream in the process.
        h = Pumped(self)
        h.call("/api/start/listen", {"action": "start"})
        order = []
        real_stop = h.home.voice.listen.stop

        def stop(*a, **kw):
            order.append("stop")
            real_stop(*a, **kw)

        def switch(name):
            order.append(("switch", h.home.voice.listen.state))
            return True

        with mock.patch.object(h.home.voice.listen, "stop", side_effect=stop), \
                mock.patch.object(h.session, "set_microphone", side_effect=switch):
            code, _page = h.call("/api/start/mic", {"name": "Microphone (fifine)"})
        self.assertEqual(code, 200)
        self.assertEqual(order[0], "stop")
        self.assertEqual(order[1], ("switch", "idle"))
        # And it listens again, to the new one.
        self.assertEqual(h.home.voice.listen.state, "listening")
        h.call("/api/start/listen", {"action": "stop"})

    def test_a_tuning_ends_the_test_rather_than_being_refused_by_it(self):
        h = Pumped(self)
        h.call("/api/start/listen", {"action": "start"})
        code, page = h.call("/api/voice/tune", {"action": "start"})
        self.assertEqual(code, 200, page)
        self.assertEqual(h.home.voice.listen.state, "idle")
        self.assertEqual(h.home.voice.tune.state, "listening")
        h.call("/api/voice/tune", {"action": "cancel"})


# ------------------------------------------------------------------------------ the models


class TestTheModelsStep(unittest.TestCase):
    def test_it_names_what_the_session_will_use_and_whether_it_is_here(self):
        h = Pumped(self)
        with mock.patch("flow.home.models.complete", return_value=False):
            _c, page = h.call("/api/start", method="GET")
        m = page["model"]
        self.assertEqual((m["partial"]["name"], m["final"]["name"]), h.session.asr.names)
        self.assertFalse(m["ready"])
        self.assertEqual(m["alternative"]["final"], "small.en")

    def test_download_fetches_the_missing_models_without_pinning_them(self):
        h = Pumped(self)
        with mock.patch("flow.home.models.complete", return_value=False), \
                mock.patch.object(h.home.models.downloads, "start") as start:
            code, _page = h.call("/api/start/models", {"action": "download"})
        self.assertEqual(code, 200)
        self.assertEqual({c.args[0].name for c in start.call_args_list},
                         set(h.session.asr.names))
        self.assertTrue(h.home.warm_when_ready)
        # Nothing chosen on anybody's behalf: automatic stays automatic.
        self.assertIsNone(h.profile.final_model)
        self.assertEqual(h.session.asr.asked, (None, None))

    def test_the_session_is_warmed_when_the_last_one_lands(self):
        h = Pumped(self)
        h.home.warm_when_ready = True
        job = mock.Mock(then_use="", name="large-v3")
        with mock.patch("flow.home.models.complete", return_value=True):
            h.home._downloaded(job)
        wait_for(self, lambda: h.session.warmed == 1)
        self.assertFalse(h.home.warm_when_ready)

    def test_nothing_to_download_warms_now(self):
        h = Pumped(self)
        with mock.patch("flow.home.models.complete", return_value=True):
            h.call("/api/start/models", {"action": "download"})
        self.assertEqual(h.session.warmed, 1)

    def test_the_smaller_pair_is_a_choice_and_is_saved_as_one(self):
        h = Pumped(self)
        with mock.patch("flow.home.models.complete", return_value=True):
            code, _page = h.call("/api/start/models", {"action": "smaller"})
        self.assertEqual(code, 200)
        self.assertEqual(h.session.asr.asked, ("base.en", "small.en"))
        self.assertEqual(Profile(h.profile.path).final_model, "small.en")

    def test_an_unknown_action_is_refused(self):
        h = Pumped(self)
        self.assertEqual(h.call("/api/start/models", {"action": "everything"})[0], 400)


# ------------------------------------------------------------------------------ done


class TestItEndsOnce(unittest.TestCase):
    def test_done_is_remembered_and_stops_what_the_steps_left_listening(self):
        h = Pumped(self)
        h.call("/api/start/listen", {"action": "start"})
        code, _page = h.call("/api/start/done", {})
        self.assertEqual(code, 200)
        self.assertTrue(Profile(h.profile.path).welcomed)
        self.assertEqual(h.home.voice.listen.state, "idle")

    def test_the_rail_does_not_list_it(self):
        # Opened once, by the launch, and left for good.
        js = (Path(__file__).resolve().parent.parent / "flow" / "home" / "static"
              / "app.js").read_text(encoding="utf-8")
        nav = js[js.index("const NAV = ["):js.index("];", js.index("const NAV = ["))]
        self.assertNotIn('"start"', nav)
        self.assertIn('"start"', js[js.index("const PAGES"):js.index("\n", js.index("const PAGES"))])


# ------------------------------------------------------------------------------ the launch


class TestTheLaunchOpensIt(unittest.TestCase):
    """`main()` opens the first run for a profile that has not been through it, and
    does not start a silent download while that page is there to show one."""

    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)

    def launch(self, profile_text=None, ready=True):
        import flow.asr
        import flow.diag
        import flow.profile
        import flow.ui_compact

        import flow.__main__ as mod

        if profile_text is not None:
            (self.dir / "profile.json").write_text(profile_text, encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(flow.profile, "DEFAULT_PATH", self.dir / "profile.json"), \
                mock.patch.object(flow.diag, "Diag"), \
                mock.patch.object(mod, "Session") as session, \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui_compact, "CompactPill") as compact, \
                mock.patch.object(Home, "models_ready", return_value=ready), \
                contextlib.redirect_stdout(out):
            compact.return_value.switch_to = None
            code = mod.main(["--no-speak", "--no-lexicon"])
            # The warm decision is made on a thread; let it land before reading.
            deadline = time.time() + 3
            while time.time() < deadline and not (
                    session.return_value.post.called or "not on this PC yet" in out.getvalue()):
                time.sleep(0.02)
        self.assertEqual(code, 0)
        return out.getvalue(), session.return_value, compact.return_value

    def scheduled(self, pill) -> dict:
        return {c.args[0]: c.args[1] for c in pill.after.call_args_list
                if len(c.args) == 2 and callable(c.args[1])}

    def test_a_new_profile_opens_the_first_run(self):
        _out, _session, pill = self.launch()
        calls = self.scheduled(pill)
        self.assertIn(400, calls)
        with mock.patch.object(Home, "open", return_value="") as open_:
            calls[400]()
        open_.assert_called_once_with("start")

    def test_a_profile_that_has_been_through_it_does_not(self):
        _out, session, pill = self.launch('{"schema": 1, "welcomed": true}')
        self.assertNotIn(400, self.scheduled(pill))
        # And its model warm is the ordinary one, straight away.
        session.warm.assert_called_once_with()

    def test_models_already_here_are_warmed_through_the_session_thread(self):
        _out, session, _pill = self.launch(ready=True)
        session.post.assert_called_once_with(session.warm)
        session.warm.assert_not_called()

    def test_models_not_here_wait_for_the_step_that_shows_the_download(self):
        out, session, _pill = self.launch(ready=False)
        self.assertIn("models: not on this PC yet - the first run in Flow Home "
                      "downloads them, with progress", out)
        session.warm.assert_not_called()
        session.post.assert_not_called()

    def test_no_profile_has_no_first_run(self):
        import flow.asr
        import flow.diag
        import flow.ui_compact

        import flow.__main__ as mod

        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(flow.diag, "Diag"), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui_compact, "CompactPill") as compact, \
                contextlib.redirect_stdout(io.StringIO()):
            compact.return_value.switch_to = None
            mod.main(["--no-profile", "--no-speak", "--no-lexicon"])
        self.assertNotIn(400, self.scheduled(compact.return_value))


class TestHandsFreeIsSaidWhereTheKeysAlreadyAre(unittest.TestCase):
    """Item 4: the tap, and why it is onboarding's problem rather than a feature page's.

    Hands-free is the one thing Flow does that the thing it is compared against does not,
    and it was a footnote in the guide. These assertions are about the *page*, because
    discoverability is a property of where a sentence sits: a gesture described on the
    screen where somebody is already pressing its key is one variation on something their
    hands know, and the same sentence on its own page is a fifth skippable step nobody
    reads. The placement is the feature.
    """

    @staticmethod
    def page() -> str:
        return (Path(__file__).resolve().parent.parent / "flow" / "home" / "static"
                / "app.js").read_text(encoding="utf-8")

    def test_step_five_names_the_tap(self):
        page = self.page()
        self.assertIn("Prefer not to hold anything?", page)
        self.assertIn("keeps listening after you let go", page)

    def test_and_it_says_the_same_keys_dictate_when_held_longer(self):
        # The one chord, two depths. Describing the tap without saying what the hold still
        # does is how somebody ends up learning press-to-press and never learning that a
        # long press is how they always dictated - and silently losing a mode they used
        # every day. Both halves, or the sentence is misleading rather than incomplete.
        page = self.page()
        self.assertIn("`tap ${chord}`", page)
        self.assertIn("held a beat longer, dictate", page)

    def test_and_the_send_word_is_read_rather_than_assumed(self):
        # `send_word` is a profile setting with a tested preset list behind it. Onboarding
        # that hardcodes "send" teaches the wrong word to anyone who changed it.
        self.assertIn("(d.send && d.send.word) || \"send\"", self.page())

    def test_lite_is_told_to_tap_the_pill_because_it_has_no_hotkeys(self):
        # Under Lite there is no chord to name, so naming one would be a sentence about a
        # key this person does not have.
        self.assertIn('d.lite ? "tap the pill"', self.page())

    def test_the_api_sends_the_word_the_session_will_actually_hear(self):
        # The page reads `d.send.word`, so the payload has to carry it or the sentence
        # silently falls back to the shipped default - which is the bug this half exists
        # to prevent.
        api = (Path(__file__).resolve().parent.parent / "flow" / "home" / "api.py"
               ).read_text(encoding="utf-8")
        self.assertIn('"send": {"word": self._send_word()}', api)
        self.assertIn("def _send_word", api)

    def test_and_a_session_carrying_nothing_still_gets_the_shipped_word(self):
        # `--no-profile` and the demo both hand this a session without `send_words`. An
        # empty string in the sentence would read as "say nothing", so the fallback is the
        # word that is actually going to work - which is `boom`, not "send". Asserted
        # against the constant rather than a literal for the reason the rest of this file
        # asserts against constants: the shipped word is a decision that has changed once
        # already, and a test pinning the string would fail the next time it did.
        from flow.edits import SEND_WORD

        import flow.home.api as api_mod

        class Bare:
            session = object()
            home = type("H", (), {"lite": False})()
            profile = None

        self.assertEqual(api_mod.Api._send_word(Bare()), SEND_WORD)

    def test_and_a_session_that_does_carry_one_is_asked_not_assumed(self):
        # The reason the helper exists at all. A session built from a profile whose send
        # word was changed must have that word on the page, not the shipped default.
        from flow.home.api import Api

        class Custom:
            session = type("S", (), {"send_words": ("goose", "enter goose")})()
            home = type("H", (), {"lite": False})()
            profile = None

        self.assertEqual(Api._send_word(Custom()), "goose")


class TestTheColdStartHarnessCannotFlatterItself(unittest.TestCase):
    """Item 5. The stages must account for the total, and both failure modes are pinned.

    The harness's first run reported a total 2.7 s larger than the sum of its own stages.
    Two things could explain that, and the wrong one was reached for first — a missing
    stage — which is exactly the order a measurement goes wrong in when nobody checks the
    arithmetic. These tests check it on every run instead.
    """

    @staticmethod
    def module(name):
        return __import__(name, fromlist=["*"])

    def test_the_stage_names_are_the_ones_the_bench_measures(self):
        from flow import coldstart

        # A stage that exists here and not in `STAGES` is a stage nothing can report, and
        # one in `STAGES` that nothing sets is a column of `n/a` in the output forever.
        marks = {"import": 0.1, "device-resolve": 0.2, "model-load": 2.5, "ready": 2.8}
        self.assertEqual(set(coldstart.STAGES), set(marks))

    def test_ready_is_last_because_it_is_the_moment_the_first_word_can_come_out(self):
        from flow import coldstart

        self.assertEqual(coldstart.STAGES[-1], coldstart.STAGE_READY)

    def test_a_staged_run_adds_up_to_its_total(self):
        # The check that catches a double-count. 0.35 s of slack covers the gap between
        # one stage's stopwatch and the next one's start, which is real but small; the
        # double-count this exists to catch was 2.5 s.
        import time

        from flow import coldstart

        t0 = time.monotonic()
        marks = {coldstart.STAGE_IMPORT: coldstart.origin()}
        time.sleep(0.02)
        marks[coldstart.STAGE_RESOLVE] = time.monotonic() - t0
        time.sleep(0.02)
        before = time.monotonic()
        time.sleep(0.02)
        marks[coldstart.STAGE_MODEL] = time.monotonic() - before
        marks[coldstart.STAGE_READY] = coldstart.origin()

        parts = [marks[s] for s in coldstart.STAGES[:-1]]
        self.assertLess(abs(sum(parts) - marks[coldstart.STAGE_READY]), 0.35)

    def test_origin_is_a_real_number_on_this_platform(self):
        # It was None on Windows until the kernel32 signatures were declared — a 64-bit
        # HANDLE truncated into a signed 32-bit int. That failure was invisible: the
        # harness printed `n/a` for two of its three columns and carried on. So the
        # platform branch is asserted here rather than left to be discovered by a person
        # reading output on the one platform Flow ships on.
        from flow import coldstart

        got = coldstart.origin()

        if got is None:
            self.skipTest("this platform does not expose a process start time")
        self.assertGreater(got, 0.0)
        #: Not seconds since the epoch. 1.7e9 would sail past `assertGreater(got, 0)` and
        #: be a start time of 1970 read as elapsed.
        self.assertLess(got, 86_400.0, "that is a timestamp, not an elapsed time")

    def test_a_zero_start_time_is_refused_rather_than_reported_as_elapsed(self):
        # `GetProcessTimes` answers 0 for a process it cannot describe, and 0 minus the
        # 1601 epoch is a date in 1601 — about 1.3e11 seconds of nonsense that looks like
        # a plausible measurement. The sanity check is what stops it being published.
        from flow import coldstart

        k32 = mock.Mock()
        k32.GetProcessTimes.return_value = 0
        with mock.patch.object(coldstart, "_init_k32", return_value=k32), \
                mock.patch("sys.platform", "win32"):
            self.assertIsNone(coldstart._windows_start())

    def test_and_a_real_one_is_not_refused(self):
        # The other half of the same check, because refusing everything is also a bug —
        # and it is the half that fails loudly. A guard that only ever refuses would leave
        # the harness printing `n/a` on every machine forever, which is the invisible
        # failure this whole module exists to prevent.
        import time

        from flow import coldstart

        self.assertIsNone(coldstart.from_filetime(0),
                          "a failed API call is not a start time in the year 1601")
        #: Also refused: a start in the future, which a clock set backwards produces.
        future = int((time.time() + 3600.0 + 11644473600.0) * 1e7)
        self.assertIsNone(coldstart.from_filetime(future))

    def test_and_a_real_one_converts_rather_than_being_refused(self):
        # The other half of the same check, because refusing everything is also a bug —
        # and it is the half that fails loudly. A guard that only ever refuses would leave
        # the harness printing `n/a` on every machine forever, which is the invisible
        # failure this whole module exists to prevent.
        from flow import coldstart

        five_ago = int((time.time() - 5.0 + 11644473600.0) * 1e7)
        got = coldstart.from_filetime(five_ago)

        self.assertIsNotNone(got)
        self.assertLess(abs(got - time.time()), 30.0, "five seconds ago, give or take")

    def test_the_bench_prints_warm_as_warm_never_as_cold(self):
        # A warm number published as a cold one is how a 4 s first run becomes a 1.4 s
        # claim. The label is the whole defence, so it is asserted on the source rather
        # than trusted.
        source = (Path(__file__).resolve().parent.parent / "scripts" / "cold_start.py"
                  ).read_text(encoding="utf-8")

        self.assertIn("NOT the number a reboot gives", source)
        self.assertIn("warm", source)

    def test_and_the_guide_no_longer_quotes_the_unmeasured_number(self):
        # The old "~1.4 s" came from a run nobody could repeat, and it did not add up to
        # its own breakdown. It is replaced by a measured warm figure plus an explicit
        # "not yet measured" for the cold one, rather than being quietly deleted.
        guide = (Path(__file__).resolve().parent.parent / "docs" / "guide.md"
                 ).read_text(encoding="utf-8")

        # The old number is quoted inside the replacement row, because a reader who
        # remembers "~1.4 s" and finds it gone has no way to know it was wrong rather
        # than merely moved. Asserted absent as a *claim*, which is what "not yet
        # measured" makes it.
        self.assertNotIn("| Cold start ", guide)
        self.assertIn("not yet measured", guide)
        self.assertIn("cold_start.py", guide)


if __name__ == "__main__":
    unittest.main()
