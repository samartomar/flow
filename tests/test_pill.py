"""What the pill draws in its own 205×40, and the three §07 animations that move it.

Everything here goes through `Pill._draw` on a fake canvas rather than through a real
window, for the reason `test_indicator.py` does: a desktop is expensive and `_draw` is
pure — given a session state and a frame counter, it writes a fixed set of shapes. The
one test that does need Tk is the font measurement, and it says so.

The four things pinned here were all "drawn nowhere yet" until now:

* the **bar label**, §02's `Plex Mono 11 · +.1em`, and the slot `PILL_W` reserves for it
* the **waiting dots**, which stand in for the meter while a CLI is out
* the **error flash**, which travels rather than switching
* the **mode tint**, the 180 ms green ⇄ violet the mode switch is continuous across
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.ui as ui  # noqa: E402
from flow.session import CONVERSE, DICTATE, State  # noqa: E402


class Canvas:
    """Records the four primitives `Pill._draw` uses, with their geometry."""

    def __init__(self) -> None:
        self.texts: list[tuple[float, float, str, str]] = []
        self.ovals: list[tuple[float, float, float, float, str]] = []
        self.rects: list[tuple[float, float, float, float, str]] = []
        self.lines: list[tuple[tuple, str]] = []

    def delete(self, *a, **kw) -> None: ...

    def create_polygon(self, *a, **kw) -> None: ...

    def create_arc(self, *a, **kw) -> None: ...

    def create_oval(self, x1, y1, x2, y2, **kw) -> None:
        self.ovals.append((x1, y1, x2, y2, kw.get("fill", "")))

    def create_rectangle(self, x1, y1, x2, y2, **kw) -> None:
        self.rects.append((x1, y1, x2, y2, kw.get("fill", "")))

    def create_line(self, *a, **kw) -> None:
        self.lines.append((a, kw.get("fill", "")))

    def create_text(self, x, y, text="", **kw) -> None:
        self.texts.append((x, y, text, kw.get("fill", "")))


def pill(state=State.IDLE, *, armed=True, mode=DICTATE, hearing=True,
         speaking=False, editing=False, mic_active=True, **attrs):
    """A pill with a fake canvas and no Tk, built the way `test_indicator` builds one.

    Every session attribute `_bar_label` reads is set to a real value rather than left
    as an auto-created Mock: `not Mock()` is `False`, so a bare Mock would silently
    answer "yes, hearing; yes, mic alive" and no deaf-state test here could ever fail.
    """
    p = ui.Pill.__new__(ui.Pill)
    p.canvas = Canvas()
    p.armed = armed
    p.levels = [0.0] * ui.BARS
    p.session = mock.Mock(
        mode=mode, state=state, hearing=hearing, editing=editing, cli=None,
        mic=mock.Mock(active=mic_active),
        speaker=mock.Mock(speaking=speaking) if speaking else None,
    )
    #: Already resolved, so converse's marker slot does not walk PATH from a fixture.
    p._clis = []
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


def label_of(p) -> str:
    """The bar label reassembled from the per-character items on the centre line."""
    mid = ui.PILL_H // 2
    chars = sorted((x, t) for x, y, t, _f in p.canvas.texts if y == mid)
    return "".join(t for _x, t in chars)


def label_xs(p) -> list[float]:
    mid = ui.PILL_H // 2
    return sorted(x for x, y, _t, _f in p.canvas.texts if y == mid)


def dots(p) -> list[tuple[float, float, float, float, str]]:
    """The waiting dots: the ovals in the meter's slot, not the mic glyph's capsule."""
    return [o for o in p.canvas.ovals if o[0] >= ui.METER_X]


class TestTheSlotIsReservedAtTheWidestLabel(unittest.TestCase):
    """`LABEL_SLOT_W` is arithmetic over a font this file does not otherwise touch."""

    def test_the_advance_is_the_one_the_real_font_measures(self):
        # The only test here that needs Tk. `LABEL_ADV` is a hardcoded 7 because `_draw`
        # cannot afford to build a font object per frame, and a hardcoded metric is only
        # safe if something measures it.
        import tkinter as tk
        import tkinter.font as tkfont

        try:
            root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - headless CI
            self.skipTest(f"no display: {exc}")
        try:
            root.withdraw()
            ui._load_fonts()
            f = tkfont.Font(root=root, font=ui.FONT_TRACE)
            # `_load_fonts` registers the bundled Plex weights through GDI and returns
            # early off Windows, so anywhere else Tk quietly substitutes its own
            # monospace and this measures *that* - 10 px on a macOS runner against the
            # 7 the real face gives. Skipped on the substitution rather than on the
            # platform, because the question is whether the font resolved, and a
            # Windows machine missing the file deserves the same answer.
            if f.actual("family") != ui.FONT_TRACE[0]:
                self.skipTest(f"{ui.FONT_TRACE[0]} not installed; "
                              f"Tk substituted {f.actual('family')!r}")
            self.assertEqual(f.measure("M"), ui.LABEL_ADV)
            # Monospaced, which is the assumption behind one advance for every glyph —
            # including the space in `NO INPUT`.
            for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ ":
                self.assertEqual(f.measure(ch), ui.LABEL_ADV, ch)
        finally:
            root.destroy()

    def test_the_slot_fits_every_label_there_is(self):
        every = [*ui.BAR_LABELS.values(), ui.LABEL_OFF, ui.LABEL_SPEAKING,
                 ui.LABEL_EDITING, ui.LABEL_NO_INPUT]
        for word in every:
            with self.subTest(word=word):
                self.assertLessEqual(
                    len(word) * ui.LABEL_PITCH - ui.LABEL_TRACK, ui.LABEL_SLOT_W)

    def test_the_widest_label_still_clears_the_meter(self):
        # The whole reason the pill grew from 168: at the old width the label and the
        # twelfth bar wanted the same pixels, and the meter is not the one that yields.
        p = pill(State.LISTENING, _docked_w=ui.PILL_W, _flash=0, _tint=0.0)
        p._draw()
        self.assertEqual(label_of(p), "LISTENING")
        self.assertGreaterEqual(min(label_xs(p)), ui.METER_X + ui.METER_W,
                                "the label is drawn through the meter")

    def test_the_meter_still_has_all_twelve_bars_in_every_state(self):
        for state, word in ui.BAR_LABELS.items():
            with self.subTest(state=state):
                p = pill(state, _docked_w=ui.PILL_W, _flash=0, _tint=0.0,
                         _dots_frame=0)
                p._draw()
                if p.waiting:
                    continue  # the meter is not drawn at all there; see the dots below
                bars = [r for r in p.canvas.rects if r[0] >= ui.METER_X]
                self.assertEqual(len(bars), ui.BARS, word)


class TestTheBarLabelSaysWhatFlowIsDoing(unittest.TestCase):
    def test_each_state_gets_its_word(self):
        for state, word in ui.BAR_LABELS.items():
            with self.subTest(state=state):
                self.assertEqual(pill(state)._bar_label(), word)

    def test_disarmed_is_a_state_of_the_pill_not_of_the_session(self):
        # The session is still sitting in IDLE; the pill is the thing that is off.
        self.assertEqual(pill(State.IDLE, armed=False)._bar_label(), ui.LABEL_OFF)

    def test_deafness_says_which_kind_it_is(self):
        # `Session.hearing` is careful that "busy, still listening" and "busy, and deaf"
        # are different promises. The label has to keep that distinction, because only
        # one of the three means the microphone is not coming back.
        self.assertEqual(
            pill(State.LISTENING, hearing=False, speaking=True)._bar_label(),
            ui.LABEL_SPEAKING)
        self.assertEqual(
            pill(State.LISTENING, hearing=False, editing=True)._bar_label(),
            ui.LABEL_EDITING)
        self.assertEqual(
            pill(State.LISTENING, mic_active=False)._bar_label(), ui.LABEL_NO_INPUT)

    def test_a_spoken_reply_is_not_labelled_as_an_edit(self):
        # Found in `23-converse-speaking.png`: the first version asked
        # `speaker.speaking`, and a session whose speaker does not carry that flag —
        # which is every session with speech switched off — fell through to `EDITING`.
        # `hearing` is defined as "not speaking and not editing", so `editing` alone
        # separates them, and it is a plain attribute rather than a reach through an
        # object that can be `None`.
        p = pill(State.IDLE, hearing=False, editing=False)
        p.session.speaker = None
        self.assertEqual(p._bar_label(), ui.LABEL_SPEAKING)

    def test_a_dead_device_outranks_the_state_that_does_not_know_it_yet(self):
        # The session can still report LISTENING for a frame after the device drops.
        # "no input" is the true answer, and it is the one that tells the user to stop
        # talking — so it wins.
        self.assertEqual(
            pill(State.LISTENING, mic_active=False)._bar_label(), ui.LABEL_NO_INPUT)

    def test_it_is_drawn_a_character_at_a_time_with_tracking(self):
        # Tk has no letter-spacing, so §02's `+.1em` only exists if `_draw` places each
        # glyph itself. One `create_text` for the whole word would be 63 px, not 71.
        p = pill(State.DRAFT, _docked_w=ui.PILL_W, _flash=0, _tint=0.0)
        p._draw()
        xs = label_xs(p)
        self.assertEqual(len(xs), len("HELD"))
        gaps = {round(b - a) for a, b in zip(xs, xs[1:])}
        self.assertEqual(gaps, {ui.LABEL_PITCH})
        self.assertGreater(ui.LABEL_PITCH, ui.LABEL_ADV, "tracking is not being applied")

    def test_the_right_edge_holds_still_when_the_pill_docks(self):
        # The pill's right edge is the one `_sync_dock` pins, so it is the only place a
        # word can sit and not move while the window grows to meet a panel.
        edges = set()
        for w in (ui.PILL_W, 380, 420):
            p = pill(State.DRAFT, _docked_w=w, _flash=0, _tint=0.0, _docked_above=True)
            p._draw()
            edges.add(w - (max(label_xs(p)) + ui.LABEL_ADV))
        self.assertEqual(edges, {ui.LABEL_PAD})

    def test_it_takes_the_accent_like_the_glyph_does(self):
        p = pill(State.LISTENING, _docked_w=ui.PILL_W, _flash=0, _tint=0.0)
        p._draw()
        fills = {f for _x, y, _t, f in p.canvas.texts if y == ui.PILL_H // 2}
        self.assertEqual(fills, {ui.HEARING})


class TestTheWaitingDotsStandInForTheMeter(unittest.TestCase):
    """§07: three 4 px dots, opacity .25 → 1, staggered 150 ms, 1.2 s loop."""

    def test_the_meter_is_replaced_rather_than_left_running(self):
        # Left up, it would be lying: nothing is being captured while a CLI is out, and
        # bars moving there are the same false "hearing you" `_flatten` exists to kill.
        p = pill(State.REFINING, _docked_w=ui.PILL_W, _flash=0, _tint=0.0,
                 _dots_frame=0)
        p._draw()
        self.assertEqual(len(dots(p)), 3)
        self.assertEqual([r for r in p.canvas.rects if r[0] >= ui.METER_X], [],
                         "the level meter is still drawn behind the dots")

    def test_they_are_four_pixels_across_and_sit_in_the_meters_slot(self):
        p = pill(State.ASKING, _docked_w=ui.PILL_W, _flash=0, _tint=0.0, _dots_frame=0)
        p._draw()
        for x1, y1, x2, y2, _f in dots(p):
            self.assertEqual((x2 - x1, y2 - y1), (2 * ui.DOT_R, 2 * ui.DOT_R))
            self.assertGreaterEqual(x1, ui.METER_X)
            self.assertLessEqual(x2, ui.METER_X + ui.METER_W)

    def test_the_three_are_staggered_rather_than_blinking_together(self):
        # Frame 8 rather than a round number: the wave straddles a peak symmetrically on
        # frames 5 and 25, where the outer two dots really are the same shade, and this
        # test is about the other thirty-eight.
        p = pill(State.REFINING, _docked_w=ui.PILL_W, _flash=0, _tint=0.0,
                 _dots_frame=8)
        p._draw()
        self.assertEqual(len({f for *_g, f in dots(p)}), 3,
                         "all three dots are the same shade on this frame")

    def test_each_one_travels_the_whole_range_over_the_loop(self):
        # Not just "it changes": .25 → 1 is the spec, and a dot that only ever moved
        # between .5 and .6 would still pass a bare inequality.
        for i in range(3):
            with self.subTest(dot=i):
                p = pill(State.REFINING, _dots_frame=0)
                lit = []
                for frame in range(ui.DOTS_LOOP):
                    p._dots_frame = frame
                    lit.append(p._dot_lit(i))
                self.assertEqual(max(lit), 1.0)
                self.assertEqual(min(lit), ui.DOT_DIM)

    def test_full_brightness_lasts_long_enough_to_be_seen(self):
        # The defect the first curve had. A sawtooth — snap to full, decay across the
        # loop — reached 1.0 on exactly one frame in forty, so the peak that makes three
        # dots read as *marching* rather than as three greys was invisible in practice:
        # two screenshots a third of a second apart both caught the brightest dot at
        # 68 %. A test that only asked "does it reach 1.0" passed the whole time.
        p = pill(State.REFINING, _dots_frame=0)
        bright = sum(
            max(p._dot_lit(i) for i in range(3)) > 0.9
            for p._dots_frame in range(ui.DOTS_LOOP)
        )
        self.assertGreater(bright, ui.DOTS_LOOP // 3,
                           "the row is dim on almost every frame")

    def test_the_bright_point_travels_along_the_row(self):
        p = pill(State.REFINING, _dots_frame=0)
        leaders = []
        for frame in range(ui.DOTS_LOOP):
            p._dots_frame = frame
            lit = [p._dot_lit(i) for i in range(3)]
            leaders.append(lit.index(max(lit)))
        # Each dot leads in turn, and it leads for a stretch — a row where the leader
        # changed every frame would be flickering, not marching.
        self.assertEqual(set(leaders), {0, 1, 2})
        self.assertLessEqual(sum(a != b for a, b in zip(leaders, leaders[1:])), 3)

    def test_the_three_are_not_all_the_same_shade(self):
        # They do coincide on the two frames in forty where the wave straddles a peak
        # symmetrically. Any other frame has to show three distinct dots.
        p = pill(State.REFINING, _dots_frame=8)
        self.assertEqual(len({round(p._dot_lit(i), 6) for i in range(3)}), 3)

    def test_the_loop_advances_on_the_frame_and_resets_when_the_wait_ends(self):
        p = pill(State.REFINING, _pointer_in=False, _tint=0.0, _dots_frame=0)
        for _ in range(3):
            p._advance_motion()
        self.assertEqual(p._dots_frame, 3)
        # Reset, not paused: the next CLI call starts at the beginning of the loop
        # rather than wherever the last one happened to stop.
        p.session.state = State.LISTENING
        p._advance_motion()
        self.assertEqual(p._dots_frame, 0)

    def test_nothing_marches_under_the_pointer(self):
        p = pill(State.REFINING, _pointer_in=True, _tint=0.0, _dots_frame=7)
        p._advance_motion()
        self.assertEqual(p._dots_frame, 7)


class TestTheErrorFlashTravels(unittest.TestCase):
    """§07's `80 / 1200 / 600`, and the one surface that is allowed to interpolate it."""

    def test_it_attacks_holds_and_decays_rather_than_switching(self):
        p = pill(_flash=ui.FLASH_FRAMES)
        curve = []
        while p._flash:
            curve.append(p.flash_t)
            p._flash -= 1
        self.assertEqual(len(curve), ui.FLASH_FRAMES)
        self.assertLess(curve[0], 1.0, "the flash arrives fully red on frame one")
        self.assertEqual(curve[ui.FLASH_ATTACK - 1], 1.0)
        self.assertEqual(curve[ui.FLASH_ATTACK], 1.0, "the hold has to be flat")
        self.assertEqual(curve[ui.FLASH_ATTACK + ui.FLASH_HOLD - 1], 1.0)
        self.assertLess(curve[-1], 0.1, "it ends as abruptly as it used to")
        # Monotone in each leg, so no frame is brighter than the one before it during
        # the decay — a sawtooth would read as a second error.
        decay = curve[ui.FLASH_ATTACK + ui.FLASH_HOLD:]
        self.assertEqual(decay, sorted(decay, reverse=True))

    def test_the_pills_hairline_is_the_thing_that_interpolates(self):
        p = pill(_flash=ui.FLASH_FRAMES)
        rings = set()
        while p._flash:
            rings.add(p.ring_color)
            p._flash -= 1
        self.assertIn(ui.ERROR, rings)
        self.assertGreater(len(rings), 3, "the ring is still switching, not travelling")
        self.assertEqual(p.ring_color, ui.RING_OUTER)

    def test_a_panel_ring_is_set_once_and_cleared_once(self):
        # "Two repaints, not sixty." The panels ask `flashing`, which is a fact about
        # the pill, rather than reading a colour that is a different blend every frame.
        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = pill(_flash=ui.FLASH_FRAMES)
        shades = set()
        while b.pill._flash:
            shades.add(b.accent)
            b.pill._flash -= 1
        self.assertEqual(shades, {ui.ERROR})

    def test_every_call_site_uses_the_one_envelope(self):
        # The 12 / 40 / 60 these used to be were three durations nobody chose, and the
        # shortest was 360 ms against a hold the spec puts at 1200.
        import re

        src = Path(ui.__file__).read_text(encoding="utf-8")
        assigned = set(re.findall(r"self\._flash = (\S+)", src))
        self.assertEqual(assigned, {"0", "FLASH_FRAMES"})


class TestTheModeSwitchIsContinuous(unittest.TestCase):
    """§07: "the pill's glyph and label tint travel green ⇄ violet at frame rate, and
    that travel is the whole continuity" of a switch that also swaps two windows."""

    def test_the_accent_arrives_at_violet_over_the_specified_frames(self):
        p = pill(State.LISTENING, mode=CONVERSE, _pointer_in=False, _flash=0,
                 _tint=0.0, _dots_frame=0)
        self.assertEqual(p.accent, ui.HEARING)
        seen = []
        for _ in range(ui.TINT_FRAMES):
            p._advance_motion()
            seen.append(p.accent)
        self.assertEqual(seen[-1], ui.CARD_ACCENT)
        self.assertNotIn(ui.HEARING, seen[1:], "it jumped instead of travelling")
        self.assertEqual(seen.count(ui.CARD_ACCENT), 1, "it arrived early")

    def test_it_travels_back(self):
        p = pill(State.LISTENING, mode=DICTATE, _pointer_in=False, _flash=0,
                 _tint=1.0, _dots_frame=0)
        self.assertEqual(p.accent, ui.CARD_ACCENT)
        for _ in range(ui.TINT_FRAMES):
            p._advance_motion()
        self.assertEqual(p.accent, ui.HEARING)

    def test_an_error_still_wins_over_wherever_the_tint_had_got_to(self):
        # An error is true regardless of which mode raised it, and a half-violet pill
        # during a failed Ask would be reporting the switch instead of the failure.
        p = pill(State.LISTENING, mode=CONVERSE, _tint=0.5, _flash=ui.FLASH_FRAMES - 3)
        self.assertEqual(p.accent, ui.ERROR)

    def test_the_glyph_and_the_label_travel_together(self):
        p = pill(State.LISTENING, mode=CONVERSE, _docked_w=ui.PILL_W, _flash=0,
                 _tint=0.5, _dots_frame=0)
        p._draw()
        mid = ui.PILL_H // 2
        half = ui._mix(ui.HEARING, ui.CARD_ACCENT, 0.5)
        self.assertEqual({f for _x, y, _t, f in p.canvas.texts if y == mid}, {half})
        self.assertEqual({o[-1] for o in p.canvas.ovals if o[0] < ui.METER_X}, {half})


class TestMix(unittest.TestCase):
    def test_the_ends_are_exact(self):
        self.assertEqual(ui._mix(ui.HEARING, ui.CARD_ACCENT, 0.0), ui.HEARING)
        self.assertEqual(ui._mix(ui.HEARING, ui.CARD_ACCENT, 1.0), ui.CARD_ACCENT)

    def test_it_clamps_rather_than_raising_inside_a_repaint(self):
        self.assertEqual(ui._mix("#000000", "#ffffff", -3.0), "#000000")
        self.assertEqual(ui._mix("#000000", "#ffffff", 9.0), "#ffffff")

    def test_it_is_a_real_blend(self):
        self.assertEqual(ui._mix("#000000", "#ffffff", 0.5), "#808080")


def docker(*, showing=True, panel_w=ui.BUBBLE_W, window=None, x=1047, docked_w=ui.PILL_W):
    """A pill with just enough of one to run `_sync_dock`, and a window it can lie about.

    `window` is what the window manager is pretending to hold — pass a (w, x, y) that
    disagrees with the pill's own state to stage the defect this class is about.
    """
    p = ui.Pill.__new__(ui.Pill)
    p.canvas = mock.Mock()
    p.session = mock.Mock(mode=DICTATE)
    p.bubble = mock.Mock(width=panel_w, _visible=showing)
    p.card = mock.Mock(width=panel_w, _visible=False)
    p.work = (0, 0, 1280, 720)
    p.x, p.y = x, 608
    p._docked_w = docked_w
    p.geometry = mock.Mock()
    p.window_geometry = mock.Mock(
        return_value=window if window is not None else (docked_w, x, 608))
    return p


class TestTheDockIsCheckedRatherThanAssumed(unittest.TestCase):
    """The pill and the panel above it share one column, and stay sharing it.

    `scripts/reel.py` found them not sharing it: the pill 420 px wide at the x a
    205 px pill sits at, hanging 215 px off the screen and unjoined from the panel it
    is docked to, held there for five seconds because the width already matched and
    nothing looked again.
    """

    def test_a_panel_appearing_moves_the_left_edge_and_holds_the_right(self):
        p = docker()
        p._sync_dock()
        p.geometry.assert_called_once_with(f"{ui.BUBBLE_W}x{ui.PILL_H}+832+608")
        self.assertEqual(p.x + ui.BUBBLE_W, 1047 + ui.PILL_W)  # the right edge did not move

    def test_nothing_is_asked_for_twice_when_the_window_already_agrees(self):
        p = docker(docked_w=ui.BUBBLE_W, x=832, window=(ui.BUBBLE_W, 832, 608))
        p._sync_dock()
        p.geometry.assert_not_called()

    def test_a_move_that_did_not_land_is_asked_for_again(self):
        # The reel's finding, staged: the resize took and the move did not, so the
        # window is at the bare-pill x while the pill's own state says it docked.
        # Before this was checked, `w == self._docked_w` returned here and the pill
        # stayed off the screen edge for as long as the panel was up.
        p = docker(docked_w=ui.BUBBLE_W, x=832, window=(ui.BUBBLE_W, 1047, 608))
        p._sync_dock()
        p.geometry.assert_called_once_with(f"{ui.BUBBLE_W}x{ui.PILL_H}+832+608")

    def test_the_recovery_does_not_move_the_pill_a_second_time(self):
        # Re-asking must re-send the *same* geometry, never re-run the relative
        # arithmetic — that would walk the pill one panel-width left per frame.
        p = docker(docked_w=ui.BUBBLE_W, x=832, window=(ui.BUBBLE_W, 1047, 608))
        for _ in range(5):
            p._sync_dock()
        self.assertEqual(p.x, 832)
        self.assertEqual({c.args for c in p.geometry.call_args_list},
                         {(f"{ui.BUBBLE_W}x{ui.PILL_H}+832+608",)})

    def test_the_panel_going_away_takes_the_width_back(self):
        p = docker(showing=False, docked_w=ui.BUBBLE_W, x=832)
        p._sync_dock()
        self.assertEqual(p.x, 1047)
        p.geometry.assert_called_once_with(f"{ui.PILL_W}x{ui.PILL_H}+1047+608")


if __name__ == "__main__":
    unittest.main()
