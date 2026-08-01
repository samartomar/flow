"""Render the pill and bubble against a fake session, then exit.

Exists so the UI can be screenshotted and inspected without a microphone, a model, or
a person talking. Claiming a UI "works" without looking at it is not a claim worth much.

The fake session walks every state the indicator is meant to cover, in the order a real
converse-mode exchange produces them, so one run shows all of them — including the two
that used to be invisible entirely (decoding, model loading) and the one that used to be
a lie (bars alive while Flow is talking over a gated microphone).

    uv run python scripts/ui_probe.py [seconds] [--hold STATE] [--bare]

`--bare` starts with no draft and no note, which is the case the indicator was added
for: a wait with nothing else on screen, where the bubble has to bring itself up.
"""

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.session import Activity, Event, State  # noqa: E402
from flow.ui import Pill  # noqa: E402

DRAFT = (
    "Hey, I wanted to check whether we are still good for the review on Tuesday "
    "afternoon, and whether you had a chance to look at the updated figures."
)

#: (name, seconds, state, activity, hearing). One pass is 21 s.
#:
#: `hearing` is carried separately from the activity because it is the thing the *pill*
#: reads — the level bars are the other half of the same answer, and the whole point of
#: the speaking phase is that the two halves agree.
SCRIPT = [
    ("loading", 2.0, State.IDLE, Activity("loading the model", True), True),
    ("listening", 3.0, State.LISTENING, None, True),
    ("decoding", 2.5, State.LISTENING, Activity("decoding", True), True),
    ("draft", 3.0, State.DRAFT, None, True),
    ("refining", 3.0, State.REFINING, Activity("refining", True), True),
    ("asking", 3.5, State.ASKING, Activity("asking", True), True),
    ("speaking", 4.0, State.IDLE,
     Activity("speaking - not listening", False), False),
]


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

    def __init__(self, hold: str | None = None, bare: bool = False) -> None:
        self.draft = FakeDraft("" if bare else DRAFT)
        self.mic = FakeMic()
        self.force_next = None
        self._hold = hold
        self._events = [] if bare else [
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

    # -- the walk ----------------------------------------------------------

    def _phase(self):
        if self._hold is not None:
            for row in SCRIPT:
                if row[0] == self._hold:
                    return row
        t = (time.perf_counter() - self._t0) % sum(r[1] for r in SCRIPT)
        for row in SCRIPT:
            if t < row[1]:
                return row
            t -= row[1]
        return SCRIPT[-1]

    @property
    def state(self) -> State:
        return self._phase()[2]

    @property
    def activity(self):
        return self._phase()[3]

    @property
    def hearing(self) -> bool:
        return self._phase()[4]

    @property
    def level_db(self) -> float:
        # A plausible speech envelope so the bars show real movement (R13). Floored the
        # way the real session floors it, so the probe cannot show a meter the app
        # would not.
        if not self.hearing:
            return -120.0
        t = time.perf_counter() - self._t0
        env = 0.5 + 0.5 * math.sin(t * 5.0)
        wobble = 0.25 * math.sin(t * 23.0)
        return -58.0 + 46.0 * max(0.0, min(1.0, 0.55 * env + wobble))


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    hold = None
    if "--hold" in sys.argv:
        hold = sys.argv[sys.argv.index("--hold") + 1]
        argv = [a for a in argv if a != hold]
    seconds = float(argv[0]) if argv else 24.0
    pill = Pill(FakeSession(hold, bare="--bare" in sys.argv))
    pill.armed = True  # skip the click so the meter is live for the screenshot
    pill.after(int(seconds * 1000), pill.quit_app)
    pill.mainloop()


if __name__ == "__main__":
    main()
