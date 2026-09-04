"""The compact pill's whole vocabulary: two colours, a meter, three gestures.

Everything here goes through `CompactPill._draw` and `_frame` on a fake canvas
and a fake session rather than through a real window, for the reason
`test_pill.py` does: a desktop is expensive and both methods are pure — given
a session state and a press, they write a fixed set of shapes and make a fixed
set of calls. The fixture idiom is test_pill's own: `__new__` plus class
defaults, never `__init__`.

Pinned: the glyph tint per mode, the ring colour per state, the capsule's
geometry against `design/compact/gen.py`, tap vs hold, the class-attribute
defaults `_draw` depends on, the pump's pull contract, Type's whole arc —
hold, release, draft, paste — and the gestures complete: the Workspace.dc.html
menu, the palette, the setup box, and the tray the canvas said no to.
"""

import time
import math
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for test_menu's fakes

import flow.ui_compact as uc  # noqa: E402
from flow.session import CONVERSE, DICTATE, REFINE, State  # noqa: E402
from test_menu import FakeMenu, FakeVar  # noqa: E402


class Canvas:
    """Records the primitives `CompactPill._draw` uses, with their geometry.

    The same shape test_pill's fake has — `polys`, `items` of ovals, rects,
    arcs, lines, and the `bindings` a `tag_bind` would make — so either pill
    can be drawn onto it. Arcs record their style and width, lines their
    width: the capsule body is pieslices and every ring is a 1 px stroke, and
    both facts are things these tests assert on.
    """

    def __init__(self) -> None:
        self.ovals: list[tuple[float, float, float, float, str]] = []
        self.rects: list[tuple[float, float, float, float, str, str]] = []
        self.lines: list[tuple] = []
        self.arcs: list[tuple] = []
        self.polys: list[tuple] = []
        self.texts: list[tuple] = []
        self.bindings: list[tuple] = []

    def delete(self, *a, **kw) -> None: ...

    def tag_bind(self, tag, sequence, callback) -> None:
        self.bindings.append((tag, sequence, callback))

    def create_oval(self, x1, y1, x2, y2, **kw) -> None:
        self.ovals.append((x1, y1, x2, y2, kw.get("fill", "")))

    def create_rectangle(self, x1, y1, x2, y2, **kw) -> None:
        self.rects.append(
            (x1, y1, x2, y2, kw.get("fill", ""), kw.get("outline", "")))

    def create_line(self, *a, **kw) -> None:
        self.lines.append((a, kw.get("fill", ""), kw.get("width", 1)))

    def create_arc(self, *a, **kw) -> None:
        self.arcs.append((a, kw.get("fill", ""), kw.get("outline", ""),
                          kw.get("style"), kw.get("width", 1),
                          kw.get("extent")))

    def create_polygon(self, *a, **kw) -> None:
        self.polys.append((a, kw.get("fill", ""), kw.get("outline", "")))

    def create_text(self, *a, **kw) -> None:
        self.texts.append((a, kw.get("text", ""), kw.get("fill", ""),
                           kw.get("font"), kw.get("anchor", "center"),
                           kw.get("width", 0)))


def session(mode=DICTATE, state=State.IDLE, hearing=True, busy=False,
            level_db=-120.0, draft_text="", capturing=False, loading=False):
    """A session Mock with real values for everything the pill reads.

    The values are set rather than left as auto-created Mocks for test_pill's
    reason: `not Mock()` is `False`, so a bare Mock would silently answer
    "yes, hearing" and no rest-state test here could ever fail. `events`
    returns a real list, because `_pump_events` iterates it. `workspace` is a
    real string, because the panel's strip prints it.
    """
    s = mock.Mock(mode=mode, state=state, hearing=hearing, busy=busy,
                  level_db=level_db, capturing=capturing)
    # Two more that a bare Mock would answer "yes" to, and both light the
    # ring: `capturing` is the microphone being open with nobody speaking,
    # and `asr.loading` is the models coming off disk. Left auto-created, the
    # pill would draw a lit ring in every test that never mentioned either.
    s.asr = mock.Mock(loading=loading)
    s.draft = mock.Mock(text=draft_text)
    s.events.return_value = []
    s.workspace = "~/dev/products/flow"
    return s


def pill(state=State.IDLE, *, armed=True, mode=DICTATE, **attrs):
    """A compact pill with a fake canvas and no Tk, built the way
    test_pill builds one: `__new__`, so every attribute `_draw` reads has to
    come from a class default or from here."""
    p = uc.CompactPill.__new__(uc.CompactPill)
    # `paint` is what `_draw` draws on, `canvas` what takes the events; on a
    # real pill those are a `GdiCanvas` and a `tk.Canvas`, and here one
    # recording fake stands in for both.
    p.paint = p.canvas = Canvas()
    p.armed = armed
    # A bare fixture has no window to resize, and `_say` resizes one to make
    # room for its strip — the same reason `panel_pill` mocks the Tk calls
    # `_sync_shell` makes. Tests that care about the strip use `panel_pill`.
    p._sync_shell = mock.Mock()
    # And no window to ask a monitor about: `_frame` re-asks every fourth
    # frame, through `winfo_screenwidth`, which on a `__new__`-built instance
    # recurses through `tk.Misc.__getattr__` rather than answering. Tests that
    # care about the monitor are in `test_compact_screen.py` and put the real
    # method back, the way `panel_pill` puts back `_sync_shell`.
    p._sync_monitor = mock.Mock()
    p.session = session(state=state, mode=mode,
                        capturing=attrs.pop("capturing", False),
                        loading=attrs.pop("loading", False))
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


def rings(p) -> list[str]:
    """The state ring's colour, or [] at rest: the only items that may wear a
    state hue are the ring's two cap arcs and two straight runs."""
    hues = (uc.HEARING, uc.WAITING, uc.ERROR)
    colours = {outline for _a, _f, outline, *_r in p.canvas.arcs
               if outline in hues}
    colours |= {fill for _a, fill, _w in p.canvas.lines if fill in hues}
    return sorted(colours)


def ring_items(p) -> list:
    """Every arc and line wearing a state hue, for the 1 px assertions."""
    hues = (uc.HEARING, uc.WAITING, uc.ERROR)
    items = [(outline, w) for _a, _f, outline, _s, w, *_r in p.canvas.arcs
             if outline in hues]
    items += [(fill, w) for _a, fill, w in p.canvas.lines if fill in hues]
    return items


def strokes(p, colour) -> list:
    """Capsule outlines: `(points, width)` per `create_line` drawn from a flat
    coordinate list. `_capsule_ring` passes one list, so the fake keeps a
    one-tuple — which is exactly what tells a traced capsule apart from the
    four-coordinate lines the glyph and the highlight draw."""
    return [([(a[0][i], a[0][i + 1]) for i in range(0, len(a[0]), 2)], w)
            for a, fill, w in p.canvas.lines
            if fill == colour and len(a) == 1]


def segments(p, colour) -> list:
    """The plain four-coordinate lines: the mic's stem and slash, the inset
    highlight, the panel's seams."""
    return [(a, w) for a, fill, w in p.canvas.lines
            if fill == colour and len(a) == 4]


def bodies(p, colour) -> list:
    """The filled capsule polygons — `(points, bbox)` each."""
    out = []
    for coords, fill, _outline in p.canvas.polys:
        if fill != colour:
            continue
        pts = coords[0] if len(coords) == 1 else coords
        xy = [(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)]
        xs, ys = [q[0] for q in xy], [q[1] for q in xy]
        out.append((xy, (min(xs), min(ys), max(xs), max(ys))))
    return out


def off_stadium(pts, x1, y1, x2, y2) -> float:
    """How far the worst point strays from the true stadium through
    `(x1, y1, x2, y2)` — 0 for a capsule, and large for the rounded rectangle
    `_round_rect` yields at r = h/2."""
    r = (y2 - y1) / 2
    cy, lcx, rcx = y1 + r, x1 + r, x2 - r
    worst = 0.0
    for x, y in pts:
        if x < lcx:
            d = abs(math.hypot(x - lcx, y - cy) - r)
        elif x > rcx:
            d = abs(math.hypot(x - rcx, y - cy) - r)
        else:
            d = min(abs(y - y1), abs(y - y2))
        worst = max(worst, d)
    return worst


def glyph_stroke(p) -> str:
    """The mic's colour: the body is the pill's only *unfilled* polygon — an
    outlined `_round_rect`. The meter's bars are polygons too now that they
    carry gen.py's 1 px cap radius, and they are filled, which is what tells
    the two apart."""
    (body,) = [it for it in p.canvas.polys if it[1] == ""]
    _coords, _fill, outline = body
    return outline


def meter_bars(p, colour) -> list:
    """The meter's bars as `(x1, y1, x2, y2)`, whichever primitive drew them.

    Rounded above their own cap diameter and squared below it (`_draw_face`,
    ui.py:5056's rule), so a bar is a polygon at some levels and a rectangle
    at others — the bbox is the thing the geometry assertions are about."""
    out = [tuple(r[:4]) for r in p.canvas.rects if r[4] == colour]
    for coords, fill, _outline in p.canvas.polys:
        if fill != colour:
            continue
        # `create_polygon(pts, **kw)` — the fake keeps `*a`, so the flat point
        # list arrives wrapped in a one-tuple.
        pts = coords[0] if len(coords) == 1 else coords
        xs, ys = pts[0::2], pts[1::2]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    return sorted(out)


class TestTheGlyphCarriesTheMode(unittest.TestCase):
    def test_type_is_white(self):
        p = pill(State.LISTENING, mode=DICTATE)
        p._draw()
        self.assertEqual(glyph_stroke(p), uc.MODE_TINT[DICTATE])
        # White, as the README's "white Type" says — ui.py's own near-white.
        self.assertEqual(uc.MODE_TINT[DICTATE], uc.TEXT)

    def test_ask_is_violet(self):
        p = pill(State.LISTENING, mode=CONVERSE)
        p._draw()
        self.assertEqual(glyph_stroke(p), uc.MODE_TINT[CONVERSE])
        self.assertEqual(uc.MODE_TINT[CONVERSE], "#B48EF5")

    def test_refines_gold_joined_the_map_with_the_mode(self):
        # Declared ahead of the session's third mode; it joined the map the
        # day REFINE landed, per the brief's rule.
        self.assertEqual(uc.REFINE_GOLD, "#E1B75C")
        self.assertEqual(uc.MODE_TINT[REFINE], uc.REFINE_GOLD)

    def test_refine_is_gold(self):
        p = pill(State.LISTENING, mode=REFINE)
        p._draw()
        self.assertEqual(glyph_stroke(p), uc.REFINE_GOLD)


class TestTheRingCarriesTheState(unittest.TestCase):
    def test_hearing_is_green(self):
        p = pill(State.LISTENING)
        p._draw()
        self.assertEqual(rings(p), ["#3ECF8E"])

    def test_a_cli_out_is_blue(self):
        for state in (State.REFINING, State.ASKING):
            with self.subTest(state=state):
                p = pill(state)
                p._draw()
                self.assertEqual(rings(p), ["#7AA2F7"])

    def test_an_error_is_red_whatever_the_state(self):
        p = pill(State.LISTENING, _flash=uc.FLASH_FRAMES)
        p._draw()
        self.assertEqual(rings(p), ["#F2584A"])

    def test_the_ring_is_one_pixel_not_two(self):
        # `box-shadow: 0 0 0 1px <state>` — every item wearing the state hue,
        # cap arcs and straight runs alike.
        p = pill(State.LISTENING)
        p._draw()
        self.assertTrue(ring_items(p))
        self.assertTrue(all(w == 1 for _c, w in ring_items(p)))

    def test_rest_is_no_ring(self):
        for state in (State.IDLE, State.DRAFT):
            with self.subTest(state=state):
                p = pill(state)
                p._draw()
                self.assertEqual(rings(p), [])

    def test_disarmed_is_rest_whatever_the_session_thinks(self):
        p = pill(State.LISTENING, armed=False)
        p._draw()
        self.assertEqual(rings(p), [])


class TestThePillSaysWhatItIsDoing(unittest.TestCase):
    """Three things a wordless pill could not say, and had to learn to.

    Every one of them came from the same report: "push to talk does not do
    anything, I cannot explain the failure to you". That is what a surface
    with no feedback produces — not a wrong description, but no description
    available at all. A colour that is missing is not a colour somebody can
    report.
    """

    def test_the_models_loading_shows_as_the_waiting_ring(self):
        # The first hold after launch used to do nothing visible for as long
        # as the models took to come off disk, with the pill exactly as it
        # looks at rest. `session.activity` has called this "loading the
        # model" for the shipped surface all along.
        p = pill(State.IDLE, armed=False, loading=True)
        p._draw()
        self.assertEqual(rings(p), [uc.WAITING])

    def test_loading_shows_even_before_anything_is_armed(self):
        # It is the application, not the capture: true whether or not a
        # microphone is open, and the answer to "why did my first hold do
        # nothing".
        p = pill(State.IDLE, armed=False, loading=True)
        self.assertEqual(p._ring_colour(), uc.WAITING)

    def test_an_open_mic_lights_the_ring_even_in_silence(self):
        # `LISTENING` means speech was *detected*, so a mic held open over a
        # silent room reports IDLE — correctly. Without this the pill looked
        # identical whether it was holding the microphone open or doing
        # nothing at all, which is what made a muted mic impossible to tell
        # from a dead application.
        p = pill(State.IDLE, armed=True, capturing=True)
        p._draw()
        self.assertEqual(rings(p), [uc.HEARING])

    def test_a_detected_state_still_outranks_a_bare_open_mic(self):
        # One state, one colour: a CLI in flight is blue even though the
        # microphone is open behind it.
        p = pill(State.REFINING, armed=True, capturing=True)
        self.assertEqual(p._ring_colour(), uc.WAITING)

    def test_a_disarmed_pill_is_still_at_rest(self):
        p = pill(State.LISTENING, armed=False, capturing=True)
        self.assertEqual(p._ring_colour(), "")


class TestEveryHoldPumpsTheSession(unittest.TestCase):
    """`_frame` reads the microphone only while `armed` — `session.tick()` is
    what pulls the audio — so anything that opens the device and leaves
    `armed` false opens it into a loop that never reads it.

    That was the chord, which is the documented push-to-talk gesture: it went
    through `_talk_start` while `armed = True` lived in `_pump_press`, the
    *mouse* path. `capturing` true, ring green, and not one sample pumped for
    the whole hold — which then read as a microphone delivering nothing.
    """

    def test_the_chord_arms(self):
        p = pill(armed=False)
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["talk"]
        p._drain_hotkeys()
        self.assertTrue(p.armed)
        p.session.talk_start.assert_called_once_with()

    def test_the_mouse_hold_arms(self):
        p = pill(armed=False)
        p._press_at = time.perf_counter() - uc.PILL_HOLD_SEC - 0.01
        p._pump_press()
        self.assertTrue(p.armed)

    def test_arming_is_the_one_seam_both_go_through(self):
        # Whichever gesture starts the hold, the same call arms it — so a
        # third one cannot arrive and quietly skip the pump.
        p = pill(armed=False)
        p._talk_start()
        self.assertTrue(p.armed)

    def test_a_refused_capture_does_not_claim_to_be_armed(self):
        p = pill(armed=False)
        p.session.talk_start.side_effect = OSError("device is busy")
        p._talk_start()
        self.assertFalse(p.armed)
        self.assertTrue(p._mic_gone)

    def test_an_armed_frame_actually_ticks_the_session(self):
        p = pill(armed=True)
        p._frame()
        p.session.tick.assert_called_once_with()

    def test_an_unarmed_frame_collects_but_does_not_tick(self):
        p = pill(armed=False)
        p._frame()
        p.session.tick.assert_not_called()
        p.session.pump_results.assert_called_once_with()


class TestTheNoticeCarriesAnySentence(unittest.TestCase):
    def test_say_sets_the_text_and_the_countdown(self):
        p = panel_pill()
        p._say("something worth reading")
        self.assertEqual(p._notice_text, "something worth reading")
        self.assertEqual(p._notice, uc.COPIED_FRAMES)

    def test_the_strip_draws_whatever_it_was_given(self):
        p = panel_pill(x=100, y=400, _notice=2,
                       _notice_text="a sentence of its own",
                       _shell_h=uc.PILL_H + uc.NOTICE_H)
        p._draw()
        said = [t for t in p.canvas.texts if t[1] == "a sentence of its own"]
        self.assertEqual(len(said), 1)
        # Never in an error colour: a muted mic is a thing to fix, not a
        # failure of Flow's — the same rule Lite's "copied" line follows.
        self.assertEqual(said[0][2], uc.DIM)


class TestTheCapsuleIsFilled(unittest.TestCase):
    """The body is drawn, not just the furniture on it.

    `scripts/compact_shots.py` caught the version without it: `-transparentcolor`
    keys the canvas background out, and on Windows a keyed pixel is click-through —
    the pill was a glyph and some bars floating over the desktop, and the
    right-click meant for the menu fell through to whatever was behind.
    """

    def test_the_shell_covers_the_pill(self):
        p = pill(State.IDLE, armed=False)
        p._draw()
        (_pts, bbox), = bodies(p, uc.SHELL)
        self.assertEqual(bbox, (0, 0, uc.PILL_W, uc.PILL_H))


class TestTheCapsuleMatchesTheCanvas(unittest.TestCase):
    """Item 2's pixel contract with `design/compact/gen.py` — the authority
    when the canvas and memory disagree. The photographs in `.shots/` are the
    visual gate; these pin the geometry headless."""

    def test_the_body_is_a_true_stadium(self):
        # Every point on the body is on the stadium: semicircular ends of
        # radius h/2 and straight runs between them. `_round_rect` at r = h/2
        # is a rounded rectangle and misses by several pixels, which is what
        # `.shots/01-compact-rest.png` showed before `_capsule` existed.
        p = pill(State.IDLE, armed=False)
        p._draw()
        (pts, _bbox), = bodies(p, uc.SHELL)
        self.assertLess(off_stadium(pts, 0, 0, uc.PILL_W, uc.PILL_H), 0.01)
        # And it really is round at the ends: the leftmost point is on the
        # vertical centre line, where only a semicircle puts it.
        left = min(pts)
        self.assertEqual(left[0], 0)
        self.assertAlmostEqual(left[1], uc.PILL_H / 2)

    def test_the_ring_traces_the_body_it_is_drawn_on(self):
        # Fill and stroke come from one point run, inset by half the stroke.
        # They were a pieslice and an arc, which do not rasterize onto the
        # same pixels: the ring stood a pixel outside the body and a dark halo
        # ran round the inside of both caps, with a step where each straight
        # run met its arc (`.shots/02-compact-hearing.png`, zoomed).
        p = pill(State.LISTENING)
        p._draw()
        (ring, width), = strokes(p, uc.HEARING)
        self.assertEqual(width, 1)
        self.assertLess(
            off_stadium(ring, 0.5, 0.5, uc.PILL_W - 0.5, uc.PILL_H - 0.5),
            0.01)
        # Closed: a box-shadow wraps all four sides.
        self.assertEqual(ring[0], ring[-1])

    def test_the_chrome_is_the_three_hairlines(self):
        # gen.py's `.pill`: a 1 px RING_OUTER border and an inset RING_TOP
        # highlight, always; the state ring one pixel further out when armed.
        p = pill(State.LISTENING)
        p._draw()
        (outer, width), = strokes(p, uc.RING_OUTER)
        # One 1 px trace, one pixel inside the state ring's.
        self.assertEqual(width, 1)
        self.assertLess(
            off_stadium(outer, 1.5, 1.5, uc.PILL_W - 1.5, uc.PILL_H - 1.5),
            0.01)
        # `inset 0 1px 0 RING_TOP` is a straight line, not a curve: an arc
        # over the pill's own bbox is an ellipse 120 px wide, and it
        # photographed as a bulge sweeping across the capsule
        # (`.shots/01-compact-rest.png`, before this was a line).
        highlights = [a for a, _w in segments(p, uc.RING_TOP)]
        self.assertEqual(len(highlights), 1)
        # It steps in with the border when a ring takes the edge, and spans
        # the flat run between the cap centres — the only part of a stadium a
        # horizontal inset line can sit on.
        r = uc.PILL_H // 2
        self.assertEqual(highlights[0], (2 + r, 2, uc.PILL_W - 2 - r, 2))
        self.assertEqual(p.canvas.arcs and
                         [outline for _a, _f, outline, style, *_r
                          in p.canvas.arcs
                          if style == uc.tk.ARC and outline == uc.RING_TOP],
                         [])

    def test_the_rest_chrome_sits_on_the_outermost_pixel(self):
        p = pill(State.IDLE, armed=False)
        p._draw()
        r = uc.PILL_H // 2
        highlights = [a for a, _w in segments(p, uc.RING_TOP)]
        self.assertEqual(highlights, [(1 + r, 1, uc.PILL_W - 1 - r, 1)])

    def test_the_meter_is_fifteen_two_pixel_bars_on_a_two_pixel_gap(self):
        p = pill(State.IDLE, armed=False)
        p._draw()
        bars = meter_bars(p, uc.DIM)
        self.assertEqual(len(bars), 15)
        self.assertEqual(uc.BARS, 15)
        for i, (x1, y1, x2, y2) in enumerate(bars):
            self.assertEqual(x1, uc.METER_X + i * (uc.BAR_W + uc.BAR_GAP))
            self.assertEqual(x2 - x1, 2)      # 2 px wide
            self.assertEqual(y2 - y1, 3.0)    # 3 px at rest
        # 2 px on a 2 px gap, and grey: rest claims no state.
        self.assertEqual(uc.BAR_W, 2)
        self.assertEqual(uc.BAR_GAP, 2)

    def test_the_mic_is_stroked_not_filled(self):
        # gen.py's `mic()`: an outlined capsule body, an arc cradle, a stem —
        # and no filled oval anywhere.
        p = pill(State.LISTENING)
        p._draw()
        self.assertEqual(p.canvas.ovals, [])
        tint = uc.MODE_TINT[DICTATE]
        self.assertEqual(glyph_stroke(p), tint)
        cradle = [outline for _a, _f, outline, style, *_r in p.canvas.arcs
                  if style == uc.tk.ARC and outline == tint]
        self.assertEqual(cradle, [tint])
        stems = [fill for _a, fill, _w in p.canvas.lines if fill == tint]
        self.assertEqual(stems, [tint])


class TestTapAndHoldShareOneButton(unittest.TestCase):
    def test_a_tap_cycles_the_mode(self):
        p = pill()
        p._on_press()
        p._on_release()
        p.session.toggle_mode.assert_called_once_with()
        p.session.talk_start.assert_not_called()
        p.session.talk_end.assert_not_called()

    def test_a_hold_talks(self):
        p = pill()
        with mock.patch.object(uc.time, "perf_counter", return_value=100.0):
            p._on_press()
        # Past the threshold, the next frame turns the press into an
        # utterance — the frame is the only clock, not an `after` timer.
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=100.0 + uc.PILL_HOLD_SEC + 0.01):
            p._pump_press()
        p.session.talk_start.assert_called_once_with()
        p._on_release()
        p.session.talk_end.assert_called_once_with()
        p.session.toggle_mode.assert_not_called()

    def test_a_short_press_the_frame_never_saw_is_a_tap(self):
        p = pill()
        p._on_press()
        p._pump_press()  # inside the threshold: nothing happens
        p.session.talk_start.assert_not_called()
        p._on_release()
        p.session.toggle_mode.assert_called_once_with()

    def test_a_drag_is_neither(self):
        p = pill()
        p._move_window = mock.Mock()
        p._on_press(mock.Mock(x_root=0, y_root=0, x=0, y=0))
        p._on_motion(mock.Mock(x_root=uc.PILL_DRAG_SLOP + 1, y_root=0,
                               x=0, y=0))
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=time.perf_counter() + uc.PILL_HOLD_SEC + 0.01):
            p._pump_press()
        p.session.talk_start.assert_not_called()
        p._on_release()
        p.session.toggle_mode.assert_not_called()


class TestQuittingIsQuiet(unittest.TestCase):
    def test_a_frame_that_outlives_the_window_says_nothing(self):
        # `quit_app` destroys the window while a frame begun before it is
        # still running, and `_present` is the first line of that frame to ask
        # Tk for anything. Un-caught it printed a whole traceback at somebody
        # who had just pressed quit and made them think they had broken it.
        p = pill()
        p.paint = mock.Mock()
        p.paint.present.side_effect = uc.tk.TclError(
            "can't invoke \"winfo\" command: application has been destroyed")
        p._present()
        self.assertFalse(p._alive)


class TestTheDragMovesIt(unittest.TestCase):
    """"Drag it anywhere" (Main.dc.html). It was the one gesture on the canvas
    with nothing behind it: `_on_motion` recorded that the press had travelled
    — which made the slop work — and never moved the window."""

    def press(self, p, x=0, y=0):
        p._on_press(mock.Mock(x_root=x, y_root=y, x=6, y=6))

    def test_past_the_slop_the_window_follows_the_pointer(self):
        p = pill()
        p._move_window = mock.Mock()
        self.press(p, 100, 100)
        p._on_motion(mock.Mock(x_root=140, y_root=180, x=6, y=6))
        # Moved by the pointer's travel, not snapped: the grab point inside
        # the window is subtracted, so the pill keeps the place under the
        # thumb it was picked up by.
        p._move_window.assert_called_once_with(134, 174)

    def test_inside_the_slop_nothing_moves(self):
        p = pill()
        p._move_window = mock.Mock()
        self.press(p)
        p._on_motion(mock.Mock(x_root=uc.PILL_DRAG_SLOP, y_root=0, x=6, y=6))
        p._move_window.assert_not_called()

    def test_a_hold_in_flight_is_never_dragged(self):
        # ui.py:2712's rule, kept: somebody talking into a held pill may well
        # move the mouse, and moving the window out from under them would be
        # the gesture betraying them.
        p = pill()
        p._move_window = mock.Mock()
        self.press(p)
        p._press_talking = True
        p._on_motion(mock.Mock(x_root=500, y_root=500, x=6, y=6))
        p._move_window.assert_not_called()
        self.assertFalse(p._press_moved)

    def test_the_move_is_clamped_to_the_screen(self):
        p = pill()
        p.geometry = mock.Mock()
        p.winfo_screenwidth = lambda: 1920
        p.winfo_screenheight = lambda: 1080
        p._shell_w, p._shell_h = uc.PILL_W, uc.PILL_H
        p._move_window(-50, 5000)
        p.geometry.assert_called_once_with(
            f"{uc.PILL_W}x{uc.PILL_H}+0+{1080 - uc.PILL_H}")


class TestTheClassDefaultsADrawNeeds(unittest.TestCase):
    """Every attribute `_draw` reads must exist on the class, so a fixture
    built with `__new__` draws instead of recursing through `tk.Misc.__getattr__`
    into `self.tk` — the RecursionError flow/ui.py:2345 cites."""

    def test_a_bare_instance_draws_the_resting_pill(self):
        p = uc.CompactPill.__new__(uc.CompactPill)
        p.paint = p.canvas = Canvas()
        p.session = session()
        p._draw()
        # Rest: no ring, and the meter is there in its grey — rest claims no
        # state, so the bars are gen.py's DIM, not a mode's tint.
        self.assertEqual(rings(p), [])
        self.assertEqual(len(meter_bars(p, uc.DIM)), uc.BARS)

    def test_every_drawn_attribute_is_a_class_attribute(self):
        for name in ("armed", "_flash", "_meter_level", "_eased_level",
                     "lite", "hotkeys", "on_send", "_press_at", "_press_xy",
                     "_press_moved", "_press_talking", "_menu", "_alive",
                     "no_activate"):
            with self.subTest(name=name):
                # On the class, not only assigned in `__init__` — an
                # instance-only attribute is exactly the RecursionError case.
                self.assertTrue(hasattr(uc.CompactPill, name), name)


class TestThePumpPulls(unittest.TestCase):
    def test_armed_ticks_disarmed_collects_and_both_drain(self):
        p = pill(State.LISTENING, armed=True)
        p._frame()
        p.session.tick.assert_called_once_with()
        p.session.pump_results.assert_not_called()
        p.session.events.assert_called_once_with()

        p2 = pill(State.IDLE, armed=False)
        p2._frame()
        p2.session.pump_results.assert_called_once_with()
        p2.session.tick.assert_not_called()
        p2.session.events.assert_called_once_with()

    def test_an_error_event_flashes_the_ring_red(self):
        s = session(state=State.IDLE)
        from flow.session import Event
        s.events.return_value = [Event("error", "no microphone")]
        p = pill(armed=False)
        p.session = s
        p._frame()
        self.assertEqual(p._flash, uc.FLASH_FRAMES - 1)  # one frame counted down
        self.assertEqual(p._ring_colour(), "#F2584A")

    def test_a_disarm_event_stops_the_pill_claiming_armed(self):
        from flow.session import Event
        s = session(state=State.IDLE)
        s.events.return_value = [Event("disarm", "")]
        p = pill(armed=False)
        p.session = s
        p.armed = True
        p._frame()
        self.assertFalse(p.armed)

    def test_the_hotkey_queue_is_drained_like_the_full_pills(self):
        p = pill()
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["warm", "talk", "talk-end", "mode"]
        self.assertTrue(p._drain_hotkeys())
        p.session.warm.assert_called_once_with()
        p.session.talk_start.assert_called_once_with()
        p.session.talk_end.assert_called_once_with()
        p.session.toggle_mode.assert_called_once_with()

    def test_no_hotkeys_is_a_fine_answer(self):
        p = pill()
        self.assertIsNone(p.hotkeys)
        self.assertTrue(p._drain_hotkeys())


class TestTypeSendsEndToEnd(unittest.TestCase):
    """Item 1's acceptance: hold, speak, release — and the words leave.

    The contract mirrored from `Pill` (flow/ui.py:2760-2834, 3756-3770): the
    release *arms* the send, the `draft` event that brings the decoded words
    *fires* it, and `_send` is the one place every route to a send goes
    through — which is what stops a release and the hotkey pasting the same
    words twice. The session is the fake from `session()` with `talk_end`,
    `send` and `events` configured, the same style as the rest of this file.
    """

    def sending_pill(self, s, sent, problem=""):
        """A pill whose `on_send` records what it was asked to paste."""
        p = pill(on_send=lambda text, target=None: sent.append(text) or problem)
        p.session = s
        return p

    def test_a_hold_a_release_and_a_draft_calls_on_send(self):
        from flow.session import Event
        s = session(state=State.LISTENING)
        s.talk_end.return_value = True  # words are in flight
        s.send.return_value = "the plan for Tuesday"
        sent = []
        p = self.sending_pill(s, sent)
        with mock.patch.object(uc.time, "perf_counter", return_value=100.0):
            p._on_press()
        # Past the threshold, the frame turns the press into an utterance.
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=100.0 + uc.PILL_HOLD_SEC + 0.01):
            p._pump_press()
        p._on_release()
        # Armed, not fired: the decode is still in flight, and nothing has
        # been sent or handed back yet.
        self.assertEqual(sent, [])
        s.send.assert_not_called()
        s.events.return_value = [Event("draft", "the plan for Tuesday")]
        s.draft.text = "the plan for Tuesday"
        p._pump_events()
        # The frame's own order: the drain lands the words, `_pump_send` finds
        # the decoder finished with them and fires.
        p._pump_send()
        s.send.assert_called_once_with()
        self.assertEqual(sent, ["the plan for Tuesday"])

    def test_a_returned_problem_flashes_rather_than_being_swallowed(self):
        s = session(state=State.IDLE)
        s.send.return_value = "the words"
        sent = []
        p = self.sending_pill(s, sent, problem="no window would take it")
        p._send()
        self.assertEqual(sent, ["the words"])
        self.assertEqual(p._flash, uc.FLASH_FRAMES)
        self.assertEqual(p._ring_colour(), "#F2584A")

    def test_a_draft_with_no_release_behind_it_sends_nothing(self):
        from flow.session import Event
        s = session(state=State.LISTENING)
        s.events.return_value = [Event("draft", "just dictation settling")]
        sent = []
        p = self.sending_pill(s, sent)
        p._pump_events()
        # The text is remembered — it is what a later send hands over, and
        # what item 3's panel will read — but nothing fires on its own.
        self.assertEqual(p._last_draft, "just dictation settling")
        s.send.assert_not_called()
        self.assertEqual(sent, [])

    def test_a_draft_mid_hold_does_not_fire_a_stale_send(self):
        from flow.session import Event
        s = session(state=State.LISTENING)
        s.talk_end.return_value = True
        s.send.return_value = "everything, cumulatively"
        sent = []
        p = self.sending_pill(s, sent)
        p.hotkeys = mock.Mock()
        # A release arms the send, and before the decode lands a new hold
        # begins: the first draft event arrives mid-utterance and must not
        # paste words the user is still adding to.
        p.hotkeys.drain.return_value = ["talk-end"]
        p._drain_hotkeys()
        self.assertTrue(p._send_pending)
        p.hotkeys.drain.return_value = ["talk"]
        p._drain_hotkeys()
        # The new hold supersedes the wait outright, which is what makes a
        # segment final inside it harmless: there is nothing left armed.
        self.assertFalse(p._send_pending)
        s.events.return_value = [Event("draft", "the first segment")]
        s.draft.text = "the first segment"
        p._pump_events()
        p._pump_send()
        s.send.assert_not_called()
        self.assertEqual(sent, [])
        # The words are cumulative in the draft; the next release sends them
        # all.
        p.hotkeys.drain.return_value = ["talk-end"]
        p._drain_hotkeys()
        s.events.return_value = [Event("draft", "everything, cumulatively")]
        s.draft.text = "everything, cumulatively"
        p._pump_events()
        p._pump_send()
        self.assertEqual(sent, ["everything, cumulatively"])

    def test_the_send_hotkey_sends_and_cancel_is_a_documented_no_op(self):
        s = session(state=State.DRAFT)
        s.send.return_value = "the words"
        sent = []
        p = self.sending_pill(s, sent)
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["send", "cancel"]
        self.assertTrue(p._drain_hotkeys())
        s.send.assert_called_once_with()
        self.assertEqual(sent, ["the words"])

    def test_talk_break_commits_without_arming_the_send(self):
        s = session(state=State.LISTENING)
        s.talk_end.return_value = True
        p = pill(State.LISTENING)
        p.session = s
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["talk-break"]
        p._drain_hotkeys()
        s.talk_end.assert_called_once_with()
        self.assertFalse(p._send_pending)

    def test_asks_release_does_not_arm_the_send(self):
        # Type only: in converse a release is the panel's "say more" (item 3),
        # and session.send() would ask the CLI — never this path.
        s = session(state=State.LISTENING, mode=CONVERSE)
        s.talk_end.return_value = True
        p = pill(State.LISTENING)
        p.session = s
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["talk-end"]
        p._drain_hotkeys()
        self.assertFalse(p._send_pending)

    def test_a_mode_switch_drops_a_pending_send(self):
        s = session(state=State.LISTENING)
        s.talk_end.return_value = True
        p = pill(State.LISTENING)
        p.session = s
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["talk-end"]
        p._drain_hotkeys()
        self.assertTrue(p._send_pending)
        p.hotkeys.drain.return_value = ["mode"]
        p._drain_hotkeys()
        # The words stay in the draft; the wait armed in the old mode is gone.
        self.assertFalse(p._send_pending)
        s.send.assert_not_called()

    def test_a_partial_is_discarded_until_the_panel_lands(self):
        from flow.session import Event
        s = session(state=State.LISTENING)
        s.events.return_value = [Event("partial", "hel")]
        p = pill(State.LISTENING)
        p.session = s
        p._pump_events()  # a decision, not a fall-through: nothing happens
        self.assertEqual(p._last_draft, "")
        self.assertFalse(p._send_pending)

    def test_the_send_paths_attributes_are_class_attributes(self):
        # The same RecursionError guard as the drawn attributes above: a bare
        # fixture driving `_frame` or `_pump_events` reads these, and only a
        # class attribute never reaches `tk.Misc.__getattr__`.
        for name in ("_last_draft", "_send_pending", "paste_target",
                     "_panel_open", "_panel_mode", "_panel_heard",
                     "_panel_heard_final", "_panel_result", "_ask_pending",
                     "_shell_w", "_shell_h", "_outside_was_down",
                     "_mic_gone", "_recover", "_notice", "_panel_failed",
                     "_capsule_off", "_mode_var"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(uc.CompactPill, name), name)


def panel_pill(state=State.IDLE, *, mode=CONVERSE, x=100, y=400, **attrs):
    """A fixture with the Tk calls `_sync_shell` and the frame poll touch
    replaced by Mocks — a bare fixture has no real window to measure, and the
    outside-click poll would otherwise read the *test runner's* mouse."""
    p = pill(state, mode=mode, **attrs)
    # The real one back: `pill` mocks it because a bare fixture has no window,
    # and this fixture's whole job is to give it one worth measuring.
    p._sync_shell = uc.CompactPill._sync_shell.__get__(p)
    p.geometry = mock.Mock()
    # The anchor is *stated*, not faked through `winfo_*`. That is the real
    # contract now: `_sync_shell` tracks where it put the window rather than
    # reading it back, because `winfo_*` lags a `geometry` call and a sync
    # that re-anchored off a stale read walked the window down the screen by
    # the panel's height every time it ran.
    p._shell_xy = (x, y)
    p._capsule_y = y
    p.winfo_rootx = mock.Mock(return_value=x)
    p.winfo_rooty = mock.Mock(return_value=y)
    p.winfo_screenwidth = mock.Mock(return_value=1920)
    p._outside_click_now = mock.Mock(return_value=False)
    return p


class TestThePanelOpensForAskAndNeverForType(unittest.TestCase):
    """The mode → panel map: a hold in a panel mode raises the band, a hold
    in Type changes nothing (README: "Type never opens a panel")."""

    def test_a_hold_in_ask_opens_the_panel_and_arms_the_fresh_start(self):
        p = panel_pill(mode=CONVERSE)
        # On screen, which is the whole condition: an exchange somebody is
        # looking at survives the press. Over a *closed* band the hold starts
        # clean (test_compact_events.py, "a hold over a closed band").
        p._panel_open = True
        p._panel_heard, p._panel_result = "an old question", "an old answer"
        p._talk_start()
        p.session.talk_start.assert_called_once_with()
        self.assertTrue(p._panel_open)
        self.assertEqual(p._panel_mode, CONVERSE)
        # "The next hold starts fresh" (Ask.dc.html) is about the thread, not
        # about wiping a visible answer before a word has arrived — so the
        # hold *arms* the clear and the first partial does it
        # (test_compact_events.py pins both halves).
        self.assertTrue(p._hold_fresh)
        self.assertEqual(p._panel_result, "an old answer")

    def test_a_hold_in_type_opens_nothing(self):
        p = panel_pill(mode=DICTATE)
        p._talk_start()
        self.assertFalse(p._panel_open)

    def test_the_map_is_the_only_place_a_mode_joins_the_panel(self):
        # Type is never here (README); the two panel modes are the whole map.
        self.assertEqual(set(uc.PANEL_SPEC), {REFINE, CONVERSE})
        self.assertNotIn(DICTATE, uc.PANEL_SPEC)


class TestTheRefinesWholeArc(unittest.TestCase):
    """Refine as a mode: hold, raw dictation heard, shaped text back, Send
    pastes. The session side is pinned in test_refine_mode.py; this is the
    panel's half — the mode landed as one `PANEL_SPEC` entry and the
    mechanism already worked."""

    def test_a_hold_in_refine_opens_the_panel(self):
        p = panel_pill(mode=REFINE)
        p._talk_start()
        self.assertTrue(p._panel_open)
        self.assertEqual(p._panel_mode, REFINE)

    def test_the_release_arms_the_ask_path_not_the_paste(self):
        # `_talk_end`'s gate, revisited: PANEL_SPEC covers REFINE, and the
        # paste rule stays Type-only.
        p = panel_pill(State.LISTENING, mode=REFINE)
        p.session.talk_end.return_value = True
        p._talk_end(send=True)
        self.assertTrue(p._ask_pending)
        self.assertFalse(p._send_pending)

    def test_the_shaped_text_lands_in_the_result_block(self):
        from flow.session import Event
        p = panel_pill(State.REFINING, mode=REFINE)
        p._panel_open = True
        p.session.events.return_value = [Event("reply", "the shaped prompt")]
        p._pump_events()
        self.assertEqual(p._panel_result, "the shaped prompt")

    def test_the_send_chip_pastes_the_result_and_closes(self):
        sent = []
        p = panel_pill(mode=REFINE,
                       on_send=lambda text, target=None: sent.append((text, target)) or "")
        p._panel_open = True
        p._panel_mode = REFINE
        p._panel_result = "the shaped prompt"
        p.paste_target = 0xBEEF
        # Off the layout, not the module constant: the footer travels with the
        # band's bottom edge and the band travels with its text.
        send_rect = p._panel_layout().send
        p._panel_click(mock.Mock(x=send_rect[0] + 4, y=send_rect[1] + 4))
        self.assertEqual(sent, [("the shaped prompt", 0xBEEF)])
        self.assertFalse(p._panel_open)

    def test_the_refine_panel_draws_the_gold_tag_and_send(self):
        p = panel_pill(mode=REFINE)
        p._panel_open = True
        p._panel_mode = REFINE
        p._panel_heard = "the raw dictation"
        p._panel_heard_final = True
        p._panel_result = "the shaped prompt"
        p._draw()
        texts = [t[1] for t in p.canvas.texts]
        self.assertIn("heard", texts)
        self.assertIn("refined for this repo", texts)
        self.assertIn("hold the mic to say more", texts)
        self.assertIn("Send", texts)
        # The tag carries the hue — Refine's result has no accent bar
        # (Refine.dc.html; the bar is Ask's card).
        gold = [t[1] for t in p.canvas.texts if t[2] == uc.REFINE_GOLD]
        self.assertEqual(gold, ["refined for this repo"])
        self.assertEqual([r for r in p.canvas.rects if r[4] == uc.REFINE_GOLD],
                         [])
        heard = [t for t in p.canvas.texts if t[1] == "the raw dictation"]
        self.assertEqual(heard[0][2], uc.PLACEHOLDER)

    def test_the_tap_cycles_three_ways_for_free(self):
        # The tap calls the session's cycle with no opinion of its own — the
        # three-way order is toggle_mode's (test_refine_mode.py pins it), so
        # Type → Refine → Ask cost the pill nothing.
        p = pill(mode=REFINE)
        p._on_press()
        p._on_release()
        p.session.toggle_mode.assert_called_once_with()


class TestTheAsksWholeArc(unittest.TestCase):
    """Hold, partials, release, draft, reply — the panel's question and answer."""

    def test_a_partial_is_the_heard_blocks_live_text(self):
        from flow.session import Event
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p._talk_start()
        p.session.events.return_value = [Event("partial", "where does the")]
        p._pump_events()
        self.assertEqual(p._panel_heard, "where does the")
        self.assertFalse(p._panel_heard_final)  # italic until the draft lands

    def test_a_partial_with_no_panel_is_still_nothing(self):
        from flow.session import Event
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p.session.events.return_value = [Event("partial", "where does the")]
        p._pump_events()
        self.assertEqual(p._panel_heard, "")

    def test_the_release_arms_the_ask_and_the_pump_fires_it(self):
        from flow.session import Event
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p._talk_start()
        p.session.talk_end.return_value = True  # words are in flight
        p._talk_end(send=True)
        self.assertTrue(p._ask_pending)
        p.session.send.assert_not_called()
        p.session.events.return_value = [Event("draft", "where does the pill decide?")]
        p.session.draft.text = "where does the pill decide?"
        p._pump_events()
        p._pump_send()
        # The question goes to the CLI — session.send() in converse asks —
        # and is never pasted: on_send is Type's path, not this one's.
        p.session.send.assert_called_once_with()
        self.assertFalse(p._ask_pending)
        self.assertEqual(p._panel_heard, "where does the pill decide?")
        self.assertTrue(p._panel_heard_final)
        self.assertEqual(p._panel_result, "")  # cleared for the coming answer

    def test_the_reply_lands_in_the_result_block(self):
        from flow.session import Event
        p = panel_pill(State.ASKING, mode=CONVERSE)
        p._panel_open = True
        p.session.events.return_value = [Event("reply", "PILL_HOLD_SEC, 0.30 s.")]
        p._pump_events()
        self.assertEqual(p._panel_result, "PILL_HOLD_SEC, 0.30 s.")

    def test_a_reply_reopens_a_closed_panel_rather_than_landing_nowhere(self):
        from flow.session import Event
        p = panel_pill(State.ASKING, mode=CONVERSE)
        p.session.events.return_value = [Event("reply", "the answer")]
        p._pump_events()
        # P2: Esc was "not looking right now", not "never tell me".
        self.assertTrue(p._panel_open)
        self.assertEqual(p._panel_result, "the answer")


class TestThePanelCloses(unittest.TestCase):
    def test_the_cancel_hotkey_is_the_panels_esc(self):
        p = panel_pill(mode=CONVERSE)
        p._talk_start()
        self.assertTrue(p._panel_open)
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["cancel"]
        p._drain_hotkeys()
        self.assertFalse(p._panel_open)

    def test_a_mode_switch_closes_the_band_it_does_not_belong_to(self):
        from flow.session import Event
        p = panel_pill(mode=CONVERSE)
        p._talk_start()
        p.session.events.return_value = [Event("mode", DICTATE)]
        p._pump_events()
        self.assertFalse(p._panel_open)

    def test_a_click_outside_closes_via_the_frame_poll(self):
        p = panel_pill(mode=CONVERSE)
        p._talk_start()
        p._outside_click_now.return_value = True
        p._frame()
        self.assertFalse(p._panel_open)

    def test_closing_drops_an_armed_ask(self):
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p._talk_start()
        p.session.talk_end.return_value = True
        p._talk_end(send=True)
        self.assertTrue(p._ask_pending)
        p._close_panel()
        self.assertFalse(p._ask_pending)

    def test_the_close_chip_closes_and_only_the_band_hit_tested(self):
        p = panel_pill(mode=CONVERSE)
        p._talk_start()
        close = p._panel_layout().close
        x = (close[0] + close[2]) // 2
        p._on_press(mock.Mock(x=x, y=(close[1] + close[3]) // 2,
                              x_root=0, y_root=0))
        self.assertFalse(p._panel_open)
        # The close never moves whatever the band does: it is in the strip,
        # which is the band's top row.
        self.assertEqual(close, uc.CLOSE_RECT)
        # And a band click that hits no chip is not a hold either — the foot
        # is the holdable part, the band is buttons and text.
        p._open_panel()
        p._on_press(mock.Mock(x=200, y=100, x_root=0, y_root=0))
        self.assertIsNone(p._press_at)


class TestTheFootStaysHoldable(unittest.TestCase):
    """"The pill never hides and never moves" — a press in the foot band is a
    hold, which in Ask is the reply path."""

    def test_a_press_in_the_foot_is_a_hold_not_a_chip(self):
        p = panel_pill(State.IDLE, mode=CONVERSE)
        p._talk_start()
        p._talk_end(send=False)
        # Below the band, whatever height the band came out at.
        foot = p._panel_layout().band_h + 17
        p._on_press(mock.Mock(x=60, y=foot, x_root=0, y_root=0))
        self.assertIsNotNone(p._press_at)

    def test_a_hold_while_the_panel_is_up_asks_a_reply(self):
        from flow.session import Event
        p = panel_pill(State.IDLE, mode=CONVERSE)
        # The first exchange is on screen.
        p._talk_start()
        p.session.talk_end.return_value = True
        p._talk_end(send=True)
        p._ask()
        p._panel_result = "the first answer"
        # The foot hold starts fresh — "hold the mic to reply" — and the
        # clearing waits for the words, so the answer is still readable until
        # the reply's own first partial lands.
        p._talk_start()
        self.assertEqual(p._panel_result, "the first answer")
        p.session.events.return_value = [Event("partial", "and what about")]
        p._pump_events()
        self.assertEqual(p._panel_result, "")
        p.session.talk_end.return_value = True
        p._talk_end(send=True)
        self.assertTrue(p._ask_pending)
        # And it is the ask that is armed, never the paste.
        self.assertFalse(p._send_pending)


class TestTheWindowGrowsAndReturns(unittest.TestCase):
    def test_the_geometry_is_400_wide_with_the_band_120_without(self):
        p = panel_pill(mode=CONVERSE, x=100, y=400)
        p._open_panel()
        # Nothing has been said, so the band is at its floor — `PANEL_H`, the
        # resting proportions the artboards drew. The foot's bottom edge
        # anchors: 400 + 34 - 234 = 200.
        self.assertEqual(p._panel_h(), uc.PANEL_H)
        p.geometry.assert_called_once_with("400x234+100+200")
        self.assertEqual((p._shell_w, p._shell_h), (uc.PANEL_W, 234))
        # Closing returns to 120×34 on the same capsule top — which needs no
        # help from the test, because the anchor never moved.
        p._close_panel()
        p.geometry.assert_called_with("120x34+100+400")

    def test_the_band_grows_left_rather_than_off_the_right_edge(self):
        p = panel_pill(mode=CONVERSE, x=1800, y=400)
        p._open_panel()
        p.geometry.assert_called_once_with("400x234+1520+200")

    def test_the_shell_sync_no_ops_when_nothing_changed(self):
        p = panel_pill()
        p._sync_shell()
        p.geometry.assert_not_called()


class TestThePanelsChips(unittest.TestCase):
    def test_copy_puts_the_result_on_the_clipboard_and_leaves_the_panel_up(self):
        p = panel_pill(mode=CONVERSE)
        p._panel_open = True
        p._panel_result = "the answer"
        copy_rect = p._panel_layout().copy
        with mock.patch.object(uc, "_copy_to_clipboard",
                               return_value="") as copy:
            p._panel_click(mock.Mock(x=copy_rect[0] + 4, y=copy_rect[1] + 4))
        copy.assert_called_once_with(p, "the answer")
        self.assertTrue(p._panel_open)  # "Copy leaves the panel up"

    def test_copy_falls_back_to_the_heard_question(self):
        p = panel_pill(mode=CONVERSE)
        p._panel_heard = "the question"
        with mock.patch.object(uc, "_copy_to_clipboard",
                               return_value="") as copy:
            p._copy_result()
        copy.assert_called_once_with(p, "the question")

    def test_a_copy_problem_is_a_red_flash(self):
        p = panel_pill(mode=CONVERSE)
        p._panel_result = "the answer"
        with mock.patch.object(uc, "_copy_to_clipboard",
                               return_value="could not copy: busy"):
            p._copy_result()
        self.assertEqual(p._flash, uc.FLASH_FRAMES)

    def test_asks_footer_has_no_send_to_click(self):
        # The mechanism exists (`_panel_send`) but no two-mode spec sets
        # "send" — the Send rect is dead while the session has two modes.
        p = panel_pill(mode=CONVERSE)
        p._panel_open = True
        p._panel_result = "the answer"
        send_rect = p._panel_layout().send
        with mock.patch.object(p, "_panel_send") as send:
            p._panel_click(mock.Mock(x=send_rect[0] + 4, y=send_rect[1] + 4))
        send.assert_not_called()
        self.assertFalse(uc.PANEL_SPEC[CONVERSE]["send"])

    def test_the_send_mechanism_pastes_the_result_and_closes(self):
        # Item 4's Refine flow, wired ahead of it: the result goes where the
        # user was, through item 1's on_send contract, target included.
        sent = []
        p = panel_pill(mode=CONVERSE,
                       on_send=lambda text, target=None: sent.append((text, target)) or "")
        p._panel_open = True
        p._panel_result = "the refined text"
        p.paste_target = 0xBEEF
        p._panel_send()
        self.assertEqual(sent, [("the refined text", 0xBEEF)])
        self.assertFalse(p._panel_open)


class TestThePanelDraws(unittest.TestCase):
    """The band against the recording fake: strip, heard, result, footer, and
    the foot below them — the same discipline as the capsule tests."""

    def open(self, **attrs):
        p = panel_pill(mode=CONVERSE, **attrs)
        p._panel_open = True
        p._panel_mode = CONVERSE
        return p

    def test_the_band_the_seam_and_the_strip(self):
        p = self.open()
        p._draw()
        # The band is SHELL with the RING_OUTER border; the strip is its own
        # darker fill — both polygons, both present.
        fills = {(fill, outline) for _a, fill, outline in p.canvas.polys}
        self.assertIn((uc.SHELL, uc.RING_OUTER), fills)
        self.assertIn((uc.STRIP, ""), fills)
        # The seam between panel and foot, and the strip's own divider.
        seams = [fill for _a, fill, _w in p.canvas.lines if fill == uc.SEAM]
        self.assertEqual(len(seams), 2)

    def test_the_strip_names_the_workspace(self):
        p = self.open()
        p._draw()
        texts = [t[1] for t in p.canvas.texts]
        self.assertIn("~/dev/products/flow", texts)
        self.assertIn("grounded", texts)

    def test_the_strip_says_when_there_is_no_workspace(self):
        p = self.open()
        p.session.workspace = ""
        p._draw()
        texts = [t[1] for t in p.canvas.texts]
        self.assertIn("no workspace", texts)
        self.assertIn("plain talk", texts)

    def test_the_heard_block_is_italic_until_final(self):
        p = self.open()
        p._panel_heard = "where does the"
        p._panel_heard_final = False
        p._draw()
        heard = [t for t in p.canvas.texts if t[1] == "where does the"]
        self.assertEqual(len(heard), 1)
        self.assertIn("italic", heard[0][3])
        p._panel_heard_final = True
        p._draw()
        heard = [t for t in p.canvas.texts if t[1] == "where does the"]
        self.assertNotIn("italic", heard[0][3] if len(heard[0][3]) > 3 else ())

    def test_the_result_block_carries_the_modes_accent(self):
        p = self.open()
        p._panel_result = "the answer"
        p._draw()
        self.assertIn("the answer", [t[1] for t in p.canvas.texts])
        bars = [r for r in p.canvas.rects if r[4] == uc.CARD_ACCENT]
        self.assertEqual(len(bars), 1)

    def test_asks_footer_is_copy_and_the_hint_no_send(self):
        p = self.open()
        p._draw()
        texts = [t[1] for t in p.canvas.texts]
        self.assertIn("Copy", texts)
        self.assertIn("hold the mic to reply", texts)
        self.assertNotIn("Send", texts)

    def test_the_foot_is_the_pill_squared_on_the_join(self):
        p = self.open()
        p._draw()
        # Square on the join, round below it: the foot's top corners are
        # exactly the band's own corners, and its bottom is a pair of
        # quarter-circles (gen.py `.foot`: border-radius 0 0 17px 17px).
        # The join is wherever the band ended, not a constant.
        band = p._panel_layout().band_h
        (pts, bbox), = [b for b in bodies(p, uc.SHELL) if b[1][1] == band]
        self.assertEqual(bbox, (0, band, uc.PANEL_W, band + uc.PILL_H))
        self.assertIn((0, band), pts)
        self.assertIn((uc.PANEL_W, band), pts)
        # The foot's face: forty bars, not the capsule's fifteen.
        self.assertEqual(len(meter_bars(p, uc.DIM)), uc.BARS_FOOT)

    def test_the_state_ring_wraps_the_foot_including_the_top(self):
        p = self.open(state=State.LISTENING)
        p._draw()
        band = p._panel_layout().band_h
        # One closed 1 px trace round the foot — the top run included, which
        # is the box-shadow wrapping a side that `border-top: 0` does not.
        (ring, width), = strokes(p, uc.HEARING)
        self.assertEqual(width, 1)
        self.assertEqual(ring[0], ring[-1])
        # And the panel band above keeps its own neutral border: nothing
        # state-coloured up there.
        self.assertTrue(all(y >= band for _x, y in ring))
        # The foot's own border stops at the seam: open, not closed.
        (outer, _w), = [st for st in strokes(p, uc.RING_OUTER)
                        if st[0][0][1] >= band]
        self.assertNotEqual(outer[0], outer[-1])


class TestTheMenuIsWorkspaceDcHtml(unittest.TestCase):
    """The right-click menu: three modes with the check on the current one,
    the hints as disabled entries (Tk has no sub-line row), Switch workspace
    with the path beneath it, Workbench setup with its hint, and Design — the
    one row the artboard does not draw, because without it the two surfaces
    cannot be reached from each other."""

    def build(self, mode=DICTATE, workspace="~/dev/products/flow",
              design="compact"):
        p = pill(mode=mode)
        p.session.workspace = workspace
        p.session.profile = mock.Mock(design=design)
        m = FakeMenu()
        with mock.patch.object(uc.tk, "StringVar", FakeVar), \
                mock.patch.object(uc, "_dark_menu", FakeMenu):
            p._populate_menu(m)
        return p, m

    def test_the_structure_in_order(self):
        _p, m = self.build()
        self.assertEqual(
            m.order,
            ["Type", "Refine", "Ask",
             "tap the pill to cycle",
             "Switch workspace", "~/dev/products/flow",
             "Workbench setup", "mic, CLI, where it pastes",
             "Design"])
        # The hints are disabled entries, never verbs.
        for hint in ("tap the pill to cycle", "~/dev/products/flow",
                     "mic, CLI, where it pastes"):
            self.assertIsNone(m.commands[hint])

    def test_design_names_both_surfaces_and_marks_the_one_running(self):
        # The shipped design's own Design menu, in this surface's idiom: the
        # same names and the same `(current)` marker, so somebody who has seen
        # one recognises the other.
        _p, m = self.build(design="compact")
        sub = m.cascades["Design"]
        self.assertEqual(sub.order, ["Current", "Compact   (current)"])

    def test_design_writes_the_choice_and_saves_it(self):
        p, m = self.build()
        m.cascades["Design"].commands["Current"]()
        self.assertEqual(p.session.profile.design, "current")
        p.session.profile.save.assert_called_once_with()

    def test_a_design_save_that_failed_is_visible(self):
        p, m = self.build()
        p.session.profile.save.return_value = False
        m.cascades["Design"].commands["Current"]()
        self.assertEqual(p._flash, uc.FLASH_FRAMES)

    def test_no_profile_writes_nothing_and_does_not_raise(self):
        p, m = self.build()
        p.session.profile = None
        m.cascades["Design"].commands["Current"]()
        self.assertEqual(p._flash, 0)

    def test_the_menu_ends_where_the_artboard_ends(self):
        # "There is no preferences window and no tray menu. The pill is the
        # only thing you can right-click, and this is everything it offers"
        # (Workspace.dc.html). Hide to tray and Quit were rows here and are
        # not on the canvas; they live on the tray icon, which `_start_tray`
        # raises at launch so that removing them costs nobody the way out.
        # Design is the one row let back in, on 2026-09-04 and for a named
        # reason. Everything else the canvas leaves out is still out.
        _p, m = self.build()
        self.assertEqual(m.order[-1], "Design")
        for gone in ("Hide to tray", "Quit"):
            self.assertNotIn(gone, m.order)

    def test_the_check_is_on_the_current_mode(self):
        for mode, name in ((DICTATE, "Type"), (REFINE, "Refine"),
                           (CONVERSE, "Ask")):
            with self.subTest(mode=mode):
                _p, m = self.build(mode=mode)
                # Three radios, one tick: FakeVar recorded the value the
                # variable was made with.
                self.assertEqual([label for label, _v in m.radios],
                                 ["Type", "Refine", "Ask"])

    def test_choosing_a_mode_goes_straight_at_it(self):
        p, m = self.build()
        m.commands["Refine"]()
        p.session.toggle_mode.assert_called_once_with(to=REFINE)

    def test_the_modes_are_named_for_the_job_not_the_mechanism(self):
        self.assertEqual(uc.MODE_NAME,
                         {DICTATE: "Type", REFINE: "Refine", CONVERSE: "Ask"})

    def test_the_workspace_line_says_when_there_is_none(self):
        _p, m = self.build(workspace="")
        self.assertIn("no workspace", m.order)

    def test_the_menu_is_rebuilt_on_open(self):
        # The check and the path are the values of now: switching modes and
        # re-opening must move the tick, not leave it where the menu was made.
        p = pill(mode=DICTATE)
        p.session.workspace = "~/dev/products/flow"
        m = FakeMenu()
        m.delete = mock.Mock()
        p._menu = m
        p.session.profile = mock.Mock(design="compact")
        with mock.patch.object(uc.tk, "StringVar", FakeVar),                 mock.patch.object(uc, "_dark_menu", FakeMenu):
            p._on_menu(mock.Mock(x_root=10, y_root=10))
        m.delete.assert_called_once_with(0, "end")
        self.assertIn("Type", m.radios[0])


class TestThePalette(unittest.TestCase):
    """The palette's logic, driven headless: the filter, the pinned row, the
    choice. The window and the keys are thin triggers beside it."""

    WORKSPACES = ("~/dev/products/flow", "~/dev/products/flow-lite-notes",
                  "~/work/riverflow")

    def palette(self, query=""):
        pal = uc._Palette(self.WORKSPACES)
        pal.query = query
        return pal

    def test_the_filter_is_a_case_insensitive_substring_in_profile_order(self):
        rows = self.palette("FLO").rows()
        # The profile's own order is the ranking — the filter never re-sorts.
        self.assertEqual([label for label, _n in rows],
                         ["~/dev/products/flow", "~/dev/products/flow-lite-notes",
                          "~/work/riverflow", uc._Palette.NONE])

    def test_the_filter_narrows(self):
        rows = self.palette("lite").rows()
        self.assertEqual([label for label, _n in rows],
                         ["~/dev/products/flow-lite-notes", uc._Palette.NONE])

    def test_no_workspace_is_always_last_and_never_filtered_out(self):
        rows = self.palette("zzz-no-such-folder").rows()
        self.assertEqual(rows, [(uc._Palette.NONE, True)])

    def test_choosing_the_pinned_row_clears_the_workspace(self):
        pal = self.palette("lite")
        self.assertIsNone(pal.choose(1))
        self.assertEqual(pal.choose(0), "~/dev/products/flow-lite-notes")

    def test_typing_and_backspace_edit_the_query(self):
        pal = uc._Palette(self.WORKSPACES)
        for ch in "flo":
            pal.type(ch)
        self.assertEqual(pal.query, "flo")
        pal.backspace()
        self.assertEqual(pal.query, "fl")

    def test_the_recents_come_from_the_profile_record(self):
        p = pill()
        p.session.profile.workspaces = ["~/a", "~/b"]
        self.assertEqual(p._workspace_recents(), ["~/a", "~/b"])


class TestThePaletteWindow(unittest.TestCase):
    """The thin triggers: keys and clicks on the box reach the palette's
    logic and the session, and every way out closes."""

    def open(self):
        p = panel_pill(mode=CONVERSE)
        p._palette = uc._Palette(["~/dev/products/flow", "~/work/riverflow"])
        p._box_kind = "palette"
        p._sync_box = mock.Mock()
        p._close_box = mock.Mock(wraps=lambda: setattr(p, "_palette", None))
        return p

    def key(self, p, keysym, char=""):
        p._on_box_key(mock.Mock(keysym=keysym, char=char))

    def test_letters_and_backspace_drive_the_query(self):
        p = self.open()
        self.key(p, "f", "f")
        self.key(p, "l", "l")
        self.key(p, "BackSpace")
        self.assertEqual(p._palette.query, "f")
        self.assertEqual(p._sync_box.call_count, 3)

    def test_enter_sets_the_top_hit_and_closes(self):
        p = self.open()
        for ch in "river":
            self.key(p, ch, ch)
        self.key(p, "Return")
        p.session.set_workspace.assert_called_once_with("~/work/riverflow")
        p._close_box.assert_called_once()

    def test_enter_on_the_pinned_row_clears_the_workspace(self):
        p = self.open()
        self.key(p, "z", "z")  # narrows to the pinned row alone
        self.key(p, "Return")
        p.session.set_workspace.assert_called_once_with(None)

    def test_esc_leaves_it_without_touching_the_workspace(self):
        p = self.open()
        self.key(p, "Escape")
        p.session.set_workspace.assert_not_called()
        p._close_box.assert_called_once()

    def test_a_row_click_is_the_same_choice(self):
        p = self.open()
        y = uc.PALETTE_FIELD_H + uc.PALETTE_ROW_H + 5  # the second row
        p._on_box_click(mock.Mock(y=y))
        p.session.set_workspace.assert_called_once_with("~/work/riverflow")
        p._close_box.assert_called_once()


class TestThePaletteAndSetupDraw(unittest.TestCase):
    def test_the_palette_draws_the_top_hit_lit_and_the_pinned_row_grey(self):
        p = panel_pill(mode=CONVERSE)
        p._palette = uc._Palette(["~/dev/products/flow", "~/work/riverflow"])
        p._palette.query = "flo"
        p._box_kind = "palette"
        c = Canvas()
        p._draw_palette(c)
        # The top row carries the highlight (CHIP), the caret is the green
        # line, the pinned row reads grey, and the footer says the keys.
        self.assertTrue(any(r[4] == uc.CHIP for r in c.rects))
        self.assertTrue(any(fill == uc.HEARING for _a, fill, _w in c.lines))
        labels = {t[1]: t[2] for t in c.texts}
        self.assertEqual(labels[uc._Palette.NONE], uc.PLACEHOLDER)
        self.assertEqual(labels["~/dev/products/flow"], uc.CODE)
        self.assertIn("↵ set    esc leave it", labels)

    def test_the_setup_box_draws_three_read_only_lines(self):
        p = panel_pill(mode=CONVERSE)
        p.session.mic = mock.Mock(device_name="Yeti Nano")
        p.session.provider = "claude"
        p.session.pastes = True
        c = Canvas()
        p._draw_setup(c)
        texts = [t[1] for t in c.texts]
        for line in ("Microphone", "Yeti Nano", "Agent CLI", "claude",
                     "On release", "paste into last window"):
            self.assertIn(line, texts)

    def test_the_setup_lines_say_none_found_and_the_clipboard_answer(self):
        p = panel_pill(mode=CONVERSE)
        p.session.mic = mock.Mock(device_name="")
        p.session.provider = ""
        p.session.pastes = False
        rows = p._setup_rows()
        self.assertEqual(rows, [("Microphone", "none found"),
                                ("Agent CLI", "none found"),
                                ("On release", "copy — you paste it")])


class TestTheTrayStays(unittest.TestCase):
    """Kept against the canvas (decided 2026-09-03): the escape hatch if the
    pill is ever dragged somewhere unreachable."""

    def tray_pill(self):
        p = panel_pill()
        p.withdraw = mock.Mock()
        p.deiconify = mock.Mock()
        p.lift = mock.Mock()
        return p

    def test_hide_to_tray_starts_the_icon_and_withdraws(self):
        p = self.tray_pill()
        icon = mock.Mock()
        icon.start.return_value = True
        with mock.patch.object(uc.tray, "available", return_value=True), \
                mock.patch.object(uc.tray, "Tray", return_value=icon):
            self.assertTrue(p.hide_to_tray())
        icon.start.assert_called_once_with()
        p.withdraw.assert_called_once_with()
        self.assertTrue(p._hidden)
        self.assertEqual(p._home, (100, 400))

    def test_no_notification_area_means_no_hiding(self):
        # Invariant 4 in a new place: a withdrawn window with no icon behind
        # it is a Flow only Task Manager can reach.
        p = self.tray_pill()
        with mock.patch.object(uc.tray, "available", return_value=False):
            self.assertFalse(p.hide_to_tray())
        p.withdraw.assert_not_called()
        self.assertFalse(p._hidden)

    def test_the_icon_is_the_way_back(self):
        p = self.tray_pill()
        p._hidden = True
        p._home = (100, 400)
        p.show_from_tray()
        p.geometry.assert_called_with("+100+400")
        p.deiconify.assert_called_once_with()
        self.assertFalse(p._hidden)

    def test_the_tray_queue_is_drained_on_the_frame(self):
        import queue as q
        p = self.tray_pill()
        p._tray = mock.Mock()
        p._tray_events = q.Queue()
        p._tray_events.put(uc.tray.SHOW)
        p._hidden = True
        p._drain_tray()
        p.deiconify.assert_called_once_with()

    def test_quit_stops_the_tray_before_the_window_goes(self):
        p = self.tray_pill()
        p._tray = mock.Mock()
        p.destroy = mock.Mock()
        p.quit_app()
        p._tray.stop.assert_called_once_with()
        p.session.close.assert_called_once_with()


class TestNoCliMeansTypeOnly(unittest.TestCase):
    """States.dc.html, first case: with no agent CLI on PATH, Refine and Ask
    are simply not offered — grey, not red. Type never depends on the CLI."""

    def test_a_tap_with_no_cli_does_not_cycle(self):
        p = pill(mode=DICTATE)
        p.session.provider = ""
        p._on_press()
        p._on_release()
        p.session.toggle_mode.assert_not_called()
        self.assertEqual(p._flash, 0)  # grey, not red: nothing happened

    def test_a_tap_with_a_cli_cycles(self):
        p = pill(mode=DICTATE)
        p._on_press()
        p._on_release()
        p.session.toggle_mode.assert_called_once_with()

    def test_the_mode_chord_follows_the_same_rule(self):
        p = pill(mode=DICTATE)
        p.session.provider = ""
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["mode"]
        p._drain_hotkeys()
        p.session.toggle_mode.assert_not_called()

    def test_already_off_type_the_cycle_is_the_way_back(self):
        # The CLI vanished mid-session: Type is the one mode left to offer.
        p = pill(mode=REFINE)
        p.session.provider = ""
        p._on_press()
        p._on_release()
        p.session.toggle_mode.assert_called_once_with(to=DICTATE)

    def test_the_menu_greys_refine_and_ask_rather_than_hiding_them(self):
        p = pill(mode=DICTATE)
        p.session.provider = ""
        p.session.profile = mock.Mock(design="compact")
        m = mock.Mock()
        with mock.patch.object(uc.tk, "StringVar", FakeVar),                 mock.patch.object(uc, "_dark_menu", FakeMenu):
            p._populate_menu(m)
        for name in ("Refine", "Ask"):
            m.add_radiobutton.assert_any_call(
                label=name, value=name, variable=mock.ANY,
                command=mock.ANY, state="disabled")
        # And Type stays a working radio.
        m.add_radiobutton.assert_any_call(
            label="Type", value="Type", variable=mock.ANY, command=mock.ANY)


class TestTheMicIsGone(unittest.TestCase):
    """States.dc.html, second case: slashed glyph, red ring, and the one
    gesture the pill refuses outright."""

    def test_a_hold_into_a_dead_mic_sets_the_slash_and_the_ring(self):
        p = pill(State.IDLE, armed=False)
        p.session.talk_start.side_effect = OSError("device held exclusively")
        p._talk_start()
        self.assertTrue(p._mic_gone)
        self.assertFalse(p._press_talking)
        self.assertEqual(p._ring_colour(), "#F2584A")
        self.assertEqual(p._glyph_tint(), "#F2584A")

    def test_the_refusal_is_persistent_not_a_flash(self):
        p = pill(State.IDLE, armed=False)
        p.session.talk_start.side_effect = OSError("gone")
        p._talk_start()
        p._flash = 0  # the flash can end; the answer cannot
        self.assertEqual(p._ring_colour(), "#F2584A")

    def test_a_capture_that_answers_clears_the_slash(self):
        p = pill(State.IDLE, armed=False)
        p._mic_gone = True
        p._talk_start()
        self.assertFalse(p._mic_gone)

    def test_the_slashed_glyph_is_drawn(self):
        p = pill(State.IDLE, armed=False, _mic_gone=True)
        p._draw()
        # gen.py's slash: one diagonal across the glyph, in the ring's red —
        # the only red line that moves on both axes (the ring's runs are
        # horizontal, the stem vertical).
        slashes = [a for a, _w in segments(p, "#F2584A")
                   if a[0] != a[2] and a[1] != a[3]]
        coords, = slashes
        x0, y0 = coords[0] - uc.MIC_X, coords[1] - uc.MIC_Y
        x1, y1 = coords[2] - uc.MIC_X, coords[3] - uc.MIC_Y
        self.assertEqual((round(x0, 1), round(y0, 1),
                          round(x1, 1), round(y1, 1)),
                         (1.6, 1.8, 12.4, 16.4))

    def test_a_disarm_that_is_not_a_release_means_the_device_died(self):
        from flow.session import Event
        p = pill(State.LISTENING)
        p.session.events.return_value = [Event("disarm", "device lost")]
        p._pump_events()
        self.assertTrue(p._mic_gone)
        self.assertFalse(p.armed)

    def test_a_release_disarm_is_ordinary(self):
        from flow.session import Event
        p = pill(State.IDLE)
        p.session.events.return_value = [Event("disarm", "push-to-talk")]
        p._pump_events()
        self.assertFalse(p._mic_gone)

    def test_the_pump_lets_a_dead_hold_become_nothing_not_a_tap(self):
        p = pill(armed=False)
        p.session.talk_start.side_effect = OSError("gone")
        with mock.patch.object(uc.time, "perf_counter", return_value=100.0):
            p._on_press()
        with mock.patch.object(
                uc.time, "perf_counter",
                return_value=100.0 + uc.PILL_HOLD_SEC + 0.01):
            p._pump_press()
        self.assertFalse(p.armed)
        self.assertIsNone(p._press_at)  # over: no tap, no cycle, no ring claim


class TestHeldNothingSaid(unittest.TestCase):
    """States.dc.html, third case: straight back to grey. No panel, no toast."""

    def test_a_silent_hold_in_a_panel_mode_closes_the_band_it_raised(self):
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p._talk_start()
        self.assertTrue(p._panel_open)
        p.session.talk_end.return_value = False  # nothing was said
        p._talk_end(send=True)
        self.assertFalse(p._panel_open)
        self.assertFalse(p._ask_pending)

    def test_a_silent_hold_leaves_an_exchange_on_screen(self):
        # The band has something to show — silence beside it changes nothing.
        p = panel_pill(State.LISTENING, mode=CONVERSE)
        p._panel_open = True
        p._panel_result = "the answer from before"
        p.session.talk_end.return_value = False
        p._talk_end(send=True)
        self.assertTrue(p._panel_open)

    def test_a_silent_hold_in_type_was_already_nothing(self):
        p = pill(State.IDLE, armed=False)
        p.session.talk_end.return_value = False
        p._talk_end(send=True)
        self.assertFalse(p._send_pending)
        self.assertFalse(p._panel_open)
        self.assertEqual(p._flash, 0)


class TestRefineFailed(unittest.TestCase):
    """States.dc.html, fourth case: the panel holds the raw dictation, the
    CLI's own last line is the message, and Send still works."""

    def failed(self):
        from flow.session import Event
        p = panel_pill(State.REFINING, mode=REFINE)
        p._panel_open = True
        p._panel_mode = REFINE
        p._panel_heard = "make the pill not show any controls"
        p.session.events.return_value = [
            Event("error", "refine failed (timed out) — draft unchanged")]
        p._pump_events()
        return p

    def test_the_clis_last_line_is_the_result_block(self):
        p = self.failed()
        self.assertTrue(p._panel_failed)
        self.assertEqual(p._panel_result,
                         "refine failed (timed out) — draft unchanged")
        self.assertEqual(p._flash, uc.FLASH_FRAMES)

    def test_send_still_works_and_sends_the_raw_text(self):
        sent = []
        p = self.failed()
        p.on_send = lambda text, target=None: sent.append(text) or ""
        p._panel_send()
        # Unrefined text beats no text.
        self.assertEqual(sent, ["make the pill not show any controls"])
        self.assertFalse(p._panel_open)

    def test_the_failure_draws_without_the_gold_tag(self):
        # The suppression is the layout's now (`result_tag_y` is None on a
        # failure), so the block starts where the tag would have been rather
        # than leaving a gap that claims a refinement that did not happen.
        p = self.failed()
        layout = p._panel_layout()
        self.assertIsNone(layout.result_tag_y)
        p._draw()
        texts = [t[1] for t in p.canvas.texts]
        self.assertNotIn("refined for this repo", texts)
        self.assertIn("refine failed (timed out) — draft unchanged", texts)

    def test_copy_on_a_failure_copies_the_raw_text_too(self):
        p = self.failed()
        with mock.patch.object(uc, "_copy_to_clipboard",
                               return_value="") as copy:
            p._copy_result()
        copy.assert_called_once_with(p, "make the pill not show any controls")

    def test_a_later_reply_clears_the_failure(self):
        from flow.session import Event
        p = self.failed()
        p.session.events.return_value = [Event("reply", "the shaped prompt")]
        p._pump_events()
        self.assertFalse(p._panel_failed)
        self.assertEqual(p._panel_result, "the shaped prompt")

    def test_an_error_that_is_not_the_clis_leaves_the_panel_alone(self):
        from flow.session import Event
        p = panel_pill(State.IDLE, mode=REFINE)
        p._panel_open = True
        p._panel_result = "the shaped prompt"
        p.session.events.return_value = [Event("error", "model failed to load: x")]
        p._pump_events()
        self.assertFalse(p._panel_failed)
        self.assertEqual(p._panel_result, "the shaped prompt")


class TestTheWorkspaceIsGone(unittest.TestCase):
    """States.dc.html, fifth case: amber once, at launch, then no workspace."""

    def test_a_stored_path_that_is_gone_arms_the_amber_notice(self):
        p = pill()
        p.session.profile.workspace = "~/work/definitely-not-here-7e3f9a"
        p._check_workspace_gone()
        self.assertEqual(p._recover, uc.RECOVER_FRAMES)

    def test_a_path_that_exists_is_not_a_notice(self):
        p = pill()
        p.session.profile.workspace = "."
        p._check_workspace_gone()
        self.assertEqual(p._recover, 0)

    def test_the_amber_ring_shows_once_and_counts_down(self):
        p = pill(State.IDLE, armed=False, _recover=2)
        self.assertEqual(p._ring_colour(), "#E8A33D")
        p._frame()
        self.assertEqual(p._recover, 1)
        p._frame()
        self.assertEqual(p._recover, 0)
        self.assertEqual(p._ring_colour(), "")  # then grey, as if nothing was

    def test_a_hold_ends_the_notice_early(self):
        p = pill(State.IDLE, armed=False, _recover=200)
        p._talk_start()
        self.assertEqual(p._recover, 0)


class TestLiteCopiesAndSaysSo(unittest.TestCase):
    """States.dc.html, last case: the clipboard, plus `copied — press Ctrl+V`
    under the pill. Not an error state."""

    def test_a_send_with_no_handler_copies_and_shows_the_line(self):
        s = session(state=State.DRAFT)
        s.send.return_value = "the words"
        p = panel_pill(x=100, y=400)
        p.session = s
        p.on_send = None
        with mock.patch.object(uc, "_copy_to_clipboard",
                               return_value="") as copy:
            p._send()
        copy.assert_called_once_with(p, "the words")
        self.assertEqual(p._flash, 0)  # not an error state
        self.assertEqual(p._notice, uc.COPIED_FRAMES)
        # The window grew 18 px *under* the capsule — which did not move —
        # and out to fit the sentence, because a strip that kept the capsule's
        # 120 px simply cut its own message in half.
        geom = p.geometry.call_args.args[0]
        size, x, y = geom.split("+")
        w, h = (int(v) for v in size.split("x"))
        self.assertEqual((h, x, y), (uc.PILL_H + uc.NOTICE_H, "100", "400"))
        self.assertGreaterEqual(w, uc.PILL_W)
        self.assertEqual(w, p._notice_w)

    def test_a_send_with_a_handler_pastes_instead(self):
        sent = []
        p = panel_pill(on_send=lambda text, target=None: sent.append(text) or "")
        p.session.send.return_value = "the words"
        with mock.patch.object(uc, "_copy_to_clipboard") as copy:
            p._send()
        copy.assert_not_called()
        self.assertEqual(sent, ["the words"])
        self.assertEqual(p._notice, 0)

    def test_the_panel_send_follows_the_same_path(self):
        p = panel_pill(mode=REFINE)
        p._panel_open = True
        p._panel_mode = REFINE
        p._panel_result = "the shaped prompt"
        p.on_send = None
        with mock.patch.object(uc, "_copy_to_clipboard",
                               return_value="") as copy:
            p._panel_send()
        copy.assert_called_once_with(p, "the shaped prompt")
        self.assertEqual(p._notice, uc.COPIED_FRAMES)
        self.assertFalse(p._panel_open)

    def test_the_notice_draws_the_line_and_counts_down_to_120(self):
        p = panel_pill(x=100, y=400, _notice=2, _shell_h=uc.PILL_H + uc.NOTICE_H)
        p._draw()
        lines = [t for t in p.canvas.texts if t[1] == "copied — press Ctrl+V"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][2], uc.DIM)  # never an error colour
        p._frame()
        self.assertEqual(p._notice, 1)
        p._frame()
        self.assertEqual(p._notice, 0)
        p.geometry.assert_called_with("120x34+100+400")


if __name__ == "__main__":
    unittest.main()
