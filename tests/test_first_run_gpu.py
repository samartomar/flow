"""The first run's model step on a PC with a GPU, and what a cancelled background fetch means.

`--engine auto` starts Parakeet's GPU build downloading in the background on a first run
with a GPU backend (decisions.md 2026-10-05). The first run's model step must then show that
build - not a Whisper pair that would be fetched as well - and the download it shows is the
job the background fetch started. A cancel of that download is a "no" and is remembered; a
failure is not and is not.

A fake cache and a pretend session, as in `test_whisper_catalog.py`: no network, no model.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_home import Pumped  # noqa: E402

from flow import parakeet  # noqa: E402
from flow.__main__ import _gpu_auto  # noqa: E402
from flow.home import models as models_mod  # noqa: E402

GPU = models_mod.PARAKEET_GPU


class _Case(unittest.TestCase):
    def setUp(self):
        self.h = Pumped(self)
        self.disk: dict[str, int] = {}
        self.present = {"gpu": False}
        patches = (
            mock.patch.object(models_mod, "on_disk", side_effect=lambda: dict(self.disk)),
            mock.patch.object(models_mod, "complete", side_effect=lambda repo: repo in self.disk),
            mock.patch.object(models_mod, "gpu", return_value={"name": "GTX 1070",
                                                               "memory_mb": 8192}),
            mock.patch.object(models_mod, "compute_types", return_value=[]),
            mock.patch.object(parakeet, "runtime_installed", return_value=(True, "")),
            mock.patch.object(parakeet, "gpu_backend", return_value=("cuda", "")),
            mock.patch.object(parakeet, "model_present",
                              side_effect=lambda key, model_dir=None: self.present.get(key, False)),
            mock.patch.object(parakeet, "installed_bytes", return_value=0),
            mock.patch.object(parakeet, "legacy_bytes", return_value=0),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def step(self):
        return self.h.call("GET", "/api/start")[1]["model"]

    def job(self, state="running", then_use="engine", error=""):
        job = models_mod.Download(GPU.name, state=state, done=GPU.size // 2, total=GPU.size,
                                  then_use=then_use, error=error, cancel=mock.Mock())
        job.cancel.is_set.return_value = False
        self.h.home.models.downloads._jobs[GPU.name] = job
        return job


class TestTheStepShowsTheGpuBuild(_Case):
    def test_it_is_one_parakeet_line_with_its_size_and_the_backends_speed(self):
        self.h.home.gpu_auto = "fetch"
        m = self.step()
        self.assertTrue(m["single"])
        self.assertEqual(m["final"]["name"], GPU.name)
        self.assertEqual(m["final"], m["partial"])
        self.assertEqual(m["final"]["size_text"], models_mod.human(parakeet.download_size("gpu")))
        self.assertEqual(m["final"]["speed"], round(1 / models_mod.GPU_RTF["cuda"], 1))
        self.assertEqual(m["device"], "cuda")
        self.assertFalse(m["ready"])
        self.assertFalse(m["downloading"])

    def test_it_shows_the_background_fetchs_own_job_and_starts_no_second(self):
        self.h.home.gpu_auto = "fetch"
        job = self.job()
        with mock.patch.object(models_mod.Downloader, "start") as start:
            m = self.step()
            self.h.call("GET", "/api/start")
        start.assert_not_called()
        self.assertTrue(m["downloading"])
        self.assertEqual(m["final"]["download"]["done"], job.done)
        self.assertEqual(m["final"]["download"]["total"], GPU.size)

    def test_pressing_download_reuses_the_running_job(self):
        self.h.home.gpu_auto = "fetch"
        job = self.job()
        with mock.patch("threading.Thread") as thread:
            self.h.call("POST", "/api/start/models", {"action": "download"})
        thread.assert_not_called()  # `Downloader.start` returned the running job
        self.assertIs(self.h.home.models.downloads.jobs()[GPU.name], job)

    def test_download_with_nothing_running_starts_the_gpu_build_to_switch_when_it_lands(self):
        self.h.home.gpu_auto = "fetch"
        with mock.patch.object(models_mod.Downloader, "start") as start:
            self.h.call("POST", "/api/start/models", {"action": "download"})
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0].name, GPU.name)
        self.assertEqual(start.call_args.kwargs.get("then_use"), "engine")
        self.assertFalse(self.h.home.warm_when_ready)  # Whisper's warm-up is not its business

    def test_installed_is_ready_and_loaded_means_parakeet_is_the_engine(self):
        self.h.home.gpu_auto = "use"
        self.present["gpu"] = True
        m = self.step()
        self.assertTrue(m["ready"])
        self.assertFalse(m["loaded"])  # the pretend session is on Whisper
        self.h.session.set_engine("parakeet", "gpu")
        self.assertTrue(self.step()["loaded"])

    def test_the_smaller_alternative_is_the_cpu_whisper_pair_as_today(self):
        self.h.home.gpu_auto = "fetch"
        alt = self.step()["alternative"]
        self.assertEqual((alt["partial"], alt["final"]), ("base.en", "small.en"))
        self.assertEqual(alt["size_text"], models_mod.human(
            models_mod.BY_NAME["base.en"].size + models_mod.BY_NAME["small.en"].size))

    def test_choosing_the_smaller_pair_declines_parakeet_and_gives_whisper_its_step_back(self):
        self.h.home.gpu_auto = "fetch"
        job = self.job()
        self.h.call("POST", "/api/start/models", {"action": "smaller"})
        job.cancel.set.assert_called_once()
        self.assertEqual(self.h.profile.engine, "whisper")
        self.assertNotIn("single", self.step())


class TestWhisperOnlyMachinesRenderAsBefore(_Case):
    def test_no_gpu_path_means_the_original_step_exactly(self):
        # `gpu_auto` is "" off the GPU path: the payload is Whisper's pair, with none of the
        # keys the GPU step adds.
        self.assertEqual(self.h.home.gpu_auto, "")
        m = self.step()
        self.assertEqual(set(m), {"partial", "final", "ready", "downloading", "loaded",
                                  "loading", "device", "gpu", "measured_on", "alternative"})
        self.assertEqual((m["partial"]["name"], m["final"]["name"]), ("small", "large-v3"))
        self.assertEqual(m["device"], "cuda")  # the session's device, not a backend

    def test_a_saved_whisper_choice_is_whispers_step_even_on_the_gpu_path(self):
        self.h.home.gpu_auto = "fetch"
        self.h.profile.engine = "whisper"
        self.assertNotIn("single", self.step())

    def test_the_page_script_keeps_the_two_line_form_for_whisper(self):
        from test_home import STATIC

        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('modelLine(m.final, "writes the words that get pasted")', js)
        self.assertIn('modelLine(m.partial, "draws the live preview")', js)
        self.assertIn("m.single ?", js)


class TestMainSaysWhichPathThisLaunchIsOn(unittest.TestCase):
    def test_gpu_auto_is_the_one_answer_main_and_the_page_share(self):
        args = mock.Mock(engine="auto")
        with mock.patch.object(parakeet, "gpu_backend", return_value=("cuda", "")), \
                mock.patch.object(parakeet, "model_present", return_value=False):
            self.assertEqual(_gpu_auto(args, "", None, False), "fetch")
            self.assertEqual(_gpu_auto(args, "whisper", None, False), "")
        with mock.patch.object(parakeet, "gpu_backend", return_value=("cuda", "")), \
                mock.patch.object(parakeet, "model_present", return_value=True):
            self.assertEqual(_gpu_auto(args, "", None, False), "use")
        source = (Path(__file__).resolve().parent.parent / "flow" / "__main__.py").read_text(
            encoding="utf-8")
        self.assertIn("home.gpu_auto = _gpu_auto(", source)


class TestACancelIsANoAndAFailureIsNot(_Case):
    def test_cancelling_the_background_fetch_saves_whisper_so_auto_stops_fetching(self):
        self.h.home.gpu_auto = "fetch"
        self.job()
        self.h.call("POST", "/api/models/cancel", {"name": GPU.name})
        self.assertEqual(self.h.profile.engine, "whisper")
        # Saved to disk, and `auto` at the next launch reads it as a choice.
        from flow.profile import Profile

        saved = Profile(self.h.profile.path).engine
        self.assertEqual(saved, "whisper")
        args = mock.Mock(engine="auto")
        self.assertEqual(_gpu_auto(args, saved, None, False), "")

    def test_cancelling_from_the_first_run_step_is_the_same_no(self):
        self.h.home.gpu_auto = "fetch"
        self.job()
        self.h.call("POST", "/api/start/models", {"action": "cancel"})
        self.assertEqual(self.h.profile.engine, "whisper")

    def test_the_models_page_still_offers_download_and_use_afterwards(self):
        self.h.home.gpu_auto = "fetch"
        self.job()
        self.h.call("POST", "/api/models/cancel", {"name": GPU.name})
        rows = {r["name"]: r for r in self.h.call("GET", "/api/models")[1]["speech"]["models"]}
        self.assertFalse(rows[GPU.name]["installed"])
        self.assertEqual(rows[GPU.name]["blocked"], "")
        with mock.patch.object(models_mod.Downloader, "start") as start:
            status, _ = self.h.call("POST", "/api/models/engine",
                                    {"engine": "parakeet", "variant": "gpu"})
        self.assertEqual(status, 200)
        self.assertEqual(start.call_args.kwargs.get("then_use"), "engine")

    def test_a_saved_choice_is_not_overwritten_by_a_cancel(self):
        self.h.profile.engine = "parakeet"
        self.job()
        self.h.call("POST", "/api/models/cancel", {"name": GPU.name})
        self.assertEqual(self.h.profile.engine, "parakeet")

    def test_a_cancel_of_a_download_that_was_not_waiting_to_switch_says_nothing(self):
        self.job(then_use="")
        self.h.call("POST", "/api/models/cancel", {"name": GPU.name})
        self.assertEqual(self.h.profile.engine, "")

    def test_a_cancel_with_nothing_running_saves_nothing(self):
        self.h.call("POST", "/api/models/cancel", {"name": GPU.name})
        self.assertEqual(self.h.profile.engine, "")

    def test_a_failure_saves_nothing_so_the_next_launch_retries_once(self):
        self.h.home.gpu_auto = "fetch"
        self.job(state="failed", error="could not reach huggingface.co")
        sp = self.h.call("GET", "/api/models")[1]["speech"]
        self.assertEqual(sp["switch"]["state"], "failed")  # the reason is in the strip
        self.assertIn("could not reach huggingface.co", sp["switch"]["reason"])
        self.assertEqual(self.h.profile.engine, "")
        args = mock.Mock(engine="auto")
        self.assertEqual(_gpu_auto(args, self.h.profile.engine, None, False), "fetch")

    def test_nothing_restarts_a_failed_fetch_within_the_launch(self):
        # Polling the page, opening the first run, or reading the strip never starts a
        # download: only `_background_gpu_fetch` (once, from `main`) and a press do.
        self.h.home.gpu_auto = "fetch"
        self.job(state="failed", error="disk full")
        with mock.patch.object(models_mod.Downloader, "start") as start:
            for path in ("/api/models", "/api/start", "/api/state"):
                self.h.call("GET", path)
        start.assert_not_called()
        source = (Path(__file__).resolve().parent.parent / "flow" / "__main__.py").read_text(
            encoding="utf-8")
        self.assertEqual(source.count("    _background_gpu_fetch(home,"), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
