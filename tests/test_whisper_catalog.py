"""The trimmed Whisper catalog (decisions.md 2026-10-05): what stayed, what left and why it still
works, and the offer to remove what left.

Parakeet on the GPU is the primary engine, so Whisper keeps four rows - `large-v3` and `small`
(the GPU pair, multilingual) and `small.en` and `base.en` (the CPU pair) - and the other five
are `RETIRED`: not offered, never downloaded, but still runnable by name, still shown when a
profile or a flag names one, and removable from disk only when somebody presses the button.

Driven through the same pretend session as `test_home_engine.py`; a fake cache stands in for
Hugging Face's, so nothing here touches the network, a model or the real `~/.cache`.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_home import STATIC, Pumped  # noqa: E402

from flow import asr, parakeet  # noqa: E402
from flow.home import models as models_mod  # noqa: E402
# Bound now, before `_Case` patches the module's own name for it.
from flow.home.models import delete as real_delete  # noqa: E402

KEPT = ("large-v3", "small.en", "small", "base.en")
RETIRED = ("large-v2", "distil-large-v3.5", "large-v3-turbo", "distil-large-v3", "medium.en")
GB = 1024 ** 3


class _Case(unittest.TestCase):
    def setUp(self):
        self.h = Pumped(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        #: {repo id: bytes} - what the fake cache holds.
        self.disk: dict[str, int] = {}
        self.deleted: list[str] = []

        def fake_delete(repo):
            self.deleted.append(repo)
            return self.disk.pop(repo, None) is not None

        patches = (
            mock.patch.object(models_mod, "on_disk", side_effect=lambda: dict(self.disk)),
            mock.patch.object(models_mod, "complete", side_effect=lambda repo: repo in self.disk),
            mock.patch.object(models_mod, "delete", side_effect=fake_delete),
            mock.patch.object(models_mod, "gpu", return_value=None),
            mock.patch.object(models_mod, "compute_types", return_value=[]),
            mock.patch.object(parakeet, "runtime_installed", return_value=(True, "")),
            mock.patch.object(parakeet, "model_present", return_value=False),
            mock.patch.object(parakeet, "installed_bytes", return_value=0),
            mock.patch.object(parakeet, "legacy_bytes", return_value=0),
            mock.patch.object(parakeet, "gpu_backend", return_value=("cuda", "")),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def have(self, *names):
        for name in names:
            spec = models_mod.BY_NAME.get(name) or models_mod.BY_RETIRED[name]
            self.disk[spec.repo] = spec.size
        self.h.home.models.forget_scan()

    def page(self):
        self.h.home.models.forget_scan()
        return self.h.call("GET", "/api/models")[1]["speech"]

    def rows(self):
        return {r["name"]: r for r in self.page()["models"]}


class TestTheCatalogContents(_Case):
    def test_whisper_keeps_the_gpu_pair_and_the_cpu_pair_and_nothing_else(self):
        self.assertEqual(tuple(s.name for s in models_mod.CATALOG), KEPT)
        # The pairs `asr.default_models` hands out are all still rows.
        for device in ("cuda", "cpu"):
            for name in asr.default_models(device):
                self.assertIn(name, models_mod.BY_NAME)
        self.assertEqual(asr.CUDA_PARTIAL_MODEL, "small")

    def test_the_five_that_left_are_retired_and_never_a_row_or_a_choice(self):
        self.assertEqual(tuple(s.name for s in models_mod.RETIRED), RETIRED)
        for name in RETIRED:
            self.assertNotIn(name, models_mod.BY_NAME)
            self.assertNotIn(name, models_mod.SPECS)
            self.assertNotIn(name, self.rows())

    def test_the_page_lists_the_kept_whisper_rows_and_parakeets(self):
        self.assertEqual(set(self.rows()),
                         set(KEPT) | {s.name for s in models_mod.PARAKEET_SPECS})

    def test_the_blind_badge_left_with_the_models_that_carried_it(self):
        self.assertFalse(hasattr(models_mod.Spec("x", "y", 1), "blind"))
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("blind", js)
        self.assertNotIn("invents words in silence", js)

    def test_a_model_named_by_a_flag_still_works_and_keeps_its_silence_guard(self):
        # `--final-model medium.en` and friends: the transcriber takes any faster-whisper
        # name, and `reports_no_speech` still knows which families lose the silence signal.
        t = asr.WhisperTranscriber("small", "distil-large-v3.5", device="cpu")
        self.assertEqual(t.names, ("small", "distil-large-v3.5"))
        self.assertTrue(asr.WhisperTranscriber("base.en", "medium.en", device="cpu").names[1]
                        == "medium.en")
        for name in ("distil-large-v3.5", "distil-large-v3", "large-v3-turbo"):
            self.assertFalse(asr.reports_no_speech(name), name)
        for name in KEPT + ("large-v2", "medium.en"):
            self.assertTrue(asr.reports_no_speech(name), name)

    def test_the_cache_total_still_counts_what_left_the_list(self):
        self.have("large-v3", "medium.en")
        want = models_mod.BY_NAME["large-v3"].size + models_mod.BY_RETIRED["medium.en"].size
        self.assertEqual(self.page()["cache"]["bytes"], want)


class TestHindi(_Case):
    """The multilingual models write Hindi and Hinglish as English; Parakeet cannot hear it."""

    def test_the_code_really_translates_to_english(self):
        # What the large-v3 note claims: the task is translate and the language is pinned
        # to English, so Hindi audio comes out as English text on a multilingual model.
        self.assertEqual(asr.TASK, "translate")
        source = Path(asr.__file__).read_text(encoding="utf-8")
        self.assertIn('"language": "en"', source)
        self.assertIn('"task": TASK', source)

    def test_the_large_v3_row_says_it_plainly(self):
        note = self.rows()["large-v3"]["note"]
        self.assertIn("Hindi", note)
        self.assertIn("Hinglish", note)
        self.assertIn("writes English", note)
        self.assertIn("Parakeet cannot", note)

    def test_small_is_multilingual_too_and_the_english_only_ones_do_not_claim_it(self):
        rows = self.rows()
        self.assertIn("Hindi", rows["small"]["note"])
        for name in ("small.en", "base.en"):
            self.assertNotIn("Hindi", rows[name]["note"])

    def test_the_parakeet_explanation_says_hindi_needs_whisper(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("25 European languages and not Hindi", js)
        self.assertIn("for Hindi or Hinglish, choose Whisper", js)


class TestParakeetLeads(_Case):
    def test_the_engine_control_is_parakeet_then_whisper(self):
        engines = self.page()["engines"]
        self.assertEqual([e["id"] for e in engines], ["parakeet", "whisper"])
        self.assertEqual([e["label"] + " " + e["maker"] for e in engines],
                         ["Parakeet NVIDIA", "Whisper OpenAI"])

    def test_the_page_draws_the_buttons_in_the_servers_order(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("${engines.map((e) =>", js)
        # No client-side reordering that would put Whisper back in front.
        self.assertNotIn("engines.sort", js)
        self.assertNotIn("engines.reverse", js)

    def test_the_intro_copy_leads_with_parakeet(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        start = js.index('<h2 class="grow">Speech recognition</h2>')
        intro = js[start:start + 1500]
        self.assertLess(intro.index("Parakeet from NVIDIA"), intro.index("Whisper from OpenAI"))


class TestAModelThatLeftTheListIsStillShown(_Case):
    """A profile or a flag can name a model Flow stopped listing: it is the model in use and
    the page says so, instead of crashing or calling it something it is not."""

    def choose(self, partial, final):
        self.h.session.asr.swap(partial, final)

    def test_it_is_a_row_with_what_it_was_measured_at_and_a_note_that_it_left(self):
        self.have("medium.en", "small")
        self.choose("small", "medium.en")
        row = self.rows()["medium.en"]
        self.assertFalse(row["catalog"])
        self.assertEqual(row["in_use"], ["final"])
        self.assertTrue(row["installed"])
        self.assertEqual(row["errors"], 18.3)
        self.assertEqual(row["size"], models_mod.BY_RETIRED["medium.en"].size)
        self.assertIn("no longer listed", row["note"])
        self.assertNotIn("silence", row["note"])  # medium.en has the silence signal

    def test_one_with_no_silence_signal_says_what_that_costs(self):
        self.have("distil-large-v3.5")
        self.choose(None, "distil-large-v3.5")
        row = self.rows()["distil-large-v3.5"]
        self.assertIn("no longer listed", row["note"])
        self.assertIn("invents words in silence", row["note"])

    def test_one_flow_never_listed_keeps_its_old_wording(self):
        self.choose(None, "someone/else-whisper")
        row = self.rows()["someone/else-whisper"]
        self.assertEqual(row["note"], "chosen outside Flow Home")
        self.assertEqual(row["errors"], None)

    def test_the_dropdown_shows_it_as_chosen_and_not_as_automatic(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("no longer listed</option>", js)
        self.assertIn(".concat(outside(chosen))", js)

    def test_use_these_is_not_refused_for_it_when_it_is_on_this_pc(self):
        self.have("medium.en", "large-v3")
        self.choose(None, "medium.en")
        status, _ = self.h.call("POST", "/api/models/use",
                                {"partial": None, "final": "medium.en", "device": "auto"})
        self.assertEqual(status, 200)
        self.assertEqual(self.h.session.asr.swaps[-1], (None, "medium.en", "auto"))

    def test_and_a_retired_model_that_is_not_here_is_unknown_not_a_download(self):
        with mock.patch.object(models_mod.Downloader, "start") as start:
            status, body = self.h.call("POST", "/api/models/use",
                                       {"partial": None, "final": "medium.en"})
        self.assertEqual(status, 400)
        self.assertIn("does not know", body["error"])
        start.assert_not_called()

    def test_a_finished_download_for_the_other_tier_still_swaps_with_it(self):
        # `Home._downloaded` read `BY_NAME[name]` for both tiers: a retired name KeyErrored.
        self.have("medium.en")
        self.h.home.pending_models = ("small.en", "medium.en", None)
        self.disk[models_mod.BY_NAME["small.en"].repo] = 1
        job = models_mod.Download("small.en", state="done", then_use="partial")
        self.h.home._downloaded(job)
        import time

        deadline = time.time() + 2
        while not self.h.session.asr.swaps and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.h.session.asr.swaps[-1], ("small.en", "medium.en", None))


class TestTheOfferToRemoveWhatLeft(_Case):
    def test_nothing_on_disk_means_no_offer(self):
        self.have("large-v3")
        self.assertEqual(self.page()["unlisted"], {"names": [], "bytes": 0, "text": "0 MB"})

    def test_it_names_the_retired_models_that_are_here_and_what_they_weigh(self):
        self.have("large-v3", "large-v2", "medium.en", "distil-large-v3")
        un = self.page()["unlisted"]
        # In the order they left the list, never the catalog's.
        self.assertEqual(un["names"], ["large-v2", "distil-large-v3", "medium.en"])
        want = sum(models_mod.BY_RETIRED[n].size for n in un["names"])
        self.assertEqual(un["bytes"], want)
        self.assertEqual(un["text"], models_mod.human(want))

    def test_a_model_in_use_or_named_by_the_profile_is_not_offered(self):
        self.have("small", "large-v2", "medium.en", "large-v3-turbo")
        self.h.session.asr.swap("small", "large-v2")           # running now
        self.h.profile.partial_model = "large-v3-turbo"          # what a switch back would load
        self.assertEqual(self.page()["unlisted"]["names"], ["medium.en"])

    def test_pressing_it_removes_exactly_those_through_the_ordinary_delete(self):
        self.have("large-v3", "small.en", "large-v2", "distil-large-v3.5", "medium.en")
        status, body = self.h.call("POST", "/api/models/delete", {"name": "unlisted-whisper"})
        self.assertEqual(status, 200)
        self.assertEqual(self.deleted, [models_mod.BY_RETIRED[n].repo
                                        for n in ("large-v2", "distil-large-v3.5", "medium.en")])
        # What stayed is untouched, and the offer is gone from the payload that came back.
        self.assertIn(models_mod.BY_NAME["large-v3"].repo, self.disk)
        self.assertIn(models_mod.BY_NAME["small.en"].repo, self.disk)
        self.assertEqual(body["speech"]["unlisted"]["names"], [])

    def test_pressing_it_with_nothing_to_remove_is_an_error_not_a_silent_success(self):
        self.have("large-v3")
        status, body = self.h.call("POST", "/api/models/delete", {"name": "unlisted-whisper"})
        self.assertEqual(status, 400)
        self.assertIn("no unlisted", body["error"])
        self.assertEqual(self.deleted, [])

    def test_the_model_in_use_survives_the_press(self):
        self.have("small", "large-v2", "medium.en")
        self.h.session.asr.swap("small", "large-v2")
        self.h.call("POST", "/api/models/delete", {"name": "unlisted-whisper"})
        self.assertEqual(self.deleted, [models_mod.BY_RETIRED["medium.en"].repo])
        self.assertIn(models_mod.BY_RETIRED["large-v2"].repo, self.disk)

    def test_nothing_deletes_on_its_own(self):
        # Reading the page, however often, removes nothing.
        self.have("large-v2", "medium.en")
        for _ in range(3):
            self.page()
        self.assertEqual(self.deleted, [])

    def test_it_goes_through_the_real_cache_delete_by_repo(self):
        # `models.delete` against a fake `scan_cache_dir`: the revisions of the one repo,
        # and no other, are handed to huggingface_hub's own delete strategy.
        executed = []
        strategy = SimpleNamespace(execute=lambda: executed.append(True))
        revs = {}

        def delete_revisions(*hashes):
            revs["hashes"] = hashes
            return strategy

        repos = [SimpleNamespace(repo_id="Systran/faster-whisper-medium.en",
                                 revisions=[SimpleNamespace(commit_hash="aaa")]),
                 SimpleNamespace(repo_id="Systran/faster-whisper-large-v3",
                                 revisions=[SimpleNamespace(commit_hash="bbb")])]
        fake = SimpleNamespace(repos=repos, delete_revisions=delete_revisions)
        with mock.patch("huggingface_hub.scan_cache_dir", return_value=fake):
            self.assertTrue(real_delete("Systran/faster-whisper-medium.en"))
        self.assertEqual(revs["hashes"], ("aaa",))
        self.assertEqual(executed, [True])

    def test_the_page_offers_it_only_on_the_whisper_tab_and_asks_first(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('engine !== "parakeet" && sp.unlisted && sp.unlisted.names.length', js)
        self.assertIn('data-act="unlisted-delete"', js)
        self.assertIn("no longer lists", js)
        block = js[js.index('"unlisted-delete": (el) => {'):]
        self.assertLess(block.index("confirm("), block.index('"unlisted-whisper"'))


class TestAFailedBackgroundDownloadIsInTheStrip(_Case):
    """The first-run download that was only there to switch engines, and did not finish."""

    def fail(self, then_use="engine", error="could not reach huggingface.co"):
        spec = models_mod.PARAKEET_GPU
        job = models_mod.Download(spec.name, state="failed", error=error, then_use=then_use)
        self.h.home.models.downloads._jobs[spec.name] = job
        return job

    def test_the_strip_says_why_and_that_flow_is_still_on_what_it_had(self):
        self.fail()
        sw = self.page()["switch"]
        self.assertEqual((sw["state"], sw["engine"], sw["variant"]),
                         ("failed", "parakeet", "gpu"))
        self.assertIn("could not reach huggingface.co", sw["reason"])
        self.assertIn("still on the engine it had", sw["reason"])
        self.assertEqual(self.page()["engine"], "whisper")

    def test_a_failed_download_that_was_not_for_a_switch_is_not_in_the_strip(self):
        self.fail(then_use="")
        self.assertIsNone(self.page()["switch"])

    def test_choosing_whisper_clears_it(self):
        self.fail()
        status, body = self.h.call("POST", "/api/models/engine", {"engine": "whisper"})
        self.assertEqual(status, 200)
        self.assertIsNone(body["speech"]["switch"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
