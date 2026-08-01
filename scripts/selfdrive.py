"""Drive the whole app from synthesised speech and check what it actually did.

Every other harness here tests one layer. `command_bench` routes strings, `gate_bench`
gates audio, the unit tests drive the state machine with a fake transcriber. None of
them answers the question a user asks, which is *does the thing work*: speak, watch the
draft change, speak again, send.

This does. A Windows SAPI voice speaks each utterance to a WAV; the WAV is fed to the
real `Session` as microphone blocks, through the real gate, the real two-tier decoder,
the real router and the real apply. The assertions are on the draft text afterwards.

SAPI is not an accented speaker and this proves nothing about P1 or P3 — those need the
recordings. What it proves is that the wiring holds end to end, which is exactly what
kept breaking by hand: a chip whose label the grammar rejected, a mode with no way to
turn the voice on, a window that placed itself off the screen.

Usage:  uv run python scripts/selfdrive.py [--only NAME] [--keep]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import SAMPLE_RATE  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.session import (  # noqa: E402
    AUTO_ASK_SEC, CONVERSE, DICTATE, Session, State,
)

CACHE = Path(__file__).resolve().parent.parent / ".bench" / "selfdrive"

#: The message every correction scenario starts from, dictated rather than pasted in,
#: so the draft under test is one this pipeline actually produced.
OPENING = ("hi Priya, the deploy is scheduled for Tuesday afternoon. "
           "Sameer is writing the release notes.")


def synth(text: str, name: str) -> Path:
    """Speak `text` to a cached 16 kHz mono WAV."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.wav"
    if path.exists():
        return path
    safe = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
        "16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s.SetOutputToWaveFile('{path}', $f); "
        f"$s.Speak('{safe}'); $s.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True, capture_output=True,
    )
    return path


def blocks(path: Path, lead_ms: int = 400, tail_ms: int = 1400) -> list[np.ndarray]:
    """A WAV as microphone blocks, padded so the gate opens and then closes.

    The tail matters: the gate needs `hang_ms` of quiet to decide the utterance ended,
    and without it the session never commits a final. Real room noise rather than
    digital silence, because digital zeros are excluded from training the noise floor
    and would leave the gate calibrated on nothing.
    """
    with wave.open(str(path), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0
    rng = np.random.default_rng(abs(hash(path.name)) % (2**32))
    room = lambda n: rng.normal(0, 10 ** (-70 / 20), n).astype(np.float32)  # noqa: E731
    padded = np.concatenate([
        room(int(SAMPLE_RATE * lead_ms / 1000)),
        audio,
        room(int(SAMPLE_RATE * tail_ms / 1000)),
    ])
    n = len(padded) // BLOCK
    return [padded[i * BLOCK:(i + 1) * BLOCK] for i in range(n)]


class ScriptedMic:
    """Replays blocks on demand; the session cannot tell it from a real device."""

    def __init__(self) -> None:
        self._queue: list[np.ndarray] = []
        self.level_db = -70.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def say(self, text: str, name: str) -> None:
        self._queue.extend(blocks(synth(text, name)))

    def drain(self) -> list[np.ndarray]:
        out, self._queue = self._queue[:64], self._queue[64:]
        return out

    @property
    def empty(self) -> bool:
        return not self._queue


class Driver:
    """One session, driven by speech, with the real decoder behind it."""

    def __init__(self, converse: bool = False, speaker=None) -> None:
        self.mic = ScriptedMic()
        self.session = Session(mic=self.mic, speaker=speaker, profile=None)
        self.session.start()
        if converse:
            self.session.toggle_mode()

    def speak(self, text: str, name: str, timeout: float = 90.0) -> None:
        """Say one utterance and pump until the session has finished with it."""
        self.mic.say(text, name)
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.session.tick()
            if self.mic.empty and not self.session.worker.busy:
                if self.session.state in (State.REFINING, State.ASKING):
                    time.sleep(0.05)
                    continue
                if not self.session._utter:
                    time.sleep(0.15)
                    self.session.tick()
                    if not self.session.worker.busy:
                        return
            time.sleep(0.02)
        raise TimeoutError(f"session never settled after {text!r}")

    def notes(self) -> list[str]:
        return [e.text for e in self.session.events()]


# -- scenarios ---------------------------------------------------------------

def scenario_dictate(report) -> None:
    """Speech becomes a held draft, and a second utterance extends it."""
    d = Driver()
    d.speak(OPENING, "opening")
    report("dictation produces a draft", bool(d.session.draft.text),
           d.session.draft.text)
    before = d.session.draft.text
    d.speak("I attached the summary from the standup.", "second")
    report("a second utterance extends it",
           len(d.session.draft.text) > len(before), d.session.draft.text)


#: A draft with the defects the case commands exist to fix.
#:
#: Seeded rather than dictated, and the first run of this harness is why: Whisper
#: writes well-formed English, so a *dictated* opening comes back with "Samir" already
#: capitalised and "release notes" already lowercase. "capitalize Sameer" against it is
#: a correct no-op, and a test that calls that a failure is testing the transcriber's
#: manners rather than the command. The seeded text is what a real mis-transcription
#: looks like; the command itself still arrives as speech.
MALFORMED = ("hi priya, the deploy is scheduled for Tuesday afternoon. sameer is "
             "writing the RELEASE NOTES. tell me if Tuesday still works.")


def scenario_corrections(report) -> None:
    """Each correction shape, spoken, applied to a draft that needs it."""
    cases = [
        ("change every Tuesday to Wednesday", "repl_all",
         lambda t: "Tuesday" not in t and t.count("Wednesday") == 2),
        ("capitalize sameer", "cap", lambda t: "Sameer" in t),
        ("lowercase release notes", "lower", lambda t: "release notes" in t),
        ("delete the last sentence", "del_last",
         lambda t: "still works" not in t),
        ("insert draft before release notes", "ins",
         lambda t: "draft RELEASE NOTES" in t),
    ]
    for text, name, check in cases:
        d = Driver()
        d.session.draft.set(MALFORMED)
        start = d.session.draft.text
        d.speak(text, f"cmd_{name}")
        after = d.session.draft.text
        report(f"spoken: {text!r}", check(after) and after != start, after)


def scenario_undo(report) -> None:
    """Undo takes back the last change rather than the whole draft."""
    d = Driver()
    d.speak(OPENING, "opening")
    original = d.session.draft.text
    d.speak("delete the last sentence", "cmd_del_last")
    shortened = d.session.draft.text
    d.speak("undo that", "cmd_undo")
    report("undo restores the previous draft",
           d.session.draft.text == original and shortened != original,
           d.session.draft.text)


def scenario_rescue(report) -> None:
    """The button's own phrase, spoken, re-reads the last dictation as a command."""
    d = Driver()
    d.speak(OPENING, "opening")
    # Something that will be heard as dictation, then reclassified.
    d.speak("delete the last sentence", "cmd_del_last")
    d.speak("was a command", "cmd_rescue")
    report("'was a command' is not appended as text",
           "was a command" not in d.session.draft.text.lower(),
           d.session.draft.text)


def scenario_send(report) -> None:
    """Dictate mode hands the caller text; converse mode hands it nothing."""
    d = Driver()
    d.speak(OPENING, "opening")
    out = d.session.send()
    report("dictate send returns the draft to paste", bool(out), out[:60])

    c = Driver(converse=True)
    report("converse mode is announced on the session", c.session.mode == CONVERSE,
           c.session.mode)


def scenario_converse(report) -> None:
    """A spoken question reaches the agent CLI and the answer comes back."""
    spoken: list[str] = []

    class Recorder:
        """Records what was spoken, and models `speaking` because the session gates the
        microphone on it — a fake without it drives a Flow that can still hear itself.

        Deliberately goes quiet immediately: the harness feeds audio far faster than an
        engine speaks, and a fake that stayed "speaking" would swallow the follow-up
        this scenario is here to test.
        """

        speaking = False

        def say(self, text: str) -> bool:
            spoken.append(text)
            return True

        def stop(self) -> None: ...

    d = Driver(converse=True, speaker=Recorder())
    d.speak("what does the acronym WER stand for", "ask_wer")
    d.session.send()
    deadline = time.perf_counter() + 90.0
    while time.perf_counter() < deadline and d.session.state is State.ASKING:
        d.session.tick()
        time.sleep(0.05)
    report("the CLI answered", bool(d.session.reply), (d.session.reply or "")[:70])
    report("the answer was spoken", spoken == [d.session.reply],
           (spoken[0] if spoken else "")[:50])
    report("the exchange is in the thread",
           any(t.startswith("(reply)") for t in d.session.thread.turns),
           f"{len(d.session.thread.turns)} turns")


def scenario_followup(report) -> None:
    """A second spoken question inherits the first exchange.

    The claim P9 rests on: continuity is re-sent from the thread rather than held in a
    CLI process. If that works, a question with no subject in it still gets answered
    about the right subject.
    """
    d = Driver(converse=True)
    for text, name in (("what does the acronym WER stand for", "ask_wer"),
                       ("and what is a typical value for a good system", "ask_typ")):
        d.speak(text, name)
        d.session.send()
        deadline = time.perf_counter() + 90.0
        while time.perf_counter() < deadline and d.session.state is State.ASKING:
            d.session.tick()
            time.sleep(0.05)
    answer = (d.session.reply or "").lower()
    # The second question never says what it is about. An answer that mentions the
    # subject or a rate can only have come from the thread.
    report("the follow-up was answered in context",
           any(w in answer for w in ("wer", "word error", "%", "percent")),
           (d.session.reply or "")[:74])


def scenario_asking_ui(report) -> None:
    """The bubble stays up while the CLI is answering.

    Asking clears the draft, and the draft-empty event used to hide the bubble — so the
    ten seconds the CLI takes were spent looking at nothing at all.
    """
    from flow.ui import Pill

    class Dead:
        level_db = -70.0

        def start(self) -> None: ...

        def stop(self) -> None: ...

        @property
        def active(self) -> bool:
            return True

        def restart(self) -> None: ...

        def drain(self) -> list:
            return []

    class NoAsr:
        def load(self, final=None) -> None: ...

        def text(self, a, *, final=False, hotwords="") -> str:
            return ""

    session = Session(asr=NoAsr(), mic=Dead(), profile=None)
    pill = Pill(session, hotkeys=None)
    try:
        session.toggle_mode()
        session.draft.set("what does WER stand for")
        session._emit("draft", session.draft.text)  # set() alone emits nothing
        pill._frame()
        report("the bubble shows the question", pill.bubble._visible, "visible")
        # Send without letting the ask thread finish, so the wait is what is observed.
        session._set_state(State.ASKING)
        session._emit("draft", "")
        session._emit("note", "asking...")
        pill._frame()
        report("the bubble survives the draft clearing", pill.bubble._visible,
               f"note={pill.bubble._note!r}")
        session._emit("reply", "Word Error Rate.")
        pill._frame()
        report("the answer replaces it", pill.bubble._reply == "Word Error Rate.",
               pill.bubble._reply)
        session._emit("draft", "and a typical value")
        pill._frame()
        report("the answer stays while the next question is dictated",
               pill.bubble._reply == "Word Error Rate.", pill.bubble._reply)
    finally:
        pill.destroy()


def scenario_calibrate(report) -> None:
    """Calibration, driven by a spoken passage rather than by synthetic noise.

    The unit tests feed `measure` generated gaussians, which is the one input whose
    room/voice split is guaranteed to be clean. This is speech with the pauses real
    reading has in it.
    """
    from flow.calibrate import PASSAGE, apply, measure
    from flow.profile import Profile

    # Hands over the whole passage at once. ScriptedMic deliberately drips 64 blocks
    # per drain to imitate a real device, and `measure(seconds=0)` drains once — which
    # fed calibration 3 s of a 45 s reading and made it judge the room on a sentence.
    class WholeReading:
        def __init__(self, blocks_):
            self._b = blocks_

        def drain(self):
            out, self._b = self._b, []
            return out

    from flow.asr import WhisperTranscriber

    mic = WholeReading(blocks(synth(PASSAGE, "passage")))
    result = measure(mic, asr=WhisperTranscriber(), seconds=0.0)
    report("the reading is usable", result.usable, result.describe())
    report("room and voice are separated by a real margin",
           result.speech_db - result.floor_db > 15.0,
           f"gap {result.speech_db - result.floor_db:.1f} dB")
    report("this speaker's confidence was read", result.confidence is not None,
           str(result.confidence))
    report("it heard the passage",
           "deploy" in result.text.lower() or "migration" in result.text.lower(),
           result.text[:70])

    prof = Profile(CACHE / "selfdrive-profile.json")
    prof.record_calibration(result.floor_db, result.speech_db, result.confidence)
    gate = __import__("flow.audio", fromlist=["SpeechGate"]).SpeechGate()
    report("the profile drives a live gate", apply(prof, gate),
           f"floor {gate.floor_db:.1f} dB, margin {gate.margin_db:.1f} dB")


def scenario_learning(report) -> None:
    """A correction said twice becomes a decode bias (P8/P4).

    Once is deliberately not enough, so this has to say it twice — and the whole point
    is that the second time is what promotes it.
    """
    from flow.lexicon import NUL_PATH, Lexicon
    from flow.profile import Profile

    prof = Profile(CACHE / "selfdrive-learn.json")
    prof.pairs.clear()
    d = Driver()
    d.session.profile = prof
    for i in range(2):
        d.session.draft.set(MALFORMED)
        d.speak("change sameer to Samir", f"cmd_learn{i}")
    report("the pair was recorded from speech", bool(prof.pairs), dict(prof.pairs))
    report("saying it twice promotes it", prof.learned_terms(), prof.learned_terms())
    lex = Lexicon(NUL_PATH, learned=prof.learned_terms)
    report("it reaches the decoder as a hotword", bool(lex.hotwords()), lex.hotwords())


def scenario_window(report) -> None:
    """Both windows land wholly inside the desktop work area."""
    from flow.ui import Pill

    class Dead:
        level_db = -70.0

        def start(self) -> None: ...

        def stop(self) -> None: ...

        @property
        def active(self) -> bool:
            return True

        def restart(self) -> None: ...

        def drain(self) -> list:
            return []

    class NoAsr:
        def load(self, final=None) -> None: ...

        def text(self, a, *, final=False, hotwords="") -> str:
            return ""

    pill = Pill(Session(asr=NoAsr(), mic=Dead(), profile=None), hotkeys=None)
    try:
        left, top, right, bottom = pill.work
        report("the pill is inside the work area",
               left <= pill.x and pill.x + 152 <= right
               and top <= pill.y and pill.y + 40 <= bottom,
               f"pill ({pill.x},{pill.y}) in {pill.work}")
        pill.bubble.show("a draft long enough to make the bubble size itself properly")
        pill.update_idletasks()
        geo = pill.bubble.geometry()
        size, _, pos = geo.partition("+")
        bx, _, by = pos.partition("+")
        bw, _, bh = size.partition("x")
        inside = (left <= int(bx) and int(bx) + int(bw) <= right
                  and top <= int(by) and int(by) + int(bh) <= bottom)
        report("the bubble is inside the work area", inside, geo)
    finally:
        pill.destroy()


#: Scenarios that build a Tk root. Each needs its own process.
#:
#: Two `tk.Tk` roots in one interpreter end the run with "Tcl_AsyncDelete: async
#: handler deleted by the wrong thread" — an abort, not an exception, which killed the
#: process before stdout flushed and took every result line with it while still
#: reporting exit 0. The real app only ever has one root, so this is a property of the
#: harness rather than of the product, and the fix belongs here.
def scenario_chips(report) -> None:
    """Actually press the buttons.

    Every other harness reaches past the UI and calls `session.send()` directly, so the
    chips were bound in `ui.py` and clicked by nothing at all — the one part of the app
    a user touches first. This clicks them where they are drawn, through Tk, so a chip
    that is mislabelled, unbound, or off the edge of the bubble fails here.
    """
    from unittest import mock

    from flow.ui import Pill

    class Dead:
        level_db = -70.0

        def start(self) -> None: ...

        def stop(self) -> None: ...

        @property
        def active(self) -> bool:
            return True

        def restart(self) -> None: ...

        def drain(self) -> list:
            return []

    class NoAsr:
        def load(self, final=None) -> None: ...

        def text(self, a, *, final=False, hotwords="") -> str:
            return ""

    def click(pill, label) -> bool:
        """Press the chip where it is actually drawn. False if there is no such chip."""
        canvas = pill.bubble.canvas
        if not canvas.find_withtag(f"chip-{label}"):
            return False
        x1, y1, x2, y2 = canvas.bbox(f"chip-{label}")
        canvas.event_generate("<Button-1>", x=int((x1 + x2) / 2), y=int((y1 + y2) / 2))
        pill.update()
        return True

    pasted: list[str] = []
    session = Session(asr=NoAsr(), mic=Dead(), profile=None)
    pill = Pill(session, on_send=pasted.append, hotkeys=None)
    try:
        session.toggle_mode()
        session.draft.set("can you hear me")
        pill.bubble.show(session.draft.text)
        pill.update()

        report("converse mode offers Ask, not Send",
               bool(pill.bubble.canvas.find_withtag("chip-Ask"))
               and not pill.bubble.canvas.find_withtag("chip-Send"),
               f"mode={session.mode}")

        # The bubble is 380 px wide and the chips are laid out left to right; a chip
        # that runs off the end is drawn but unreachable.
        edges = []
        for label in ("Refine", "Continue", "Ask"):
            if pill.bubble.canvas.find_withtag(f"chip-{label}"):
                edges.append(pill.bubble.canvas.bbox(f"chip-{label}")[2])
        report("every chip is inside the bubble", edges and max(edges) <= 380,
               f"rightmost edge {max(edges) if edges else '?'} of 380")

        with mock.patch("flow.session.ask",
                        return_value=("Yes, I can hear you.", "codex")):
            report("the Ask chip was clickable", click(pill, "Ask"))
            report("clicking Ask put the question to the CLI",
                   session.state is State.ASKING, session.state.value)
            report("clicking Ask pasted nothing", pasted == [], str(pasted))
            deadline = time.perf_counter() + 20.0
            while time.perf_counter() < deadline and not session.reply:
                session.pump_results()
                pill.update()
            report("the answer came back", session.reply == "Yes, I can hear you.",
                   session.reply)

        session.draft.set("some words")
        pill.bubble.show(session.draft.text)
        pill.update()
        click(pill, "Refine")
        report("the Refine chip arms the next utterance",
               session.force_next == "edit", str(session.force_next))
        click(pill, "Refine")
        report("pressing it again disarms it", session.force_next is None,
               str(session.force_next))

        session.toggle_mode()
        pill.bubble.show(session.draft.text)
        pill.update()
        report("dictate mode offers Send, not Ask",
               bool(pill.bubble.canvas.find_withtag("chip-Send"))
               and not pill.bubble.canvas.find_withtag("chip-Ask"),
               f"mode={session.mode}")
        click(pill, "Send")
        report("clicking Send handed the draft over", pasted == ["some words"],
               str(pasted))

        # P9 auto-ask: the countdown has to be on the button, and it has to fire.
        session.toggle_mode()
        session.draft.set("what is the time")
        session._after_draft_change()
        pill._frame()
        label = pill.bubble.canvas.itemcget(
            pill.bubble.canvas.find_withtag("chip-Ask")[1], "text"
        )
        report("the Ask button shows the countdown", label.startswith("Ask ")
               and label.endswith("s"), label)
        click(pill, "Refine")
        report("a chip press buys the time back",
               session.auto_ask_in > AUTO_ASK_SEC - 1.0,
               f"{session.auto_ask_in:.1f}s left of {AUTO_ASK_SEC:.0f}")
        with mock.patch("flow.session.ask", return_value=("Half past four.", "codex")):
            session._settled_at -= AUTO_ASK_SEC + 0.1
            session.tick()
            report("the pause asked it without a press",
                   session.state is State.ASKING, session.state.value)
            report("nothing was pasted by the pause", pasted == ["some words"],
                   str(pasted))
    finally:
        pill.destroy()


TK_SCENARIOS = {"asking_ui", "window", "chips"}

SCENARIOS = {
    "dictate": scenario_dictate,
    "corrections": scenario_corrections,
    "undo": scenario_undo,
    "rescue": scenario_rescue,
    "send": scenario_send,
    "converse": scenario_converse,
    "followup": scenario_followup,
    "asking_ui": scenario_asking_ui,
    "chips": scenario_chips,
    "calibrate": scenario_calibrate,
    "learning": scenario_learning,
    "window": scenario_window,
}


def _run_isolated(name: str, report) -> None:
    """Run one scenario in a fresh interpreter and replay its verdicts."""
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--only", name],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    seen = False
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        for word, ok in (("PASS ", True), ("FAIL ", False)):
            if stripped.startswith(word):
                report(stripped[len(word):].strip(), ok)
                seen = True
                break
    if not seen:
        report(f"{name} produced no verdicts", False,
               (proc.stderr or proc.stdout or "").strip()[:78])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="run one scenario by name")
    args = ap.parse_args()

    results: list[tuple[bool, str, str]] = []

    def report(what: str, ok: bool, detail: str = "") -> None:
        results.append((ok, what, str(detail).replace(chr(10), " ")[:78]))
        # Flushed: a run takes minutes, and Python block-buffers stdout when it is
        # redirected, so an unflushed harness looks identical to a hung one.
        print(f"  {'PASS' if ok else 'FAIL'}  {what}", flush=True)
        if detail:
            print(f"        {str(detail).replace(chr(10), ' ')[:78]}", flush=True)

    names = [args.only] if args.only else list(SCENARIOS)
    for name in names:
        fn = SCENARIOS.get(name)
        if fn is None:
            print(f"no such scenario: {name}", file=sys.stderr)
            raise SystemExit(2)
        print(f"\n== {name}", flush=True)
        if name in TK_SCENARIOS and args.only is None:
            _run_isolated(name, report)
            continue
        try:
            fn(report)
        except Exception as exc:  # a scenario that dies is a failure, not a crash
            report(f"{name} raised", False, f"{type(exc).__name__}: {exc}")

    bad = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    for _, what, detail in bad:
        print(f"  FAILED  {what}\n          {detail}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
