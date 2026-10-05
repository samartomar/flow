"""The Parakeet engine: an opt-in decoder, and the rules that keep it opt-in.

Nothing here needs the model, the network or the `[parakeet]` extra. `sherpa_onnx` is a
fake put into `sys.modules`, and the download goes through a `file://` URL, so what is
asserted is Flow's side of each contract:

  **Importing it costs nothing, and a default install never breaks on it.** The real
  package is imported inside `load()` and nowhere else.

  **`auto` never picks it.** It is a different engine with real costs (an extra, a 465 MB
  model, one tier, no hotword biasing, a hallucination gate that rests on one measured
  example), so choosing it is the user's act. `TestAutoNeverChoosesParakeet` pins that
  on every platform and with everything installed.

  **A refusal says why, and names the fallback** — the same as `--engine native`.

  **The archive is not trusted.** The model arrives as a `.tar.bz2` from a URL; a member
  that names a path outside the destination, or is a link, is refused before anything is
  written.
"""

import bz2
import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.parakeet as parakeet  # noqa: E402
from flow.__main__ import _engine  # noqa: E402
from flow.asr import Drop  # noqa: E402

NAMES = parakeet.REQUIRED_FILES


class _Result:
    def __init__(self, text, log_probs):
        self.text = text
        self.ys_log_probs = log_probs


class _Stream:
    def __init__(self, owner):
        self._owner = owner
        self.result = None

    def accept_waveform(self, rate, samples):
        self._owner.heard.append((rate, np.asarray(samples)))


class _Recogniser:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.heard = []
        self.answer = _Result("hello world", [-0.1, -0.2])

    def create_stream(self):
        return _Stream(self)

    def decode_stream(self, stream):
        stream.result = self.answer


class _FakeSherpa:
    """Stands in for the `sherpa_onnx` module: records how the recogniser was built."""

    def __init__(self):
        self.built = []
        outer = self

        class OfflineRecognizer:
            @staticmethod
            def from_transducer(**kwargs):
                rec = _Recogniser(kwargs)
                outer.built.append(rec)
                return rec

        self.OfflineRecognizer = OfflineRecognizer


def _model_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        (root / name).write_bytes(b"x")
    return root


def _archive(path: Path, members) -> Path:
    """A `.tar.bz2` of `(name, data)` pairs; `data` is bytes, or a `TarInfo` for the odd ones."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in members:
            if isinstance(data, tarfile.TarInfo):
                data.name = name
                tar.addfile(data)
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    path.write_bytes(bz2.compress(raw.getvalue()))
    return path


def _good_archive(path: Path) -> Path:
    return _archive(path, [(f"{parakeet.MODEL_NAME}/{n}", b"model") for n in NAMES])


class _TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class TestImportingCostsNothing(unittest.TestCase):
    def test_constructing_never_imports_the_runtime(self):
        with mock.patch.dict(sys.modules):
            sys.modules.pop("sherpa_onnx", None)
            parakeet.ParakeetTranscriber(model_dir=Path("/nowhere"))
            self.assertNotIn("sherpa_onnx", sys.modules)

    def test_only_load_imports_it(self):
        fake = _FakeSherpa()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules):
            sys.modules["sherpa_onnx"] = fake
            t = parakeet.ParakeetTranscriber(model_dir=_model_dir(Path(tmp) / "m"))
            self.assertEqual(fake.built, [])
            t.load()
            self.assertEqual(len(fake.built), 1)

    def test_the_default_install_without_the_runtime_says_how_to_get_it(self):
        with mock.patch.dict(sys.modules):
            sys.modules["sherpa_onnx"] = None  # what a missing package looks like
            ok, why = parakeet.runtime_installed.__wrapped__() \
                if hasattr(parakeet.runtime_installed, "__wrapped__") else (False, "")
            with tempfile.TemporaryDirectory() as tmp:
                t = parakeet.ParakeetTranscriber(model_dir=_model_dir(Path(tmp) / "m"))
                with self.assertRaises(parakeet.NotAvailable) as raised:
                    t.load()
            self.assertIn("sherpa-onnx", str(raised.exception))
            self.assertIn("uv pip install", str(raised.exception))


class TestTheTranscriber(_TempCase):
    def setUp(self):
        super().setUp()
        self.fake = _FakeSherpa()
        patch = mock.patch.dict(sys.modules, {"sherpa_onnx": self.fake})
        patch.start()
        self.addCleanup(patch.stop)
        self.dir = _model_dir(self.tmp / "model")
        self.t = parakeet.ParakeetTranscriber(model_dir=self.dir, threads=3)

    def audio(self, n=1600):
        return np.full(n, 0.1, dtype=np.float32)

    def test_it_builds_the_recogniser_the_way_the_spike_measured(self):
        self.t.load()
        kw = self.fake.built[0].kwargs
        self.assertEqual(kw["model_type"], "nemo_transducer")
        self.assertEqual(kw["provider"], "cpu")
        self.assertEqual(kw["num_threads"], 3)
        self.assertEqual(kw["encoder"], str(self.dir / "encoder.int8.onnx"))
        self.assertEqual(kw["tokens"], str(self.dir / "tokens.txt"))

    def test_text_comes_back_and_the_audio_is_sent_at_16k_float32(self):
        self.assertEqual(self.t.text(self.audio()), "hello world")
        rate, samples = self.fake.built[0].heard[0]
        self.assertEqual(rate, 16000)
        self.assertEqual(samples.dtype, np.float32)

    def test_the_first_text_loads_lazily_and_only_once(self):
        self.assertFalse(self.t.loaded)
        self.t.text(self.audio())
        self.t.text(self.audio())
        self.assertTrue(self.t.loaded)
        self.assertEqual(len(self.fake.built), 1)

    def test_empty_audio_is_empty_text_without_loading(self):
        self.assertEqual(self.t.text(np.zeros(0, dtype=np.float32)), "")
        self.assertFalse(self.t.loaded)

    def test_hotwords_and_final_are_accepted_and_change_nothing(self):
        plain = self.t.text(self.audio())
        biased = self.t.text(self.audio(), final=True, hotwords="Kubernetes")
        self.assertEqual(plain, biased)
        # Nothing reached the recogniser's construction either: there is no biasing here.
        self.assertNotIn("hotwords", self.fake.built[0].kwargs)

    def test_unload_releases_it_and_the_next_text_rebuilds(self):
        self.t.text(self.audio())
        self.t.unload()
        self.assertFalse(self.t.loaded)
        self.t.unload()  # twice is not an error
        self.assertEqual(self.t.text(self.audio()), "hello world")
        self.assertEqual(len(self.fake.built), 2)

    def test_loading_is_true_only_while_it_is_being_built(self):
        seen = []
        build = self.fake.OfflineRecognizer.from_transducer
        self.fake.OfflineRecognizer.from_transducer = staticmethod(
            lambda **kw: (seen.append(self.t.loading), build(**kw))[1])
        self.assertFalse(self.t.loading)
        self.t.load()
        self.assertEqual(seen, [True])
        self.assertFalse(self.t.loading)

    def test_a_missing_model_is_refused_with_where_it_looked(self):
        t = parakeet.ParakeetTranscriber(model_dir=self.tmp / "empty")
        with self.assertRaises(parakeet.NotAvailable) as raised:
            t.load()
        self.assertIn("not downloaded", str(raised.exception))
        self.assertFalse(t.loading)

    def test_the_session_sees_a_transcriber_with_drops_and_no_confidence(self):
        for name in ("text", "load", "unload", "take_drops"):
            self.assertTrue(callable(getattr(self.t, name)), name)
        # Its numbers are not on Whisper's `avg_logprob` scale, which is what the session
        # reads `take_confidence` as. Absent is honest; a lookalike would be a lie.
        self.assertIsNone(getattr(self.t, "take_confidence", None))
        self.assertFalse(getattr(self.t, "cancellable", False))

    def test_the_users_declared_corrections_are_applied(self):
        lex = mock.Mock()
        lex.apply.side_effect = lambda text: text.replace("hello", "HELLO")
        t = parakeet.ParakeetTranscriber(model_dir=self.dir, lexicon=lex)
        self.assertEqual(t.text(self.audio()), "HELLO world")


class TestTheHallucinationGate(_TempCase):
    def setUp(self):
        super().setUp()
        self.fake = _FakeSherpa()
        patch = mock.patch.dict(sys.modules, {"sherpa_onnx": self.fake})
        patch.start()
        self.addCleanup(patch.stop)
        self.t = parakeet.ParakeetTranscriber(model_dir=_model_dir(self.tmp / "m"))
        self.t.load()
        self.rec = self.fake.built[0]

    def hear(self, text, log_probs, final=True):
        self.rec.answer = _Result(text, log_probs)
        return self.t.text(np.full(1600, 0.1, dtype=np.float32), final=final)

    def test_speech_at_the_worst_measured_percentile_is_kept(self):
        # p1 of 299 EdAcc clips: -0.59.
        self.assertEqual(self.hear("I need to send the email", [-0.59, -0.59]),
                         "I need to send the email")
        self.assertEqual(self.t.take_drops(), [])

    def test_the_one_measured_invention_is_dropped_with_its_evidence(self):
        # "It is." on fan noise, mean token log-prob -1.10.
        self.assertEqual(self.hear("It is.", [-1.0, -1.2]), "")
        drops = self.t.take_drops()
        self.assertEqual([d.reason for d in drops], ["unconfident-tokens"])
        self.assertEqual(drops[0].text, "It is.")
        self.assertAlmostEqual(drops[0].avg_logprob, -1.10)
        self.assertIsNone(drops[0].no_speech_prob)
        self.assertTrue(drops[0].final)
        self.assertIn("unconfident-tokens", drops[0].describe())

    def test_a_drop_is_announced_without_the_invented_words(self):
        self.hear("It is.", [-1.1])
        line = self.t.take_drops()[0].announce()
        self.assertNotIn("It is", line)
        self.assertNotIn("that one did not sound like speech", line)  # has its own words

    def test_the_drops_are_drained_like_whispers(self):
        self.hear("It is.", [-1.1])
        self.assertEqual(len(self.t.take_drops()), 1)
        self.assertEqual(self.t.take_drops(), [])

    def test_silence_that_the_model_answers_with_nothing_records_nothing(self):
        # 7 of 8 silence clips: empty. Announcing "I did not catch 0 words" for each
        # would be the bug the drop log's own docstring describes.
        self.assertEqual(self.hear("", []), "")
        self.assertEqual(self.t.take_drops(), [])

    def test_no_reported_probabilities_is_no_evidence_and_not_a_drop(self):
        self.assertEqual(self.hear("hello world", []), "hello world")
        self.assertEqual(self.hear("hello world", None), "hello world")

    def test_a_whole_utterance_filler_is_still_caught_without_any_numbers(self):
        self.assertEqual(self.hear("Thank you.", [-0.1]), "")
        self.assertEqual([d.reason for d in self.t.take_drops()], ["filler"])

    def test_every_drop_reason_has_words_for_a_surface_that_speaks(self):
        from flow.asr import _REASON_WORDS

        self.assertIn("unconfident-tokens", _REASON_WORDS)
        self.assertIsInstance(Drop("x", "unconfident-tokens", None, -1.1, True).announce(),
                              str)

    def test_the_drop_log_is_bounded(self):
        from flow.asr import DROP_HISTORY

        for _ in range(DROP_HISTORY + 20):
            self.hear("It is.", [-1.1], final=False)
        self.assertEqual(len(self.t.take_drops()), DROP_HISTORY)


class TestMeanLogprob(unittest.TestCase):
    def test_it_is_the_mean_of_the_token_log_probs(self):
        self.assertAlmostEqual(parakeet.mean_logprob(_Result("a", [-1.0, -2.0])), -1.5)

    def test_nothing_reported_is_none_and_never_zero(self):
        self.assertIsNone(parakeet.mean_logprob(_Result("a", [])))
        self.assertIsNone(parakeet.mean_logprob(_Result("a", None)))
        self.assertIsNone(parakeet.mean_logprob(object()))


class TestIsItHere(_TempCase):
    def test_a_complete_directory_is_a_model(self):
        self.assertTrue(parakeet.model_present(_model_dir(self.tmp / "m")))

    def test_a_missing_or_partial_directory_is_not(self):
        self.assertFalse(parakeet.model_present(self.tmp / "nope"))
        partial = _model_dir(self.tmp / "p")
        (partial / "encoder.int8.onnx").unlink()
        self.assertFalse(parakeet.model_present(partial))
        (partial / "encoder.int8.onnx").write_bytes(b"")  # present but empty
        self.assertFalse(parakeet.model_present(partial))

    def test_available_names_the_first_thing_missing(self):
        with mock.patch.object(parakeet, "runtime_installed",
                               return_value=(False, "no runtime")):
            self.assertEqual(parakeet.available(self.tmp), (False, "no runtime"))
        with mock.patch.object(parakeet, "runtime_installed", return_value=(True, "")):
            ok, why = parakeet.available(self.tmp / "nope")
            self.assertFalse(ok)
            self.assertIn("not downloaded", why)
            self.assertEqual(parakeet.available(_model_dir(self.tmp / "m")), (True, ""))

    def test_the_runtime_probe_does_not_import_it(self):
        with mock.patch.dict(sys.modules):
            sys.modules.pop("sherpa_onnx", None)
            parakeet.runtime_installed()
            self.assertNotIn("sherpa_onnx", sys.modules)

    def test_threads_default_to_the_measured_eight_or_the_cores_there_are(self):
        with mock.patch("os.cpu_count", return_value=24):
            self.assertEqual(parakeet.default_threads(), 8)
        with mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(parakeet.default_threads(), 4)
        with mock.patch("os.cpu_count", return_value=None):
            self.assertEqual(parakeet.default_threads(), 1)


class TestTheArchiveIsNotTrusted(_TempCase):
    def refused(self, members):
        archive = _archive(self.tmp / "bad.tar.bz2", members)
        out = self.tmp / "out"
        with self.assertRaises(parakeet.NotAvailable):
            parakeet.extract(archive, out)
        return out

    def test_a_dotdot_member_is_refused_and_nothing_is_written(self):
        out = self.refused([("../escaped.txt", b"x"),
                            (f"{parakeet.MODEL_NAME}/tokens.txt", b"x")])
        self.assertFalse((self.tmp / "escaped.txt").exists())
        self.assertEqual(list(out.iterdir()), [])  # not even the harmless member

    def test_an_absolute_member_is_refused(self):
        self.refused([("/etc/escaped.txt", b"x")])
        self.refused([("C:/escaped.txt", b"x")])

    def test_a_backslash_traversal_is_refused_because_windows_reads_it_as_one(self):
        self.refused([("..\\escaped.txt", b"x")])

    def test_a_symlink_is_refused(self):
        link = tarfile.TarInfo()
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        self.refused([(f"{parakeet.MODEL_NAME}/encoder.int8.onnx", link)])

    def test_a_good_archive_is_unpacked_and_its_root_found(self):
        archive = _good_archive(self.tmp / "ok.tar.bz2")
        root = parakeet.extract(archive, self.tmp / "out")
        self.assertEqual(root.name, parakeet.MODEL_NAME)
        self.assertTrue(parakeet.model_present(root))

    def test_an_archive_without_the_model_is_refused(self):
        archive = _archive(self.tmp / "empty.tar.bz2", [("readme.txt", b"x")])
        with self.assertRaises(parakeet.NotAvailable) as raised:
            parakeet.extract(archive, self.tmp / "out")
        self.assertIn("model files", str(raised.exception))

    def test_a_corrupt_archive_is_refused_not_raised_raw(self):
        bad = self.tmp / "bad.tar.bz2"
        bad.write_bytes(b"not an archive")
        with self.assertRaises(parakeet.NotAvailable):
            parakeet.extract(bad, self.tmp / "out")


class TestFetch(_TempCase):
    """The download, through a `file://` URL — no network."""

    def fetch(self, archive, **kw):
        kw.setdefault("expected_bytes", None)
        return parakeet.fetch(self.tmp / "models" / "m", url=archive.as_uri(), **kw)

    def leftovers(self):
        return [p for p in (self.tmp / "models").iterdir() if p.name != "m"]

    def test_it_lands_whole_and_leaves_no_scratch_behind(self):
        archive = _good_archive(self.tmp / "a.tar.bz2")
        dest = self.fetch(archive)
        self.assertEqual(dest, self.tmp / "models" / "m")
        self.assertTrue(parakeet.model_present(dest))
        self.assertEqual(self.leftovers(), [])

    def test_progress_is_reported_in_bytes_ending_at_the_total(self):
        archive = _good_archive(self.tmp / "a.tar.bz2")
        seen = []
        self.fetch(archive, progress=lambda done, total: seen.append((done, total)))
        self.assertTrue(seen)
        self.assertEqual(seen[-1], (archive.stat().st_size, archive.stat().st_size))

    def test_a_failed_fetch_leaves_nothing_a_model_check_could_accept(self):
        bad = _archive(self.tmp / "bad.tar.bz2", [("../escape", b"x")])
        with self.assertRaises(parakeet.NotAvailable):
            self.fetch(bad)
        self.assertFalse((self.tmp / "models" / "m").exists())
        self.assertEqual(self.leftovers(), [])
        self.assertFalse((self.tmp / "models" / "escape").exists())

    def test_a_truncated_download_is_refused_by_size(self):
        archive = _good_archive(self.tmp / "a.tar.bz2")
        with self.assertRaises(parakeet.NotAvailable) as raised:
            self.fetch(archive, expected_bytes=archive.stat().st_size + 1)
        self.assertIn("bytes", str(raised.exception))
        self.assertFalse((self.tmp / "models" / "m").exists())

    def test_a_server_that_is_not_there_is_a_reason_not_a_traceback(self):
        with self.assertRaises(parakeet.NotAvailable) as raised:
            self.fetch(self.tmp / "does-not-exist.tar.bz2")
        self.assertIn("download failed", str(raised.exception))

    def test_a_broken_earlier_copy_is_replaced(self):
        dest = self.tmp / "models" / "m"
        dest.mkdir(parents=True)
        (dest / "junk").write_bytes(b"half")
        self.fetch(_good_archive(self.tmp / "a.tar.bz2"))
        self.assertTrue(parakeet.model_present(dest))
        self.assertFalse((dest / "junk").exists())

    def test_a_cancel_mid_download_leaves_no_partial_model_and_no_scratch(self):
        archive = _good_archive(self.tmp / "a.tar.bz2")
        asked = []

        def cancelled():
            asked.append(1)
            return len(asked) > 2  # let two chunks through, then stop

        with mock.patch.object(parakeet, "_CHUNK", 8):
            with self.assertRaises(parakeet.Cancelled):
                self.fetch(archive, cancelled=cancelled)
        self.assertGreaterEqual(len(asked), 3)  # asked per chunk, not once
        self.assertFalse((self.tmp / "models" / "m").exists())
        self.assertEqual(self.leftovers(), [])

    def test_a_cancel_after_the_download_stops_before_anything_is_installed(self):
        archive = _good_archive(self.tmp / "a.tar.bz2")
        # False through every chunk and the end-of-stream read, true at the unpack gate.
        chunks = archive.stat().st_size // parakeet._CHUNK + 2
        answers = iter([False] * chunks + [True])
        with self.assertRaises(parakeet.Cancelled):
            self.fetch(archive, cancelled=lambda: next(answers, True))
        self.assertFalse((self.tmp / "models" / "m").exists())
        self.assertEqual(self.leftovers(), [])

    def test_a_cancel_keeps_an_earlier_good_copy(self):
        dest = _model_dir(self.tmp / "models" / "m")
        with self.assertRaises(parakeet.Cancelled):
            self.fetch(_good_archive(self.tmp / "a.tar.bz2"), cancelled=lambda: True)
        self.assertTrue(parakeet.model_present(dest))

    def test_cancelled_is_not_a_failure(self):
        self.assertFalse(issubclass(parakeet.Cancelled, parakeet.NotAvailable))

    def test_the_size_on_disk_is_the_four_files(self):
        self.assertEqual(parakeet.installed_bytes(self.tmp / "nope"), 0)
        self.assertEqual(parakeet.installed_bytes(_model_dir(self.tmp / "m")), len(NAMES))

    def test_the_constants_say_what_was_measured(self):
        self.assertEqual(parakeet.ARCHIVE_BYTES, 487_170_055)
        self.assertTrue(parakeet.URL.startswith("https://github.com/k2-fsa/"))
        self.assertTrue(parakeet.URL.endswith(parakeet.MODEL_NAME + ".tar.bz2"))


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
    def run_engine(self, installed=(True, ""), present=True, fetch=None):
        said = []
        with mock.patch.object(parakeet, "runtime_installed", return_value=installed), \
                mock.patch.object(parakeet, "model_present", return_value=present), \
                mock.patch.object(parakeet, "fetch", fetch or mock.Mock()) as fetching, \
                mock.patch("flow.__main__.say", said.append):
            got = _engine(_args("parakeet"), "base.en", "small.en")
        return got, said, fetching

    def test_ready_means_parakeet_and_the_startup_line_can_say_why(self):
        (engine, why), said, fetching = self.run_engine()
        self.assertEqual(engine, "parakeet")
        self.assertIn("--engine parakeet", why)
        fetching.assert_not_called()

    def test_a_missing_runtime_falls_back_to_whisper_out_loud(self):
        (engine, _why), said, fetching = self.run_engine(
            installed=(False, "sherpa-onnx is not installed - run: uv pip install x"))
        self.assertEqual(engine, "whisper")
        text = " ".join(said)
        self.assertIn("sherpa-onnx is not installed", text)
        self.assertIn("using whisper", text)
        fetching.assert_not_called()  # no point downloading 465 MB for a runtime it lacks

    def test_a_missing_model_is_fetched_and_the_size_is_said_first(self):
        (engine, _why), said, fetching = self.run_engine(present=False)
        self.assertEqual(engine, "parakeet")
        fetching.assert_called_once()
        self.assertIn("465 MB", said[0])
        self.assertIn("github.com", said[0])

    def test_a_failed_download_falls_back_with_the_reason(self):
        boom = mock.Mock(side_effect=parakeet.NotAvailable("download failed: offline"))
        (engine, _why), said, _f = self.run_engine(present=False, fetch=boom)
        self.assertEqual(engine, "whisper")
        self.assertIn("download failed: offline", " ".join(said))

    def test_progress_is_a_line_per_tenth_not_per_megabyte(self):
        def fake_fetch(progress=None, **_kw):
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

    def ready(self, runtime=(True, ""), model=True):
        return (mock.patch.object(parakeet, "runtime_installed", return_value=runtime),
                mock.patch.object(parakeet, "model_present", return_value=model),
                mock.patch.object(parakeet, "fetch"))

    def pick(self, engine, saved, runtime=(True, ""), model=True, platform="win32",
             whisper_here=True, native=(False, "no")):
        said = []
        a, b, c = self.ready(runtime, model)
        with a, b, c as fetching, mock.patch.object(sys, "platform", platform),                 mock.patch("flow.__main__.say", said.append),                 mock.patch("flow.__main__._models_present", return_value=whisper_here),                 mock.patch("flow.native.available", return_value=native):
            got = _engine(_args(engine), "base.en", "small.en", saved=saved)
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
        # ...native on a Mac with no Whisper models included.
        (engine, why), _s, _f = self.pick("auto", "whisper", platform="darwin",
                                          whisper_here=False, native=(True, ""))
        self.assertEqual(engine, "native")
        self.assertIn("models not found", why)

    def test_a_saved_parakeet_whose_runtime_is_gone_falls_back_and_says_why(self):
        (engine, _w), said, fetching = self.pick(
            "auto", "parakeet", runtime=(False, "sherpa-onnx is not installed"))
        self.assertEqual(engine, "whisper")
        self.assertIn("sherpa-onnx is not installed", " ".join(said))
        self.assertIn("Models page", " ".join(said))
        fetching.assert_not_called()

    def test_a_saved_parakeet_whose_model_is_gone_never_blocks_launch_on_a_download(self):
        (engine, _w), said, fetching = self.pick("auto", "parakeet", model=False)
        self.assertEqual(engine, "whisper")
        fetching.assert_not_called()  # the page offers it; the launch does not wait on it
        self.assertIn("downloads it", " ".join(said))
        self.assertTrue(all(s.isascii() for s in said))

    def test_the_explicit_flag_still_downloads_as_before(self):
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


_HAS_SHERPA = parakeet.runtime_installed()[0]


@unittest.skipUnless(_HAS_SHERPA, "the parakeet extra is not installed")
class TestParakeetReal(unittest.TestCase):
    """The real package, when this machine has it. Skipped everywhere else.

    The contract with someone else's code that the fakes above cannot check: that
    `OfflineRecognizer.from_transducer` still takes the arguments `load()` passes. No
    model is loaded, so this works on a machine that installed the extra and never
    downloaded the model.
    """

    def test_the_constructor_still_takes_what_load_passes(self):
        import inspect

        import sherpa_onnx

        params = inspect.signature(sherpa_onnx.OfflineRecognizer.from_transducer).parameters
        for name in ("encoder", "decoder", "joiner", "tokens", "model_type",
                     "num_threads", "provider"):
            self.assertIn(name, params)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
