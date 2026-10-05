"""The Parakeet engine: an opt-in decoder, and the rules that keep it opt-in.

Nothing here needs the model, the network or the `[parakeet]` extra. `onnx_asr` and
`onnxruntime` are fakes put into `sys.modules`, the variants are shrunk to a few bytes, and
the download goes through `file://` URLs, so what is asserted is Flow's side of each
contract:

  **Importing it costs nothing, and a default install never breaks on it.** The real
  packages are imported inside `load()` and nowhere else.

  **`auto` never picks it on its own.** It is a different engine with real costs (an extra,
  a model of 640 MB or 2.4 GB, one tier, no hotword biasing, a hallucination gate that rests
  on three measured examples), so choosing it is the user's act. A *saved* choice is the
  user's act too, and the flag beats it.

  **A refusal says why, and names the fallback** — the same as `--engine native`.

  **A download is verified and atomic.** Every file is checked against its size and, where
  the hub publishes one, its SHA-256; the directory appears all at once or not at all; and
  a cancel leaves what a failure does.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.parakeet as parakeet  # noqa: E402
from flow.__main__ import _engine  # noqa: E402
from flow.asr import Drop  # noqa: E402


class _Result:
    def __init__(self, text, logprobs):
        self.text = text
        self.logprobs = logprobs


class _Adapter:
    def __init__(self):
        self.heard = []
        self.answer = _Result("hello world", [-0.1, -0.2])
        self.timestamped = False

    def with_timestamps(self):
        self.timestamped = True
        return self

    def recognize(self, audio, *, sample_rate=16000, **kwargs):
        self.heard.append((sample_rate, np.asarray(audio), kwargs))
        return self.answer


class _FakeRuntime:
    """Stands in for `onnx_asr` and `onnxruntime`, recording how the model was built."""

    def __init__(self):
        self.built = []
        outer = self

        class SessionOptions:
            intra_op_num_threads = 0

        self.onnxruntime = SimpleNamespace(SessionOptions=SessionOptions)

        def load_model(name, path=None, **kwargs):
            adapter = _Adapter()
            outer.built.append((name, path, kwargs, adapter))
            return adapter

        self.onnx_asr = SimpleNamespace(load_model=load_model)

    def patch(self, test):
        patcher = mock.patch.dict(sys.modules, {"onnx_asr": self.onnx_asr,
                                                "onnxruntime": self.onnxruntime})
        patcher.start()
        test.addCleanup(patcher.stop)
        return self


def _file(name, data):
    return parakeet.File(name, len(data), hashlib.sha256(data).hexdigest())


def _tiny_variants():
    """Both variants shrunk to a few bytes, with real checksums, for the fakes to serve."""
    contents = {
        "fp32": {"encoder-model.onnx": b"enc32", "encoder-model.onnx.data": b"data32" * 5,
                 "decoder_joint-model.onnx": b"dec32", "vocab.txt": b"vocab"},
        "int8": {"encoder-model.int8.onnx": b"enc8",
                 "decoder_joint-model.int8.onnx": b"dec8", "vocab.txt": b"vocab"},
    }
    variants = {
        key: parakeet.Variant(key, parakeet.VARIANTS[key].name,
                              parakeet.VARIANTS[key].quantization,
                              tuple(_file(n, d) for n, d in files.items()))
        for key, files in contents.items()
    }
    return variants, contents


class _TempCase(unittest.TestCase):
    """A temp `~/.flow/models` and two tiny variants."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.models = self.tmp / "models"
        self.variants, self.contents = _tiny_variants()
        for patcher in (mock.patch.object(parakeet, "MODELS_DIR", self.models),
                        mock.patch.dict(parakeet.VARIANTS, self.variants),
                        # No GPU backend unless a test says so: the machine running the suite
                        # may well have one, and the answer must not depend on it.
                        mock.patch.object(parakeet, "gpu_backend",
                                          return_value=("", "no GPU in tests"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def put(self, key, root=None):
        """Install variant `key` the way a finished fetch leaves it."""
        root = Path(root) if root else parakeet.variant_dir(key)
        root.mkdir(parents=True, exist_ok=True)
        for name, data in self.contents[key].items():
            (root / name).write_bytes(data)
        return root

    def source(self, key):
        """A directory that serves variant `key`, for `fetch(url_for=...)`."""
        root = self.tmp / f"source-{key}"
        self.put(key, root)
        return root, lambda name: (root / name).as_uri()


class TestImportingCostsNothing(unittest.TestCase):
    def test_constructing_never_imports_the_runtime(self):
        with mock.patch.dict(sys.modules):
            for name in ("onnx_asr", "onnxruntime"):
                sys.modules.pop(name, None)
            parakeet.ParakeetTranscriber(model_dir=Path("/nowhere"))
            self.assertNotIn("onnx_asr", sys.modules)

    def test_the_runtime_probe_does_not_import_it(self):
        with mock.patch.dict(sys.modules):
            for name in ("onnx_asr", "onnxruntime"):
                sys.modules.pop(name, None)
            parakeet.runtime_installed()
            self.assertNotIn("onnx_asr", sys.modules)

    def test_a_missing_runtime_says_how_to_get_it(self):
        with mock.patch.dict(sys.modules):
            sys.modules["onnx_asr"] = None  # what a missing package looks like
            sys.modules["onnxruntime"] = None
            with self.assertRaises(parakeet.NotAvailable) as raised:
                parakeet._import_runtime()
        self.assertIn("uv pip install", str(raised.exception))
        self.assertIn("onnx-asr", str(raised.exception))
        self.assertIn("[parakeet]", str(raised.exception))

    def test_the_probe_needs_both_packages(self):
        with mock.patch.dict(sys.modules, {"onnx_asr": object(), "onnxruntime": None}), \
                mock.patch("importlib.util.find_spec", return_value=None):
            ok, why = parakeet.runtime_installed()
        self.assertFalse(ok)
        self.assertEqual(why, parakeet.INSTALL_HINT)


class TestTheTranscriber(_TempCase):
    def setUp(self):
        super().setUp()
        self.fake = _FakeRuntime().patch(self)
        self.dir = self.put("fp32")
        self.t = parakeet.ParakeetTranscriber("fp32", model_dir=self.dir, threads=3)

    def audio(self, n=1600):
        return np.full(n, 0.1, dtype=np.float32)

    def test_it_builds_each_variant_the_way_the_bench_measured(self):
        for key, quantization in (("fp32", None), ("int8", "int8")):
            with self.subTest(key=key):
                self.fake.built.clear()
                root = self.put(key)
                t = parakeet.ParakeetTranscriber(key, threads=3)
                t.load()
                name, path, kwargs, adapter = self.fake.built[0]
                self.assertEqual(name, "nemo-parakeet-tdt-0.6b-v3")
                self.assertEqual(Path(path), root)
                self.assertEqual(kwargs["quantization"], quantization)
                self.assertEqual(kwargs["providers"], ["CPUExecutionProvider"])
                self.assertEqual(kwargs["sess_options"].intra_op_num_threads, 3)
                self.assertTrue(adapter.timestamped)  # logprobs need the timestamped form

    def test_the_default_thread_count_is_the_measured_rule(self):
        t = parakeet.ParakeetTranscriber("fp32", model_dir=self.dir)
        with mock.patch("os.cpu_count", return_value=24):
            t._threads = parakeet.default_threads()
        t.load()
        self.assertEqual(self.fake.built[-1][2]["sess_options"].intra_op_num_threads, 8)

    def test_text_comes_back_and_the_audio_is_sent_at_16k_float32(self):
        self.assertEqual(self.t.text(self.audio()), "hello world")
        rate, samples, _kw = self.fake.built[0][3].heard[0]
        self.assertEqual(rate, 16000)
        self.assertEqual(samples.dtype, np.float32)

    def test_the_first_text_loads_lazily_and_only_once(self):
        self.assertFalse(self.t.loaded)
        self.t.text(self.audio())
        self.t.text(self.audio())
        self.assertTrue(self.t.loaded)
        self.assertEqual(len(self.fake.built), 1)

    def test_only_load_imports_the_runtime(self):
        with mock.patch.dict(sys.modules):
            for name in ("onnx_asr", "onnxruntime"):
                sys.modules.pop(name, None)
            t = parakeet.ParakeetTranscriber("fp32", model_dir=self.dir)
            sys.modules["onnx_asr"] = self.fake.onnx_asr
            sys.modules["onnxruntime"] = self.fake.onnxruntime
            self.assertEqual(self.fake.built, [])
            t.load()
            self.assertEqual(len(self.fake.built), 1)

    def test_empty_audio_is_empty_text_without_loading(self):
        self.assertEqual(self.t.text(np.zeros(0, dtype=np.float32)), "")
        self.assertFalse(self.t.loaded)

    def test_hotwords_and_final_are_accepted_and_change_nothing(self):
        plain = self.t.text(self.audio())
        biased = self.t.text(self.audio(), final=True, hotwords="Kubernetes")
        self.assertEqual(plain, biased)
        for _rate, _audio, kwargs in self.fake.built[0][3].heard:
            self.assertNotIn("hotwords", kwargs)  # there is no biasing to pass it to

    def test_unload_releases_it_and_the_next_text_rebuilds(self):
        self.t.text(self.audio())
        self.t.unload()
        self.assertFalse(self.t.loaded)
        self.t.unload()  # twice is not an error
        self.assertEqual(self.t.text(self.audio()), "hello world")
        self.assertEqual(len(self.fake.built), 2)

    def test_loading_is_true_only_while_it_is_being_built(self):
        seen = []
        build = self.fake.onnx_asr.load_model
        self.fake.onnx_asr.load_model = lambda *a, **k: (seen.append(self.t.loading),
                                                        build(*a, **k))[1]
        self.assertFalse(self.t.loading)
        self.t.load()
        self.assertEqual(seen, [True])
        self.assertFalse(self.t.loading)

    def test_a_missing_or_partial_model_is_refused_with_where_it_looked(self):
        t = parakeet.ParakeetTranscriber("int8")  # nothing installed for int8
        with self.assertRaises(parakeet.NotAvailable) as raised:
            t.load()
        self.assertIn("not downloaded", str(raised.exception))
        self.assertFalse(t.loading)

    def test_the_variant_is_named_and_validated(self):
        self.assertEqual(self.t.variant, "fp32")
        self.assertEqual(self.t.engine, "parakeet")
        with self.assertRaises(ValueError):
            parakeet.ParakeetTranscriber("fp16")

    def test_the_session_sees_a_transcriber_with_drops_and_no_confidence(self):
        for name in ("text", "load", "unload", "take_drops"):
            self.assertTrue(callable(getattr(self.t, name)), name)
        self.assertIsNone(getattr(self.t, "take_confidence", None))
        self.assertFalse(getattr(self.t, "cancellable", False))

    def test_the_users_declared_corrections_are_applied(self):
        lex = mock.Mock()
        lex.apply.side_effect = lambda text: text.replace("hello", "HELLO")
        t = parakeet.ParakeetTranscriber("fp32", model_dir=self.dir, lexicon=lex)
        self.assertEqual(t.text(self.audio()), "HELLO world")


class TestTheHallucinationGate(_TempCase):
    def setUp(self):
        super().setUp()
        self.fake = _FakeRuntime().patch(self)
        self.t = parakeet.ParakeetTranscriber("fp32", model_dir=self.put("fp32"))
        self.t.load()
        self.adapter = self.fake.built[0][3]

    def hear(self, text, logprobs, final=True):
        self.adapter.answer = _Result(text, logprobs)
        return self.t.text(np.full(1600, 0.1, dtype=np.float32), final=final)

    def test_speech_at_the_worst_measured_percentile_is_kept(self):
        # p1 of 300 EdAcc clips: -0.51 (fp32), -0.57 (int8).
        self.assertEqual(self.hear("I need to send the email", [-0.57, -0.57]),
                         "I need to send the email")
        self.assertEqual(self.t.take_drops(), [])

    def test_the_measured_inventions_are_dropped_or_caught_by_the_filler_list(self):
        self.assertEqual(self.hear("Ha ha", [-0.9, -0.9]), "")   # int8 on a quiet room
        self.assertEqual(self.hear("It is.", [-1.0, -1.2]), "")  # sherpa int8 on fan noise
        self.assertEqual(self.hear("Okay.", [-0.6]), "")         # filler list, not the bar
        reasons = [d.reason for d in self.t.take_drops()]
        self.assertEqual(reasons, ["unconfident-tokens", "unconfident-tokens", "filler"])

    def test_a_drop_carries_its_evidence(self):
        self.hear("It is.", [-1.0, -1.2])
        drop = self.t.take_drops()[0]
        self.assertEqual(drop.text, "It is.")
        self.assertAlmostEqual(drop.avg_logprob, -1.10)
        self.assertIsNone(drop.no_speech_prob)
        self.assertTrue(drop.final)
        self.assertIn("unconfident-tokens", drop.describe())

    def test_a_drop_is_announced_without_the_invented_words(self):
        self.hear("It is.", [-1.1])
        line = self.t.take_drops()[0].announce()
        self.assertNotIn("It is", line)
        self.assertNotIn("that one did not sound like speech", line)

    def test_the_drops_are_drained_like_whispers(self):
        self.hear("It is.", [-1.1])
        self.assertEqual(len(self.t.take_drops()), 1)
        self.assertEqual(self.t.take_drops(), [])

    def test_silence_answered_with_nothing_records_nothing(self):
        self.assertEqual(self.hear("", []), "")
        self.assertEqual(self.t.take_drops(), [])

    def test_no_reported_probabilities_is_no_evidence_and_not_a_drop(self):
        self.assertEqual(self.hear("hello world", []), "hello world")
        self.assertEqual(self.hear("hello world", None), "hello world")

    def test_every_drop_reason_has_words_for_a_surface_that_speaks(self):
        from flow.asr import _REASON_WORDS

        self.assertIn("unconfident-tokens", _REASON_WORDS)
        self.assertIsInstance(Drop("x", "unconfident-tokens", None, -1.1, True).announce(),
                              str)

    def test_the_drop_log_is_bounded(self):
        from flow.asr import DROP_HISTORY

        for _ in range(DROP_HISTORY + 20):
            self.hear("Ha ha", [-1.1], final=False)
        self.assertEqual(len(self.t.take_drops()), DROP_HISTORY)

    def test_one_bar_serves_both_builds(self):
        # The scales agree (p1 -0.51 vs -0.57, p50 -0.09 vs -0.11), so the gate does not
        # ask which variant is running.
        for key in ("fp32", "int8"):
            t = parakeet.ParakeetTranscriber(key, model_dir=self.put(key))
            t.load()
            adapter = self.fake.built[-1][3]
            adapter.answer = _Result("Ha ha", [-0.9])
            self.assertEqual(t.text(np.full(1600, 0.1, dtype=np.float32)), "")


class TestMeanLogprob(unittest.TestCase):
    def test_it_is_the_mean_of_the_token_log_probs(self):
        self.assertAlmostEqual(parakeet.mean_logprob(_Result("a", [-1.0, -2.0])), -1.5)

    def test_nothing_reported_is_none_and_never_zero(self):
        self.assertIsNone(parakeet.mean_logprob(_Result("a", [])))
        self.assertIsNone(parakeet.mean_logprob(_Result("a", None)))
        self.assertIsNone(parakeet.mean_logprob(object()))


class TestTheShippedTables(unittest.TestCase):
    """The real `VARIANTS`, read back against what the hub published at the pinned revision."""

    def test_the_sizes_add_up_to_what_the_hub_listed(self):
        self.assertEqual(parakeet.REVISION, "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce")
        self.assertEqual(parakeet.REPO, "istupakov/parakeet-tdt-0.6b-v3-onnx")
        self.assertEqual(parakeet.VARIANTS["fp32"].bytes, 41_770_866 + 2_435_420_160
                         + 72_520_893 + 139_764 + 93_939 + 97)
        self.assertEqual(parakeet.VARIANTS["int8"].bytes,
                         652_183_999 + 18_202_004 + 139_764 + 93_939 + 97)

    def test_every_large_file_has_a_checksum_and_the_small_ones_are_sized(self):
        for key, variant in parakeet.VARIANTS.items():
            for f in variant.files:
                with self.subTest(key=key, file=f.name):
                    self.assertGreater(f.size, 0)
                    if f.size > 1_000_000:
                        self.assertEqual(len(f.sha256), 64)

    def test_the_names_are_plain_so_no_path_can_escape_the_directory(self):
        for variant in parakeet.VARIANTS.values():
            for f in variant.files:
                self.assertEqual(Path(f.name).name, f.name)

    def test_the_variant_names_are_the_catalog_names_and_the_choices_include_auto(self):
        self.assertEqual(parakeet.VARIANTS["fp32"].name, "parakeet-tdt-0.6b-v3")
        self.assertEqual(parakeet.VARIANTS["int8"].name, "parakeet-tdt-0.6b-v3-int8")
        self.assertEqual(parakeet.VARIANT_CHOICES, ("auto", "fp32", "int8", "gpu"))
        self.assertEqual(parakeet.VARIANTS["gpu"].name, "parakeet-tdt-0.6b-v3-gpu")


class TestTheVariants(_TempCase):
    def test_urls_are_pinned_to_the_revision_and_not_a_branch(self):
        url = parakeet.hub_url("encoder-model.onnx.data")
        self.assertEqual(url, "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx/"
                              f"resolve/{parakeet.REVISION}/encoder-model.onnx.data")
        self.assertNotIn("/main/", url)

    def test_each_variant_has_its_own_directory_and_quantization(self):
        self.assertEqual(parakeet.variant_dir("fp32"), self.models / "parakeet-tdt-0.6b-v3")
        self.assertEqual(parakeet.variant_dir("int8"),
                         self.models / "parakeet-tdt-0.6b-v3-int8")
        self.assertIsNone(parakeet.VARIANTS["fp32"].quantization)
        self.assertEqual(parakeet.VARIANTS["int8"].quantization, "int8")

    def test_a_complete_directory_is_a_model(self):
        self.put("fp32")
        self.assertTrue(parakeet.model_present("fp32"))
        self.assertFalse(parakeet.model_present("int8"))
        self.assertEqual(parakeet.installed_variants(), ["fp32"])

    def test_a_missing_partial_or_wrong_size_file_is_not_a_model(self):
        root = self.put("fp32")
        (root / "vocab.txt").write_bytes(b"too long")  # right name, wrong size
        self.assertFalse(parakeet.model_present("fp32"))
        (root / "vocab.txt").write_bytes(b"vocab")
        (root / "encoder-model.onnx").unlink()
        self.assertFalse(parakeet.model_present("fp32"))
        self.assertFalse(parakeet.model_present("fp32", self.tmp / "nope"))

    def test_auto_prefers_fp32_then_int8_then_fp32_to_download(self):
        self.assertEqual(parakeet.resolve_variant("auto"), "fp32")
        self.assertEqual(parakeet.resolve_variant(None), "fp32")
        self.put("int8")
        self.assertEqual(parakeet.resolve_variant("auto"), "int8")
        self.put("fp32")
        self.assertEqual(parakeet.resolve_variant("auto"), "fp32")

    def test_an_explicit_choice_is_honoured_even_when_it_is_not_here(self):
        self.put("fp32")
        self.assertEqual(parakeet.resolve_variant("int8"), "int8")

    def test_available_names_the_first_thing_missing(self):
        with mock.patch.object(parakeet, "runtime_installed",
                               return_value=(False, "no runtime")):
            self.assertEqual(parakeet.available("fp32"), (False, "no runtime"))
        with mock.patch.object(parakeet, "runtime_installed", return_value=(True, "")):
            ok, why = parakeet.available("fp32")
            self.assertFalse(ok)
            self.assertIn("not downloaded", why)
            self.put("fp32")
            self.assertEqual(parakeet.available("fp32"), (True, ""))

    def test_the_size_on_disk_is_the_files(self):
        self.assertEqual(parakeet.installed_bytes("fp32"), 0)
        self.put("int8")
        self.assertEqual(parakeet.installed_bytes("int8"),
                         sum(len(d) for d in self.contents["int8"].values()))

    def test_threads_default_to_the_measured_eight_or_the_cores_there_are(self):
        with mock.patch("os.cpu_count", return_value=24):
            self.assertEqual(parakeet.default_threads(), 8)
        with mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(parakeet.default_threads(), 4)
        with mock.patch("os.cpu_count", return_value=None):
            self.assertEqual(parakeet.default_threads(), 1)


class TestTheOldSherpaFolder(_TempCase):
    def old(self):
        root = parakeet.legacy_dir()
        root.mkdir(parents=True)
        (root / "encoder.int8.onnx").write_bytes(b"x" * 100)
        return root

    def test_it_is_not_a_model_for_this_runtime(self):
        self.old()
        self.assertFalse(parakeet.model_present("int8"))
        self.assertEqual(parakeet.installed_variants(), [])
        self.assertEqual(parakeet.resolve_variant("auto"), "fp32")

    def test_it_is_counted_so_the_page_can_offer_to_remove_it(self):
        self.assertEqual(parakeet.legacy_bytes(), 0)
        self.old()
        self.assertEqual(parakeet.legacy_bytes(), 100)

    def test_it_is_removed_only_when_asked(self):
        root = self.old()
        parakeet.fetch("int8", url_for=self.source("int8")[1])  # a fetch leaves it alone
        self.assertTrue(root.exists())
        self.assertTrue(parakeet.remove_legacy())
        self.assertFalse(root.exists())
        self.assertFalse(parakeet.remove_legacy())


class TestFetch(_TempCase):
    """The download, through `file://` URLs — no network."""

    def fetch(self, key="int8", **kw):
        _root, url_for = self.source(key)
        return parakeet.fetch(key, url_for=url_for, **kw)

    def leftovers(self):
        return [p for p in self.models.iterdir() if not p.name.startswith("parakeet-tdt")]

    def test_it_lands_whole_and_leaves_no_scratch_behind(self):
        dest = self.fetch("int8")
        self.assertEqual(dest, parakeet.variant_dir("int8"))
        self.assertTrue(parakeet.model_present("int8"))
        self.assertEqual(self.leftovers(), [])

    def test_the_bigger_variant_has_its_external_data_file_in_place(self):
        dest = self.fetch("fp32")
        self.assertTrue((dest / "encoder-model.onnx.data").is_file())
        self.assertTrue(parakeet.model_present("fp32"))

    def test_progress_is_in_bytes_across_the_whole_variant_ending_at_the_total(self):
        seen = []
        self.fetch("int8", progress=lambda done, total: seen.append((done, total)))
        total = parakeet.VARIANTS["int8"].bytes
        self.assertEqual(seen[-1], (total, total))
        self.assertEqual([d for d, _ in seen], sorted(d for d, _ in seen))  # never backwards

    def test_a_file_that_is_the_wrong_size_is_refused_and_nothing_lands(self):
        root, url_for = self.source("int8")
        (root / "encoder-model.int8.onnx").write_bytes(b"truncated")
        with self.assertRaises(parakeet.NotAvailable) as raised:
            parakeet.fetch("int8", url_for=url_for)
        self.assertIn("encoder-model.int8.onnx", str(raised.exception))
        self.assertFalse(parakeet.variant_dir("int8").exists())
        self.assertEqual(self.leftovers(), [])

    def test_a_file_with_the_right_size_and_the_wrong_bytes_fails_its_checksum(self):
        root, url_for = self.source("int8")
        (root / "decoder_joint-model.int8.onnx").write_bytes(b"XXXX")  # same 4 bytes
        with self.assertRaises(parakeet.NotAvailable) as raised:
            parakeet.fetch("int8", url_for=url_for)
        self.assertIn("checksum", str(raised.exception))
        self.assertFalse(parakeet.variant_dir("int8").exists())

    def test_a_server_that_is_not_there_is_a_reason_not_a_traceback(self):
        with self.assertRaises(parakeet.NotAvailable) as raised:
            parakeet.fetch("int8", url_for=lambda n: (self.tmp / "gone" / n).as_uri())
        self.assertIn("download failed", str(raised.exception))
        self.assertFalse(parakeet.variant_dir("int8").exists())

    def test_a_cancel_mid_download_leaves_no_partial_model_and_no_scratch(self):
        asked = []

        def cancelled():
            asked.append(1)
            return len(asked) > 2  # let a couple of chunks through, then stop

        with mock.patch.object(parakeet, "_CHUNK", 2):
            with self.assertRaises(parakeet.Cancelled):
                self.fetch("fp32", cancelled=cancelled)
        self.assertGreaterEqual(len(asked), 3)  # asked per chunk, not once
        self.assertFalse(parakeet.variant_dir("fp32").exists())
        self.assertEqual(self.leftovers(), [])

    def test_a_cancel_after_the_last_file_stops_before_anything_is_installed(self):
        total_chunks = sum(-(-f.size // parakeet._CHUNK) + 1
                           for f in parakeet.VARIANTS["int8"].files)
        answers = iter([False] * total_chunks + [True])
        with self.assertRaises(parakeet.Cancelled):
            self.fetch("int8", cancelled=lambda: next(answers, True))
        self.assertFalse(parakeet.variant_dir("int8").exists())
        self.assertEqual(self.leftovers(), [])

    def test_a_cancel_keeps_an_earlier_good_copy(self):
        self.put("int8")
        with self.assertRaises(parakeet.Cancelled):
            self.fetch("int8", cancelled=lambda: True)
        self.assertTrue(parakeet.model_present("int8"))

    def test_a_broken_earlier_copy_is_replaced(self):
        dest = parakeet.variant_dir("int8")
        dest.mkdir(parents=True)
        (dest / "junk").write_bytes(b"half")
        self.fetch("int8")
        self.assertTrue(parakeet.model_present("int8"))
        self.assertFalse((dest / "junk").exists())

    def test_cancelled_is_not_a_failure(self):
        self.assertFalse(issubclass(parakeet.Cancelled, parakeet.NotAvailable))

    def test_the_default_source_is_the_pinned_revision(self):
        seen = []

        def refuse(request, timeout=None):
            seen.append(request.full_url)
            raise OSError("no network in tests")

        with mock.patch("urllib.request.urlopen", refuse):
            with self.assertRaises(parakeet.NotAvailable):
                parakeet.fetch("int8")
        self.assertEqual(seen, [parakeet.hub_url("encoder-model.int8.onnx")])
        self.assertIn(parakeet.REVISION, seen[0])


def _args(engine):
    return mock.Mock(engine=engine)


class TestAutoNeverChoosesParakeet(unittest.TestCase):
    """The rule that keeps this an opt-in: nothing installed or on disk changes `auto`."""

    def everything_ready(self):
        return (mock.patch.object(parakeet, "runtime_installed", return_value=(True, "")),
                mock.patch.object(parakeet, "model_present", return_value=True),
                mock.patch.object(parakeet, "available", return_value=(True, "")),
                mock.patch.object(parakeet, "fetch"))

    def test_auto_keeps_whisper_on_every_platform_with_parakeet_fully_ready(self):
        for platform in ("win32", "linux", "darwin"):
            for whisper_here in (True, False):
                with self.subTest(platform=platform, whisper_here=whisper_here):
                    a, b, c, fetch = self.everything_ready()
                    with a, b, c, fetch as fetching, \
                            mock.patch.object(sys, "platform", platform), \
                            mock.patch("flow.__main__._models_present",
                                       return_value=whisper_here), \
                            mock.patch("flow.native.available",
                                       return_value=(False, "no")):
                        engine, _why = _engine(_args("auto"), "base.en", "small.en")
                    self.assertNotEqual(engine, "parakeet")
                    fetching.assert_not_called()

    def test_whisper_by_name_never_looks_at_parakeet(self):
        with mock.patch.object(parakeet, "runtime_installed") as probe:
            self.assertEqual(_engine(_args("whisper"), "base.en", "small.en"),
                             ("whisper", ""))
        probe.assert_not_called()


class TestAskingForParakeet(unittest.TestCase):
    def run_engine(self, installed=(True, ""), present=True, fetch=None, variant=None):
        said = []
        with mock.patch.object(parakeet, "runtime_installed", return_value=installed), \
                mock.patch.object(parakeet, "gpu_backend", return_value=("", "none")), \
                mock.patch.object(parakeet, "model_present",
                                  side_effect=lambda key, model_dir=None: present and key != "gpu"), \
                mock.patch.object(parakeet, "fetch", fetch or mock.Mock()) as fetching, \
                mock.patch("flow.__main__.say", said.append):
            got = _engine(_args("parakeet"), "base.en", "small.en", variant=variant)
        return got, said, fetching

    def test_ready_means_parakeet_and_the_startup_line_can_say_why(self):
        (engine, why), said, fetching = self.run_engine()
        self.assertEqual(engine, "parakeet")
        self.assertIn("--engine parakeet", why)
        fetching.assert_not_called()

    def test_a_missing_runtime_falls_back_to_whisper_out_loud(self):
        (engine, _why), said, fetching = self.run_engine(
            installed=(False, parakeet.INSTALL_HINT))
        self.assertEqual(engine, "whisper")
        text = " ".join(said)
        self.assertIn("uv pip install", text)
        self.assertIn("using whisper", text)
        fetching.assert_not_called()  # no point downloading gigabytes for a runtime it lacks

    def test_a_missing_model_is_fetched_and_the_size_and_source_are_said_first(self):
        (engine, _why), said, fetching = self.run_engine(present=False)
        self.assertEqual(engine, "parakeet")
        fetching.assert_called_once()
        self.assertEqual(fetching.call_args.args[0], "fp32")  # nothing here: the accurate one
        self.assertIn("2432 MB", said[0])
        self.assertIn("huggingface.co", said[0])
        self.assertNotIn("github", said[0])

    def test_the_profiles_build_is_the_one_that_is_fetched(self):
        _got, said, fetching = self.run_engine(present=False, variant="int8")
        self.assertEqual(fetching.call_args.args[0], "int8")
        self.assertIn("640 MB", said[0])

    def test_a_failed_download_falls_back_with_the_reason(self):
        boom = mock.Mock(side_effect=parakeet.NotAvailable("download failed: offline"))
        (engine, _why), said, _f = self.run_engine(present=False, fetch=boom)
        self.assertEqual(engine, "whisper")
        self.assertIn("download failed: offline", " ".join(said))

    def test_progress_is_a_line_per_tenth_not_per_megabyte(self):
        def fake_fetch(key, progress=None, **_kw):
            for done in range(0, 101):
                progress(done * 10, 1000)

        (engine, _why), said, _f = self.run_engine(present=False, fetch=fake_fetch)
        lines = [s for s in said if "download" in s and "%" in s]
        self.assertEqual(engine, "parakeet")
        self.assertEqual(len(lines), 10)
        self.assertTrue(all(s.isascii() for s in said))


class TestThePrecedenceOfFlagProfileAndAuto(unittest.TestCase):
    """`--engine` beats the Models page's remembered choice; `auto` honours it; and with no
    remembered Parakeet everything is exactly as it was — native on a Mac included."""

    def pick(self, engine, saved, runtime=(True, ""), model=True, platform="win32",
             whisper_here=True, native=(False, "no"), variant=None):
        said = []
        with mock.patch.object(parakeet, "runtime_installed", return_value=runtime), \
                mock.patch.object(parakeet, "gpu_backend", return_value=("", "none")), \
                mock.patch.object(parakeet, "model_present",
                                  side_effect=lambda key, model_dir=None: model and key != "gpu"), \
                mock.patch.object(parakeet, "fetch") as fetching, \
                mock.patch.object(sys, "platform", platform), \
                mock.patch("flow.__main__.say", said.append), \
                mock.patch("flow.__main__._models_present", return_value=whisper_here), \
                mock.patch("flow.native.available", return_value=native):
            got = _engine(_args(engine), "base.en", "small.en", saved=saved,
                          variant=variant)
        return got, said, fetching

    def test_auto_with_a_saved_parakeet_is_parakeet(self):
        (engine, why), said, fetching = self.pick("auto", "parakeet")
        self.assertEqual(engine, "parakeet")
        self.assertIn("Models page", why)
        fetching.assert_not_called()

    def test_auto_with_a_saved_parakeet_wins_over_native_on_a_mac(self):
        (engine, _why), _said, _f = self.pick("auto", "parakeet", platform="darwin",
                                              whisper_here=False, native=(True, ""))
        self.assertEqual(engine, "parakeet")

    def test_the_flag_beats_the_saved_choice_both_ways(self):
        self.assertEqual(self.pick("whisper", "parakeet")[0], ("whisper", ""))
        self.assertEqual(self.pick("parakeet", "whisper")[0][0], "parakeet")

    def test_a_saved_whisper_or_none_leaves_auto_exactly_as_it_was(self):
        for saved in ("whisper", ""):
            with self.subTest(saved=saved):
                self.assertEqual(self.pick("auto", saved)[0], ("whisper", ""))
        (engine, why), _s, _f = self.pick("auto", "whisper", platform="darwin",
                                          whisper_here=False, native=(True, ""))
        self.assertEqual(engine, "native")
        self.assertIn("models not found", why)

    def test_a_saved_parakeet_whose_runtime_is_gone_falls_back_and_says_why(self):
        (engine, _w), said, fetching = self.pick(
            "auto", "parakeet", runtime=(False, parakeet.INSTALL_HINT))
        self.assertEqual(engine, "whisper")
        self.assertIn("uv pip install", " ".join(said))
        self.assertIn("Models page", " ".join(said))
        fetching.assert_not_called()

    def test_a_saved_parakeet_whose_model_is_gone_never_blocks_launch_on_a_download(self):
        (engine, _w), said, fetching = self.pick("auto", "parakeet", model=False,
                                                 variant="int8")
        self.assertEqual(engine, "whisper")
        fetching.assert_not_called()  # the page offers it; the launch does not wait on it
        text = " ".join(said)
        self.assertIn("downloads it", text)
        self.assertIn("int8", text)
        self.assertTrue(all(s.isascii() for s in said))

    def test_the_explicit_flag_still_downloads(self):
        (engine, _w), _said, fetching = self.pick("parakeet", "whisper", model=False)
        self.assertEqual(engine, "parakeet")
        fetching.assert_called_once()


class TestTheEngineFlag(unittest.TestCase):
    def test_parakeet_is_a_choice_and_the_default_is_still_auto(self):
        import subprocess

        out = subprocess.run([sys.executable, "-m", "flow", "--help"],
                             capture_output=True, text=True, check=True,
                             cwd=Path(__file__).resolve().parent.parent,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"}).stdout
        flat = " ".join(out.split())
        self.assertIn("{auto,whisper,native,parakeet}", flat)
        self.assertIn("never chosen by auto", flat)
        self.assertIn("onnx-asr", flat)


_HAS_RUNTIME = parakeet.runtime_installed()[0]


@unittest.skipUnless(_HAS_RUNTIME, "the parakeet extra is not installed")
class TestParakeetReal(unittest.TestCase):
    """The real packages, when this machine has them. Skipped everywhere else.

    The contract with someone else's code that the fakes above cannot check: that
    `onnx_asr.load_model` still takes the arguments `load_model` passes, that the adapter
    still offers `with_timestamps`, and that its result still carries `.text` and
    `.logprobs`. No model is loaded, so this works on a machine that installed the extra
    and never downloaded one.
    """

    def test_the_loader_still_takes_what_we_pass(self):
        import inspect

        import onnx_asr

        params = inspect.signature(onnx_asr.load_model).parameters
        for name in ("model", "path", "quantization", "sess_options", "providers"):
            self.assertIn(name, params)

    def test_the_result_still_carries_text_and_logprobs(self):
        from onnx_asr.adapters import TextResultsAsrAdapter, TimestampedResult

        fields = set(TimestampedResult.__dataclass_fields__)
        self.assertTrue({"text", "logprobs"} <= fields)
        self.assertTrue(callable(getattr(TextResultsAsrAdapter, "with_timestamps", None)))

    def test_the_cpu_session_options_take_a_thread_count(self):
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 3
        self.assertEqual(options.intra_op_num_threads, 3)
        self.assertIn("CPUExecutionProvider", onnxruntime.get_available_providers())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
