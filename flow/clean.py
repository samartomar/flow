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
    """Collapse degenerate repetition of short, low-content tokens.

    Guards against the `bring // // // //` output observed in stage 3 partials. Only
    tokens that are punctuation or at most two characters are collapsed — real speech
    genuinely repeats words ("very very good"), and that must not be touched.
    """
    out: list[str] = []
    run_token: str | None = None
    run_len = 0
    for tok in text.split():
        if tok == run_token:
            run_len += 1
        else:
            run_token, run_len = tok, 1
        collapsible = len(tok) <= 2 or not any(c.isalnum() for c in tok)
        if collapsible and run_len > limit:
            continue
        out.append(tok)
    return " ".join(out)


def normalise(text: str) -> str:
    """Whitespace and marker tidy-up. Never removes words."""
    text = strip_markers(text)
    text = collapse_repeats(text)
    return re.sub(r"\s{2,}", " ", text).strip()


def is_invented(
    text: str,
    no_speech_prob: float | None = None,
    avg_logprob: float | None = None,
) -> bool:
    """True if this segment looks like the model talking to itself.

    Requires two signals to agree, so an unusual-but-real utterance is not discarded on
    one borderline number.
    """
    stripped = normalise(text).strip().strip(".!?,").lower()
    if not stripped:
        return True

    if no_speech_prob is None:
        # No probability available (a non-Whisper engine, say): fall back to the
        # narrow whole-utterance filler check only.
        return stripped in _FILLER_ONLY

    if no_speech_prob <= NO_SPEECH_MAX:
        return False

    # Model says "probably not speech". Confirm with a second signal before dropping:
    # either the content is too thin to lose, or token confidence is also poor.
    thin = len(stripped.split()) <= 3
    unconfident = avg_logprob is not None and avg_logprob < LOW_CONFIDENCE
    return thin or unconfident
