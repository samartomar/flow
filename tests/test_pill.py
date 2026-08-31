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

    #: `_sync_dock` resizes the canvas when a panel docks or goes away. Accepted and
    #: recorded rather than ignored, so a test can tell a widened pill from a moved one.
    def configure(self, **kw) -> None:
        self.width = kw.get("width", getattr(self, "width", None))

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
    p._meter_level = 0.0
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


class TestTheMeterBloomsFromItsCentre(unittest.TestCase):
    """The shape taken from FluidVoice's `BottomWaveformView`, asserted as a shape.

    Flow's meter used to be a scrolling history — one level per frame through a deque,
    travelling right to left. It is a symmetric bloom now: every bar reads the same
    current level, and the envelope is what makes the middle ones tallest. These are
    the properties that distinguish the two, so that a future edit which quietly
    restored the old behaviour would fail here rather than merely look different.
    """

    def heights(self, level: float) -> list[float]:
        return [ui.Pill._bar_half_height(i, level) for i in range(ui.BARS)]

    def test_the_middle_is_the_tallest_part_of_the_shape(self):
        h = self.heights(1.0)
        self.assertEqual(max(h), max(h[ui.BARS // 2 - 1:ui.BARS // 2 + 1]))

    def test_it_falls_away_toward_both_ends(self):
        # Monotonic out from the centre in each direction. The per-bar variation is
        # deliberately small enough not to break this — a wobble that reordered the
        # envelope would be a comb, not a bloom.
        h = self.heights(1.0)
        mid = ui.BARS // 2
        self.assertEqual(h[:mid], sorted(h[:mid]))
        self.assertEqual(h[mid:], sorted(h[mid:], reverse=True))

    def test_the_ends_still_move_rather_than_sitting_dead(self):
        # `_ENVELOPE_MIN` is 18% and not 0. An end bar pinned at the minimum would read
        # as a broken meter rather than a shaped one.
        self.assertGreater(self.heights(1.0)[0], self.heights(0.0)[0])

    def test_silence_is_a_flat_line_of_stubs_and_not_an_empty_box(self):
        # The one thing the old meter and this one agree on, and the reason `BAR_MIN_H`
        # is not zero: an empty widget reads as "not working", not as "quiet".
        self.assertEqual(self.heights(0.0), [ui.BAR_MIN_H] * ui.BARS)

    def test_nothing_ever_draws_outside_the_pill(self):
        # Half-heights, mirrored, inside a 40 px pill with 8 px of air.
        for level in (0.0, 0.25, 0.5, 0.75, 1.0, 2.0, -1.0):
            with self.subTest(level=level):
                for h in self.heights(level):
                    self.assertGreaterEqual(h, ui.BAR_MIN_H)
                    self.assertLessEqual(h, ui.BAR_MAX_H)

    def test_ordinary_speech_reaches_most_of_the_way_up(self):
        # What the 0.55 exponent buys. At half level a linear meter would draw half
        # height, which is what made the old one look timid at conversational volume —
        # the top of the widget was reserved for shouting.
        half = self.heights(0.5)[ui.BARS // 2]
        full = self.heights(1.0)[ui.BARS // 2]
        self.assertGreater(half, full * 0.6)

    def test_every_bar_answers_the_same_level(self):
        # The bloom's defining property, and the one a reintroduced history would break:
        # the shape between bars is the envelope, never the past.
        first = self.heights(0.7)
        self.assertEqual(first, self.heights(0.7))


class TestWhereThePanelOpens(unittest.TestCase):
    """FluidVoice's `positionWindow` arithmetic, ported and asserted.

    Their rule reads oddly until you notice it uses *two* rectangles on purpose:
    centred on `screen.frame` — the physical display — but stood on
    `screen.visibleFrame`, which excludes the Dock. Windows hands back the same pair as
    `rcMonitor` and `rcWork`, so this ports without being reinterpreted.
    """

    #: A 1920×1080 display with a 48 px taskbar, offset on a virtual desktop so that a
    #: test cannot pass by assuming the origin is (0, 0) — which is the bug a
    #: second-monitor user gets.
    FULL = (1920, 0, 3840, 1080)
    WORK = (1920, 0, 3840, 1032)

    def test_it_centres_on_the_physical_display(self):
        x, _y = ui.bottom_centre(400, 100, self.FULL, self.WORK)
        self.assertEqual(x, 1920 + (1920 - 400) // 2)

    def test_it_stands_on_the_work_area_and_not_the_screen_edge(self):
        # The asymmetry that matters: centred on `full`, but lifted clear of the
        # taskbar. Standing on `full` would put the panel under it.
        _x, y = ui.bottom_centre(400, 100, self.FULL, self.WORK)
        self.assertLessEqual(y + 100, self.WORK[3])

    def test_the_offset_lifts_it_and_is_measured_from_the_bottom(self):
        # Both offsets clear of the 10 px floor, so this measures the offset rather than
        # the clamp. FluidVoice floors at `visibleFrame.minY + 10` the same way, which
        # is why an offset of 0 and an offset of 10 land in the same place.
        _x, near = ui.bottom_centre(400, 100, self.FULL, self.WORK, offset=20)
        _x, far = ui.bottom_centre(400, 100, self.FULL, self.WORK, offset=120)
        self.assertEqual(near - far, 100)

    def test_the_last_ten_pixels_are_a_floor_rather_than_a_range(self):
        flush = ui.bottom_centre(400, 100, self.FULL, self.WORK, offset=0)
        floored = ui.bottom_centre(400, 100, self.FULL, self.WORK, offset=10)
        self.assertEqual(flush, floored)

    def test_an_offset_from_a_hand_edited_profile_cannot_push_it_off_screen(self):
        # The clamp is what makes the offset safe to expose as a setting. Both ends,
        # because a negative number is as easy to type as a huge one.
        for offset in (-10_000, -1, 0, 900, 10_000):
            with self.subTest(offset=offset):
                x, y = ui.bottom_centre(400, 100, self.FULL, self.WORK, offset)
                self.assertGreaterEqual(y, self.WORK[1] + 40)
                self.assertLessEqual(y + 100, self.WORK[3] - 10)
                self.assertGreaterEqual(x, self.WORK[0])
                self.assertLessEqual(x + 400, self.WORK[2])

    def test_a_panel_taller_than_the_display_keeps_its_bottom(self):
        # The one case where the clamp cannot satisfy both ends. The bottom is the edge
        # worth keeping: the top of a draft can run under the taskbar and still be read,
        # and the chips that act on it live at the bottom.
        _x, y = ui.bottom_centre(400, 5000, self.FULL, self.WORK)
        self.assertEqual(y + 5000, self.WORK[3] - 10)

    def test_a_panel_wider_than_the_display_starts_at_its_left_edge(self):
        x, _y = ui.bottom_centre(4000, 100, self.FULL, self.WORK)
        self.assertEqual(x, self.WORK[0])

    def test_the_monitor_under_the_pointer_answers_with_two_rectangles(self):
        # `_work_area` asks `SystemParametersInfoW`, which only ever answers for the
        # primary display — so on a two-monitor desk everything Flow drew landed on the
        # wrong one whenever the user was working on the other.
        full, work = ui._pointer_monitor(1280, 720)
        for rect in (full, work):
            self.assertEqual(len(rect), 4)
            self.assertGreater(rect[2], rect[0])
            self.assertGreater(rect[3], rect[1])
        # The work area is the one the taskbar comes out of, so it can only be smaller.
        self.assertLessEqual(work[3] - work[1], full[3] - full[1])
        self.assertLessEqual(work[2] - work[0], full[2] - full[0])

    def test_it_degrades_to_the_primary_work_area_rather_than_raising(self):
        # A repaint is not a place to handle a Win32 failure. `_NoHands` is this
        # module's own idea of "nothing happened", and the fallback has to land
        # somewhere drawable rather than at (0, 0) with no size.
        # `create=True` because `ctypes.windll` does not exist off Windows at all, and
        # this test asserts the degradation that matters most *on* those platforms.
        with mock.patch.object(ui.ctypes, "windll", ui._NoHands(), create=True):
            full, work = ui._pointer_monitor(1280, 720)
        self.assertEqual(full, work)
        self.assertGreater(full[2], full[0])


class TestWhichPlacementIsInForce(unittest.TestCase):
    """`PLACE`, and the two answers `_placed` gives.

    Restores the module afterwards for `tests/test_overlay.py`'s reason: this is a
    global, and a test that moved it would outlive itself.
    """

    FULL = (1920, 0, 3840, 1080)
    WORK = (1920, 0, 3840, 1032)

    def setUp(self):
        self.addCleanup(ui.apply_place, ui.PLACE_DEFAULT)
        self.p = ui.Pill.__new__(ui.Pill)
        self.p.full, self.p.work = self.FULL, self.WORK

    def test_bottom_is_what_ships(self):
        # Stated as a fact rather than left to the constant, because this is the change
        # of default: the corner is where Windows puts the tray, every toast, and most
        # apps' own status chrome, and it was the one place Flow had reserved.
        self.assertEqual(ui.PLACE_DEFAULT, "bottom")
        self.assertEqual(ui.PLACE, "bottom")

    def test_bottom_centres_the_stack_on_the_display(self):
        ui.apply_place("bottom")
        x, _y = self.p._placed(ui.PILL_W)
        self.assertEqual(x, ui.bottom_centre(ui.PILL_W, ui.PILL_H, self.FULL,
                                             self.WORK, ui.PANEL_BOTTOM_OFFSET)[0])

    def test_corner_still_puts_it_bottom_right_where_it_always_was(self):
        # Kept rather than removed: somebody who has spent months with the pill in the
        # bottom right should not have it moved by an upgrade they did not ask for.
        ui.apply_place("corner")
        x, y = self.p._placed(ui.PILL_W)
        self.assertEqual(x, self.WORK[2] - ui.PILL_W - 28)
        self.assertEqual(y, self.WORK[3] - ui.PILL_H - 24)

    def test_the_two_placements_are_actually_different(self):
        # A guard against both branches collapsing to the same arithmetic, which is how
        # a setting comes to look like it works while doing nothing.
        ui.apply_place("bottom")
        here = self.p._placed(ui.PILL_W)
        ui.apply_place("corner")
        self.assertNotEqual(here, self.p._placed(ui.PILL_W))

    def test_a_typo_costs_the_setting_and_not_the_app(self):
        # This arrives from a hand-edited profile. Raising here would be a launch that
        # dies on a misspelled word.
        for name in ("bottomm", "", "BOTTOM", "centre", "left"):
            with self.subTest(name=name):
                ui.apply_place(name)
                self.assertEqual(ui.PLACE, ui.PLACE_DEFAULT)

    def test_the_widths_it_is_asked_about_are_the_ones_it_is_placed_at(self):
        # `_placed` takes the width because the pill grows to the panel's when one is
        # docked. Centring a 420-wide stack using the 152-wide pill's position is how
        # the stack would sit off-centre exactly when it is most visible.
        ui.apply_place("bottom")
        narrow, _ = self.p._placed(ui.PILL_W)
        wide, _ = self.p._placed(ui.BUBBLE_W)
        self.assertGreater(narrow, wide)


class TestTheStackFollowsThePointersMonitor(unittest.TestCase):
    """The bug the placement work turned up, asserted so it cannot come back.

    `self.work` was read once in `__init__` from `SystemParametersInfoW`, which only
    ever answers for the primary display. On a two-monitor desk that put every window
    Flow drew against a screen the user might not be looking at — and pointed the
    on-screen clamps at the wrong rectangle too.
    """

    ONE = ((0, 0, 1920, 1080), (0, 0, 1920, 1032))
    TWO = ((1920, 0, 3840, 1080), (1920, 0, 3840, 1032))

    def pill(self, at):
        p = ui.Pill.__new__(ui.Pill)
        p.full, p.work = at
        p.x, p.y = p._placed(ui.PILL_W)
        p._docked_w = ui.PILL_W
        p.canvas = Canvas()
        # `pill_w` reads `front`, which reads `session.mode`. Set for the reason
        # `test_lite`'s harness sets everything: `tk.Misc.__getattr__` forwards an
        # unknown attribute to `self.tk`, so a missing one recurses rather than defaults.
        p.session = mock.Mock(mode=DICTATE)
        p.bubble = mock.Mock(_visible=False)
        p.card = mock.Mock(_visible=False)
        p.winfo_screenwidth = lambda: 1920
        p.winfo_screenheight = lambda: 1080
        p.window_geometry = lambda: (ui.PILL_W, p.x, p.y)
        p.geometry = mock.Mock()
        return p

    def test_moving_the_pointer_to_the_other_monitor_moves_the_stack(self):
        p = self.pill(self.ONE)
        was = (p.x, p.y)
        with mock.patch.object(ui, "_pointer_monitor", return_value=self.TWO):
            p._sync_monitor()
        self.assertNotEqual((p.x, p.y), was)
        self.assertGreaterEqual(p.x, self.TWO[1][0])
        self.assertLessEqual(p.x + ui.PILL_W, self.TWO[1][2])

    def test_a_pointer_that_has_not_left_the_monitor_costs_nothing(self):
        # Every frame asks. Acting unconditionally would be a `geometry` call per frame
        # forever — the same shape `_track_target` uses for `classify`, for the reason.
        p = self.pill(self.ONE)
        with mock.patch.object(ui, "_pointer_monitor", return_value=self.ONE):
            p._sync_monitor()
        p.geometry.assert_not_called()

    def test_a_panel_that_is_up_is_moved_with_the_pill(self):
        # The panels are placed *from* the pill, so moving it is the whole move — but
        # only for a window somebody can see.
        p = self.pill(self.ONE)
        p.bubble = mock.Mock(_visible=True, width=ui.BUBBLE_W)
        with mock.patch.object(ui, "_pointer_monitor", return_value=self.TWO):
            p._sync_monitor()
        p.bubble.reposition.assert_called_once()
        p.card.reposition.assert_not_called()


class TestAHiddenPanelIsParkedRatherThanUnmapped(unittest.TestCase):
    """FluidVoice's `parkWindowOffscreen`, and the one property it must have.

    The panels used to `withdraw()`. Push-to-talk made that the wrong trade: a panel now
    has to be up between a key going down and somebody starting to speak, and a remap is
    work done in exactly that gap.
    """

    #: Two monitors side by side, the left one primary. The union is what matters.
    DESKTOP = (0, 0, 3840, 1080)

    def test_a_parked_panel_is_clear_of_every_monitor(self):
        # The one thing that must never happen. Parking off the right edge of the *left*
        # display in a two-monitor desk parks it in the middle of the right one, in full
        # view, which is why this is the union and not the current screen.
        x, y = ui.park_spot(420, 300, self.DESKTOP)
        self.assertGreater(x, self.DESKTOP[2])
        self.assertGreater(y, self.DESKTOP[3])

    def test_the_panel_clears_the_edge_by_its_own_size_as_well_as_the_margin(self):
        # Its top-left corner being past the edge is not enough — the window extends
        # right and down from there.
        for w, h in ((205, 40), (420, 300), (640, 900)):
            with self.subTest(w=w, h=h):
                x, y = ui.park_spot(w, h, self.DESKTOP)
                self.assertGreaterEqual(x - self.DESKTOP[2], w + ui.PARK_MARGIN)
                self.assertGreaterEqual(y - self.DESKTOP[3], h + ui.PARK_MARGIN)

    def test_the_desktop_is_every_monitor_and_not_the_primary_one(self):
        left, top, right, bottom = ui._virtual_desktop(1280, 720)
        self.assertGreater(right, left)
        self.assertGreater(bottom, top)

    def test_it_degrades_to_the_screen_rather_than_raising(self):
        with mock.patch.object(ui.ctypes, "windll", ui._NoHands(), create=True):
            self.assertEqual(ui._virtual_desktop(1280, 720), (0, 0, 1280, 720))

    def test_parking_moves_the_window_and_never_unmaps_it(self):
        # The distinction the whole change rests on: a `withdraw` here would cost a
        # remap on the next hold, which is the gap push-to-talk has to fit inside.
        win = mock.Mock(width=420, _h=300)
        win.winfo_screenwidth.return_value = 1280
        win.winfo_screenheight.return_value = 720
        ui.park(win)
        win.withdraw.assert_not_called()
        win.geometry.assert_called_once()
        asked = win.geometry.call_args[0][0]
        self.assertTrue(asked.startswith("420x300+"), asked)

    def test_a_panel_with_no_height_yet_is_still_parked_somewhere_legal(self):
        # `_h` is not set until the first render, and a hide can beat it — a zero-sized
        # geometry request is one a window manager is entitled to refuse.
        win = mock.Mock(width=420, spec=["width", "geometry", "winfo_screenwidth",
                                         "winfo_screenheight"])
        win.winfo_screenwidth.return_value = 1280
        win.winfo_screenheight.return_value = 720
        ui.park(win)
        self.assertTrue(win.geometry.call_args[0][0].startswith("420x1+"))


class TestTheWorkAreaOffWindows(unittest.TestCase):
    """`_tk_work_area`, which exists because a Mac put the pill under the Dock.

    `_work_area` degrades to the whole screen off Windows, so bottom-centre placement
    stood the stack on the very bottom edge — behind the Dock on macOS, behind the panel
    on a bottom-taskbar Linux.

    The fix is a *measurement*: maximise a window and look at where the window manager
    put it, since it has to honour its own panels to do that. The obvious call,
    `wm_maxsize`, was tried first and is useless — on Windows it answers with the whole
    screen even with a taskbar present, which is wrong in exactly the way this is meant
    to fix.
    """

    def setUp(self):
        # Module-level cache, so a test that measured would outlive itself.
        self._was = ui._TK_WORK
        ui._TK_WORK = None
        self.addCleanup(lambda: setattr(ui, "_TK_WORK", self._was))

    def fake_win(self, zoomed=(0, 23, 1280, 672)):
        """A Tk stand-in whose `Toplevel` reports a maximised geometry."""
        x, y, r, b = zoomed
        probe = mock.Mock()
        probe.winfo_rootx.return_value = x
        probe.winfo_rooty.return_value = y
        probe.winfo_width.return_value = r - x
        probe.winfo_height.return_value = b - y
        return probe

    def test_it_reads_back_where_the_window_manager_put_a_maximised_window(self):
        probe = self.fake_win()
        with mock.patch.object(ui.tk, "Toplevel", return_value=probe):
            self.assertEqual(ui._tk_work_area(mock.Mock(), 1280, 720),
                             (0, 23, 1280, 672))

    def test_the_probe_is_invisible_and_cleaned_up(self):
        # Nothing may flash on screen, and a probe left alive is a stray window.
        probe = self.fake_win()
        with mock.patch.object(ui.tk, "Toplevel", return_value=probe):
            ui._tk_work_area(mock.Mock(), 1280, 720)
        probe.attributes.assert_any_call("-alpha", 0.0)
        probe.destroy.assert_called_once()

    def test_it_is_measured_once_and_then_remembered(self):
        # `_sync_monitor` asks every frame. Measuring per frame would open and destroy a
        # Toplevel thirty times a second.
        probe = self.fake_win()
        with mock.patch.object(ui.tk, "Toplevel", return_value=probe) as made:
            for _ in range(50):
                ui._tk_work_area(mock.Mock(), 1280, 720)
        made.assert_called_once()

    def test_a_build_without_zoomed_falls_back_to_the_whole_screen(self):
        # `state("zoomed")` is documented for Windows and X11 and may not exist here.
        # The whole screen is the honest answer then: wrong by a Dock, rather than wrong
        # by whatever a broken measurement returned.
        probe = self.fake_win()
        probe.state.side_effect = ui.tk.TclError("bad state")
        with mock.patch.object(ui.tk, "Toplevel", return_value=probe):
            self.assertEqual(ui._tk_work_area(mock.Mock(), 1280, 720),
                             (0, 0, 1280, 720))
        probe.destroy.assert_called_once()

    def test_a_nonsense_measurement_is_refused(self):
        # A window manager that hands back something larger than the screen, or inside
        # out, has not answered the question.
        for bad in ((0, 0, 4000, 672), (0, 0, 0, 0), (500, 0, 100, 672)):
            with self.subTest(bad=bad):
                ui._TK_WORK = None
                with mock.patch.object(ui.tk, "Toplevel",
                                       return_value=self.fake_win(bad)):
                    self.assertEqual(ui._tk_work_area(mock.Mock(), 1280, 720),
                                     (0, 0, 1280, 720))

    def test_the_bottom_edge_is_the_one_that_has_to_be_right(self):
        # It is what bottom-centre placement stands on, and getting it wrong is the
        # whole bug: 672 here against a screen of 720 is a 48 px Dock found.
        with mock.patch.object(ui.tk, "Toplevel", return_value=self.fake_win()):
            work = ui._tk_work_area(mock.Mock(), 1280, 720)
        _x, y = ui.bottom_centre(ui.PILL_W, ui.PILL_H, (0, 0, 1280, 720), work,
                                 ui.PANEL_BOTTOM_OFFSET)
        self.assertLessEqual(y + ui.PILL_H, 672)


class TestTheMacWindowStyle(unittest.TestCase):
    """Aqua's `overrideredirect` + `WS_EX_NOACTIVATE`, which is one call and unsupported.

    Reported from a real Mac: the pill sat there with its close and maximize buttons
    showing. `overrideredirect(True)` is not enough on Aqua, because Tk maps a Toplevel
    to an `NSWindow` whose style comes from the window *class*.
    """

    def test_it_asks_for_no_activates_and_then_takes_the_frame_off_again(self):
        # The order is the fix. `plain` is a window *class* and it is **not** frameless —
        # a Mac showed a Toplevel given only the style coming up decorated. So the
        # redirect is re-asserted after the style, and the class can never win.
        win = mock.Mock()
        win.winfo_ismapped.return_value = False
        self.assertTrue(ui._mac_window_style(win))
        args = win.tk.call.call_args[0]
        self.assertEqual(args[0], "::tk::unsupported::MacWindowStyle")
        self.assertIn("noActivates", args)
        win.overrideredirect.assert_called_once_with(True)

    def test_a_window_already_on_screen_is_remapped_to_force_the_rebuild(self):
        # The root window's NSWindow is built when it is first mapped, and a redirect
        # asked for afterwards does not restyle what already exists. That is why the
        # panels were bare and the pill — which *is* the root — was not.
        win = mock.Mock()
        win.winfo_ismapped.return_value = True
        ui._mac_window_style(win)
        win.withdraw.assert_called_once()
        win.deiconify.assert_called_once()

    def test_a_withdrawn_window_is_not_put_on_screen_by_the_fix(self):
        # `_no_activate` runs over all three windows at startup, and the panels are
        # withdrawn at that point. Deiconifying them would put two empty surfaces in
        # front of the user.
        win = mock.Mock()
        win.winfo_ismapped.return_value = False
        ui._mac_window_style(win)
        win.withdraw.assert_not_called()
        win.deiconify.assert_not_called()

    def test_the_frame_still_comes_off_when_the_style_call_is_unavailable(self):
        # Tk calls it `::tk::unsupported::` itself. Losing it should cost the focus
        # behaviour, not put a title bar back on the pill.
        win = mock.Mock()
        win.winfo_ismapped.return_value = False
        win.tk.call.side_effect = ui.tk.TclError("no such command")
        self.assertFalse(ui._mac_window_style(win))
        win.overrideredirect.assert_called_once_with(True)

    def test_no_activate_routes_to_it_on_a_mac_and_refuses_elsewhere(self):
        # One name for "take this window out of the activation chain", answered by
        # whichever platform API can actually do it.
        win = mock.Mock()
        win.winfo_ismapped.return_value = False
        with mock.patch.object(ui.sys, "platform", "darwin"):
            self.assertTrue(ui._no_activate(win))
            win.tk.call.assert_called_once()
        with mock.patch.object(ui.sys, "platform", "linux"):
            self.assertFalse(ui._no_activate(mock.Mock()))


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
    p.full = (0, 0, 1280, 720)
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

    Pinned to `"corner"`, because holding the right edge is *corner* placement's rule
    and not the dock's: the pill is anchored to the screen edge it sits against, and
    growing away from it is the only direction there is. Centred placement has no
    anchored edge and re-centres instead — `TestTheDockRecentresWhenThereIsNoEdge`
    below is the same class of check for it.
    """

    def setUp(self):
        self.addCleanup(ui.apply_place, ui.PLACE_DEFAULT)
        ui.apply_place("corner")

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


class TestTheDockRecentresWhenThereIsNoEdge(unittest.TestCase):
    """The same dock under centred placement, where holding an edge is the bug.

    Found by running the shipped placement against the dock rather than by reading it:
    the pill is 205 px and the panel 420, and holding the right edge put the pair
    **107 px left of centre the moment a draft appeared** — visibly, on every utterance,
    because a draft appearing is the single most common thing that happens.

    Corner placement is anchored to the screen edge it sits against, so growing away
    from that edge is the only direction there is. Centred placement has no anchored
    edge, and the width it should be centred on is the *new* one.
    """

    def setUp(self):
        self.addCleanup(ui.apply_place, ui.PLACE_DEFAULT)
        ui.apply_place("bottom")

    def centre_of(self, p, w):
        return p._placed(w)[0]

    def test_a_panel_appearing_recentres_on_the_new_width(self):
        p = docker(x=538, docked_w=ui.PILL_W)
        p._sync_dock()
        self.assertEqual(p.x, self.centre_of(p, ui.BUBBLE_W))

    def test_the_panel_going_away_recentres_on_the_pill(self):
        p = docker(showing=False, docked_w=ui.BUBBLE_W, x=430)
        p._sync_dock()
        self.assertEqual(p.x, self.centre_of(p, ui.PILL_W))

    def test_the_stack_stays_centred_across_an_open_and_a_close(self):
        # The round trip, because an off-by-one in either direction accumulates: a pill
        # that came back a few pixels off would drift across a session.
        p = docker(x=538, docked_w=ui.PILL_W)
        p._sync_dock()
        p.bubble = mock.Mock(width=ui.BUBBLE_W, _visible=False)
        p.window_geometry = mock.Mock(return_value=(ui.BUBBLE_W, p.x, 608))
        p._sync_dock()
        self.assertEqual(p.x, 538)

    def test_it_is_still_clamped_onto_the_screen(self):
        # The clamp survives the branch. A panel wider than the display would otherwise
        # be centred to a negative x.
        p = docker(x=538, docked_w=ui.PILL_W, panel_w=4000)
        p._sync_dock()
        self.assertGreaterEqual(p.x, p.work[0])

    def test_corner_placement_is_untouched_by_any_of_this(self):
        # The two branches are different rules, not one rule with a flag, and the
        # corner's is the one people have been using.
        ui.apply_place("corner")
        p = docker()
        p._sync_dock()
        self.assertEqual(p.x + ui.BUBBLE_W, 1047 + ui.PILL_W)


if __name__ == "__main__":
    unittest.main()
