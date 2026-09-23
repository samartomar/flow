"""Flow Home: the window for everything that isn't talking (decisions.md 2026-09-22).

What is pinned here, in the order a request meets it:

- the **server** answers only its own host, its own origin and its own token, serves a
  fixed list of files and nothing else, and closes a connection it refused;
- the **bridge** runs a call on the session's thread and hands back its answer, its
  exception, or `Busy` when the pill is not pumping;
- the **API** reads and changes what the pages show, through the demo's `FakeSession` —
  the same pretend session `python -m flow.home.demo` serves;
- the **session, transcriber, microphone and profile** hooks it needed: `post`, a live
  model swap that cannot hand a decode a dropped model, a microphone switch by name, and
  six settings that were flags;
- the **downloads** report bytes and stop when cancelled;
- the **window** is Edge in app mode with a profile of its own, or the browser.

Nothing here opens a window, touches the network, loads a model or reaches the real
`~/.flow`: every profile is in a temporary folder.
"""

import json
import queue
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import audio, stats  # noqa: E402
from flow.asr import WhisperTranscriber  # noqa: E402
from flow.home import Home  # noqa: E402
from flow.home import api as api_mod  # noqa: E402
from flow.home import models as models_mod  # noqa: E402
from flow.home import window as window_mod  # noqa: E402
from flow.home.bridge import Bridge, Busy  # noqa: E402
from flow.home.demo import FakeSession  # noqa: E402
from flow.home.server import FILES, HomeServer  # noqa: E402
from flow.profile import Profile  # noqa: E402
from flow.session import Session  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "flow" / "home" / "static"


class Pumped:
    """A FakeSession whose posted calls run on a thread of their own, as a pill's frames
    would run them — so the bridge really crosses a thread."""

    def __init__(self, test: unittest.TestCase) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="flow-home-test-"))
        self.profile = Profile(self.folder / "profile.json")
        self.session = FakeSession(self.profile)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        test.addCleanup(self._stop.set)
        self.home = Home(self.session, profile=self.profile, hotkeys=None, lite=False,
                         lexicon_path=self.folder / "lexicon.txt",
                         trace_path=self.folder / "diag.jsonl")
        self.home.design = "compact"
        test.addCleanup(self.home.close)

    def _pump(self) -> None:
        while not self._stop.is_set():
            self.session.run_posted()
            time.sleep(0.005)

    def call(self, method: str, path: str, body: dict | None = None):
        return self.home.api.handle(method, path, body or {})


# ------------------------------------------------------------------------------ server


class TestTheServerAnswersOnlyItsOwnWindow(unittest.TestCase):
    """Three checks in front of every API call, and a file list instead of a folder."""

    def setUp(self):
        self.calls = []

        def handle(method, path, body):
            self.calls.append((method, path, body))
            return 200, {"ok": True}

        self.server = HomeServer(handle)
        self.server.start()
        self.addCleanup(self.server.stop)

    def request(self, path, body=None, token=None, headers=None, ctype="application/json"):
        data = None if body is None else (body if isinstance(body, bytes)
                                          else json.dumps(body).encode())
        req = urllib.request.Request(self.server.origin + path, data=data,
                                     method="POST" if data is not None else "GET")
        req.add_header("X-Flow-Token", self.server.token if token is None else token)
        if data is not None and ctype:
            req.add_header("Content-Type", ctype)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def test_it_listens_on_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_the_right_token_reaches_the_api(self):
        status, _h, body = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})
        self.assertEqual(self.calls, [("GET", "/api/state", {})])

    def test_a_wrong_or_missing_token_is_refused_before_the_api(self):
        for token in ("", "nope", self.server.token + "x"):
            with self.subTest(token=token):
                status, _h, body = self.request("/api/state", token=token)
                self.assertEqual(status, 401)
                self.assertIn("open Flow Home again", json.loads(body)["error"])
        self.assertEqual(self.calls, [])

    def test_another_host_is_refused_which_is_what_stops_dns_rebinding(self):
        status, _h, _b = self.request("/api/state", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 421)
        self.assertEqual(self.calls, [])

    def test_another_origin_is_refused(self):
        status, _h, _b = self.request("/api/state",
                                      headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.calls, [])

    def test_a_post_must_be_a_json_object(self):
        for body, ctype in ((b"word=boom", "application/x-www-form-urlencoded"),
                            (b"[1, 2]", "application/json"),
                            (b"{nope", "application/json")):
            with self.subTest(ctype=ctype, body=body):
                status, headers, _b = self.request("/api/settings/send", body, ctype=ctype)
                self.assertEqual(status, 400)
                # A refusal may not have read the body it refused; the connection goes.
                self.assertEqual(headers.get("Connection"), "close")
        self.assertEqual(self.calls, [])

    def test_a_json_post_reaches_the_api_with_its_body(self):
        status, _h, _b = self.request("/api/settings/send", {"word": "tango"})
        self.assertEqual(status, 200)
        self.assertEqual(self.calls, [("POST", "/api/settings/send", {"word": "tango"})])

    def test_the_page_and_its_files_are_served_with_the_policy(self):
        for path in ("/", "/app.css", "/app.js", "/fonts/IBMPlexSans-Regular.ttf"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_nothing_outside_the_list_is_served(self):
        for path in ("/../flow/__main__.py", "/static/app.js", "/flow/profile.py",
                     "/%2e%2e/pyproject.toml", "/fonts/../app.js"):
            with self.subTest(path=path):
                status, _h, _b = self.request(path)
                self.assertEqual(status, 404)

    def test_connected_means_a_window_polled_recently(self):
        self.assertFalse(self.server.connected())
        self.request("/api/state")
        self.assertTrue(self.server.connected())

    def test_every_listed_file_exists(self):
        for path, (file, _ctype) in FILES.items():
            with self.subTest(path=path):
                self.assertTrue(file.is_file(), file)


class TestThePageWritesNoInlineStyleOrScript(unittest.TestCase):
    """The policy allows the page's own files and nothing inline. A `style="…"` in the
    markup would be dropped silently by the browser, which is the kind of failure that
    only shows up as a picture that looks slightly wrong."""

    def test_no_inline_style_attributes(self):
        for name in ("index.html", "app.js"):
            with self.subTest(name=name):
                self.assertNotIn('style="', (STATIC / name).read_text(encoding="utf-8"))

    def test_no_inline_script(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("<script"), 1)
        self.assertIn('<script src="/app.js" defer></script>', html)

    def test_the_token_is_sent_as_a_header_and_never_as_a_query(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('"X-Flow-Token": TOKEN', js)
        self.assertNotIn("?token=", js)


class TestAnAnswerIsDrawnOnlyOnThePageThatAsked(unittest.TestCase):
    """A voice change on Models, then a click on Settings before it answered, drew
    Settings from Models' payload: "Cannot read properties of undefined (reading
    'chosen')". Every action goes through `run`, so the rule is pinned there: the page
    is taken when the action starts, and its answer redraws only that page."""

    def test_run_remembers_the_page_and_checks_it_before_drawing(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        body = js[js.index("async function run(fn, done"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("const page = current();", body)
        self.assertIn("current() === page", body)
        self.assertIn("LOAD[page]", body)
        self.assertNotIn("LOAD[current()]", body)

    def test_an_acknowledgment_is_never_drawn_as_a_page(self):
        # "Open folder" (Settings, Models, Voice) and Preview answer `{"ok": True}`, and
        # drawn as the page that is a page with no microphone and no models — the
        # "reading 'chosen'" error on the owner's Settings page. Every route that answers
        # like that must be called with `run(..., false)`, which does not redraw.
        import ast
        import re

        api_src = (Path(__file__).resolve().parent.parent / "flow" / "home" / "api.py"
                   ).read_text(encoding="utf-8")
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        routes = dict(re.findall(r'\("POST", "/api/([^"]+)"\): self\.(\w+)', api_src))
        tree = ast.parse(api_src)
        acks = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in routes.values():
                for ret in ast.walk(node):
                    if (isinstance(ret, ast.Return) and isinstance(ret.value, ast.Dict)
                            and [getattr(k, "value", None) for k in ret.value.keys]
                            == ["ok"]):
                        acks.add(node.name)
        called = {route for route, name in routes.items() if name in acks}
        self.assertEqual(called, {"open", "replies/preview"})
        for route in called:
            with self.subTest(route=route):
                calls = re.findall(r'run\(\(\) => api\("%s"[^\n]*' % re.escape(route), js)
                self.assertTrue(calls, f"{route} is not called through run()")
                for call in calls:
                    self.assertTrue(call.rstrip(",").endswith("null, false)"), call)

    def test_every_other_redraw_is_already_guarded(self):
        # The page fetch and the poll both check the page after their await; `run` was
        # the one path that did not.
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("if (current() !== name) return;", js)
        self.assertIn("if (current() === name) { data = fresh; draw(name, false); }", js)


# ------------------------------------------------------------------------------ bridge


class TestTheBridge(unittest.TestCase):
    def test_the_call_runs_on_the_posting_thread_and_its_answer_comes_back(self):
        q = queue.SimpleQueue()
        where = []

        def pump():
            fn = q.get(timeout=2)
            where.append(threading.current_thread().name)
            fn()

        t = threading.Thread(target=pump, name="the-pill")
        t.start()
        self.assertEqual(Bridge(q.put).call(lambda: 42), 42)
        t.join()
        self.assertEqual(where, ["the-pill"])

    def test_its_exception_comes_back_too(self):
        def post(fn):
            fn()

        with self.assertRaises(ValueError):
            Bridge(post).call(lambda: (_ for _ in ()).throw(ValueError("no")))

    def test_a_pill_that_is_not_pumping_is_busy_not_a_hang(self):
        with self.assertRaises(Busy):
            Bridge(lambda fn: None).call(lambda: 1, timeout=0.05)


# ------------------------------------------------------------------------------ API


class TestTheLiveStrip(unittest.TestCase):
    def test_state_reads_the_session_through_the_bridge(self):
        h = Pumped(self)
        status, state = h.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["mode"], "dictate")
        self.assertEqual(state["mic"], "Yeti Nano")
        self.assertEqual(state["cli"], "claude")
        self.assertIsNone(state["navigate"])

    def test_a_page_to_move_to_is_handed_over_once(self):
        h = Pumped(self)
        h.home._navigate = "models"
        self.assertEqual(h.call("GET", "/api/state")[1]["navigate"], "models")
        self.assertIsNone(h.call("GET", "/api/state")[1]["navigate"])

    def test_an_unknown_route_is_404(self):
        h = Pumped(self)
        self.assertEqual(h.call("GET", "/api/nope")[0], 404)


class TestTheHomePage(unittest.TestCase):
    def test_it_lists_six_setup_steps_and_this_sessions_words(self):
        h = Pumped(self)
        status, page = h.call("GET", "/api/home")
        self.assertEqual(status, 200)
        self.assertEqual([s["id"] for s in page["setup"]],
                         ["mic", "model", "agent", "workspace", "voice", "words"])
        self.assertEqual({r["side"] for r in page["recent"]}, {"dictate", "ask"})

    def test_the_counts_come_from_this_sessions_files_and_not_the_home_folder(self):
        # The demo and the suite run over a profile in a temporary folder; reading the
        # stats from the defaults instead put the real ~/.flow's lifetime total on a
        # page about a pretend session.
        h = Pumped(self)
        with mock.patch.object(stats, "read", wraps=stats.read) as read:
            h.call("GET", "/api/home")
        _args, kwargs = read.call_args
        self.assertEqual(Path(kwargs["profile"]), h.profile.path)
        self.assertEqual(Path(kwargs["trace"]), h.folder / "diag.jsonl")

    def test_a_workspace_marks_its_step_done(self):
        h = Pumped(self)
        h.session.workspace = str(h.folder)
        step = {s["id"]: s for s in h.call("GET", "/api/home")[1]["setup"]}["workspace"]
        self.assertTrue(step["done"])
        self.assertEqual(step["detail"], str(h.folder))


class TestTheModelsPage(unittest.TestCase):
    def patched(self, installed=()):
        cached = {models_mod.BY_NAME[n].repo: 1_000_000 for n in installed}
        return (mock.patch.object(models_mod, "on_disk", return_value=cached),
                mock.patch.object(models_mod, "complete",
                                  side_effect=lambda repo: repo in cached),
                mock.patch.object(models_mod, "gpu", return_value={"name": "Test GPU",
                                                                   "memory_mb": 8192}),
                mock.patch.object(models_mod, "compute_types", return_value=["int8"]))

    def call(self, h, method, path, body=None, installed=("large-v3", "small")):
        patches = self.patched(installed)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return h.call(method, path, body)

    def test_every_catalog_model_is_a_row_with_the_one_in_use_marked(self):
        h = Pumped(self)
        status, page = self.call(h, "GET", "/api/models")
        self.assertEqual(status, 200)
        rows = {r["name"]: r for r in page["speech"]["models"]}
        self.assertEqual(set(rows), set(models_mod.BY_NAME))
        self.assertEqual(rows["large-v3"]["in_use"], ["final"])
        self.assertEqual(rows["small"]["in_use"], ["partial"])
        self.assertTrue(rows["large-v3"]["installed"])
        self.assertFalse(rows["medium.en"]["installed"])

    def test_the_numbers_say_where_they_were_measured(self):
        h = Pumped(self)
        page = self.call(h, "GET", "/api/models")[1]
        self.assertIn("GTX 1070", page["speech"]["measured_on"])
        rows = {r["name"]: r for r in page["speech"]["models"]}
        self.assertEqual(rows["large-v3"]["errors"], 16.8)
        self.assertTrue(rows["distil-large-v3.5"]["blind"])
        self.assertFalse(rows["large-v3"]["blind"])

    def test_choosing_models_that_are_here_swaps_them_now(self):
        h = Pumped(self)
        self.call(h, "POST", "/api/models/use",
                  {"partial": None, "final": "large-v3", "device": "auto"})
        self.assertEqual(h.session.asr.swaps[-1], (None, "large-v3", "auto"))
        self.assertEqual(h.profile.final_model, "large-v3")

    def test_a_model_that_is_not_here_downloads_first_and_waits(self):
        h = Pumped(self)
        with mock.patch.object(models_mod.Downloader, "start") as start:
            self.call(h, "POST", "/api/models/use",
                      {"partial": None, "final": "medium.en"})
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs.get("then_use"), "final")
        self.assertEqual(h.session.asr.swaps, [])
        self.assertEqual(h.home.pending_models, (None, "medium.en", None))

    def test_the_finished_download_is_used_then(self):
        h = Pumped(self)
        h.home.pending_models = (None, "medium.en", None)
        job = models_mod.Download("medium.en", state="done", then_use="final")
        with mock.patch.object(models_mod, "complete", return_value=True):
            h.home._downloaded(job)
        deadline = time.time() + 2
        while not h.session.asr.swaps and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(h.session.asr.swaps[-1], (None, "medium.en", None))
        self.assertIsNone(h.home.pending_models)

    def test_a_choice_that_applies_now_ends_one_still_waiting(self):
        # A model that had to download, then one that is here: the download's finish
        # must not swap back to the choice that was abandoned.
        h = Pumped(self)
        with mock.patch.object(models_mod.Downloader, "start"):
            self.call(h, "POST", "/api/models/use", {"partial": None, "final": "medium.en"})
        self.call(h, "POST", "/api/models/use",
                  {"partial": None, "final": "large-v3", "device": "auto"})
        self.assertIsNone(h.home.pending_models)
        job = models_mod.Download("medium.en", state="done", then_use="final")
        with mock.patch.object(models_mod, "complete", return_value=True), \
                mock.patch.object(h.session, "post") as post:
            h.home._downloaded(job)
        post.assert_not_called()
        self.assertEqual(h.session.asr.swaps[-1], (None, "large-v3", "auto"))

    def test_an_unknown_model_is_refused(self):
        h = Pumped(self)
        status, body = self.call(h, "POST", "/api/models/use", {"final": "gpt-4"})
        self.assertEqual(status, 400)
        self.assertIn("does not know", body["error"])

    def test_the_model_in_use_cannot_be_deleted(self):
        h = Pumped(self)
        with mock.patch.object(models_mod, "delete") as delete:
            status, body = self.call(h, "POST", "/api/models/delete", {"name": "large-v3"})
        self.assertEqual(status, 400)
        self.assertIn("in use", body["error"])
        delete.assert_not_called()

    def test_the_agent_settings_apply(self):
        h = Pumped(self)
        with mock.patch.object(api_mod, "available", return_value=[]):
            self.call(h, "POST", "/api/agent", {"effort": "high", "model": "gpt-5",
                                               "timeout": 45})
        self.assertEqual(h.session.cli_effort, "high")
        self.assertEqual(h.session.cli_model, "gpt-5")
        self.assertEqual(h.session.cli_timeout, 45)

    def test_a_cli_that_is_not_installed_cannot_be_pinned(self):
        h = Pumped(self)
        with mock.patch.object(api_mod, "available", return_value=[]):
            status, body = self.call(h, "POST", "/api/agent", {"cli": "codex"})
        self.assertEqual(status, 400)
        self.assertIn("not installed", body["error"])

    def test_the_reply_voice_and_mute(self):
        h = Pumped(self)
        self.call(h, "POST", "/api/replies", {"voice": "Microsoft Zira Desktop", "muted": True})
        self.assertEqual(h.session.speaker.voice, "Microsoft Zira Desktop")
        self.assertTrue(h.session.muted)
        status, body = self.call(h, "POST", "/api/replies", {"voice": "Nobody"})
        self.assertEqual(status, 400)


class TestTheSettingsPage(unittest.TestCase):
    def test_the_page_reads(self):
        h = Pumped(self)
        with mock.patch.object(audio, "input_devices",
                               return_value=[{"index": 1, "name": "Yeti Nano", "default": True}]):
            status, page = h.call("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(page["mic"]["devices"][0]["name"], "Yeti Nano")
        self.assertEqual(page["send"]["word"], "boom")
        self.assertEqual(page["design"]["current"], "compact")
        self.assertFalse(page["shortcuts"]["available"])

    def test_the_microphone_is_chosen_by_name(self):
        h = Pumped(self)
        with mock.patch.object(audio, "input_devices", return_value=[]):
            h.call("POST", "/api/settings/mic", {"name": "Headset"})
        self.assertEqual(h.session.mic.device_name, "Headset")
        self.assertEqual(h.profile.mic_device, "Headset")

    def test_only_a_tested_send_word_can_be_chosen(self):
        h = Pumped(self)
        with mock.patch.object(audio, "input_devices", return_value=[]):
            status, _ = h.call("POST", "/api/settings/send", {"word": "tango"})
            self.assertEqual(status, 200)
            self.assertEqual((h.profile.send_word, h.profile.send_enter_word),
                             ("tango", "enter tango"))
            status, body = h.call("POST", "/api/settings/send", {"word": "hello"})
        self.assertEqual(status, 400)
        self.assertIn("listed words", body["error"])

    def test_a_workspace_must_be_a_folder(self):
        h = Pumped(self)
        with mock.patch.object(audio, "input_devices", return_value=[]):
            status, _ = h.call("POST", "/api/settings/workspace/add", {"path": str(h.folder)})
            self.assertEqual(status, 200)
            self.assertEqual(h.session.workspace, str(h.folder))
            status, body = h.call("POST", "/api/settings/workspace/add",
                                  {"path": str(h.folder / "not-there")})
        self.assertEqual(status, 400)
        self.assertIn("not a folder", body["error"])

    def test_a_refused_switch_is_an_error_and_not_a_change(self):
        # An answer still in flight refuses the switch (`Session.set_workspace`), and
        # the page must not say "Workspace changed" about a project the next question
        # will not be grounded in.
        h = Pumped(self)
        with mock.patch.object(audio, "input_devices", return_value=[]), \
                mock.patch.object(h.session, "set_workspace", return_value=False):
            for route in ("/api/settings/workspace", "/api/settings/workspace/add"):
                with self.subTest(route=route):
                    status, body = h.call("POST", route, {"path": str(h.folder)})
                    self.assertEqual(status, 400)
                    self.assertIn("did not change", body["error"])

    def test_the_folder_it_is_already_in_is_not_a_refusal(self):
        h = Pumped(self)
        h.session.workspace = str(h.folder)
        with mock.patch.object(audio, "input_devices", return_value=[]), \
                mock.patch.object(h.session, "set_workspace", return_value=False):
            status, _body = h.call("POST", "/api/settings/workspace", {"path": str(h.folder)})
        self.assertEqual(status, 200)

    def test_a_forgotten_workspace_leaves_the_list(self):
        h = Pumped(self)
        h.profile.workspaces = [str(h.folder), "C:\\elsewhere"]
        with mock.patch.object(audio, "input_devices", return_value=[]):
            h.call("POST", "/api/settings/workspace/forget", {"path": str(h.folder)})
        self.assertEqual(h.profile.workspaces, ["C:\\elsewhere"])
        self.assertEqual(Profile(h.profile.path).workspaces, ["C:\\elsewhere"])

    def test_the_warm_start_and_the_per_app_instruction_are_saved(self):
        h = Pumped(self)
        with mock.patch.object(audio, "input_devices", return_value=[]):
            h.call("POST", "/api/settings/warm", {"on": False})
            h.call("POST", "/api/settings/apps", {"exe": "Slack.exe",
                                                   "instruction": "keep it to one line"})
        saved = Profile(h.profile.path)
        self.assertFalse(saved.warm)
        self.assertEqual(saved.apps, {"slack.exe": "keep it to one line"})

    def test_a_program_is_named_by_its_file(self):
        h = Pumped(self)
        status, _ = h.call("POST", "/api/settings/apps", {"exe": "C:\\x\\slack.exe",
                                                           "instruction": "x"})
        self.assertEqual(status, 400)

    @unittest.skipUnless(sys.platform == "win32", "the combo parser is Windows-only")
    def test_a_shortcut_is_checked_before_it_is_saved(self):
        h = Pumped(self)
        with mock.patch.object(audio, "input_devices", return_value=[]):
            status, body = h.call("POST", "/api/settings/hotkey",
                                  {"action": "toggle", "combo": "space"})
            self.assertEqual(status, 400)
            self.assertIn("space", body["error"])
            status, _ = h.call("POST", "/api/settings/hotkey",
                               {"action": "toggle", "combo": "ctrl+alt+j"})
        self.assertEqual(status, 200)
        self.assertEqual(Profile(h.profile.path).hotkeys, {"toggle": "ctrl+alt+j"})

    def test_a_design_switch_is_its_own_callback_on_the_pill(self):
        # It runs inside the pill's frame, and a switch takes that window down — so it
        # is scheduled like the menu row it replaces, never run inline.
        h = Pumped(self)
        surface = mock.Mock()
        h.home.surface = surface
        with mock.patch.object(audio, "input_devices", return_value=[]):
            h.call("POST", "/api/settings/design", {"name": "current"})
        surface.after.assert_called_once()
        surface.switch_design.assert_not_called()
        surface.after.call_args.args[1]()
        surface.switch_design.assert_called_once_with("current")

    def test_only_flows_own_folders_can_be_opened(self):
        h = Pumped(self)
        with mock.patch.object(api_mod, "reveal") as reveal:
            status, _ = h.call("POST", "/api/open", {"what": "settings"})
            self.assertEqual(status, 200)
            reveal.assert_called_once_with(h.profile.path.parent)
            status, _ = h.call("POST", "/api/open", {"what": "C:\\Windows"})
        self.assertEqual(status, 400)

    def test_no_profile_means_nothing_can_be_saved_and_it_says_so(self):
        h = Pumped(self)
        h.home.profile = None
        status, body = h.call("POST", "/api/settings/warm", {"on": False})
        self.assertEqual(status, 400)
        self.assertIn("--no-profile", body["error"])


# ------------------------------------------------------------------------------ Home


class TestOpeningTheWindow(unittest.TestCase):
    def test_the_first_open_starts_the_server_and_launches_a_window(self):
        h = Pumped(self)
        with mock.patch.object(window_mod, "launch", return_value=True) as launch:
            self.assertEqual(h.home.open("models"), "")
        url = launch.call_args.args[0]
        server = h.home.server()
        self.assertTrue(url.startswith(server.origin + "/#token="))
        self.assertIn(server.token, url)
        self.assertTrue(url.endswith("&page=models"))

    def test_an_open_window_is_brought_forward_and_moved_instead(self):
        h = Pumped(self)
        server = h.home.server()
        server.last_seen = time.monotonic()
        with mock.patch.object(window_mod, "focus", return_value=True), \
                mock.patch.object(window_mod, "launch") as launch:
            self.assertEqual(h.home.open("settings"), "")
        launch.assert_not_called()
        self.assertEqual(h.home.take_navigate(), "settings")

    def test_a_window_that_cannot_open_says_where_home_is(self):
        h = Pumped(self)
        with mock.patch.object(window_mod, "launch", return_value=False):
            why = h.home.open()
        self.assertIn(h.home.server().origin, why)

    def test_an_unknown_page_opens_home(self):
        h = Pumped(self)
        self.assertTrue(h.home.url("nowhere").endswith("&page=home"))


class TestTheWindowIsEdgeInAppMode(unittest.TestCase):
    def test_its_flags(self):
        args = window_mod.edge_args("msedge.exe", "http://127.0.0.1:1/#token=t&page=home")
        self.assertEqual(args[0], "msedge.exe")
        self.assertIn("--app=http://127.0.0.1:1/#token=t&page=home", args)
        self.assertIn(f"--user-data-dir={window_mod.PROFILE_DIR}", args)
        self.assertIn("--no-first-run", args)

    def test_it_keeps_a_profile_apart_from_the_persons_browsing(self):
        self.assertEqual(window_mod.PROFILE_DIR, Path.home() / ".flow" / "home")

    def test_no_edge_opens_the_browser_instead(self):
        with mock.patch.object(window_mod, "find_edge", return_value=None), \
                mock.patch.object(window_mod.webbrowser, "open", return_value=True) as open_:
            self.assertTrue(window_mod.launch("http://127.0.0.1:1/"))
        open_.assert_called_once_with("http://127.0.0.1:1/")


# ------------------------------------------------------------------------------ session


class TestTheSessionRunsWhatWasPosted(unittest.TestCase):
    def bare(self):
        s = Session.__new__(Session)
        s._posted = queue.SimpleQueue()
        return s

    def test_posted_calls_run_in_order_on_the_next_pump(self):
        s = self.bare()
        ran = []
        s.post(lambda: ran.append(1))
        s.post(lambda: ran.append(2))
        s._run_posted()
        self.assertEqual(ran, [1, 2])

    def test_one_failure_costs_that_call_not_the_frame(self):
        s = self.bare()
        ran = []
        s.post(lambda: 1 / 0)
        s.post(lambda: ran.append("after"))
        with mock.patch("traceback.print_exc"):
            s._run_posted()
        self.assertEqual(ran, ["after"])

    def test_pump_results_drains_them_first(self):
        s = self.bare()
        order = []
        s.post(lambda: order.append("posted"))
        for name in ("_pump_saves", "_pump_decodes", "_pump_drops", "_pump_refine",
                     "_pump_ask", "_pump_linger"):
            setattr(s, name, lambda n=name: order.append(n))
        s.pump_results()
        self.assertEqual(order[0], "posted")


class FakeAsr:
    def __init__(self):
        self.swapped = threading.Event()
        self.args = None

    def swap(self, partial, final, device=None):
        self.args = (partial, final, device)
        self.swapped.set()
        return True


class TestAModelSwapIsLive(unittest.TestCase):
    def session(self, asr):
        s = Session.__new__(Session)
        s.asr = asr
        s.profile = mock.Mock()
        s._events = __import__("collections").deque()
        s._warm = mock.Mock()
        return s

    def test_the_choice_is_saved_and_the_swap_runs_off_the_pills_thread(self):
        asr = FakeAsr()
        s = self.session(asr)
        self.assertTrue(s.set_models("small", "large-v3", "cuda"))
        self.assertTrue(asr.swapped.wait(2))
        self.assertEqual(asr.args, ("small", "large-v3", "cuda"))
        self.assertEqual((s.profile.partial_model, s.profile.final_model),
                         ("small", "large-v3"))
        s.profile.save.assert_called()
        deadline = time.time() + 2
        while not s._warm.called and time.time() < deadline:
            time.sleep(0.01)
        s._warm.assert_called_once()

    def test_an_engine_with_nothing_to_swap_says_so(self):
        s = self.session(object())
        self.assertFalse(s.set_models(None, "large-v3"))
        self.assertIn("no models", s._events[-1].text)


class TestTheTranscriberSwap(unittest.TestCase):
    def transcriber(self):
        t = WhisperTranscriber("base.en", "small.en", device="cpu")
        t._models = {False: "partial-model", True: "final-model"}
        t._built = {False: "base.en", True: "small.en"}
        return t

    def test_only_the_tier_that_changed_is_dropped(self):
        t = self.transcriber()
        self.assertTrue(t.swap("base.en", "large-v3"))
        self.assertEqual(t._models, {False: "partial-model", True: None})
        self.assertEqual(t.names, ("base.en", "large-v3"))
        self.assertEqual(t.asked, ("base.en", "large-v3"))

    def test_the_same_choice_changes_nothing(self):
        t = self.transcriber()
        self.assertFalse(t.swap("base.en", "small.en"))
        self.assertEqual(t._models, {False: "partial-model", True: "final-model"})

    def test_a_decode_never_gets_a_model_a_swap_just_dropped(self):
        # `load()` returns, a swap drops the tier, then the decode reads it: the lookup
        # loads again rather than handing `transcribe` a None.
        t = self.transcriber()
        calls = []

        def load(final=None):
            calls.append(final)
            if len(calls) == 1:
                t._models[True] = None  # the swap lands here
            else:
                t._models[True] = "rebuilt"
                t._built[True] = "large-v3"

        t.load = load
        self.assertEqual(t._model(True), ("rebuilt", "large-v3"))
        self.assertEqual(calls, [True, True])


class TestTheMicrophoneSwitch(unittest.TestCase):
    def session(self):
        s = Session.__new__(Session)
        s.mic = mock.Mock(device_name="Yeti Nano")
        s.mic.use.return_value = ""
        s.profile = mock.Mock(calibrated=False)
        s._events = __import__("collections").deque()
        s._noted_device = None
        s.speaker = None
        return s

    def test_it_switches_by_name_and_remembers(self):
        s = self.session()
        with mock.patch.object(Session, "talking", new_callable=mock.PropertyMock,
                               return_value=False):
            self.assertTrue(s.set_microphone("Headset"))
        s.mic.use.assert_called_once_with("Headset")
        self.assertEqual(s.profile.mic_device, "Headset")

    def test_not_while_a_reply_is_playing(self):
        # Switching refreshes PortAudio, which closes the stream the reply plays through.
        s = self.session()
        with mock.patch.object(Session, "talking", new_callable=mock.PropertyMock,
                               return_value=True):
            self.assertFalse(s.set_microphone("Headset"))
        s.mic.use.assert_not_called()

    def test_a_device_that_is_not_there_keeps_the_old_one(self):
        s = self.session()
        s.mic.use.return_value = "Headset is not connected"
        with mock.patch.object(Session, "talking", new_callable=mock.PropertyMock,
                               return_value=False):
            self.assertFalse(s.set_microphone("Headset"))
        self.assertNotEqual(s.profile.mic_device, "Headset")


class TestTheDeviceListShowsEachMicrophoneOnce(unittest.TestCase):
    DEVICES = [
        {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Yeti Nano (Blue)", "max_input_channels": 2, "hostapi": 0},
        {"name": "Speakers (Realtek)", "max_input_channels": 0, "hostapi": 0},
        {"name": "Yeti Nano (Blue Microphones)", "max_input_channels": 2, "hostapi": 1},
    ]

    def patched(self):
        sd = mock.Mock()
        sd.default.device = [1, 2]
        sd.query_devices.side_effect = lambda i=None: (
            self.DEVICES if i is None else self.DEVICES[i])
        return mock.patch.object(audio, "sd", sd)

    def test_one_host_api_real_inputs_only(self):
        # The Sound Mapper is MME's name for "the default", which the page already
        # offers as its first choice — a second row meaning the same thing is noise.
        with self.patched():
            names = [d["name"] for d in audio.input_devices()]
        self.assertEqual(names, ["Yeti Nano (Blue)"])

    def test_a_name_is_found_exactly_or_by_its_truncation(self):
        with self.patched():
            self.assertEqual(audio.find_input("Yeti Nano (Blue)"), 1)
            self.assertEqual(audio.find_input("Yeti Nano (Blue) Microphone Array"), 1)
            self.assertIsNone(audio.find_input("Headset"))
            self.assertIsNone(audio.find_input(""))


class TestAChosenMicrophoneIsFoundByNameAgain(unittest.TestCase):
    """A choice made by name stays a pin — Flow never records through another
    microphone on its own — but a pin by *index* goes stale when devices come and go,
    so a named one is looked up again before every reopen."""

    def quiet(self):
        return (mock.patch.object(audio.Mic, "refresh"),
                mock.patch.object(audio.Mic, "start"),
                mock.patch.object(audio.Mic, "stop"))

    def test_use_remembers_the_name_and_the_default_forgets_it(self):
        mic = audio.Mic()
        a, b, c = self.quiet()
        with a, b, c, mock.patch.object(audio, "find_input", return_value=3):
            self.assertEqual(mic.use("Headset"), "")
            self.assertEqual((mic.pinned, mic.want), (3, "Headset"))
            self.assertEqual(mic.use(None), "")
        self.assertEqual((mic.pinned, mic.want), (None, None))

    def test_a_name_that_is_not_connected_changes_nothing(self):
        mic = audio.Mic(device=1)
        a, b, c = self.quiet()
        with a, b, c, mock.patch.object(audio, "find_input", return_value=None):
            self.assertIn("not connected", mic.use("Headset"))
        self.assertEqual((mic.pinned, mic.want), (1, None))

    def opening(self):
        """`start` for real, with PortAudio's stream faked: what the open was asked for."""
        return (mock.patch.object(audio.Mic, "refresh"),
                mock.patch.object(audio.Mic, "stop"),
                mock.patch.object(audio, "sd"))

    def test_a_reopen_finds_it_at_its_new_index(self):
        mic = audio.Mic(device=1)
        mic.want = "Yeti Nano (Blue)"
        a, b, c = self.opening()
        with a, b, c as sd, mock.patch.object(audio, "find_input", return_value=4):
            mic.restart()
        self.assertEqual(mic.pinned, 4)
        self.assertEqual(sd.InputStream.call_args.kwargs["device"], 4)

    def test_a_reopen_while_it_is_gone_opens_nothing(self):
        # After a device comes and goes its old index can belong to a different
        # microphone, and opening it would be recording through something nobody
        # chose. Refused instead, so the session's retry asks again until it is back.
        mic = audio.Mic(device=1)
        mic.want = "Yeti Nano (Blue)"
        a, b, c = self.opening()
        with a, b, c as sd, mock.patch.object(audio, "find_input", return_value=None):
            with self.assertRaises(audio.NotConnected) as raised:
                mic.restart()
        sd.InputStream.assert_not_called()
        self.assertIn("Yeti Nano (Blue) is not connected", str(raised.exception))
        self.assertEqual(mic.pinned, 1)

    def test_an_arm_opens_it_by_name_too(self):
        # Arming opens without a restart, and a headset plugged in since the choice
        # renumbers the list just the same.
        mic = audio.Mic(device=1)
        mic.want = "Yeti Nano (Blue)"
        with mock.patch.object(audio, "sd") as sd, \
                mock.patch.object(audio, "find_input", return_value=5):
            mic.start()
        self.assertEqual(sd.InputStream.call_args.kwargs["device"], 5)

    def test_a_default_mic_is_not_looked_up(self):
        mic = audio.Mic(device=None)
        with mock.patch.object(audio, "sd") as sd, \
                mock.patch.object(audio, "find_input") as find:
            mic.start()
        find.assert_not_called()
        self.assertIsNone(sd.InputStream.call_args.kwargs["device"])


class TestProfileKeepsWhatFlagsUsedTo(unittest.TestCase):
    def test_the_new_fields_round_trip(self):
        folder = Path(tempfile.mkdtemp())
        p = Profile(folder / "profile.json")
        p.partial_model, p.final_model = "small", "large-v3"
        p.decode_device, p.mic_device = "cuda", "Yeti Nano"
        p.cli_timeout, p.warm = 45.0, False
        self.assertTrue(p.save())
        q = Profile(folder / "profile.json")
        self.assertEqual((q.partial_model, q.final_model, q.decode_device, q.mic_device,
                          q.cli_timeout, q.warm),
                         ("small", "large-v3", "cuda", "Yeti Nano", 45.0, False))
        self.assertEqual(q.faults, [])

    def test_an_older_profile_launches_as_it_always_did(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "profile.json").write_text(json.dumps({"schema": 1}), encoding="utf-8")
        q = Profile(folder / "profile.json")
        self.assertEqual((q.partial_model, q.final_model, q.decode_device, q.mic_device,
                          q.cli_timeout, q.warm),
                         (None, None, "auto", None, None, True))

    def test_nonsense_degrades_and_is_named(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "profile.json").write_text(json.dumps(
            {"schema": 1, "decode_device": "tpu", "cli_timeout": -5}), encoding="utf-8")
        q = Profile(folder / "profile.json")
        self.assertEqual((q.decode_device, q.cli_timeout), ("auto", None))
        self.assertIn("decode_device", q.faults)
        self.assertIn("cli_timeout", q.faults)


# ------------------------------------------------------------------------------ downloads


class TestDownloadsReportBytesAndStop(unittest.TestCase):
    def test_the_snapshot_bytes_bar_is_what_is_counted(self):
        job = models_mod.Download("large-v3")
        bar_cls = models_mod._progress_class(job)
        bytes_bar = bar_cls(desc="Reconstructing (incomplete total...)", total=0, unit="B")
        bytes_bar.total = 1000
        bytes_bar.update(250)
        bytes_bar.update(250)
        wire = bar_cls(desc="Downloading bytes", total=0, unit="B")
        wire.update(999)  # the wire's count is not the snapshot's
        files = bar_cls(desc="Fetching 5 files", total=5)
        files.update(2)
        self.assertEqual((job.done, job.total), (500, 1000))
        self.assertEqual((job.files_done, job.files_total), (2, 5))

    def test_cancel_raises_inside_the_download(self):
        job = models_mod.Download("large-v3", cancel=threading.Event())
        bar = models_mod._progress_class(job)(desc="Reconstructing", total=10, unit="B")
        job.cancel.set()
        with self.assertRaises(models_mod.Cancelled):
            bar.update(1)

    def test_a_run_that_finishes_calls_back_and_one_that_fails_says_why(self):
        done = []
        d = models_mod.Downloader(on_done=done.append)
        spec = models_mod.BY_NAME["base.en"]
        with mock.patch("huggingface_hub.snapshot_download") as snap:
            job = d.start(spec, then_use="partial")
            deadline = time.time() + 2
            while job.state == "running" and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(job.state, "done")
        self.assertEqual(done, [job])
        self.assertEqual(snap.call_args.kwargs["allow_patterns"], models_mod.ALLOW_PATTERNS)

        with mock.patch("huggingface_hub.snapshot_download",
                        side_effect=OSError("Max retries exceeded (network unreachable)")):
            job = d.start(models_mod.BY_NAME["small.en"])
            deadline = time.time() + 2
            while job.state == "running" and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(job.state, "failed")
        self.assertIn("huggingface.co", job.error)

    def test_a_second_start_joins_the_running_download(self):
        d = models_mod.Downloader()
        gate = threading.Event()
        with mock.patch("huggingface_hub.snapshot_download",
                        side_effect=lambda *a, **k: gate.wait(2)):
            first = d.start(models_mod.BY_NAME["base.en"])
            second = d.start(models_mod.BY_NAME["base.en"], then_use="final")
            self.assertIs(first, second)
            self.assertEqual(second.then_use, "final")
            gate.set()

    def test_sizes_read_the_way_a_download_is_read(self):
        self.assertEqual(models_mod.human(2970 * 1024 * 1024), "2.9 GB")
        self.assertEqual(models_mod.human(464 * 1024 * 1024), "464 MB")


if __name__ == "__main__":
    unittest.main()
