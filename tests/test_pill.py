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
from flow.session import CONVERSE, DICTATE, REFINE, State  # noqa: E402


class Canvas:
    """Records the four primitives `Pill._draw` uses, with their geometry."""

    def __init__(self) -> None:
        self.texts: list[tuple[float, float, str, str]] = []
        self.ovals: list[tuple[float, float, float, float, str]] = []
        self.rects: list[tuple[float, float, float, float, str]] = []
        self.lines: list[tuple[tuple, str]] = []
        #: (tag, sequence, callback) per `tag_bind`. The row grew hit regions when the
        #: settings, voice and mode icons moved onto it, and a click that reaches nothing
        #: is the failure worth asserting against.
        self.bindings: list[tuple] = []
        self.polys: list[tuple] = []
        self.arcs: list[tuple] = []

    def tag_bind(self, tag, sequence, callback) -> None:
        self.bindings.append((tag, sequence, callback))

    def delete(self, *a, **kw) -> None: ...

    #: `_sync_shell` places this canvas at the foot of a window whose top edge moves
    #: when a panel opens. Recorded rather than ignored, so a test can check the row
    #: really is at the bottom of whatever height the shell currently is.
    def place(self, **kw) -> None:
        self.placed = kw

    #: `_sync_dock` resizes the canvas when a panel docks or goes away. Accepted and
    #: recorded rather than ignored, so a test can tell a widened pill from a moved one.
    def configure(self, **kw) -> None:
        self.width = kw.get("width", getattr(self, "width", None))

    def create_polygon(self, *a, **kw) -> None:
        self.polys.append((a, kw.get("fill", "")))

    def create_arc(self, *a, **kw) -> None:
        self.arcs.append((a, kw.get("outline", "")))

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

    def test_it_is_drawn_a_character_at_a_time_on_one_pitch(self):
        # Tk has no letter-spacing, so `_draw` places each glyph itself and the pitch
        # is this module's to choose. §02's `+.1em` tracking was retired by the compact
        # pass — the 7 px it cost the slot went to the command marks the row carries —
        # so the pitch is exactly the advance now, and a test that demanded tracking
        # would be asking for the room back.
        p = pill(State.DRAFT, _docked_w=ui.PILL_W, _flash=0, _tint=0.0)
        p._draw()
        xs = label_xs(p)
        self.assertEqual(len(xs), len("HELD"))
        gaps = {round(b - a) for a, b in zip(xs, xs[1:])}
        self.assertEqual(gaps, {ui.LABEL_PITCH})
        self.assertEqual(ui.LABEL_PITCH, ui.LABEL_ADV)

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
        # The mic's capsule sits left of the meter, past the app slot the CLI's name
        # takes in converse. Read off arcs and lines rather than an oval since the
        # glyph language changed: `glyphs.mic` strokes its capsule from arcs and
        # straight runs where the shipped mic used to fill an oval.
        left = ui.METER_X + p._row_shift()
        mic = {colour for coords, colour in p.canvas.arcs + p.canvas.lines
               if max(coords[0::2]) < left}
        self.assertEqual(mic, {half})


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
        p.bubble = mock.Mock(_visible=True, width=ui.BUBBLE_W, _h=ui.PANEL_MAX_H)
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


class TestTheWindowsOnlyAttributes(unittest.TestCase):
    """`-transparentcolor` and `-toolwindow` exist on one platform and are fatal on the
    others: `bad attribute "-transparentcolor"` out of Tk, raised before a window has
    been drawn.

    The guard used to be `lite` alone, because `__main__` forces lite mode off Windows
    (`lite = args.lite or sys.platform != "win32"`) so the two could not come apart. They
    came apart as soon as something other than `__main__` built a `Pill`:
    `scripts/mac_report.py` asked for full mode on a Mac and the report died in the
    constructor.
    """

    def test_full_mode_off_windows_asks_for_neither(self):
        win = mock.Mock()
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(ui._shell_window(win, lite=False, alpha=0.94), ui.SHELL)
        asked = [c.args[0] for c in win.attributes.call_args_list]
        self.assertNotIn("-transparentcolor", asked)
        self.assertNotIn("-toolwindow", asked)

    def test_full_mode_on_windows_still_asks_for_both(self):
        # The keyed colour is how the pill has no rectangle around it. Losing this on
        # Windows would be a visible regression, not a quiet one.
        win = mock.Mock()
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(ui._shell_window(win, lite=False, alpha=0.94),
                             ui.TRANSPARENT)
        win.attributes.assert_any_call("-transparentcolor", ui.TRANSPARENT)
        win.attributes.assert_any_call("-toolwindow", True)

    def test_the_shared_two_are_asked_for_everywhere(self):
        for platform in ("darwin", "win32", "linux"):
            with self.subTest(platform=platform):
                win = mock.Mock()
                with mock.patch.object(sys, "platform", platform):
                    ui._shell_window(win, lite=True, alpha=0.5)
                win.attributes.assert_any_call("-topmost", True)
                win.attributes.assert_any_call("-alpha", 0.5)


class TestTakingTheFrameOff(unittest.TestCase):
    """`_bare_window`, and why Aqua does not get `overrideredirect`.

    Two faults reported from a Mac - click the app you want to dictate into and Flow's
    window vanishes, and clicking Send does nothing - and one cause. Six variants were
    put on screen and the results split on exactly this line: every window without
    `overrideredirect` kept its place when another app came forward and had its button
    reached by a click, and every window with it was deaf and gone.

    A style mask with no bits is the replacement. `titled` is the bit that puts a title
    bar on, so a mask with none is bare, and nothing else about the window has been given
    away. Measured at 0 px of decoration on a Mac against the control's 28.
    """

    def test_aqua_asks_for_an_empty_style_mask_and_not_overrideredirect(self):
        win = mock.Mock()
        with mock.patch.object(sys, "platform", "darwin"):
            ui._bare_window(win)
        win.wm_attributes.assert_called_once_with("-stylemask", "")
        win.overrideredirect.assert_not_called()

    def test_everywhere_else_is_unchanged(self):
        # `-stylemask` is an Aqua attribute. Windows and X11 have never needed it, and
        # `overrideredirect` is not the cause of anything there.
        for platform in ("win32", "linux"):
            with self.subTest(platform=platform):
                win = mock.Mock()
                with mock.patch.object(sys, "platform", platform):
                    ui._bare_window(win)
                win.overrideredirect.assert_called_once_with(True)
                win.wm_attributes.assert_not_called()

    def test_a_mac_on_tk_8_6_falls_back_rather_than_wearing_a_title_bar(self):
        # `-stylemask` arrived in Tk 9. Older builds should get the behaviour they
        # always had, which is imperfect but not a window with a frame on it.
        win = mock.Mock()
        win.wm_attributes.side_effect = ui.tk.TclError("bad attribute")
        with mock.patch.object(sys, "platform", "darwin"):
            ui._bare_window(win)
        win.overrideredirect.assert_called_once_with(True)

    def test_every_window_flow_owns_goes_through_it(self):
        # The pill, the bubble, the card and the help panel all build their shell here,
        # and a window that missed this would be the one wearing a frame.
        win = mock.Mock()
        with mock.patch.object(sys, "platform", "darwin"),                 mock.patch.object(ui, "_bare_window") as bare:
            ui._shell_window(win, lite=True, alpha=0.9)
        bare.assert_called_once_with(win)


class TestTheWorkAreaOnAqua(unittest.TestCase):
    """`_aqua_work_area`, which exists because the maximise probe is ignored on a Mac.

    A Mac reported `_tk_work_area()` answering with the whole 1352x878 screen, identical
    to `_work_area()`. `state("zoomed")` had neither raised nor maximised — asked to
    maximise a 200x120 window at +80+80 it returned the same window at +80+80, and no
    error — so the fallback did not fall back, `bottom_centre` stood the pill 24 px above
    878, and the pill sat inside an 85 px Dock.

    `wm maxsize` is the instrument here and *only* here: Tk's Aqua port answers it from
    `[NSScreen visibleFrame]`. On Windows the same call reports the whole screen with a
    taskbar present, which is the reason the maximise probe exists at all.
    """

    def setUp(self):
        self._was = ui._TK_WORK
        ui._TK_WORK = None
        self.addCleanup(lambda: setattr(ui, "_TK_WORK", self._was))

    def win(self, maxsize=(1352, 735), title=28, menu=30):
        """The numbers a 14-inch MacBook Pro actually reported, not invented ones.

        `scripts/mac_area_probe.py` on darwin, Tk 9.0.3, a 1352x878 screen: a titled
        probe asked for +80+300 landing at y 328, so a 28 px title bar; the same probe
        asked for +0+0 landing at y 58, so a 30 px menu bar under it; and `maxsize`
        1352x735, which plus the title bar is a 763 px visible frame.
        """
        probe = mock.Mock()
        probe.maxsize.return_value = maxsize
        seen = []

        def geometry(spec):
            seen.append(spec)

        def rooty():
            # +80+300 first, then +0+0 - the order the function asks in.
            return ui._AQUA_FREE_Y + title if len(seen) == 1 else menu + title

        probe.geometry.side_effect = geometry
        probe.winfo_rooty.side_effect = rooty
        return mock.Mock(), probe

    def call(self, win, probe, sw=1352, sh=878):
        with mock.patch.object(ui.tk, "Toplevel", return_value=probe):
            return ui._aqua_work_area(win, sw, sh)

    def test_the_bottom_is_the_top_of_the_dock(self):
        # The whole point: 793, not 878. The pill stands on this number.
        win, probe = self.win()
        self.assertEqual(self.call(win, probe), (0, 30, 1352, 793))

    def test_the_dock_it_finds_matches_the_dock_the_os_reports(self):
        """85 px of Dock, against a `com.apple.dock tilesize` of 69 read separately.

        The reason this platform is believed at all now. `maxsize`, the title bar and the
        menu bar are all Tk asking Tk; a tile size out of `defaults` came from somewhere
        else entirely, and 69 plus Apple's padding is the 85 this leaves. Three earlier
        guesses at Aqua all failed for want of a second source.
        """
        win, probe = self.win()
        self.assertEqual(878 - self.call(win, probe)[3], 85)

    def test_the_title_bar_is_added_back_to_the_content_size(self):
        """The bug this shape was written to make impossible.

        `maxsize` is a maximum *content* size, short by whatever decoration its window
        wears — 735 from a titled probe against 763 from the `overrideredirect` pill on
        the same display. The first version took the origin from a probe and the size
        from the caller's window, counted the 28 px title bar twice, and put the work
        area at 821: the pill moved off the Dock and straight back onto it.

        One probe answers everything, so its decoration appears on both sides and
        cancels. A window with no title bar at all must land on the same answer.
        """
        win, bare = self.win(maxsize=(1352, 763), title=0)
        self.assertEqual(self.call(win, bare), (0, 30, 1352, 793))

    def test_the_probe_is_invisible_and_cleaned_up(self):
        win, probe = self.win()
        self.call(win, probe)
        probe.attributes.assert_any_call("-alpha", 0.0)
        probe.destroy.assert_called_once()

    def test_a_maxsize_of_the_whole_screen_means_it_does_not_know(self):
        # Windows answers this way with a taskbar present. Reporting the whole screen as
        # a work area is the bug, not a fix for it.
        win, probe = self.win(maxsize=(1352, 878), title=0, menu=0)
        self.assertIsNone(self.call(win, probe))

    def test_a_window_manager_that_honoured_plus_zero_is_not_a_menu_bar(self):
        # Windows puts a window where it is asked. A number far outside a menu bar's
        # range is a literal placement, and nothing here can be believed.
        win, probe = self.win(menu=400)
        self.assertIsNone(self.call(win, probe))

    def test_a_title_bar_too_tall_to_be_one_is_refused(self):
        win, probe = self.win(title=200)
        self.assertIsNone(self.call(win, probe))

    def test_measurements_that_disagree_about_the_display_are_refused(self):
        # A menu bar plus a visible frame cannot be taller than the display it is on.
        win, probe = self.win(maxsize=(1352, 870))
        self.assertIsNone(self.call(win, probe))

    def test_a_build_without_maxsize_says_so(self):
        win, probe = self.win()
        probe.maxsize.side_effect = ui.tk.TclError("no such command")
        self.assertIsNone(self.call(win, probe))

    def test_a_probe_that_cannot_be_built_says_so(self):
        win, _probe = self.win()
        with mock.patch.object(ui.tk, "Toplevel", side_effect=ui.tk.TclError("no")):
            self.assertIsNone(ui._aqua_work_area(win, 1352, 878))

    def test_tk_work_area_prefers_it_on_darwin(self):
        win, probe = self.win()
        with mock.patch.object(sys, "platform", "darwin"),                 mock.patch.object(ui.tk, "Toplevel", return_value=probe):
            self.assertEqual(ui._tk_work_area(win, 1352, 878), (0, 30, 1352, 793))

    def test_and_falls_through_to_the_maximise_probe_when_it_declines(self):
        # The guarantee that made this safe to write before a Mac had confirmed it: if
        # the Aqua path cannot answer, the worst case is exactly the old behaviour.
        win, probe = self.win(maxsize=(1352, 878), title=0, menu=0)
        probe.winfo_rootx.return_value = 0
        probe.winfo_rooty.side_effect = None
        probe.winfo_rooty.return_value = 30
        probe.winfo_width.return_value = 1352
        probe.winfo_height.return_value = 763
        with mock.patch.object(sys, "platform", "darwin"),                 mock.patch.object(ui.tk, "Toplevel", return_value=probe):
            self.assertEqual(ui._tk_work_area(win, 1352, 878), (0, 30, 1352, 793))

    def test_windows_never_takes_this_path(self):
        # `maxsize` there is the whole screen, taskbar or not. Asking it would undo the
        # measurement this module went to the trouble of making.
        win, probe = self.win()
        with mock.patch.object(sys, "platform", "win32"),                 mock.patch.object(ui, "_aqua_work_area") as aqua,                 mock.patch.object(ui.tk, "Toplevel", return_value=probe):
            probe.winfo_rootx.return_value = 0
            probe.winfo_rooty.side_effect = None
            probe.winfo_rooty.return_value = 23
            probe.winfo_width.return_value = 1280
            probe.winfo_height.return_value = 649
            ui._tk_work_area(win, 1280, 720)
        aqua.assert_not_called()


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
        # **Says which platform it is testing rather than inheriting the host's.**
        # `_tk_work_area` short-circuits into `_aqua_work_area` on darwin, so on a Mac
        # these ran the branch above the one they describe: two Toplevels per call
        # instead of one, and every count here off by the probe nobody meant to make.
        # On Windows the same tests passed, which is how a suite named "off Windows"
        # came to be verified only there. Linux is the platform whose answer this path
        # actually is; the aqua path has its own tests.
        platform = mock.patch.object(ui.sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)

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

    def test_a_probe_that_was_never_maximised_is_refused(self):
        # The one that got through, and put the pill in the top-left corner of a Mac.
        # `state("zoomed")` on Aqua does not raise and does not maximise either: it is
        # accepted and ignored, so the probe stayed the 200x120 it was asked for and
        # that rectangle was believed.
        ui._TK_WORK = None
        with mock.patch.object(ui.tk, "Toplevel",
                               return_value=self.fake_win((80, 80, 280, 200))):
            self.assertEqual(ui._tk_work_area(mock.Mock(), 1512, 982),
                             (0, 0, 1512, 982))

    def test_a_window_grown_only_a_little_is_refused_too(self):
        # The other hole: a window manager that honoured `zoomed` partially. A real work
        # area is the screen minus a Dock or a taskbar, nowhere near half of it.
        ui._TK_WORK = None
        with mock.patch.object(ui.tk, "Toplevel",
                               return_value=self.fake_win((0, 0, 700, 400))):
            self.assertEqual(ui._tk_work_area(mock.Mock(), 1512, 982),
                             (0, 0, 1512, 982))

    def test_the_fallback_still_puts_the_stack_on_screen(self):
        # Refusing the measurement must not mean refusing to place anything. The whole
        # screen is wrong by a Dock; the top-left corner is wrong by a screen.
        ui._TK_WORK = None
        with mock.patch.object(ui.tk, "Toplevel",
                               return_value=self.fake_win((80, 80, 280, 200))):
            work = ui._tk_work_area(mock.Mock(), 1512, 982)
        x, y = ui.bottom_centre(ui.PILL_W, ui.PILL_H, (0, 0, 1512, 982), work,
                                ui.PANEL_BOTTOM_OFFSET)
        self.assertGreater(y, 982 * 0.8, "the stack is nowhere near the bottom")
        self.assertGreater(x, 1512 * 0.3, "the stack is nowhere near the centre")

    def test_the_bottom_edge_is_the_one_that_has_to_be_right(self):
        # It is what bottom-centre placement stands on, and getting it wrong is the
        # whole bug: 672 here against a screen of 720 is a 48 px Dock found.
        with mock.patch.object(ui.tk, "Toplevel", return_value=self.fake_win()):
            work = ui._tk_work_area(mock.Mock(), 1280, 720)
        _x, y = ui.bottom_centre(ui.PILL_W, ui.PILL_H, (0, 0, 1280, 720), work,
                                 ui.PANEL_BOTTOM_OFFSET)
        self.assertLessEqual(y + ui.PILL_H, 672)


class TestTheMacFrame(unittest.TestCase):
    """What strips the frame on Aqua, asserted as the absence of two wrong answers.

    A Mac reported the pill wearing a title bar and three traffic lights while the
    panels above it were bare, and two fixes were tried before the right one. Both are
    pinned here because both looked correct and each broke something else:

      **`MacWindowStyle plain` is not frameless.** `plain` is a window *class*, and a
      Toplevel given only that style comes up decorated - settled on a real machine by
      `scripts/mac_frame_probe.py`. Asked for on a mapped window it put the frame back.

      **`noActivates` is worse.** It takes the window out of the activation chain, and a
      window that never activates does not take clicks: Send stopped working. `_menu`
      already depended on the opposite, and says so.

    What was left after removing both is the line that had been doing the work all
    along, which is why this class asserts an absence rather than a mechanism.
    """

    def source(self) -> str:
        return (Path(__file__).resolve().parent.parent
                / "flow" / "ui.py").read_text(encoding="utf-8")

    def test_nothing_asks_aqua_for_a_window_class(self):
        # Asserted over the source because the mistake is *making the call at all*, and
        # a mock cannot notice a call that is no longer there. The name still appears in
        # prose explaining why it is not used - those comments are the point of this
        # test, so what is checked is the invocation.
        for line in self.source().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("*"):
                continue
            with self.subTest(line=stripped[:60]):
                self.assertNotIn("::tk::unsupported::", line)

    def test_no_window_is_withdrawn_and_remapped_to_restyle_it(self):
        # The second wrong answer. It was solving a problem the first one created, and
        # on a real Mac it left the window hidden after the remap - shown, then gone.
        self.assertNotIn("_mac_reframe", self.source())

    def test_no_activate_refuses_off_windows_because_the_app_depends_on_it(self):
        # `_menu` borrows the foreground on Windows precisely because a non-activating
        # window gets no input for its popup, and states that Lite needs none of that.
        # Asking Aqua for the equivalent broke Send.
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform):
                with mock.patch.object(ui.sys, "platform", platform):
                    self.assertFalse(ui._no_activate(mock.Mock()))

    def test_the_shell_still_asks_for_the_one_thing_that_works(self):
        """On Tk 9 that is `-stylemask`; on 8.6, which has none, `overrideredirect`.

        Pinned to darwin rather than left to the host, and the drift is why: on Windows
        the darwin branch never ran, so this asserted `overrideredirect` and passed — and
        on a Mac, where a Mock answers `wm_attributes` happily, the function returned at
        the style mask and `overrideredirect` was never reached. A test in a class called
        `TestTheMacFrame` was checking the frame every platform *but* a Mac gets.
        """
        with mock.patch.object(ui.sys, "platform", "darwin"):
            win = mock.Mock()
            ui._shell_window(win, lite=True, alpha=0.94)
            win.wm_attributes.assert_any_call("-stylemask", "")
            win.overrideredirect.assert_not_called()

            # Tk 8.6 has no style masks, and a Mac on it must still lose its title bar.
            old = mock.Mock()
            old.wm_attributes.side_effect = ui.tk.TclError("no such attribute")
            ui._shell_window(old, lite=True, alpha=0.94)
            old.overrideredirect.assert_called_once_with(True)


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
    # `_h` is a real int: the shell is sized from the band's actual height now, so a
    # Mock there would put a Mock into the arithmetic.
    p.bubble = mock.Mock(width=panel_w, _visible=showing, _h=ui.PANEL_MAX_H)
    p.card = mock.Mock(width=panel_w, _visible=False, _h=ui.PANEL_MAX_H)
    p.work = (0, 0, 1280, 720)
    p.full = (0, 0, 1280, 720)
    p.x, p.y = x, 608
    p._docked_w = docked_w
    p.geometry = mock.Mock()
    p.window_geometry = mock.Mock(
        return_value=window if window is not None else (docked_w, x, 608))
    return p


class TestTheShellIsOneWindow(unittest.TestCase):
    """`_sync_shell`, which is what `_sync_dock` became when the dock stopped existing.

    The pill and its panel used to be two windows kept adjacent by hand, and
    `scripts/reel.py` once caught them **215 px apart, for five seconds**: the resize had
    landed and the matching move had not, and the pill's remembered width then answered
    "nothing to do" on every frame after. That failure needs two windows to be possible.
    There is one now, and all that arithmetic has collapsed into a height.

    What the two classes here used to cover — holding the right edge in corner placement,
    re-centring on the new width in bottom placement, the 107 px lurch when a draft
    appeared — is gone with the width change that caused it. The pill is the panel's
    width whether a panel is up or not.
    """

    def setUp(self):
        self.addCleanup(ui.apply_place, ui.PLACE_DEFAULT)
        ui.apply_place("bottom")

    def asked(self, p):
        w, _, rest = p.geometry.call_args.args[0].partition("x")
        h, _, _pos = rest.partition("+")
        return int(w), int(h)

    def test_a_panel_opening_grows_the_window_upward(self):
        # The band reports its own height now that it is snug around its content, so the
        # shell is the row plus whatever that is — bounded by the ceiling.
        p = docker(showing=True)
        p._sync_shell()
        self.assertEqual(self.asked(p), (ui.BUBBLE_W, ui.PANEL_MAX_H + ui.PILL_H))

    def test_the_shell_follows_the_band_rather_than_its_ceiling(self):
        # A shell sized to the ceiling leaves the row floating below a shorter band,
        # which is the detached-boxes look the merge exists to end. Caught in a shot.
        p = docker(showing=True)
        p.bubble._h = 130
        p._sync_shell()
        self.assertEqual(self.asked(p), (ui.BUBBLE_W, 130 + ui.PILL_H))

    def test_and_the_foot_does_not_move_when_it_does(self):
        """The whole of "the controls stay where they are", as arithmetic.

        Send, the meter and the chip row are laid out from the bottom of the window. A
        shell that grew downward — or that centred its growth — would move every one of
        them every time a draft appeared, which is the motion this work exists to end.
        """
        idle = docker(showing=False)
        idle._sync_shell()
        opened = docker(showing=True)
        opened._sync_shell()
        self.assertEqual(idle.y + idle._shell_h, opened.y + opened._shell_h)

    def test_an_idle_pill_is_just_the_row(self):
        p = docker(showing=False)
        p._sync_shell()
        self.assertEqual(p._shell_h, ui.PILL_H)

    def test_nothing_is_asked_for_twice_when_the_window_already_agrees(self):
        # Idempotent, so it can run from the frame pump and from a panel's `reposition`
        # without either caring which got there first.
        p = docker(showing=False, x=538)
        p._sync_shell()
        p.window_geometry = mock.Mock(return_value=(ui.BUBBLE_W, p.x, p.y))
        p.geometry.reset_mock()
        for _ in range(5):
            p._sync_shell()
        p.geometry.assert_not_called()

    def test_a_window_that_drifted_is_asked_again(self):
        # `reel.py`'s defect, in the only form it can still take. Compared against the
        # *window* rather than against a remembered value: state saying the move happened
        # is not evidence that it did.
        p = docker(showing=True, window=(ui.BUBBLE_W, 4, 4))
        p._sync_shell()
        p.geometry.assert_called_once()

    def test_the_shell_is_clamped_onto_the_screen(self):
        p = docker(showing=True)
        p.work = p.full = (0, 0, 300, 200)
        p._sync_shell()
        self.assertGreaterEqual(p.x, 0)
        self.assertGreaterEqual(p.y, 0)
        self.assertLessEqual(p.y + p._shell_h, 200)

    def test_a_panel_size_change_takes_the_row_with_it(self):
        """The panel-size setting rebinds `BUBBLE_W` while Flow is running, so the width
        changes with nothing else changing beside it.

        Left out of the comparison, the row kept the width it was built at while the band
        above it took the new one — two boxes of different widths stacked in one window,
        which is what a screenshot of "panel size: larger" showed. `_docked_w` is what
        `_draw` measures the row against, so it moves in the same breath as the canvas.
        """
        self.addCleanup(ui.apply_panel_width, ui.PANEL_WIDTHS["regular"])
        p = docker(showing=False, x=430)
        p._sync_shell()
        p.geometry.reset_mock()
        ui.apply_panel_width(ui.PANEL_WIDTHS["larger"])
        p.window_geometry = mock.Mock(return_value=(ui.PANEL_WIDTHS["regular"],
                                                    p.x, p.y))
        p._sync_shell()
        self.assertEqual(p._docked_w, ui.PANEL_WIDTHS["larger"])
        self.assertEqual(p.canvas.place.call_args.kwargs["width"],
                         ui.PANEL_WIDTHS["larger"])
        self.assertIn(str(ui.PANEL_WIDTHS["larger"]), p.geometry.call_args.args[0])

    def test_the_row_is_placed_at_the_foot_of_whatever_height_it_is(self):
        # The canvas is the bottom band of the window, not the whole of it — which is
        # what makes "the foot never moves" true of the pixels and not just of the frame.
        for showing in (False, True):
            with self.subTest(showing=showing):
                p = docker(showing=showing)
                p._sync_shell()
                kw = p.canvas.place.call_args.kwargs
                self.assertEqual(kw["y"] + kw["height"], p._shell_h)


class TestTheRowIcons(unittest.TestCase):
    """Settings, voice and mode, between the meter and the status word.

    **These were a strip of words above the draft first.** Written from "Dictate and
    Converse for sure Then workspace and voices", it put a chip and two labels across the
    top of the panel — and on seeing it the owner's answer was "Not looking good instead
    after progress bar add settings icon ... and top you can remove it". Words that name
    a setting are a sentence *about* the app; the row is where the app already says what
    it is doing with a drawn mic and a drawn meter, and three more drawn marks belong
    there. It costs nothing at rest, too, which the strip could not — the row is on
    screen either way.
    """

    def row(self, **session):
        c = Canvas()
        p = ui.Pill.__new__(ui.Pill)
        p.session = mock.Mock(**{"mode": DICTATE, "speaker": None, "muted": False,
                                 **session})
        p.open_settings = mock.Mock()
        return c, p, ui._row_icons(c, p, 100, 20)

    def fire(self, c, tag):
        next(fn for t, seq, fn in c.bindings
             if t == tag and seq == "<Button-1>")(None)

    def tags(self, c):
        drawn = set()
        for item in c.ovals + c.rects:
            drawn |= set(item[-1] if isinstance(item[-1], tuple) else ())
        return drawn

    def test_the_gear_opens_the_settings_menu(self):
        # The same items the right-click builds, not a second set: everything in them is
        # a dispatcher onto the session or the profile.
        c, p, _x = self.row()
        self.fire(c, "row-gear")
        p.open_settings.assert_called_once()

    def test_the_gear_posts_the_items_and_not_a_settings_cascade(self):
        """A shortcut that costs an extra hover is not a shortcut.

        `open_settings` posted `_settings_menu`, which *adds a cascade* to whatever it is
        given — so the gear opened a menu whose only row was `Settings >`, and the whole
        list was one hover further away than the right-click had it.
        """
        p = ui.Pill.__new__(ui.Pill)
        posted = []
        p._popup_menu = posted.append
        ui.Pill.open_settings(p)
        self.assertEqual(posted, [p._settings_items])

    def test_the_mode_glyph_switches_the_mode(self):
        c, p, _x = self.row()
        self.fire(c, "row-mode")
        p.session.toggle_mode.assert_called_once()

    def test_the_mode_glyph_is_a_pen_in_refine_not_a_bubble(self):
        # The two-way read (`mode != DICTATE`) drew converse's speech bubble
        # over a mode that pastes — the exact defect the third mode was not to
        # introduce silently. The pen is its own mark: shaft and nib.
        #
        # Counted as arcs as well as lines since the glyph language changed:
        # the bubble was a smoothed polygon and is four corner arcs and four
        # sides now, so "not a polygon" no longer tells the three marks apart.
        shapes = {}
        for mode in (DICTATE, REFINE, CONVERSE):
            c = Canvas()
            ui._mode_glyph(c, 10, 10, "#fff", mode, ())
            shapes[mode] = (len(c.arcs), len(c.lines))
        self.assertEqual(shapes[DICTATE], (0, 3))   # three lines of text
        # The pen: shaft, band, and the draft line it rewrites. Its nib used to
        # be a second line off the shaft's lower end — collinear with it, so the
        # two drew one diagonal and the pen had no pen.
        self.assertEqual(shapes[REFINE], (0, 3))
        self.assertEqual(shapes[CONVERSE], (4, 5))  # the bubble and its tail

    def test_a_mode_with_no_mark_says_so_rather_than_drawing_the_wrong_one(self):
        # The old glyph fell through to dictate's three lines for anything it
        # did not recognise, which is how a bubble ended up over a mode that
        # pastes. A fourth mode is a decision, not a default.
        with self.assertRaises(ValueError):
            ui._mode_glyph(Canvas(), 10, 10, "#fff", "translate", ())

    def test_the_speaker_toggles_replies(self):
        c, p, _x = self.row(speaker=mock.Mock())
        self.fire(c, "row-voice")
        p.session.toggle_speech.assert_called_once()

    def test_there_is_no_speaker_icon_when_nothing_can_speak(self):
        # An icon that toggles nothing is worse than an absent one. `speaker` is None
        # under `--no-speak` and wherever the voice engine is missing.
        c, _p, _x = self.row(speaker=None)
        self.assertFalse([b for b in c.bindings if b[0] == "row-voice"])

    def test_and_it_is_there_when_something_can(self):
        c, _p, _x = self.row(speaker=mock.Mock())
        self.assertTrue([b for b in c.bindings if b[0] == "row-voice"])

    def test_muting_changes_the_mark_rather_than_removing_it(self):
        # "Off" has to be legible without remembering what "on" looked like, and an icon
        # that vanishes when a setting is off is a setting nobody finds their way back to.
        loud, _p, _x = self.row(speaker=mock.Mock(), muted=False)
        quiet, _p2, _x2 = self.row(speaker=mock.Mock(), muted=True)
        self.assertTrue([b for b in quiet.bindings if b[0] == "row-voice"])
        self.assertNotEqual(len(loud.lines), len(quiet.lines))

    def test_a_pill_with_no_session_draws_nothing(self):
        # Fixtures build pills with `__new__`, and a row that assumed a session would
        # take the whole surface down with it.
        c = Canvas()
        p = ui.Pill.__new__(ui.Pill)
        p.session = None
        self.assertEqual(ui._row_icons(c, p, 100, 20), 100)
        self.assertEqual(c.bindings, [])

    def test_they_are_skipped_on_a_pill_too_narrow_to_hold_them(self):
        """The status word is the thing that says whether Flow is listening, and three
        icons drawn over it would cost more than they add."""
        p = ui.Pill.__new__(ui.Pill)
        p.canvas = Canvas()
        p.session = mock.Mock(mode=DICTATE, speaker=None, muted=False)
        p._docked_w = ui.PILL_W
        p._shell_h = ui.PILL_H
        p._flash = 0
        p.armed = False
        p._meter_level = 0.0
        ui.Pill._draw(p)
        self.assertFalse([b for b in p.canvas.bindings if b[0].startswith("row-")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

class TestTheWindowFlowIsAimedAt(unittest.TestCase):
    """The name of the app that will receive the paste, at the left of the row.

    Asked for as an *icon* — "if i am on notepad i see notepad icon and when i am on
    claude ide i see claude icon" — and the name is the half that costs nothing.
    `_track_target` already resolves the foreground process for the paste, on the edge
    rather than per frame, so `session.target_app` is already sitting there reading
    `claude.exe`. The picture needs `ExtractIconExW`, `GetIconInfo` and `GetDIBits` to
    get pixels into a `PhotoImage`, which is a different size of job.
    """

    def drawn(self, target="notepad.exe", lite=False):
        p = pill(armed=True, lite=lite)
        p.session.target_app = target
        p._draw()
        return p

    def test_the_name_is_drawn_at_the_left_of_the_row(self):
        p = self.drawn()
        self.assertIn("Notepad", [text for _x, _y, text, _f in p.canvas.texts])

    def test_the_extension_goes_and_a_bare_stem_gets_a_capital(self):
        self.assertEqual(ui.app_label("notepad.exe"), "Notepad")

    def test_a_name_its_author_capitalised_is_left_alone(self):
        # `Code` and `WindowsTerminal` keep the shape they were given.
        self.assertEqual(ui.app_label("Code.exe"), "Code")

    def test_a_long_name_is_cut_at_the_end_not_the_start(self):
        """The opposite of what the draft body does, for the opposite reason: a draft is
        windowed to its tail because the newest words are the ones being spoken, while an
        application is recognised by its head."""
        shown = ui.app_label("WindowsTerminal.exe")
        self.assertTrue(shown.startswith("WindowsTe"), shown)
        self.assertEqual(len(shown), ui.APP_NAME_CHARS)

    def test_a_non_string_target_is_no_name(self):
        # `target_app` is "" until the first foreground window resolves, and a Mock in
        # any fixture that builds a pill with `__new__`.
        self.assertEqual(ui.app_label(mock.Mock()), "")
        self.assertEqual(ui.app_label(""), "")

    def test_the_slot_is_the_same_width_whatever_the_name_is(self):
        """A slot that sized itself to the name would shift the mic, the meter and every
        icon each time you changed window — the motion this surface spent a night
        removing."""
        short = self.drawn("vi.exe")
        long_ = self.drawn("WindowsTerminal.exe")
        self.assertEqual(short._row_shift(), long_._row_shift())

    def test_the_meter_moves_over_to_make_room(self):
        bare = self.drawn("")
        named = self.drawn("notepad.exe")
        self.assertEqual(named._row_shift() - bare._row_shift(),
                         ui.APP_SLOT_W + ui.APP_SLOT_GAP)
        self.assertGreater(min(r[0] for r in named.canvas.rects),
                           min(r[0] for r in bare.canvas.rects))

    def test_lite_reserves_nothing_because_it_tracks_nothing(self):
        # `_track_target` returns early in Lite, so `target_app` never fills — the row on
        # a Mac is exactly what it always was.
        self.assertEqual(self.drawn("notepad.exe", lite=True)._row_shift(), 0)

    def test_no_target_reserves_nothing_either(self):
        self.assertEqual(self.drawn("")._row_shift(), 0)

    def test_the_marching_dots_move_with_the_meter(self):
        """`_draw_dots` takes the meter's place and is called without the shift, so one
        computed and the other not would draw the dots under the app name."""
        p = self.drawn()
        p.canvas.ovals.clear()
        p._draw_dots(p.canvas, ui.PILL_H // 2, "#FFFFFF")
        self.assertGreater(min(o[0] for o in p.canvas.ovals),
                           ui.METER_X + ui.APP_SLOT_W)

