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
reply interruptible, and it is what lets `speaking` be answered at all.

**`speaking` is the important part of this module, not `say`.** The microphone is gated
on it (`Session._pump_audio`), because without echo cancellation Flow cannot tell its own
voice from the user's — it hears the reply, opens the gate, and transcribes itself into
the next question. A VAD does not help: the speakers really are producing speech. So the
host is asked what the engine is doing, and the answer decides whether the microphone
counts as evidence.

**Built unless refused (`--no-speak`), not only when asked for.** This was off by
default at first, on the argument that a voice starting unbidden in a shared office is a
worse first impression than no voice at all. That is true of dictate mode and wrong
about converse mode, where the user has explicitly asked for a conversation — and it
made the feature unreachable by the route people actually take, since someone who finds
converse mode with ctrl+alt+M mid-session cannot go back and add a launch flag.
Entering converse mode is the opt-in; `Session.muted` is the runtime toggle.
"""

from __future__ import annotations

import base64
import subprocess
import threading
import time

#: Rate is -10..10, 0 being the engine default. Slightly quick: these are short answers
#: to a developer who is waiting, not an audiobook.
DEFAULT_RATE = 1

#: How often to ask the host whether it is still talking. The host is idle between
#: utterances — `SpeakAsync` returns immediately — so this is a pipe round trip and not
#: work. It only has to be fine enough that the microphone reopens promptly once the
#: answer ends.
POLL_SEC = 0.1

#: A ceiling on how long `speaking` may report True, derived from the text.
#:
#: This gates the microphone, so a latched True would leave Flow permanently deaf — a
#: far worse failure than a little leaked echo. The ceiling is therefore enforced by the
#: *reader* in `speaking`, not by the watcher thread: even if the host wedges and the
#: watcher blocks forever on its read, suppression still expires on schedule.
#:
#: Measured on this machine at rate 1: a 15-word sentence took 4.9 s, so about 3 words a
#: second. Half that rate plus 5 s of slack is generous without being unbounded.
WORDS_PER_SEC = 1.5
CEILING_SLACK_SEC = 5.0

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
#:
#: `| Out-Null` is load-bearing now that stdout is a pipe we read: `SpeakAsync` returns a
#: Prompt object, and PowerShell formats a bare return value onto stdout. Unread that was
#: invisible; against the state protocol below it would be noise interleaved with the
#: answers, and the microphone gating depends on reading those cleanly.
_SAY = (
    "$s.SpeakAsyncCancelAll() | Out-Null;"
    "$s.SpeakAsync([Text.Encoding]::UTF8.GetString("
    "[Convert]::FromBase64String('{b64}'))) | Out-Null;"
)

_STOP = "$s.SpeakAsyncCancelAll() | Out-Null;"

#: The whole state protocol: one line, one prefix, so a stray line from the host cannot
#: be mistaken for an answer. `$s.State` is `Speaking` or `Ready` — verified directly
#: against the engine before this was built on top of it.
STATE_PREFIX = "FLOWSTATE="
_STATE = f'[Console]::Out.WriteLine("{STATE_PREFIX}" + $s.State);'

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
        #: Serialises writes to the host's stdin. Two threads reach it now — whoever
        #: calls say()/stop(), and the watcher asking for state — and interleaved
        #: writes would corrupt both commands.
        self._io = threading.Lock()
        self._speaking = False
        self._deadline = 0.0

    @property
    def available(self) -> bool:
        return self._ensure() is not None

    @property
    def speaking(self) -> bool:
        """True while a reply is coming out of the speakers.

        The microphone is gated on this (see `Session._pump_audio`), which is why the
        ceiling is enforced here rather than in the watcher: a wedged host must not be
        able to leave Flow deaf. Past the deadline this reports False regardless of what
        the watcher has or has not seen.
        """
        with self._lock:
            if not self._speaking:
                return False
            if time.monotonic() >= self._deadline:
                self._speaking = False
                return False
        # A dead host is not speaking, whatever the deadline says. Without this, losing
        # the engine mid-reply would hold the microphone shut for the rest of a ceiling
        # sized for the *text*, which for a long answer is half a minute of silence the
        # user cannot explain.
        proc = self._proc
        if proc is not None and proc.poll() is not None:
            with self._lock:
                self._speaking = False
            return False
        return True

    def _watch(self) -> None:
        """Poll the host until it stops speaking, so the mic reopens as soon as possible.

        Best-effort by design. Everything that matters for safety is the deadline in
        `speaking`; this only makes the common case — an answer that ends well before
        its ceiling — end promptly instead of at the ceiling.
        """
        while True:
            time.sleep(POLL_SEC)
            with self._lock:
                if not self._speaking or time.monotonic() >= self._deadline:
                    self._speaking = False
                    return
            proc = self._proc
            if proc is None or proc.stdout is None or not self._write(_STATE):
                break
            line = proc.stdout.readline()
            if not line:
                break
            if STATE_PREFIX in line and "Ready" in line:
                break
        with self._lock:
            self._speaking = False

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
                    # A pipe, not DEVNULL: the state protocol is read from here, and it
                    # is what tells the microphone when the answer has finished playing.
                    stdout=subprocess.PIPE,
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
            with self._io:
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
        # Marked as speaking *before* the write, not after: the engine starts producing
        # sound within milliseconds, and the microphone has to already be gated by then
        # or the first syllable of the reply is captured as if the user had said it.
        ceiling = len(text.split()) / WORDS_PER_SEC + CEILING_SLACK_SEC
        with self._lock:
            already = self._speaking
            self._speaking = True
            self._deadline = time.monotonic() + ceiling
        if not self._write(_SAY.format(b64=b64)):
            with self._lock:
                self._speaking = False
            return False
        if not already:
            threading.Thread(target=self._watch, daemon=True, name="speech").start()
        return True

    def stop(self) -> bool:
        """Cut off the current reply — the user has taken the answer back."""
        with self._lock:
            self._speaking = False
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
