"""Better voices from Flow Home (decisions.md 2026-09-23, "Better voices from Flow Home").

Two engines added with a press, and Piper's voices downloaded, on the Models page. Pinned:
the engine specs are the extras' own; the installer is uv, then pip, and never anything in
the Windows download; an install is judged by whether the engine imports afterwards; a
voice is written only once it arrived whole, and a download that did not finish leaves
nothing behind; adding an engine never changes the voice Flow speaks with; and the page
wires every button to the route that does it.
"""

import hashlib
import io
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flow.home import voicepacks as vp  # noqa: E402
from flow.home.voicepacks import ENGINES, Job, PiperVoice, VoicePacks  # noqa: E402

STATIC = ROOT / "flow" / "home" / "static"


def _wait(job, timeout=5.0):
    end = time.time() + timeout
    while job.state == "running" and time.time() < end:
        time.sleep(0.01)
    return job


class _Packs(VoicePacks):
    """VoicePacks over a temporary folder, with the machine's answers set by the test."""

    def __init__(self, folder, *, have=(), command=(["uv", "pip", "install"], ""), **kw):
        super().__init__(None, **kw)
        self.have = set(have)
        self.command = command
        self.dir = Path(folder)

    def _importable(self, module):
        return module in self.have

    def _installer(self, spec):
        cmd, why = self.command
        return (cmd + [spec] if cmd is not None else None), why

    def _folder(self):
        return self.dir


class TestAEnginesAreTheExtrasOwn(unittest.TestCase):

    def test_the_specs_are_what_pyproject_declares(self):
        extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"]["optional-dependencies"]
        for name, about in ENGINES.items():
            with self.subTest(engine=name):
                self.assertIn(about["spec"], extras[about["extra"]])

    def test_the_default_install_still_declares_three(self):
        deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"]["dependencies"]
        self.assertEqual(len(deps), 3)


class TestBTheInstallerIsUvThenPipAndNeverInTheDownload(unittest.TestCase):

    def test_uv_from_uv_run(self):
        with mock.patch.dict("os.environ", {"UV": r"C:\bin\uv.exe"}), \
                mock.patch.object(vp.sys, "frozen", False, create=True):
            cmd, why = vp.installer("piper-tts>=1.6")
        self.assertEqual(cmd, [r"C:\bin\uv.exe", "pip", "install", "--python",
                               sys.executable, "piper-tts>=1.6"])
        self.assertEqual(why, "")

    def test_pip_when_there_is_no_uv(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(vp.shutil, "which", return_value=None), \
                mock.patch.object(vp, "importable", return_value=True):
            cmd, _why = vp.installer("edge-tts>=7.2")
        self.assertEqual(cmd, [sys.executable, "-m", "pip", "install", "edge-tts>=7.2"])

    def test_neither_says_the_command_to_run(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(vp.shutil, "which", return_value=None), \
                mock.patch.object(vp, "importable", return_value=False):
            cmd, why = vp.installer("edge-tts>=7.2")
        self.assertIsNone(cmd)
        self.assertIn('uv pip install "edge-tts>=7.2"', why)

    def test_the_windows_download_installs_nothing(self):
        with mock.patch.object(vp.sys, "frozen", True, create=True):
            cmd, why = vp.installer("piper-tts>=1.6")
        self.assertIsNone(cmd)
        self.assertIn("ships both engines", why)


class TestCAnInstallIsJudgedByTheImport(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.changed = mock.patch.object(vp, "_voices_changed").start()
        self.addCleanup(mock.patch.stopall)

    def _run(self, returncode=0, stderr="", then_have=None):
        def run(command, **kwargs):
            self.command, self.kwargs = command, kwargs
            if then_have:
                packs.have.add(then_have)
            return subprocess.CompletedProcess(command, returncode, "", stderr)

        packs = _Packs(self.folder, run=run)
        return packs

    def test_a_clean_install_is_done_and_lists_the_voices(self):
        packs = self._run(then_have="piper")
        job = _wait(packs.install("piper"))
        self.assertEqual(job.state, "done")
        self.assertEqual(self.command[-1], "piper-tts>=1.6")
        self.assertEqual(self.kwargs["timeout"], vp.INSTALL_TIMEOUT_SEC)
        self.changed.assert_called_once_with("piper")

    def test_a_failed_install_says_the_installers_last_line(self):
        packs = self._run(returncode=1, stderr="resolving...\nerror: no wheel for your "
                                                "platform\n")
        job = _wait(packs.install("edge"))
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error, "error: no wheel for your platform")
        self.changed.assert_not_called()

    def test_an_install_that_will_not_import_says_restart(self):
        packs = self._run()
        job = _wait(packs.install("piper"))
        self.assertEqual(job.state, "failed")
        self.assertIn("restart Flow", job.error)

    def test_a_timeout_and_a_missing_installer_are_said(self):
        def slow(command, **kw):
            raise subprocess.TimeoutExpired(command, 600)

        job = _wait(_Packs(self.folder, run=slow).install("piper"))
        self.assertIn("more than 10 minutes", job.error)
        packs = _Packs(self.folder, command=(None, "no installer here"))
        job = _wait(packs.install("piper"))
        self.assertEqual((job.state, job.error), ("failed", "no installer here"))

    def test_one_install_at_a_time(self):
        gate = __import__("threading").Event()

        def run(command, **kw):
            gate.wait(2)
            return subprocess.CompletedProcess(command, 1, "", "stop")

        packs = _Packs(self.folder, run=run)
        first = packs.install("piper")
        self.assertIs(packs.install("piper"), first)
        gate.set()
        _wait(first)

    def test_an_unknown_engine_is_refused(self):
        with self.assertRaises(ValueError):
            _Packs(self.folder).install("espeak")


def _voice(model: bytes, sidecar: bytes) -> PiperVoice:
    return PiperVoice("en_GB-test-high", "en/en_GB/test/high/en_GB-test-high.onnx",
                      "British", "high", len(model), hashlib.md5(model).hexdigest(),
                      hashlib.md5(sidecar).hexdigest())


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class TestDAVoiceIsKeptOnlyWhole(unittest.TestCase):

    MODEL = b"onnx" * 300_000
    SIDECAR = b'{"audio": {"sample_rate": 22050}}'

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.changed = mock.patch.object(vp, "_voices_changed").start()
        self.addCleanup(mock.patch.stopall)
        self.urls = []

    def _packs(self, model=None, sidecar=None):
        def fetch(url):
            self.urls.append(url)
            return _Response(sidecar if url.endswith(".json") else model)

        return _Packs(self.folder, fetch=fetch)

    def test_a_download_lands_both_halves_and_lists_them(self):
        packs = self._packs(self.MODEL, self.SIDECAR)
        voice, job = _voice(self.MODEL, self.SIDECAR), Job(total=len(self.MODEL))
        packs._download(voice, job)
        self.assertEqual(job.state, "done")
        self.assertEqual((self.folder / "en_GB-test-high.onnx").read_bytes(), self.MODEL)
        self.assertEqual((self.folder / "en_GB-test-high.onnx.json").read_bytes(),
                         self.SIDECAR)
        self.assertEqual(job.done, len(self.MODEL))
        self.changed.assert_called_once_with("piper")
        # From Piper's repository, at the pinned tag.
        self.assertTrue(all(f"/rhasspy/piper-voices/resolve/{vp.PIPER_REVISION}/" in u
                            for u in self.urls))
        self.assertTrue(self.urls[0].endswith(".onnx.json"), "the sidecar comes first")

    def test_a_corrupt_download_leaves_nothing(self):
        packs = self._packs(self.MODEL[:-1] + b"X", self.SIDECAR)
        job = Job()
        packs._download(_voice(self.MODEL, self.SIDECAR), job)
        self.assertEqual(job.state, "failed")
        self.assertIn("did not arrive whole", job.error)
        self.assertEqual(list(self.folder.iterdir()), [])
        self.changed.assert_not_called()

    def test_a_cancelled_download_leaves_nothing(self):
        packs = self._packs(self.MODEL, self.SIDECAR)
        job = Job()
        job.cancel.set()
        packs._download(_voice(self.MODEL, self.SIDECAR), job)
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_hf_endpoint_is_honoured(self):
        packs = self._packs(self.MODEL, self.SIDECAR)
        with mock.patch.dict("os.environ", {"HF_ENDPOINT": "https://hf-mirror.example/"}):
            packs._download(_voice(self.MODEL, self.SIDECAR), Job())
        self.assertTrue(all(u.startswith("https://hf-mirror.example/rhasspy/") for u in
                            self.urls))

    def test_delete_takes_both_halves(self):
        key = vp.CATALOG[0].key
        for suffix in (".onnx", ".onnx.json"):
            (self.folder / f"{key}{suffix}").write_bytes(b"x")
        packs = _Packs(self.folder)
        self.assertTrue(packs.delete(key))
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertFalse(packs.delete(key))
        with self.assertRaises(ValueError):
            packs.delete("en_GB-nobody-high")


class TestECatalogue(unittest.TestCase):

    def test_every_voice_is_english_single_file_and_checked(self):
        keys = [v.key for v in vp.CATALOG]
        self.assertEqual(len(keys), len(set(keys)))
        for v in vp.CATALOG:
            with self.subTest(voice=v.key):
                self.assertTrue(v.key.startswith("en_"))
                self.assertTrue(v.path.endswith(f"/{v.key}.onnx"))
                self.assertEqual(len(v.md5), 32)
                self.assertEqual(len(v.json_md5), 32)
                self.assertGreater(v.size, 10_000_000)

    def test_the_label_names_the_voice_and_its_accent(self):
        self.assertEqual(vp.BY_KEY["en_GB-cori-high"].label,
                         "Cori - British, high quality")
        self.assertEqual(vp.BY_KEY["en_GB-northern_english_male-medium"].label,
                         "Northern English Male - Northern English, medium quality")


class TestFTheSnapshot(unittest.TestCase):

    def test_what_the_card_needs(self):
        folder = Path(tempfile.mkdtemp())
        key = vp.CATALOG[0].key
        for suffix in (".onnx", ".onnx.json"):
            (folder / f"{key}{suffix}").write_bytes(b"x")
        packs = _Packs(folder, have={"piper"}, command=(None, "nothing to install with"))
        snap = packs.snapshot(current_voice=f"Piper {key}")
        self.assertTrue(snap["piper"]["installed"])
        self.assertTrue(snap["piper"]["can"])
        self.assertFalse(snap["edge"]["installed"])
        self.assertFalse(snap["edge"]["can"])
        self.assertEqual(snap["edge"]["why"], "nothing to install with")
        first = snap["piper"]["voices"][0]
        self.assertEqual((first["key"], first["installed"], first["in_use"]),
                         (key, True, True))
        self.assertFalse(any(v["installed"] for v in snap["piper"]["voices"][1:]))


class TestGAddingNeverChangesTheVoice(unittest.TestCase):
    """Only choosing a Natural voice sends an answer to Microsoft — adding lists them."""

    def test_the_install_path_never_sets_a_voice(self):
        src = (ROOT / "flow" / "home" / "voicepacks.py").read_text(encoding="utf-8")
        self.assertNotIn("set_voice", src)

    def test_voices_changed_rebuilds_the_lists_from_one_engine(self):
        from flow import speak
        from flow.speak import Voice

        sapi = Voice("Microsoft David", "Male", "en-US")
        cori = Voice("Piper en_GB-cori-high", "NotSet", "en-GB", engine="piper")
        with mock.patch.object(speak, "_ALL", [sapi]), \
                mock.patch.object(speak, "_CACHE", [sapi]), \
                mock.patch("flow.piper.voices", return_value=[cori]) as piper_voices, \
                mock.patch("flow.edge.voices", return_value=[]) as edge_voices, \
                mock.patch.object(speak, "_sapi_voices") as sapi_list:
            speak.voices_changed("piper")
            self.assertEqual(speak.installed_voices(), [cori])
            self.assertEqual(speak.all_voices(), [cori, sapi])
        piper_voices.assert_any_call(refresh=True)
        self.assertNotIn(mock.call(refresh=True), edge_voices.call_args_list)
        sapi_list.assert_not_called()


class TestHPageAndRoutes(unittest.TestCase):

    def setUp(self):
        from flow.home import demo

        self.home, self.session = demo.build()
        self.addCleanup(self.home.close)

    def test_the_models_page_carries_the_card(self):
        page = self.home.api.models({})
        packs = page["voice"]["packs"]
        self.assertEqual(set(packs), {"piper", "edge"})
        self.assertEqual(len(packs["piper"]["voices"]), len(vp.CATALOG))

    def test_an_unknown_engine_or_voice_or_action_is_refused(self):
        from flow.home.api import ApiError

        api = self.home.api
        with self.assertRaises(ApiError):
            api.voice_engine({"engine": "espeak"})
        with self.assertRaises(ApiError):
            api.piper_voice({"name": "en_GB-nobody-high", "action": "download"})
        with self.assertRaises(ApiError):
            api.piper_voice({"name": vp.CATALOG[0].key, "action": "play"})

    def test_the_voice_flow_speaks_with_cannot_be_deleted(self):
        from flow.home.api import ApiError

        key = vp.CATALOG[0].key
        self.session.speaker.voice = f"Piper {key}"
        with self.assertRaises(ApiError) as caught:
            self.home.api.piper_voice({"name": key, "action": "delete"})
        self.assertIn("choose another first", str(caught.exception))

    def test_every_button_is_wired_to_its_route(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        for act, route in (('"pack-add"', 'api("voices/engine"'),
                           ('"piper-download"', 'api("voices/piper"'),
                           ('"piper-cancel"', 'api("voices/piper"'),
                           ('"piper-delete"', 'api("voices/piper"')):
            with self.subTest(act=act):
                line = next(l for l in js.splitlines() if l.strip().startswith(act + ":"))
                self.assertIn(route, line)
        self.assertIn("packsBusy(data)", js)


class TestITheDownloadShipsBothEngines(unittest.TestCase):
    """A frozen download cannot install into itself, so it carries both engines."""

    def test_the_release_builds_with_both_extras(self):
        yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        build = next(line for line in yml.splitlines() if "pyinstaller --noconfirm" in line)
        self.assertIn("--extra voice", build)
        self.assertIn("--extra edge", build)

    def test_the_spec_collects_them(self):
        spec = (ROOT / "packaging" / "flow.spec").read_text(encoding="utf-8")
        self.assertIn('for _pkg in ("piper", "edge_tts"):', spec)
        self.assertIn("collect_all(_pkg)", spec)

    def test_but_not_the_hebrew_model_no_voice_here_opens(self):
        # Piper opens `nakdimon.onnx` only for a voice whose phonemes are Hebrew, and every
        # voice Flow offers is English: 18.9 MB of v0.6.0's zip carried nothing Flow could
        # say. Pinned both ways, so a Hebrew voice joining the catalogue fails here first.
        from flow.home.voicepacks import CATALOG

        self.assertTrue(all(v.key.startswith("en_") for v in CATALOG))
        spec = (ROOT / "packaging" / "flow.spec").read_text(encoding="utf-8")
        self.assertIn('UNUSED_DATA = {"nakdimon.onnx"}', spec)
        self.assertIn("os.path.basename(src) not in UNUSED_DATA", spec)


if __name__ == "__main__":
    unittest.main()
