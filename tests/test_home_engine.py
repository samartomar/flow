"""Flow Home's engine control: choosing Whisper or Parakeet on the Models page.

Driven through `FakeSession`, the same pretend session `python -m flow.home.demo` serves,
so what is asserted is the page's contract with the API: the payload (engines, availability
and the reason, the Parakeet row and the basis its speed was measured on), the switch
and its refusals, and the row's download, cancel and delete through the same manager the
Whisper rows use. `Session.set_engine` itself is `test_engine_switch.py`.

Nothing here touches the network, a model, or the real `~/.flow`.
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_home import STATIC, Pumped  # noqa: E402

from flow import parakeet  # noqa: E402
from flow.home import models as models_mod  # noqa: E402

PK = "parakeet-tdt-0.6b-v3"
PK8 = "parakeet-tdt-0.6b-v3-int8"


class _Case(unittest.TestCase):
    def setUp(self):
        self.h = Pumped(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Which Parakeet builds are on disk: both, unless a test says otherwise.
        self.state = {"runtime": (True, ""), "model": True, "fp32": True, "int8": True}
        patches = (
            mock.patch.object(parakeet, "runtime_installed",
                              side_effect=lambda: self.state["runtime"]),
            mock.patch.object(parakeet, "model_present",
                              side_effect=lambda key, model_dir=None:
                              self.state["model"] and self.state[key]),
            mock.patch.object(models_mod, "on_disk", return_value={}),
            mock.patch.object(models_mod, "complete", return_value=False),
            mock.patch.object(models_mod, "gpu", return_value=None),
            mock.patch.object(models_mod, "compute_types", return_value=[]),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def page(self):
        return self.h.call("GET", "/api/models")[1]["speech"]

    def post(self, engine):
        return self.h.call("POST", "/api/models/engine", {"engine": engine})

    def wait(self, until, timeout=2.0):
        deadline = time.time() + timeout
        while not until() and time.time() < deadline:
            time.sleep(0.01)
        return until()


class TestThePayload(_Case):
    def test_it_lists_the_engines_and_which_one_is_running(self):
        sp = self.page()
        self.assertEqual(sp["engine"], "whisper")
        self.assertTrue(sp["engine_switchable"])
        engines = {e["id"]: e for e in sp["engines"]}
        self.assertEqual(list(engines), ["whisper", "parakeet"])
        self.assertEqual((engines["whisper"]["label"], engines["whisper"]["maker"]),
                         ("Whisper", "OpenAI"))
        self.assertEqual((engines["parakeet"]["label"], engines["parakeet"]["maker"]),
                         ("Parakeet", "NVIDIA"))
        self.assertTrue(engines["parakeet"]["available"])
        self.assertEqual(engines["parakeet"]["threads"], parakeet.default_threads())

    def test_without_the_runtime_parakeet_is_unavailable_and_says_how_to_get_it(self):
        self.state["runtime"] = (False, "no")
        entry = {e["id"]: e for e in self.page()["engines"]}["parakeet"]
        self.assertFalse(entry["available"])
        self.assertIn("Parakeet add-on", entry["why"])
        self.assertIn('uv pip install -e ".[parakeet]"', entry["why"])

    def test_the_parakeet_row_is_measured_and_labelled_on_the_cpu(self):
        rows = {r["name"]: r for r in self.page()["models"]}
        row = rows[PK]
        self.assertEqual(row["engine"], "parakeet")
        self.assertEqual((row["maker"], row["family"]), ("NVIDIA", "Parakeet"))
        self.assertEqual(row["errors"], 14.7)
        self.assertEqual(row["speed"], 14.7)  # 1 / 0.068, measured on the CPU
        # Never mislabelled as the GTX 1070 the other rows were measured on.
        self.assertEqual(row["speed_basis"], "CPU")
        self.assertFalse(row["blind"])
        self.assertEqual(row["size"], parakeet.VARIANTS["fp32"].bytes)  # the download, until here
        self.assertEqual({n for n, r in rows.items() if r["speed_basis"]}, {PK, PK8})
        self.assertEqual(rows["large-v3"]["family"], "Whisper")

    def test_a_row_whose_runtime_is_missing_is_not_offered_for_download(self):
        self.assertEqual({r["name"]: r for r in self.page()["models"]}[PK]["blocked"], "")
        self.state["runtime"] = (False, "no")
        rows = {r["name"]: r for r in self.page()["models"]}
        self.assertIn("Parakeet add-on", rows[PK]["blocked"])
        self.assertTrue(all(r["blocked"] == "" for n, r in rows.items() if n not in (PK, PK8)))

    def test_an_installed_parakeet_reports_its_size_on_disk(self):
        with mock.patch.object(parakeet, "installed_bytes", return_value=670_000_000):
            row = {r["name"]: r for r in self.page()["models"]}[PK]
        self.assertTrue(row["installed"])
        self.assertEqual(row["size"], 670_000_000)

    def test_parakeet_is_never_a_whisper_tier_choice(self):
        self.assertNotIn(PK, models_mod.BY_NAME)
        status, _body = self.h.call("POST", "/api/models/use", {"final": PK})
        self.assertEqual(status, 400)
        self.assertEqual(self.h.session.asr.swaps, [])

    def test_the_page_script_keeps_it_out_of_the_tier_dropdowns(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('m.catalog && m.engine === "whisper"', js)
        self.assertIn('data-act="engine"', js)
        # The speed is never shown without the basis it was measured on.
        self.assertIn("m.speed_basis", js)


class TestSwitching(_Case):
    def test_choosing_parakeet_switches_and_remembers_it(self):
        status, body = self.post("parakeet")
        self.assertEqual(status, 200)
        self.assertEqual(body["speech"]["engine"], "parakeet")
        self.assertEqual(self.h.profile.engine, "parakeet")
        rows = {r["name"]: r for r in body["speech"]["models"]}
        self.assertEqual(rows[PK]["in_use"], ["partial", "final"])
        self.assertEqual(rows["large-v3"]["in_use"], [])
        self.assertFalse(body["speech"]["swappable"])  # one model: nothing to choose

    def test_and_back_to_whisper(self):
        self.post("parakeet")
        _status, body = self.post("whisper")
        self.assertEqual(body["speech"]["engine"], "whisper")
        self.assertEqual(self.h.profile.engine, "whisper")
        self.assertTrue(body["speech"]["swappable"])

    def test_a_missing_runtime_is_an_error_with_the_fix_and_nothing_changes(self):
        self.state["runtime"] = (False, "no")
        status, body = self.post("parakeet")
        self.assertEqual(status, 400)
        self.assertIn("Parakeet add-on", body["error"])
        self.assertEqual(self.h.session.engine, "whisper")

    def test_a_missing_model_downloads_first_and_switches_when_it_lands(self):
        self.state["model"] = False
        with mock.patch.object(models_mod.Downloader, "start") as start:
            status, _body = self.post("parakeet")
        self.assertEqual(status, 200)
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0].name, PK)
        self.assertEqual(start.call_args.kwargs.get("then_use"), "engine")
        self.assertEqual(self.h.session.engine, "whisper")  # not silently switched

        self.state["model"] = True
        job = models_mod.Download(PK, state="done", then_use="engine")
        self.h.home._downloaded(job)
        self.assertTrue(self.wait(lambda: self.h.session.engine == "parakeet"))

    def test_choosing_whisper_ends_a_download_that_was_waiting_to_switch(self):
        job = models_mod.Download(PK, then_use="engine")
        with mock.patch.object(models_mod.Downloader, "jobs", return_value={PK: job}):
            self.post("whisper")
        self.assertEqual(job.then_use, "")

    def test_a_refusal_from_the_session_is_the_pages_error(self):
        self.h.session.engine_refusal = lambda name, variant=None: "stop listening first"
        status, body = self.post("parakeet")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "stop listening first")
        self.assertEqual(self.h.session.engine, "whisper")

    def test_an_unknown_engine_is_refused(self):
        self.assertEqual(self.post("deepgram")[0], 400)

    def test_the_route_answers_a_page_and_not_an_acknowledgement(self):
        # test_home pins that only `open` and `replies/preview` answer `{"ok": True}`.
        status, body = self.post("whisper")
        self.assertEqual(status, 200)
        self.assertIn("speech", body)


class TestTheRestOfThePage(_Case):
    def test_the_rails_footer_and_the_home_row_name_parakeet(self):
        self.post("parakeet")
        state = self.h.call("GET", "/api/state")[1]
        self.assertEqual(state["engine"], "parakeet")
        self.assertIsNone(state["models"])  # no tier names, so the page names the engine
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("ENGINE_WORD[live.engine]", js)
        home = self.h.call("GET", "/api/home")[1]
        step = next(s for s in home["setup"] if s["id"] == "model")
        self.assertEqual(step["detail"], "Parakeet, on the CPU")  # not ", on the CPU"

    def test_an_engine_with_no_device_is_named_without_one(self):
        self.h.session.asr = SimpleNamespace(engine="native", loaded=True, loading=False)
        home = self.h.call("GET", "/api/home")[1]
        step = next(s for s in home["setup"] if s["id"] == "model")
        self.assertEqual(step["detail"], "Apple speech")


class TestTheRowsDownloadCancelAndDelete(_Case):
    def test_it_downloads_with_real_progress_through_the_same_manager(self):
        done = []
        d = models_mod.Downloader(on_done=done.append)

        def fake_fetch(key, progress=None, cancelled=None, **_kw):
            progress(10, 100)
            progress(60, 100)

        with mock.patch.object(parakeet, "fetch", side_effect=fake_fetch):
            job = d.start(models_mod.PARAKEET, then_use="engine")
            self.wait(lambda: job.state != "running")
        self.assertEqual(job.state, "done")
        self.assertEqual(done, [job])
        self.assertEqual(job.then_use, "engine")
        self.assertEqual((job.done, job.total), (100, 100))

    def test_progress_reaches_the_page_while_it_runs(self):
        gate = threading.Event()

        def slow_fetch(key, progress=None, cancelled=None, **_kw):
            progress(25, 100)
            gate.wait(2)

        self.state["model"] = False
        with mock.patch.object(parakeet, "fetch", side_effect=slow_fetch):
            self.h.call("POST", "/api/models/download", {"name": PK})
            row = {}

            def moving():
                nonlocal row
                row = {r["name"]: r for r in self.page()["models"]}[PK]
                return bool(row["download"] and row["download"]["done"])

            self.assertTrue(self.wait(moving))
            self.assertEqual(row["download"]["state"], "running")
            self.assertEqual((row["download"]["done"], row["download"]["total"]), (25, 100))
            gate.set()

    def test_cancelling_stops_the_fetch_through_its_cancel_hook(self):
        d = models_mod.Downloader()
        started = threading.Event()

        def cancellable_fetch(key, progress=None, cancelled=None, **_kw):
            started.set()
            self.wait(cancelled)
            if cancelled():
                raise parakeet.Cancelled()

        with mock.patch.object(parakeet, "fetch", side_effect=cancellable_fetch):
            job = d.start(models_mod.PARAKEET)
            self.assertTrue(started.wait(2))
            self.assertTrue(d.cancel(PK))
            self.wait(lambda: job.state != "running")
        self.assertEqual(job.state, "cancelled")

    def test_a_failed_fetch_says_why_in_its_own_words(self):
        d = models_mod.Downloader()
        with mock.patch.object(parakeet, "fetch",
                               side_effect=parakeet.NotAvailable("download failed: offline")):
            job = d.start(models_mod.PARAKEET)
            self.wait(lambda: job.state != "running")
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error, "download failed: offline")

    def test_deleting_it_removes_the_model_folder(self):
        root = Path(self.tmp.name)
        folder = root / "parakeet-tdt-0.6b-v3"
        other = root / "parakeet-tdt-0.6b-v3-int8"
        for d in (folder, other):
            d.mkdir()
            (d / "vocab.txt").write_text("x", encoding="utf-8")
        with mock.patch.object(parakeet, "MODELS_DIR", root):
            status, _ = self.h.call("POST", "/api/models/delete", {"name": PK})
        self.assertEqual(status, 200)
        self.assertFalse(folder.exists())
        self.assertTrue(other.exists())  # only the one named

    def test_the_one_in_use_cannot_be_deleted(self):
        self.post("parakeet")
        status, body = self.h.call("POST", "/api/models/delete", {"name": PK})
        self.assertEqual(status, 400)
        self.assertIn("in use", body["error"])


class TestTheTwoBuilds(_Case):
    """Accurate (fp32) and Light (int8): two rows, one engine, a choice that is remembered."""

    def test_both_builds_are_rows_with_their_own_measurements_and_the_cpu_basis(self):
        rows = {r["name"]: r for r in self.page()["models"]}
        accurate, light = rows[PK], rows[PK8]
        self.assertEqual((accurate["variant"], light["variant"]), ("fp32", "int8"))
        self.assertEqual((accurate["errors"], light["errors"]), (14.7, 16.9))
        self.assertEqual(accurate["speed_basis"], "CPU")
        self.assertEqual(light["speed_basis"], "CPU")
        self.assertFalse(accurate["blind"] or light["blind"])
        self.assertEqual(accurate["size"], parakeet.VARIANTS["fp32"].bytes)
        self.assertEqual(light["size"], parakeet.VARIANTS["int8"].bytes)
        self.assertLess(light["size"], accurate["size"])
        self.assertNotIn(PK8, models_mod.BY_NAME)  # still never a Whisper tier

    def test_neither_build_is_in_the_whisper_dropdowns_or_chosen_as_a_tier(self):
        for name in (PK, PK8):
            status, _ = self.h.call("POST", "/api/models/use", {"final": name})
            self.assertEqual(status, 400)

    def test_the_engine_lists_its_builds_and_which_is_chosen(self):
        entry = {e["id"]: e for e in self.page()["engines"]}["parakeet"]
        self.assertEqual(entry["variant"], "fp32")
        self.assertEqual([(v["key"], v["label"], v["installed"]) for v in entry["variants"]],
                         [("fp32", "Accurate", True), ("int8", "Light", True)])

    def test_a_downloaded_build_switches_and_is_remembered(self):
        status, body = self.h.call("POST", "/api/models/engine",
                                   {"engine": "parakeet", "variant": "int8"})
        self.assertEqual(status, 200)
        sp = body["speech"]
        self.assertEqual(sp["engine"], "parakeet")
        rows = {r["name"]: r for r in sp["models"]}
        self.assertEqual(rows[PK8]["in_use"], ["partial", "final"])
        self.assertEqual(rows[PK]["in_use"], [])
        self.assertEqual({e["id"]: e for e in sp["engines"]}["parakeet"]["variant"], "int8")
        self.assertEqual(self.h.profile.parakeet_model, "int8")

    def test_the_other_build_switches_live_through_the_same_route(self):
        self.h.call("POST", "/api/models/engine", {"engine": "parakeet", "variant": "int8"})
        _status, body = self.h.call("POST", "/api/models/engine",
                                    {"engine": "parakeet", "variant": "fp32"})
        rows = {r["name"]: r for r in body["speech"]["models"]}
        self.assertEqual(rows[PK]["in_use"], ["partial", "final"])
        self.assertEqual(self.h.profile.parakeet_model, "fp32")

    def test_a_build_that_is_not_here_downloads_first_and_switches_to_that_build(self):
        self.state["int8"] = False
        with mock.patch.object(models_mod.Downloader, "start") as start:
            status, _ = self.h.call("POST", "/api/models/engine",
                                    {"engine": "parakeet", "variant": "int8"})
        self.assertEqual(status, 200)
        self.assertEqual(start.call_args.args[0].name, PK8)
        self.assertEqual(start.call_args.kwargs.get("then_use"), "engine")
        self.assertEqual(self.h.session.engine, "whisper")

        self.state["int8"] = True
        self.h.home._downloaded(models_mod.Download(PK8, state="done", then_use="engine"))
        deadline = time.time() + 2
        while self.h.session.engine_variant != "int8" and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.h.session.engine_variant, "int8")

    def test_choosing_the_other_build_ends_a_download_waiting_to_switch(self):
        waiting = models_mod.Download(PK8, then_use="engine")
        self.state["fp32"] = False
        with mock.patch.object(models_mod.Downloader, "jobs", return_value={PK8: waiting}), \
                mock.patch.object(models_mod.Downloader, "start"):
            self.h.call("POST", "/api/models/engine",
                        {"engine": "parakeet", "variant": "fp32"})
        self.assertEqual(waiting.then_use, "")

    def test_an_unknown_build_is_refused(self):
        status, body = self.h.call("POST", "/api/models/engine",
                                   {"engine": "parakeet", "variant": "fp16"})
        self.assertEqual(status, 400)
        self.assertIn("fp32", body["error"])

    def test_each_row_downloads_and_deletes_its_own_build(self):
        got = []
        with mock.patch.object(parakeet, "fetch",
                               side_effect=lambda key, **kw: got.append(key)):
            self.h.call("POST", "/api/models/download", {"name": PK8})
            self.assertTrue(self.wait(lambda: got))
        self.assertEqual(got, ["int8"])

    def test_the_footer_names_parakeet_whichever_build(self):
        self.h.call("POST", "/api/models/engine", {"engine": "parakeet", "variant": "int8"})
        self.assertEqual(self.h.call("GET", "/api/state")[1]["engine"], "parakeet")


class TestTheOldSherpaFiles(_Case):
    def old(self):
        root = Path(self.tmp.name)
        folder = root / parakeet.LEGACY_NAME
        folder.mkdir()
        (folder / "encoder.int8.onnx").write_bytes(b"x" * 50)
        return root, folder

    def test_the_page_reports_them_without_touching_them(self):
        root, folder = self.old()
        with mock.patch.object(parakeet, "MODELS_DIR", root):
            cache = self.page()["cache"]
        self.assertEqual(cache["legacy_bytes"], 50)
        self.assertTrue(folder.exists())

    def test_there_is_nothing_to_offer_when_there_are_none(self):
        with mock.patch.object(parakeet, "MODELS_DIR", Path(self.tmp.name)):
            self.assertEqual(self.page()["cache"]["legacy_bytes"], 0)

    def test_removing_them_is_an_explicit_request(self):
        root, folder = self.old()
        with mock.patch.object(parakeet, "MODELS_DIR", root):
            status, _ = self.h.call("POST", "/api/models/delete",
                                    {"name": "sherpa-onnx-legacy"})
            self.assertEqual(status, 200)
            self.assertFalse(folder.exists())
            status, body = self.h.call("POST", "/api/models/delete",
                                       {"name": "sherpa-onnx-legacy"})
        self.assertEqual(status, 400)
        self.assertIn("not on this PC", body["error"])

    def test_the_page_script_offers_it(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("legacy-delete", js)
        self.assertIn("sherpa-onnx-legacy", js)


class TestOpenFolder(_Case):
    def test_it_opens_parakeets_own_folder_when_asked_for_it(self):
        opened = []
        with mock.patch.object(parakeet, "MODELS_DIR", Path(self.tmp.name) / "m"), \
                mock.patch("flow.home.api.reveal", opened.append):
            status, _ = self.h.call("POST", "/api/open", {"what": "parakeet"})
        self.assertEqual(status, 200)
        self.assertEqual(opened, [Path(self.tmp.name) / "m"])

    def test_the_page_asks_for_the_folder_of_the_engine_in_use(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-what="${engine === "parakeet" ? "parakeet" : "models"}"', js)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
