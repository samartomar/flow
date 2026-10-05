"""Parakeet on the GPU: parakeet.cpp's server as a helper process, and everything around it.

No real executable, no model and no network. The server is a small Python script that speaks
the same protocol (one `POST /v1/audio/transcriptions`, a `listening on` line when it is
ready, `--host`/`--port`/`--model`), run as a real subprocess so that what is asserted is the
process boundary itself: the arguments it is launched with, that it is waited for and timed
out, that a crash becomes a sentence, that stopping it ends it, and that a binary which is not
the pinned one is never run. Downloads go through `file://` URLs against shrunk tables.

What carries the feature, in the order a launch meets it:

  **Nothing unverified runs.** The helper is a downloaded executable. Its SHA-256 is pinned in
  the source and checked before every launch, and the release zip is checked before anything is
  taken out of it - and only two files are.

  **The helper cannot outlive Flow, and cannot listen on the network.** It is bound to 127.0.0.1
  with `--host`, and tied to the process with a Windows Job Object so a hard kill of Flow takes
  it too.

  **The backend is chosen by what is here**, CUDA when the NVIDIA runtime and a GPU are, else
  Vulkan, else none with the reason.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.parakeet as parakeet  # noqa: E402
from flow.clean import WORD_CONF_MIN, invented_reason  # noqa: E402

#: Speaks parakeet-server's protocol, as far as Flow uses it. Behaviour is chosen by files
#: beside the "model" so a test can change the reply or make it misbehave without a restart:
#: `answer.json` (the reply), `mode.txt` ("oom", "crash", "slow", "die-after-first").
FAKE_SERVER = textwrap.dedent('''
    import json, sys, time
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path

    args = sys.argv[1:]
    opt = {args[i]: args[i + 1] for i in range(0, len(args) - 1, 2) if args[i].startswith("--")}
    model = Path(opt["--model"])
    mode = (model.parent / "mode.txt").read_text().strip() if (model.parent / "mode.txt").exists() else ""
    (model.parent / "argv.json").write_text(json.dumps(sys.argv[1:]))
    if mode == "oom":
        print("ggml_cuda: cudaMalloc failed: out of memory", flush=True)
        sys.exit(1)
    if mode == "crash":
        print("something broke in the loader", flush=True)
        sys.exit(3)
    if mode == "slow":
        time.sleep(60)
    served = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            global served
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            served += 1
            if mode == "die-after-first" and served >= 2:
                import os
                os._exit(7)
            (model.parent / "last_request.bin").write_bytes(body)
            reply = (model.parent / "answer.json").read_text() if (model.parent / "answer.json").exists() else '{"text": "", "words": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply.encode())

    server = HTTPServer((opt["--host"], int(opt["--port"])), Handler)
    print(f"parakeet-server: listening on http://{opt['--host']}:{opt['--port']} (model: {model})", flush=True)
    server.serve_forever()
''')


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Case(unittest.TestCase):
    """A temp `~/.flow/models`, tiny pinned tables, and a fake server script."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.models = self.tmp / "models"
        self.exe_bytes = b"MZ fake server executable"
        self.zip_bytes = self.make_zip()
        runtime = parakeet.Runtime(
            "vulkan",
            parakeet.File("release-vulkan.zip", len(self.zip_bytes), _sha(self.zip_bytes)),
            _sha(self.exe_bytes), len(self.exe_bytes))
        self.model_bytes = b"gguf" * 8
        variant = parakeet.Variant(
            "gpu", "parakeet-tdt-0.6b-v3-gpu", None,
            (parakeet.File("m.gguf", len(self.model_bytes), _sha(self.model_bytes)),),
            repo=parakeet.VARIANTS["gpu"].repo, revision=parakeet.VARIANTS["gpu"].revision,
            runtime="gpu")
        for patcher in (
                mock.patch.object(parakeet, "MODELS_DIR", self.models),
                mock.patch.dict(parakeet.RUNTIMES, {"vulkan": runtime}),
                mock.patch.dict(parakeet.VARIANTS, {"gpu": variant}),
                mock.patch.object(parakeet, "gpu_backend", return_value=("vulkan", ""))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runtime = runtime
        self.variant = variant

    def make_zip(self, extra=None, exe=None) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr("parakeet-v0.5.0-bin-win-vulkan-x64/parakeet-server.exe",
                        exe if exe is not None else self.exe_bytes)
            zf.writestr("parakeet-v0.5.0-bin-win-vulkan-x64/LICENSE", "MIT\n")
            zf.writestr("parakeet-v0.5.0-bin-win-vulkan-x64/README.md", "readme")
            zf.writestr("parakeet-v0.5.0-bin-win-vulkan-x64/parakeet-cli.exe", b"cli")
            for name, data in (extra or {}).items():
                zf.writestr(name, data)
        return out.getvalue()

    # -- fixtures ------------------------------------------------------------

    def install_runtime(self, exe_bytes=None):
        root = parakeet.runtime_dir("vulkan")
        root.mkdir(parents=True)
        (root / parakeet.SERVER_EXE).write_bytes(exe_bytes or self.exe_bytes)
        (root / "LICENSE").write_text("MIT\n")
        return root

    def install_model(self):
        root = parakeet.variant_dir("gpu")
        root.mkdir(parents=True, exist_ok=True)
        (root / "m.gguf").write_bytes(self.model_bytes)
        return root

    def served(self):
        """A fake server standing in for the executable: `(exe script, prefix)`."""
        script = self.tmp / "fake_server.py"
        script.write_text(FAKE_SERVER, encoding="utf-8")
        return script, [sys.executable]

    def helper(self, mode="", answer=None):
        script, prefix = self.served()
        model_dir = self.install_model()
        if mode:
            (model_dir / "mode.txt").write_text(mode)
        if answer is not None:
            (model_dir / "answer.json").write_text(json.dumps(answer))
        helper = parakeet._Helper(script, model_dir / "m.gguf", prefix=prefix)
        self.addCleanup(helper.stop)
        return helper, model_dir

    def starter(self, mode="", answer=None):
        """A `starter` for the transcriber that really spawns the fake server."""
        script, prefix = self.served()
        model_dir = self.install_model()
        if mode:
            (model_dir / "mode.txt").write_text(mode)
        if answer is not None:
            (model_dir / "answer.json").write_text(json.dumps(answer))
        made = []

        def start(backend, directory):
            helper = parakeet._Helper(script, model_dir / "m.gguf", prefix=prefix)
            helper.start(timeout=20)
            made.append(helper)
            return helper

        self.addCleanup(lambda: [h.stop() for h in made])
        return start, made, model_dir


def _answer(text, confs):
    words = [{"word": w, "start": 0.0, "end": 0.1, "conf": c}
             for w, c in zip(text.split(), confs)]
    return {"task": "transcribe", "text": text, "words": words}


class TestTheHelperProcess(_Case):
    def test_it_is_launched_bound_to_loopback_on_a_free_port_with_the_model(self):
        helper, model_dir = self.helper(answer=_answer("hello world", [0.9, 0.9]))
        helper.start(timeout=20)
        argv = json.loads((model_dir / "argv.json").read_text())
        opts = dict(zip(argv[::2], argv[1::2]))
        self.assertEqual(opts["--host"], "127.0.0.1")  # never the LAN
        self.assertEqual(opts["--model"], str(model_dir / "m.gguf"))
        self.assertEqual(int(opts["--port"]), helper.port)
        self.assertGreater(helper.port, 1023)
        self.assertEqual(helper.argv()[helper.argv().index("--host") + 1], "127.0.0.1")

    def test_a_decode_posts_a_wav_and_asks_for_word_confidences(self):
        helper, model_dir = self.helper(answer=_answer("hello world", [0.9, 0.8]))
        helper.start(timeout=20)
        answer = helper.recognise(np.full(1600, 0.1, dtype=np.float32))
        self.assertEqual(answer["text"], "hello world")
        sent = (model_dir / "last_request.bin").read_bytes()
        self.assertIn(b'name="response_format"', sent)
        self.assertIn(b"verbose_json", sent)
        self.assertIn(b'name="timestamp_granularities[]"', sent)  # without it: no confidences
        self.assertIn(b"RIFF", sent)
        self.assertIn(b"WAVE", sent)

    def test_the_audio_is_16_bit_mono_16k(self):
        import wave

        wav = parakeet._wav(np.array([0.0, 1.0, -1.0, 0.5], dtype=np.float32))
        with wave.open(io.BytesIO(wav)) as handle:
            self.assertEqual((handle.getnchannels(), handle.getsampwidth(),
                              handle.getframerate()), (1, 2, 16000))
            frames = np.frombuffer(handle.readframes(4), dtype="<i2")
        self.assertEqual(list(frames), [0, 32767, -32767, 16383])

    def test_it_waits_for_the_helper_to_say_it_is_listening_and_gives_up_after_the_bound(self):
        helper, _ = self.helper(mode="slow")
        started = time.monotonic()
        with self.assertRaises(parakeet.NotAvailable) as raised:
            helper.start(timeout=1.0)
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn("did not start", str(raised.exception))
        self.assertFalse(helper.alive)  # and it was not left running

    def test_out_of_video_memory_is_said_as_that(self):
        helper, _ = self.helper(mode="oom")
        with self.assertRaises(parakeet.NotAvailable) as raised:
            helper.start(timeout=20)
        self.assertIn("not enough video memory", str(raised.exception))

    def test_any_other_crash_carries_the_exit_code_and_its_last_words(self):
        helper, _ = self.helper(mode="crash")
        with self.assertRaises(parakeet.NotAvailable) as raised:
            helper.start(timeout=20)
        text = str(raised.exception)
        self.assertIn("exit 3", text)
        self.assertIn("something broke in the loader", text)

    def test_stopping_it_ends_the_process_and_is_idempotent(self):
        helper, _ = self.helper()
        helper.start(timeout=20)
        proc = helper.proc
        helper.stop()
        self.assertIsNotNone(proc.poll())
        self.assertFalse(helper.alive)
        helper.stop()  # twice is not an error

    def test_a_missing_executable_is_a_reason_not_a_traceback(self):
        helper = parakeet._Helper(self.tmp / "nope.exe", self.tmp / "m.gguf")
        with self.assertRaises(parakeet.NotAvailable) as raised:
            helper.start(timeout=5)
        self.assertIn("could not start", str(raised.exception))

    def test_the_cuda_runtime_dirs_go_on_the_helpers_path_and_only_its(self):
        seen = {}
        real = subprocess.Popen

        def spy(argv, **kwargs):
            seen.update(kwargs.get("env") or {})
            return real(argv, **kwargs)

        script, prefix = self.served()
        model_dir = self.install_model()
        helper = parakeet._Helper(script, model_dir / "m.gguf", ["C:\\cuda\\bin"], prefix)
        self.addCleanup(helper.stop)
        with mock.patch("subprocess.Popen", spy):
            helper.start(timeout=20)
        self.assertTrue(seen["PATH"].startswith("C:\\cuda\\bin" + os.pathsep))


@unittest.skipUnless(sys.platform == "win32", "Windows Job Objects")
class TestItDiesWithFlow(unittest.TestCase):
    def test_a_hard_killed_parent_takes_its_helper_with_it(self):
        parent_code = textwrap.dedent('''
            import subprocess, sys, time
            sys.path.insert(0, sys.argv[1])
            from flow import parakeet
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            ok = parakeet._bind_to_job(child)
            print(child.pid, ok, flush=True)
            time.sleep(120)
        ''')
        root = str(Path(__file__).resolve().parent.parent)
        parent = subprocess.Popen([sys.executable, "-c", parent_code, root],
                                  stdout=subprocess.PIPE, text=True)
        self.addCleanup(parent.kill)
        self.addCleanup(parent.stdout.close)
        pid, ok = parent.stdout.readline().split()
        self.assertEqual(ok, "True")  # the OS accepted the job
        self.assertTrue(self.running(pid))
        parent.kill()  # a hard kill: no atexit, no finally, no goodbye
        deadline = time.time() + 15
        while self.running(pid) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(self.running(pid), "the helper outlived Flow")

    @staticmethod
    def running(pid) -> bool:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out

    def test_it_is_not_attempted_off_windows(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(parakeet._bind_to_job(mock.Mock()))


class TestNothingUnverifiedRuns(_Case):
    def test_a_runtime_that_is_the_pinned_one_verifies(self):
        self.install_runtime()
        self.assertEqual(parakeet.verify_runtime("vulkan"),
                         parakeet.runtime_dir("vulkan") / parakeet.SERVER_EXE)

    def test_a_tampered_executable_is_refused_before_any_process_exists(self):
        root = self.install_runtime(exe_bytes=b"MZ fake server executXble")  # same size
        self.assertEqual(len(b"MZ fake server executXble"), self.runtime.exe_bytes)
        with mock.patch("subprocess.Popen") as spawn:
            with self.assertRaises(parakeet.NotAvailable) as raised:
                parakeet.start_helper("vulkan", self.install_model())
        spawn.assert_not_called()  # the file was never executed
        self.assertIn("does not match", str(raised.exception))
        self.assertIn(str(root), str(raised.exception))

    def test_it_is_checked_on_every_launch_not_once_at_install(self):
        self.install_runtime()
        parakeet.verify_runtime("vulkan")
        (parakeet.runtime_dir("vulkan") / parakeet.SERVER_EXE).write_bytes(
            b"MZ fake server executXble")
        with self.assertRaises(parakeet.NotAvailable):
            parakeet.verify_runtime("vulkan")

    def test_a_truncated_executable_is_not_even_present(self):
        self.install_runtime(exe_bytes=b"MZ")
        self.assertFalse(parakeet.runtime_present("vulkan"))
        with self.assertRaises(parakeet.NotAvailable):
            parakeet.verify_runtime("vulkan")

    def test_the_pinned_hashes_are_real_ones(self):
        for backend, runtime in (("cuda", parakeet.RUNTIMES["cuda"]),):
            self.assertEqual(len(runtime.exe_sha256), 64, backend)
            self.assertEqual(len(runtime.zip.sha256), 64, backend)

    def test_the_helper_is_warmed_and_marked_once_it_has_started(self):
        self.install_runtime()
        model_dir = self.install_model()
        (model_dir / "answer.json").write_text(json.dumps(_answer("x", [0.9])))
        script, prefix = self.served()
        real = parakeet._Helper

        def helper_with_prefix(exe, model, env_dirs=None, prefix_=None):
            return real(script, model, env_dirs, prefix)

        with mock.patch.object(parakeet, "_Helper", helper_with_prefix):
            helper = parakeet.start_helper("vulkan", model_dir)
        self.addCleanup(helper.stop)
        self.assertTrue(helper.alive)
        self.assertTrue((parakeet.runtime_dir("vulkan") / parakeet.LOADED_MARKER).exists())
        self.assertTrue((model_dir / "last_request.bin").exists())  # the warm-up decode


class TestTheGpuTranscriber(_Case):
    def audio(self):
        return np.full(1600, 0.1, dtype=np.float32)

    def make(self, mode="", answer=None):
        start, made, model_dir = self.starter(mode, answer)
        t = parakeet.ParakeetGpuTranscriber("vulkan", starter=start)
        self.addCleanup(t.unload)
        return t, made, model_dir

    def test_it_satisfies_the_surface_the_session_reads(self):
        t, _, _ = self.make()
        for name in ("text", "load", "unload", "take_drops"):
            self.assertTrue(callable(getattr(t, name)), name)
        self.assertEqual((t.engine, t.variant), ("parakeet", "gpu"))
        self.assertIsNone(getattr(t, "take_confidence", None))
        self.assertEqual((t.backend, t.device), ("vulkan", "vulkan"))

    def test_text_comes_back_from_the_helper(self):
        t, _, _ = self.make(answer=_answer("hello world", [0.95, 0.9]))
        self.assertEqual(t.text(self.audio()), "hello world")
        self.assertEqual(t.take_drops(), [])

    def test_loading_starts_the_process_once_and_unloading_ends_it(self):
        t, made, _ = self.make(answer=_answer("a", [0.9]))
        self.assertFalse(t.loaded)
        t.load()
        t.load()  # idempotent
        self.assertTrue(t.loaded)
        self.assertEqual(len(made), 1)
        proc = made[0].proc
        t.unload()
        self.assertFalse(t.loaded)
        self.assertIsNotNone(proc.poll())  # the GPU's memory is what this gives back
        t.unload()

    def test_loading_is_true_only_while_the_process_is_starting(self):
        seen = []
        start, made, _ = self.starter(answer=_answer("a", [0.9]))
        t = parakeet.ParakeetGpuTranscriber(
            "vulkan", starter=lambda b, d: (seen.append(t.loading), start(b, d))[1])
        self.addCleanup(t.unload)
        t.load()
        self.assertEqual(seen, [True])
        self.assertFalse(t.loading)

    def test_hotwords_and_final_are_accepted_and_ignored(self):
        t, _, _ = self.make(answer=_answer("hello", [0.9]))
        self.assertEqual(t.text(self.audio(), final=True, hotwords="Kubernetes"), "hello")

    def test_a_low_confidence_decode_is_dropped_with_its_evidence(self):
        t, _, _ = self.make(answer=_answer("Ha ha", [0.3, 0.3]))
        self.assertEqual(t.text(self.audio(), final=True), "")
        drops = t.take_drops()
        self.assertEqual([d.reason for d in drops], ["unconfident-words"])
        self.assertAlmostEqual(drops[0].conf, 0.3)
        self.assertIsNone(drops[0].avg_logprob)
        self.assertIn("conf=0.30", drops[0].describe())
        self.assertNotIn("Ha ha", drops[0].announce())  # never read the invention back
        self.assertEqual(t.take_drops(), [])

    def test_speech_at_the_measured_worst_percentile_is_kept(self):
        # p1 of 300 EdAcc clips: 0.52-0.53.
        t, _, _ = self.make(answer=_answer("I need to send the email", [0.53] * 6))
        self.assertEqual(t.text(self.audio()), "I need to send the email")

    def test_silence_answered_with_nothing_records_nothing(self):
        t, _, _ = self.make(answer={"text": "", "words": []})
        self.assertEqual(t.text(self.audio()), "")
        self.assertEqual(t.take_drops(), [])

    def test_a_filler_is_still_caught_by_the_list(self):
        t, _, _ = self.make(answer=_answer("Okay.", [0.39]))
        self.assertEqual(t.text(self.audio()), "")
        self.assertEqual([d.reason for d in t.take_drops()], ["filler"])

    def test_a_helper_that_dies_mid_session_is_a_sentence_and_the_next_decode_restarts_it(self):
        t, made, _ = self.make(mode="die-after-first", answer=_answer("hello", [0.9]))
        self.assertEqual(t.text(self.audio()), "hello")  # the warm-up was the first request
        with self.assertRaises(parakeet.NotAvailable) as raised:
            t.text(self.audio())
        self.assertIn("exit 7", str(raised.exception))
        self.assertFalse(t.loaded)
        # ...and the next utterance starts a fresh one rather than staying broken.
        t.load()
        self.assertEqual(len(made), 2)

    def test_no_backend_is_a_reason(self):
        t = parakeet.ParakeetGpuTranscriber(starter=mock.Mock())
        with mock.patch.object(parakeet, "gpu_backend", return_value=("", "no GPU here")):
            with self.assertRaises(parakeet.NotAvailable) as raised:
                t.load()
        self.assertIn("no GPU here", str(raised.exception))
        self.assertFalse(t.loading)

    def test_make_transcriber_picks_the_build_the_profile_resolves_to(self):
        self.install_model()
        self.install_runtime()
        self.assertIsInstance(parakeet.make_transcriber("gpu"), parakeet.ParakeetGpuTranscriber)
        self.assertIsInstance(parakeet.make_transcriber("auto"), parakeet.ParakeetGpuTranscriber)
        self.assertEqual(type(parakeet.make_transcriber("int8")), parakeet.ParakeetTranscriber)

    def test_word_confidence_is_the_mean_and_never_a_fabricated_one(self):
        self.assertAlmostEqual(parakeet.mean_word_conf([{"conf": 0.5}, {"conf": 1.0}]), 0.75)
        self.assertIsNone(parakeet.mean_word_conf([]))
        self.assertIsNone(parakeet.mean_word_conf(None))
        self.assertIsNone(parakeet.mean_word_conf([{"word": "x"}]))


class TestTheGate(unittest.TestCase):
    def test_a_confidence_below_the_bar_is_dropped_and_named(self):
        self.assertEqual(invented_reason("Ha ha", None, None, None, None, 0.30),
                         "unconfident-words")
        self.assertEqual(invented_reason("Ha ha", mean_word_conf=WORD_CONF_MIN - 0.01),
                         "unconfident-words")

    def test_at_or_above_it_is_kept(self):
        self.assertIsNone(invented_reason("I need the report", mean_word_conf=WORD_CONF_MIN))
        self.assertIsNone(invented_reason("I need the report", mean_word_conf=0.53))

    def test_no_reading_is_no_evidence(self):
        self.assertIsNone(invented_reason("I need the report", mean_word_conf=None))

    def test_the_bar_is_the_log_prob_bar_carried_over(self):
        from flow.clean import TOKEN_LOGPROB_MIN
        import math

        self.assertAlmostEqual(WORD_CONF_MIN, math.exp(TOKEN_LOGPROB_MIN), delta=0.005)

    def test_the_two_signals_are_independent_and_whisper_ignores_both(self):
        self.assertEqual(invented_reason("It is.", None, None, None, -1.1, 0.9),
                         "unconfident-tokens")
        for ns in (0.01, 0.9):
            with self.subTest(ns=ns):
                self.assertEqual(
                    invented_reason("I need the report", ns, -0.2, None, -9.0, 0.01),
                    invented_reason("I need the report", ns, -0.2))

    def test_a_reason_the_surfaces_can_say(self):
        from flow.asr import _REASON_WORDS
        from flow.home.api import SET_ASIDE_WHY

        self.assertIn("unconfident-words", _REASON_WORDS)
        self.assertIn("unconfident-words", SET_ASIDE_WHY)


class TestTheBackendChoice(unittest.TestCase):
    def detect(self, platform="win32", nvidia=True, dirs=("C:\\cuda",), vulkan=True):
        with mock.patch.object(sys, "platform", platform), \
                mock.patch.object(parakeet, "_nvidia_present", return_value=nvidia), \
                mock.patch.object(parakeet, "cuda_dirs", return_value=list(dirs)), \
                mock.patch.object(parakeet, "_vulkan_loader", return_value=vulkan):
            return parakeet._detect_backend()

    def test_cuda_when_the_runtime_and_an_nvidia_gpu_are_here(self):
        self.assertEqual(self.detect(), ("cuda", ""))

    def test_vulkan_when_cuda_is_not_installed(self):
        self.assertEqual(self.detect(dirs=()), ("vulkan", ""))

    def test_vulkan_on_a_machine_with_no_nvidia_gpu(self):
        self.assertEqual(self.detect(nvidia=False, dirs=()), ("vulkan", ""))

    def test_none_with_the_fix_named_when_there_is_an_nvidia_gpu_and_nothing_to_run_it(self):
        backend, why = self.detect(dirs=(), vulkan=False)
        self.assertEqual(backend, "")
        self.assertIn('[cuda]', why)

    def test_none_when_there_is_no_gpu_driver_at_all(self):
        backend, why = self.detect(nvidia=False, dirs=(), vulkan=False)
        self.assertEqual(backend, "")
        self.assertIn("no GPU", why)

    def test_windows_only_for_now(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                backend, why = self.detect(platform=platform)
                self.assertEqual(backend, "")
                self.assertIn("Windows", why)

    def test_the_answer_is_remembered(self):
        with mock.patch.object(parakeet, "_backend_cache", None), \
                mock.patch.object(parakeet, "_detect_backend",
                                  return_value=("vulkan", "")) as detect:
            parakeet.gpu_backend()
            parakeet.gpu_backend()
        detect.assert_called_once()


class TestTheCudaRuntimeIsFoundInTheWheels(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def wheel(self, name, dlls):
        d = self.tmp / name
        d.mkdir()
        for dll in dlls:
            (d / dll).write_bytes(b"")
        return str(d)

    def test_the_three_dlls_across_the_wheels_are_enough(self):
        dirs = [self.wheel("cublas", ["cublas64_12.dll", "cublasLt64_12.dll"]),
                self.wheel("cuda_runtime", ["cudart64_12.dll"])]
        with mock.patch("flow.asr._wheel_dll_dirs", return_value=dirs), \
                mock.patch("shutil.which", return_value=None):
            self.assertEqual(parakeet.cuda_dirs(), sorted(dirs))

    def test_one_missing_means_none(self):
        dirs = [self.wheel("cublas", ["cublas64_12.dll", "cublasLt64_12.dll"])]
        with mock.patch("flow.asr._wheel_dll_dirs", return_value=dirs), \
                mock.patch("shutil.which", return_value=None):
            self.assertEqual(parakeet.cuda_dirs(), [])

    def test_a_system_cuda_install_on_path_counts(self):
        sysdir = self.wheel("toolkit", list(parakeet.CUDA_DLLS))
        with mock.patch("flow.asr._wheel_dll_dirs", return_value=[]), \
                mock.patch("shutil.which",
                           side_effect=lambda name: str(Path(sysdir) / name)):
            self.assertEqual(parakeet.cuda_dirs(), [sysdir])

    def test_the_wheel_the_extra_adds_is_the_runtime_dll(self):
        self.assertIn("cudart64_12.dll", parakeet.CUDA_DLLS)
        text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
            encoding="utf-8")
        self.assertIn("nvidia-cuda-runtime-cu12", text)
        self.assertIn("nvidia-cublas-cu12", text)


class TestTheDownloads(_Case):
    def urls(self):
        (self.tmp / "serve").mkdir(exist_ok=True)
        (self.tmp / "serve" / self.runtime.zip.name).write_bytes(self.zip_bytes)
        (self.tmp / "serve" / "m.gguf").write_bytes(self.model_bytes)
        return (lambda name: (self.tmp / "serve" / name).as_uri(),)

    def fetch(self, **kw):
        (url,) = self.urls()
        return parakeet.fetch("gpu", backend="vulkan", url_for=url, runtime_url_for=url, **kw)

    def test_both_land_and_the_variant_is_then_present(self):
        dest = self.fetch()
        self.assertEqual(dest, parakeet.variant_dir("gpu"))
        self.assertTrue(parakeet.runtime_present("vulkan"))
        self.assertTrue(parakeet.model_present("gpu"))

    def test_only_the_executable_and_its_licence_are_taken_from_the_zip(self):
        self.fetch()
        names = sorted(p.name for p in parakeet.runtime_dir("vulkan").iterdir())
        self.assertEqual(names, ["LICENSE", parakeet.SERVER_EXE])  # not the cli, not the readme

    def test_a_member_that_climbs_out_is_never_considered(self):
        self.zip_bytes = self.make_zip(extra={"../parakeet-server.exe": b"evil",
                                              "/abs/LICENSE": b"evil"})
        # The pinned table must describe the new zip for it to be downloaded at all.
        self.runtime = parakeet.Runtime(
            "vulkan", parakeet.File("release-vulkan.zip", len(self.zip_bytes),
                                    _sha(self.zip_bytes)),
            self.runtime.exe_sha256, self.runtime.exe_bytes)
        with mock.patch.dict(parakeet.RUNTIMES, {"vulkan": self.runtime}):
            self.fetch()
        self.assertFalse((self.models / "parakeet-server.exe").exists())
        self.assertFalse((self.tmp / "parakeet-server.exe").exists())
        self.assertEqual((parakeet.runtime_dir("vulkan") / parakeet.SERVER_EXE).read_bytes(),
                         self.exe_bytes)

    def test_a_zip_that_is_not_the_pinned_one_is_refused_before_anything_is_extracted(self):
        (self.tmp / "serve").mkdir()
        (self.tmp / "serve" / self.runtime.zip.name).write_bytes(
            self.zip_bytes[:-1] + b"X")  # same size, different bytes
        (self.tmp / "serve" / "m.gguf").write_bytes(self.model_bytes)
        url = lambda name: (self.tmp / "serve" / name).as_uri()  # noqa: E731
        with self.assertRaises(parakeet.NotAvailable) as raised:
            parakeet.fetch("gpu", backend="vulkan", url_for=url, runtime_url_for=url)
        self.assertIn("checksum", str(raised.exception))
        self.assertFalse(parakeet.runtime_dir("vulkan").exists())
        self.assertFalse(parakeet.variant_dir("gpu").exists())

    def test_an_executable_in_the_zip_that_this_flow_does_not_pin_is_refused(self):
        bad = self.make_zip(exe=b"MZ some other executable!")
        self.runtime = parakeet.Runtime(
            "vulkan", parakeet.File("release-vulkan.zip", len(bad), _sha(bad)),
            self.runtime.exe_sha256, self.runtime.exe_bytes)
        self.zip_bytes = bad
        with mock.patch.dict(parakeet.RUNTIMES, {"vulkan": self.runtime}):
            with self.assertRaises(parakeet.NotAvailable) as raised:
                self.fetch()
        self.assertIn("not the one this Flow pins", str(raised.exception))
        self.assertFalse(parakeet.runtime_dir("vulkan").exists())

    def test_progress_counts_both_downloads_as_one_bar(self):
        seen = []
        self.fetch(progress=lambda done, total: seen.append((done, total)))
        total = self.runtime.zip.size + self.variant.bytes
        self.assertEqual({t for _, t in seen}, {total})
        self.assertEqual(seen[-1][0], total)
        self.assertEqual([d for d, _ in seen], sorted(d for d, _ in seen))

    def test_what_is_already_here_is_not_fetched_again(self):
        self.install_runtime()
        seen = []
        self.fetch(progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (self.variant.bytes, self.variant.bytes))  # no zip in it
        # A model that is here is not re-downloaded for the sake of a helper either.
        seen.clear()
        shutil_rmtree(parakeet.runtime_dir("vulkan"))
        self.fetch(progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (self.runtime.zip.size, self.runtime.zip.size))

    def test_a_cancel_leaves_nothing_behind(self):
        asked = []

        def cancelled():
            asked.append(1)
            return len(asked) > 1

        with mock.patch.object(parakeet, "_CHUNK", 8):
            with self.assertRaises(parakeet.Cancelled):
                self.fetch(cancelled=cancelled)
        self.assertFalse(parakeet.runtime_dir("vulkan").exists())
        self.assertFalse(parakeet.variant_dir("gpu").exists())
        leftovers = [p for p in self.models.iterdir()] if self.models.exists() else []
        self.assertEqual(leftovers, [])

    def test_no_backend_is_a_reason(self):
        with mock.patch.object(parakeet, "gpu_backend", return_value=("", "no GPU here")):
            with self.assertRaises(parakeet.NotAvailable) as raised:
                parakeet.fetch("gpu")
        self.assertIn("no GPU here", str(raised.exception))

    def test_the_default_sources_are_the_pinned_tag_and_commit(self):
        self.assertEqual(
            parakeet.release_url("parakeet-v0.5.0-bin-win-cuda-x64.zip"),
            "https://github.com/mudler/parakeet.cpp/releases/download/v0.5.0/"
            "parakeet-v0.5.0-bin-win-cuda-x64.zip")
        v = parakeet.VARIANTS["gpu"]
        self.assertEqual(parakeet.hub_url("m.gguf", v.repo, v.revision),
                         f"https://huggingface.co/mudler/parakeet-cpp-gguf/resolve/{v.revision}/m.gguf")
        self.assertNotIn("/main/", parakeet.hub_url("m.gguf", v.repo, v.revision))

    def test_the_default_url_for_the_helper_is_a_release_asset_and_for_the_model_the_hub(self):
        seen = []

        def refuse(request, timeout=None):
            seen.append(request.full_url)
            raise OSError("no network in tests")

        with mock.patch("urllib.request.urlopen", refuse):
            with self.assertRaises(parakeet.NotAvailable):
                parakeet.fetch("gpu", backend="vulkan")
        self.assertEqual(seen, [parakeet.release_url(self.runtime.zip.name)])
        self.assertTrue(seen[0].startswith("https://github.com/mudler/parakeet.cpp/"))


def shutil_rmtree(path):
    import shutil

    shutil.rmtree(path)


class TestTheShippedGpuTables(unittest.TestCase):
    def test_the_sizes_and_pins_are_what_was_published(self):
        gpu = parakeet.VARIANTS["gpu"]
        self.assertEqual(gpu.bytes, 940_663_680)
        self.assertEqual(gpu.files[0].name, "tdt-0.6b-v3-q8_0.gguf")
        self.assertEqual(gpu.files[0].sha256,
                         "4d69a4a6683f4f2d952bad794c1357ca6eb628027695b4699c5a9ad4cd07d757")
        self.assertEqual(gpu.revision, "741158ae71e64ef5c89385862c18f777d07a97a1")
        self.assertEqual(gpu.runtime, "gpu")
        self.assertEqual(parakeet.RUNTIMES["cuda"].zip.size, 312_914_549)
        self.assertEqual(parakeet.RUNTIMES["vulkan"].zip.size, 35_828_324)
        self.assertEqual(parakeet.RUNTIMES["cuda"].zip.sha256,
                         "0c90f619a368e67418596231470e916fda60118180879e4334d29d9b0df93b21")
        self.assertEqual(parakeet.RUNTIMES["vulkan"].zip.sha256,
                         "717c416fab299755e8140137e3a0115121ce1acb6379d13c60f2f0613f6c13a3")
        self.assertEqual(parakeet.CPP_VERSION, "v0.5.0")

    def test_the_helpers_live_beside_the_models_under_a_versioned_name(self):
        self.assertEqual(parakeet.RUNTIMES["cuda"].dirname, "parakeet-cpp-v0.5.0-cuda")
        self.assertEqual(parakeet.RUNTIMES["vulkan"].dirname, "parakeet-cpp-v0.5.0-vulkan")

    def test_the_one_url_opener_is_still_this_module(self):
        # tests/test_version.py counts modules that hold one; this file is why it is two.
        src = (Path(__file__).resolve().parent.parent / "flow" / "parakeet.py").read_text(
            encoding="utf-8")
        self.assertEqual(src.count("urllib.request.urlopen("), 1)


class TestTheGpuVariantIsAProfileChoice(_Case):
    def test_it_is_a_choice_and_auto_prefers_it_when_it_is_here(self):
        from flow.profile import PARAKEET_MODELS

        self.assertIn("gpu", PARAKEET_MODELS)
        self.assertEqual(PARAKEET_MODELS, parakeet.VARIANT_CHOICES)
        self.install_runtime()
        self.install_model()
        self.assertEqual(parakeet.resolve_variant("auto"), "gpu")
        self.assertEqual(parakeet.resolve_variant("fp32"), "fp32")  # an explicit choice wins

    def test_auto_skips_it_when_there_is_no_backend_even_with_the_files(self):
        self.install_runtime()
        self.install_model()
        with mock.patch.object(parakeet, "gpu_backend", return_value=("", "no GPU")), \
                mock.patch.object(parakeet, "runtime_installed", return_value=(True, "")):
            self.assertNotEqual(parakeet.resolve_variant("auto"), "gpu")

    def test_the_model_alone_is_not_the_variant_the_helper_is_part_of_it(self):
        self.install_model()
        self.assertFalse(parakeet.model_present("gpu"))
        self.install_runtime()
        self.assertTrue(parakeet.model_present("gpu"))

    def test_a_machine_without_the_addon_is_offered_what_it_can_run(self):
        with mock.patch.object(parakeet, "runtime_installed",
                               return_value=(False, parakeet.INSTALL_HINT)):
            self.assertEqual(parakeet.resolve_variant("auto"), "gpu")
        with mock.patch.object(parakeet, "runtime_installed",
                               return_value=(False, parakeet.INSTALL_HINT)), \
                mock.patch.object(parakeet, "gpu_backend", return_value=("", "none")):
            self.assertEqual(parakeet.resolve_variant("auto"), "fp32")
        with mock.patch.object(parakeet, "runtime_installed", return_value=(True, "")):
            self.assertEqual(parakeet.resolve_variant("auto"), "fp32")

    def test_the_gpu_build_needs_no_addon_and_the_others_still_do(self):
        with mock.patch.object(parakeet, "runtime_installed",
                               return_value=(False, parakeet.INSTALL_HINT)):
            self.assertEqual(parakeet.missing_runtime("gpu"), "")
            self.assertEqual(parakeet.missing_runtime("fp32"), parakeet.ADDON_HINT)
            self.assertEqual(parakeet.missing_runtime("int8"), parakeet.ADDON_HINT)
        with mock.patch.object(parakeet, "gpu_backend", return_value=("", "no GPU here")):
            self.assertEqual(parakeet.missing_runtime("gpu"), "no GPU here")

    def test_the_download_size_adds_the_helper_only_when_it_is_missing(self):
        self.assertEqual(parakeet.download_size("gpu"),
                         self.variant.bytes + self.runtime.zip.size)
        self.install_runtime()
        self.assertEqual(parakeet.download_size("gpu"), self.variant.bytes)
        self.assertEqual(parakeet.download_size("int8"), parakeet.VARIANTS["int8"].bytes)
        self.assertEqual(parakeet.sources("gpu"), "huggingface.co and github.com")
        self.assertEqual(parakeet.sources("fp32"), "huggingface.co")

    def test_the_installed_size_counts_the_helper(self):
        self.install_model()
        self.install_runtime()
        self.assertEqual(parakeet.installed_bytes("gpu"),
                         len(self.model_bytes) + len(self.exe_bytes))

    def test_the_load_estimate_is_honest_about_the_first_cuda_load(self):
        with mock.patch.object(parakeet, "gpu_backend", return_value=("cuda", "")):
            runtime_dir = parakeet.runtime_dir("cuda")
            self.assertEqual(parakeet.load_seconds("gpu"), parakeet.GPU_FIRST_LOAD_SEC["cuda"])
            runtime_dir.mkdir(parents=True)
            (runtime_dir / parakeet.LOADED_MARKER).write_text("x")
            self.assertEqual(parakeet.load_seconds("gpu"), parakeet.GPU_LOAD_SEC["cuda"])
        self.assertEqual(parakeet.load_seconds("gpu"), parakeet.GPU_LOAD_SEC["vulkan"])
        self.assertEqual(parakeet.load_seconds("fp32"), parakeet.LOAD_SEC["fp32"])
        self.assertGreater(parakeet.GPU_FIRST_LOAD_SEC["cuda"], parakeet.GPU_LOAD_SEC["cuda"])


class TestTheMainPathKnowsTheGpuBuild(unittest.TestCase):
    def pick(self, engine, saved, variant, missing="", model=True):
        from flow.__main__ import _engine

        said = []
        with mock.patch.object(parakeet, "missing_runtime", return_value=missing), \
                mock.patch.object(parakeet, "model_present", return_value=model), \
                mock.patch.object(parakeet, "fetch") as fetching, \
                mock.patch.object(parakeet, "download_size", return_value=976_492_004), \
                mock.patch("flow.__main__.say", said.append):
            got = _engine(mock.Mock(engine=engine), "base.en", "small.en", saved=saved,
                          variant=variant)
        return got, said, fetching

    def test_a_saved_gpu_choice_with_no_backend_falls_back_with_the_backends_reason(self):
        (engine, _w), said, fetching = self.pick("auto", "parakeet", "gpu",
                                                 missing="no GPU with a CUDA or Vulkan driver")
        self.assertEqual(engine, "whisper")
        self.assertIn("no GPU with a CUDA or Vulkan driver", " ".join(said))
        fetching.assert_not_called()

    def test_a_saved_gpu_choice_that_is_ready_is_parakeet(self):
        (engine, why), _s, fetching = self.pick("auto", "parakeet", "gpu")
        self.assertEqual(engine, "parakeet")
        fetching.assert_not_called()

    def test_the_flag_downloads_the_gpu_build_saying_both_sources_and_the_total(self):
        (engine, _w), said, fetching = self.pick("parakeet", "whisper", "gpu", model=False)
        self.assertEqual(engine, "parakeet")
        fetching.assert_called_once()
        self.assertEqual(fetching.call_args.args[0], "gpu")
        self.assertIn("huggingface.co and github.com", said[0])
        self.assertIn("931 MB", said[0])
        self.assertTrue(all(s.isascii() for s in said))

    def test_the_factory_builds_the_gpu_transcriber_for_a_gpu_choice(self):
        from flow.__main__ import _parakeet_transcriber

        with mock.patch.object(parakeet, "model_present", return_value=True):
            t = _parakeet_transcriber(None, "gpu")
        self.assertIsInstance(t, parakeet.ParakeetGpuTranscriber)


_HAS_GPU_BUILD = parakeet.model_present("gpu") and parakeet.gpu_backend()[0] != ""


@unittest.skipUnless(_HAS_GPU_BUILD, "the Parakeet GPU build is not installed")
class TestParakeetGpuReal(unittest.TestCase):
    """The real helper and model, when this machine has them. Skipped everywhere else."""

    def test_it_loads_decodes_silence_and_unloads(self):
        t = parakeet.ParakeetGpuTranscriber()
        try:
            t.load()
            self.assertTrue(t.loaded)
            self.assertEqual(t.text(np.zeros(16000, dtype=np.float32)), "")
        finally:
            proc = t._model.proc if t._model is not None else None
            t.unload()
        if proc is not None:
            self.assertIsNotNone(proc.poll())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)


class TestEachBuildSaysWhatItIs(unittest.TestCase):
    """What the trace records about a Parakeet decode: build, pinned model, runtime."""

    def test_the_cpu_builds_name_their_pinned_model_and_runtime(self):
        for key in ("fp32", "int8"):
            got = dict(parakeet.ParakeetTranscriber(key).identity())
            self.assertEqual(got["engine"], f"parakeet-{key}")
            variant = parakeet.VARIANTS[key]
            self.assertEqual(got[f"model:{variant.name}"],
                             variant.revision)
            self.assertIn("onnx-asr", got)
            self.assertIn("onnxruntime", got)

    def test_the_gpu_build_names_the_helper_that_actually_runs(self):
        got = dict(parakeet.ParakeetGpuTranscriber(backend="cuda").identity())
        self.assertEqual(got["engine"], "parakeet-gpu")
        self.assertEqual(got["parakeet.cpp"], f"{parakeet.CPP_VERSION}-cuda")
        # The pinned hash `verify_runtime` refuses to launch without: the binary that ran.
        self.assertEqual(got[parakeet.SERVER_EXE], parakeet.RUNTIMES["cuda"].exe_sha256[:16])
        self.assertNotIn("onnx-asr", got)

    def test_every_value_survives_the_traces_redaction_guard(self):
        # `diag` writes only short tokens; anything else lands as <refused>, which would
        # make the record exist and say nothing.
        from flow.diag import _TOKEN

        for t in (parakeet.ParakeetTranscriber("fp32"), parakeet.ParakeetTranscriber("int8"),
                  parakeet.ParakeetGpuTranscriber(backend="cuda"),
                  parakeet.ParakeetGpuTranscriber(backend="vulkan")):
            for component, version in t.identity():
                self.assertRegex(version, _TOKEN, f"{component}={version!r}")
