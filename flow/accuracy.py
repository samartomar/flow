"""How well Flow hears *this* voice: five sentences, read aloud, scored word by word.

Every accuracy number elsewhere in this repository is somebody else's — EdAcc clips, the
recording kit's volunteers, the development machine's owner. The README says so in its
known limits ("Accuracy on your own voice is unmeasured"), and Flow Home's Voice page is
where that stops being true: the person reads these sentences, Flow decodes them through
the same pipeline it pastes from, and the page shows errors per 100 words and exactly
which words it missed — each one a candidate for the dictionary.

The sentences are short, ordinary developer speech, and each carries one of the sounds
the anchor accents trade (product.md): v and w (review, Wednesday), th (Thursday, the),
r and l (release, cluster, rename), and two names a decoder has no reason to know.
Scoring is word-level edit distance after a deliberately plain normalisation — lower
case, no punctuation — because the question is "did it hear the words", not "did it
punctuate them the way the sentence did".

Nothing here touches a microphone or a model; `flow/home/voice.py` does that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SENTENCES: tuple[str, ...] = (
    "Please review the pull request before the release on Wednesday.",
    "The deploy failed because the database connection pool was exhausted.",
    "Ask Priya to check the Kubernetes logs for the staging cluster.",
    "We should rename the variable and write a unit test for it.",
    "Send the summary to Samir and set up a meeting on Thursday afternoon.",
)


def words(text: str) -> list[str]:
    """The words of `text` as the score compares them: lower case, no punctuation.

    Apostrophes inside a word survive ("don't" is one word); hyphens split, because a
    decoder writes "set up" and "set-up" for the same sound.
    """
    return [w.strip("'") for w in re.findall(r"[a-z0-9']+", text.lower().replace("-", " "))
            if w.strip("'")]


@dataclass
class Step:
    """One aligned position: what was said, what was heard, and which of the four it is."""

    op: str  # "ok" | "sub" | "del" | "ins"
    said: str = ""
    heard: str = ""


@dataclass
class Score:
    """One sentence's result."""

    reference: str
    heard: str
    steps: list[Step] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for s in self.steps if s.op != "ok")

    @property
    def total(self) -> int:
        """Words in the sentence, which is what errors are counted per."""
        return sum(1 for s in self.steps if s.op != "ins")

    @property
    def missed(self) -> list[str]:
        """Words that were said and not written, in the sentence's own spelling."""
        spelled = {w.lower().strip(".,!?;:'\""): w.strip(".,!?;:'\"")
                   for w in self.reference.split()}
        return [spelled.get(s.said, s.said) for s in self.steps if s.op in ("sub", "del")]


def align(reference: str, heard: str) -> Score:
    """Word-level edit distance, with the path kept so the page can show the misses.

    Substitution, deletion and insertion cost one each. Several paths often share the
    fewest errors, and the one kept is the one that matches the most words: "review the
    pull request" heard as "we view the request" reads as *review* misheard, *view*
    added and *pull* dropped around a matched *the* — not as three words swapped for
    three others, which is the same count and a worse picture of what was heard.
    """
    ref, hyp = words(reference), words(heard)
    n, m = len(ref), len(hyp)
    # (errors, -matches): the fewest errors first, and among those the most matches.
    best = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    move = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        best[i][0], move[i][0] = (i, 0), "del"
    for j in range(1, m + 1):
        best[0][j], move[0][j] = (j, 0), "ins"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = ref[i - 1] == hyp[j - 1]
            e, k = best[i - 1][j - 1]
            options = [((e, k - 1), "ok") if same else ((e + 1, k), "sub")]
            e, k = best[i - 1][j]
            options.append(((e + 1, k), "del"))
            e, k = best[i][j - 1]
            options.append(((e + 1, k), "ins"))
            best[i][j], move[i][j] = min(options, key=lambda o: o[0])
    steps: list[Step] = []
    i, j = n, m
    while i > 0 or j > 0:
        op = move[i][j]
        if op in ("ok", "sub"):
            steps.append(Step(op, ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif op == "del":
            steps.append(Step("del", ref[i - 1], ""))
            i -= 1
        else:
            steps.append(Step("ins", "", hyp[j - 1]))
            j -= 1
    steps.reverse()
    return Score(reference, heard, steps)


def per_hundred(scores: list[Score]) -> float | None:
    """Errors per 100 words over every sentence read so far. None before the first."""
    total = sum(s.total for s in scores)
    if not total:
        return None
    return round(100.0 * sum(s.errors for s in scores) / total, 1)
