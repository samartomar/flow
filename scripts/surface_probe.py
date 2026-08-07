"""Real Tk: exactly one of the two surfaces is up, whatever arrives and whenever.

    uv run python scripts/surface_probe.py

Item 63 made a mode switch a surface switch and proved it with a throwaway probe. Item 73
is what that costs: a reply arriving 12 s after the switch reopened the card on top of the
draft bubble, nothing in the suite could see it, and the probe that would have caught it
had not been kept. This one is kept.

It reads **Tk's own `state()`**, not the code's claim about it, and drives everything
through `Pill._frame` — the same two rules that made item 63's probe find a `card.partial`
call against a method renamed two commits earlier. Unit tests here assert that the reply
branch passed `surface=False`; that is a statement about an argument. The defect was two
windows on a screen, and this is the only thing that measures two windows on a screen.

Exit status is the number of failed checks, so it can stand in a list of checks.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling FakeSession

from flow.session import CONVERSE, DICTATE, Event, State  # noqa: E402
from flow.ui import Pill  # noqa: E402
from ui_probe import FakeSession  # noqa: E402

ANSWER = "the CLI finally answered, 12 s later"


class Probe(FakeSession):
    """Silent by design: no scripted walk and no activity.

    `ui_probe`'s session cycles seven states so a screenshot shows all of them, and any
    one of them can bring a surface up on its own — which would make every reading here
    a measurement of the walk rather than of the event under test.
    """

    def __init__(self) -> None:
        super().__init__(bare=True)
        self.mode = DICTATE

    @property
    def state(self) -> State:
        return State.IDLE

    @property
    def activity(self):
        return None

    @property
    def hearing(self) -> bool:
        return True

    @property
    def level_db(self) -> float:
        return -120.0

    def queue(self, *events) -> None:
        self._events.extend(Event(kind, text) for kind, text in events)

    def toggle_mode(self) -> str:
        self.mode = CONVERSE if self.mode == DICTATE else DICTATE
        self.queue(("mode", self.mode))
        return self.mode


def up(win) -> bool:
    return bool(win.winfo_exists() and win.state() != "withdrawn")


def main() -> int:
    session = Probe()
    pill = Pill(session)
    pill.armed = True
    rows: list[str] = []
    bad = 0

    def frame(n: int = 3) -> None:
        # More than one, because a surface raised on frame N is only readable on N+1 —
        # `deiconify` is a request to the window manager, not a state change.
        for _ in range(n):
            pill._frame()
            pill.update()
            time.sleep(0.02)

    def check(label: str, bubble: bool, card: bool, note: str = "") -> None:
        nonlocal bad
        frame()
        got = (up(pill.bubble), up(pill.card))
        ok = got == (bubble, card)
        bad += 0 if ok else 1
        rows.append(
            f"{'ok  ' if ok else 'FAIL'}  {label:<44}"
            f"bubble={str(got[0]):<6}card={str(got[1]):<6}"
            f"{'  <-- TWO WINDOWS' if got[0] and got[1] else ''}{note}"
        )

    frame()
    check("start, dictate, nothing said", False, False)

    session.toggle_mode()
    session.queue(("draft", "how do I add a column"))
    check("converse, question forming", False, True)

    session.queue(("draft", ""), ("reply", "you add it with a migration"))
    check("converse, answer lands", False, True)

    # Item 73's sequence, as reported: ask in converse, switch before the CLI answers.
    session.toggle_mode()
    check("switched to dictate mid-ask", True, False)

    session.queue(("draft", "AI-Continuum is a local-first memory workspace"))
    check("dictate, drafting from the clipboard", True, False)

    session.queue(("reply", ANSWER))
    check("item 73: answer arrives in dictate", True, False)

    held = pill.card._answer == ANSWER
    session.toggle_mode()
    check("switched back to converse", False, True,
          f"  held: {pill.card._answer!r}")

    # The other half of item 73, and the reason the answer is held rather than dropped:
    # one mode switch has to be the whole cost of reading it.
    rows.append(f"{'ok  ' if held else 'FAIL'}  "
                f"{'the answer was held while the card was down':<44}")
    bad += 0 if held else 1

    print("\n".join(rows))
    print(f"\n{len(rows) - bad}/{len(rows)} checks passed")
    pill.quit_app()
    return bad


if __name__ == "__main__":
    sys.exit(main())
