"""The Microsoft natural voices, reached the only way they can be (P9).

**This is the one part of Flow that sends anything off the machine, and it is off by
default.** Everything else — dictation, corrections, the lexicon, calibration, refinement
through an already-authenticated CLI — runs locally, and R9's "no API key" holds here too:
this engine needs no key and no account. But it is a network engine. Choosing one of these
voices means the *text of each spoken reply* is sent to Microsoft's speech service to be
synthesised. Nothing else goes with it: not audio, not the draft, not the workspace path.
Install the extra and pick the voice and you have opted into that; do neither and no
socket is ever opened. `docs/decisions.md` records the narrowing and its date.

**Why it exists at all.** `speak.installed_voices` documents the dead end: Windows 11
installs Ava, Guy and Sonia as MSIX packages for Narrator, ships a complete and valid SAPI
token for each, and then registers that token into a hive which does not exist, behind an
engine CLSID present in no COM store. They are on the disk, they are excellent, and no
public API on the machine can reach them. This service serves the same voice family. It is
the only way to hear them, which is why the guarantee was narrowed rather than the feature
dropped — and `flow/piper.py` remains the local answer for anyone who would rather not.

**Streaming, because the alternative is a second of silence.** The service returns MP3, not
PCM — there is no output-format parameter to ask otherwise — so a decode step is
unavoidable. `av` does it, and costs nothing to depend on: faster-whisper already pulls it
in, so this adds no wheel that was not being downloaded anyway. Buffering the whole reply
before decoding measured 1.18 s to first sound. Feeding the demuxer from a queue as the
bytes arrive measured 1.94 s, which was *worse*, because PyAV probes the stream before
returning and the probe waited on data. Capping the probe fixed it: `probesize` 2048 and
`analyzeduration` 0 give **0.58 s to first sound**, only 0.13 s behind the first byte off
the wire. That is network latency and nothing else, which is as good as this can be.

Synthesis runs about six times faster than playback, so once sound starts it does not
stall.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # `speak` imports this module, so the Voice import cannot be circular.
    from .speak import Voice

HOME = Path.home() / ".flow"

#: The voice list, kept so the menu works without a network round trip — and so it works
#: at all on a machine that is offline right now but was not when it last ran. Refreshed
#: only when asked, because 322 voices do not change between sessions.
CACHE_PATH = HOME / "edge-voices.json"

#: What the service returns, and what `Synth` therefore resamples to. Fixed by the
#: `audio-24khz-48kbitrate-mono-mp3` format `edge_tts` requests and does not expose.
SAMPLE_RATE = 24000

#: Only English is offered. The service lists 322 voices across every locale it supports,
#: and putting all of them in a right-click menu would make the menu useless. Flow
#: produces English to read, which is the same reason `speak.pick` prefers it.
LOCALE_PREFIX = "en-"

#: English locales in the order they are offered, best first; everything else follows in
#: name order. This is ordering and not filtering — en-IN, en-NG and the rest are all
#: still in the menu, just below.
#:
#: It is load-bearing rather than cosmetic. `speak.pick` breaks a tie with `min`, which is
#: stable, so *list order decides what `--voice female` returns* once several voices match
#: on gender and engine. Left in the service's own order that was `en-AU-NatashaNeural`:
#: alphabetically first, Australian, and chosen for a user who asked only for "female".
#: The machine's own locale goes first so the answer sounds local, then the two largest.
PREFERRED_LOCALES = ("en-US", "en-GB")


#: Categories the service tags each voice with. `Cartoon` is a novelty voice — `en-US-Ana`
#: is tagged `Cartoon`/`Cute` — and must not be what someone who typed `--voice female`
#: gets, which is exactly what alphabetical order gave before this existed. `Conversation`
#: is ranked up for the obvious reason: converse mode is a conversation.
NOVELTY = "Cartoon"
CONVERSATIONAL = "Conversation"


def _system_locale() -> str:
    """This machine's locale as `en-GB`, or "" if it cannot be read.

    `ctypes` first, and on Windows that is the only branch that works. `locale.getlocale`
    returns `('English_United States', '1252')` there — a display name, not a tag — so the
    obvious implementation produced `Engli` after normalising and matched no locale at
    all. `GetUserDefaultLocaleName` returns `en-US`, which is what is wanted.

    Best-effort and never raises: this only decides an ordering, so a wrong answer costs a
    voice from the wrong side of an ocean rather than a failure.
    """
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
            return buf.value
    except (AttributeError, OSError, ValueError):
        pass
    try:
        import locale as _locale

        tag = _locale.getdefaultlocale()[0] or ""
    except (ValueError, AttributeError):
        return ""
    return tag.replace("_", "-")

#: How long to wait on the service when listing. Short: a slow network must not hold up
#: the menu, and there is a cache to fall back to.
LIST_TIMEOUT_SEC = 10.0

#: Bytes the demuxer may read before it decides what it is looking at. The default probe
#: is large enough to out-wait the network and cost a second of silence; see the module
#: docstring for the three measurements.
PROBE_SIZE = "2048"
BUFFER_SIZE = 4096

#: Audio held before the first sample is written, and frames per write after that. Both
#: mean here exactly what `piper.PREBUFFER_SEC` and `piper.CHUNK_FRAMES` mean there: a
#: cushion so a stalled producer does not break the reply up, and slices small enough that
#: `stop()` is heard promptly rather than at the end of the sentence.
PREBUFFER_SEC = 0.5
CHUNK_FRAMES = 4096
LATENCY = "high"


def available() -> bool:
    """Whether the `edge` extra is installed. False is the ordinary case."""
    try:
        import av  # noqa: F401
        import edge_tts  # noqa: F401
    except Exception:
        return False
    return True


def rate_percent(rate: int) -> str:
    """`speak`'s SAPI rate as the percentage string the service takes.

    10% per step, so `speak.DEFAULT_RATE` of 1 is a touch quick — the same intent the SAPI
    path has. Clamped to what the service accepts.
    """
    return "%+d%%" % max(-50, min(100, rate * 10))


def _from_service(entry: dict) -> Voice | None:
    from .speak import Voice

    short = str(entry.get("ShortName") or "")
    locale = str(entry.get("Locale") or "")
    if not short or not locale:
        return None
    gender = str(entry.get("Gender") or "NotSet")
    # Named by ShortName for the reason `piper._read` names by file stem: `Voice.name` is
    # the only handle the menu, the profile, `--voice` and `Speaker`'s routing carry, so
    # it has to be unique. `ShortName` already is, service-wide. It also keeps the word
    # people search for — `--voice ava` still matches by substring.
    return Voice(
        name=f"Natural {short}",
        gender=gender if gender in ("Male", "Female") else "NotSet",
        culture=locale,
        engine="edge",
        path=short,
        sample_rate=SAMPLE_RATE,
    )


def _fetch() -> list[dict]:
    """Ask the service what it has. Network; returns [] rather than raising."""
    import asyncio

    import edge_tts

    async def go():
        return await asyncio.wait_for(edge_tts.list_voices(), LIST_TIMEOUT_SEC)

    try:
        return list(asyncio.run(go()))
    except Exception:
        return []


def _cached() -> list[dict]:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


_CACHE: list[Voice] | None = None


def voices(refresh: bool = False) -> list[Voice]:
    """The English natural voices, as `speak.Voice` rows the menu can render.

    The cache is preferred over the service, which is deliberate and is what keeps this
    off the startup path: the list is fetched once, written to `~/.flow/edge-voices.json`,
    and read from there forever after unless `refresh=True`. So a session that has run
    before opens its menu with no socket at all, and a machine that is offline today still
    shows the voices it found yesterday.

    Empty — not an error — when the extra is absent, or on the very first run with no
    network. `speak.installed_voices` concatenates this with the other engines.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    found: list[Voice] = []
    if available():
        raw = [] if refresh else _cached()
        if not raw:
            raw = _fetch()
            if raw:
                try:
                    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    CACHE_PATH.write_text(json.dumps(raw), encoding="utf-8")
                except OSError:
                    pass  # A cache that cannot be written is slow, not broken.
        order = [loc for loc in (_system_locale(),) if loc.startswith(LOCALE_PREFIX)]
        order += [loc for loc in PREFERRED_LOCALES if loc not in order]

        ranked: list[tuple[tuple, Voice]] = []
        for entry in raw:
            if not str(entry.get("Locale") or "").startswith(LOCALE_PREFIX):
                continue
            if (v := _from_service(entry)) is None:
                continue
            tag = entry.get("VoiceTag") or {}
            cats = tag.get("ContentCategories") or []
            ranked.append(((
                # This tuple is what `--voice female` resolves through, because
                # `speak.pick` breaks ties with a stable `min` and so takes whatever is
                # first here. Every term below was put in by watching it pick badly.
                order.index(v.culture) if v.culture in order else len(order),
                NOVELTY in cats,           # a cartoon voice is never the right default
                CONVERSATIONAL not in cats,  # converse mode is a conversation
                # Plain before Multilingual: both match `--voice ava`, and
                # `en-US-AvaNeural` is the one somebody means by "Ava". Name order alone
                # returns the Multilingual variant, which is a different voice.
                "Multilingual" in v.path,
                v.name,
            ), v))
        ranked.sort(key=lambda pair: pair[0])
        found = [v for _, v in ranked]
    _CACHE = found
    return found


def pcm(frame) -> bytes:
    """The real samples of a decoded frame, without the padding PyAV leaves after them.

    A function rather than an expression inline in `_play` because it is the fix for a bug
    that reached a user's ears and there should be somewhere to point a test at.

    An audio plane is allocated to an alignment boundary, so its buffer is longer than
    what was decoded into it: measured at 1216 bytes for 576 samples, on every one of 133
    frames of one reply. `bytes(plane)` returns all of it, and those extra 64 bytes are
    whatever the allocator last left there. Written to the device they are a burst of
    noise spliced into the speech every 1152 bytes — the words come through, the audio
    crackles the whole way, and that is how it was reported: "sounds good but breaking".
    """
    return bytes(frame.planes[0])[: frame.samples * 2]


class _Feeder:
    """A blocking file object over a queue, so the demuxer can pull as bytes arrive.

    `av.open` wants something with `read`; `edge_tts` produces chunks on an event loop in
    another thread. This is the join between them. `read` returns short only at the end of
    the stream, which is how the demuxer learns the file is over.
    """

    def __init__(self, q: queue.Queue) -> None:
        self._q = q
        self._buf = bytearray()
        self._eof = False

    def read(self, n: int) -> bytes:
        while len(self._buf) < n and not self._eof:
            item = self._q.get()
            if item is None:
                self._eof = True
                break
            self._buf += item
        out, self._buf = bytes(self._buf[:n]), self._buf[n:]
        return out


class Synth:
    """Speech through the service, with the same five verbs `speak.Speaker` exposes.

    Constructed per voice by `speak.Speaker` when the chosen voice is one of these, and
    closed when the choice changes. Holds nothing expensive — there is no model to load,
    only a socket per utterance.
    """

    def __init__(self, voice: Voice, rate: int = 0) -> None:
        self._voice = voice
        self._rate = rate
        self._lock = threading.Lock()
        self._stream = None
        #: Bumped by every `say` and every `stop`. Both worker threads compare it against
        #: the value they started with and return when they differ, which is what stops a
        #: cancelled reply from writing into the stream the next one is using.
        self._epoch = 0
        self._speaking = False
        self._deadline = 0.0

    @property
    def voice(self) -> Voice:
        return self._voice

    @property
    def ready(self) -> bool:
        """Nothing to load, so this is just "is the extra installed"."""
        return available()

    @property
    def speaking(self) -> bool:
        """True while samples are still going to the speakers.

        The microphone is gated on this (`Session._pump_audio`), so the ceiling from
        `speak.py` is enforced here as it is in every engine — and it matters more here
        than anywhere else, because this one can be stalled by somebody else's network. A
        latched True would leave Flow permanently deaf, so the deadline is read by the
        reader and never depends on a worker that may itself be blocked on a socket.
        """
        with self._lock:
            if not self._speaking:
                return False
            if time.monotonic() >= self._deadline:
                self._speaking = False
                return False
            return True

    def _pull(self, text: str, q: queue.Queue, epoch: int) -> None:
        """Fetch MP3 from the service into `q`. Always terminates the queue with None."""
        import asyncio

        import edge_tts

        async def go():
            c = edge_tts.Communicate(text, self._voice.path, rate=rate_percent(self._rate))
            async for chunk in c.stream():
                with self._lock:
                    if epoch != self._epoch:
                        return
                if chunk.get("type") == "audio" and chunk.get("data"):
                    q.put(chunk["data"])

        try:
            asyncio.run(go())
        except Exception:
            # No network, a refused connection, a service error. The reply is silent and
            # the session carries on — the same contract every other engine here has.
            pass
        finally:
            q.put(None)

    def _play(self, q: queue.Queue, epoch: int) -> None:
        """Decode what arrives and write it to the device until one of them ends."""
        import av
        import sounddevice as sd

        stream = None
        try:
            container = av.open(
                _Feeder(q), format="mp3", buffer_size=BUFFER_SIZE,
                options={"probesize": PROBE_SIZE, "analyzeduration": "0"},
            )
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            need = int(SAMPLE_RATE * 2 * PREBUFFER_SEC)
            pending = bytearray()
            for frame in container.decode(container.streams.audio[0]):
                for out in resampler.resample(frame):
                    with self._lock:
                        if epoch != self._epoch:
                            return
                    pending += pcm(out)
                    if stream is None and len(pending) < need:
                        # A cushion before the first sample, for the reason
                        # `piper.PREBUFFER_SEC` explains at length: the producer here is a
                        # network rather than a model, but the failure is the same one —
                        # the device drains during a gap and the reply breaks up.
                        continue
                    if stream is None:
                        stream = sd.RawOutputStream(
                            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            latency=LATENCY,
                        )
                        stream.start()
                        with self._lock:
                            if epoch != self._epoch:
                                stream.close()
                                return
                            self._stream = stream
                    for i in range(0, len(pending), CHUNK_FRAMES * 2):
                        with self._lock:
                            if epoch != self._epoch:
                                return
                        stream.write(bytes(pending[i:i + CHUNK_FRAMES * 2]))
                    pending = bytearray()
            if pending and stream is not None:
                stream.write(bytes(pending))
            elif pending:
                # Shorter than the cushion: the whole reply fits in one go.
                stream = sd.RawOutputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16", latency=LATENCY,
                )
                stream.start()
                with self._lock:
                    if epoch != self._epoch:
                        stream.close()
                        return
                    self._stream = stream
                stream.write(bytes(pending))
        except Exception:
            pass
        finally:
            with self._lock:
                current = epoch == self._epoch
                if current:
                    self._speaking = False
                    self._stream = None
            if stream is not None and current:
                # Drain rather than abort: this is the end of the answer, and clipping
                # the last word would sound like a fault.
                for step in (stream.stop, stream.close):
                    try:
                        step()
                    except Exception:
                        pass

    def say(self, text: str) -> bool:
        """Speak `text`, cutting off whatever is already speaking. False if silent."""
        if not text.strip() or not available():
            return False
        from .speak import CEILING_SLACK_SEC, WORDS_PER_SEC

        self.stop()
        # The ceiling covers the round trip as well as the speech, because this engine
        # waits on a network before its first sample.
        ceiling = (len(text.split()) / WORDS_PER_SEC + CEILING_SLACK_SEC
                   + LIST_TIMEOUT_SEC)
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._epoch += 1
            epoch = self._epoch
            # Set before either worker starts, for the reason `speak.Speaker.say` gives:
            # the microphone has to be gated before the first sample, or the reply's
            # opening syllable is transcribed as the user's.
            self._speaking = True
            self._deadline = time.monotonic() + ceiling
        threading.Thread(target=self._pull, args=(text, q, epoch),
                         daemon=True, name="edge-pull").start()
        threading.Thread(target=self._play, args=(q, epoch),
                         daemon=True, name="edge-play").start()
        return True

    def stop(self) -> bool:
        """Cut off the current reply — the user has taken the answer back.

        Bumping the epoch ends both workers at their next check. `abort` rather than
        `stop` on the device, which is the difference between silence now and silence
        after the rest of the sentence has played.
        """
        with self._lock:
            self._epoch += 1
            self._speaking = False
            stream, self._stream = self._stream, None
        if stream is not None:
            for step in (stream.abort, stream.close):
                try:
                    step()
                except Exception:
                    pass
        return True

    def close(self) -> None:
        self.stop()
