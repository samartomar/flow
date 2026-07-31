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

#: What a CLI rewrite is allowed to see. Deliberately smaller than the store: context
#: is there to disambiguate a follow-up, not to re-send the conversation, and R11 caps
#: what reaches a subprocess.
CONTEXT_CHARS = 1_500


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
