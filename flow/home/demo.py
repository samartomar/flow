"""Flow Home against a pretend session: `python -m flow.home.demo`.

For working on the page itself — no microphone, no model, no pill. Every setting works
against an in-memory session and a profile in a temporary folder, and the model list is
this machine's real cache, so what the Models page shows is true of the machine even
though nothing here decodes. `--no-open` prints the address instead of opening a window.

`FakeSession` is also what `tests/test_home_api.py` drives, which is why it lives in the
package rather than in `scripts/`: it is the smallest honest statement of the session
surface Flow Home depends on.
"""

from __future__ import annotations

import argparse
import queue
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from ..edits import SEND_ENTER_WORD, SEND_WORD
from ..history import (
    ANSWERED,
    ASKED,
    DICTATED,
    KEEP,
    REFINED,
    SET_ASIDE,
    History,
    NullHistory,
    make_entry,
    new_id,
)
from ..notes import Notes, render as render_notes
from ..session import CONVERSE, DICTATE, RECENT_ANSWERED, RECENT_ASKED, RECENT_SAID

#: What the pretend CLI answers, whatever it is asked: long enough to scroll, with the
#: code block and the inline code a real answer carries, so the page's rendering of
#: both has something to render.
DEMO_ANSWER = (
    "In `flow/ui.py`: a press shorter than `PILL_HOLD_SEC`, 0.30 s, is a tap and cycles "
    "the mode; anything longer is a hold and opens the microphone. Beside it, "
    "`PILL_DRAG_SLOP` gives a hold 4 px to wander, so a nudge while you talk is not read "
    "as a drag.\n\n```python\nPILL_HOLD_SEC = 0.30   # tap below, hold above\n"
    "PILL_DRAG_SLOP = 4     # px a hold may wander\n```\n\n"
    "**Both surfaces** read the same constant, so the compact pill splits a tap from a "
    "hold at the same 0.30 s."
)


class FakeTranscriber:
    def __init__(self) -> None:
        self._asked = (None, None)
        self.device = "cuda"
        self.loading = False
        self.loaded = True
        self.lexicon = None
        self.swaps: list[tuple] = []

    @property
    def asked(self):
        return self._asked

    @property
    def names(self):
        from ..asr import default_models

        auto = default_models(self.device)
        return (self._asked[0] or auto[0], self._asked[1] or auto[1])

    def swap(self, partial, final, device=None) -> bool:
        before = self.names
        self._asked = (partial, final)
        if device and device != "auto":
            self.device = device
        self.swaps.append((partial, final, device))
        return before != self.names

    #: What the pretend decoder hears for each accuracy sentence: the kind of misses an
    #: accent produces, so the demo's check has something to show.
    MISHEARD = {
        "Please review": "Please we view the pull request before the release on Wednesday.",
        "Ask Priya": "Ask pria to check the Kubernetes logs for the staging cluster.",
        "Send the summary": "Send the summary to Semir and set up a meeting on Thursday afternoon.",
    }

    def text(self, audio, *, final: bool = False, hotwords: str = "") -> str:
        """A take shorter than ten seconds is an accuracy sentence, heard in order; a
        longer one is the tuning passage. The pretend decoder cannot know which sentence
        was read, so it takes them in turn — the demo reads them in turn too."""
        from ..accuracy import SENTENCES
        from ..calibrate import PASSAGE
        from .. import SAMPLE_RATE

        if len(audio) >= 10 * SAMPLE_RATE:
            return PASSAGE
        said = SENTENCES[self._takes % len(SENTENCES)]
        self._takes += 1
        for start, heard in self.MISHEARD.items():
            if said.startswith(start):
                return heard
        return said

    _takes = 0

    def take_confidence(self):
        return -0.31


class FakeMic:
    def __init__(self) -> None:
        self.device_name = "Yeti Nano"
        self.pinned = None
        self.want = None

    def use(self, name):
        self.device_name = name or "Yeti Nano"
        self.want = name or None
        self.pinned = 1 if name else None
        return ""


class ReadingMic:
    """A microphone that hears a person reading: a quiet room, then speech, then quiet.

    For the Voice page's two listeners in the demo and the suite. Blocks arrive at the
    real rate, so the gate ends a take and the tuning minute passes the way they would.
    """

    def __init__(self, speech_sec: float = 2.5, lead_sec: float = 0.4, rate: float = 1.0) -> None:
        self.speech_sec, self.lead_sec, self.rate = speech_sec, lead_sec, rate
        self._t0 = None
        self._sent = 0
        self.device_name = "Yeti Nano"
        self.want = None

    def start(self) -> None:
        import time as _time

        self._t0 = _time.monotonic()
        self._sent = 0

    def stop(self) -> None:
        self._t0 = None

    def drain(self):
        import time as _time

        import numpy as _np

        from ..audio import BLOCK
        from .. import SAMPLE_RATE

        if self._t0 is None:
            return []
        due = int((_time.monotonic() - self._t0) * self.rate * SAMPLE_RATE / BLOCK)
        out = []
        rng = _np.random.default_rng(self._sent)
        while self._sent < due:
            t = self._sent * BLOCK / SAMPLE_RATE
            # Speech in bursts with short pauses, the way a paragraph is read.
            talking = self.lead_sec <= t < self.lead_sec + self.speech_sec \
                or (t > 3 and int(t) % 4 != 0 and t < 58)
            loud = 0.08 if talking else 0.0015
            out.append((rng.standard_normal(BLOCK) * loud).astype(_np.float32))
            self._sent += 1
        return out


class FakeSpeaker:
    def __init__(self) -> None:
        self.voice = None
        self.said: list[str] = []

    def use(self, name):
        self.voice = name
        return True

    def say(self, text):
        self.said.append(text)
        return True

    def stop(self):
        return True


class FakeSession:
    """What Flow Home reads and changes, with none of the machinery behind it."""

    def __init__(self, profile=None) -> None:
        self.profile = profile
        self.asr = FakeTranscriber()
        self.mic = FakeMic()
        self.speaker = FakeSpeaker()
        self.mode = DICTATE
        self.capturing = True
        self.hearing = False
        self.level_db = -48.0
        self.activity = None
        self.talking = False
        self.muted = False
        self.workspace = None
        self.provider = "claude"
        self.pastes = True
        self.auto_ask = True
        self.cli = None
        self.cli_model = ""
        self.cli_effort = "low"
        self.cli_timeout = 20.0
        #: What the session would have said in its bubble, for the suite to read.
        self.said: list[str] = []
        #: The kept notes, the real store: Wrap up renders them the real way.
        self.notes = Notes()
        #: The real history store over the demo's profile, or nothing.
        self.history = History(profile.path.parent / "history.jsonl", profile) \
            if profile is not None else NullHistory()
        self.conversation = new_id()
        self.exchanges: list[dict] = []
        self.asking = False
        self.reply = ""
        self.wrapped_to = ""
        self.target_app = "WindowsTerminal.exe"
        self._handed: str = ""
        #: How long the pretend CLI takes to answer.
        self.answer_sec = 1.6
        #: The live gate a tuning is applied to; only its two numbers are ever read.
        self.gate = SimpleNamespace(floor_db=-55.0, margin_db=10.0)
        self._posted: queue.SimpleQueue = queue.SimpleQueue()
        self._recent = [
            (RECENT_SAID, "claude, look at session.py and figure out why the decode worker "
                          "drops the last utterance"),
            (RECENT_ASKED, "Where does the pill decide it was a hold and not a tap?"),
            (RECENT_ANSWERED, "PILL_HOLD_SEC in flow/ui.py - 0.30 s, with a 4 px drag slop."),
        ]

    # -- the thread contract -------------------------------------------------

    def post(self, fn) -> None:
        self._posted.put(fn)

    def run_posted(self) -> None:
        while True:
            try:
                fn = self._posted.get_nowait()
            except queue.Empty:
                return
            fn()

    # -- what Home reads -------------------------------------------------------

    @property
    def recent(self):
        return list(reversed(self._recent))

    @property
    def send_words(self):
        if self.profile is None:
            return (SEND_WORD, SEND_ENTER_WORD)
        return (self.profile.send_word, self.profile.send_enter_word)

    def voices(self):
        from ..speak import Voice

        return [Voice("Microsoft Zira Desktop", "Female", "en-US"),
                Voice("en_GB-cori-high", "NotSet", "en-GB", engine="piper")]

    # -- what Home changes -------------------------------------------------------

    def _note(self, text: str) -> None:
        self.said.append(text)

    # -- History and Conversations ------------------------------------------------

    def delivered(self, text: str, problem: str = "", copied: bool = False) -> None:
        self._handed = text
        self.history.add(DICTATED, text, app=self.target_app, words=len(text.split()),
                         how="copied" if copied else "pasted", note=problem)

    @property
    def last_handed(self) -> str:
        newest = self.history.newest
        return self._handed or (newest["text"] if isinstance(newest, dict) else "")

    def ask(self, question: str) -> str:
        question = (question or "").strip()
        if not question:
            return "type a question first"
        if self.asking:
            return "still waiting on the last answer"
        entry = make_entry(ASKED, question, conv=self.conversation, ws=self.workspace,
                           via="typed")
        self.exchanges.append(entry)
        self.history.keep(entry)
        self.asking = True
        conv = self.conversation

        def answer() -> None:
            if conv != self.conversation:
                return
            reply = make_entry(ANSWERED, DEMO_ANSWER, conv=conv, cli="claude",
                               secs=self.answer_sec)
            self.exchanges.append(reply)
            self.history.keep(reply)
            self.reply = DEMO_ANSWER
            self.asking = False

        timer = threading.Timer(self.answer_sec, lambda: self.post(answer))
        timer.daemon = True
        timer.start()
        return ""

    def new_conversation(self) -> None:
        self.conversation = new_id()
        self.exchanges = []
        self.asking = False
        self.reply = ""

    def resume(self, conv: str, entries: list) -> str:
        if self.asking:
            return "still waiting on the last answer"
        self.conversation = conv
        self.exchanges = [dict(e) for e in entries]
        return ""

    def keep_note(self, text: str = "", question: str = "") -> bool:
        if not text:
            return False
        self.notes.add(text, question=question,
                       workspace=Path(self.workspace).name if self.workspace else "")
        return True

    def wrap_up(self, pill: bool = True) -> bool:
        held = self.notes.all
        if not held:
            return False
        self.reply = render_notes(held, workspace="")
        self.wrapped_to = ""
        self.notes.clear()
        return True

    def stop_speaking(self) -> bool:
        return True

    #: How many times something asked for the models to be loaded.
    warmed = 0

    def warm(self) -> None:
        self.warmed += 1

    def set_models(self, partial, final, device=None) -> bool:
        self.asr.swap(partial, final, device)
        if self.profile is not None:
            self.profile.partial_model, self.profile.final_model = partial, final
            self.profile.save()
        return True

    def set_microphone(self, name) -> bool:
        why = self.mic.use(name)
        if self.profile is not None:
            self.profile.mic_device = name
            self.profile.save()
        return not why

    def set_cli(self, cli) -> None:
        self.cli = cli

    def set_cli_model(self, model: str) -> None:
        self.cli_model = model.strip()
        if self.profile is not None and self.cli_model and \
                self.cli_model not in self.profile.cli_models:
            self.profile.cli_models = (*self.profile.cli_models, self.cli_model)

    def set_cli_effort(self, effort: str) -> None:
        self.cli_effort = effort

    def set_cli_timeout(self, seconds: float) -> None:
        from ..refine import sane_timeout

        self.cli_timeout = sane_timeout(seconds)

    def set_voice(self, name) -> bool:
        self.speaker.use(name)
        return True

    def toggle_speech(self) -> bool:
        self.muted = not self.muted
        return not self.muted

    def toggle_auto_ask(self) -> bool:
        self.auto_ask = not self.auto_ask
        return self.auto_ask

    def set_workspace(self, path) -> bool:
        self.workspace = path or None
        if self.profile is not None and path:
            self.profile.note_workspace(path)
        return True

    def toggle_mode(self, to=None) -> str:
        self.mode = to or (CONVERSE if self.mode == DICTATE else DICTATE)
        return self.mode

    mic_on_loan = ""

    def lend_mic(self, why: str) -> str:
        if self.mic_on_loan:
            return f"{self.mic_on_loan} - wait for it to finish"
        self.mic_on_loan = why
        return ""

    def return_mic(self) -> None:
        self.mic_on_loan = ""



def seed(session, kept: bool) -> None:
    """Something for the History and Conversations pages to show.

    The conversation on screen always — it lives in memory whatever the choice. With
    `kept`, history is chosen and a few days of pretend entries are written: dictation
    into three programs, a refined prompt, a set-aside "Thank you.", and a conversation
    from last week in another workspace.
    """
    now = time.time()
    q = make_entry(ASKED, "Where does the pill decide it was a hold and not a tap?",
                   at=now - 620, conv=session.conversation, ws=session.workspace,
                   via="voice")
    a = make_entry(ANSWERED, DEMO_ANSWER, at=now - 612, conv=session.conversation,
                   cli="claude", secs=4.2)
    session.exchanges.extend([q, a])
    if not kept or session.profile is None:
        return
    session.profile.history = KEEP
    session.profile.save()
    h = session.history
    for entry in (q, a):
        h.keep(entry)
    rows = [
        (DICTATED, "Thanks, I will send the updated figures by Friday.", 26.2,
         {"app": "OUTLOOK.EXE", "how": "pasted"}),
        (DICTATED, "Hey Marco, are we still good for the review on Tuesday afternoon, "
                   "and did you get a chance to look at the updated figures?", 3.1,
         {"app": "slack.exe", "how": "pasted"}),
        (SET_ASIDE, "Thank you.", 2.6, {"reason": "filler"}),
        (REFINED, "Strip every control from the push-to-talk pill in flow/ui.py - leave "
                  "the mic glyph and the meter. On release, inject the draft into the "
                  "window that held focus before the pill.", 2.2,
         {"app": "WindowsTerminal.exe", "how": "pasted", "cli": "claude", "secs": 6.1,
          "heard": "make the pill not show any controls just the mic and when i let go "
                   "it should paste in the window i was in before"}),
        (DICTATED, "claude, check the cube control logs for the staging pod, and tell me "
                   "why the decode worker drops the last utterance when I stop quickly.",
         1.4, {"app": "WindowsTerminal.exe", "how": "pasted"}),
    ]
    for kind, text, hours, fields in rows:
        if kind != SET_ASIDE:
            fields = {**fields, "words": len(text.split())}
        h.keep(make_entry(kind, text, at=now - hours * 3600, **fields))
    conv = new_id()
    h.keep(make_entry(ASKED, "Three names for a send word that nobody says by accident",
                      at=now - 8 * 86400, conv=conv, ws="D:\\dev\\acme", via="voice"))
    h.keep(make_entry(ANSWERED, "Boom, ship it, and send it - each measured against "
                                "hundreds of recordings so none fires by accident.",
                      at=now - 8 * 86400 + 5, conv=conv, cli="claude", secs=4.8))
    h.flush()


def build(profile_dir: Path | None = None, kept: bool = False):
    """A Home over a FakeSession, with its pump running. Returns (home, session).

    `kept` starts it with history chosen and a few days of pretend entries (`seed`);
    without it, the History page asks the question the way a first launch would.
    """
    from ..profile import Profile
    from . import Home

    folder = Path(profile_dir or tempfile.mkdtemp(prefix="flow-home-"))
    profile = Profile(folder / "profile.json")
    session = FakeSession(profile)
    seed(session, kept)

    def pump() -> None:
        while True:
            session.run_posted()
            time.sleep(0.03)

    threading.Thread(target=pump, daemon=True, name="demo-pump").start()
    home = Home(session, profile=profile, hotkeys=None, lite=False,
                lexicon_path=folder / "lexicon.txt", trace_path=folder / "diag.jsonl")
    home.design = "compact"
    home.mic_factory = ReadingMic
    return home, session


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m flow.home.demo", description=__doc__)
    ap.add_argument("--no-open", action="store_true", help="print the address only")
    ap.add_argument("--history", action="store_true",
                    help="start with history kept, and a few days of pretend entries")
    ap.add_argument("--first-run", action="store_true",
                    help="open at the first run's five steps, as a new profile does")
    args = ap.parse_args(argv)
    home, _session = build(kept=args.history)
    page = "start" if args.first_run else "home"
    url = home.url(page)
    print(url, flush=True)
    if not args.no_open:
        home.open(page)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        home.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
