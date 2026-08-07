"""Speech-to-text.

Kept behind a deliberately tiny surface (`Transcriber.text`) so the engine can be
swapped for whisper.cpp later without touching the session logic — that swap is the
documented escape hatch if the ~384 MB faster-whisper footprint ever matters more
than build time.
"""

from __future__ import annotations

import os
import sys
import threading
from collections import deque
from pathlib import Path
from typing import NamedTuple, Protocol

import numpy as np

from .clean import invented_reason, normalise
from .lexicon import MAX_TERMS, Lexicon, as_hotwords

#: How many recent drops to keep. Bounded because R8 says a long session must cost what
#: a short one costs; 100 is enough for the UI to explain what just vanished.
DROP_HISTORY = 100

#: The two tiers, split because one model cannot serve both paths on this CPU.
#:
#: `small.en` is 16–23% relative better than `base.en` on four of five accent groups
#: (largest on Japanese, the worst-served: 0.306 → 0.234) — but the R4 gate measured it
#: at 2.66–3.78 s per partial *at every prefix length from 1 s up*, against a 1.5 s
#: budget, because Whisper pads every input to one 30 s mel window and there is no
#: short-utterance regime where the tier is fast. It cannot drive partials here.
#:
#: Finals are not bound that way — the draft is held on screen while they run (R5) — so
#: the accuracy goes where the text that actually gets pasted is decided: 3.65 s median
#: (4.87 s worst) for a full 10–20 s utterance.
#:
#: The cost is a visible partial→final rewrite, since the tiers disagree on roughly one
#: word in five of accented speech. That is the trade the numbers force, and it is the
#: same one Wispr makes.
PARTIAL_MODEL = "base.en"
FINAL_MODEL = "small.en"

#: One model for both paths, on a machine with a GPU.
#:
#: Everything the two tiers above argue is a *CPU* argument, and the GPU answers it
#: rather than refining it. Measured on this machine (GTX 1070, int8), same 300-clip
#: EdAcc slice (5 155 reference words) and the same decode options the app uses:
#:
#:     small.en            WER 0.194   RTF 0.070   ns 0.84-0.92
#:     medium.en           WER 0.183   RTF 0.131
#:     distil-large-v3     WER 0.181   RTF 0.111
#:     large-v3-turbo      WER 0.178   RTF 0.116   ns 0.000   <- guard dead
#:     large-v2            WER 0.170   RTF 0.211
#:     large-v3            WER 0.168   RTF 0.190   ns 0.81-0.85
#:     distil-large-v3.5   WER 0.160   RTF 0.104   ns 0.13-0.20  <- guard dead
#:
#: **The winner on word error is not the choice, and the `ns` column is why.** The
#: hallucination guard in clean.py gates on `no_speech_prob` before it looks at anything
#: else, and `distil-large-v3.5` and `large-v3-turbo` do not produce that signal — they
#: report near-zero on three seconds of digital silence. So the guard never fires for
#: them and Whisper's silence-hallucination goes into the draft: measured, both models
#: return "you" / "Thank you." on silence, room noise and fan noise, all three kept,
#: where `small.en` and `large-v3` have all three dropped as `filler`. P2 calls an
#: invented word a defect, and 1.6 fewer word errors per hundred does not buy one.
#:
#: `large-v3` is therefore the tier: best of the models whose signals still work, 13.4%
#: relatively better than the `small.en` the CPU ran, and 3.9x faster than it despite
#: being the largest thing here. `reports_no_speech()` keeps the rest of that list
#: usable — a model without the signal now falls back rather than losing the guard.
#:
#: The partial budget `small.en` could never meet on CPU — 2.66-3.78 s per prefix
#: against 1.5 s — `large-v3` meets: 0.75 s at a 1 s prefix rising to 1.30 s at 13 s,
#: median of three. That is inside the budget but it is the tightest number on this
#: page; if partials start arriving late under load, this is the line to revisit.
#:
#: Which means the split itself goes away here, and with it the cost the split was
#: paying: the visible partial->final rewrite, where the two tiers disagreed on roughly
#: one word in five of accented speech. One model cannot disagree with itself.
CUDA_MODEL = "large-v3"

#: Models that do not produce a usable `no_speech_prob`, and therefore cannot be trusted
#: to gate clean.py's hallucination filter.
#:
#: `invented_reason` treats a low `no_speech_prob` as "this is speech" and returns before
#: it consults the filler list at all, which is right for a model that reports the signal
#: and catastrophic for one that does not: the guard does not weaken, it switches off.
#: Measured on three seconds of digital silence — `small.en` 0.878, `large-v3` 0.849,
#: `large-v3-turbo` **0.000**, `distil-large-v3.5` **0.130**. The distilled and turbo
#: decoders drop the no-speech token behaviour along with the layers.
#:
#: Prefix-matched, because this is a property of a model *family* and the names are
#: versioned: `distil-large-v3`, `distil-large-v3.5` and `distil-small.en` all behave the
#: same way, and the next distil release will too.
_NO_SPEECH_BLIND = ("distil-", "large-v3-turbo", "turbo")


def reports_no_speech(name: str) -> bool:
    """False when this model's `no_speech_prob` must be treated as absent.

    Absent, not zero — `clean.invented_reason` has a documented path for an engine that
    cannot report it, and falling into that path keeps a narrow whole-utterance filler
    check. Passing the model's own 0.000 through instead keeps nothing.
    """
    base = name.rsplit("/", 1)[-1].lower()
    return not any(base.startswith(p) or p in base for p in _NO_SPEECH_BLIND)

#: Where a decode runs. "auto" means CUDA when this machine has a working one and CPU
#: otherwise — see `cuda_ready()` for what "working" has to mean on Windows, and
#: `CUDA_MODEL` above for what the GPU buys. CPU stays a first-class configuration:
#: `default_models("cpu")` is unchanged and a failed GPU build demotes to it.
DEVICE = "auto"


#: Partials pay for no retries at all. faster-whisper re-decodes a segment at rising
#: temperatures whenever `avg_logprob` falls under its −1.0 threshold, and accented
#: speech fails that check constantly: a 1 s Japanese-accented prefix scores −1.15 and
#: costs **2.40 s median (1.48–3.69 s, nondeterministic) against a 1.5 s R4 budget**,
#: versus 0.75 s greedy. A partial is provisional — the final replaces it within
#: seconds — so buying quality with latency is the wrong trade on this path.
PARTIAL_TEMPERATURES = (0.0,)

#: Finals are what gets pasted, so they can afford a bounded retry; the draft is held
#: on screen while they run (R5). Bounded, not open-ended: the library's full six-step
#: ladder costs **7.6 s and 8.5 s on 5 s of room noise** (measured, `.bench/room.wav`
#: and `fan55_quiet.wav`), which the three-step cap cuts to 5.3 s and 6.2 s.
FINAL_TEMPERATURES = (0.0, 0.2, 0.4)

#: Beam width. Partials are greedy — they get replaced. Finals use the library default
#: of 5 rather than the 2 this build shipped with: measured at +0.25 s median on a full
#: utterance for base.en (1.12 → 1.37 s), off the latency path entirely.
PARTIAL_BEAM = 1
FINAL_BEAM = 5


#: P2, defect 2: faster-whisper drops a segment *inside the library*, before Flow ever
#: sees it, when `no_speech_prob > 0.6` and `avg_logprob < -1.0` — and accented speech
#: scores worse on exactly those two signals. Measured on 280 short clips: 5 of 9
#: silent deletions happened there, unlogged and unattributable. `None` turns that
#: second, invisible filter off. Flow then has exactly one filter — its own, in
#: clean.py, which records what it drops and why.
#:
#: The cost is real and bounded: `no_speech_threshold` also suppresses the temperature
#: fallback on probable silence, so a *final* decoded from noise may now retry up to
#: its three capped steps. The speech gate means that is a rare path.
NO_SPEECH_THRESHOLD = None

#: `None` means: never retry a decode merely because the model was unsure. It still
#: retries when the output is *degenerate* — `compression_ratio_threshold` stays at the
#: library default and is what catches repetition loops, which is the case where a
#: hotter sample genuinely helps.
#:
#: Measured, and this is the whole argument: on the 300-clip accent slice the retry
#: buys nothing — base.en scores 0.233 / 0.283 / 0.173 / 0.189 / 0.276 across the five
#: groups without it versus 0.231 / 0.281 / 0.178 / 0.187 / 0.276 with it, differences
#: smaller than the run-to-run noise of the sampling itself. It costs, though: leaving
#: it at −1.0 turned one 5 s noise clip from 0.84 s into 3.66 s, because low confidence
#: on near-silence is exactly what a retry cannot fix.
LOG_PROB_THRESHOLD = None


#: **The send word is never biased toward. This is a safety rule, not a tuning choice.**
#:
#: `hotwords` is not a scoring hint. faster-whisper encodes it into the
#: `<|startofprev|>` prompt slot (`transcribe.py:get_prompt`) — the same context
#: `condition_on_previous_text=False` above exists to keep empty, and the one Whisper
#: parrots out of when the audio is short or unsure. Putting the trigger there does not
#: teach the decoder a word; it hands it a word to guess with.
#:
#: Measured on EdAcc with "boom"/"enter boom" as the bias against no bias at all:
#:
#:   - `small.en`, 300 conversational clips: the send word appears in text nobody said
#:     4 times against 0. Pooled WER moves -0.007, which is inside the run-to-run noise
#:     of the temperature fallback and points the other way on two of five groups.
#:   - `small.en`, 280 **short** clips, which is what a trigger actually looks like: 26
#:     against 0, WER 0.534 -> 0.624, and **6 decode to exactly "boom"** — a
#:     whole-utterance match, which is a Send. "MM HMM", "UM", "YEAH THAT'S COOL",
#:     "MM HMM TRUE", "I THINK THAT WAS WHAT HAPPEND".
#:   - `large-v3-turbo`, the same 280: **the stronger model is no safer**. 14 against 0,
#:     WER 0.458 -> 0.501, and the same **6 false sends** — "UM", "TOODLES", "OF
#:     AZKABAN", "I DON'T KNOW", "TWO MONTHS", "NO NO NO NO". Model quality is not the
#:     variable; a prompt on a low-information utterance is.
#:   - `large-v3-turbo`, 300 conversational clips: **the bias helps here**, and not by a
#:     little — 0.179 -> 0.157 (0.157-0.158 across runs), same sign on all five
#:     groups, 1 invented and 0 false
#:     sends. That is a real effect and it is not an argument for this: it is an
#:     argument that *some* prompt suits long conversational audio, and the send word
#:     was never the reason. Worth a neutral-prompt experiment; not worth six sends.
#:
#: Six filler sounds in 280 pasting a draft into a terminal and pressing Enter is not a
#: word-error rate, it is the irreversible action this grammar is built to make rare.
#: A gain on long utterances cannot buy it, because the two do not trade: the utterances
#: that gain are the ones that could never have fired a Send anyway.
#: The whole-utterance rule was doing its job; the bias was manufacturing whole
#: utterances for it to match. `Session._note_near_miss` is the half of that change that
#: costs nothing and stays: it reads phonetic similarity off text the decoder produced
#: on its own, and it only ever speaks.
#:
#: A first attempt gated the bias to utterances short enough to *be* a trigger, on the
#: reasoning that a long one can never fire a Send. That is true and it is backwards:
#: short is where the prompt dominates, so the gate kept the bias exactly where all six
#: false sends were. Recorded because the reasoning is tempting and the numbers are the
#: only thing that catches it.


#: The CUDA runtime libraries CTranslate2 reaches for, dependencies first.
#:
#: These ship as pip wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) that drop their
#: DLLs under `site-packages/nvidia/*/bin`, and nothing on Windows puts that directory on
#: the loader path. `os.add_dll_directory` is *not* enough on its own either: it steers
#: resolution for a Python extension's own imports, and CTranslate2 asks for cuBLAS with
#: a plain runtime `LoadLibrary` long after import, which searches PATH and the modules
#: already in the process. So the directory goes on PATH and the libraries are loaded by
#: absolute path up front — after which the later lookup finds them by name.
_CUDA_LIBS = ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn_ops64_9.dll")

#: Resolved once and remembered, because probing costs a DLL load and the answer cannot
#: change inside a session. None means "not asked yet".
_cuda_ok: bool | None = None


def _wheel_dll_dirs() -> list[str]:
    """Directories inside the venv holding CUDA DLLs, or [] when the wheels are absent.

    Absent is an ordinary case, not a failure: a machine with a system-wide CUDA install
    needs nothing from here, and a CPU-only machine needs nothing at all.
    """
    import importlib.util

    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    out = []
    for root in spec.submodule_search_locations:
        for sub in sorted(Path(root).iterdir()):
            for cand in (sub / "bin", sub / "lib"):
                if cand.is_dir() and any(cand.glob("*.dll")):
                    out.append(str(cand))
    return out


def cuda_ready() -> bool:
    """True when a decode can actually run on this machine's GPU.

    Three things have to line up and only the first is visible from `nvidia-smi`: a
    device has to exist, CTranslate2 has to see it, and the CUDA runtime has to be
    loadable. The third is the one that fails on Windows, and it fails *late* — the
    model builds happily on `cuda` and then the first encode raises `Library
    cublas64_12.dll is not found`. Checking the libraries here rather than trusting the
    device count is what turns that into a fallback instead of a broken session.
    """
    global _cuda_ok
    if _cuda_ok is not None:
        return _cuda_ok
    _cuda_ok = False
    try:
        import ctypes

        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return _cuda_ok
        if sys.platform == "win32":
            dirs = _wheel_dll_dirs()
            for d in dirs:
                os.add_dll_directory(d)
            if dirs:
                os.environ["PATH"] = os.pathsep.join(
                    dirs + [os.environ.get("PATH", "")])
            for name in _CUDA_LIBS:
                ctypes.CDLL(name)  # by name: PATH, then what is already loaded
        _cuda_ok = True
    except Exception:
        # Any of it missing means CPU, and CPU is a working configuration rather than a
        # degraded one — this is a speed and accuracy ceiling, not a dependency.
        _cuda_ok = False
    return _cuda_ok


def resolve_device(device: str = DEVICE) -> str:
    """"auto" becomes "cuda" or "cpu"; anything else is taken literally.

    `cuda_ready()` is called for an explicit "cuda" too, and discarded. It is not only a
    question — it is where the runtime libraries get put on the loader path, and asking
    for the GPU by name has to work at least as well as being given it by default. This
    was a real defect first: `--decode-device cuda` skipped the probe and every decode
    died on `cublas64_12.dll is not found` while `auto` on the same machine was fine.
    """
    if device == "cuda":
        cuda_ready()
        return "cuda"
    if device != "auto":
        return device
    return "cuda" if cuda_ready() else "cpu"


def default_models(device: str) -> tuple[str, str]:
    """(partial, final) for a resolved device.

    Kept as a function rather than two more constants because the answer is not two
    independent choices — on a GPU it is deliberately the *same* model twice, and a
    reader who changes one half of that should have to see the other.
    """
    if device == "cuda":
        return CUDA_MODEL, CUDA_MODEL
    return PARTIAL_MODEL, FINAL_MODEL


def decode_options(final: bool, hotwords: str | None = None) -> dict:
    """The decode parameters, in one place.

    Exported because the benchmarks in scripts/ decode with them too; a bench that
    quietly drifts from the app measures a build nobody runs.
    """
    if hotwords:
        return {**decode_options(final), "hotwords": hotwords}
    return {
        "language": "en",  # R2: never spend compute on language detection
        "beam_size": FINAL_BEAM if final else PARTIAL_BEAM,
        "temperature": FINAL_TEMPERATURES if final else PARTIAL_TEMPERATURES,
        "vad_filter": False,  # SpeechGate already decided this is speech
        # Critical for R8: with context carry-over, a long session can fall into
        # repetition loops where the model echoes earlier text forever.
        "condition_on_previous_text": False,
        "no_speech_threshold": NO_SPEECH_THRESHOLD,
        "log_prob_threshold": LOG_PROB_THRESHOLD,
    }


class Drop(NamedTuple):
    """One segment the filter rejected, with the evidence it used.

    P2 is "never loses words silently": a rejection is allowed, an *unexplained* one is
    not. Keeping the text is what makes a later rescue possible — the user cannot
    recover words they were never shown, but they can recover these.
    """

    text: str
    reason: str
    no_speech_prob: float | None
    avg_logprob: float | None
    final: bool

    def describe(self) -> str:
        ns = "?" if self.no_speech_prob is None else f"{self.no_speech_prob:.2f}"
        lp = "?" if self.avg_logprob is None else f"{self.avg_logprob:.2f}"
        kind = "final" if self.final else "partial"
        return f"dropped {self.text.strip()!r} ({self.reason}, ns={ns} lp={lp}, {kind})"


class Transcriber(Protocol):
    def text(
        self, audio: np.ndarray, *, final: bool = False, hotwords: str = ""
    ) -> str:
        """Transcribe mono float32 audio at SAMPLE_RATE. Returns plain text.

        `hotwords` biases this one decode — used by the constrained re-decode of a
        suspected mis-heard command. It is passed only when non-empty, so a simpler
        Transcriber that does not accept it still satisfies the caller.
        """
        ...


class WhisperTranscriber:
    """faster-whisper on CPU, int8, in two tiers.

    A fast model for partials and a stronger one for finals — see PARTIAL_MODEL and
    FINAL_MODEL for the measurements that forced the split. Pin both to one name
    (`WhisperTranscriber("base.en", "base.en")`) to benchmark a single tier.

    Loading is lazy *per tier*, so importing this module (and therefore starting the
    UI) pays nothing, and a session that only ever shows partials never loads the
    finals model at all.
    """

    def __init__(
        self,
        partial_model: str | None = None,
        final_model: str | None = None,
        compute_type: str = "int8",
        lexicon: Lexicon | None = None,
        baseline: float | None = None,
        device: str = DEVICE,
    ) -> None:
        #: P8: this speaker's own clean-speech `avg_logprob`, from calibration. None
        #: keeps the shipped absolute bar. See clean.confidence_floor.
        self.baseline = baseline
        #: None means "whatever this device should run" — resolved with the device, not
        #: here, because picking it needs to know whether there is a GPU and asking that
        #: loads DLLs. An explicit name is always honoured, on either device.
        self._asked = {False: partial_model, True: final_model}
        self._names_cache: dict[bool, str] | None = None
        #: The user's own words, biasing both tiers (P4). Re-read when the file
        #: changes, so a name added mid-session lands on the next utterance.
        self.lexicon = lexicon if lexicon is not None else Lexicon()
        self._compute_type = compute_type
        #: Resolved lazily rather than here, so constructing a Transcriber still costs
        #: nothing — `cuda_ready()` loads DLLs, and the UI builds one of these at start.
        self._device = device
        self._resolved: str | None = None
        self._models: dict[bool, object | None] = {False: None, True: None}
        # Guards the model dict and the drop log — both touched from the decode
        # thread and the UI thread. Never held across a model build.
        self._lock = threading.Lock()
        # Two threads can race to load: the background preload started by
        # Session.start() and the decode worker calling text() lazily. Without a lock
        # both build a model and one is thrown away, so each tier gets its own.
        self._locks = {False: threading.Lock(), True: threading.Lock()}
        #: Which tiers are being built right now. A first decode of a tier is a model
        #: load and not a slow decode, and those are a second apart in cost — so the UI
        #: has to be able to say which one the user is waiting on rather than showing
        #: the same indicator for both.
        self._loading: set[bool] = set()
        #: Recent rejections, newest last. Written on the decode thread and drained on
        #: the UI thread, so it is a deque with a maxlen rather than a growing list.
        self._drops: deque[Drop] = deque(maxlen=DROP_HISTORY)
        #: Worst avg_logprob of the last decode's kept segments. Drained
        #: by take_confidence(); see there for why it is not a mean.
        self._confidence: float | None = None

    def take_drops(self) -> list[Drop]:
        """Return and clear the recorded rejections.

        Draining rather than indexing, for the reason PROGRESS.md records about the
        soak test: a bounded deque stops growing once saturated, so "everything since
        last time" computed from a length silently returns nothing forever.
        """
        with self._lock:
            out = list(self._drops)
            self._drops.clear()
            return out

    def load(self, final: bool | None = None) -> None:
        """Load one tier, or both when called with no argument.

        `Session.start()` preloads both on a background thread. The order matters:
        partials are what the user waits on, and the finals model is the bigger
        download, so the fast tier is ready first even on a cold first run.
        """
        tiers = (False, True) if final is None else (final,)
        for tier in tiers:
            # One lock *per tier*, held across the build. Per tier, so that preloading
            # the finals model does not block a partial that only needs the fast one;
            # held across the build, because without that the preload thread and the
            # decode worker each construct a model and one is thrown away.
            with self._locks[tier]:
                if self._models[tier] is not None:
                    continue
                from faster_whisper import WhisperModel

                with self._lock:
                    self._loading.add(tier)
                try:
                    name = self.names[tier]
                    try:
                        model = WhisperModel(
                            name, device=self.device,
                            compute_type=self._compute_type,
                        )
                    except Exception:
                        # A GPU that will not build a model is a GPU this session does
                        # not have. Demote once, for every tier, rather than retrying
                        # per load — and never fail the session over it, because CPU is
                        # a working configuration.
                        if self.device == "cpu":
                            raise
                        self._resolved = "cpu"
                        # The names go with the device: the GPU tier is a model this CPU
                        # cannot decode inside any budget, so falling back to it would
                        # trade a broken session for an unusable one.
                        self._names_cache = None
                        model = WhisperModel(
                            self.names[tier], device="cpu",
                            compute_type=self._compute_type,
                        )
                    with self._lock:
                        self._models[tier] = model
                finally:
                    # Cleared after the model is published, not before, so there is no
                    # frame in which a tier is neither loading nor loaded and the UI
                    # reports the wait as an ordinary decode.
                    with self._lock:
                        self._loading.discard(tier)

    def take_confidence(self) -> float | None:
        """The worst `avg_logprob` among the segments the last decode kept.

        Worst, not mean: an utterance the model was sure about for four words and lost
        on the fifth is exactly the case the guardrail exists for, and a mean would
        hide it. None when the decode produced nothing, or when the model reported no
        score — callers must treat that as "unknown", never as "confident".

        Drained like `take_drops()`, because a stale reading is worse than no reading:
        it would let one confident utterance vouch for the next one.
        """
        with self._lock:
            out, self._confidence = self._confidence, None
        return out

    def unload(self) -> None:
        """Release both models after a long idle period (R8)."""
        with self._lock:
            self._models = {False: None, True: None}

    @property
    def loaded(self) -> bool:
        """True once *any* tier is resident — this is what the idle-unload check reads,
        and it must fire while either model is still holding memory."""
        with self._lock:
            return any(m is not None for m in self._models.values())

    @property
    def loading(self) -> bool:
        """True while a tier is being built, so the UI can name that wait.

        Measured at roughly a second per tier on a warm cache, and the whole download on
        a cold one. Both are indistinguishable from a slow decode without this, which is
        why the first utterance of a session used to look like the app had hung.
        """
        with self._lock:
            return bool(self._loading)

    @property
    def device(self) -> str:
        """"cuda" or "cpu", decided once and then fixed for the session.

        Named rather than assumed, because the startup diagnostic has to be able to say
        which one the user got: the difference is a 3.7 s final decode against ~0.3 s,
        and somebody whose GPU silently did not engage deserves to see that rather than
        wonder why it feels the same.
        """
        if self._resolved is None:
            self._resolved = resolve_device(self._device)
        return self._resolved

    @property
    def names(self) -> tuple[str, str]:
        """(partial, final) model names, for startup diagnostics.

        Resolving these resolves the device, since what a tier should be depends on it.
        """
        if self._names_cache is None:
            partial, final = default_models(self.device)
            self._names_cache = {
                False: self._asked[False] or partial,
                True: self._asked[True] or final,
            }
        return self._names_cache[False], self._names_cache[True]

    def _standing_bias(self) -> str | None:
        """The lexicon, and only ever the lexicon.

        The send words used to ride in front of this on every final decode. They do not
        any more, and the block above `decode_options` is the measurement that took them
        out — six of 280 short clips decoded to exactly "boom" and would have sent the
        draft. What the user has taught Flow is different in kind: those are words they
        actually say, the file they live in prices the bias in its own comments, and
        adding one is a thing they chose.
        """
        return as_hotwords(self.lexicon.terms()[:MAX_TERMS])

    def text(
        self, audio: np.ndarray, *, final: bool = False, hotwords: str = ""
    ) -> str:
        if audio.size == 0:
            return ""
        # Only the tier being used: a partial must never wait on the finals model.
        self.load(final)
        with self._lock:
            model = self._models[final]
        # A caller-supplied bias wins over the standing lexicon rather than joining
        # it: a rescue decode is aimed at one utterance, and the lexicon measurement
        # says a longer prompt full of terms that are not being said costs accuracy.
        bias = hotwords or self._standing_bias()
        segments, _ = model.transcribe(audio, **decode_options(final, bias))
        trusts_ns = reports_no_speech(self.names[final])
        kept = []
        worst: float | None = None
        for s in segments:
            # Drop segments the model invented rather than heard, and record every one
            # with the evidence used (P2). See flow/clean.py for the measurements
            # behind the thresholds.
            ns = getattr(s, "no_speech_prob", None)
            # A model that cannot report this must not be read as reporting *zero*:
            # `invented_reason` gates on it first, so a false 0.000 does not soften the
            # hallucination filter, it removes it. See `reports_no_speech`.
            if not trusts_ns:
                ns = None
            lp = getattr(s, "avg_logprob", None)
            reason = invented_reason(s.text, ns, lp, self.baseline)
            if reason is not None:
                with self._lock:
                    self._drops.append(Drop(s.text, reason, ns, lp, final))
                continue
            kept.append(s.text.strip())
            if lp is not None:
                worst = lp if worst is None else min(worst, lp)
        with self._lock:
            self._confidence = worst
        # Corrections last, and on the joined text: the router, the undo stack and the
        # paste all read what this returns, so a name the user has declared has to be
        # right by here or it is wrong everywhere. After `normalise`, so a declared
        # phrase matches tidied words rather than decoder markers and double spaces.
        return self.lexicon.apply(normalise(" ".join(kept)))
