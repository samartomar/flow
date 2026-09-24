"""Record the compact pill in motion, against a drawn terminal.

This was the README's GIF until `home_reel.py`, which records Flow Home with the pill over
it, took the place and borrows `Tap` and `STEP_MS` from here.

`compact_shots.py` photographs each state the compact pill can draw. This records the
motion between them, which no still can show: the ring and the meter answering a
voice, the words landing where you were typing, a spoken fix changing them there, and
the band rising for a Refine and an Ask. The real `CompactPill` runs against
`shots.FakeSession` — no microphone, no model, no CLI, nothing pasted.

**Nothing on the screen is read, and the pointer is never moved.** Every frame is the
bitmap the pill hands Windows: `GdiCanvas.present` is wrapped to keep a copy of the
premultiplied pixels it presents, so the reel is exactly what the layered window shows,
antialiasing and per-pixel alpha included, whatever else is on the desktop. `reel.py`,
which records the Classic pill, reads the screen instead, and that is why it covers the
desktop with a backdrop and parks the cursor. The pill does appear at the bottom of the
monitor under the pointer while this runs, for about twenty seconds.

The window the words land in is drawn here rather than opened: Type pastes into another
program, and the reel has to show one. Its text follows the timeline, not a real paste.

    uv run --with pillow python scripts/compact_reel.py            # -> docs/pill.gif
    uv run --with pillow python scripts/compact_reel.py --frames out/  # and every frame
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from flow import paint  # noqa: E402

# Before any window, for compact_shots.py's reason: awareness is fixed for the process
# the moment the first window exists, and frames drawn unaware are a third-size image
# the compositor stretched.
paint.make_dpi_aware()

import shots  # noqa: E402  — the fake session
from flow.session import CONVERSE, DICTATE, REFINE, State  # noqa: E402
from flow.ui_compact import CompactPill  # noqa: E402

FONTS = REPO / "flow" / "assets" / "fonts"

#: `shots.py`'s backdrop: the desk everything sits on.
DESK = (35, 38, 43)
#: The terminal the words land in. Darker than the desk, lighter than the pill's shell,
#: so the three read as three things.
WINDOW, EDGE, TITLE = (22, 24, 29), (46, 50, 58), (28, 31, 37)
TEXT, DIM, MUTED = (230, 232, 237), (150, 156, 166), (112, 118, 128)
#: Behind the word a spoken fix just changed, for as long as the pill's note says so.
MARK = (58, 64, 78)

#: Output frames are at most this often. The pill presents on every 30 ms tick while
#: the meter moves; a GIF does not need 33 fps to show a meter, and 25 halves the file.
STEP_MS = 40
#: One palette for the whole reel (see `write_gif`). The ring's four colours, the pill's
#: greys and the antialiasing between them fit in this with room to spare.
COLOURS = 160
#: Let the pill paint before the timeline starts, so the reel does not open on nothing.
WARMUP_MS = 800

#: The story, in the words it is told in. Type pastes the first line, a spoken fix
#: changes one word of it, Refine turns a rough instruction into the prompt Send pastes,
#: and Ask answers a question in the band. The answer is true of this repository.
TYPED = "add a retry to the upload step and log each failure"
FIXED = TYPED.replace("upload", "download")
SAID_REFINE = "and make it back off exponentially maybe three tries"
REFINED = ("Retry the download step up to three times with exponential backoff "
           "(1 s, 2 s, 4 s), and log each failed attempt with its error.")
QUESTION = "Where does the pill decide it was a hold and not a tap?"
ANSWER = ("PILL_HOLD_SEC in flow/ui.py: 0.30 s, with a 4 px drag slop beside it so a "
          "nudge while holding is not read as a move.")


@dataclass
class Frame:
    """One bitmap the pill presented, and where on the screen it went."""
    t: float
    x: int
    y: int
    w: int
    h: int
    px: bytes  # premultiplied BGRA, top-down, device pixels
    #: The whole window's opacity, which `present` hands Windows separately as
    #: `SourceConstantAlpha` — `PILL_ALPHA` makes it 240 of 255 for the compact pill.
    ca: int = 255


class Tap:
    """Keeps a copy of every frame the pill hands Windows.

    `CompactPill._present` calls `present` only when the picture changed, so this is a
    list of changes, each stamped with when it happened. The position is the pill's own
    `_shell_xy`, the anchor it placed the window from, rather than `winfo_*`, which lags
    a `geometry` call by a frame or two and would make the band jump in the reel.
    """

    def __init__(self, pill) -> None:
        self.pill = pill
        self.frames: list[Frame] = []
        real = paint.GdiCanvas.present
        tap = self

        def present(canvas, win, at=None):
            ok = real(canvas, win, at)
            if win is tap.pill:
                w, h = canvas.device_size
                x, y = tap.pill._shell_xy
                tap.frames.append(Frame(time.perf_counter(), x, y, w, h,
                                        canvas._buf.raw[: w * h * 4],
                                        canvas.constant_alpha))
            return ok

        paint.GdiCanvas.present = present


@dataclass
class Scene:
    """The terminal the words land in: what it holds, and when that changed."""
    history: tuple = ()
    line: str = ""
    mark: str = ""
    changes: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.note()

    def set(self, **kw) -> None:
        for name, value in kw.items():
            setattr(self, name, value)
        self.note()

    def note(self) -> None:
        self.changes.append((time.perf_counter(), (self.history, self.line, self.mark)))


def timeline(pill, sess, scene):
    """The recording, as (hold_ms, action) pairs. `None` holds without acting."""

    def hold(mode=DICTATE):
        def fn():
            sess.mode, sess.state, sess.hearing = mode, State.LISTENING, True
            pill.armed = True
            if mode != DICTATE:
                # A hold in a panel mode raises the band at once, heard block first.
                pill._panel_mode = mode
                pill._panel_heard, pill._panel_heard_final = "", False
                pill._panel_result, pill._panel_failed = "", False
                pill._open_panel()
        return fn

    def rest():
        sess.state = State.IDLE
        pill.armed = False

    def heard(text: str, final: bool = False):
        def fn():
            pill._panel_heard, pill._panel_heard_final = text, final
            pill._open_panel()
        return fn

    def partials(text: str, stops) -> list:
        # Uneven on purpose, as `reel.py` has it: a decoder does not emit on a
        # metronome, and a reel that does looks like a mock.
        words = text.split()
        return [(210, heard(" ".join(words[:n]))) for n in stops]

    def waiting(final_heard: str, state):
        def fn():
            pill._panel_heard, pill._panel_heard_final = final_heard, True
            sess.state = state
            pill.armed = True
            pill._open_panel()
        return fn

    def answered(result: str):
        def fn():
            pill._panel_result = result
            rest()
            pill._open_panel()
        return fn

    def refine_sent():
        pill._close_panel()
        scene.set(line=REFINED)

    return [
        # -- at rest, in Type ------------------------------------------------------
        (0, rest),
        (900, None),
        # -- hold: it hears you ----------------------------------------------------
        (0, hold()),
        (1500, None),
        # -- let go: the words paste where you were typing ------------------------
        (0, lambda: (rest(), scene.set(line=TYPED))),
        (1400, None),
        # -- hold again: "change upload to download" ------------------------------
        (0, hold()),
        (1100, None),
        (0, lambda: (rest(), scene.set(line=FIXED, mark="download"),
                     pill._say("changed “upload” to “download”", 72))),
        (2300, None),
        # -- Enter: the line goes up, the prompt is empty again -------------------
        (0, lambda: scene.set(history=(FIXED,), line="", mark="")),
        (600, None),
        # -- tap: Refine -----------------------------------------------------------
        (0, lambda: setattr(sess, "mode", REFINE)),
        (1000, None),
        (0, hold(REFINE)),
        (250, None),
        *partials(SAID_REFINE, (2, 4, 6, 8, 9)),
        (250, None),
        (0, waiting(SAID_REFINE, State.REFINING)),
        (1300, None),
        (0, answered(REFINED)),
        (2600, None),
        # -- Send: the shaped prompt pastes ---------------------------------------
        (0, refine_sent),
        (1500, None),
        # -- tap: Ask --------------------------------------------------------------
        (0, lambda: setattr(sess, "mode", CONVERSE)),
        (1000, None),
        (0, hold(CONVERSE)),
        (250, None),
        *partials(QUESTION.lower().rstrip("?"), (2, 5, 8, 11)),
        (250, None),
        (0, waiting(QUESTION, State.ASKING)),
        (1400, None),
        (0, answered(ANSWER)),
        (3400, None),
    ]


# -- the terminal ------------------------------------------------------------------


def _font(name: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), px)


def _wrap(text: str, font, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and font.getlength(trial) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur] if cur or not lines else lines


def draw_terminal(size, rect, snap, k: float) -> Image.Image:
    """The window the words land in, at device resolution."""
    history, line, mark = snap
    img = Image.new("RGB", size, DESK)
    d = ImageDraw.Draw(img)
    s = lambda v: round(v * k)  # noqa: E731
    left, top, right, bottom = rect
    d.rounded_rectangle(rect, radius=s(10), fill=WINDOW, outline=EDGE, width=max(1, s(1)))
    bar = top + s(30)
    d.rounded_rectangle((left + s(1), top + s(1), right - s(1), bar), radius=s(9), fill=TITLE)
    d.rectangle((left + s(1), bar - s(10), right - s(1), bar), fill=TITLE)
    d.line((left + s(1), bar, right - s(1), bar), fill=EDGE, width=max(1, s(1)))
    title = _font("IBMPlexSans-Medium.ttf", s(12))
    d.text((left + s(14), top + s(15)), "acme — terminal", font=title, fill=MUTED, anchor="lm")

    mono = _font("IBMPlexMono-Regular.ttf", s(14))
    lh = s(22)
    x0, y = left + s(16), bar + s(14)
    width = right - s(16) - (x0 + s(18))
    for past in history:
        for i, part in enumerate(_wrap(past, mono, width)):
            d.text((x0, y), "›" if i == 0 else " ", font=mono, fill=MUTED)
            d.text((x0 + s(18), y), part, font=mono, fill=DIM)
            y += lh
    if history:
        y += s(8)
    parts = _wrap(line, mono, width) if line else [""]
    for i, part in enumerate(parts):
        d.text((x0, y), "›" if i == 0 else " ", font=mono, fill=TEXT)
        tx = x0 + s(18)
        if mark and mark in part:
            before = part[: part.index(mark)]
            mx = tx + mono.getlength(before)
            d.rounded_rectangle((mx - s(3), y - s(1), mx + mono.getlength(mark) + s(3),
                                 y + s(19)), radius=s(4), fill=MARK)
        d.text((tx, y), part, font=mono, fill=TEXT)
        if i == len(parts) - 1:
            cx = tx + mono.getlength(part) + s(2)
            d.rectangle((cx, y + s(2), cx + max(2, s(2)), y + s(18)), fill=TEXT)
        y += lh
    return img


# -- composing ---------------------------------------------------------------------


def overlay(bg: np.ndarray, f: Frame, ox: int, oy: int) -> np.ndarray:
    """`bg` with the pill's premultiplied BGRA frame over it, where it really was, blended
    the way `UpdateLayeredWindow` blends it: the constant alpha scales the colour and the
    per-pixel alpha alike before the source goes over what is under it."""
    src = np.frombuffer(f.px, np.uint8).reshape(f.h, f.w, 4)
    rgb = (src[..., 2::-1].astype(np.uint16) * f.ca + 127) // 255
    a = (src[..., 3:4].astype(np.uint16) * f.ca + 127) // 255
    out = bg.copy()
    y0, x0 = f.y - oy, f.x - ox
    under = out[y0:y0 + f.h, x0:x0 + f.w].astype(np.uint16)
    out[y0:y0 + f.h, x0:x0 + f.w] = np.minimum(
        255, rgb + (under * (255 - a) + 127) // 255).astype(np.uint8)
    return out


def compose(frames: list[Frame], scene: Scene, k: float, scale: float,
            begin: float, end: float):
    """The reel: pill frames over the terminal, on a 40 ms grid, identical ones merged.

    It opens on whatever the pill last presented before the timeline began, which is
    the pill at rest: a pill presents only when its picture changes, so the resting
    frame is the one from the warm-up, not one stamped inside the reel.
    """
    first = max((i for i, f in enumerate(frames) if f.t <= begin), default=0)
    frames = frames[first:]
    rest = frames[0]
    left = min(f.x for f in frames)
    top = min(f.y for f in frames)
    right = max(f.x + f.w for f in frames)
    bottom = max(f.y + f.h for f in frames)
    m = round(24 * k)
    width = max(right - left + 2 * m, round(600 * k))
    cx = (left + right) // 2
    ox = cx - width // 2
    # Tall enough for the terminal to hold its lines above the capsule even when no
    # band ever rose that high.
    oy = min(top - m, rest.y - round(18 * k) - round(170 * k) - m)
    height = bottom + m - oy
    rect = (ox + m, oy + m, ox + width - m, rest.y - round(18 * k))
    rect = tuple(v - o for v, o in zip(rect, (ox, oy, ox, oy)))
    out_size = (round(width * scale / k), round(height * scale / k))

    backs: dict = {}
    images, durations, key = [], [], None
    fi = si = 0
    t = begin
    while t <= end:
        while fi + 1 < len(frames) and frames[fi + 1].t <= t:
            fi += 1
        while si + 1 < len(scene.changes) and scene.changes[si + 1][0] <= t:
            si += 1
        now = (fi, si)
        if now == key:
            durations[-1] += STEP_MS
        else:
            snap = scene.changes[si][1]
            if snap not in backs:
                backs[snap] = np.asarray(draw_terminal((width, height), rect, snap, k))
            img = Image.fromarray(overlay(backs[snap], frames[fi], ox, oy))
            images.append(img.resize(out_size, Image.LANCZOS))
            durations.append(STEP_MS)
            key = now
        t += STEP_MS / 1000
    return images, durations


def write_gif(frames, durations, path: Path) -> None:
    """One palette for the whole reel, from a sample of it, as `reel.py` explains:
    per-frame palettes make flat surfaces shimmer."""
    step = max(1, len(frames) // 32)
    sample = frames[::step]
    strip = Image.new("RGB", (sample[0].width, sample[0].height * len(sample)))
    for i, f in enumerate(sample):
        strip.paste(f, (0, i * f.height))
    pal = strip.quantize(colors=COLOURS, method=Image.Quantize.MEDIANCUT)
    flat = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    flat[0].save(path, save_all=True, append_images=flat[1:], duration=durations,
                 loop=0, optimize=True, disposal=1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "pill.gif")
    # 1.25, because the band's labels are 11 px in the design and a README shows the
    # GIF at its own size: at 1.0 the note under the pill is a grey smudge.
    ap.add_argument("--scale", type=float, default=1.25,
                    help="output pixels per design pixel")
    ap.add_argument("--frames", type=Path, default=None,
                    help="also write every output frame as a PNG here, to look at")
    args = ap.parse_args()

    sess = shots.FakeSession()
    # The fake's workspace is this checkout, which the band prints in full: somebody's
    # own path in a public GIF, and not the project the terminal is in.
    sess.workspace = r"D:\dev\acme"
    pill = CompactPill(sess)
    # The take must not depend on what the person at the desk does with their mouse:
    # a click anywhere else closes an open band, which is right for Flow and wrong for
    # a recording. These are the pill's two reads of the real mouse.
    pill._outside_click_now = lambda: False
    pill._clicked_off_pill = lambda: False
    tap = Tap(pill)
    scene = Scene()
    steps = timeline(pill, sess, scene)
    print(f"recording {len(steps)} beats -> {args.out}", flush=True)
    began, ended, scale_k = [], [], []

    def run(i=0):
        if i == 0:
            began.append(time.perf_counter())
            scale_k.append(pill.dev(1000) / 1000)
        if i >= len(steps):
            ended.append(time.perf_counter())
            pill.after(200, pill.quit_app)
            return
        hold_ms, fn = steps[i]

        def go():
            if fn is not None:
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
            run(i + 1)

        pill.after(hold_ms, go)

    pill.after(60_000, pill.quit_app)  # hard stop, whatever happens
    pill.after(WARMUP_MS, run)
    pill.mainloop()

    if not tap.frames or not ended:
        print(f"no reel: {len(tap.frames)} frames, finished={bool(ended)}", file=sys.stderr)
        raise SystemExit(1)
    k = scale_k[0]
    images, durations = compose(tap.frames, scene, k, args.scale, began[0], ended[0])
    if args.frames:
        args.frames.mkdir(parents=True, exist_ok=True)
        for i, img in enumerate(images):
            img.save(args.frames / f"{i:04d}.png")
    write_gif(images, durations, args.out)
    kb = args.out.stat().st_size / 1024
    print(f"{len(tap.frames)} frames presented at {k:g}x; {len(images)} in the reel, "
          f"{sum(durations) / 1000:.1f} s, {images[0].width}x{images[0].height}, "
          f"{kb:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
