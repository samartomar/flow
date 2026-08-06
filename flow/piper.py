"""A second speech engine, for the voice SAPI cannot give you (P9).

`speak.py` explains why Windows' own engine is the floor and not a choice: both token
stores hold the 2013 `MSTTS_V110` generation, and the natural voices Windows 11 installs
through Narrator's settings are unreachable by any public API — `speak.installed_voices`
carries the measurement. Installing more Windows voices cannot improve the reply.
Shipping a different engine is the only thing that can, and this is it.

**Why this and not the network engine.** `flow/edge.py` serves the exact Ava/Guy/Sonia
voices sitting unusable in `WindowsApps`, and it ships too — but it ships *beside* this
one, not instead of it, and this is the one to reach for first. It synthesises locally, so
nothing leaves the machine and no reply depends on a connection. Both are optional extras,
so R16 holds either way by the reading `pyproject.toml` already applies to `[cuda]`: a
default install still fetches three packages. This is also the engine that works on macOS,
where there is no SAPI half at all, and the one that works on a train.

**In-process, not a subprocess, and that is a measurement rather than a preference.** This
module was first built around the `piper` CLI — one process per utterance, killed on
`stop()`, which is tidy because Flow owns playback and killing the child really does stop
the sound. Then it was timed. On this machine the CLI takes **3.30 s to produce its first
sample**, and that figure barely moves between a 61 MB model and a 109 MB one, so it is
not model loading — it is Python start-up and the `onnxruntime` import, paid again on
every single reply. Three seconds of silence before each answer is not a conversation.

The in-process API pays those costs once. Measured on the same sentence and the same
model: `import piper` 0.33 s, `PiperVoice.load` 3.16 s, and then **0.13–0.22 s to the
first chunk** with 5.6 s of audio synthesised in 0.95 s. So the load is hoisted into a
background thread the moment a Piper voice is chosen, and by the time anyone speaks it has
usually finished.

`synthesize()` returning a generator is what makes interruption survive the change.
Stopping is no longer "kill the child" but "stop consuming the generator and abort the
stream", which is cheaper, needs no framing protocol, and cannot leave a process behind.

**Absent by default, and that is a supported state.** Most machines have neither the
package nor a model, so every entry point here returns empty or False rather than raising,
and `speak.Speaker` falls back to SAPI. Flow gains a better voice when one is installed
and behaves exactly as before when one is not.
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

#: Where Flow keeps everything it did not install itself. Same directory as the profile
#: and the lexicon, because a voice model is user data: chosen by the user, kept across
#: upgrades, and deleted by deleting a folder.
HOME = Path.home() / ".flow"
VOICES_DIR = HOME / "voices"

#: A model is the `.onnx` next to its `.onnx.json`. Both halves are required — the sidecar
#: carries the sample rate, and a guessed sample rate produces audio at the wrong pitch
#: rather than audio that fails.
MODEL_SUFFIX = ".onnx"

#: How long `say` will wait for a model that is still loading before giving up on the
#: utterance. Comfortably over the 3.16 s measured for the largest English model, because
#: the alternative to waiting is a reply that is silently dropped.
LOAD_WAIT_SEC = 20.0

#: Frames written to the device at a time when a synthesised chunk is larger than this.
#: Piper returns a chunk per sentence, which for a long answer is seconds of audio, and
#: `RawOutputStream.write` blocks until the device has taken all of it — so writing a
#: whole chunk would make `stop()` wait for the end of the sentence. Splitting bounds how
#: long an interruption can take to be heard.
#:
#: 4096 and not the 1024 this started at, which is a trade against the *other* failure.
#: Every write is a GIL round trip, and at 1024 frames that is one every 46 ms on a thread
#: competing with the UI, the audio pump and a decode — enough contention and the writes
#: stop arriving in time. `write` blocks inside PortAudio with the GIL released, so fewer
#: and larger writes leave the interpreter for longer. The cost is that `stop()` is heard
#: after up to ~190 ms instead of ~50 ms, which is well inside what reads as immediate.
CHUNK_FRAMES = 4096

#: How much audio to hold before the first sample is written, and the reason synthesis
#: and playback are separate threads at all.
#:
#: Piper yields one chunk per *sentence*, and generating the next one takes real CPU. Done
#: in a single thread the device is fed nothing at all for the length of each synthesis,
#: and the only thing standing between that and an audible gap is the device's own buffer
#: — measured at 0.183 s here. On an idle machine synthesis outruns playback about six to
#: one and it holds; with a `faster-whisper` decode running on the same cores it does not,
#: and the reply breaks up at every sentence boundary. Reported from use, which is how
#: this was found: "sounds good but breaking".
#:
#: So a producer thread synthesises into a queue and a consumer thread writes, and this is
#: the cushion the consumer builds before it starts. Half a second costs half a second of
#: added latency on the first reply and absorbs a sentence that takes that much longer
#: than expected to generate.
PREBUFFER_SEC = 0.5

#: Requested from PortAudio for the same reason. It made no measurable difference on an
#: idle machine — the device reported 0.183 s either way — but asking for headroom is free
#: and the failure it guards against only appears under load.
LATENCY = "high"


def available() -> bool:
    """Whether the Piper package is importable at all. False is the ordinary case."""
    try:
        import piper  # noqa: F401
    except Exception:
        return False
    return True


def length_scale(rate: int) -> float:
    """`speak`'s SAPI rate on Piper's inverted scale.

    Piper expresses speed as a length multiplier, so lower is faster and 1.0 is the
    model's own pace, while `speak.DEFAULT_RATE` is SAPI's -10..10 where higher is faster.
    5% per step, clamped, so one `rate` setting drives both engines and the extremes stay
    intelligible instead of unusable.
    """
    return max(0.4, min(2.0, 1.0 - 0.05 * rate))


def _gender(dataset: str, sidecar: dict) -> str:
    """Male/Female when the model says so, `NotSet` when it does not — never a guess.

    Piper sidecars carry no gender field. Verified against the two installed here:
    `en_GB-cori-high.onnx.json` holds `dataset`, `audio`, `espeak`, `language`,
    `inference`, phoneme tables, `num_speakers` and `speaker_id_map`, and nothing that
    describes the speaker. So for most voices this genuinely is not known, and only an
    explicit token in the name is trusted (`hfc_female`, `northern_english_male`).

    Inferring from the rest — treating `cori` as female, `alan` as male — would be reading
    a person's gender off their first name, which is exactly as reliable here as anywhere
    else, and it would be doing it silently inside a menu.

    The cost is bounded and worth naming: `--voice female` cannot select such a voice, so
    it stays on the Windows voices. Asking by name always works, which is how `pick`
    already treats every voice it cannot classify.
    """
    stated = str(sidecar.get("gender") or "").strip().lower()
    if stated in ("male", "female"):
        return stated.capitalize()
    words = dataset.lower().replace("-", "_").split("_")
    if "female" in words:
        return "Female"
    if "male" in words:
        return "Male"
    return "NotSet"


def _read(model: Path) -> Voice | None:
    """One model file as a `Voice`, or None if it is not a usable pair."""
    from .speak import Voice

    sidecar = model.with_suffix(model.suffix + ".json")
    if not sidecar.is_file():
        return None
    try:
        # Explicitly UTF-8, and that is load-bearing rather than habit: these sidecars
        # carry IPA phoneme tables, and reading one under the Windows default (cp1252)
        # raises `UnicodeDecodeError` partway through the file.
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    audio = meta.get("audio") if isinstance(meta.get("audio"), dict) else {}
    rate = audio.get("sample_rate")
    if not isinstance(rate, int) or rate <= 0:
        return None
    lang = meta.get("language") if isinstance(meta.get("language"), dict) else {}
    culture = str(lang.get("code") or "").replace("_", "-") or "und"
    # The file stem, not the `dataset` field, and that is a correction rather than a
    # preference. Everything downstream keys on `Voice.name` — the menu, the profile,
    # `--voice`, and `Speaker._backend`'s routing — so a name has to be unique. `dataset`
    # is not: `en_GB-cori-high` and `en_GB-cori-medium` both declare `"dataset": "cori"`,
    # and so would `en_US-cori-*`. Two rows called "Piper cori" would make the second
    # unselectable. A filename is unique within a directory by construction, and it is
    # also what the user typed to download the voice, so it is what they will recognise.
    stem = model.name[: -len(MODEL_SUFFIX)]
    return Voice(
        name=f"Piper {stem}",
        gender=_gender(str(meta.get("dataset") or stem), meta),
        culture=culture,
        engine="piper",
        path=str(model),
        sample_rate=rate,
    )


_CACHE: list[Voice] | None = None


def voices(refresh: bool = False) -> list[Voice]:
    """Every Piper model installed, as `speak.Voice` rows the menu can render.

    Empty — not an error — when the package is absent, when the directory does not exist,
    or when it holds no complete model pair. `speak.installed_voices` concatenates this
    with what Windows offers, so an empty list simply means the menu looks as it always
    did.

    The package is checked before the directory is read, because models with no Piper to
    run them are not voices: listing them would put rows in the menu that select a voice
    which then cannot speak, the one failure `speak.py` is careful to avoid.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    found: list[Voice] = []
    if available():
        try:
            entries = sorted(VOICES_DIR.glob(f"*{MODEL_SUFFIX}"))
        except OSError:
            entries = []
        for model in entries:
            if (v := _read(model)) is not None:
                found.append(v)
    _CACHE = found
    return found


class Synth:
    """Speech through Piper, with the same five verbs `speak.Speaker` exposes.

    Constructed per voice by `speak.Speaker` when the chosen voice is a Piper one, and
    closed when the choice changes. Holds the loaded model for its lifetime, which is the
    whole point — see the module docstring for what loading it per utterance cost.
    """

    def __init__(self, voice: Voice, rate: int = 0) -> None:
        self._voice = voice
        self._rate = rate
        self._lock = threading.Lock()
        self._model = None
        self._load_failed = False
        #: Set when the load thread finishes, either way. `say` waits on this rather than
        #: polling, and a failed load sets it too so a waiter is released instead of
        #: sitting out the full timeout for a model that is never coming.
        self._loaded = threading.Event()
        self._stream = None
        #: Bumped by every `say` and every `stop`. The feeder compares it against the
        #: value it started with and returns when they differ, which is what stops a
        #: cancelled utterance from writing into the stream the next one is using.
        self._epoch = 0
        self._speaking = False
        self._deadline = 0.0
        # Started here rather than on first `say`, because 3.16 s was measured for the
        # load and a voice is normally chosen from a menu some seconds before anyone
        # speaks. By the time the first reply arrives this has usually finished.
        threading.Thread(target=self._load, daemon=True, name="piper-load").start()

    @property
    def voice(self) -> Voice:
        return self._voice

    def _load(self) -> None:
        try:
            from piper import PiperVoice

            model = PiperVoice.load(self._voice.path)
        except Exception:
            # A corrupt model, a sidecar that does not match it, a package that imports
            # but cannot run. All of them mean the same thing to the caller: this voice
            # does not speak, so fall silent rather than take the session down.
            with self._lock:
                self._load_failed = True
            self._loaded.set()
            return
        with self._lock:
            self._model = model
        self._loaded.set()

    @property
    def ready(self) -> bool:
        """True once the model is loaded and usable. False while loading, and if it failed."""
        return self._loaded.is_set() and not self._load_failed

    @property
    def speaking(self) -> bool:
        """True while samples are still going to the speakers.

        The microphone is gated on this (`Session._pump_audio`), so the ceiling from
        `speak.py` is kept here even though this engine could answer exactly. The precise
        answer is better in every case but the one that matters: if synthesis stalls or
        the audio device stops consuming, an exact reading latches True and Flow goes
        permanently deaf. The deadline makes that impossible, and it is read here rather
        than enforced by the feeder for the reason `speak.Speaker.speaking` gives — the
        reader must not depend on a thread that may itself be stuck.
        """
        with self._lock:
            if not self._speaking:
                return False
            if time.monotonic() >= self._deadline:
                self._speaking = False
                return False
            return True

    def _synthesise(self, text: str, q: queue.Queue, epoch: int) -> None:
        """Generate PCM into `q`. Always terminates the queue with None.

        The generator is what makes `stop` cheap: abandoning it ends synthesis at the next
        sentence boundary, and nothing has to be killed or drained.
        """
        try:
            if not self._loaded.wait(LOAD_WAIT_SEC):
                return
            with self._lock:
                model, failed = self._model, self._load_failed
                if epoch != self._epoch:
                    return
            if model is None or failed:
                return
            from piper import SynthesisConfig

            cfg = SynthesisConfig(length_scale=length_scale(self._rate))
            for chunk in model.synthesize(text, cfg):
                with self._lock:
                    if epoch != self._epoch:
                        return
                q.put(chunk.audio_int16_bytes)
        except Exception:
            # A model that failed on this input. The reply falls silent and the session
            # carries on, which is the contract every engine here shares.
            pass
        finally:
            q.put(None)

    def _play(self, q: queue.Queue, epoch: int) -> None:
        """Write what the producer generates, after building a cushion first."""
        import sounddevice as sd

        stream = None
        current = False
        try:
            need = int(self._voice.sample_rate * 2 * PREBUFFER_SEC)
            pending, done = bytearray(), False
            # Filled before the device is opened, so the cushion is audio in hand rather
            # than an empty buffer the consumer is already behind on.
            while len(pending) < need and not done:
                with self._lock:
                    if epoch != self._epoch:
                        return
                item = q.get()
                if item is None:
                    done = True
                else:
                    pending += item
            if not pending:
                return
            stream = sd.RawOutputStream(
                samplerate=self._voice.sample_rate, channels=1, dtype="int16",
                latency=LATENCY,
            )
            stream.start()
            with self._lock:
                if epoch != self._epoch:
                    stream.close()
                    return
                self._stream = stream
            while True:
                # Written in slices rather than whole. `write` blocks until the device has
                # taken everything handed to it, so passing a whole sentence would make an
                # interruption wait for that sentence to finish playing.
                for i in range(0, len(pending), CHUNK_FRAMES * 2):
                    with self._lock:
                        if epoch != self._epoch:
                            return
                    stream.write(bytes(pending[i:i + CHUNK_FRAMES * 2]))
                if done:
                    break
                item = q.get()
                if item is None:
                    break
                pending = bytearray(item)
        except Exception:
            # A device that disappeared mid-reply, a model that failed on this input.
            # Both mean the utterance is over.
            pass
        finally:
            with self._lock:
                current = epoch == self._epoch
                if current:
                    self._speaking = False
                    self._stream = None
            if stream is not None and current:
                # Drain rather than abort: this is the end of the answer, not an
                # interruption, and clipping the last word would sound like a fault.
                for step in (stream.stop, stream.close):
                    try:
                        step()
                    except Exception:
                        pass

    def say(self, text: str) -> bool:
        """Speak `text`, cutting off whatever is already speaking. False if silent."""
        if not text.strip():
            return False
        if self._load_failed:
            return False
        from .speak import CEILING_SLACK_SEC, WORDS_PER_SEC

        self.stop()
        # The ceiling covers the load as well as the speech, because on the very first
        # reply after a voice is chosen the model may still be coming in.
        ceiling = len(text.split()) / WORDS_PER_SEC + CEILING_SLACK_SEC + LOAD_WAIT_SEC
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._epoch += 1
            epoch = self._epoch
            # Set before either worker starts, for the reason `speak.Speaker.say` gives:
            # the microphone has to be gated before the first sample, or the reply's
            # opening syllable is transcribed as the user's.
            self._speaking = True
            self._deadline = time.monotonic() + ceiling
        threading.Thread(target=self._synthesise, args=(text, q, epoch),
                         daemon=True, name="piper-synth").start()
        threading.Thread(target=self._play, args=(q, epoch),
                         daemon=True, name="piper-play").start()
        return True

    def stop(self) -> bool:
        """Cut off the current reply — the user has taken the answer back.

        Bumping the epoch is what ends synthesis: the feeder abandons the generator at its
        next check. `abort` rather than `stop` on the stream, which is the difference
        between silence now and silence after the rest of the sentence has played.
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
        with self._lock:
            self._model = None
