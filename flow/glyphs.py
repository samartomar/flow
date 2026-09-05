"""One glyph language, drawn once, for both of Flow's surfaces.

**The language is the compact canvas's.** `design/compact/gen.py` draws every icon
it has as an SVG with `fill="none"`, `stroke-width="1.4"` and `stroke-linecap="round"`
in a 14-18 px box: the mic is a capsule outline with an arc cradle and a stem, the
folder is one path, the close is two crossed lines, the copy is two rounded outlines.
Nothing in it is filled. `flow/ui_compact.py` already drew that way because it was
built from that file; `flow/ui.py` did not — its gear was a filled disc with the hub
punched back out in `SHELL`, its speaker a filled wedge, its command marks 2 px
strokes with a filled pencil nib and filled eyes. Side by side the two surfaces read
as two products, and the difference was never a decision anybody made: one was drawn
from a canvas and the other from scratch, eight months apart.

So the shapes live here, in the canvas's language, and both surfaces call them.
`ui.py` keeps `_gear`, `_speaker`, `_mode_glyph` and every `_glyph_*` as the names its
tables and its tests know, and each one is now a call into this module.

**Strokes, not fills.** The only fill this module will draw is a dot no larger than the
stroke itself — an eye, an antenna tip — because a dot is a stroke that stopped moving.
Everything else is `create_line`, `create_arc`, `create_oval` and `create_rectangle`
with an outline and no fill. That rule is what makes a 14 px mark on one surface and a
16 px mark on the other look like the same hand drew them, and it is also what makes a
mark composite anywhere: a filled shape has to know what is behind it (the shipped
gear's hub was `SHELL`, so the gear could only ever sit on the shell), and a stroked
one does not.

**`STROKE = 1.5`, which is the canvas's 1.4.** Tk 8.6 has no fractional rasterizer, so
1.4 and 1.5 both land as one hard pixel on a `tk.Canvas`; GDI+ (`flow/paint.py`, the
compact surface's real painter) antialiases it, and Windows' own scaling makes it four
or five pixels on the owner's 300 % display. 1.5 is written rather than 1.4 because
the half is the one value that rounds the same way in both directions, and because
`_glyph_command`'s docstring already had to argue for a thinner-than-2 stroke on its
own: at 2 px a 6.8 px loop is a smudge.

**The rounded rectangle here is built from arcs and lines**, not from a smoothed
polygon. `ui_compact._round_rect` dispatches — `GdiCanvas.round_rect` where the painter
is compositing, Tk's `smooth=True` spline where it is not — and those two disagree
about where the edge is: Tk's B-spline pulls inside its control points and GDI+'s
cardinal spline pushes outside them (see `_capsule_points`, which was rewritten for a
version of exactly this bug — a stroke and a fill taken from different primitives left
a dark halo a pixel wide). An arc is an arc on both, so a glyph drawn from arcs is the
same glyph on both.

**Colour is not decided here.** Every function takes one. The shipped row's gold gear,
cyan speaker and pink mode glyph (`ui.ICON_SETTINGS`/`ICON_VOICE`/`ICON_MODE`) and the
four hues the command marks carry (`ui.COMMAND_COLOURS`) were argued for on their own
terms and settled — "This is what you build this is what you promise", said of the
canvas the four hues come from — and the compact surface's mode tints and state ring
were argued for on theirs. Unifying two drawings is not licence to relitigate two
palettes. Shapes and stroke weight are what this module owns.

This module imports nothing from `ui` or `ui_compact`; both import it.
"""

from __future__ import annotations

import math
import tkinter as tk

#: The one stroke weight, for the reasons in the module docstring.
STROKE = 1.5

#: Every glyph but the mic is written on gen.py's 16-unit `viewBox` and scaled to
#: whatever box the caller lays out for — 14 px for the shipped row's icons
#: (`ui.ICON_SIZE`), 16 for its command marks (`ui.MARK_GLYPH`), 13-14 for the
#: compact surface's panel and menu icons. Writing them in units rather than pixels
#: is what lets one drawing serve three sizes.
UNIT = 16

#: The mic is gen.py's own 14x18 — it is the one glyph that is taller than it is
#: wide, and squaring it would either flatten the capsule or float it. `size` is its
#: *width*; the box it draws in is `size` by `size * MIC_ASPECT`.
MIC_UNIT_W, MIC_UNIT_H = 14, 18
MIC_ASPECT = MIC_UNIT_H / MIC_UNIT_W

#: The three session modes `mode()` knows, spelled the way `flow/session.py` spells
#: them. Repeated rather than imported: this module draws, and a drawing module that
#: imports the session is a drawing module that cannot be tested without one.
MODES = ("dictate", "refine", "converse")

#: The cog: how many teeth, and the three radii and two half-angles that make a tooth
#: a tooth. **The first shipped gear was spokes on a ring and it read as a sun**, and
#: the fix then was a filled disc with trapezoidal teeth and a punched hub. Stroked,
#: the same lesson holds with one change: the rim and the teeth are drawn as *one*
#: closed outline whose valleys sit at the root radius, so the teeth are edges of a
#: body rather than eight marks arranged around a circle. The hub is a stroked circle
#: inside it — a hole, not a disc of background colour.
GEAR_TEETH = 8
GEAR_HUB, GEAR_ROOT, GEAR_TIP = 2.2, 4.9, 7.0
GEAR_TIP_HALF, GEAR_ROOT_HALF = math.radians(7), math.radians(12)

#: Below this, a straight run between two corner arcs is not a run at all: the two
#: arcs meet, and the rounded rectangle is a capsule on that axis. Drawing the
#: zero-length line anyway would put a round cap's worth of ink where the shape has
#: no edge.
_EPS = 1e-6


class _Box:
    """Unit coordinates in, pixel coordinates out.

    Every glyph body below is written in the units of its own viewBox and mapped
    through one of these, so a glyph is one drawing at every size it is asked for
    rather than a set of hand-tuned pixel constants per caller.
    """

    __slots__ = ("x", "y", "s")

    def __init__(self, x: float, y: float, size: float, unit: float = UNIT) -> None:
        self.x, self.y, self.s = x, y, size / unit

    def __call__(self, *coords: float) -> list:
        """A flat run of unit coordinates, as a flat run of pixel coordinates."""
        out = []
        for i in range(0, len(coords), 2):
            out.append(self.x + coords[i] * self.s)
            out.append(self.y + coords[i + 1] * self.s)
        return out


def _line(c, b: _Box, coords, colour: str, width: float, tags) -> None:
    """One stroked polyline, round-capped and round-jointed where the target takes it.

    `tk.Canvas` takes both; `GdiCanvas.create_line` ignores them today and strokes
    with GDI+'s defaults, which at this weight is a difference nobody can see. It is
    passed anyway, because the day the painter grows a pen cap the call sites should
    not all have to be visited.
    """
    c.create_line(*b(*coords), fill=colour, width=width,
                  capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=tags)


def _arc(c, b: _Box, box, start: float, extent: float, colour: str, width: float,
         tags) -> None:
    """One stroked arc. Tk's angles: degrees anticlockwise from three o'clock, on a
    canvas whose y grows downward — so 0 to 180 is the top half of the box, and
    `GdiCanvas.create_arc` converts for GDI+ at its own end."""
    c.create_arc(*b(*box), start=start, extent=extent, style=tk.ARC,
                 outline=colour, width=width, tags=tags)


def _rrect(c, b: _Box, x1: float, y1: float, x2: float, y2: float, r: float,
           colour: str, width: float, tags) -> None:
    """A rounded rectangle as four corner arcs and up to four straight runs.

    Not a smoothed polygon, for the reason in the module docstring. Where a side is
    exactly twice the radius its two corners are one semicircle and the run between
    them is nothing, so the pair is drawn as a single arc — which is what makes the
    mic's body two arcs and two lines rather than four arcs and two lines with two
    stray caps. That case is not an optimisation: it is the difference between a
    capsule and a rounded rectangle that happens to have met in the middle.
    """
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    d = 2 * r
    wide, tall = (x2 - x1) - d > _EPS, (y2 - y1) - d > _EPS
    if not wide:  # a vertical capsule: one cap over the top, one under the bottom
        _arc(c, b, (x1, y1, x2, y1 + d), 0, 180, colour, width, tags)
        _arc(c, b, (x1, y2 - d, x2, y2), 180, 180, colour, width, tags)
    elif not tall:  # a horizontal capsule: one cap at each end
        _arc(c, b, (x1, y1, x1 + d, y2), 90, 180, colour, width, tags)
        _arc(c, b, (x2 - d, y1, x2, y2), 270, 180, colour, width, tags)
    else:
        for bx, by, start in ((x1, y1, 90), (x2 - d, y1, 0),
                              (x2 - d, y2 - d, 270), (x1, y2 - d, 180)):
            _arc(c, b, (bx, by, bx + d, by + d), start, 90, colour, width, tags)
    if wide:
        _line(c, b, (x1 + r, y1, x2 - r, y1), colour, width, tags)
        _line(c, b, (x1 + r, y2, x2 - r, y2), colour, width, tags)
    if tall:
        _line(c, b, (x1, y1 + r, x1, y2 - r), colour, width, tags)
        _line(c, b, (x2, y1 + r, x2, y2 - r), colour, width, tags)


def _dot(c, b: _Box, x: float, y: float, colour: str, width: float, tags) -> None:
    """The one filled thing in this module: a dot the size of the stroke.

    An eye and an antenna tip are dots in every stroke icon set there is, and a
    circle drawn at the stroke's own diameter is indistinguishable from a line
    that stopped — which is the test that keeps this from becoming a licence to
    fill things. The diameter is in *pixels*, not units, so it tracks the stroke
    rather than the size.
    """
    px, py = b(x, y)
    r = width / 2
    c.create_oval(px - r, py - r, px + r, py + r, fill=colour, outline="",
                  tags=tags)


# ---------------------------------------------------------------- the set


def mic(c, x: float, y: float, colour: str, *, size: float = MIC_UNIT_W,
        width: float = STROKE, slash: bool = False, tags=()) -> None:
    """gen.py's `mic()`, exactly: a capsule, an arc cradle, a stem, and the slash.

    The box is `size` wide and `size * MIC_ASPECT` tall — 14 x 18 at the default,
    which is the frame the compact pill already reserves (`ui_compact.MIC_X`,
    `MIC_Y`) and the width the shipped mic view already measures its row against
    (`ui.MIC_GLYPH_R` x 2).

    `slash` is the dead-microphone variant (States.dc.html): one diagonal across the
    whole glyph, in whatever red the caller is already using for the ring. A slash
    rather than a missing icon, for the same reason the speaker's mute is a slash —
    "off" has to be legible without remembering what "on" looked like.
    """
    b = _Box(x, y, size, MIC_UNIT_W)
    _rrect(c, b, 4.3, 1.2, 9.7, 10.8, 2.7, colour, width, tags)
    _arc(c, b, (1.8, 3.2, 12.2, 13.6), 180, 180, colour, width, tags)
    _line(c, b, (7, 13.6, 7, 16.4), colour, width, tags)
    if slash:
        _line(c, b, (1.6, 1.8, 12.4, 16.4), colour, width, tags)


def folder(c, x: float, y: float, colour: str, *, size: float = UNIT,
           width: float = STROKE, tags=()) -> None:
    """gen.py's `FOLDER`: a body and a tab.

    The tab is a polyline over the body's top-left corner rather than a second
    rounded rectangle — the two overlap in the same colour, so the join reads as one
    outline, and a 1.4-unit corner radius on the tab itself is under a pixel at every
    size this is drawn at.
    """
    b = _Box(x, y, size)
    _rrect(c, b, 1.8, 4.5, 13.2, 13.6, 1.4, colour, width, tags)
    _line(c, b, (1.8, 5.9, 1.8, 4.2, 3.2, 2.8, 6.2, 2.8, 7.6, 4.5),
          colour, width, tags)


def copy(c, x: float, y: float, colour: str, *, size: float = UNIT,
         width: float = STROKE, tags=()) -> None:
    """gen.py's `COPY_ICON`: two sheets, the near one offset — the mark every OS uses.

    The back sheet is an open path that stops where the front one covers it, which is
    what tells the two apart without a fill. The shipped mark filled the front sheet
    with `SHELL` to punch the back one out; this needs no background to be right.
    """
    b = _Box(x, y, size)
    _rrect(c, b, 5.5, 5.5, 13.7, 13.7, 1.8, colour, width, tags)
    _line(c, b, (10.5, 5.5, 10.5, 4.0, 8.9, 2.4, 3.9, 2.4, 2.3, 4.0,
                 2.3, 9.0, 3.9, 10.6, 5.5, 10.6), colour, width, tags)


def close(c, x: float, y: float, colour: str, *, size: float = UNIT,
          width: float = STROKE, tags=()) -> None:
    """gen.py's close cross, from `strip()`: two crossed lines and nothing else."""
    b = _Box(x, y, size)
    _line(c, b, (4, 4, 12, 12), colour, width, tags)
    _line(c, b, (12, 4, 4, 12), colour, width, tags)


def cancel(c, x: float, y: float, colour: str, *, size: float = UNIT,
           width: float = STROKE, tags=()) -> None:
    """Cancel is the close cross. One drawing, because it is one idea: stop this.

    Kept as a name of its own because `ui.COMMAND_GLYPHS` maps a command to a
    function and a table that reads `"Cancel": glyphs.close` says something slightly
    untrue about what the mark means.
    """
    close(c, x, y, colour, size=size, width=width, tags=tags)


def search(c, x: float, y: float, colour: str, *, size: float = UNIT,
           width: float = STROKE, tags=()) -> None:
    """gen.py's `search_icon`: a lens and its handle."""
    b = _Box(x, y, size)
    c.create_oval(*b(2.6, 2.6, 11.8, 11.8), fill="", outline=colour, width=width,
                  tags=tags)
    _line(c, b, (10.6, 10.6, 13.6, 13.6), colour, width, tags)


def gear(c, x: float, y: float, colour: str, *, size: float = UNIT,
         width: float = STROKE, tags=()) -> None:
    """A settings gear: a toothed rim and a hole through the middle.

    **The first version of this was spokes on a ring and it read as a sun.** Eight
    lines poking out of a circle is what an asterisk looks like. What makes a gear a
    gear is that the teeth are part of the body — so the rim and the teeth are one
    closed outline here, stepping between `GEAR_ROOT` and `GEAR_TIP` eight times, and
    the valleys between teeth are the body's own edge. The chords across those valleys
    are straight because at this radius a 23-degree arc departs from its chord by a
    tenth of a unit, which is a tenth of a pixel.

    The hub was a `SHELL`-filled disc when the body was filled: a hole punched by
    painting the background over the middle, which is exact only while the row's fill
    is the one behind it. Stroked, it is a circle, and the glyph composites anywhere.
    """
    b = _Box(x, y, size)
    pts = []
    for i in range(GEAR_TEETH):
        a = 2 * math.pi * i / GEAR_TEETH
        for radius, half in ((GEAR_ROOT, -GEAR_ROOT_HALF), (GEAR_TIP, -GEAR_TIP_HALF),
                             (GEAR_TIP, GEAR_TIP_HALF), (GEAR_ROOT, GEAR_ROOT_HALF)):
            pts += [UNIT / 2 + math.cos(a + half) * radius,
                    UNIT / 2 + math.sin(a + half) * radius]
    _line(c, b, pts + pts[:2], colour, width, tags)
    c.create_oval(*b(UNIT / 2 - GEAR_HUB, UNIT / 2 - GEAR_HUB,
                     UNIT / 2 + GEAR_HUB, UNIT / 2 + GEAR_HUB),
                  fill="", outline=colour, width=width, tags=tags)


def speaker(c, x: float, y: float, colour: str, *, muted: bool = False,
            size: float = UNIT, width: float = STROKE, tags=()) -> None:
    """A speaker, with a slash through where the sound would be when replies are muted.

    The body is one closed outline — the box and the cone are a single path, which is
    what they are in every stroke icon set and what the filled version could only fake
    with two shapes that had to agree about a seam.

    The slash rather than a different colour or a missing icon: "off" has to be
    legible without remembering what "on" looked like, and an icon that disappears
    when a setting is off is a setting nobody can find their way back to.
    """
    b = _Box(x, y, size)
    _line(c, b, (2.2, 6.2, 5.2, 6.2, 8.6, 2.8, 8.6, 13.2, 5.2, 9.8, 2.2, 9.8,
                 2.2, 6.2), colour, width, tags)
    if muted:
        _line(c, b, (9.2, 3.6, 14.6, 12.4), colour, width, tags)
        return
    _arc(c, b, (5.8, 5.2, 11.4, 10.8), -55, 110, colour, width, tags)
    _arc(c, b, (3.8, 3.2, 13.4, 12.8), -48, 96, colour, width, tags)


def mode(c, x: float, y: float, colour: str, name: str, *, size: float = UNIT,
         width: float = STROKE, tags=()) -> None:
    """Lines of text for dictate, a pen for refine, a speech bubble for converse.

    The modes differ in *where the words go* — into the window you were in, to an
    agent that shapes them and hands them back, or to an agent that answers — so the
    marks are "text", "a pen" and "a reply", not abstractions somebody has to learn.

    `name` and not a converse bool. The two-way read (`!= DICTATE`) drew the speech
    bubble over a mode that pastes, which is exactly the lie a third mode was not
    supposed to introduce silently, so a fourth name raises here rather than falling
    through to whichever branch is last.
    """
    b = _Box(x, y, size)
    if name == "converse":
        _rrect(c, b, 2, 3, 14, 11.5, 3.5, colour, width, tags)
        _line(c, b, (5.5, 11.5, 4, 14.5), colour, width, tags)
    elif name == "refine":
        # A pen over the line it rewrites: the shaft, the band across its top,
        # and the draft underneath.
        #
        # **The nib used to be a second line off the shaft's lower end, and it
        # was collinear with it** — two lines that drew one diagonal, which is
        # what a pen with no pen looks like. The band is a stroke *across* the
        # shaft rather than along it, so it cannot disappear into it, and it is
        # the mark that says which end writes.
        #
        # The line under it is not decoration either. Refine's Edit command
        # draws `edit`'s outlined pencil, `ui.ICON_MODE` and
        # `ui.COMMAND_COLOURS["Edit"]` are the same pink, and both can be on
        # the pill row at once — a mode that draws the same mark as an action
        # beside it is a row that reads as a mistake. The draft under the pen
        # is also the truer picture: this mode rewrites what is already there.
        _line(c, b, (4.0, 10.5, 11.8, 2.7), colour, width, tags)
        _line(c, b, (9.0, 1.9, 12.6, 5.5), colour, width, tags)
        _line(c, b, (2.5, 13.6, 13.5, 13.6), colour, width, tags)
    elif name == "dictate":
        for i, right in enumerate((14, 14, 9.2)):
            _line(c, b, (2, 4 + i * 4, right, 4 + i * 4), colour, width, tags)
    else:
        raise ValueError(f"no glyph for mode {name!r}; known: {MODES}")


def refine(c, x: float, y: float, colour: str, *, size: float = UNIT,
           width: float = STROKE, tags=()) -> None:
    """A wand with a spark at its tip: this rewrites what you said.

    The first attempt was a stroke and two dots, and at sixteen pixels that reads as a
    slash with specks on it. A four-point spark — two crossed strokes, the vertical
    longer — is what carries "magic" at this size, so the wand got shorter to make
    room for it.
    """
    b = _Box(x, y, size)
    _line(c, b, (2.5, 13.5, 9, 7), colour, width, tags)
    _line(c, b, (11.5, 1.5, 11.5, 8.5), colour, width, tags)
    _line(c, b, (8, 5, 15, 5), colour, width, tags)


def continue_(c, x: float, y: float, colour: str, *, size: float = UNIT,
              width: float = STROKE, tags=()) -> None:
    """A plus: keep going, and add to what is there."""
    b = _Box(x, y, size)
    _line(c, b, (8, 3, 8, 13), colour, width, tags)
    _line(c, b, (3, 8, 13, 8), colour, width, tags)


def edit(c, x: float, y: float, colour: str, *, size: float = UNIT,
         width: float = STROKE, tags=()) -> None:
    """A pencil, nib down-left — an outline now, not a thick stroke with a filled nib.

    The filled version put a 2 px triangle on the end of a 3 px line and the two
    merged; the fix then was to make the nib wider than the body. Stroked, the body is
    a four-sided outline 4.2 units across, which leaves 2.7 units of air between its
    two long edges at 16 px — enough that it reads as a pencil rather than as a
    diagonal drawn twice — and the nib is where those edges meet the point.
    """
    b = _Box(x, y, size)
    _line(c, b, (2.4, 13.6, 3.04, 10.0, 10.11, 2.93, 13.07, 5.89, 6.0, 12.96,
                 2.4, 13.6), colour, width, tags)
    _line(c, b, (4.46, 8.58, 7.42, 11.54), colour, width, tags)


def command(c, x: float, y: float, colour: str, *, size: float = UNIT,
            width: float = STROKE, tags=()) -> None:
    """The command loop — the owner's suggestion, and the right one.

    "for command universally we can use ⌘". It is the mark everybody already reads as
    *this was an instruction, not text*, which is exactly what the chip meant.

    Four open loops on the corners of a square, which is the knot itself: each arc
    starts and ends *on* the square's edges, so the two read as one continuous line.

    **This is the mark that set the stroke weight for everything else here.** At 2 px
    on a 6 px loop the hole is 2 px across and the glyph renders as a smudge — it did,
    twice, once as arcs and once as closed rings. `STROKE` on a 6.8 px loop leaves
    4 px of air, which is what makes it read as ⌘ rather than as four blobs.

    Each loop's 90-degree gap faces the square, so the top-left starts at 0 and sweeps
    270 (east round to south), leaving the south-east quadrant open for the corner it
    joins.
    """
    b = _Box(x, y, size)
    r = 3.4
    for cx, cy, start in ((5, 5, 0), (11, 5, 270), (5, 11, 90), (11, 11, 180)):
        _arc(c, b, (cx - r, cy - r, cx + r, cy + r), start, 270, colour, width, tags)
    c.create_rectangle(*b(5, 5, 11, 11), fill="", outline=colour, width=width,
                       tags=tags)


def into_baseline(c, x: float, y: float, colour: str, *, size: float = UNIT,
                  width: float = STROKE, tags=()) -> None:
    """An arrow down into a line: this lands somewhere.

    gen.py draws it on the Workbench setup page for "On release — paste into last
    window"; the shipped panel drew the same arrow for "Use this", the mark that puts
    an answer into the draft. Two names for one sentence, so one drawing — see
    `take`.
    """
    b = _Box(x, y, size)
    _line(c, b, (8, 2.6, 8, 10.6), colour, width, tags)
    _line(c, b, (4.6, 7.2, 8, 10.6, 11.4, 7.2), colour, width, tags)
    _line(c, b, (2.6, 13.4, 13.4, 13.4), colour, width, tags)


def take(c, x: float, y: float, colour: str, *, size: float = UNIT,
         width: float = STROKE, tags=()) -> None:
    """Put this answer into the draft — `into_baseline` under the name the mark has."""
    into_baseline(c, x, y, colour, size=size, width=width, tags=tags)


def new(c, x: float, y: float, colour: str, *, size: float = UNIT,
        width: float = STROKE, tags=()) -> None:
    """A speech bubble with a plus: start the conversation again."""
    b = _Box(x, y, size)
    _rrect(c, b, 2, 3, 14, 11, 3, colour, width, tags)
    _line(c, b, (5, 11, 4, 14), colour, width, tags)
    _line(c, b, (8, 5, 8, 9), colour, width, tags)
    _line(c, b, (6, 7, 10, 7), colour, width, tags)


def send(c, x: float, y: float, colour: str, *, size: float = UNIT,
         width: float = STROKE, tags=()) -> None:
    """Two chevrons: the words go *out*, into the window Flow is aimed at."""
    b = _Box(x, y, size)
    for dx in (1.5, 7.5):
        _line(c, b, (dx, 3, dx + 5, 8, dx, 13), colour, width, tags)


def agent(c, x: float, y: float, colour: str, *, size: float = UNIT,
          width: float = STROKE, tags=()) -> None:
    """A small agent — a head with two eyes and an antenna: the question goes to one.

    The eyes and the antenna tip are the module's only fills, and each is a dot the
    stroke's own diameter (`_dot`). Drawn as outlined circles they would be rings at
    this size, and a face with two rings for eyes is a face that is surprised.
    """
    b = _Box(x, y, size)
    _rrect(c, b, 2.5, 5.5, 13.5, 14, 3, colour, width, tags)
    _line(c, b, (8, 5.5, 8, 2.5), colour, width, tags)
    _dot(c, b, 8, 2.5, colour, width, tags)
    for ex in (5.5, 10.5):
        _dot(c, b, ex, 9.5, colour, width, tags)


def terminal(c, x: float, y: float, colour: str, *, size: float = UNIT,
             width: float = STROKE, tags=()) -> None:
    """gen.py's Agent CLI icon: a prompt chevron and its line, in a box."""
    b = _Box(x, y, size)
    _rrect(c, b, 1.6, 2.6, 14.4, 13.4, 2, colour, width, tags)
    _line(c, b, (4, 5.6, 6.8, 8, 4, 10.4), colour, width, tags)
    _line(c, b, (8.6, 10.8, 12, 10.8), colour, width, tags)
