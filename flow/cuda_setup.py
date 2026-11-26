"""Install the optional Parakeet CUDA libraries selected in Windows Setup."""

import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from . import parakeet


# NVIDIA's Windows wheels, pinned to the same releases as uv.lock.
_WHEELS = {
    "Blas": (
        "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
        "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661",
        ("cublas64_12.dll", "cublasLt64_12.dll"),
    ),
    "Runtime": (
        "https://files.pythonhosted.org/packages/59/df/e7c3a360be4f7b93cee39271b792669baeb3846c58a4df6dfcf187a7ffab/nvidia_cuda_runtime_cu12-12.9.79-py3-none-win_amd64.whl",
        "8e018af8fa02363876860388bd10ccb89eb9ab8fb0aa749aaf58430a9f7c4891",
        ("cudart64_12.dll",),
    ),
}


def installer_defines() -> dict[str, str]:
    pins = {}
    for label, (url, sha, _) in _WHEELS.items():
        pins[f"{label}Url"] = url
        pins[f"{label}Sha"] = sha
    helper = parakeet.RUNTIMES["cuda"]
    pins["HelperUrl"] = parakeet.release_url(helper.zip.name)
    pins["HelperSha"] = helper.zip.sha256
    pins["HelperExeSha"] = helper.exe_sha256
    pins["HelperExePath"] = rf".flow\models\{helper.dirname}\{parakeet.SERVER_EXE}"
    return pins


def _copy_pinned_members(archive: Path, sha: str, members: dict[str, str], dest: Path) -> None:
    with archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != sha:
            raise ValueError(f"{archive.name} failed SHA-256 verification")
        with zipfile.ZipFile(source) as zipped:
            for name, target in members.items():
                with zipped.open(parakeet._member(zipped, name)) as item, (dest / target).open("wb") as output:
                    shutil.copyfileobj(item, output)


def install(archives: Path, app: Path) -> None:
    with tempfile.TemporaryDirectory(dir=app, prefix=".flow-cuda-") as temporary:
        staging = Path(temporary)
        libraries = staging / "libraries"
        libraries.mkdir()
        for label, (_, sha, dlls) in _WHEELS.items():
            members = {name: name for name in dlls}
            members["License.txt"] = f"NVIDIA-{label}-License.txt"
            _copy_pinned_members(archives / f"Flow-CUDA-{label}.zip", sha, members, libraries)
        helper_zip = archives / "Flow-CUDA-Helper.zip"
        if helper_zip.exists():
            runtime = parakeet.RUNTIMES["cuda"]
            scratch = parakeet._scratch(parakeet.MODELS_DIR)
            try:
                _copy_pinned_members(helper_zip, runtime.zip.sha256,
                                     {parakeet.SERVER_EXE: parakeet.SERVER_EXE, "LICENSE": "LICENSE"},
                                     scratch)
                with (scratch / parakeet.SERVER_EXE).open("rb") as source:
                    if hashlib.file_digest(source, "sha256").hexdigest() != runtime.exe_sha256:
                        raise ValueError("The CUDA helper did not match the pinned release")
                parakeet._install(scratch, parakeet.runtime_dir("cuda"), "CUDA helper")
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
        else:
            parakeet.verify_runtime("cuda")
        dest = app / "cuda"
        # Keep the working CUDA libraries if replacing them fails.
        backup = staging / "previous"
        if dest.exists():
            dest.replace(backup)
        try:
            libraries.replace(dest)
        except OSError:
            if backup.exists():
                backup.replace(dest)
            raise


if __name__ == "__main__":
    print(json.dumps(installer_defines()))
