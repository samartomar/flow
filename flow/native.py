"""Apple's on-device recogniser, as a `Transcriber` Flow can use instead of Whisper.

**Why this exists.** faster-whisper's CT2 weights are published on HuggingFace and
nowhere else official — SYSTRAN's GitHub ships the library, not the models. On a network
that blocks `huggingface.co` that leaves copying 138 MB by hand onto every machine.
macOS has a speech engine already installed, with models the OS downloads through
System Settings, and using it ends the transport problem rather than routing around it.

**Why a subprocess.** The dependency budget is three (R16) and PyObjC is not one of them.
Flow already shells out to `codex` and `claude`, so a process that reads audio and writes
text is a shape this app has. It also puts every Objective-C API behind a pipe, where a
crash is an exit code instead of a dead interpreter.

**What it costs, stated rather than discovered.** Apple's recogniser reports no
`no_speech_prob`, so `clean.py` falls to the narrow whole-utterance filler check it
documents for exactly this case — hallucination filtering is weaker here than with
Whisper. `hotwords` has no equivalent on this path and is accepted and ignored, which
makes the constrained re-decode of a suspected mis-heard command a no-op rather than an
error. And the permission prompt is attributed to whatever launched Flow, usually a
terminal, because this is not a signed bundle.
"""

from __future__ import annotations

import struct
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

#: The helper's source, and where its build lands. Built into the user's cache rather
#: than into the checkout: a repo on a read-only share still has to work, and a binary
#: in a source tree is a thing that gets committed by accident.
SOURCE = Path(__file__).resolve().parent.parent / "native" / "flow_stt.swift"
BUILD_DIR = Path.home() / ".flow" / "bin"
BINARY = BUILD_DIR / "flow-stt"

#: How long a build may take before it is called a failure. `swiftc` on a cold toolchain
#: is slow; a launch is not the place to find out how slow.
BUILD_TIMEOUT_SEC = 120.0
#: How long one utterance may take. The helper has its own 30 s bound inside; this is the
#: outer one for a process that has stopped answering at all.
DECODE_TIMEOUT_SEC = 40.0


class NotAvailable(RuntimeError):
    """This machine cannot run the native engine, with the reason in the message.

    One exception for every way of not having it — wrong platform, no toolchain, a build
    that failed, a permission the user declined — because every one of them means the
    same thing to the caller: use Whisper, and say this sentence to explain why.
    """


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          check=False)


def build(force: bool = False) -> Path:
    """Compile the helper if it is not already built. Returns the binary's path.

    Built on first use rather than shipped, because a prebuilt binary would have to be
    signed and notarised to be worth anything on a Mac, and an unsigned one is a
    Gatekeeper prompt with a worse story than the source it came from. `swiftc` is
    present wherever Xcode Command Line Tools are, which is most machines that have
    ever run `git`.
    """
    if sys.platform != "darwin":
        raise NotAvailable("the native engine is macOS only")
    if BINARY.exists() and not force:
        return BINARY
    if not SOURCE.exists():
        raise NotAvailable(f"helper source missing: {SOURCE}")
    try:
        which = _run(["xcrun", "--find", "swiftc"], 20.0)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotAvailable(f"no Swift toolchain: {exc}") from exc
    if which.returncode != 0:
        raise NotAvailable("no Swift toolchain — run: xcode-select --install")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # `-parse-as-library` is required, not tuning: a single-file executable is
        # parsed as a script, and `@main` cannot coexist with script mode.
        built = _run(["xcrun", "swiftc", "-O", "-parse-as-library",
                      "-o", str(BINARY), str(SOURCE)], BUILD_TIMEOUT_SEC)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotAvailable(f"build failed: {exc}") from exc
    if built.returncode != 0 or not BINARY.exists():
        # The compiler's own words, trimmed. A build error the user cannot see is a
        # feature that is missing for no stated reason.
        detail = (built.stderr or built.stdout or "").strip().splitlines()
        raise NotAvailable("build failed: " + (detail[-1] if detail else "no output"))
    return BINARY


def available() -> tuple[bool, str]:
    """`(usable, why not)` for this machine, without starting a session on it.

    Runs the helper's own `--probe`, which is the only honest check: the engine exists
    when the OS says it does, the locale resolves, on-device recognition is supported —
    which needs Dictation enabled so macOS has downloaded the offline model — and the
    user has granted the permission. Anything less is a guess that fails later, in the
    middle of somebody's first sentence.
    """
    try:
        binary = build()
    except NotAvailable as exc:
        return False, str(exc)
    try:
        probe = _run([str(binary), "--probe"], 60.0)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"probe failed: {exc}"
    if probe.returncode != 0:
        return False, (probe.stderr or "probe refused").strip().splitlines()[-1]
    return True, ""


class NativeTranscriber:
    """Satisfies `asr.Transcriber` by talking to one long-lived helper process.

    Long-lived rather than one process per utterance, because starting a process and
    authorising a recogniser costs more than the decode does. The process is started
    lazily on the first decode — `load()` is what a caller uses to pay that cost at a
    moment of its choosing, which is exactly what `Session._warm` already does for
    Whisper's tiers.
    """

    #: Set so `Session._pump_health`'s idle-unload check reads something true. There is
    #: no 605 MB to give back here — the models belong to the OS — but the session asks.
    loading = False

    def __init__(self, binary: Path | None = None) -> None:
        self._binary = Path(binary) if binary else None
        self._proc: subprocess.Popen | None = None
        #: One decode at a time over one pipe. `DecodeWorker` is single-threaded today,
        #: and this makes that a guarantee of this class rather than a fact about its
        #: caller.
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def load(self, final=None) -> None:
        """Start the helper. Idempotent, and the signature matches Whisper's tier load."""
        with self._lock:
            self._ensure()

    def unload(self) -> None:
        """Close the helper down. The idle path calls this; there is little to reclaim.

        Closing stdin is the documented way out — the helper returns from its read loop
        and exits — so this asks before it insists.
        """
        with self._lock:
            proc, self._proc = self._proc, None
            if proc is None:
                return
            try:
                if proc.stdin:
                    proc.stdin.close()
                proc.wait(timeout=2.0)
            except (OSError, subprocess.SubprocessError):
                pass
            if proc.poll() is None:
                proc.kill()

    def _ensure(self) -> None:
        if self.loaded:
            return
        binary = self._binary or build()
        try:
            self._proc = subprocess.Popen(
                [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NotAvailable(f"could not start {binary}: {exc}") from exc

    # -- the one method the protocol asks for ------------------------------

    def text(self, audio: np.ndarray, *, final: bool = False,
             hotwords: str = "") -> str:
        """Transcribe mono float32 at 16 kHz.

        `final` is accepted and ignored: Apple's recogniser has one quality, where
        Whisper has a fast tier and a strong one. That is a real difference and not a
        stub — there is no second model to reach for, so a partial and a final of the
        same audio return the same words.

        `hotwords` is accepted and ignored too. Biasing has no equivalent here, so the
        constrained re-decode that `Session.submit_rescue` performs comes back
        unbiased rather than failing.
        """
        block = np.ascontiguousarray(audio, dtype=np.float32)
        if block.size == 0:
            return ""
        with self._lock:
            self._ensure()
            proc = self._proc
            if proc is None or proc.stdin is None or proc.stdout is None:
                raise NotAvailable("helper is not running")
            try:
                proc.stdin.write(struct.pack("<I", block.size))
                proc.stdin.write(block.tobytes())
                proc.stdin.flush()
                line = proc.stdout.readline()
            except (OSError, ValueError) as exc:
                self._proc = None
                raise NotAvailable(f"helper stopped: {exc}") from exc
            if not line:
                # The helper died mid-utterance. Its stderr is the only account of why,
                # and losing it would make this the silent failure the whole file is
                # written against.
                detail = ""
                if proc.stderr is not None:
                    try:
                        detail = proc.stderr.read().decode("utf-8", "replace").strip()
                    except (OSError, ValueError):
                        pass
                self._proc = None
                raise NotAvailable(detail.splitlines()[-1] if detail
                                   else "helper exited without answering")
            return line.decode("utf-8", "replace").strip()
