"""Render the pill and bubble against a fake session, then exit.

Exists so the UI can be screenshotted and inspected without a microphone, a model, or
a person talking. Claiming a UI "works" without looking at it is not a claim worth much.

    uv run python scripts/ui_probe.py [seconds]
"""

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.session import Event, State  # noqa: E402
from flow.ui import Pill  # noqa: E402

DRAFT = (
    "Hey, I wanted to check whether we are still good for the review on Tuesday "
    "afternoon, and whether you had a chance to look at the updated figures."
)


class FakeMic:
    def stop(self) -> None: ...


class FakeDraft:
    def __init__(self, text: str) -> None:
        self.text = text

    def clear(self) -> str:
        out, self.text = self.text, ""
        return out


class FakeSession:
    """Just enough of the Session surface for the UI to drive."""

    def __init__(self) -> None:
        self.state = State.DRAFT
        self.draft = FakeDraft(DRAFT)
        self.mic = FakeMic()
        self.force_next = None
        self._events = [
            Event("draft", DRAFT),
            Event("note", "local: replace('thursday' -> 'Tuesday')"),
        ]
        self._t0 = time.perf_counter()

    def start(self) -> None: ...
    def close(self) -> None: ...
    def tick(self) -> None: ...

    def events(self):
        out, self._events = self._events, []
        return out

    def send(self) -> str:
        return self.draft.clear()

    @property
    def level_db(self) -> float:
        # A plausible speech envelope so the bars show real movement (R13).
        t = time.perf_counter() - self._t0
        env = 0.5 + 0.5 * math.sin(t * 5.0)
        wobble = 0.25 * math.sin(t * 23.0)
        return -58.0 + 46.0 * max(0.0, min(1.0, 0.55 * env + wobble))


def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    pill = Pill(FakeSession())
    pill.armed = True  # skip the click so the meter is live for the screenshot
    pill.after(int(seconds * 1000), pill.quit_app)
    pill.mainloop()


if __name__ == "__main__":
    main()
