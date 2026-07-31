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

#: Only ever applied to a *whole* utterance. "Thank you" inside real dictation must
#: survive; "Thank you." as the entire output of a silent stretch is Whisper's training
#: data leaking through.
_FILLER_ONLY = {
    "you", "thank you", "thanks", "thank you.", "thanks for watching",
    "thanks for watching!", "please subscribe", "subscribe", "bye", "bye.",
    "okay", "ok", "hmm", "mm", "uh", "um", "so", "yeah",
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


def normalise(text: str) -> str:
    """Whitespace and marker tidy-up, plus the two degenerate-repetition guards.

    Removes words only where they are a decode artefact — a token or a phrase looping
    beyond what speech does — never ordinary content.
    """
    text = strip_markers(text)
    text = collapse_repeats(text)
    text = collapse_phrase_repeats(text)
    return re.sub(r"\s{2,}", " ", text).strip()


def invented_reason(
    text: str,
    no_speech_prob: float | None = None,
    avg_logprob: float | None = None,
) -> str | None:
    """Which rule rejects this segment, or None to keep it.

    The decision is identical to `is_invented`; this form names the rule that fired.
    A drop is a deletion of something the user said, so it has to be attributable —
    both for the log line the runtime will emit (P2) and for a benchmark that needs to
    say *which* filter ate the speech rather than that some filter did.
    """
    stripped = normalise(text).strip().strip(".!?,").lower()
    if not stripped:
        return "empty"

    if no_speech_prob is None:
        # No probability available (a non-Whisper engine, say): fall back to the
        # narrow whole-utterance filler check only.
        return "filler" if stripped in _FILLER_ONLY else None

    if no_speech_prob <= NO_SPEECH_MAX:
        return None

    # Model says "probably not speech". Confirm with a second signal before dropping:
    # either the content is too thin to lose, or token confidence is also poor.
    thin = len(stripped.split()) <= 3
    unconfident = avg_logprob is not None and avg_logprob < LOW_CONFIDENCE
    if thin and unconfident:
        return "thin+unconfident"
    if thin:
        return "thin"
    if unconfident:
        return "unconfident"
    return None


def is_invented(
    text: str,
    no_speech_prob: float | None = None,
    avg_logprob: float | None = None,
) -> bool:
    """True if this segment looks like the model talking to itself.

    Requires two signals to agree, so an unusual-but-real utterance is not discarded on
    one borderline number.
    """
    return invented_reason(text, no_speech_prob, avg_logprob) is not None
