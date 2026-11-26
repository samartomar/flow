import hashlib
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from flow import cuda_setup, parakeet


class TestCudaSetup(unittest.TestCase):
    def test_the_nvidia_downloads_match_the_windows_wheels_in_the_lock(self):
        lock = Path(__file__).resolve().parent.parent / "uv.lock"
        packages = tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
        windows_wheels = {(wheel["url"], wheel["hash"]) for package in packages
                          for wheel in package.get("wheels", ())
                          if wheel["url"].endswith("-win_amd64.whl")}
        for url, sha, _ in cuda_setup._WHEELS.values():
            self.assertIn((url, "sha256:" + sha), windows_wheels)

    def test_setup_reuses_the_cached_helper_and_weight_and_installs_private_dlls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "app"
            archives = root / "downloads"
            models = root / "models"
            app.mkdir()
            archives.mkdir()
            models.mkdir()
            weights = models / "existing-weights.gguf"
            weights.write_bytes(b"already downloaded")
            wheels = {}
            for label, (url, _, dlls) in cuda_setup._WHEELS.items():
                archive = archives / f"Flow-CUDA-{label}.zip"
                with zipfile.ZipFile(archive, "w") as zipped:
                    for dll in dlls:
                        zipped.writestr(f"nvidia/bin/{dll}", dll)
                    zipped.writestr("test.dist-info/licenses/License.txt", "NVIDIA license")
                wheels[label] = (url, hashlib.sha256(archive.read_bytes()).hexdigest(), dlls)
            with mock.patch.object(cuda_setup, "_WHEELS", wheels), \
                    mock.patch.object(parakeet, "verify_runtime") as verify:
                cuda_setup.install(archives, app)
                verify.assert_called_once_with("cuda")
                self.assertEqual(weights.read_bytes(), b"already downloaded")
                self.assertEqual({file.name for file in (app / "cuda").glob("*.dll")},
                                 set(parakeet.CUDA_DLLS))
                (archives / "Flow-CUDA-Blas.zip").write_bytes(b"invalid archive")
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    cuda_setup.install(archives, app)
                self.assertEqual({file.name for file in (app / "cuda").glob("*.dll")},
                                 set(parakeet.CUDA_DLLS))
