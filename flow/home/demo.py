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
from ..session import CONVERSE, DICTATE, RECENT_ANSWERED, RECENT_ASKED, RECENT_SAID


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
        self.notes: list[str] = []
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
        self.notes.append(text)

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



def build(profile_dir: Path | None = None):
    """A Home over a FakeSession, with its pump running. Returns (home, session)."""
    from ..profile import Profile
    from . import Home

    folder = Path(profile_dir or tempfile.mkdtemp(prefix="flow-home-"))
    profile = Profile(folder / "profile.json")
    session = FakeSession(profile)

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
    args = ap.parse_args(argv)
    home, _session = build()
    url = home.url("home")
    print(url, flush=True)
    if not args.no_open:
        home.open("home")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        home.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
