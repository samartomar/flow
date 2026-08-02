"""What Flow is doing right now, and whether it can still hear.

Two things are pinned here. The first is a defect: the level meter is driven by
`Mic._level`, which the PortAudio callback writes on every block it receives — and it
knows nothing about the echo guard in `_pump_audio`. So while a converse-mode reply
played, the guard discarded every block *and the eighteen bars kept dancing to Flow's
own voice*, which is the pill's way of saying "I am hearing you" at the one moment it
was guaranteed not to be. Measured before the fix: 30 blocks discarded, meter at 83% of
full scale.

The second is the indicator itself. `Session.activity` is a single value read every
frame rather than an event, because a wait has no edges — it is a condition that holds
for a while — and the states it covers (a decode, a model load, a CLI call, a reply
playing) were previously invisible or, in the speaking case, actively misreported.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.asr import WhisperTranscriber  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.refine import Cli  # noqa: E402
from flow.session import CONVERSE, DEAF_DB, DICTATE, Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)

#: What the pill maps onto its eighteen bars. Duplicated from `flow.ui` on purpose:
#: importing it would pull tkinter into a headless test run.
DB_FLOOR, DB_CEIL = -58.0, -12.0


def bar_height(db: float) -> float:
    """0.0 is a flat line, 1.0 is a full-height bar."""
    return max(0.0, min(1.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))


class FakeMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        #: Loud, and it stays loud: a real mic keeps reporting the room even when
        #: nobody is reading its blocks.
        self.level_db = -20.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeAsr:
    loading = False

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return "" if not final else "how do I widen a column"


class SlowAsr(FakeAsr):
    """Blocks inside `text` so a decode can be observed while it is still running."""

    def __init__(self) -> None:
        self.release = False

    def text(self, audio, *, final=False, hotwords="") -> str:
        while not self.release:
            time.sleep(0.005)
        return "widen a column"


class FakeSpeaker:
    def __init__(self) -> None:
        self.speaking = False

    def say(self, text: str) -> bool:
        self.speaking = True
        return True

    def stop(self) -> None:
        self.speaking = False


def session(**kw) -> Session:
    return Session(asr=kw.pop("asr", None) or FakeAsr(), mic=FakeMic(), **kw)


class TestTheMeterDoesNotClaimToHear(unittest.TestCase):
    """The defect. The bars are the only thing on screen that answers "am I being
    heard", and while Flow talks the honest answer is no."""

    def test_the_level_is_the_microphone_when_nothing_is_playing(self):
        s = session(speaker=FakeSpeaker())
        self.assertEqual(s.level_db, -20.0)
        self.assertGreater(bar_height(s.level_db), 0.5)

    def test_the_level_reads_silent_while_a_reply_plays(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        sp.say("Yes, we can hear you.")
        self.assertEqual(s.level_db, DEAF_DB)
        self.assertEqual(bar_height(s.level_db), 0.0)

    def test_the_meter_agrees_with_the_blocks_actually_being_thrown_away(self):
        # The two halves of the same fact, which is what came apart: the guard was
        # already discarding audio and the meter was already animating to it.
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.start()
        sp.say("Yes, we can hear you.")
        s.mic._blocks.extend([LOUD] * 30)
        s.tick()
        self.assertEqual(s.echo_blocks, 30, "the guard did not discard anything")
        self.assertEqual(bar_height(s.level_db), 0.0,
                         "every block was discarded and the meter still moved")

    def test_the_meter_comes_back_when_the_reply_ends(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        sp.say("a long answer")
        sp.speaking = False
        self.assertEqual(s.level_db, -20.0)

    def test_a_session_with_no_speech_engine_always_hears(self):
        s = session()
        self.assertTrue(s.hearing)
        self.assertEqual(s.level_db, -20.0)


class TestWhatFlowIsDoing(unittest.TestCase):
    def test_nothing_to_report_when_idle(self):
        self.assertIsNone(session().activity)

    def test_nothing_to_report_for_a_held_draft(self):
        # Already said by the pill's colour and by the countdown on the Ask button. An
        # indicator that is always on is one nobody reads.
        s = session()
        s.draft.set("the deploy failed")
        s._set_state(State.DRAFT)
        self.assertIsNone(s.activity)

    def test_a_reply_playing_says_it_is_not_listening(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        sp.say("Word Error Rate.")
        act = s.activity
        self.assertIn("not listening", act.label)
        self.assertFalse(act.waiting, "a steady state should not animate")

    def test_speaking_outranks_everything_else(self):
        # It is the only one of these that means "stop talking" rather than "wait a
        # moment", so it has to win however busy Flow also is.
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s._set_state(State.ASKING)
        sp.say("Word Error Rate.")
        self.assertIn("not listening", s.activity.label)

    def test_a_question_with_the_cli_says_asking(self):
        s = session()
        s._set_state(State.ASKING)
        self.assertEqual(s.activity, ("asking", True))

    def test_a_rewrite_with_the_cli_says_refining(self):
        s = session()
        s._set_state(State.REFINING)
        self.assertEqual(s.activity, ("refining", True))

    def test_a_model_build_is_named_as_one(self):
        # A first decode of a tier is a model build with a decode behind it, and those
        # are about a second apart. Reporting both as "decoding" is how the first
        # utterance of a session came to look like the app had hung.
        asr = FakeAsr()
        asr.loading = True
        s = session(asr=asr)
        self.assertEqual(s.activity, ("loading the model", True))

    def test_the_model_build_outranks_the_decode_it_is_holding_up(self):
        asr = SlowAsr()
        asr.loading = True
        s = session(asr=asr)
        try:
            s.worker.submit_final(LOUD)
            self.assertTrue(self._until(lambda: s.worker.busy))
            self.assertEqual(s.activity.label, "loading the model")
        finally:
            asr.release = True
            s.close()

    def test_a_decode_in_flight_is_visible(self):
        asr = SlowAsr()
        s = session(asr=asr)
        try:
            s.worker.submit_final(LOUD)
            self.assertTrue(self._until(lambda: s.worker.busy))
            self.assertEqual(s.activity, ("decoding", True))
        finally:
            asr.release = True
            s.close()

    def test_a_decode_is_not_announced_while_the_user_is_mid_sentence(self):
        # Partials run continuously while the gate is open, so this would be lit
        # permanently and would say nothing. The bars carry that moment.
        asr = SlowAsr()
        s = session(asr=asr)
        try:
            s.worker.submit_partial(LOUD)
            self.assertTrue(self._until(lambda: s.worker.busy))
            s.gate.speaking = True
            self.assertIsNone(s.activity)
        finally:
            asr.release = True
            s.close()

    def test_every_indeterminate_wait_animates(self):
        s = session()
        for state in (State.ASKING, State.REFINING):
            s._set_state(state)
            self.assertTrue(s.activity.waiting, state)

    @staticmethod
    def _until(check, timeout: float = 2.0) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if check():
                return True
            time.sleep(0.005)
        return False


class TestTheWholeExchangeIsAccountedFor(unittest.TestCase):
    """No silent stretch: every step of a converse round trip names itself."""

    def test_asking_then_speaking_then_quiet(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode()
        s.draft.set("what does WER stand for")
        with mock.patch("flow.session.ask",
                        return_value=("Word Error Rate.", "codex")):
            s.send()
            self.assertEqual(s.activity.label, "asking")
            self.assertTrue(s.hearing, "asking is a wait, not a deafness")
            s.wait_idle(timeout=5.0)
        # The answer arrived and is being read aloud: the promise changes from "wait a
        # moment" to "stop talking", and the microphone really is shut.
        self.assertTrue(sp.speaking)
        self.assertFalse(s.hearing)
        self.assertIn("not listening", s.activity.label)
        sp.speaking = False
        self.assertIsNone(s.activity)


class TestTheModelReportsItsOwnLoad(unittest.TestCase):
    def test_a_fresh_transcriber_is_not_loading(self):
        self.assertFalse(WhisperTranscriber().loading)

    def test_loading_is_true_while_a_tier_is_built_and_false_after(self):
        # No model is downloaded here: the build is replaced, and what is under test is
        # the flag around it, which is what the UI reads.
        asr = WhisperTranscriber()
        seen = []

        class FakeModel:
            def __init__(self, *a, **kw):
                seen.append(asr.loading)

        with mock.patch.dict(
            sys.modules, {"faster_whisper": mock.Mock(WhisperModel=FakeModel)}
        ):
            asr.load(final=False)
        self.assertEqual(seen, [True], "the flag was not up during the build")
        self.assertFalse(asr.loading, "the flag never came down")
        self.assertTrue(asr.loaded)

    def test_the_flag_comes_down_even_if_the_build_fails(self):
        # A failed load must not leave the indicator claiming a load forever.
        asr = WhisperTranscriber()

        def boom(*a, **kw):
            raise RuntimeError("no such model")

        with mock.patch.dict(
            sys.modules, {"faster_whisper": mock.Mock(WhisperModel=boom)}
        ):
            with self.assertRaises(RuntimeError):
                asr.load(final=False)
        self.assertFalse(asr.loading)


class RecordingCanvas:
    """Enough of a Tk canvas to catch what `_draw` puts on it, without a window.

    The alternative — a real `Pill` — needs a desktop, and `test_resilience.py` already
    pays for the one case that genuinely does.
    """

    def __init__(self) -> None:
        self.texts: list[tuple[float, float, str]] = []

    def delete(self, *a, **kw) -> None: ...

    def create_polygon(self, *a, **kw) -> None: ...

    def create_oval(self, *a, **kw) -> None: ...

    def create_arc(self, *a, **kw) -> None: ...

    def create_line(self, *a, **kw) -> None: ...

    def create_rectangle(self, *a, **kw) -> None: ...

    def create_text(self, x, y, text="", **kw) -> None:
        self.texts.append((x, y, text))


CODEX = Cli("codex", ("codex", "exec"))
CLAUDE = Cli("claude", ("claude", "-p"))


class TestTheConverseMarkerNamesItsCli(unittest.TestCase):
    """The mode signal is the marker's presence; its text was spare capacity.

    Real `refine.Cli` instances rather than mocks, because `name` is reserved in Mock's
    constructor — item 11 shipped `<Mock name='claude.name' id=...>` into a note before
    a test caught it.
    """

    @staticmethod
    def _pill(mode=CONVERSE, pinned=None):
        import flow.ui as ui

        pill = ui.Pill.__new__(ui.Pill)
        pill.canvas = RecordingCanvas()
        pill._flash = 0
        pill.armed = True
        pill._clis = None
        pill.levels = [0.0] * 18
        pill.session = mock.Mock(mode=mode, state=State.IDLE, cli=pinned)
        return pill

    @classmethod
    def _draw(cls, mode=CONVERSE, clis=(CODEX,), pinned=None) -> list[str]:
        import flow.ui as ui

        pill = cls._pill(mode, pinned)
        with mock.patch.object(ui, "available", return_value=list(clis)):
            pill._draw()
        return [t for _, _, t in pill.canvas.texts]

    def test_the_marker_names_whichever_cli_resolved(self):
        # Both directions, so a constant cannot pass this by matching one of them.
        self.assertEqual(self._draw(clis=[CODEX]), ["codex"])
        self.assertEqual(self._draw(clis=[CLAUDE]), ["claude"])

    def test_a_pinned_cli_wins_over_the_preference_order(self):
        # `set_cli` exists so a wedged CLI is recoverable without a restart; the marker
        # would be lying if it kept naming the one the pin took Flow off.
        self.assertEqual(self._draw(clis=[CODEX, CLAUDE], pinned=CLAUDE), ["claude"])

    def test_with_no_cli_on_path_it_keeps_saying_ask(self):
        # Naming a provider that is not there is worse than naming the mode.
        self.assertEqual(self._draw(clis=[]), ["ASK"])

    def test_a_name_too_long_for_the_slot_falls_back_to_the_mode(self):
        # The baseline sits at y 33 and the level bars run to y 32 from x 40: a wider
        # token overlaps them. Refusing to draw it is the honest failure — a clipped
        # name reads as a different CLI.
        long = Cli("gemini-cli", ("gemini",))
        self.assertEqual(self._draw(clis=[long]), ["ASK"])

    def test_the_rule_holds_for_the_names_that_actually_ship(self):
        # The check above used an invented name, which proves the rule and not the
        # product. The adapter carries five entries now and two are wider than the slot.
        # Asked of every candidate rather than only the invocable ones, deliberately:
        # `verified` flips the day somebody runs the verification, and the marker has to
        # be right *before* that rather than a fix that follows it.
        from flow.refine import CANDIDATES, named

        self.assertEqual(self._draw(clis=[named("opencode")]), ["ASK"], "8 characters")
        self.assertEqual(self._draw(clis=[named("gemini")]), ["gemini"], "exactly 6")
        # `kiro-cli` is 8 too, and unlike opencode it is verified — so it was the first
        # time the pill declined to name a CLI that was genuinely about to answer. The
        # owner read `ASK` as Kiro not being captured, and the entry carries an alias now.
        self.assertEqual(self._draw(clis=[named("kiro-cli")]), ["kiro"], "the alias")
        for cli in CANDIDATES:
            with self.subTest(cli=cli.name):
                drawn = self._draw(clis=[cli])
                want = cli.marker or cli.name
                self.assertEqual(
                    drawn, [want if len(want) <= 6 else "ASK"],
                    "a shipped name that neither fits nor falls back",
                )


    def test_dictate_mode_still_draws_no_marker_at_all(self):
        self.assertEqual(self._draw(mode=DICTATE, clis=[CODEX]), [])

    def test_the_marker_keeps_its_place_and_its_size(self):
        import flow.ui as ui

        pill = self._pill()
        with mock.patch.object(ui, "available", return_value=[CODEX]):
            pill._draw()
        x, y, text = pill.canvas.texts[0]
        self.assertEqual((x, y), (22, ui.PILL_H - 7), "the slot moved")
        self.assertEqual(text, "codex")

    def test_the_path_is_walked_once_and_not_per_frame(self):
        # `available()` measures 10.2 ms on this machine — two PATH walks across every
        # PATHEXT entry, or 34% of the 30 ms frame `_draw` has to finish inside. The
        # marker is a name that does not change while the app runs; the lookup behind it
        # must not be paid 33 times a second for that.
        import flow.ui as ui

        pill = self._pill()
        with mock.patch.object(ui, "available", return_value=[CODEX]) as lookup:
            for _ in range(60):
                pill._draw()
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual([t for _, _, t in pill.canvas.texts][-1], "codex")

    def test_opening_the_menu_re_resolves_what_is_installed(self):
        # The one place a CLI can appear mid-session and then be selected is the menu,
        # and it was already paying for a lookup; the marker rides along on that rather
        # than polling for a change that happens once a year.
        import tkinter as tk

        import flow.ui as ui

        class FakeMenu:
            def __init__(self, *a, **kw): ...

            def add_command(self, **kw): ...

            def add_separator(self): ...

            def add_cascade(self, **kw): ...

            def tk_popup(self, *a): ...

            def grab_release(self): ...

        pill = self._pill()
        pill.session.speaker = None  # skip the voice cascade; not what this pins
        pill.session.profile = None  # nor the correction offers
        pill.bubble = mock.Mock()
        with mock.patch.object(ui, "available", return_value=[]):
            pill._draw()
        self.assertEqual([t for _, _, t in pill.canvas.texts], ["ASK"])
        with mock.patch.object(ui, "available", return_value=[CODEX, CLAUDE]), \
                mock.patch.object(tk, "Menu", FakeMenu), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0), \
                mock.patch.object(ui, "_user32"):
            pill._menu(mock.Mock(x_root=0, y_root=0))
        pill.canvas.texts.clear()
        pill._draw()
        self.assertEqual([t for _, _, t in pill.canvas.texts], ["codex"])


class TestTheMarkerMayCarryAShortNameForACliThatDoesNotFit(unittest.TestCase):
    """Item 15's 6-character wall is unchanged; what an entry may offer it is not.

    kiro-cli is why: the slot beside the level bars cannot hold 8 characters without
    overlapping them, so the pill drew `ASK` while kiro-cli was the CLI that would answer,
    and the owner read that as Kiro not being captured. The rule item 35 pinned at
    `opencode` is extended rather than rewritten — an alias where there is one, the name
    where it fits, `ASK` otherwise — and the fallback is asserted here in both of the ways
    it can still be reached.
    """

    #: Borrowed rather than rebuilt: a second pill fixture is a second thing to keep true.
    _draw = TestTheConverseMarkerNamesItsCli._draw

    def test_an_alias_is_drawn_instead_of_a_name_that_does_not_fit(self):
        self.assertEqual(self._draw(clis=[Cli("kiro-cli", ("kiro-cli",),
                                              marker="kiro")]), ["kiro"])

    def test_a_name_that_fits_is_still_the_name(self):
        # Both directions, so the alias branch cannot pass this by firing for everybody.
        self.assertEqual(self._draw(clis=[Cli("codex", ("codex",))]), ["codex"])

    def test_no_alias_still_means_the_fallback(self):
        self.assertEqual(self._draw(clis=[Cli("gemini-cli", ("gemini",))]), ["ASK"])

    def test_an_alias_that_does_not_fit_either_falls_back(self):
        # The bound is the slot, not the field. An alias is a shorter name, not a licence
        # to draw over the level bars.
        self.assertEqual(self._draw(clis=[Cli("whatever", ("whatever",),
                                              marker="verylong")]), ["ASK"])

    def test_every_shipped_alias_fits_the_slot(self):
        # Asserted over the whole table rather than over the one alias that exists today:
        # the next alias is where a seven-character one gets typed.
        import flow.ui as ui

        from flow.refine import CANDIDATES

        for cli in CANDIDATES:
            if cli.marker:
                with self.subTest(cli=cli.name):
                    self.assertLessEqual(len(cli.marker), ui.Pill.MARKER_MAX)

    def test_a_pinned_cli_draws_its_alias_too(self):
        # The pin is what makes a wedged CLI recoverable, and the marker exists to say
        # which CLI is about to answer. Both have to agree about kiro-cli.
        from flow.refine import named

        kiro = named("kiro-cli")
        self.assertEqual(self._draw(clis=[named("codex"), kiro], pinned=kiro), ["kiro"])


if __name__ == "__main__":
    unittest.main()
