"""The user's own words.

Whisper decodes toward what it has seen most, which means a name, a repo, or a piece
of in-house jargon loses to whatever common word sounds nearest — and it loses harder
in an accent, because the acoustic evidence is already weaker (P4). faster-whisper
takes a `hotwords` string that is prepended to the decoder prompt, biasing it toward
those spellings. This module is where that string comes from.

A plain text file, one term per line, `#` for comments, re-read whenever it changes so
editing it does not mean restarting:

    # ~/.flow/lexicon.txt
    Kubernetes
    kubectl
    Grafana
    Samir

Deliberately not a config format. The user editing this is mid-task and annoyed that
their colleague's name keeps coming out wrong; a text file they can open and type into
is the whole interface.

**Biasing is not free, and the measurement says so loudly** (scripts/lexicon_bench.py,
`small.en`, EdAcc). When a term really is being said, biasing recovers **27–34%** of
the rare words the model otherwise missed, for about 3% relative WER. But on speech
containing *none* of the terms — the common case, since a lexicon is the user's
vocabulary rather than this utterance's — WER got **14–38% relatively worse**:
0.221 → 0.252 and 0.223 → 0.265 with 61 terms, and 0.201 → 0.278 with only **eight**.
The harm did not scale down with size, which is why there is no "safe small lexicon"
recommendation here.

So the file does not exist by default, and creating it is the opt-in. That is the
honest shape of the feature given the numbers: useful when a meaningful share of what
you dictate contains your terms, harmful when it does not. The targeted fix is Phase 3's
constrained re-decode — bias *only* when the first pass produced something phonetically
near a lexicon term — which spends the bias where it pays.

The cap is Flow's, not the library's. faster-whisper truncates the prompt at
`max_length // 2 - 1` tokens (223 for these models) *silently*, mid-term, which would
turn "Kubernetes" into a fragment biasing the decoder toward nothing in particular. So
terms are dropped whole, from the end, and the drop is reportable.
"""

from __future__ import annotations

import threading
from pathlib import Path

#: Where the file lives unless told otherwise. `~` expands on Windows too.
DEFAULT_PATH = Path.home() / ".flow" / "lexicon.txt"

#: A path that cannot exist, for `--no-lexicon`. Pointing the loader at nothing is
#: simpler than threading an enabled flag through the transcriber, and it keeps
#: "no lexicon" and "empty lexicon" the same code path.
NUL_PATH = Path(__file__).resolve().parent / "__no_such_lexicon__"

#: Cap on the prompt Flow will build. The library's own limit is 223 tokens; a term
#: averages 2–4 for the kind of words that end up here (proper nouns, tool names), so
#: 64 terms sits comfortably under it while leaving room for the space separators.
#: Measured cost of a full 64-term lexicon: see PROGRESS.md, 2026-07-31.
MAX_TERMS = 64

#: A single absurd line cannot eat the budget on its own.
MAX_TERM_CHARS = 40


def parse(text: str) -> list[str]:
    """Terms from file contents, in order, deduplicated case-insensitively.

    Order is the user's: the first terms in the file are the ones that survive the
    cap, so a lexicon that has grown past it degrades predictably from the bottom.
    """
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        term = line.split("#", 1)[0].strip()
        if not term or len(term) > MAX_TERM_CHARS:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= MAX_TERMS:
            break
    return out


def as_hotwords(terms: list[str]) -> str | None:
    """The string faster-whisper wants, or None when there is nothing to bias toward.

    `None` rather than `""` because an empty string still makes the library build a
    prompt prefix, and paying for a prompt that biases toward nothing is pure cost.
    """
    joined = " ".join(terms).strip()
    return joined or None


class Lexicon:
    """A lexicon file, re-read when it changes.

    Checked by mtime on every decode: a `stat` is microseconds against a decode of
    hundreds of milliseconds, and it means a user can add a name mid-session and have
    the next utterance pick it up.
    """

    def __init__(
        self, path: Path | str | None = None, learned=None
    ) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self._terms: list[str] = []
        self._stamp: tuple[float, int] | None = None
        self._lock = threading.Lock()
        #: P8: a callable returning terms Flow learned from the user's own corrections,
        #: merged with the file at read time rather than written into it. The file
        #: stays something the user typed and owns; what Flow inferred is kept
        #: separately, so deleting the profile forgets the inferences and nothing else.
        self._learned = learned

    def _merged(self) -> list[str]:
        """File terms first, learned terms after, deduplicated case-insensitively.

        File first because a term the user typed is a stated preference, and the
        `MAX_TERMS` cut has to fall on the inferred tail rather than on it.
        """
        terms = list(self._terms)
        if self._learned is None:
            return terms
        try:
            extra = self._learned() or []
        except Exception:
            return terms  # learning must never be able to break decoding
        seen = {t.lower() for t in terms}
        for term in extra:
            if term.lower() not in seen and len(term) <= MAX_TERM_CHARS:
                terms.append(term)
                seen.add(term.lower())
        return terms[:MAX_TERMS]

    def terms(self) -> list[str]:
        with self._lock:
            self._refresh()
            return self._merged()

    def hotwords(self) -> str | None:
        with self._lock:
            self._refresh()
            return as_hotwords(self._merged())

    def _refresh(self) -> None:
        try:
            st = self.path.stat()
            stamp = (st.st_mtime, st.st_size)
        except OSError:
            # No file is the normal case, not an error: Flow works without one.
            if self._stamp is not None:
                self._terms, self._stamp = [], None
            return
        if stamp == self._stamp:
            return
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return  # mid-write, or a permissions blip; keep the previous terms
        self._terms = parse(text)
        self._stamp = stamp
