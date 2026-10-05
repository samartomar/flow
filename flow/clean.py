"""Rejecting text the model invented rather than heard.

Whisper hallucinates on silence and noise — an artefact of its training data. For a tool
that pastes into the user's document, an invented word is a defect, not a quirk.

Measured on this machine with `base.en` (scripts/hallucination_probe.py):

    input                     no_speech_prob   emitted
    digital silence 3s        0.691            'You'
    quiet noise 3s            -                nothing
    room-ish noise 3s         -                nothing
    louder hiss 2s            0.899            'You'
    genuine 0.4s fragment     0.099            'I need...'
    real speech               0.00017          correct transcription

So `no_speech_prob` separates invention from speech with a wide margin, and the filter is
built around that rather than around a blocklist of phrases.

The bias throughout is deliberate: **dropping a real word is worse than admitting a rare
invented one**, because the user can delete a stray word but cannot recover one that was
never shown. Every rule here needs two independent signals before it discards anything.
"""

from __future__ import annotations

import re

#: Above this, the model itself believes there was no speech. Chosen to sit clear of a
#: genuine short fragment (0.099 measured) and below an outright hallucination (0.691).
NO_SPEECH_MAX = 0.6

#: A second, independent signal: poor average token confidence.
LOW_CONFIDENCE = -0.8

#: How far below a speaker's *own* clean-speech confidence counts as unconfident (P8).
#:
#: `avg_logprob` is not comparable between speakers, which makes a single absolute bar
#: mean different things to different people. Measured on 200 accent clips: Spanish
#: -0.62 median against -0.27…-0.32 for indian, japanese, russian and the US control.
#: So -0.8 sits 0.5 below a typical speaker's baseline and only 0.18 below a
#: Spanish-accented one — the same rule, applied far more aggressively to one accent.
#: -0.5 is that typical distance, taken from the US control's -0.29 against the shipped
#: -0.8, so a calibrated typical speaker keeps exactly the behaviour they had.
CONFIDENCE_MARGIN = -0.5


#: The invention bar for an engine that has no `no_speech_prob` at all: the **mean
#: log-probability of the tokens it emitted** (`flow/parakeet.py` reads it from onnx-asr's
#: `logprobs`). Not `LOW_CONFIDENCE`, which is Whisper's per-segment `avg_logprob` on
#: Whisper's own scale, so it is a second constant rather than a reuse.
#:
#: **Provisional: thin on inventions, and measured twice.** Parakeet TDT 0.6B v3 on
#: onnx-asr, 2026-10-05 (`scripts/parakeet_bench.py`), 300 EdAcc clips and 8 silence/noise
#: clips, CPU:
#:
#:                  real speech mean log-prob        silence/noise inventions
#:                  p1      p5     p50   below bar     (mean log-prob)
#:   fp32          -0.51   -0.28  -0.09    1 of 300      none of 8
#:   int8          -0.57   -0.40  -0.11    0 of 299      "Okay." -0.60, "Ha ha" -0.90
#:   sherpa int8   -0.59   -0.40  -0.11                   "It is." -1.10  (the first spike)
#:
#: The two builds sit on the same scale, so one bar serves both. -0.8 catches "Ha ha" and
#: "It is."; "Okay." is not below it and is caught by the filler list instead. The cost is
#: the one fp32 clip under the bar — a one-word "So", which the filler list would have taken
#: anyway. What is NOT known: fp32 produced no invention at all, so on that build the bar has
#: nothing to be checked against, and three inventions in total cannot say where the rest
#: sit. Re-measure before trusting it more, and prefer relaxing it to tightening it: a
#: dropped real word cannot be recovered.
TOKEN_LOGPROB_MIN = -0.8

#: The same bar for the Parakeet **GPU** build, whose helper reports a **mean word
#: confidence** (NeMo's `max_prob`, aggregated per word with `min`) instead of token
#: log-probabilities. parakeet.cpp v0.5.0, q8_0, CUDA and Vulkan, 2026-10-05
#: (`scripts/parakeet_bench.py gpu`), 300 EdAcc clips: p1 0.52-0.53, p5 0.68, p50 0.89, and
#: the only clips under 0.5 are two one-or-three-word fragments ("Okay." 0.39, "So" 0.43)
#: that the filler list drops anyway; the lowest non-filler clip is 0.51. **Zero inventions on
#: the 8 silence/noise clips, on either backend** - so, unlike the bars above, this one has no
#: invention to be checked against at all. 0.45 is `exp(TOKEN_LOGPROB_MIN)` (0.449), which is
#: the same geometric-mean confidence the log-prob bar encodes, carried over by translation
#: rather than calibrated: it sits clear under every real non-filler clip, and what it catches
#: is the weak kind of invention the sibling builds produced ("Ha ha", "It is."). Provisional;
#: re-measure when this engine invents something, and relax before tightening.
WORD_CONF_MIN = 0.45


def confidence_floor(baseline: float | None) -> float:
    """The unconfident bar for this speaker.

    Deliberately `min`, so calibration can only ever *relax* the filter. A speaker
    whose clean speech reads -0.19 would otherwise get a bar of -0.69 and start losing
    words they never used to lose — P2 says a drop is a deletion of something the user
    said, and a feature meant to remove an accent penalty must not add a new one to
    whoever calibrates. Measuring yourself can buy you leniency; it cannot cost you.
    """
    if baseline is None:
        return LOW_CONFIDENCE
    return min(LOW_CONFIDENCE, baseline + CONFIDENCE_MARGIN)


#: Only ever applied to a *whole* utterance. "Thank you" inside real dictation must
#: survive; "Thank you." as the entire output of a silent stretch is Whisper's training
#: data leaking through. Since 2026-07-31 this list carries more weight: it is the
#: second signal that replaced "the utterance is short", which was deleting real
#: spoken corrections.
_FILLER_ONLY = {
    "you", "thank you", "thanks", "thank you.", "thanks for watching",
    "thanks for watching!", "thank you for watching", "thank you for watching.",
    "thank you for watching!", "thanks for listening", "please subscribe",
    "subscribe", "bye", "bye.", "okay", "ok", "hmm", "mm", "uh", "um", "so", "yeah",
}

#: Non-speech markers Whisper emits verbatim.
_MARKERS = re.compile(
    r"\[(?:blank_audio|music|silence|noise|inaudible|applause)\]"
    r"|\((?:silence|music|inaudible|laughs?)\)"
    r"|[♪♫♩]",
    re.I,
)


def strip_markers(text: str) -> str:
    return _MARKERS.sub(" ", text)


def collapse_repeats(text: str, limit: int = 3) -> str:
    """Collapse a token repeated back to back more than `limit` times.

    Guards against the `bring // // // //` output observed in stage 3 partials, and
    against the loops the capped temperature ladder no longer breaks: a 0.55 s clip
    came back as 29 segments of "Okay.".

    `limit` is 3 rather than 1 because real speech does repeat a word — "very very
    very good" survives untouched. It does not repeat one twenty-nine times.

    This used to apply only to tokens of at most two characters, on the theory that
    longer words are always real. The measurement above is what disproved that: the
    two-character rule and `collapse_phrase_repeats`'s two-word minimum left a gap
    exactly wide enough for a single long token to loop through.
    """
    out: list[str] = []
    run_token: str | None = None
    run_len = 0
    for tok in text.split():
        if tok == run_token:
            run_len += 1
        else:
            run_token, run_len = tok, 1
        if run_len > limit:
            continue
        out.append(tok)
    return " ".join(out)


def collapse_phrase_repeats(text: str, limit: int = 2, max_phrase: int = 12) -> str:
    """Collapse a *phrase* repeated back to back more than `limit` times.

    Whisper's defence against a repetition loop is its temperature ladder: when a
    decode comes back too repetitive it retries hotter, and the hot samples break the
    loop. Flow caps that ladder at three steps because the full six cost 7.6 s on 5 s
    of room noise (see flow/asr.py), which means Flow has to break the loops itself.

    Measured on the 300-clip accent slice: capping the ladder without this turned one
    Spanish clip into "I'm so sorry." thirty times — 87 edits against a four-word
    reference. Deterministic and free, where a hotter re-decode is neither.

    Only phrases of two or more words are considered; single-token runs are
    `collapse_repeats`'s job, and its limit is deliberately looser because real speech
    repeats single words ("no no no") far more readily than it repeats phrases.

    `max_phrase` is 12 words because the loops are not short: a 2.6 s Indian clip came
    back as "I read on the bit of course" — seven words — repeated twenty-two times,
    and a six-word window missed it entirely. Nobody dictates the same seven-word
    phrase three times in a row on purpose.
    """
    words = text.split()
    if len(words) < 2 * 2:  # too short to contain a repeated multi-word phrase
        return text
    out: list[str] = []
    i = 0
    while i < len(words):
        # Shortest phrase first, because that is the *fundamental* period. Scanning
        # longest-first matches a multiple of it — thirty copies of "I'm so sorry."
        # look like fifteen copies of a six-word phrase, and keeping two of those
        # leaves four copies behind.
        for k in range(2, min(max_phrase, (len(words) - i) // 2) + 1):
            phrase = words[i:i + k]
            j = i + k
            reps = 1
            while words[j:j + k] == phrase:
                reps += 1
                j += k
            if reps > limit:
                out.extend(phrase * limit)
                i = j
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


#: Whisper's sign-off hallucination, which arrives **in front of real speech** rather
#: than in place of it. Observed 2026-09-30 on this machine: "So when this works" came
#: back as *"Thank you for watching. So when this works"* — the words, prefixed.
#:
#: **This is a different defect from the whole-utterance list above, and the two are not
#: substitutes.** `_FILLER_ONLY` is only ever consulted on the entire output, so a
#: hallucination with real dictation behind it sails past it by construction. And the
#: string that turned up was *"thank you for watching"*, which the list did not hold
#: anyway — it holds *"thanks for watching"* and *"thank you."* separately, and the
#: model emits all four spellings.
#:
#: **Only a leading fragment, and only these.** Every one of these is a YouTube sign-off
#: and not a thing a developer says into a dictation app and then keeps talking through, so
#: the risk of cutting real speech is far below the cost of pasting this in front of it
#: every time the room goes quiet. Bare `"thank you"`, `"so"` and `"okay"` are *not*
#: here: those are ordinary words inside real sentences, and removing them would be the
#: defect this list exists to avoid.
_SIGNOFF_PREFIX = re.compile(
    # "thank you for" and "thanks for" are two different strings and the model emits
    # both. `thanks?` alone matches only the second, which is why the reported phrase
    # sailed through on the first attempt at this.
    r"^(?:thanks?\s+(?:you\s+)?for\s+(?:watching|listening|subscribing)"
    r"|please\s+subscribe"
    # `bye` is a real English word a person says, so it is only a sign-off at the very
    # end of the output — never as a prefix in front of real speech. "Bye then, I will
    # call back" is somebody's sentence and was being cut to "then, I will call back".
    # The trailing punctuation is its own here because the shared `[\s,.!]*` below would
    # otherwise run past the anchor and eat the rest of the sentence with it.
    r"|bye[\s,.!]*\Z"
    r"|subtitles?\s+by\s+\S+"
    r"|amara\.org"
    r"|www\.\S+)"
    # The punctuation and spaces that followed the phrase, so "…watching. So when this
    # works" becomes "So when this works" rather than ". So when this works". The
    # sign-offs only — `bye` below carries its own anchor and must not be eaten.
    r"[\s,.!]*",
    re.I,
)


def strip_signoff_prefix(text: str) -> str:
    """One leading sign-off hallucination, if that is what this is.

    **A loop, not a single pass.** Whisper stacks them — "Thanks for watching. Thank you
    for watching." was measured on the same recording — and one substitution would leave
    the second behind, which is the half the bug report did not mention. Bounded at
    three, because past that it is not a sign-off any more and something in the room is
    being dictated.
    """
    out = text
    for _ in range(3):
        stripped = _SIGNOFF_PREFIX.sub("", out, count=1)
        if stripped == out:
            break
        out = stripped
    return out


def normalise(text: str) -> str:
    """Whitespace and marker tidy-up, plus the three degenerate-repetition guards.

    Removes words only where they are a decode artefact — a token or a phrase looping
    beyond what speech does, or a sign-off hallucination in front of it — never ordinary
    content.
    """
    text = strip_markers(text)
    text = collapse_repeats(text)
    text = collapse_phrase_repeats(text)
    text = strip_signoff_prefix(text)
    return re.sub(r"\s{2,}", " ", text).strip()


def invented_reason(
    text: str,
    no_speech_prob: float | None = None,
    avg_logprob: float | None = None,
    baseline: float | None = None,
    mean_token_logprob: float | None = None,
    mean_word_conf: float | None = None,
) -> str | None:
    """Which rule rejects this segment, or None to keep it.

    The decision is identical to `is_invented`; this form names the rule that fired.
    A drop is a deletion of something the user said, so it has to be attributable —
    both for the log line the runtime will emit (P2) and for a benchmark that needs to
    say *which* filter ate the speech rather than that some filter did.

    `mean_token_logprob` is read **only when `no_speech_prob` is None** — an engine that
    has no silence probability (Parakeet) and does have per-token log-probabilities. A
    caller that has `no_speech_prob` is a Whisper caller and gets exactly the rules below
    the early return, unchanged; the argument cannot soften or tighten them.
    """
    stripped = normalise(text).strip().strip(".!?,").lower()
    if not stripped:
        return "empty"

    if no_speech_prob is None:
        # No probability available (a non-Whisper engine, say): fall back to the
        # narrow whole-utterance filler check, and — for an engine that reports its
        # token confidence — the one signal it has. Filler first, so a known
        # hallucination keeps the more specific name.
        if stripped in _FILLER_ONLY:
            return "filler"
        if mean_token_logprob is not None and mean_token_logprob < TOKEN_LOGPROB_MIN:
            return "unconfident-tokens"
        if mean_word_conf is not None and mean_word_conf < WORD_CONF_MIN:
            return "unconfident-words"
        return None

    if no_speech_prob <= NO_SPEECH_MAX:
        return None

    # The model says "probably not speech". That is one signal, and one is not enough
    # to delete what someone said, so a second must agree:
    #
    #   filler       - the whole utterance is a phrase Whisper is known to emit into
    #                  silence. Evidence about *this text*, independent of length.
    #   unconfident  - the token probabilities are poor too.
    #
    # Shortness is deliberately **not** one of them any more. It used to be, and it is
    # the roadmap's defect 3: a spoken correction *is* short ("delete that line"), so
    # dropping on length preferentially deletes commands from the people whose speech
    # scores worst on `no_speech_prob` — exactly the users Flow is for. Measured on the
    # short-clip slice, the thin rule alone accounted for the drop of a confident,
    # correctly transcribed utterance while the filler list catches the actual
    # hallucinations: the digital-silence 'You' (0.691 / −0.711) is thin *and* filler,
    # so it still dies here.
    if stripped in _FILLER_ONLY:
        return "filler"
    if avg_logprob is not None and avg_logprob < confidence_floor(baseline):
        return "unconfident"
    return None


def is_invented(
    text: str,
    no_speech_prob: float | None = None,
    avg_logprob: float | None = None,
    baseline: float | None = None,
    mean_token_logprob: float | None = None,
    mean_word_conf: float | None = None,
) -> bool:
    """True if this segment looks like the model talking to itself.

    Requires two signals to agree, so an unusual-but-real utterance is not discarded on
    one borderline number. (The token-confidence path for an engine with no
    `no_speech_prob` is the exception, and `TOKEN_LOGPROB_MIN` says why it is allowed.)
    """
    return invented_reason(text, no_speech_prob, avg_logprob, baseline,
                           mean_token_logprob, mean_word_conf) is not None
