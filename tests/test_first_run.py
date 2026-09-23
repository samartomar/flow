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


if __name__ == "__main__":
    unittest.main()
