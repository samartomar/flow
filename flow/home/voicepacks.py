"""Better voices, added from Flow Home (decisions.md 2026-09-23, "Better voices from Flow
Home").

Every voice Windows lets a program use is the 2013 generation, and installing Windows
voices does not change that — `speak.installed_voices` carries the measurement. Two
engines do: **Piper**, which speaks on this PC, and **the Microsoft natural voices**, the
family Narrator's Ava, Guy and Sonia come from, reached over Microsoft's speech service.
Both were extras somebody installed from a terminal. Models ▸ Better voices adds them with
a press:

- **The engine** — `piper-tts` or `edge-tts`, installed into the environment this Flow
  runs from, at the exact versions `uv.lock` resolved for the `voice` and `edge`
  extras: `uv pip install` when uv is here, `python -m pip` when pip is, and neither in the
  Windows download, which ships both engines instead of installing them. The default
  install still declares three dependencies (R16): an engine arrives when somebody asks.
- **Piper's voices** — eight English voices from Piper's own catalogue, fetched into
  `~/.flow/voices/` with progress and checked against the catalogue's MD5 before they are
  used, as a speech model is fetched on the same page.

**Nothing here changes the voice Flow speaks with.** Adding the Microsoft voices lists
them; choosing one — which is what sends an answer's text to Microsoft — is still a
choice made in the list above, as it always was (`flow/edge.py`).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .models import human

#: The two engines, by the name the page and the voice list use. `spec` is the extra's own
#: requirement in `pyproject.toml` (a test holds them equal), `module` what has to import
#: for the engine to be there, `size` what the install fetches, measured 2026-09-23 on
#: PyPI for piper-tts 1.8.0, the version pinned below: its
#: Windows wheel is 34.1 MB (onnxruntime, which it runs on,
#: already came with faster-whisper); edge-tts and aiohttp with its eight small
#: dependencies are about 2 MB.
#:
#: The number after `>=` is also the oldest copy that works, and `outdated` reads it: an
#: engine already here but below it is offered an update instead of being called "Added".
#: That is not hypothetical. Microsoft's speech service began refusing edge-tts 7.2.8 and
#: older around 2026-10-10 (measured 2026-11-23 from this repository: 7.2.8 is answered
#: HTTP 403 on the handshake, 7.3.1 speaks; the voice *list* still loads on both, which
#: is how a Natural voice could be chosen and say nothing). Every Flow that had added
#: the Microsoft voices before then held a copy that could not speak and said "Added".
#: `old` is what the page says about a copy below the floor.
#:
#: `pin` is what is actually installed: the exact version `uv.lock` resolved for that
#: extra (a test holds them equal). The range alone let a press of "Add" fetch whatever
#: PyPI served that minute — the newest upload, which is the one most likely to be a
#: hijacked account (`exclude-newer` in pyproject.toml makes the same argument for the
#: lock). Pinned here rather than read out of `uv.lock` at install time, because the
#: documented install is `uv tool install git+…`, and that wheel carries no lock to read:
#: a constant works for a checkout and an installed tool alike. Only the engine itself is
#: exact; what it depends on is resolved by the installer, as `uv tool install` does.
ENGINES = {
    "piper": {"spec": "piper-tts>=1.6", "pin": "piper-tts==1.8.0", "module": "piper",
              "extra": "voice", "size": 34_119_688,
              "old": "This copy of Piper is older than this Flow can use."},
    "edge": {"spec": "edge-tts>=7.3", "pin": "edge-tts==7.3.1", "module": "edge_tts",
             "extra": "edge", "size": 2_000_000,
             "old": "Microsoft's voice service no longer answers this copy of its "
                    "voices, so they are silent."},
}

#: Engines whose update is picked up without a restart: pure Python, and imported by
#: Flow at the moment of use (`flow/edge.py` imports `edge_tts` inside each call), so
#: dropping the loaded copy is enough for the next reply to load the new one. Piper is
#: not here: it holds a model and native code, and a second copy of those in one process
#: is not something to find out about in the middle of an answer.
RELOADS = frozenset({"edge"})

#: How long an install may take before it is given up on. A slow connection and a cold
#: uv cache are minutes, not hours.
INSTALL_TIMEOUT_SEC = 600

#: Where Piper's voices come from: its own repository, at the tag the catalogue below was
#: read from, so a later reshuffle upstream cannot change what a name downloads.
#: `HF_ENDPOINT` is honoured, as for the speech models ("Without HuggingFace", the guide).
PIPER_REPO = "rhasspy/piper-voices"
PIPER_REVISION = "v1.0.0"

#: Listen before you download — Piper's own page of samples, one per voice.
PIPER_SAMPLES = "https://rhasspy.github.io/piper-samples/"


@dataclass(frozen=True)
class PiperVoice:
    """One voice from Piper's catalogue, as `voices.json` at `PIPER_REVISION` has it."""

    key: str       # the file stem, and so `Voice.name` after "Piper "
    path: str      # the .onnx under the repository
    accent: str
    quality: str
    size: int      # bytes of the .onnx
    md5: str       # of the .onnx
    json_md5: str  # of the .onnx.json sidecar

    @property
    def label(self) -> str:
        name = self.key.split("-")[1].replace("_", " ").title()
        return f"{name} - {self.accent}, {self.quality} quality"


#: Eight single-speaker English voices, British and American, high quality first. Read
#: from `voices.json` at `PIPER_REVISION` on 2026-09-23. No genders: Piper's catalogue
#: states none, and `piper._gender` explains why Flow does not read one off a name — the
#: samples page is where to hear them.
CATALOG = (
    PiperVoice("en_GB-cori-high", "en/en_GB/cori/high/en_GB-cori-high.onnx",
               "British", "high", 114_219_352,
               "3474a80133d9a03e6870d2ac42c18806", "0f7d42e77a99193006aa34a34442f5e0"),
    PiperVoice("en_US-lessac-high", "en/en_US/lessac/high/en_US-lessac-high.onnx",
               "American", "high", 113_895_201,
               "99d1f6181a7f5ccbe3f117ba8ce63c93", "02e8e364c86b5d3b75e81704b0369856"),
    PiperVoice("en_US-ryan-high", "en/en_US/ryan/high/en_US-ryan-high.onnx",
               "American", "high", 120_786_792,
               "5d879a17bddf5007f76655b445ba78b4", "444ff9d6c17218a0eb1d12a20559d869"),
    PiperVoice("en_GB-alan-medium", "en/en_GB/alan/medium/en_GB-alan-medium.onnx",
               "British", "medium", 63_201_294,
               "8f6b35eeb8ef6269021c6cb6d2414c9b", "b11d9afd0a8f5372c42a52fbd6e021d4"),
    PiperVoice("en_GB-jenny_dioco-medium",
               "en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx",
               "British", "medium", 63_201_294,
               "d08f2f7edf0c858275a7eca74ff2a9e4", "e999a9c0aa535fb42e43b04cebcd65d2"),
    PiperVoice("en_GB-northern_english_male-medium",
               "en/en_GB/northern_english_male/medium/"
               "en_GB-northern_english_male-medium.onnx",
               "Northern English", "medium", 63_201_294,
               "4c9a9735bfb76ad67c8b31b23d6840a0", "0ce3f61a9604616ed475c921fdeedb1a"),
    PiperVoice("en_US-amy-medium", "en/en_US/amy/medium/en_US-amy-medium.onnx",
               "American", "medium", 63_201_294,
               "778d28aeb95fcdf8a882344d9df142fc", "7f37dadb26340c90ebc8088e0b252310"),
    PiperVoice("en_US-hfc_male-medium",
               "en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx",
               "American", "medium", 63_201_294,
               "cd2fda1933f0653d3ddc85e5f30ebdd2", "9b4849dbc1e72f35de7391528dea60d9"),
)
BY_KEY = {v.key: v for v in CATALOG}

#: Bytes read per step of a download, and how long one read may wait.
CHUNK = 1 << 20
READ_TIMEOUT_SEC = 30


def voices_dir() -> Path:
    """Where Piper's voices live — `piper.VOICES_DIR`, read when asked so a test can move
    it."""
    from .. import piper

    return piper.VOICES_DIR


def importable(module: str) -> bool:
    """Whether `module` would import now. Cheap: no import happens."""
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def installed_version(package: str) -> str:
    """The version of `package` on this PC's disk now, or "" when it cannot be read."""
    import importlib.metadata

    importlib.invalidate_caches()
    try:
        return importlib.metadata.version(package)
    except Exception:
        return ""


def _numbers(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


def too_old(have: str, floor: str) -> bool:
    """Whether version `have` is below `floor`. False when either cannot be read as
    numbers: a version Flow cannot compare is left alone, never called old."""
    a, b = _numbers(have), _numbers(floor)
    return a is not None and b is not None and a < b


def _forget(module: str) -> None:
    """Drop a loaded engine, so its next use imports what was just installed."""
    for name in [n for n in sys.modules if n == module or n.startswith(module + ".")]:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()


def installer(spec: str) -> tuple[list[str] | None, str]:
    """The command that installs `spec` into this Flow's own environment, or None and why
    not.

    uv first — `uv run` puts its own path in `UV`, and PATH has it on every machine that
    installed Flow with it — then pip, if the environment has one (a uv environment does
    not). A built download cannot install anything into itself, which is why it ships both
    engines; one that is missing an engine was built without it.
    """
    if getattr(sys, "frozen", False):
        return None, "this download of Flow cannot add packages - it ships both engines"
    uv = os.environ.get("UV") or shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", sys.executable, spec], ""
    if importable("pip"):
        return [sys.executable, "-m", "pip", "install", spec], ""
    return None, f"neither uv nor pip is here to install with - run: uv pip install \"{spec}\""


@dataclass
class Job:
    """One engine install or one voice download, as the page shows it."""

    state: str = "running"  # running | done | failed | cancelled
    done: int = 0
    total: int = 0
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        return {"state": self.state, "done": self.done, "total": self.total,
                "error": self.error}


class Cancelled(Exception):
    pass


class VoicePacks:
    """The Better voices card: the two engines, and Piper's catalogue."""

    def __init__(self, session=None, *, run=subprocess.run, fetch=None) -> None:
        self.session = session
        #: The subprocess runner and the URL opener, replaceable so the suite can say what
        #: an install or a download did without doing either.
        self._run = run
        self._fetch = fetch or (lambda url: urllib.request.urlopen(
            url, timeout=READ_TIMEOUT_SEC))
        self._engines: dict[str, Job] = {}
        self._voices: dict[str, Job] = {}
        self._lock = threading.Lock()

    # The machine, asked through these three so the demo can stand in for it — its "Add
    # Piper" must not install anything into the environment it is running from.

    def _importable(self, module: str) -> bool:
        return importable(module)

    def _installer(self, spec: str) -> tuple[list[str] | None, str]:
        return installer(spec)

    def _folder(self) -> Path:
        return voices_dir()

    def _version(self, package: str) -> str:
        return installed_version(package)

    def _loaded(self, module: str) -> bool:
        return module in sys.modules

    # -- the engines -----------------------------------------------------------------

    def outdated(self, engine: str) -> bool:
        """Whether `engine` is here but older than the oldest copy that works."""
        about = ENGINES[engine]
        package, floor = about["spec"].split(">=")
        return self._importable(about["module"]) and too_old(self._version(package), floor)

    def install(self, engine: str) -> Job:
        """Install `engine` - or update it, which is the same command - or return the
        install already running."""
        if engine not in ENGINES:
            raise ValueError(f"no engine called {engine}")
        with self._lock:
            job = self._engines.get(engine)
            if job is not None and job.state == "running":
                return job
            job = self._engines[engine] = Job(total=ENGINES[engine]["size"])
        threading.Thread(target=self._install, args=(engine, job), daemon=True,
                         name=f"install-{engine}").start()
        return job

    def _install(self, engine: str, job: Job) -> None:
        about = ENGINES[engine]
        # Read before the install: afterwards the disk holds the new copy, and whether
        # this process is still running the old one is what decides the last step.
        stale = self.outdated(engine) and self._loaded(about["module"])
        command, why = self._installer(about["pin"])
        if command is None:
            job.state, job.error = "failed", why
            return
        try:
            done = self._run(command, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=INSTALL_TIMEOUT_SEC,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            job.state = "failed"
            job.error = f"the install took more than {INSTALL_TIMEOUT_SEC // 60} minutes"
            return
        except OSError as exc:
            job.state, job.error = "failed", f"could not run the installer: {exc}"
            return
        if done.returncode != 0:
            job.state, job.error = "failed", _last_line(done.stderr or done.stdout)
            return
        if not self._importable(about["module"]):
            job.state = "failed"
            job.error = "installed, but this Flow cannot load it yet - restart Flow"
            return
        if self.outdated(engine):
            # The installer said yes and the copy on disk is still the old one: another
            # environment was written to, or the pin itself is below the floor.
            job.state = "failed"
            job.error = "the update did not replace the old copy - restart Flow and try again"
            return
        if stale:
            # An update, into a process that has the old copy loaded and would go on
            # being refused with it.
            if engine in RELOADS:
                _forget(about["module"])
            else:
                job.state = "failed"
                job.error = "updated - restart Flow to use it"
                return
        job.state, job.done = "done", job.total
        # Listed now, not at the next launch: the engine's voices join the list, and for
        # the Microsoft voices that is one request to the service for its catalogue.
        _voices_changed(engine)

    # -- Piper's voices ----------------------------------------------------------------

    def download(self, key: str) -> Job:
        voice = BY_KEY.get(key)
        if voice is None:
            raise ValueError("Flow does not know that voice")
        with self._lock:
            job = self._voices.get(key)
            if job is not None and job.state == "running":
                return job
            job = self._voices[key] = Job(total=voice.size)
        threading.Thread(target=self._download, args=(voice, job), daemon=True,
                         name=f"voice-{key}").start()
        return job

    def cancel(self, key: str) -> bool:
        with self._lock:
            job = self._voices.get(key)
        if job is None or job.state != "running":
            return False
        job.cancel.set()
        return True

    def delete(self, key: str) -> bool:
        """Take a downloaded voice off this PC. False when it was not here."""
        if key not in BY_KEY:
            raise ValueError("Flow does not know that voice")
        folder = self._folder()
        gone = False
        for suffix in (".onnx", ".onnx.json"):
            try:
                (folder / f"{key}{suffix}").unlink()
                gone = True
            except FileNotFoundError:
                pass
        if gone:
            _voices_changed("piper")
        return gone

    def _download(self, voice: PiperVoice, job: Job) -> None:
        folder = self._folder()
        model = folder / f"{voice.key}.onnx"
        sidecar = folder / f"{voice.key}.onnx.json"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            # The sidecar first — it is small, and `piper.voices` lists a model only with
            # its sidecar beside it, so the model landing last is what makes it appear.
            self._fetch_to(voice.path + ".json", sidecar, voice.json_md5, None)
            self._fetch_to(voice.path, model, voice.md5, job)
            job.state = "done"
        except Cancelled:
            job.state = "cancelled"
        except Exception as exc:
            job.state, job.error = "failed", _why(exc)
        if job.state != "done":
            # What did not finish goes: the `.part`s, and a sidecar whose model never
            # landed — half a pair is not a voice, and would make the row look done.
            for path in (model, sidecar):
                path.with_name(path.name + ".part").unlink(missing_ok=True)
            if not model.is_file():
                sidecar.unlink(missing_ok=True)
            return
        _voices_changed("piper")

    def _fetch_to(self, path: str, dest: Path, md5: str, job: Job | None) -> None:
        """Fetch one file into `dest` through a `.part`, checked before it is renamed."""
        base = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
        url = f"{base}/{PIPER_REPO}/resolve/{PIPER_REVISION}/{path}"
        part = dest.with_name(dest.name + ".part")
        digest = hashlib.md5()
        with self._fetch(url) as response, open(part, "wb") as out:
            while True:
                if job is not None and job.cancel.is_set():
                    raise Cancelled()
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                if job is not None:
                    job.done += len(chunk)
        if digest.hexdigest() != md5:
            part.unlink(missing_ok=True)
            raise ValueError(f"{dest.name} did not arrive whole - try again")
        os.replace(part, dest)

    # -- what the page draws -------------------------------------------------------------

    def snapshot(self, current_voice: str | None = None) -> dict:
        with self._lock:
            engines = dict(self._engines)
            voices = dict(self._voices)
        folder = self._folder()

        def engine(name: str) -> dict:
            about = ENGINES[name]
            job = engines.get(name)
            here = self._importable(about["module"])
            # Here, and too old to work: the page offers an update, and `can` then means
            # what it means for an engine that is absent - whether this Flow can install.
            old = here and self.outdated(name)
            ready = here and not old
            command, why = (None, "") if ready else self._installer(about["spec"])
            return {
                "installed": here,
                "outdated": old,
                "old": about["old"] if old else "",
                "job": job.public() if job is not None else None,
                "can": ready or command is not None,
                "why": "" if ready or command is not None else why,
                "size_text": human(about["size"]),
                "spec": about["spec"],
            }

        rows = []
        for v in CATALOG:
            job = voices.get(v.key)
            here = (folder / f"{v.key}.onnx").is_file() and \
                (folder / f"{v.key}.onnx.json").is_file()
            rows.append({
                "key": v.key, "label": v.label, "size_text": human(v.size),
                "installed": here, "in_use": current_voice == f"Piper {v.key}",
                "job": job.public() if job is not None and not here else None,
            })
        return {"piper": {**engine("piper"), "voices": rows, "samples": PIPER_SAMPLES},
                "edge": engine("edge")}

    def busy(self) -> bool:
        with self._lock:
            jobs = list(self._engines.values()) + list(self._voices.values())
        return any(j.state == "running" for j in jobs)


def _voices_changed(engine: str) -> None:
    try:
        from ..speak import voices_changed

        voices_changed(engine)
    except Exception:
        pass  # a list that did not refresh is refreshed by the next launch


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return (lines[-1] if lines else "the installer failed and said nothing")[:240]


def _why(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    lowered = text.lower()
    if any(word in lowered for word in ("urlopen", "getaddrinfo", "timed out",
                                        "connection", "unreachable", "network")):
        return "could not reach huggingface.co - check the connection and try again"
    if "no space" in lowered:
        return "not enough disk space"
    return text[:200]
