"""Speech models for Flow Home's Models page: what exists, what is here, and getting more.

**The numbers are measurements, and say whose.** `CATALOG` carries the table in
`flow/asr.py` (the `CUDA_MODEL` block): word error on 300 clips of accented English from
EdAcc, and real-time factor, both measured on the development machine's GTX 1070 at int8.
The page labels them that way. They are a fair comparison between models and not a
promise about somebody else's voice or card — Voice's accuracy check is what measures
theirs.

**Two models are marked, not hidden.** `distil-large-v3.5` has the lowest error of any
model here, and it and `large-v3-turbo` report no `no_speech_prob` — so the hallucination
guard in `clean.py` cannot fire for them, and they hear "thank you" in an empty room.
`asr.reports_no_speech` keeps them usable; the page says what they cost.

**Downloads report bytes.** faster-whisper downloads through `huggingface_hub` with the
progress bar switched off (`faster_whisper.utils.disabled_tqdm`), which is why a first
run said "loading the model" over three gigabytes. This calls `snapshot_download` with
the same file patterns and a progress class of its own, which `huggingface_hub` 1.x
feeds with byte counts for the whole snapshot. A version that does not is still counted,
in files.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass

#: The files faster-whisper downloads for a model, and nothing else — the same list
#: `faster_whisper.utils.download_model` asks for, so a model fetched here is one it
#: finds in the cache and never fetches again.
ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


@dataclass(frozen=True)
class Spec:
    """One model Flow can run."""

    name: str
    repo: str
    #: What the download weighs, about — measured as the models sit on disk here.
    size: int
    #: Errors per 100 words on the EdAcc slice, GTX 1070 int8. None: not measured.
    errors: float | None = None
    #: Real-time factor on the same card. None: not measured there.
    rtf: float | None = None
    #: A few words for the row, when the model has a job only it does.
    note: str = ""
    #: No usable `no_speech_prob`, so it invents words in silence.
    blind: bool = False


_MB = 1024 * 1024

CATALOG: tuple[Spec, ...] = (
    Spec("large-v3", "Systran/faster-whisper-large-v3", 2970 * _MB, 16.8, 0.190,
         note="the most accurate model with a working silence guard"),
    Spec("large-v2", "Systran/faster-whisper-large-v2", 2970 * _MB, 17.0, 0.211),
    Spec("distil-large-v3.5", "distil-whisper/distil-large-v3.5-ct2", 1510 * _MB, 16.0, 0.104,
         blind=True),
    Spec("large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1620 * _MB, 17.8,
         0.116, blind=True),
    Spec("distil-large-v3", "Systran/faster-distil-whisper-large-v3", 1510 * _MB, 18.1, 0.111,
         blind=True),
    Spec("medium.en", "Systran/faster-whisper-medium.en", 1530 * _MB, 18.3, 0.131),
    Spec("small.en", "Systran/faster-whisper-small.en", 464 * _MB, 19.4, 0.070,
         note="the most accurate model a CPU can run in time"),
    Spec("small", "Systran/faster-whisper-small", 464 * _MB, None, 0.070,
         note="multilingual; the live preview on a GPU"),
    Spec("base.en", "Systran/faster-whisper-base.en", 141 * _MB, None, None,
         note="the live preview on a CPU"),
)

BY_NAME = {spec.name: spec for spec in CATALOG}

#: What `errors` and `rtf` were measured on, said wherever they are shown.
MEASURED_ON = "300 clips of accented English (EdAcc), on a GTX 1070"


def human(size: int) -> str:
    """Bytes as somebody reads a download: '2.9 GB', '464 MB'."""
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB"
    return f"{size / _MB:.0f} MB"


def cache_dir() -> str:
    """Where huggingface_hub keeps models on this machine, as it resolves it."""
    try:
        from huggingface_hub import constants

        return str(constants.HF_HUB_CACHE)
    except Exception:
        return ""


def on_disk() -> dict[str, int]:
    """{repo id: bytes} for every repo in the cache. Empty when there is no cache."""
    try:
        from huggingface_hub import scan_cache_dir

        info = scan_cache_dir()
    except Exception:
        return {}
    return {repo.repo_id: repo.size_on_disk for repo in info.repos}


def complete(repo: str) -> bool:
    """Whether a finished copy of `repo` is in the cache — `model.bin` is the last file a
    download writes into the snapshot, so its presence means the rest is there too."""
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(repo, "model.bin"), str)
    except Exception:
        return False


def delete(repo: str) -> bool:
    """Remove every revision of `repo` from the cache. True when anything was removed."""
    try:
        from huggingface_hub import scan_cache_dir

        info = scan_cache_dir()
        hashes = [rev.commit_hash for r in info.repos if r.repo_id == repo
                  for rev in r.revisions]
        if not hashes:
            return False
        info.delete_revisions(*hashes).execute()
        return True
    except Exception:
        return False


# -- the machine ---------------------------------------------------------------------


_GPU: dict | None = None


def gpu() -> dict | None:
    """{"name", "memory_mb"} for the first NVIDIA card, from `nvidia-smi`, or None.

    Asked once per process: the card does not change mid-session, and the query is a
    process start. CTranslate2 reports whether CUDA works but not what the card is
    called, and a page that says "GPU" without naming it cannot be checked by the person
    reading it.
    """
    global _GPU
    if _GPU is not None:
        return _GPU or None
    _GPU = {}
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=flags,
        ).stdout.strip().splitlines()
        if out:
            name, _, memory = out[0].partition(",")
            _GPU = {"name": name.strip(), "memory_mb": int(float(memory.strip() or 0))}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return _GPU or None


def compute_types(device: str) -> list[str]:
    """What CTranslate2 can run on `device` here — the set gpu-pascal.md reads a card by."""
    try:
        import ctranslate2

        return sorted(ctranslate2.get_supported_compute_types(device))
    except Exception:
        return []


# -- downloads -----------------------------------------------------------------------


class Cancelled(Exception):
    """Raised inside the download's progress callback to stop it."""


@dataclass
class Download:
    """One download's state, as the page shows it."""

    name: str
    state: str = "running"  # running | done | failed | cancelled
    done: int = 0
    total: int = 0
    #: Files, for a huggingface_hub that does not report bytes.
    files_done: int = 0
    files_total: int = 0
    error: str = ""
    #: Swap to this model when the download finishes: "final", "partial" or "".
    then_use: str = ""
    cancel: threading.Event | None = None

    def public(self) -> dict:
        return {"state": self.state, "done": self.done, "total": self.total,
                "files_done": self.files_done, "files_total": self.files_total,
                "error": self.error}


def _progress_class(job: Download):
    """A tqdm the snapshot download can drive, which records into `job` and draws nothing.

    `huggingface_hub` builds three bars from the class it is handed: the snapshot's bytes
    ("Reconstructing…"), the bytes on the wire ("Downloading bytes"), and the count of
    files. The first is the one that ends at the model's size on disk; the file count is
    what is left when a version reports no bytes. Every update checks for cancel, and
    raising there is what stops the download: the exception comes out of the worker
    thread and out of `snapshot_download`.
    """
    from tqdm.auto import tqdm as base

    class _Bar(base):
        def __init__(self, *args, **kwargs):
            desc = str(kwargs.get("desc") or "")
            self._kind = ("bytes" if desc.startswith("Reconstructing")
                          else "wire" if desc.startswith("Downloading") else "files")
            self._count = 0
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)
            if self._kind == "files" and kwargs.get("total"):
                job.files_total = int(kwargs["total"])

        def update(self, n=1):
            if job.cancel is not None and job.cancel.is_set():
                raise Cancelled()
            self._count += int(n or 0)
            if self._kind == "bytes":
                job.done = self._count
                job.total = int(self.total or 0)
            elif self._kind == "files":
                job.files_done = self._count
                if self.total:
                    job.files_total = int(self.total)
            return super().update(n)

    return _Bar


class Downloader:
    """Downloads on threads of their own, one per model, with their state kept for the page."""

    def __init__(self, on_done=None) -> None:
        self._jobs: dict[str, Download] = {}
        self._lock = threading.Lock()
        #: Called with the finished `Download` on its thread. Home uses it to swap to a
        #: model somebody chose before it was here.
        self.on_done = on_done

    def jobs(self) -> dict[str, Download]:
        with self._lock:
            return dict(self._jobs)

    def start(self, spec: Spec, then_use: str = "") -> Download:
        """Start downloading `spec`, or return the download already running."""
        with self._lock:
            job = self._jobs.get(spec.name)
            if job is not None and job.state == "running":
                if then_use:
                    job.then_use = then_use
                return job
            job = Download(spec.name, total=spec.size, then_use=then_use,
                           cancel=threading.Event())
            self._jobs[spec.name] = job
        threading.Thread(target=self._run, args=(spec, job), daemon=True,
                         name=f"download-{spec.name}").start()
        return job

    def cancel(self, name: str) -> bool:
        with self._lock:
            job = self._jobs.get(name)
        if job is None or job.state != "running" or job.cancel is None:
            return False
        job.cancel.set()
        return True

    def _run(self, spec: Spec, job: Download) -> None:
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(spec.repo, allow_patterns=ALLOW_PATTERNS,
                              tqdm_class=_progress_class(job))
            job.state = "done"
            if job.total and job.done < job.total:
                job.done = job.total
        except Cancelled:
            job.state = "cancelled"
        except Exception as exc:
            job.state = "failed"
            job.error = _why(exc)
        if job.state == "done" and self.on_done is not None:
            try:
                self.on_done(job)
            except Exception:
                pass


def _why(exc: Exception) -> str:
    """A download failure, said the way somebody can act on."""
    text = str(exc) or type(exc).__name__
    lowered = text.lower()
    if any(word in lowered for word in ("connection", "resolve", "offline", "timed out",
                                        "max retries", "network")):
        return "could not reach huggingface.co - check the connection and try again"
    if "space" in lowered and "disk" in lowered or "no space" in lowered:
        return "not enough disk space"
    return text[:200]


class ModelManager:
    """The Models page's view of the machine, and the three things it can do to it."""

    #: How long the cache scan is trusted. It walks the cache directory, and the page
    #: asks for it every couple of seconds while a download is running.
    SCAN_TTL = 2.0

    def __init__(self, session, on_downloaded=None) -> None:
        self.session = session
        self.downloads = Downloader(on_done=on_downloaded)
        self._scan: tuple[float, dict[str, int]] = (0.0, {})

    def _disk(self) -> dict[str, int]:
        when, sizes = self._scan
        if time.monotonic() - when > self.SCAN_TTL:
            sizes = on_disk()
            self._scan = (time.monotonic(), sizes)
        return sizes

    def forget_scan(self) -> None:
        self._scan = (0.0, {})

    def in_use(self) -> dict[str, list[str]]:
        """{model name: ["partial"] / ["final"] / both} for what the session runs now."""
        names = getattr(getattr(self.session, "asr", None), "names", None)
        out: dict[str, list[str]] = {}
        if isinstance(names, tuple) and len(names) == 2:
            out.setdefault(names[0], []).append("partial")
            out.setdefault(names[1], []).append("final")
        return out

    def snapshot(self) -> dict:
        """Everything the speech half of the page draws."""
        asr = getattr(self.session, "asr", None)
        sizes = self._disk()
        jobs = self.downloads.jobs()
        using = self.in_use()
        device = getattr(asr, "device", "cpu") if asr is not None else "cpu"
        rows = []
        for spec in CATALOG:
            here = complete(spec.repo)
            job = jobs.get(spec.name)
            rows.append({
                "name": spec.name,
                "catalog": True,
                "size": (sizes.get(spec.repo) or spec.size) if here else spec.size,
                "size_text": human(sizes.get(spec.repo) or spec.size),
                "installed": here,
                "errors": spec.errors,
                "speed": round(1 / spec.rtf, 1) if spec.rtf else None,
                "note": spec.note,
                "blind": spec.blind,
                "in_use": using.get(spec.name, []),
                "download": job.public() if job is not None and
                (job.state == "running" or job.state == "failed") else None,
            })
        # A model named by a flag or a hand-edited profile that is not in the catalog is
        # still the model in use, and the page must not pretend otherwise.
        for name, roles in using.items():
            if name not in BY_NAME:
                rows.append({"name": name, "catalog": False, "size": None, "size_text": "",
                             "installed": True,
                             "errors": None, "speed": None, "note": "chosen outside Flow Home",
                             "blind": False, "in_use": roles, "download": None})
        from ..asr import default_models

        auto_partial, auto_final = default_models(device)
        asked = getattr(asr, "asked", (None, None)) if asr is not None else (None, None)
        if not (isinstance(asked, tuple) and len(asked) == 2):
            asked = (None, None)
        info = gpu() if device == "cuda" or sys.platform == "win32" else None
        return {
            "models": rows,
            "measured_on": MEASURED_ON,
            "device": device,
            "device_asked": getattr(asr, "_device", "auto") if asr is not None else "auto",
            "why_cpu": _why_cpu(device),
            "gpu": info,
            "compute_types": compute_types(device),
            "loading": bool(getattr(asr, "loading", False)),
            "automatic": {"partial": auto_partial, "final": auto_final},
            "chosen": {"partial": asked[0], "final": asked[1]},
            "cache": {"path": cache_dir(),
                      "bytes": sum(sizes.get(s.repo, 0) for s in CATALOG),
                      "text": human(sum(sizes.get(s.repo, 0) for s in CATALOG))},
            "swappable": callable(getattr(asr, "swap", None)),
        }


def _why_cpu(device: str) -> str:
    if device != "cpu":
        return ""
    try:
        from ..asr import cuda_reason

        return cuda_reason()
    except Exception:
        return ""
