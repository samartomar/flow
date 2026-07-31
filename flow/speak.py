"""Spoken replies (P9, optional half) through the speech engine Windows already has.

R16 caps this project at three declared dependencies, so a TTS package is not an
option. `System.Speech.Synthesis` is part of .NET on every Windows install and is
reachable through PowerShell, which is how `scripts/` already synthesises the SAPI
control voice for the benchmarks. Nothing is installed and nothing leaves the machine
(R9).

**One long-lived host process, not one per reply.** The obvious implementation shells
out per utterance, and it is wrong twice: PowerShell costs ~700 ms of startup before
the first phoneme, and a subprocess that has already been launched cannot be told to
stop talking. Keeping one process alive and writing commands to its stdin makes the
reply interruptible, which matters because the user speaking again is exactly the
signal that they are done listening.

Off by default. Converse mode is fully usable in silence, and a voice that starts
talking unbidden in a shared office is a worse first impression than no voice at all.
"""

from __future__ import annotations

import base64
import subprocess
import threading

#: Rate is -10..10, 0 being the engine default. Slightly quick: these are short answers
#: to a developer who is waiting, not an audiobook.
DEFAULT_RATE = 1

#: Bootstrap run once in the host. `SpeakAsync` rather than `Speak` so the host stays
#: responsive to the next command — that is what makes an interruption possible.
_BOOTSTRAP = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.Rate = {rate};"
)

#: Text arrives base64-encoded. An answer can contain quotes, dollar signs, backticks
#: and newlines — every one of which is PowerShell syntax — and no amount of escaping
#: is as safe as not putting the text in the command line at all.
_SAY = (
    "$s.SpeakAsyncCancelAll();"
    "$s.SpeakAsync([Text.Encoding]::UTF8.GetString("
    "[Convert]::FromBase64String('{b64}')));"
)

_STOP = "$s.SpeakAsyncCancelAll();"

STARTUP_SEC = 10.0


class Speaker:
    """A speech host, started lazily and safe to construct anywhere.

    Every method is a no-op when the engine is unavailable, so callers never have to
    ask whether speech works: a machine without it degrades converse mode to a silent
    reply, which is what converse mode does by default anyway.
    """

    def __init__(self, rate: int = DEFAULT_RATE, enabled: bool = True) -> None:
        self._rate = rate
        self._enabled = enabled
        self._proc: subprocess.Popen | None = None
        self._tried = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._ensure() is not None

    def _ensure(self) -> subprocess.Popen | None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self._proc
            if self._tried or not self._enabled:
                return None
            self._tried = True
            try:
                proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", "-"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                proc.stdin.write(_BOOTSTRAP.format(rate=self._rate) + "\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                return None
            self._proc = proc
            return proc

    def _write(self, command: str) -> bool:
        proc = self._ensure()
        if proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(command + "\n")
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            # The host died — a later call will not resurrect it, because a speech
            # engine that crashes once is not worth retrying on every reply.
            with self._lock:
                self._proc = None
            return False

    def say(self, text: str) -> bool:
        """Speak `text`, cutting off whatever is already speaking. False if silent."""
        if not text.strip():
            return False
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return self._write(_SAY.format(b64=b64))

    def stop(self) -> bool:
        """Cut off the current reply — the user has started speaking again."""
        return self._write(_STOP)

    def close(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=2.0)
        except Exception:
            proc.kill()
