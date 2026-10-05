"""NVIDIA Parakeet TDT 0.6B v3, through onnx-asr, as a `Transcriber` Flow can use instead of Whisper.

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

**Two variants, because the trade is real.** `fp32` is **2.4 GB** on disk and loads in about five
seconds; `int8` is **640 MB** and loads in about three. Same decode speed. fp32 is the default
whenever it is downloaded; int8 is the one for a small disk, at 2.2 errors per 100 words more.

**What it costs, stated rather than discovered.**

- *The runtime is ~7 MB* (`onnx-asr`) plus `onnxruntime` — no torch. That is why this is an
  extra (`[parakeet]`, R16) and an explicit choice, and why `--engine auto` never picks it.
- *The model comes from Hugging Face*, `istupakov/parakeet-tdt-0.6b-v3-onnx`, pinned to one
  commit (`REVISION`) so a re-upload cannot change what a user gets, and every large file is
  checked against its published SHA-256. **This build therefore does not avoid
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

import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

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
}

#: About how long `load()` takes, in seconds, for the page to say "(about 3 s)". Measured
#: 2026-10-05 on this machine: fp32 4.4-4.9 s, int8 3.2-3.4 s. A promise of the order of
#: magnitude, not of the second - a colder disk or a smaller CPU takes longer.
LOAD_SEC = {"fp32": 5, "int8": 3}

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


def variant_dir(key: str) -> Path:
    return MODELS_DIR / VARIANTS[key].name


def model_present(key: str, model_dir: Path | None = None) -> bool:
    """Whether every file of variant `key` is in its directory, at exactly the right size.

    By size and not merely by existence: a file cut short is the one failure `fetch()`'s
    atomic rename cannot see on a disk that filled up later or was edited by hand.
    """
    root = Path(model_dir) if model_dir else variant_dir(key)
    try:
        return all((root / f.name).is_file() and (root / f.name).stat().st_size == f.size
                   for f in VARIANTS[key].files)
    except OSError:
        return False


def installed_variants() -> list[str]:
    return [key for key in VARIANTS if model_present(key)]


def resolve_variant(asked: str | None) -> str:
    """Which variant to use for a profile's `parakeet_model`.

    An explicit "fp32" or "int8" is honoured whether or not it is downloaded — the caller
    decides whether to fetch it. "auto" (or nothing) is the most accurate one that is
    here, and fp32, to be downloaded, when none is.
    """
    if asked in VARIANTS:
        return asked
    for key in ("fp32", "int8"):
        if model_present(key):
            return key
    return "fp32"


def installed_bytes(key: str, model_dir: Path | None = None) -> int:
    """What variant `key` takes on disk, for the Models page's size column. 0 when absent."""
    root = Path(model_dir) if model_dir else variant_dir(key)
    try:
        return sum((root / f.name).stat().st_size for f in VARIANTS[key].files)
    except OSError:
        return 0


def available(key: str | None = None, model_dir: Path | None = None) -> tuple[bool, str]:
    """`(usable, why not)`: the runtime is installed and variant `key` is on disk.

    Cheap and read-only — it never imports the runtime and never downloads, so it is
    safe to ask at startup. Fetching is `fetch()`'s job, and is only done on request.
    """
    ok, why = runtime_installed()
    if not ok:
        return False, why
    key = key or resolve_variant("auto")
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
    """Where one file of the model is, at the pinned revision."""
    return f"https://huggingface.co/{repo}/resolve/{revision}/{name}"


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


def fetch(key: str = "fp32", dest: Path | None = None, progress=None,
          cancelled=None, url_for=None) -> Path:
    """Download variant `key` into `dest`, atomically. Returns `dest`.

    Every file goes into a scratch directory *beside* `dest`, verified as it lands, and the
    directory is renamed into place with one `os.replace` only once all of them are there —
    so an interrupted fetch leaves nothing at `dest` that `model_present` could mistake for
    a model, and the next attempt simply starts again (there is no resume). `progress(done,
    total)` is called per chunk with byte counts across the whole variant; the caller
    decides how often to show it. `cancelled`, when given, is asked before each chunk and
    before the rename; true raises `Cancelled` and the scratch directory goes with it, so a
    cancel leaves exactly what a failure does. `url_for(name)` overrides where files come
    from (tests use `file://`); the default is the pinned revision on huggingface.co.
    Raises `NotAvailable`, with the reason, for every way this can fail.
    """
    variant = VARIANTS[key]
    dest = Path(dest) if dest else variant_dir(key)
    url_for = url_for or hub_url
    parent = dest.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=".parakeet-", dir=parent))
    except OSError as exc:
        raise NotAvailable(f"cannot write to {parent}: {exc}") from exc
    try:
        before = 0
        for file in variant.files:
            _download(url_for(file.name), scratch / file.name, file, before,
                      variant.bytes, progress, cancelled)
            before += file.size
        if cancelled is not None and cancelled():
            raise Cancelled()
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            os.replace(scratch, dest)
        except OSError as exc:
            raise NotAvailable(f"could not install the model at {dest}: {exc}") from exc
        return dest
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# -- decoding ------------------------------------------------------------------


def _import_runtime():
    """The one place `onnx_asr` and `onnxruntime` are imported — when a model is built."""
    try:
        import onnx_asr
        import onnxruntime
    except ImportError as exc:
        raise NotAvailable(f"{INSTALL_HINT} ({exc})") from exc
    return onnx_asr, onnxruntime


def load_model(key: str, model_dir: Path | None = None, threads: int | None = None):
    """Build the onnx-asr model for variant `key`, on the CPU, with results that carry
    per-token log-probabilities. Shared by the transcriber and the benchmark, so the
    benchmark measures the build Flow runs."""
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
        #: "fp32" or "int8". Read by `Session` to tell a variant switch from a no-op.
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
            model = self._model
            if model is None:  # unloaded between load() and here
                raise NotAvailable("the Parakeet model was unloaded")
            raw, lp = decode(model, block)
        if not raw:
            # What the model does with silence: nothing to say and nothing to record. A
            # drop here would announce "I did not catch 0 words".
            return ""
        reason = invented_reason(raw, None, None, None, mean_token_logprob=lp)
        if reason is not None:
            with self._drops_lock:
                self._drops.append(Drop(raw, reason, None, lp, final))
                del self._drops[:-DROP_HISTORY]
            return ""
        return self.lexicon.apply(normalise(raw))
