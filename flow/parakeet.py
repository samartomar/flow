"""NVIDIA Parakeet TDT, through sherpa-onnx, as a `Transcriber` Flow can use instead of Whisper.

**Why this exists.** It is the one engine measured to beat the best Whisper model a CPU can
run, on the same CPU. Parakeet TDT 0.6B v3 (int8), 300 EdAcc clips of accented English,
errors per 100 words, 2026-10-04:

    group      parakeet   small.en
    indian        18.9       21.9
    japanese      26.3       23.4     <- WORSE: the one accent where it loses
    russian        9.9       15.1
    spanish       14.6       16.6
    us-control    19.9       22.1
    all           17.3       19.5     (catalog large-v3 on a GTX 1070: 16.8)

And it is fast where `small.en` is not: **real-time factor 0.070 on CPU with 8 threads**
(14x real time, p50 366 ms, p95 968 ms per clip) against `small.en`'s ~0.54 on the same CPU.
Load is 2.2 s. So a machine with no GPU gets close to large-v3's accuracy at a speed the
live preview can use — which `small.en` cannot offer.

**What it costs, stated rather than discovered.**

- *The runtime is ~93 MB* (`sherpa-onnx` from PyPI, no torch) and the model is a **487,170,055
  byte** `.tar.bz2` that unpacks to 652 MB of encoder. That is why this is an extra
  (`[parakeet]`, R16) and an explicit `--engine parakeet`, and why `--engine auto` never
  picks it: a working Whisper install is not switched on a machine whose owner never asked.
- *One tier.* Whisper has a fast model for partials and a strong one for finals; here the
  same model does both, because at 14x real time there is no speed to buy by splitting.
  `final` is accepted and ignored, and a partial and a final of one clip return the same words.
- *No hotword biasing.* `hotwords` is accepted and ignored — as `native.py` does — so the
  constrained re-decode of a suspected mis-heard command comes back unbiased rather than
  failing. The user's declared corrections (`lexicon`) are still applied after the decode.
- *Japanese-accented English is worse than with `small.en`* (26.3 vs 23.4, above).
- *The silence guard is different, not absent.* Whisper's `no_speech_prob` does not exist
  here. Measured, Parakeet returns nothing on 7 of 8 silence/noise clips where `small.en`
  invented text on **all 8** (caught only by `no_speech_prob` 0.78-0.95) — so it is not
  `blind` in the sense `home/models.py` uses the word. The eighth, fan noise, came back as
  "It is." at a mean token log-probability of -1.10, against real speech at p1 -0.59, p5
  -0.40, p50 -0.11 (n=299). `clean.TOKEN_LOGPROB_MIN` turns that into a drop; it rests on
  that single invention and says so.

**Where the model comes from.** GitHub releases (`k2-fsa/sherpa-onnx`), not huggingface.co —
which matters because `native.py` exists for networks that block the latter. It is kept
under `~/.flow/models/`, beside the profile and the voices, and `fetch()` puts it there.

**Why in-process.** `sherpa-onnx` is a wheel with a Python API; the recogniser is built once
and decoding is a call. No helper process to frame audio over, unlike `native.py`.

`import sherpa_onnx` happens inside `load()` and nowhere else, so importing this module
costs nothing and a default install — which has no `[parakeet]` extra — never breaks on it.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path, PurePosixPath

import numpy as np

from . import SAMPLE_RATE
from .asr import DROP_HISTORY, Drop
from .clean import invented_reason, normalise
from .lexicon import Lexicon

#: What the model is called on disk, and where it lives. Under the user's `~/.flow`
#: with their profile and voices, for the same reason as the voices: it is chosen by the
#: user, survives upgrades, and is removed by deleting a folder.
MODEL_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
MODELS_DIR = Path.home() / ".flow" / "models"
MODEL_DIR = MODELS_DIR / MODEL_NAME

#: The files a usable model directory holds. Presence of all four is what "downloaded"
#: means; a half-extracted directory must not pass for a model.
REQUIRED_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")

#: Where it is fetched from, and how big that is — measured 2026-10-04. The size is
#: checked after the download as a truncation guard (no digest is published beside the
#: asset), and also what the startup line quotes. Unpacked it is about 670 MB.
URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
       f"{MODEL_NAME}.tar.bz2")
ARCHIVE_BYTES = 487_170_055
UNPACKED_BYTES = 670_000_000

#: Per-socket-operation timeout while downloading. Not a deadline for the whole fetch,
#: which is half a gigabyte; a connection that has stopped answering is what this catches.
FETCH_TIMEOUT_SEC = 30.0
_CHUNK = 1024 * 1024

#: sherpa-onnx's `num_threads`. **8, or every core on a smaller machine.** The 0.070
#: real-time factor above was measured at 8 threads on this 24-thread box; more threads
#: than that were not measured, and a recogniser that takes every core of a 4-core laptop
#: starves the UI thread it shares the process with.
MAX_THREADS = 8


def default_threads() -> int:
    return max(1, min(MAX_THREADS, os.cpu_count() or 1))


class NotAvailable(RuntimeError):
    """This machine cannot run the Parakeet engine, with the reason in the message.

    One exception for every way of not having it — no runtime, no model, a download that
    failed — because each means the same to the caller: use Whisper, and say this sentence.
    """


# -- is it here? ---------------------------------------------------------------


#: What to say when the runtime is missing, in one place so the probe and the import agree.
INSTALL_HINT = ("sherpa-onnx is not installed - run: "
                "uv pip install \"sherpa-onnx>=1.13\"  (or the [parakeet] extra)")


def runtime_installed() -> tuple[bool, str]:
    """`(usable, why not)` for the `sherpa-onnx` package, without importing it.

    `find_spec` rather than an import: the import is the expensive part (a native
    library), and `--engine auto` must not pay for an engine it will not choose.
    """
    if sys.modules.get("sherpa_onnx") is not None:
        return True, ""
    try:
        found = importlib.util.find_spec("sherpa_onnx") is not None
    except (ImportError, ValueError):
        found = False
    if found:
        return True, ""
    return False, INSTALL_HINT


def model_present(model_dir: Path | None = None) -> bool:
    """Whether every file of the model is in `model_dir`, and none of them empty."""
    root = Path(model_dir) if model_dir else MODEL_DIR
    try:
        return all((root / name).is_file() and (root / name).stat().st_size > 0
                   for name in REQUIRED_FILES)
    except OSError:
        return False


def available(model_dir: Path | None = None) -> tuple[bool, str]:
    """`(usable, why not)`: the runtime is installed and the model is on disk.

    Cheap and read-only — it never imports the runtime and never downloads, so it is
    safe to ask at startup. Fetching is `fetch()`'s job, and is only done on request.
    """
    ok, why = runtime_installed()
    if not ok:
        return False, why
    if not model_present(model_dir):
        root = Path(model_dir) if model_dir else MODEL_DIR
        return False, f"model not downloaded yet ({root})"
    return True, ""


# -- getting it ----------------------------------------------------------------


def _check_member(member: tarfile.TarInfo, into: Path) -> None:
    """Refuse an archive member that could write outside `into`, or is not a plain file.

    Rejected, not skipped: an archive that tries this is not one to extract the rest of.
    Backslashes count as separators because a name that is harmless to a POSIX tar is a
    traversal on Windows. Links and device nodes are refused outright — the model is four
    ordinary files, and a symlink is how a later member gets written through an earlier one.
    """
    name = member.name.replace("\\", "/")
    parts = PurePosixPath(name).parts
    if (name.startswith("/") or (len(name) > 1 and name[1] == ":")
            or ".." in parts):
        raise NotAvailable(f"unsafe path in archive: {member.name!r}")
    if not (member.isreg() or member.isdir()):
        raise NotAvailable(f"unexpected entry in archive: {member.name!r}")
    target = (into / name).resolve()
    if into.resolve() not in (target, *target.parents):
        raise NotAvailable(f"unsafe path in archive: {member.name!r}")


def extract(archive: Path, into: Path) -> Path:
    """Unpack the `.tar.bz2` into `into` and return the directory holding the model files.

    Every member is checked before any is written. The archive's own top-level directory
    is found rather than assumed, so a release that renames it still unpacks.
    """
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:bz2") as tar:
            members = tar.getmembers()
            for member in members:
                _check_member(member, into)
            # `data` is the stdlib's own belt for the same hazards (3.12+, which is this
            # project's floor); the checks above are what name the refusal.
            tar.extractall(into, members=members, filter="data")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise NotAvailable(f"could not unpack the model: {exc}") from exc
    candidates = [into, *sorted(p for p in into.iterdir() if p.is_dir())]
    for root in candidates:
        if model_present(root):
            return root
    raise NotAvailable("the archive did not contain the Parakeet model files")


def fetch(dest: Path | None = None, progress=None, url: str = URL,
          expected_bytes: int | None = ARCHIVE_BYTES) -> Path:
    """Download and unpack the model into `dest`, atomically. Returns `dest`.

    Downloaded and unpacked in a scratch directory *beside* `dest`, and moved into place
    with one rename only once every file is there and checked — so an interrupted fetch
    leaves nothing at `dest` that `model_present` could mistake for a model, and the next
    launch simply tries again. `progress(done, total)` is called per chunk with byte
    counts (`total` is 0 when the server does not say); the caller decides how often to
    show it. Raises `NotAvailable`, with the reason, for every way this can fail.
    """
    dest = Path(dest) if dest else MODEL_DIR
    parent = dest.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=".parakeet-", dir=parent))
    except OSError as exc:
        raise NotAvailable(f"cannot write to {parent}: {exc}") from exc
    try:
        archive = scratch / "model.tar.bz2"
        done = 0
        request = urllib.request.Request(url, headers={"User-Agent": "flow"})
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SEC) as answer, \
                    open(archive, "wb") as out:
                total = int(answer.headers.get("Content-Length") or 0)
                while True:
                    chunk = answer.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total or (expected_bytes or 0))
        except (OSError, ValueError) as exc:
            raise NotAvailable(f"download failed: {exc}") from exc
        if (total and done != total) or (expected_bytes and done != expected_bytes):
            raise NotAvailable(
                f"download is {done} bytes, expected {expected_bytes or total}")
        root = extract(archive, scratch / "unpacked")
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            os.replace(root, dest)
        except OSError as exc:
            raise NotAvailable(f"could not install the model at {dest}: {exc}") from exc
        return dest
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# -- decoding ------------------------------------------------------------------


def _import_sherpa():
    """The one place `sherpa_onnx` is imported — and only when a recogniser is built."""
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise NotAvailable(f"{INSTALL_HINT} ({exc})") from exc
    return sherpa_onnx


def mean_logprob(result) -> float | None:
    """The mean log-probability of the tokens in a sherpa-onnx result, or None.

    None, not 0.0, when the engine reported nothing: `clean.invented_reason` treats None
    as "no evidence" and a fabricated zero as "very confident".
    """
    probs = getattr(result, "ys_log_probs", None)
    if probs is None or len(probs) == 0:
        return None
    return float(np.mean(np.asarray(probs, dtype=np.float64)))


class ParakeetTranscriber:
    """Satisfies `asr.Transcriber` with one in-process sherpa-onnx recogniser.

    Lazy: constructing it costs nothing, and `load()` — which `Session._warm` calls at a
    moment of its choosing — pays the 2.2 s. `take_drops()` is what makes the hallucination
    gate attributable the way Whisper's is. There is deliberately no `take_confidence`: the
    session reads that on Whisper's `avg_logprob` scale and this engine's numbers are not on
    it, so absent is the honest answer, as for `native.py`.
    """

    def __init__(self, model_dir: Path | None = None, threads: int | None = None,
                 lexicon: Lexicon | None = None) -> None:
        self._dir = Path(model_dir) if model_dir else MODEL_DIR
        self._threads = threads if threads else default_threads()
        #: The user's declared corrections, applied after the decode as for Whisper (P4).
        #: Its terms cannot bias this engine, so only the `wrong -> right` half is used.
        self.lexicon = lexicon if lexicon is not None else Lexicon()
        self._rec = None
        self._loading = False
        #: One recogniser, one decode at a time; also serialises load/unload against it.
        self._lock = threading.Lock()
        self._drops: list[Drop] = []
        self._drops_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    #: Parakeet runs on the CPU here: the tested wheel is the CPU build.
    device = "cpu"

    @property
    def loaded(self) -> bool:
        return self._rec is not None

    @property
    def loading(self) -> bool:
        """True while the recogniser is being built, so the UI can name that wait."""
        return self._loading

    def load(self, final=None) -> None:
        """Build the recogniser. Idempotent; the signature matches Whisper's tier load."""
        with self._lock:
            if self._rec is not None:
                return
            self._loading = True
            try:
                sherpa = _import_sherpa()
                if not model_present(self._dir):
                    raise NotAvailable(f"model not downloaded yet ({self._dir})")
                self._rec = sherpa.OfflineRecognizer.from_transducer(
                    encoder=str(self._dir / "encoder.int8.onnx"),
                    decoder=str(self._dir / "decoder.int8.onnx"),
                    joiner=str(self._dir / "joiner.int8.onnx"),
                    tokens=str(self._dir / "tokens.txt"),
                    model_type="nemo_transducer",
                    num_threads=self._threads,
                    provider="cpu",
                )
            finally:
                self._loading = False

    def unload(self) -> None:
        """Release the recogniser (652 MB of encoder). The idle path calls this."""
        with self._lock:
            self._rec = None

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
            rec = self._rec
            if rec is None:  # unloaded between load() and here
                raise NotAvailable("the Parakeet recogniser was unloaded")
            stream = rec.create_stream()
            stream.accept_waveform(SAMPLE_RATE, block)
            rec.decode_stream(stream)
            result = stream.result
        raw = (getattr(result, "text", "") or "").strip()
        if not raw:
            # What the model does with silence 7 times in 8: nothing to say and nothing
            # to record. A drop here would announce "I did not catch 0 words".
            return ""
        lp = mean_logprob(result)
        reason = invented_reason(raw, None, None, None, mean_token_logprob=lp)
        if reason is not None:
            with self._drops_lock:
                self._drops.append(Drop(raw, reason, None, lp, final))
                del self._drops[:-DROP_HISTORY]
            return ""
        return self.lexicon.apply(normalise(raw))
