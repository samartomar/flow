"""What was already sent (P6).

Send used to erase. That is right for a dictation tool and wrong for the thing people
actually do with one: a prompt is rarely finished on the first send, and the next
utterance is usually a follow-up rather than a fresh thought. Keeping the sent turns
costs a few kilobytes and turns Flow from a typewriter into a conversation.

Bounded twice over, by turns and by characters, because R8 says a long session must
cost what a short one costs. The oldest turns fall off the front — the tail is what a
follow-up refers to, and nobody follows up on their fortieth-last prompt.
"""

from __future__ import annotations

from collections import deque

#: Turns kept. Twenty is far more than a follow-up ever reaches back through, and it
#: bounds the worst case at a few hundred kilobytes.
MAX_TURNS = 20

#: Total characters kept across all turns. A single enormous prompt must not be able
#: to hold the whole budget hostage.
MAX_CHARS = 20_000

#: What a CLI **rewrite** is allowed to see. Deliberately smaller than the store: context
#: is there to disambiguate a follow-up, not to re-send the conversation, and R11 caps
#: what reaches a subprocess.
CONTEXT_CHARS = 1_500

#: What a CLI **question** is allowed to see (P9), and the reason there are two numbers.
#:
#: There was one, and converse mode inherited it. The sentence above is the whole
#: argument for 1 500 and it is an argument about `refine`: a rewrite needs just enough
#: of the thread to know what "the other endpoint" refers to. Converse is not that job.
#: Its context *is* the conversation, and P9's card renders every turn of it on screen —
#: so the number sized for disambiguation was quietly deciding how much of a visible
#: conversation the CLI was allowed to remember.
#:
#: Measured 2026-08-06 on the owner's own session, rebuilt at its real lengths: five
#: turns on the card, 1 765 characters, of which `tail()` returned **three of the four**
#: prior turns. The opening question fell off, nothing said so, and the CLI answered "I
#: only have this conversation, which started with a question about a step-by-step plan"
#: — an accurate report of what it was handed, read by the owner as amnesia inside a
#: single session. Replies are stored as turns too and are the longer half, so in
#: converse every answer evicts a question.
#:
#: 8 000 is bounded and stays bounded, which is the property R8 asks for: under half the
#: 20 000-char store, so a long session still costs a fixed ceiling rather than a growing
#: one, and the cut still exists for a session that genuinely outruns it. What changed is
#: which side of the cut an ordinary conversation falls on. When it does cut, `Session`
#: now says how many turns went — the silence was the worse half of this defect.
ASK_CONTEXT_CHARS = 8_000


class Thread:
    """The prompts sent so far, oldest first."""

    def __init__(
        self, max_turns: int = MAX_TURNS, max_chars: int = MAX_CHARS
    ) -> None:
        self._turns: deque[str] = deque()
        self.max_turns = max_turns
        self.max_chars = max_chars

    def __len__(self) -> int:
        return len(self._turns)

    @property
    def turns(self) -> list[str]:
        return list(self._turns)

    @property
    def last(self) -> str:
        """The most recently sent prompt, or "" if nothing has been sent."""
        return self._turns[-1] if self._turns else ""

    @property
    def chars(self) -> int:
        return sum(len(t) for t in self._turns)

    def add(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._turns.append(text)
        self._trim()

    def _trim(self) -> None:
        while len(self._turns) > self.max_turns:
            self._turns.popleft()
        # Never trim to nothing: one oversized turn is kept whole rather than dropped,
        # because "bring back my last prompt" has to work even for a long one.
        while len(self._turns) > 1 and self.chars > self.max_chars:
            self._turns.popleft()

    def tail(self, max_chars: int = CONTEXT_CHARS) -> list[str]:
        """The most recent turns that fit in `max_chars`, oldest first.

        Whole turns only. Half a previous prompt is worse than none: it reads as
        context while being missing the part that mattered.
        """
        out: list[str] = []
        used = 0
        for turn in reversed(self._turns):
            if out and used + len(turn) > max_chars:
                break
            out.append(turn)
            used += len(turn)
        return list(reversed(out))

    def clear(self) -> None:
        self._turns.clear()
