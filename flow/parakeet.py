"""NVIDIA Parakeet TDT 0.6B v3, through onnx-asr or parakeet.cpp, as a `Transcriber` Flow can use
instead of Whisper.

**Why this exists.** It is the most accurate speech model Flow has measured, and it runs on
a CPU. 300 EdAcc clips of accented English, errors per 100 words, 2026-10-05, same scorer
(`scripts/accent_bench.wer_counts`) for every column, Parakeet on onnx-asr with 8 threads:

    group        parakeet fp32   parakeet int8   small.en   large-v3 (GTX 1070)
    indian            15.5            18.9          21.9
    japanese          20.3            23.9          23.4
    russian            9.4            10.4          15.1
    spanish           13.0            13.9          16.6
    us-control        17.2            19.9          22.1
    all               14.7            16.9          19.5          16.8

So the full-precision model beats `large-v3` on a GPU, and beats `small.en` in every accent
group, **Japanese-accented English included.** The int8 build does not: 23.9 against
`small.en`'s 23.4 is a tie in practice, and the int8 export run through sherpa-onnx (the
first runtime Flow shipped) was worse still at 26.3 and 17.3 overall. The Japanese gap is
the quantisation and not the model, which is why there are two variants below.

**Speed**, CPU with 8 threads, two full runs each (accuracy and log-probabilities came out
identical; speed moves a little): real-time factor 0.065-0.068 for fp32 (p50 338-349 ms, p95
881-902 ms per clip, load 4.4-4.9 s) and 0.067-0.076 for int8 (p50 350-400 ms, p95
966-1012 ms, load 3.2-3.4 s), against `small.en`'s ~0.54 on the same CPU: 13-15x real time.
`scripts/parakeet_bench.py` reproduces all of it, and writes
`.bench/accent/results-parakeet-<variant>.json`.

**Three variants, because the trade is real.** `fp32` is **2.4 GB** on disk and loads in about five
seconds; `int8` is **640 MB** and loads in about three. Same decode speed. int8 is the one for a
small disk, at 2.2 errors per 100 words more. The third, `gpu`, is below, and is the default
whenever it is downloaded and a backend exists.

**The GPU build** runs parakeet.cpp (MIT) as a helper process on the same weights, quantised to
q8_0 (940 MB), measured 2026-10-05 on the same 300 clips and the GTX 1070 the Whisper rows were
measured on (`scripts/parakeet_bench.py gpu`):

    backend   errors/100   RTF     real time   p50 / p95 per clip   load
    CUDA         14.5      0.020      50x        107 / 229 ms       1.3 s (about 27 s the first time)
    Vulkan       14.5      0.036      27x        211 / 386 ms       1.6 s

Per group (CUDA): indian 15.5, japanese 20.2, russian 9.4, spanish 13.1, us-control 16.4 - level
with fp32 everywhere, so the 8-bit weights cost nothing measurable. Silence: nothing invented on
any of the 8 clips, on either backend. It costs a process, ~1 GB of video memory while loaded
(measured +1.0 GiB CUDA, +0.9 Vulkan, returned when it is unloaded), a 36 MB (Vulkan) or 313 MB
(CUDA) helper, and trust in an executable that is not ours: its SHA-256 is pinned in this file
and checked before every launch (0.05 s for Vulkan's, 0.17 s for CUDA's, measured), and the
helper is bound to 127.0.0.1 and tied to Flow with a Windows Job Object so it cannot listen on
the network or outlive a hard kill. It needs no add-on and no onnxruntime, only a CUDA runtime
(`[cuda]`, NVIDIA's own wheels) or a Vulkan driver; Windows only for now.

**What it costs, stated rather than discovered.**

- *The runtime is ~7 MB* (`onnx-asr`) plus `onnxruntime` — no torch. That is why this is an
  extra (`[parakeet]`, R16) and an explicit choice, and why `--engine auto` never picks it.
- *The model comes from Hugging Face*, `istupakov/parakeet-tdt-0.6b-v3-onnx` (the GPU build's,
  `mudler/parakeet-cpp-gguf`), pinned to one commit (`REVISION`) so a re-upload cannot change
  what a user gets, and every large file is checked against its published SHA-256. The GPU
  build's helper comes from a pinned `github.com` release, zip and executable both hashed. **This build therefore does not avoid
  huggingface.co** — the first Parakeet shipped from GitHub releases and did; the native
  engine (`native.py`) remains the answer for a network that blocks it.
- *One tier.* Whisper has a fast model for partials and a strong one for finals; here the same
  model does both, because at 14x real time there is no speed to buy by splitting. `final`
  is accepted and ignored.
- *No hotword biasing.* `hotwords` is accepted and ignored — as `native.py` does — so the
  constrained re-decode of a suspected mis-heard command comes back unbiased. The user's
  declared corrections (`lexicon`) are still applied after the decode.
- *The silence guard is different, not absent.* Whisper's `no_speech_prob` does not exist
  here, and `small.en` invented text on all 8 silence and noise clips. Measured on onnx-asr,
  fp32 returned nothing on every one of the 8. int8 invented twice: "Okay." (mean token
  log-probability -0.60, which the filler list catches) and "Ha ha" (-0.90, which
  `clean.TOKEN_LOGPROB_MIN` does); the sherpa int8 build invented "It is." at -1.10. Real
  speech sits at p1 -0.51, p5 -0.28, p50 -0.09 for fp32 and -0.57, -0.40, -0.11 for int8, so
  one threshold serves both. `clean.py` has the numbers and says how thin they are.

**Where the model lives.** `~/.flow/models/<variant name>/`, plain files. **Not the Hugging
Face cache**: onnxruntime 1.30+ refuses external weights reached through cache symlinks
("External data path escapes model dir"), and fp32's encoder is a 41 MB graph plus a 2.4 GB
`.data` file. `fetch()` puts it there — atomically (a scratch directory beside it, renamed
into place), cancellably, and with the size and checksum of every file verified.

**Threads.** `onnx-asr` takes a `SessionOptions`, so `intra_op_num_threads` is set explicitly to
`default_threads()` — 8 or every core on a smaller machine — rather than left to onnxruntime's
own default.

`import onnx_asr` happens inside `load()` and nowhere else, so importing this module costs
nothing and a default install — which has no `[parakeet]` extra — never breaks on it.
"""

from __future__ import annotations

import atexit
import hashlib
import http.client
import importlib.util
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np

from . import SAMPLE_RATE
from .asr import DROP_HISTORY, Drop
from .clean import invented_reason, normalise
from .lexicon import Lexicon

#: Where Flow keeps what it did not install itself, beside the profile and the voices.
MODELS_DIR = Path.home() / ".flow" / "models"

#: The model, as onnx-asr names it; the same graph in both variants.
ONNX_ASR_NAME = "nemo-parakeet-tdt-0.6b-v3"

#: Where the files come from, and **which commit of it**. A branch name would let a
#: re-upload change what every user gets; a commit hash cannot. Sizes and checksums below
#: were read from the hub's API at exactly this revision on 2026-10-05.
REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
REVISION = "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce"


@dataclass(frozen=True)
class File:
    """One file of a model: its size, and its SHA-256 where the hub publishes one."""

    name: str
    size: int
    sha256: str = ""


#: Files both variants need: the feature extractor graph, the vocabulary, the config.
_SHARED = (
    File("nemo128.onnx", 139_764,
         "a9fde1486ebfcc08f328d75ad4610c67835fea58c73ba57e3209a6f6cf019e9f"),
    File("vocab.txt", 93_939),
    File("config.json", 97),
)


@dataclass(frozen=True)
class Variant:
    """One downloadable build of the model."""

    #: What the profile stores and the API says: "fp32" or "int8".
    key: str
    #: The catalog name and the directory under `MODELS_DIR`.
    name: str
    #: onnx-asr's `quantization` argument.
    quantization: str | None
    files: tuple[File, ...]
    #: Where the files come from, and at which commit. The ONNX builds share one repo; the
    #: GPU build's GGUF is another.
    repo: str = REPO
    revision: str = REVISION
    #: What runs it: "onnx" (onnx-asr, in this process) or "gpu" (parakeet.cpp's server,
    #: a helper process on the GPU).
    runtime: str = "onnx"

    @property
    def bytes(self) -> int:
        return sum(f.size for f in self.files)


VARIANTS: dict[str, Variant] = {
    "fp32": Variant("fp32", "parakeet-tdt-0.6b-v3", None, (
        File("encoder-model.onnx", 41_770_866,
             "98a74b21b4cc0017c1e7030319a4a96f4a9506e50f0708f3a516d02a77c96bb1"),
        File("encoder-model.onnx.data", 2_435_420_160,
             "9a22d372c51455c34f13405da2520baefb7125bd16981397561423ed32d24f36"),
        File("decoder_joint-model.onnx", 72_520_893,
             "e978ddf6688527182c10fde2eb4b83068421648985ef23f7a86be732be8706c1"),
        *_SHARED)),
    "int8": Variant("int8", "parakeet-tdt-0.6b-v3-int8", "int8", (
        File("encoder-model.int8.onnx", 652_183_999,
             "6139d2fa7e1b086097b277c7149725edbab89cc7c7ae64b23c741be4055aff09"),
        File("decoder_joint-model.int8.onnx", 18_202_004,
             "eea7483ee3d1a30375daedc8ed83e3960c91b098812127a0d99d1c8977667a70"),
        *_SHARED)),
    # The GPU build: parakeet.cpp's GGUF, quantised to q8_0. The same graph as the two above
    # and measured no worse than fp32 (14.5 against 14.7 errors per 100 words), at a
    # quarter the size. Hugging Face `mudler/parakeet-cpp-gguf`, one commit.
    "gpu": Variant("gpu", "parakeet-tdt-0.6b-v3-gpu", None, (
        File("tdt-0.6b-v3-q8_0.gguf", 940_663_680,
             "4d69a4a6683f4f2d952bad794c1357ca6eb628027695b4699c5a9ad4cd07d757"),),
        repo="mudler/parakeet-cpp-gguf",
        revision="741158ae71e64ef5c89385862c18f777d07a97a1", runtime="gpu"),
}

#: About how long `load()` takes, in seconds, for the page to say "(about 3 s)". Measured
#: 2026-10-05 on this machine: fp32 4.4-4.9 s, int8 3.2-3.4 s. A promise of the order of
#: magnitude, not of the second - a colder disk or a smaller CPU takes longer. The GPU
#: build's depends on the backend, in `GPU_LOAD_SEC`.
LOAD_SEC = {"fp32": 5, "int8": 3}


def load_seconds(key: str) -> int | None:
    """About how long variant `key` takes to load here, for the page; None when unknown."""
    if key == "gpu":
        backend = gpu_backend()[0]
        if backend in GPU_FIRST_LOAD_SEC and not (runtime_dir(backend) / LOADED_MARKER).exists():
            return GPU_FIRST_LOAD_SEC[backend]
        return GPU_LOAD_SEC.get(backend)
    return LOAD_SEC.get(key)

#: What the profile may hold: a variant, or "auto" — fp32 if it is here, else int8 if that
#: is, else fp32 (which is what will be downloaded).
VARIANT_CHOICES = ("auto", *VARIANTS)

#: What the first Parakeet (sherpa-onnx, int8) left on disk. Not read by this runtime, and
#: not deleted behind anybody's back: the Models page offers to remove it.
LEGACY_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"

#: Per-socket-operation timeout while downloading. Not a deadline for the whole fetch,
#: which is gigabytes; a connection that has stopped answering is what this catches.
FETCH_TIMEOUT_SEC = 30.0
_CHUNK = 1024 * 1024

#: `intra_op_num_threads`. **8, or every core on a smaller machine.** The speeds above were
#: measured at 8 threads on a 24-thread box; a recogniser that takes every core of a 4-core
#: laptop starves the UI thread it shares the process with.
MAX_THREADS = 8


def default_threads() -> int:
    return max(1, min(MAX_THREADS, os.cpu_count() or 1))


class NotAvailable(RuntimeError):
    """This machine cannot run the Parakeet engine, with the reason in the message.

    One exception for every way of not having it — no runtime, no model, a download that
    failed — because each means the same to the caller: use Whisper, and say this sentence.
    """


class Cancelled(Exception):
    """`fetch(cancelled=...)` was told to stop. Not a failure, so not a `NotAvailable`."""


# -- is it here? ---------------------------------------------------------------

#: What to say when the runtime is missing, in one place so the probe and the import agree.
INSTALL_HINT = ("the Parakeet runtime is not installed - run: "
                'uv pip install "onnx-asr[cpu]>=0.12"  (or the [parakeet] extra)')


def runtime_installed() -> tuple[bool, str]:
    """`(usable, why not)` for `onnx-asr` and `onnxruntime`, without importing either.

    `find_spec` rather than an import: the import loads a native library, and `--engine
    auto` must not pay for an engine it will not choose.
    """
    for module in ("onnx_asr", "onnxruntime"):
        if sys.modules.get(module) is not None:
            continue
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            return False, INSTALL_HINT
    return True, ""


# -- the GPU build: parakeet.cpp's server as a helper process --------------------------

#: parakeet.cpp (MIT, github.com/mudler/parakeet.cpp), the release the helper comes from. A
#: tag and not a branch, and each zip is pinned by SHA-256 below — the digests GitHub itself
#: publishes for the assets, which match the ones computed from the downloads.
CPP_REPO = "mudler/parakeet.cpp"
CPP_VERSION = "v0.5.0"
SERVER_EXE = "parakeet-server.exe"

#: What `LOAD_SEC` is for the GPU build, by backend. Steady state is about a second and a
#: half (1.3 s CUDA, 1.2-1.6 s Vulkan, warm-up decode included). The **first** CUDA load on a
#: Pascal card (sm_61, which the release was not built for, so the kernels are JIT-compiled
#: from PTX) took **26.9 s** with the driver's cache disabled and 16 s in an earlier run, and
#: is fast once the driver has cached them. Flow cannot see that cache, so it remembers its
#: own first success in a marker file beside the helper and promises 30 s until it exists.
GPU_LOAD_SEC = {"cuda": 2, "vulkan": 2}
GPU_FIRST_LOAD_SEC = {"cuda": 30}
LOADED_MARKER = ".loaded"


@dataclass(frozen=True)
class Runtime:
    """One backend's helper, as released: the zip, and the executable inside it."""

    backend: str
    zip: File
    #: SHA-256 and size of the extracted `parakeet-server.exe`. Pinned rather than recorded
    #: at install, so a file swapped on disk after the download is caught too — Flow is
    #: about to *execute* it, which is why it is hashed again before every launch.
    exe_sha256: str
    exe_bytes: int

    @property
    def dirname(self) -> str:
        return f"parakeet-cpp-{CPP_VERSION}-{self.backend}"


RUNTIMES: dict[str, Runtime] = {
    "cuda": Runtime(
        "cuda",
        File(f"parakeet-{CPP_VERSION}-bin-win-cuda-x64.zip", 312_914_549,
             "0c90f619a368e67418596231470e916fda60118180879e4334d29d9b0df93b21"),
        "2621da65562a53fd26bfc6ab601fdf8133032516d7b31fb0617d7f6064e8c682", 169_658_880),
    "vulkan": Runtime(
        "vulkan",
        File(f"parakeet-{CPP_VERSION}-bin-win-vulkan-x64.zip", 35_828_324,
             "717c416fab299755e8140137e3a0115121ce1acb6379d13c60f2f0613f6c13a3"),
        "5b2da797198ee0ef9ce4438f2be71cf77fa7089efe7617d956cb6fb75ec54f73", 59_147_776),
}

#: What the CUDA helper links beside the system: the runtime and cuBLAS, both from NVIDIA's
#: own wheels (`[cuda]`), never from a zip of somebody's making. Checked with a dependency
#: listing of the executable and by running it with nothing else on its PATH.
CUDA_DLLS = ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll")

BACKEND_LABEL = {"cuda": "CUDA", "vulkan": "Vulkan"}

_backend_cache: tuple[str, str] | None = None
_nvidia_cache: bool | None = None


def _nvidia_present() -> bool:
    """Whether `nvidia-smi` sees a GPU. Asked once: the card does not change mid-session."""
    global _nvidia_cache
    if _nvidia_cache is None:
        _nvidia_cache = False
        exe = shutil.which("nvidia-smi")
        if exe:
            try:
                out = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=10,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                _nvidia_cache = out.returncode == 0 and "GPU" in out.stdout
            except (OSError, subprocess.SubprocessError):
                pass
    return _nvidia_cache


def cuda_dirs() -> list[str]:
    """Directories that together hold every DLL the CUDA helper needs, or [] if one is missing.

    The wheels under `site-packages/nvidia` first (what `[cuda]` installs, and what
    `asr.cuda_ready` already looks in), then anything already on PATH — a machine with the
    CUDA toolkit needs nothing from here.
    """
    from .asr import _wheel_dll_dirs

    found: dict[str, str] = {}
    for directory in _wheel_dll_dirs():
        for name in CUDA_DLLS:
            if name not in found and (Path(directory) / name).is_file():
                found[name] = directory
    for name in CUDA_DLLS:
        if name not in found:
            hit = shutil.which(name)
            if hit:
                found[name] = str(Path(hit).parent)
    if len(found) < len(CUDA_DLLS):
        return []
    return sorted(set(found.values()))


def _vulkan_loader() -> bool:
    """Whether the Vulkan loader is on this machine: the GPU driver provides it."""
    try:
        import ctypes

        ctypes.WinDLL("vulkan-1.dll")
        return True
    except (OSError, AttributeError):
        return False


def _detect_backend() -> tuple[str, str]:
    """`(backend, why not)`: "cuda", "vulkan", or "" with the reason there is none."""
    if sys.platform != "win32":
        return "", "the GPU build of Parakeet is Windows-only for now"
    nvidia = _nvidia_present()
    if nvidia and cuda_dirs():
        return "cuda", ""
    if _vulkan_loader():
        return "vulkan", ""
    if nvidia:
        return "", ('an NVIDIA GPU was found but not the CUDA runtime: '
                    'uv pip install -e ".[cuda]"')
    return "", "no GPU with a CUDA or Vulkan driver was found"


def gpu_backend() -> tuple[str, str]:
    """Which backend the GPU build would use on this PC, once: CUDA when the runtime is here
    and an NVIDIA GPU is, else Vulkan (any Vulkan GPU, no CUDA needed), else none."""
    global _backend_cache
    if _backend_cache is None:
        _backend_cache = _detect_backend()
    return _backend_cache


def runtime_dir(backend: str) -> Path:
    return MODELS_DIR / RUNTIMES[backend].dirname


def runtime_present(backend: str) -> bool:
    """Whether the helper for `backend` is installed: its executable, at the pinned size.

    A stat and not a hash — this is asked every time the page polls. The hash is checked
    where it matters, before the file is run (`verify_runtime`).
    """
    runtime = RUNTIMES.get(backend)
    if runtime is None:
        return False
    exe = runtime_dir(backend) / SERVER_EXE
    try:
        return exe.is_file() and exe.stat().st_size == runtime.exe_bytes
    except OSError:
        return False


def verify_runtime(backend: str) -> Path:
    """The helper's path, once its SHA-256 has been checked against the pinned one.

    Run before **every** launch. Hashing the 170 MB CUDA executable takes about 0.2 s
    (measured, warm cache), which is cheap beside the seconds the load costs, and the
    alternative is executing whatever a file on disk has become since it was verified.
    """
    runtime = RUNTIMES[backend]
    exe = runtime_dir(backend) / SERVER_EXE
    if not runtime_present(backend):
        raise NotAvailable(f"the GPU helper is not installed yet ({exe})")
    digest = hashlib.sha256()
    try:
        with open(exe, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 22), b""):
                digest.update(chunk)
    except OSError as exc:
        raise NotAvailable(f"could not read the GPU helper: {exc}") from exc
    if digest.hexdigest() != runtime.exe_sha256:
        raise NotAvailable(f"{SERVER_EXE} does not match the release it was downloaded from "
                           f"- not running it. Delete {exe.parent} and download it again")
    return exe


def variant_runtime(key: str | None) -> tuple[bool, str]:
    """`(usable, why not)` for what variant `key` runs on: onnx-asr for fp32 and int8, a GPU
    backend for the GPU build. No key means the ONNX runtime, as `runtime_installed`."""
    if key == "gpu":
        backend, why = gpu_backend()
        return bool(backend), why
    return runtime_installed()


#: What to say when the ONNX builds' add-on is missing, in the words every surface uses.
ADDON_HINT = "needs the Parakeet add-on: " + 'uv pip install -e ".[parakeet]"'


def missing_runtime(key: str | None) -> str:
    """The sentence for why variant `key` cannot run here, or "" when its runtime is there.

    The add-on hint for the ONNX builds, and the backend's own reason for the GPU build -
    which needs no add-on at all, only a GPU with a Vulkan or CUDA driver.
    """
    ok, why = variant_runtime(key)
    if ok:
        return ""
    return why if key == "gpu" else ADDON_HINT


def download_size(key: str) -> int:
    """Bytes a fresh download of variant `key` would fetch here: the model, plus the GPU
    build's helper when the backend's is not installed."""
    total = VARIANTS[key].bytes
    if key == "gpu":
        backend = gpu_backend()[0]
        if backend in RUNTIMES and not runtime_present(backend):
            total += RUNTIMES[backend].zip.size
    return total


def sources(key: str) -> str:
    """Where a download of variant `key` comes from, for the line that says so first."""
    return "huggingface.co and github.com" if key == "gpu" else "huggingface.co"


def variant_dir(key: str) -> Path:
    return MODELS_DIR / VARIANTS[key].name


def model_present(key: str, model_dir: Path | None = None) -> bool:
    """Whether every file of variant `key` is in its directory, at exactly the right size.
    For the GPU build that includes the helper for the backend this PC would use.

    By size and not merely by existence: a file cut short is the one failure `fetch()`'s
    atomic rename cannot see on a disk that filled up later or was edited by hand.
    """
    root = Path(model_dir) if model_dir else variant_dir(key)
    try:
        files = all((root / f.name).is_file() and (root / f.name).stat().st_size == f.size
                    for f in VARIANTS[key].files)
    except OSError:
        return False
    if not files or key != "gpu" or model_dir is not None:
        return files
    # The GPU build is the model *and* the helper for the backend this PC would use.
    backend = gpu_backend()[0]
    return bool(backend) and runtime_present(backend)


def installed_variants() -> list[str]:
    return [key for key in VARIANTS if model_present(key)]


def resolve_variant(asked: str | None) -> str:
    """Which variant to use for a profile's `parakeet_model`.

    An explicit "gpu", "fp32" or "int8" is honoured whether or not it is downloaded — the
    caller decides whether to fetch it. "auto" (or nothing) is the best one that is here:
    the GPU build when it is downloaded and a backend exists, then fp32, then int8. With
    none downloaded it is fp32 when the ONNX runtime is installed, else the GPU build when
    a backend exists (so a machine that never installed the add-on is offered what it can
    run), else fp32.
    """
    if asked in VARIANTS:
        return asked
    for key in ("gpu", "fp32", "int8"):
        if model_present(key):
            return key
    if runtime_installed()[0]:
        return "fp32"
    return "gpu" if gpu_backend()[0] else "fp32"


def installed_bytes(key: str, model_dir: Path | None = None) -> int:
    """What variant `key` takes on disk, for the Models page's size column. 0 when absent."""
    root = Path(model_dir) if model_dir else variant_dir(key)
    try:
        total = sum((root / f.name).stat().st_size for f in VARIANTS[key].files)
    except OSError:
        return 0
    if key == "gpu" and model_dir is None:
        backend = gpu_backend()[0]
        if backend and runtime_present(backend):
            total += RUNTIMES[backend].exe_bytes
    return total


def available(key: str | None = None, model_dir: Path | None = None) -> tuple[bool, str]:
    """`(usable, why not)`: the runtime is installed and variant `key` is on disk.

    Cheap and read-only — it never imports the runtime and never downloads, so it is
    safe to ask at startup. Fetching is `fetch()`'s job, and is only done on request.
    """
    key = key or resolve_variant("auto")
    ok, why = variant_runtime(key)
    if not ok:
        return False, why
    if not model_present(key, model_dir):
        root = Path(model_dir) if model_dir else variant_dir(key)
        return False, f"model not downloaded yet ({root})"
    return True, ""


def legacy_dir() -> Path:
    return MODELS_DIR / LEGACY_NAME


def legacy_bytes() -> int:
    """What the first Parakeet's files still take, or 0 when there are none."""
    root = legacy_dir()
    try:
        return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    except OSError:
        return 0


def remove_legacy() -> bool:
    """Delete the first Parakeet's files. True when anything was removed."""
    root = legacy_dir()
    if not root.exists():
        return False
    shutil.rmtree(root, ignore_errors=True)
    return not root.exists()


# -- getting it ----------------------------------------------------------------


def hub_url(name: str, repo: str = REPO, revision: str = REVISION) -> str:
    """Where one file of a model is, at a pinned revision."""
    return f"https://huggingface.co/{repo}/resolve/{revision}/{name}"


def release_url(name: str, repo: str = CPP_REPO, version: str = CPP_VERSION) -> str:
    """Where one asset of a parakeet.cpp release is, at a pinned tag."""
    return f"https://github.com/{repo}/releases/download/{version}/{name}"


def _download(url: str, out: Path, file: File, before: int, total: int,
              progress, cancelled) -> None:
    """One file, to `out`, with its size and checksum verified. Raises on any mismatch."""
    request = urllib.request.Request(url, headers={"User-Agent": "flow"})
    digest = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SEC) as answer, \
                open(out, "wb") as sink:
            said = answer.headers.get("Content-Length")
            if said and int(said) != file.size:
                raise NotAvailable(
                    f"{file.name} is {said} bytes on the server, expected {file.size}")
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                chunk = answer.read(_CHUNK)
                if not chunk:
                    break
                sink.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                if progress is not None:
                    progress(before + got, total)
    except (OSError, ValueError) as exc:
        raise NotAvailable(f"download failed: {exc}") from exc
    if got != file.size:
        raise NotAvailable(f"{file.name} is {got} bytes, expected {file.size}")
    if file.sha256 and digest.hexdigest() != file.sha256:
        raise NotAvailable(f"{file.name} failed its checksum")


def _scratch(parent: Path) -> Path:
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=".parakeet-", dir=parent))
    except OSError as exc:
        raise NotAvailable(f"cannot write to {parent}: {exc}") from exc


def _install(scratch: Path, dest: Path, what: str) -> None:
    """Move a finished scratch directory into place, replacing whatever was there."""
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    try:
        os.replace(scratch, dest)
    except OSError as exc:
        raise NotAvailable(f"could not install the {what} at {dest}: {exc}") from exc


def _fetch_files(variant: Variant, dest: Path, url_for, progress, cancelled,
                 before: int, total: int) -> Path:
    """Every file of `variant`, verified, into `dest`, atomically."""
    scratch = _scratch(dest.parent)
    try:
        for file in variant.files:
            _download(url_for(file.name), scratch / file.name, file, before, total,
                      progress, cancelled)
            before += file.size
        if cancelled is not None and cancelled():
            raise Cancelled()
        _install(scratch, dest, "model")
        return dest
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _member(archive: zipfile.ZipFile, name: str) -> zipfile.ZipInfo:
    """The one file called `name` in `archive`, wherever it sits — and never by its own path.

    Only the *basename* is matched, and a member whose path climbs out (`..`) or is absolute
    is not considered at all. The caller writes to a name it chose, so what an archive claims
    about where a file goes is never used.
    """
    found = []
    for info in archive.infolist():
        parts = PurePosixPath(info.filename.replace("\\", "/")).parts
        if (not info.is_dir() and parts and parts[-1] == name and ".." not in parts
                and not info.filename.startswith(("/", "\\"))
                and not (len(info.filename) > 1 and info.filename[1] == ":")):
            found.append((len(parts), info))
    if not found:
        raise NotAvailable(f"the release archive has no {name}")
    return min(found, key=lambda pair: pair[0])[1]


def _fetch_runtime(runtime: Runtime, url_for, progress, cancelled, total: int) -> Path:
    """The helper for one backend: the release zip, checked, and from it `parakeet-server.exe`
    and its `LICENSE` — nothing else is extracted — into `runtime_dir`, atomically."""
    dest = runtime_dir(runtime.backend)
    scratch = _scratch(dest.parent)
    try:
        archive = scratch / "release.zip"
        _download(url_for(runtime.zip.name), archive, runtime.zip, 0, total, progress, cancelled)
        out = scratch / "unpacked"
        out.mkdir()
        try:
            with zipfile.ZipFile(archive) as zf:
                for name in (SERVER_EXE, "LICENSE"):
                    with zf.open(_member(zf, name)) as source, open(out / name, "wb") as sink:
                        shutil.copyfileobj(source, sink)
        except (zipfile.BadZipFile, OSError) as exc:
            raise NotAvailable(f"could not unpack the GPU helper: {exc}") from exc
        exe = out / SERVER_EXE
        digest = hashlib.sha256(exe.read_bytes()).hexdigest()
        if digest != runtime.exe_sha256 or exe.stat().st_size != runtime.exe_bytes:
            raise NotAvailable(f"{SERVER_EXE} in the release is not the one this Flow pins")
        if cancelled is not None and cancelled():
            raise Cancelled()
        _install(out, dest, "GPU helper")
        return dest
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def fetch(key: str = "fp32", dest: Path | None = None, progress=None,
          cancelled=None, url_for=None, backend: str | None = None, runtime_url_for=None) -> Path:
    """Download variant `key` into `dest`, atomically. Returns `dest`.

    Every file goes into a scratch directory *beside* `dest`, verified as it lands, and the
    directory is renamed into place with one `os.replace` only once all of them are there —
    so an interrupted fetch leaves nothing at `dest` that `model_present` could mistake for
    a model, and the next attempt simply starts again (there is no resume). `progress(done,
    total)` is called per chunk with byte counts across the whole variant; the caller
    decides how often to show it. `cancelled`, when given, is asked before each chunk and
    before the rename; true raises `Cancelled` and the scratch directory goes with it, so a
    cancel leaves exactly what a failure does. `url_for(name)` overrides where the model's
    files come from (tests use `file://`); the default is its pinned revision on
    huggingface.co. Raises `NotAvailable`, with the reason, for every way this can fail.

    **The GPU build is two downloads**, and `dest` is its model's directory: the helper
    (`parakeet-server.exe` and `LICENSE` out of the pinned release zip on github.com, for
    `backend` or the one `gpu_backend()` chose) unless it is already installed and
    verified, then the model. `runtime_url_for(name)` overrides the zip's source. Progress
    counts both, so the bar is one bar.
    """
    variant = VARIANTS[key]
    dest = Path(dest) if dest else variant_dir(key)
    url_for = url_for or (lambda name: hub_url(name, variant.repo, variant.revision))
    if variant.runtime != "gpu":
        return _fetch_files(variant, dest, url_for, progress, cancelled, 0, variant.bytes)
    backend = backend or gpu_backend()[0]
    if backend not in RUNTIMES:
        raise NotAvailable(gpu_backend()[1] or "no GPU backend for the Parakeet GPU build")
    runtime = RUNTIMES[backend]
    need_runtime = not runtime_present(backend)
    # Only what is missing: a model already here is not fetched again for the sake of a
    # helper (a second backend, or a deleted one), nor a helper for the sake of a model.
    need_model = not model_present("gpu", dest)
    total = (variant.bytes if need_model else 0) + (runtime.zip.size if need_runtime else 0)
    done = 0
    if need_runtime:
        _fetch_runtime(runtime, runtime_url_for or release_url, progress, cancelled, total)
        done = runtime.zip.size
    if need_model:
        _fetch_files(variant, dest, url_for, progress, cancelled, done, total)
    return dest


# -- decoding ------------------------------------------------------------------


def _import_runtime():
    """The one place `onnx_asr` and `onnxruntime` are imported — when a model is built."""
    try:
        import onnx_asr
        import onnxruntime
    except ImportError as exc:
        raise NotAvailable(f"{INSTALL_HINT} ({exc})") from exc
    return onnx_asr, onnxruntime


def load_model(key: str, model_dir: Path | None = None, threads: int | None = None,
               backend: str | None = None):
    """Build the model for variant `key`: onnx-asr on the CPU, with results that carry
    per-token log-probabilities, or - for the GPU build - a started helper process on
    `backend`. Shared by the transcriber and the benchmark, so the benchmark measures the
    build Flow runs."""
    if key == "gpu":
        return start_helper(backend or gpu_backend()[0], model_dir)
    onnx_asr, onnxruntime = _import_runtime()
    root = Path(model_dir) if model_dir else variant_dir(key)
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = threads if threads else default_threads()
    model = onnx_asr.load_model(
        ONNX_ASR_NAME, path=root, quantization=VARIANTS[key].quantization,
        sess_options=options, providers=["CPUExecutionProvider"])
    return model.with_timestamps()


def mean_logprob(result) -> float | None:
    """The mean log-probability of the tokens in an onnx-asr result, or None.

    None, not 0.0, when the engine reported nothing: `clean.invented_reason` treats None
    as "no evidence" and a fabricated zero as "very confident".
    """
    probs = getattr(result, "logprobs", None)
    if probs is None or len(probs) == 0:
        return None
    return float(np.mean(np.asarray(probs, dtype=np.float64)))


def decode(model, audio: np.ndarray) -> tuple[str, float | None]:
    """`(text, mean token log-probability)` for mono float32 audio at 16 kHz."""
    result = model.recognize(audio, sample_rate=SAMPLE_RATE)
    return (getattr(result, "text", "") or "").strip(), mean_logprob(result)


class ParakeetTranscriber:
    """Satisfies `asr.Transcriber` with one in-process onnx-asr model.

    Lazy: constructing it costs nothing, and `load()` — which `Session._warm` calls at a
    moment of its choosing — pays the 2 s (int8) or 5 s (fp32). `take_drops()` is what makes
    the hallucination gate attributable the way Whisper's is. There is deliberately no
    `take_confidence`: the session reads that on Whisper's `avg_logprob` scale and this
    engine's numbers are not on it, so absent is the honest answer, as for `native.py`.
    """

    #: Which engine this is, as `Session.engine`, the profile and the Models page name it.
    engine = "parakeet"
    #: Parakeet runs on the CPU here: that is the measurement, and the shipped wheel.
    device = "cpu"

    def __init__(self, variant: str = "fp32", model_dir: Path | None = None,
                 threads: int | None = None, lexicon: Lexicon | None = None) -> None:
        if variant not in VARIANTS:
            raise ValueError(f"unknown Parakeet variant {variant!r}")
        #: "fp32", "int8" or "gpu". Read by `Session` to tell a variant switch from a no-op.
        self.variant = variant
        self._dir = Path(model_dir) if model_dir else None
        self._threads = threads if threads else default_threads()
        #: The user's declared corrections, applied after the decode as for Whisper (P4).
        #: Its terms cannot bias this engine, so only the `wrong -> right` half is used.
        self.lexicon = lexicon if lexicon is not None else Lexicon()
        self._model = None
        self._loading = False
        #: One model, one decode at a time; also serialises load/unload against it.
        self._lock = threading.Lock()
        self._drops: list[Drop] = []
        self._drops_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def loading(self) -> bool:
        """True while the model is being built, so the UI can name that wait."""
        return self._loading

    def load(self, final=None) -> None:
        """Build the model. Idempotent; the signature matches Whisper's tier load."""
        with self._lock:
            if self._model is not None:
                return
            self._loading = True
            try:
                root = self._dir or variant_dir(self.variant)
                if not model_present(self.variant, root):
                    raise NotAvailable(f"model not downloaded yet ({root})")
                self._model = load_model(self.variant, root, self._threads)
            finally:
                self._loading = False

    def unload(self) -> None:
        """Release the model (up to 2.5 GB of RAM). The idle path calls this."""
        with self._lock:
            self._model = None

    def take_drops(self) -> list[Drop]:
        """Return and clear the recorded rejections, as `WhisperTranscriber` does."""
        with self._drops_lock:
            out, self._drops = self._drops, []
            return out

    def identity(self) -> list[tuple[str, str]]:
        """What decides this build's numbers, as (component, version) for the trace.

        The engine and build, the model at its pinned commit, and the runtime that ran it.
        `diag.identity` records Whisper's model revisions; without this a Parakeet decode
        in the trace would not say which of three builds produced it.
        """
        import importlib.metadata as md

        # Values are tokens, because `diag` refuses anything else: the repo is implied by
        # the model's name (each build has exactly one), so the commit alone pins it.
        variant = VARIANTS[self.variant]
        out = [("engine", f"parakeet-{self.variant}"),
               (f"model:{variant.name}", variant.revision)]
        for name in ("onnx-asr", "onnxruntime"):
            try:
                out.append((name, md.version(name)))
            except md.PackageNotFoundError:
                out.append((name, "absent"))
        return out

    # -- the one method the protocol asks for ------------------------------

    def text(self, audio: np.ndarray, *, final: bool = False,
             hotwords: str = "") -> str:
        """Transcribe mono float32 at 16 kHz.

        `final` and `hotwords` are accepted and ignored — see the module docstring: one
        tier, and no biasing. A decode the model itself doubts (`clean.TOKEN_LOGPROB_MIN`)
        is returned as "" and recorded in `take_drops()` with the evidence, so the refusal
        is never silent (P2).
        """
        block = np.ascontiguousarray(audio, dtype=np.float32)
        if block.size == 0:
            return ""
        self.load()
        with self._lock:
            raw, lp, conf = self._recognise(block)
        if not raw:
            # What the model does with silence: nothing to say and nothing to record. A
            # drop here would announce "I did not catch 0 words".
            return ""
        reason = invented_reason(raw, None, None, None, mean_token_logprob=lp,
                                 mean_word_conf=conf)
        if reason is not None:
            with self._drops_lock:
                self._drops.append(Drop(raw, reason, None, lp, final, conf))
                del self._drops[:-DROP_HISTORY]
            return ""
        return self.lexicon.apply(normalise(raw))

    def _recognise(self, block: np.ndarray) -> tuple[str, float | None, float | None]:
        """`(text, mean token log-prob, mean word confidence)` - one of the two numbers,
        whichever this runtime reports; the other is None. Called with the lock held."""
        model = self._model
        if model is None:  # unloaded between load() and here
            raise NotAvailable("the Parakeet model was unloaded")
        text, lp = decode(model, block)
        return text, lp, None


# -- the GPU helper process --------------------------------------------------------

#: How long the helper may take to say it is listening. Generous against the 16 s first CUDA
#: load, and still a bound: a helper that has stopped answering must become a message.
GPU_START_TIMEOUT_SEC = 120.0
GPU_REQUEST_TIMEOUT_SEC = 60.0

_job_handle = None


def _bind_to_job(proc: subprocess.Popen) -> bool:
    """Tie `proc` to this process with a Windows Job Object, so it dies when Flow does.

    `KILL_ON_JOB_CLOSE`: when the last handle to the job closes - which Windows does when
    this process ends *for any reason*, a hard kill and a crash included - every process in
    the job is terminated. A GPU helper that outlived Flow would hold the model in video
    memory with nobody to talk to it, which `unload()` and `atexit` cover on a clean exit
    and cannot on any other. Best effort: False if this is not Windows or the OS said no,
    and the callers still stop the helper themselves.
    """
    global _job_handle
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _job_handle is None:
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return False
            info = _Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                                    ctypes.sizeof(info)):
                return False
            _job_handle = job  # held for the life of the process: closing it is the kill
        return bool(kernel32.AssignProcessToJobObject(_job_handle, int(proc._handle)))
    except (OSError, AttributeError, ValueError):
        return False


def _free_port() -> int:
    """A port nothing is listening on, on the loopback interface only."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wav(audio: np.ndarray) -> bytes:
    """Mono float32 at 16 kHz as the 16-bit WAV the helper accepts."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return out.getvalue()


def mean_word_conf(words) -> float | None:
    """The mean of the per-word confidences the helper reported, or None.

    A word's `conf` is NeMo's `max_prob`: the probability of the token the decoder emitted,
    the minimum over the word's tokens, in (0, 1]. None, not 1.0, when there are no words.
    """
    values = [w["conf"] for w in (words or []) if isinstance(w.get("conf"), (int, float))]
    return float(np.mean(values)) if values else None


class _Helper:
    """One running `parakeet-server`: started, waited on, asked, and stopped.

    A process and not the C API (`parakeet.dll` through ctypes) for the reason `native.py`
    gives: a crash in a native library is an exit code here and a dead interpreter there,
    and a process can be killed to free the GPU. Bound to **127.0.0.1** explicitly
    (`--host`; the default is the same, and the docker image's is not): a dictation engine
    is not something to leave listening on the LAN. One request at a time, which is all a
    dictation session makes.
    """

    def __init__(self, exe: Path, model: Path, env_dirs: list[str] | None = None,
                 prefix: list[str] | None = None) -> None:
        self.exe, self.model = Path(exe), Path(model)
        self.env_dirs = list(env_dirs or [])
        #: Words to put in front of the executable. Empty in the product; a test's stand-in
        #: for the server is a script, run as `[python, script, ...]`.
        self.prefix = list(prefix or [])
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self._log = ""

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def argv(self) -> list[str]:
        return [*self.prefix, str(self.exe), "--model", str(self.model), "--host", "127.0.0.1",
                "--port", str(self.port)]

    def start(self, timeout: float = GPU_START_TIMEOUT_SEC) -> None:
        """Launch the process and wait until it says it is listening, or raise why not."""
        self.port = _free_port()
        env = dict(os.environ)
        if self.env_dirs:
            env["PATH"] = os.pathsep.join(self.env_dirs + [env.get("PATH", "")])
        fd, self._log = tempfile.mkstemp(prefix="flow-parakeet-", suffix=".log")
        try:
            with os.fdopen(fd, "wb") as sink:
                self.proc = subprocess.Popen(
                    self.argv(), env=env, stdout=sink, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self._forget_log()
            raise NotAvailable(f"could not start the GPU helper: {exc}") from exc
        _bind_to_job(self.proc)
        deadline = time.monotonic() + timeout
        while True:
            if "listening on" in self.log_text():
                return
            if self.proc.poll() is not None:
                raise NotAvailable(self.failure())
            if time.monotonic() > deadline:
                self.stop()
                raise NotAvailable(f"the GPU helper did not start within {timeout:.0f} s")
            time.sleep(0.05)

    def log_text(self) -> str:
        try:
            return Path(self._log).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def failure(self) -> str:
        """Why the helper is not answering, in a sentence: its own last words, or what they mean."""
        text = self.log_text()
        lowered = text.lower()
        if "out of memory" in lowered or "cudamalloc failed" in lowered:
            return "not enough video memory for Parakeet on this GPU"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        code = self.proc.returncode if self.proc is not None else None
        tail = lines[-1] if lines else "no output"
        return f"the GPU helper stopped (exit {code}): {tail}"[:300]

    def recognise(self, audio: np.ndarray) -> dict:
        """POST one clip and return the helper's `verbose_json` with word confidences."""
        boundary = uuid.uuid4().hex
        parts = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in (("response_format", "verbose_json"),
                         ("timestamp_granularities[]", "word")))
        body = (parts + (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                         f'filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()
                + _wav(audio) + f"\r\n--{boundary}--\r\n".encode())
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                              timeout=GPU_REQUEST_TIMEOUT_SEC)
            try:
                conn.request("POST", "/v1/audio/transcriptions", body,
                             {"Content-Type": f"multipart/form-data; boundary={boundary}"})
                answer = conn.getresponse()
                payload = answer.read()
            finally:
                conn.close()
        except (OSError, http.client.HTTPException) as exc:
            if self.proc is not None:
                try:
                    # A helper that just died may not have finished dying: let its exit code
                    # be the answer rather than "did not answer".
                    self.proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
            if not self.alive:
                raise NotAvailable(self.failure()) from exc
            raise NotAvailable(f"the GPU helper did not answer: {exc}") from exc
        if answer.status != 200:
            raise NotAvailable(f"the GPU helper refused the audio (HTTP {answer.status})")
        import json

        try:
            return json.loads(payload)
        except ValueError as exc:
            raise NotAvailable("the GPU helper's answer was not JSON") from exc

    def stop(self) -> None:
        """Ask the process to end, then insist. Idempotent; frees the GPU's memory."""
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
        self._forget_log()

    def _forget_log(self) -> None:
        try:
            if self._log:
                os.unlink(self._log)
        except OSError:
            pass
        self._log = ""


def start_helper(backend: str, model_dir: Path | None = None) -> _Helper:
    """A running, warmed helper for `backend`: verified, started, and one decode in.

    The executable's hash is checked first. The warm-up decode is what pays the first-run
    cost (CUDA kernels JIT-compiled on a card the release was not built for) here, where
    the Models page says "loading", rather than inside somebody's first sentence.
    """
    exe = verify_runtime(backend)
    root = Path(model_dir) if model_dir else variant_dir("gpu")
    model = root / VARIANTS["gpu"].files[0].name
    if not model_present("gpu", root):
        raise NotAvailable(f"model not downloaded yet ({root})")
    dirs = cuda_dirs() if backend == "cuda" else []
    if backend == "cuda" and not dirs:
        raise NotAvailable('the CUDA runtime is not installed: uv pip install -e ".[cuda]"')
    helper = _Helper(exe, model, dirs)
    atexit.register(helper.stop)
    try:
        helper.start()
        helper.recognise(np.zeros(SAMPLE_RATE, dtype=np.float32))
    except BaseException:
        helper.stop()
        raise
    try:
        (runtime_dir(backend) / LOADED_MARKER).write_text("loaded once\n", encoding="utf-8")
    except OSError:
        pass  # only the page's promise of how long the next load takes
    return helper


def decode_full(model, audio: np.ndarray) -> tuple[str, float | None, float | None]:
    """`(text, mean token log-prob, mean word confidence)` from either runtime's model, for the
    benchmark: whichever number the runtime reports, and None for the other."""
    if isinstance(model, _Helper):
        answer = model.recognise(audio)
        return ((answer.get("text") or "").strip(), None,
                mean_word_conf(answer.get("words")))
    text, lp = decode(model, audio)
    return text, lp, None


class ParakeetGpuTranscriber(ParakeetTranscriber):
    """The GPU build: parakeet.cpp's server as a helper process, behind the same surface.

    Loading starts the process (hash-checked first) and warms it; unloading stops it, which
    is what returns the model's video memory; a helper that dies mid-session is a
    `NotAvailable` with its last words, and the next decode starts a fresh one. Its quality
    signal is the helper's per-word confidence rather than a token log-probability, so it is
    gated by `clean.WORD_CONF_MIN`.
    """

    def __init__(self, backend: str | None = None, model_dir: Path | None = None,
                 lexicon: Lexicon | None = None, starter=None) -> None:
        super().__init__("gpu", model_dir, None, lexicon)
        self._backend = backend
        #: Overridable so tests need no real executable: `starter(backend, model_dir)`.
        self._starter = starter or start_helper

    def identity(self) -> list[tuple[str, str]]:
        """The ONNX components replaced by the helper: its release, backend and exact
        executable. The hash is the pinned one `verify_runtime` refuses to launch without,
        so it names the binary that actually ran - its first 16 hex digits, because the
        trace takes tokens of at most 40 characters and that is plenty to tell builds apart."""
        variant = VARIANTS[self.variant]
        out = [("engine", f"parakeet-{self.variant}"),
               (f"model:{variant.name}", variant.revision)]
        backend = self.backend
        if backend in RUNTIMES:
            out.append(("parakeet.cpp", f"{CPP_VERSION}-{backend}"))
            out.append((SERVER_EXE, RUNTIMES[backend].exe_sha256[:16]))
        return out

    @property
    def backend(self) -> str:
        """"cuda" or "vulkan" - the backend this transcriber runs on, or would."""
        return self._backend or gpu_backend()[0]

    @property
    def device(self) -> str:  # type: ignore[override]
        return self.backend or "cpu"

    @property
    def loaded(self) -> bool:
        helper = self._model
        return helper is not None and helper.alive

    def load(self, final=None) -> None:
        with self._lock:
            if self._model is not None and self._model.alive:
                return
            self._loading = True
            try:
                self._model = None
                backend = self._backend or gpu_backend()[0]
                if not backend:
                    raise NotAvailable(gpu_backend()[1])
                self._model = self._starter(backend, self._dir)
            finally:
                self._loading = False

    def unload(self) -> None:
        with self._lock:
            helper, self._model = self._model, None
        if helper is not None:
            helper.stop()

    def _recognise(self, block):
        helper = self._model
        if helper is None or not helper.alive:
            self._model = None
            raise NotAvailable(helper.failure() if helper is not None
                               else "the Parakeet GPU helper is not running")
        answer = helper.recognise(block)
        return (answer.get("text") or "").strip(), None, mean_word_conf(answer.get("words"))


def make_transcriber(variant: str | None, lexicon: Lexicon | None = None) -> ParakeetTranscriber:
    """The transcriber for a profile's `parakeet_model`, resolved to a build."""
    key = resolve_variant(variant)
    if key == "gpu":
        return ParakeetGpuTranscriber(lexicon=lexicon)
    return ParakeetTranscriber(key, lexicon=lexicon)
