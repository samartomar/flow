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
import os
import shutil
import subprocess
import threading
import time
from typing import NamedTuple

# The only thing this module borrows from the CLI adapter, and it is borrowed rather than
# copied for the reason `resolve` gives: a second resolver is how the two halves of a
# lookup come to disagree. Nothing in `refine` imports back, so this stays a leaf edge.
from .refine import trusted

#: Rate is -10..10, 0 being the engine default. Slightly quick: these are short answers
#: to a developer who is waiting, not an audiobook.
DEFAULT_RATE = 1

#: How long to wait for the engine to list what is installed. Generous: this is one
#: PowerShell start-up, it happens once per session, and returning an empty list would
#: read as "you have no voices" rather than "the query was slow".
LIST_TIMEOUT_SEC = 15.0

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

#: Base64 for the same reason the text is: a voice name is data, and `SelectVoice` on a
#: name that is not installed throws. Wrapped in try/catch so a stale name in a profile
#: — a voice uninstalled since it was chosen — leaves the engine on its default instead
#: of killing the host and taking every spoken reply with it.
_SELECT = (
    "try{{$s.SelectVoice([Text.Encoding]::UTF8.GetString("
    "[Convert]::FromBase64String('{b64}')))}}catch{{}};"
)

#: Marks a line of `_LIST` output. Same discipline as STATE_PREFIX: PowerShell can print
#: things nobody asked for, and a prefix is what stops one of them being read as a voice.
VOICE_PREFIX = "FLOWVOICE="

#: Ask the engine what it has. Runs in its own short-lived process rather than in the
#: speech host: it is wanted before the host exists (to validate `--voice` and to fill
#: the menu), it is asked once, and a query that hangs must not be able to wedge the
#: process that owns spoken replies.
#:
#: `$v.Enabled` is checked because a disabled voice is enumerated and cannot be selected.
_LIST = (
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "foreach($v in $s.GetInstalledVoices()){if($v.Enabled){$i=$v.VoiceInfo;"
    "[Console]::Out.WriteLine('" + VOICE_PREFIX + "'+$i.Name+'|'+$i.Gender+'|'+$i.Culture)"
    "}};$s.Dispose();"
)


#: Which PowerShell hosts the speech, in order of preference.
#:
#: This is not a style choice, it is the difference between two voices and five.
#: `System.Speech` is a .NET API and the two editions ship different implementations of
#: it: Windows PowerShell 5.1 (.NET Framework) enumerates only the legacy SAPI5 token
#: store, PowerShell 7 (.NET) also reads the OneCore store. Measured on this machine —
#: powershell: David Desktop, Zira Desktop. pwsh: those two plus David, Mark and Zira.
#:
#: The OneCore store is where Windows puts everything modern, including the Natural
#: voices added through Narrator's settings, so a host that cannot see it cannot ever be
#: given a good voice. `pwsh` is not on every machine, hence the fallback — and 5.1 is,
#: which is why the fallback is guaranteed to work rather than merely likely.
HOSTS = ("pwsh", "powershell")

#: Resolved once, and used by *both* the enumeration and the speech host. They must be
#: the same executable: a menu built from voices `pwsh` can see, driving a host running
#: under 5.1, offers names that `SelectVoice` will refuse — and it refuses quietly, so
#: the reply would arrive in the default voice with nothing on screen to explain it.
_HOST: str | None = None


def _stock_host() -> str:
    """`HOSTS[-1]` by its fixed location rather than by name.

    Windows PowerShell 5.1 is part of the OS and lives at exactly this path on every
    install, which is what makes it the guaranteed fallback in the first place — so it can
    be *addressed*, and a thing that is addressed cannot be substituted.

    Not checked for existence deliberately. If it were somehow absent, `Popen` raises the
    `OSError` `_ensure` already handles and speech is simply off; a name that falls back to
    a search would instead start whatever answers to it. Failing closed is the point.
    """
    if os.name != "nt":
        return HOSTS[-1]
    return os.path.join(os.environ.get("SystemRoot") or "C:\\Windows",
                        "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def host() -> str:
    """The PowerShell that both speaks and enumerates, as a path rather than a word.

    It used to store the *name* it had looked up, which meant the lookup that decided
    PowerShell was available and the search that actually starts it were two different
    searches under two different rule sets, run seconds apart — and until `main()` closes
    it, both consult the current directory first. Keeping what `which` returned collapses
    them into one answer, and `refine.trusted` is what makes that answer a safe one.

    The fallback is `_stock_host()` and not `HOSTS[-1]`, which is a correction the probe
    made rather than a preference: a planted workspace holds *both* names, so both lookups
    are refused, and a bare name handed to `Popen` is resolved by `CreateProcess` — from
    the current directory first. The one branch that existed to be safe was the only one
    left reaching the planted file.
    """
    global _HOST
    if _HOST is None:
        _HOST = next(
            (found for h in HOSTS if (found := trusted(shutil.which(h)))), _stock_host()
        )
    return _HOST


class Voice(NamedTuple):
    """One installed voice, as the engine describes it."""

    name: str
    gender: str  # Male | Female | Neutral | NotSet
    culture: str  # en-US, en-GB, ...

    def describe(self) -> str:
        return f"{self.name} ({self.gender.lower()}, {self.culture})"


#: Filled once per process by `installed_voices`. Voices do not appear mid-session, and
#: the query costs a PowerShell start-up.
_CACHE: list[Voice] | None = None


def installed_voices(refresh: bool = False) -> list[Voice]:
    """Every voice this machine can speak with. Empty if the engine is unavailable.

    Worth knowing where these come from, because it is the difference between "you are
    stuck with what you hear" and "install better ones and they appear here". Measured
    on this machine: the SAPI5 token store holds only the two *Desktop* voices, yet
    `System.Speech` enumerates five — so it is reading the OneCore store as well, and
    that is where Windows puts the modern voices, including the Natural ones added
    through Narrator's settings. Nothing in Flow has to change for those to show up.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    try:
        out = subprocess.run(
            [host(), "-NoProfile", "-NonInteractive", "-Command", _LIST],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=LIST_TIMEOUT_SEC,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        out = ""
    found: list[Voice] = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith(VOICE_PREFIX):
            continue
        parts = line[len(VOICE_PREFIX):].split("|")
        if len(parts) == 3 and parts[0]:
            found.append(Voice(*parts))
    _CACHE = found
    return found


def _legacy(v: Voice) -> int:
    """Sort key that puts the older engine last when nothing else separates two voices.

    A registry fact rather than an opinion about how they sound, which is not something
    this file is in a position to have: the `... Desktop` voices are registered in the
    SAPI5 token store, and everything else — including every modern voice Windows
    installs — is registered under Speech_OneCore. Measured on the development machine,
    where the SAPI5 store held exactly the two Desktop voices and OneCore held three
    more. It only decides a request that names no voice, like `--voice female`; asking
    for one by name always gets that one.
    """
    return 1 if v.name.strip().lower().endswith("desktop") else 0


def _select(name: str) -> str:
    b64 = base64.b64encode(name.encode("utf-8")).decode("ascii")
    return _SELECT.format(b64=b64)


def pick(want: str | None, voices: list[Voice] | None = None) -> str | None:
    """Resolve what someone asked for to a voice that is actually installed.

    `None` back means "no opinion — let the engine use its default", which is also what
    an unmatched request produces: a name that no longer exists must not silence the
    replies, and the caller says so rather than failing.

    Deliberately forgiving about how it is asked for, because the alternative is typing
    "Microsoft Zira Desktop" exactly. In order: the full name, then `male`/`female`,
    then any voice whose name contains what was typed. English is preferred when a
    gender matches several, since Flow only produces English to read.
    """
    voices = installed_voices() if voices is None else voices
    if not want or not voices:
        return None
    wanted = want.strip().lower()
    for v in voices:
        if v.name.lower() == wanted:
            return v.name
    if wanted in ("male", "female"):
        matching = [v for v in voices if v.gender.lower() == wanted]
        english = [v for v in matching if v.culture.lower().startswith("en")]
        for pool in (english, matching):
            if pool:
                return min(pool, key=_legacy).name
        return None
    partial = [v for v in voices if wanted in v.name.lower()]
    return min(partial, key=_legacy).name if partial else None

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

    def __init__(
        self, rate: int = DEFAULT_RATE, enabled: bool = True, voice: str | None = None
    ) -> None:
        self._rate = rate
        self._enabled = enabled
        #: The exact installed name, or None for whatever the engine defaults to. Not
        #: resolved here: `pick()` costs a PowerShell start-up and this constructor runs
        #: on the launch path whether or not anyone ever speaks.
        self._voice = voice
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
    def voice(self) -> str | None:
        """The chosen voice, or None while the engine's own default is in use."""
        return self._voice

    def use(self, name: str | None) -> bool:
        """Switch voice. Takes effect on the next reply, and on this host if it is up.

        Stops first, because selecting a voice out from under an utterance already being
        spoken is the one thing the engine can be asked here that it may refuse.
        """
        self._voice = name
        self.stop()
        if self._proc is None:
            return True  # nothing running; the bootstrap will carry it
        return self._write(_select(name)) if name else True

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
                    [host(), "-NoProfile", "-NonInteractive", "-Command", "-"],
                    stdin=subprocess.PIPE,
                    # A pipe, not DEVNULL: the state protocol is read from here, and it
                    # is what tells the microphone when the answer has finished playing.
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                boot = _BOOTSTRAP.format(rate=self._rate)
                if self._voice:
                    boot += _select(self._voice)
                proc.stdin.write(boot + "\n")
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
        # `_speaking` is cleared here and not left to the watcher, because `speaking`
        # reads a dead host through `self._proc` and there is no `self._proc` any more.
        # Without this a close mid-reply reports "still speaking" until the ceiling —
        # and the microphone is gated on that, so the last thing a closing session
        # would do is go deaf for the length of a long answer.
        with self._lock:
            self._speaking = False
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=2.0)
        except Exception:
            proc.kill()
