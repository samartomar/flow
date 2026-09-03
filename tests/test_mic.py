"""The mic view: two frames, and nothing on either but what the gesture needs.

At rest the row is the focused app's name and the mic glyph. While the chord is held it
is the level bars and nothing else, in a box of the same width. Modelled on
`test_compact.py`, which adds widths up against the smallest layout — the same job here,
one layout smaller and two frames deep.

What is pinned is the four constraints the view was settled under, because each of them
is a promise a later change could break while looking reasonable in isolation:

* **It is a view, not a mode.** `flow/session.py` does not know it exists and emits
  exactly the events it emits without it; the pill draws fewer of them. Asserted twice —
  against the source, and against a scripted drain whose session-side calls must be
  identical with the view on and off.
* **A refusal is never silent.** With no panels there is nowhere for a note to land, so
  a note grows the full pill back for as long as it is up. This is the one that had to
  be right before anything visual, and the one a change to `Bubble.note` would break
  without failing anything else.
* **Purely additive.** One checkbutton, and only in push-to-talk.
* **Placement is free**, because there is no stack to fit — so an (x, y), persisted, and
  clamped to the work area on the way out rather than trusted.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui as ui  # noqa: E402
from flow.profile import Profile  # noqa: E402
from flow.session import DICTATE, State  # noqa: E402
from test_menu import Menu  # noqa: E402
from test_pill import Canvas, pill  # noqa: E402

FOUR = [("Refine", "Refine", None), ("Continue", "Continue", None),
        ("Edit", "Edit", None), ("Was a command", "Was a command", None)]


def mic_pill(*, on=True, gesture="hold", app="Code.exe", marks=(), visible=False,
             state=State.IDLE, talking=False, **attrs):
    """A pill in the mic view, built the way `test_pill` builds one.

    The chord is a live `Chord` and not a flag, because `push_to_talk` reads the gesture
    off the object `_gesture_menu` writes to — a switch made while Flow is running has to
    take the view away with it, and reading a copy would pass this test and not that one.
    """
    p = pill(state, mode=DICTATE, _flash=0, _tint=0.0,
             _ptt_since=1.0 if talking else None, _press_talking=False, **attrs)
    p._docked_w = ui.MIC_W
    p.session.target_app = app
    p.hotkeys = mock.Mock(chord=mock.Mock(gesture=gesture))
    p.mic_view_on = on
    p._mic_at = None
    p.bubble = SimpleNamespace(_visible=visible, _marks=list(marks))
    return p


class TestTheRowFitsWhatItDraws(unittest.TestCase):
    """`test_compact.py`'s arithmetic, at both of this view's layouts."""

    def test_the_width_is_the_meter_and_pad_either_side(self):
        # Written out rather than re-derived from the constant, so it is checked against
        # its own description instead of against itself.
        self.assertEqual(ui.MIC_W, ui.PAD + ui.METER_W + ui.PAD)

    def test_and_the_resting_frame_fits_that_same_width_exactly(self):
        # The name slot, the glyph and `PAD` either side. The two frames agreeing is
        # what makes this one box with two things drawn in it rather than a row that
        # resizes on every utterance — so it is asserted, not left to arithmetic that
        # happened to work out once.
        self.assertEqual(
            ui.PAD + ui.MIC_NAME_W + ui.APP_SLOT_GAP + 2 * ui.MIC_GLYPH_R + ui.PAD,
            ui.MIC_W)

    def test_the_glyph_and_the_last_bar_both_land_inside_it(self):
        self.assertLessEqual(ui.MIC_CX + ui.MIC_GLYPH_R, ui.MIC_W - ui.PAD)
        self.assertLessEqual(ui.PAD + ui.METER_W, ui.MIC_W - ui.PAD)

    def test_the_mic_glyph_clears_the_name(self):
        self.assertGreaterEqual(ui.MIC_CX - ui.MIC_GLYPH_R, ui.PAD + ui.MIC_NAME_W)

    def test_the_name_slot_is_at_least_as_wide_as_the_full_rows(self):
        # The full row fits `APP_NAME_CHARS` in `APP_SLOT_W` with marks and icons
        # competing for the same line. Here nothing competes, so the slot is not
        # allowed to be the narrower of the two.
        self.assertGreaterEqual(ui.MIC_NAME_W, ui.APP_SLOT_W)

    def test_it_is_narrower_than_the_narrowest_panel_by_a_wide_margin(self):
        # The whole claim of the view: this is not a small pill, it is a different one.
        self.assertLess(ui.MIC_W, min(ui.PANEL_WIDTHS.values()) // 4)

    def test_the_pill_asks_for_that_width_only_while_the_view_is_up(self):
        p = mic_pill()
        self.assertEqual(p.pill_w, ui.MIC_W)
        p.mic_view_on = False
        self.assertEqual(p.pill_w, ui.BUBBLE_W)

    def test_the_press_does_not_resize_the_row(self):
        # The frame that changed on 2026-08-09 was a *width*, and it moved every control
        # on the row under a reaching hand. Nothing here moves: the press swaps what is
        # inside a box that stays put.
        p = mic_pill(talking=False)
        resting = p.pill_w
        p._ptt_since = 1.0
        self.assertEqual(p.pill_w, resting)


class TestTheViewDrawsNothingElse(unittest.TestCase):
    def test_no_chip_no_mark_no_icon_gets_a_hit_region(self):
        # Every control on the full row binds a tag: the three icons, and one per mark.
        # Nothing on this row is clickable, so nothing binds — the same assertion as
        # "there are no controls", made against what the canvas received rather than
        # against a list of names somebody has to keep current.
        p = mic_pill(marks=FOUR)
        p._draw()
        self.assertEqual(p.canvas.bindings, [])

    def test_the_only_text_is_the_app_name(self):
        p = mic_pill(app="claude.exe")
        p._draw()
        self.assertEqual([t for _x, _y, t, _f in p.canvas.texts], ["Claude"])

    def test_the_name_is_the_whole_word_and_not_an_initial(self):
        # `C` is Code, Chrome, Claude and cmd — four answers to the one question the
        # slot exists to settle, which is where these words are about to land.
        p = mic_pill(app="Code.exe")
        p._draw()
        self.assertEqual([t for _x, _y, t, _f in p.canvas.texts], ["Code"])

    def test_a_long_name_is_truncated_by_the_rule_the_full_row_uses(self):
        p = mic_pill(app="WindowsTerminal.exe")
        p._draw()
        drawn = [t for _x, _y, t, _f in p.canvas.texts][0]
        self.assertEqual(drawn, ui.app_label("WindowsTerminal.exe"))
        self.assertLessEqual(len(drawn), ui.APP_NAME_CHARS)

    def test_no_bar_label_in_either_frame(self):
        # `NO INPUT` and the rest live in a slot neither frame reserves. A row that drew
        # one would be `LABEL_SLOT_W` wider than it has and would clip it.
        for talking in (False, True):
            with self.subTest(talking=talking):
                p = mic_pill(armed=False, talking=talking)
                p._draw()
                self.assertNotIn(ui.LABEL_OFF,
                                 [t for _x, _y, t, _f in p.canvas.texts])

    def test_the_marks_the_bubble_publishes_are_not_drawn(self):
        with_marks = mic_pill(marks=FOUR)
        with_marks._draw()
        without = mic_pill(marks=())
        without._draw()
        self.assertEqual(with_marks.canvas.rects, without.canvas.rects)
        self.assertEqual(with_marks.canvas.polys, without.canvas.polys)

    def test_the_initial_is_absent_when_there_is_no_window_to_name(self):
        p = mic_pill(app="")
        p._draw()
        self.assertEqual(p.canvas.texts, [])

    def test_the_waiting_dots_are_drawn_in_neither_frame(self):
        # On the full row they stand in for the meter while a CLI is out. Here there is
        # no resting meter to stand in for, and the mic glyph already carries `accent` —
        # the same state, said by the one thing on the row rather than by a second.
        for talking in (False, True):
            with self.subTest(talking=talking):
                p = mic_pill(state=State.REFINING, talking=talking)
                p._dots_frame = 0
                p._draw()
                self.assertEqual(len(p.canvas.ovals), 0 if talking else 1)


class TestTheTwoFrames(unittest.TestCase):
    """At rest: the initial and the mic. Held: the bars. Never both, never neither."""

    @staticmethod
    def bars(p):
        """The meter's own rectangles, told from the capsule chrome's by their width.

        A bar is `BAR_W` wide by construction and the chrome is the row; nothing else on
        either frame is a rectangle at all.
        """
        return sorted(r for r in p.canvas.rects if r[2] - r[0] == ui.BAR_W)

    def test_at_rest_there_is_no_meter(self):
        # A flat meter under a mic is a control's worth of pixels reporting a level
        # nobody is producing — which is the thing this view exists to not draw.
        p = mic_pill(talking=False)
        p._meter_level = 0.0
        p._draw()
        self.assertEqual(self.bars(p), [])

    def test_at_rest_the_name_and_the_mic_are_both_there(self):
        p = mic_pill(talking=False, app="Code.exe")
        p._draw()
        self.assertEqual([t for _x, _y, t, _f in p.canvas.texts], ["Code"])
        self.assertEqual(len(p.canvas.arcs), 1)   # the capsule's shoulder
        self.assertEqual(len(p.canvas.ovals), 1)  # the capsule
        self.assertTrue(p.canvas.lines)           # the stand

    def test_while_held_there_is_nothing_but_the_bars(self):
        p = mic_pill(talking=True, app="Code.exe")
        p._meter_level = 0.6
        p._draw()
        self.assertEqual(p.canvas.texts, [])
        self.assertEqual(p.canvas.arcs, [])
        self.assertEqual(p.canvas.ovals, [])
        # The row's own chrome is a rounded polygon too, so it is measured from the
        # frame that draws nothing else rather than assumed to be a particular count.
        rest = mic_pill(talking=False)
        rest._draw()
        chrome = len(rest.canvas.polys)
        self.assertEqual(len(self.bars(p)) + len(p.canvas.polys) - chrome, ui.BARS)

    def test_the_bars_start_at_the_pad_and_end_inside_the_row(self):
        # `PAD`, not `METER_X`: that offset exists to clear a mic glyph this frame does
        # not draw, and leaving it in would be 30 px of air at the left of a 90 px row.
        p = mic_pill(talking=True)
        p._meter_level = 0.0
        p._draw()
        left = min(r[0] for r in self.bars(p))
        right = max(r[2] for r in self.bars(p))
        self.assertEqual(left, ui.PAD)
        self.assertLessEqual(right, ui.MIC_W - ui.PAD)

    def test_the_level_moves_the_bars_because_that_is_the_point(self):
        quiet, loud = mic_pill(talking=True), mic_pill(talking=True)
        loud._meter_level = 0.9
        quiet._draw()
        loud._draw()
        self.assertNotEqual(quiet.canvas.rects, loud.canvas.rects)

    def test_a_press_and_hold_on_the_pill_is_the_same_gesture(self):
        # The pill carries the hold too (`PILL_HOLD_SEC`), and it is the same utterance,
        # so it gets the same frame — the alternative is a meter that appears for one of
        # the two ways of starting to speak.
        p = mic_pill(talking=False)
        p._press_talking = True
        self.assertTrue(p.mic_talking)

    def test_the_release_falls_back_even_while_the_decode_is_still_running(self):
        # `_ptt_wait` is the decode after the key came up. Nothing is being captured
        # then, so a meter left up is the same false "hearing you" `_flatten` kills —
        # and the ask was that the release falls straight back to the resting frame.
        p = mic_pill(talking=True)
        p._ptt_since = None
        p._ptt_wait = 1.0
        self.assertFalse(p.mic_talking)
        p._draw()
        self.assertEqual([t for _x, _y, t, _f in p.canvas.texts], ["Code"])

    def test_the_frame_change_alone_forces_a_repaint(self):
        # Same level, same colour, same app name — the reads `_draw_key` is otherwise
        # built from. Without the frame in the key, the press draws the resting row at
        # the meter's width.
        p = mic_pill(talking=False)
        p._draw()
        p._ptt_since = 1.0
        self.assertNotEqual(p._draw_key(), p._drawn_key)


class TestTheNameFitsTheSlotItIsDrawnIn(unittest.TestCase):
    """Measured against the real font, because that is what found this.

    Every other test here drives `_draw` against a recording canvas, which proves what
    was asked of Tk and nothing about what Tk did with it. A rendered run put
    `WindowsTe…` straight through the mic glyph: `app_label` cuts at `APP_NAME_CHARS`
    *characters*, and ten characters is 25 px of `Code` and 80 px of capital Ms in a
    proportional font. The full row has the same overrun and never shows it, because the
    next thing on that line is 24 px further away.
    """

    #: Real names, plus the two that are only reachable by measuring: the widest ten
    #: characters the font has, and the one that sent this back.
    NAMES = ("claude.exe", "Code.exe", "WindowsTerminal.exe", "explorer.exe",
             "chrome.exe", "notepad.exe", "cmd.exe", "MMMMMMMMMMMM.exe",
             "WWWWWWWWWWWW.exe")

    def setUp(self) -> None:
        import tkinter as tkinter_
        try:
            self.root = tkinter_.Tk()
        except Exception as exc:  # pragma: no cover - headless CI
            self.skipTest(f"no desktop: {exc}")
        self.root.withdraw()

    def tearDown(self) -> None:
        self.root.destroy()

    def font(self):
        import tkinter.font as tkfont
        return tkfont.Font(root=self.root, font=ui.FONT_NOTE)

    def fit(self, process: str) -> str:
        return ui.Pill._fit_note(self.root, ui.app_label(process), ui.MIC_NAME_W)

    def test_every_name_measures_inside_the_slot(self):
        font = self.font()
        for process in self.NAMES:
            with self.subTest(process=process):
                self.assertLessEqual(font.measure(self.fit(process)), ui.MIC_NAME_W)

    def test_and_the_cut_name_therefore_clears_the_mic_glyph(self):
        font = self.font()
        for process in self.NAMES:
            with self.subTest(process=process):
                right = ui.PAD + font.measure(self.fit(process))
                self.assertLessEqual(right, ui.MIC_CX - ui.MIC_GLYPH_R)

    def test_the_test_would_fail_without_the_cut(self):
        # The guard against a green test: `app_label` alone overruns, so this class is
        # measuring something that was actually wrong rather than restating the fix.
        font = self.font()
        self.assertGreater(font.measure(ui.app_label("WindowsTerminal.exe")),
                           ui.MIC_NAME_W)

    def test_a_name_that_already_fits_is_left_alone(self):
        # The cut must not be a haircut everything gets. `Claude` is 33 px in a 50 px
        # slot and has to come back exactly as it went in, ellipsis-free.
        for process in ("claude.exe", "Code.exe", "cmd.exe"):
            with self.subTest(process=process):
                self.assertEqual(self.fit(process), ui.app_label(process))

    def test_the_full_row_gets_the_same_cut(self):
        # Not a mic-view bug. The same name printed through the full row's mic glyph —
        # 69 px from x=10 against an arc starting at 61 — and was written off here as an
        # overrun that row never shows. A screenshot of Windows Terminal settled it.
        font = self.font()
        mic_arc_left = ui.METER_X - 12 + ui.APP_SLOT_W + ui.APP_SLOT_GAP - 7
        for process in self.NAMES:
            with self.subTest(process=process):
                cut = ui.Pill._fit_note(self.root, ui.app_label(process), ui.APP_SLOT_W)
                self.assertLessEqual(ui.PAD + font.measure(cut), mic_arc_left)

    def test_and_the_full_row_would_have_failed_that(self):
        font = self.font()
        mic_arc_left = ui.METER_X - 12 + ui.APP_SLOT_W + ui.APP_SLOT_GAP - 7
        uncut = ui.PAD + font.measure(ui.app_label("WindowsTerminal.exe"))
        self.assertGreater(uncut, mic_arc_left)

    def test_what_is_cut_keeps_its_head_and_says_so(self):
        # An application is recognised by its head — the rule `app_label` states — and
        # the ellipsis is what marks the difference between a cut name and a short one.
        cut = self.fit("WindowsTerminal.exe")
        self.assertTrue(cut.startswith("Wind"))
        self.assertTrue(cut.endswith("…"))


class TestTheFitIsCheapEnoughForTheFrameLoop(unittest.TestCase):
    """`_draw` may not build a font object per frame — the rule `LABEL_ADV` exists for."""

    def test_the_answer_is_memoised_per_name(self):
        p = mic_pill()
        p._note_font = SimpleNamespace(measure=mock.Mock(return_value=10))
        for _ in range(30):
            p._fit_note("Claude", ui.MIC_NAME_W)
        self.assertEqual(p._note_font.measure.call_count, 1)

    def test_a_second_name_gets_its_own_entry_rather_than_the_first_ones(self):
        p = mic_pill()
        p._note_font = SimpleNamespace(measure=mock.Mock(return_value=10))
        self.assertEqual(p._fit_note("Claude", ui.MIC_NAME_W), "Claude")
        self.assertEqual(p._fit_note("Code", ui.MIC_NAME_W), "Code")

    def test_no_interpreter_costs_the_cut_and_not_the_name(self):
        # A fixture built with `__new__`, or a font Tk will not resolve. The name is
        # already capped at `APP_NAME_CHARS`, so drawing it uncut is a cosmetic overrun
        # — and drawing nothing would lose the one thing the resting frame is for.
        p = mic_pill()
        p._note_font = SimpleNamespace(measure=mock.Mock(side_effect=RuntimeError))
        self.assertEqual(p._fit_note("WindowsTe…", ui.MIC_NAME_W), "WindowsTe…")

    def test_an_empty_name_is_empty_and_measures_nothing(self):
        p = mic_pill()
        p._note_font = SimpleNamespace(measure=mock.Mock(side_effect=AssertionError))
        self.assertEqual(p._fit_note("", ui.MIC_NAME_W), "")


class TestTheCheckbuttonIsOfferedOnlyInPushToTalk(Menu):
    LABEL = "Mic view - just the mic and the level, no controls"

    def settings(self, **kw):
        return self.build(self.profile(), **kw).cascades["Settings"]

    def test_it_is_there_in_push_to_talk(self):
        ticks = [label for label, _v in self.settings(gesture="hold").checks]
        self.assertIn(self.LABEL, ticks)

    def test_it_is_absent_in_toggle(self):
        # Absent rather than disabled: a toggle has no release to paste on, so hiding
        # its controls is an option that makes Flow worse and cannot say so from a label.
        settings = self.settings(gesture="toggle")
        self.assertNotIn(self.LABEL, [label for label, _v in settings.checks])
        self.assertNotIn(self.LABEL, settings.commands)

    def test_it_is_absent_when_there_is_no_chord_at_all(self):
        settings = self.settings(gesture=None)
        self.assertNotIn(self.LABEL, [label for label, _v in settings.checks])

    def test_it_is_one_row_and_not_a_cascade(self):
        # Purely additive means exactly this: one `add_checkbutton`, no page.
        settings = self.settings(gesture="hold")
        self.assertNotIn("Mic view", settings.cascades)
        self.assertEqual(
            1, sum(1 for label, _v in settings.checks if label == self.LABEL))

    def test_the_tick_reads_the_setting(self):
        for on in (False, True):
            with self.subTest(on=on):
                settings = self.settings(gesture="hold", mic=on)
                self.assertEqual(dict(settings.checks)[self.LABEL].get(), on)

    def test_choosing_it_writes_the_profile(self):
        profile = self.profile()
        settings = self.build(profile, gesture="hold").cascades["Settings"]
        dict(settings.checks)[self.LABEL].set(True)
        settings.commands[self.LABEL]()
        self.assertTrue(profile.mic)
        again = Profile(profile.path)
        again.load()
        self.assertTrue(again.mic)


class Stub(SimpleNamespace):
    """A bubble that is real where the test is about the real code.

    `Bubble` is a `tk.Frame` and cannot be built without a desktop, so the two methods
    under test are called against this instead. Everything they touch is here, and
    `_render` is counted rather than faked away — a note that sets the fields and never
    paints is the same silence as one that was dropped.
    """

    def __init__(self, pill, **kw) -> None:
        super().__init__(pill=pill, _visible=False, _note="", _note_undo=False,
                         _for_activity=False, _for_note=None, _text="", _partial="",
                         _sent="", _frame_key=None, _act=None, _dot=0, renders=0, **kw)

    def _render(self) -> None:
        self.renders += 1

    def show(self, text: str) -> None:
        """What the draft route calls. Recorded, because the assertion that the view
        draws fewer events is exactly the assertion that this was not reached."""
        self._visible, self._text = True, text

    def show_partial(self, text: str) -> None:
        self._visible, self._partial = True, text

    #: `Bubble.hide` reaches these two on its way out. Stubbed rather than routed around,
    #: so the real `hide` is what runs — the fields it clears are the assertion.
    def place_forget(self) -> None: ...

    def reposition(self) -> None: ...

    _editor = None
    _placed_band = None
    showing_sent = False

    hide = ui.Bubble.hide
    surface = ui.Bubble.surface
    note = ui.Bubble.note
    tick_note = ui.Bubble.tick_note
    tick_activity = ui.Bubble.tick_activity


class TestANoteGrowsTheFullPillBack(unittest.TestCase):
    """The one hard part. With no panels there is nowhere for a note to land."""

    def bubble(self, **kw):
        p = mic_pill(**kw)
        p._sync_shell = mock.Mock()
        p.bubble = Stub(p)
        return p, p.bubble

    def test_a_note_that_would_have_been_dropped_is_shown(self):
        # On the full row a note with no draft behind it is dropped, and that is right:
        # `surface` is the door for lines that must be seen regardless. Under this view
        # there is never a draft, so that door is the only one, and dropping would make
        # this the one place in Flow where a refusal is silent.
        p, b = self.bubble()
        b.note("refine came back with commentary")
        self.assertTrue(b._visible)
        self.assertEqual(b._note, "refine came back with commentary")
        self.assertEqual(b.renders, 1)

    def test_and_the_pill_is_the_full_one_again_on_that_frame(self):
        p, b = self.bubble()
        self.assertTrue(p.mic_view)
        b.note("could not reach the CLI")
        self.assertFalse(p.mic_view)
        self.assertEqual(p.pill_w, ui.BUBBLE_W)
        p._sync_shell.assert_called()

    def test_and_it_shrinks_again_when_the_note_clears_with_no_state_to_unwind(self):
        p, b = self.bubble()
        b.note("unverified CLI")
        b._visible = False  # what `Bubble.hide` leaves behind
        self.assertTrue(p.mic_view)
        self.assertEqual(p.pill_w, ui.MIC_W)
        # Nothing was entered, so there is nothing that could have been left entered.
        self.assertTrue(p.mic_view_on)

    def test_the_frame_that_grows_back_is_not_skipped_as_unchanged(self):
        # `_draw` returns early when its key matches the last one. The key has to carry
        # the view, or the grow-back is a frame that draws nothing and leaves a 128 px
        # row under a 400 px panel.
        p, b = self.bubble()
        p.canvas = Canvas()
        p._draw()
        b._visible = True
        p._docked_w = ui.BUBBLE_W
        self.assertNotEqual(p._draw_key(), p._drawn_key)

    def test_an_undoable_edit_keeps_its_way_back(self):
        # `surface` clears the flag, its own traffic being errors. This door's is not.
        p, b = self.bubble()
        b.note("removed a filler word", undoable=True)
        self.assertTrue(b._note_undo)

    def test_an_empty_note_does_not_open_a_panel_to_say_nothing(self):
        p, b = self.bubble()
        b.note("")
        self.assertFalse(b._visible)

    def test_off_the_view_a_note_is_dropped_exactly_as_before(self):
        # The gate is the whole of what changed here, so with the view off this path is
        # the behaviour it was.
        p, b = self.bubble(on=False)
        b.note("panel size: large")
        self.assertFalse(b._visible)
        self.assertEqual(b.renders, 0)


class TestTheReleaseDoesNotOpenAPanel(unittest.TestCase):
    """The bug this view was reported with: the panel appeared on every utterance.

    A push-to-talk release ends in `_pump_talk` calling `_send`, and `_send` put a sent
    card on screen for words that had *already* been pasted into the other window. It is
    not an event, so `_pump_events`' gate never saw it — which is exactly why it is worth
    its own test rather than a line in the routing one.
    """

    def send(self, *, problem="", lite=False, on_send=True):
        p = mic_pill()
        p.lite = lite
        p.paste_target = 1
        p.on_send = (lambda *a, **kw: problem) if on_send else None
        # Lite with no handler copies instead of pasting, and `_copy` reaches Tk's
        # clipboard — which on a fixture built with `__new__` is a recursion, not a
        # clipboard. The copy is not what this class is about.
        p._copy = mock.Mock(return_value=problem)
        p.session.send.return_value = "the words that went"
        p.session.mode = DICTATE
        p._ptt_wait = 1.0
        p._sync_shell = mock.Mock()
        p.bubble = Stub(p)
        p.bubble.show_sent = mock.Mock()
        p._send()
        return p

    def test_a_paste_that_worked_leaves_the_row_alone(self):
        p = self.send()
        p.bubble.show_sent.assert_not_called()
        self.assertFalse(p.bubble._visible)
        self.assertTrue(p.mic_view)

    def test_the_words_still_went(self):
        # Nothing about the drawing may change what was sent. The card was a receipt for
        # a paste that had already happened, and the paste is untouched.
        p = self.send()
        p.session.send.assert_called_once()

    def test_a_paste_that_failed_still_opens_the_panel_and_flashes(self):
        # The one thing here that cannot be inferred from looking at the other window.
        p = self.send(problem="the clipboard would not restore")
        p.bubble.show_sent.assert_called_once()
        self.assertEqual(p._flash, ui.FLASH_FRAMES)

    def test_and_off_the_view_the_card_is_exactly_what_it_was(self):
        p = mic_pill(on=False)
        p.lite = False
        p.paste_target = 1
        p.on_send = lambda *a, **kw: ""
        p.session.send.return_value = "the words that went"
        p.session.mode = DICTATE
        p._sync_shell = mock.Mock()
        p.bubble = Stub(p)
        p.bubble.show_sent = mock.Mock()
        p._send()
        p.bubble.show_sent.assert_called_once_with("the words that went")

    def test_lite_still_says_the_last_step_is_yours(self):
        # No card, but the words were copied rather than pasted — so the note that says
        # somebody has to paste them still has to arrive, and it grows the panel back.
        p = self.send(lite=True, on_send=False)
        self.assertTrue(p.bubble._visible)
        self.assertEqual(p.bubble._note, ui.COPIED)


class TestTheGrownBackPanelGivesTheRowBack(unittest.TestCase):
    """The other half of the grow-back, and the half that was assumed rather than run.

    Nothing hides a surfaced note. On the full row it lands on a panel that was already
    up and the next draft clears it; under this view there is no next draft, so one line
    from a settings row left the pill 400 px wide for as long as Flow ran. Measured on
    the real window: twelve seconds after clicking "Push to talk", still 400x98. The
    earlier tests here called `hide()` by hand and so proved only that hiding works.
    """

    def bubble(self, **kw):
        p = mic_pill(**kw)
        p._sync_shell = mock.Mock()
        p.bubble = Stub(p)
        return p, p.bubble

    def test_the_note_is_stamped_when_the_view_surfaces_it(self):
        p, b = self.bubble()
        b.note("chord: Push to talk - hold to speak, release to send")
        self.assertIsNotNone(b._for_note)

    def test_it_stays_long_enough_to_read(self):
        p, b = self.bubble()
        b.note("could not reach the CLI")
        b.tick_note()
        self.assertTrue(b._visible)
        b._for_note = time.perf_counter() - (ui.MIC_NOTE_SEC - 0.5)
        b.tick_note()
        self.assertTrue(b._visible)

    def test_and_then_the_row_comes_back_on_its_own(self):
        p, b = self.bubble()
        b.note("could not reach the CLI")
        b._for_note = time.perf_counter() - ui.MIC_NOTE_SEC
        b.tick_note()
        self.assertFalse(b._visible)
        self.assertEqual(b._note, "")
        self.assertTrue(p.mic_view)
        self.assertEqual(p.pill_w, ui.MIC_W)

    def test_a_panel_with_something_else_on_it_is_not_taken_away(self):
        # A draft, a partial or a sent card arriving during the dwell means the surface
        # has a second reason to be up. Hiding it under one of those would be this fix
        # causing the class of bug it exists to fix.
        for field in ("_text", "_partial", "_sent"):
            with self.subTest(field=field):
                p, b = self.bubble()
                b.note("a line")
                setattr(b, field, "the words")
                b._for_note = time.perf_counter() - ui.MIC_NOTE_SEC * 3
                b.tick_note()
                self.assertTrue(b._visible)
                self.assertIsNone(b._for_note)

    def test_a_panel_the_view_did_not_surface_is_never_touched(self):
        # Every note on the full pill, and every panel up for its own reasons. The stamp
        # is set in `note` under the view and nowhere else.
        p, b = self.bubble(on=False)
        b._visible = True
        b.note("panel size: large")
        self.assertIsNone(b._for_note)
        b.tick_note()
        self.assertTrue(b._visible)

    def test_the_dwell_is_longer_than_the_sent_cards(self):
        # That card is a receipt for something the user just did on purpose; this is a
        # line they did not ask for and have to read cold.
        self.assertGreater(ui.MIC_NOTE_SEC, ui.SENT_LINGER_SEC)


class TestProgressDoesNotOpenAPanel(unittest.TestCase):
    """The startup somebody reported as "it opens as a big window then it shifts to mic".

    `Bubble.tick_activity` surfaces the panel for a wait with nothing else on screen —
    right on the full row, where the invisible states are the ones with no draft to hang
    a note on. Under this view it meant the model load opened a 400 px panel on every
    launch and held it for the eight seconds the load takes. Measured on the real window
    from a cold start: 90x34 at 0.76 s, 400x98 at 1.07 s, back to 90x34 at 9.52 s.
    """

    def bubble(self, *, on=True, act=SimpleNamespace(label="loading the model",
                                                     waiting=True)):
        p = mic_pill(on=on)
        p._sync_shell = mock.Mock()
        p.bubble = Stub(p)
        p.session.activity = act
        return p, p.bubble

    def test_a_wait_does_not_surface_a_panel_under_the_view(self):
        p, b = self.bubble()
        b.tick_activity()
        self.assertFalse(b._visible)
        self.assertTrue(p.mic_view)
        self.assertEqual(p.pill_w, ui.MIC_W)

    def test_and_off_the_view_it_surfaces_exactly_as_it_did(self):
        # The wait is the only thing that says a fresh Flow is doing anything at all, so
        # taking it away from the full row would be a regression, not a tidy-up.
        p, b = self.bubble(on=False)
        b.tick_activity()
        self.assertTrue(b._visible)
        self.assertTrue(b._for_activity)

    def test_a_note_arriving_during_the_wait_still_gets_through(self):
        # Progress is not something to read; a refusal is. Declining to open a panel for
        # the wait must not close the door the notes come through.
        p, b = self.bubble()
        b.tick_activity()
        b.note("could not reach the CLI")
        self.assertTrue(b._visible)
        self.assertFalse(p.mic_view)

    def test_the_panel_is_not_taken_away_from_a_wait_that_is_already_up(self):
        # Switching the view on mid-load must not yank a panel that is already carrying
        # the indicator: `tick_activity` only declines to *open* one.
        p, b = self.bubble(on=False)
        b.tick_activity()
        p.mic_view_on = True
        b._frame_key = None
        b.tick_activity()
        self.assertTrue(b._visible)


class Recorder:
    """A session that reports a fixed script and records every call made to it."""

    def __init__(self, script) -> None:
        self.script = list(script)
        self.calls: list[str] = []
        self.state = State.DRAFT
        self.mode = DICTATE
        self.profile = None

    def events(self):
        self.calls.append("events")
        return list(self.script)


class TestTheSessionDoesNotKnowThisExists(unittest.TestCase):
    def test_no_module_but_the_ui_mentions_the_view(self):
        # The structural half of "a view, not a mode": if a session route ever needs a
        # branch for this, the design is wrong and this test is where that is noticed.
        root = Path(__file__).resolve().parent.parent / "flow"
        for name in ("session.py", "asr.py", "audio.py", "inject.py", "refine.py"):
            with self.subTest(name=name):
                source = (root / name).read_text(encoding="utf-8")
                self.assertNotIn("mic_view", source)
                self.assertNotIn("mic_at", source)

    def drain(self, on):
        events = [SimpleNamespace(kind="draft", text="hello there"),
                  SimpleNamespace(kind="partial", text="hello"),
                  SimpleNamespace(kind="note", text="a note"),
                  SimpleNamespace(kind="drop", text="too quiet"),
                  SimpleNamespace(kind="error", text="no CLI")]
        p = mic_pill(on=on)
        p.session = Recorder(events)
        p._sync_shell = mock.Mock()
        p.bubble = Stub(p)
        p.card = SimpleNamespace(_visible=False)
        p._asked = False
        p._last_draft = ""
        p._flash = 0
        p._pump_events()
        return p

    def test_the_session_sees_the_same_calls_either_way(self):
        self.assertEqual(self.drain(True).session.calls,
                         self.drain(False).session.calls)

    def test_the_view_draws_fewer_of_them_and_that_is_all(self):
        # The draft and the partial are not drawn; everything that says something still
        # arrives, and the last of them is on the panel that grew back to carry it.
        on = self.drain(True)
        self.assertEqual(on.bubble._note, "no CLI")
        self.assertTrue(on.bubble._visible)

    def test_and_the_draft_is_still_remembered_for_a_mode_switch(self):
        # `_last_draft` is what a switch to converse pins as the question that went. Not
        # drawing the draft must not mean forgetting it.
        self.assertEqual(self.drain(True)._last_draft, "hello there")


class TestThePositionSurvivesARestart(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "profile.json"

    def test_a_dragged_position_is_written_and_read_back(self):
        p = mic_pill()
        p.x, p.y = 1200, 340
        p.session.profile = Profile(self.path)
        p._remember_mic_at()
        self.assertTrue(self.path.exists())
        again = Profile(self.path)
        again.load()
        self.assertEqual(again.mic_at, [1200, 340])
        self.assertEqual(ui._mic_spot(again.mic_at), (1200, 340))

    def test_and_the_setting_comes_back_with_it(self):
        profile = Profile(self.path)
        profile.mic = True
        profile.mic_at = (10, 20)
        profile.save()
        again = Profile(self.path)
        again.load()
        self.assertTrue(again.mic)
        self.assertEqual(again.mic_at, [10, 20])

    def test_the_default_profile_has_the_view_off_and_no_position(self):
        # Purely additive: a profile written before this existed reads as "off".
        profile = Profile(self.path)
        self.assertFalse(profile.mic)
        self.assertIsNone(profile.mic_at)

    def test_a_position_off_the_screen_lands_on_it(self):
        # The reason this is not a `PLACES` name: the answer is per monitor and the
        # profile is not, so a spot saved on a display that is no longer plugged in has
        # to be clamped rather than honoured.
        p = mic_pill()
        p.work = (0, 0, 1920, 1040)
        p.full = (0, 0, 1920, 1080)
        p._mic_at = (5000, 5000)
        self.assertEqual(p._placed(ui.MIC_W),
                         (1920 - ui.MIC_W, 1040 - ui.PILL_H))

    def test_a_hand_edited_position_costs_the_setting_and_not_the_launch(self):
        junk = (None, "somewhere", [1], [1, 2, 3], ["a", "b"], 3.5, [float("inf"), 0])
        for value in junk:
            with self.subTest(value=value):
                self.assertIsNone(ui._mic_spot(value))
                profile = Profile(self.path)
                profile.mic_at = value
                self.assertTrue(profile.save())

    def test_the_full_pill_is_placed_the_way_it_always_was(self):
        # The (x, y) belongs to this view alone. With it off, `PLACE` decides — the
        # stack still has a 400-580 px panel to fit, and that is what `PLACES` is for.
        p = mic_pill(on=False)
        p.work = (0, 0, 1920, 1040)
        p.full = (0, 0, 1920, 1080)
        p._mic_at = (5, 5)
        with mock.patch.object(ui, "PLACE", "corner"):
            self.assertEqual(p._placed(ui.BUBBLE_W),
                             (1920 - ui.BUBBLE_W - 28, 1040 - ui.PILL_H - 24))


class TestTheViewStandsDownWhenItShould(unittest.TestCase):
    def test_a_switch_to_the_toggle_gesture_takes_it_away(self):
        p = mic_pill(gesture="hold")
        self.assertTrue(p.mic_view)
        p.hotkeys.chord.gesture = "toggle"
        self.assertFalse(p.mic_view)
        self.assertEqual(p.pill_w, ui.BUBBLE_W)

    def test_no_chord_is_not_push_to_talk(self):
        p = mic_pill()
        p.hotkeys = None
        self.assertFalse(p.push_to_talk)
        self.assertFalse(p.mic_view)

    def test_a_visible_card_stands_it_down_too(self):
        p = mic_pill()
        p.card = SimpleNamespace(_visible=True, _marks=[])
        self.assertFalse(p.mic_view)

    def test_a_bare_fixture_answers_rather_than_recursing(self):
        # `tk.Misc.__getattr__` forwards a miss to `self.tk`. Both new fields are class
        # attributes for that reason — item 32's `RecursionError`, found again.
        bare = ui.Pill.__new__(ui.Pill)
        self.assertFalse(bare.mic_view_on)
        self.assertIsNone(bare._mic_at)
        self.assertFalse(bare.push_to_talk)
        self.assertFalse(bare.mic_view)


if __name__ == "__main__":
    unittest.main()
