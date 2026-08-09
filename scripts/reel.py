"""Record Flow using itself, as one animated GIF for the README.

`shots.py` next door photographs every surface — one still per state, which is
what a UI review needs. This records the *motion between* those states, which is
what a stranger needs: the meter answering a voice, the partial arriving word by
word and being replaced by a clean sentence, three dots marching while a refine
runs, a countdown ticking on the chip that takes a Send back, and the glyph
travelling green to violet on a mode switch. None of that is visible in a still,
and all of it is the part that explains what Flow is.

    uv run --with pillow python scripts/reel.py
    uv run --with pillow python scripts/reel.py --out docs/flow.gif --scale 1.0

Everything about the stand-in session is `shots.py`'s, imported rather than
copied: the same fake `Session`, the same level envelope, the same backdrop, the
same refusal to open a microphone, load a model, call a CLI or paste anything.
This file owns only the timeline and the encoder.

Two things worth knowing before changing the timeline:

  **Frames are timed, not counted.** A grab blocks the Tk loop while it runs, so
  the capture rate is whatever the machine managed — about 16 fps here. Each
  frame therefore carries the wall time it actually covered, and the GIF plays
  back at the speed the recording really happened rather than at a nominal one
  it did not.

  **The canvas is the union of every frame's window stack, in screen
  coordinates.** Flow's windows do not move during the walk — the pill is pinned
  and the panels grow upward out of it — so compositing by absolute position
  keeps the pill still while the panel above it changes height. Anchoring on the
  crop instead would make the whole app jump every time the draft grew a line.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import threading
import time
import tkinter as tk
import traceback
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PIL import Image, ImageGrab  # noqa: E402

import flow.ui as ui  # noqa: E402
from flow.session import CONVERSE, Activity, State  # noqa: E402
from flow.ui import Pill  # noqa: E402

from shots import (ANSWER, DRAFT, QUESTION, FakeSession, _front,  # noqa: E402
                   _ratio, _visible, user32)

#: The backdrop `shots.py` paints, and therefore the colour every part of the
#: canvas no window covers has to be, or the composite shows a seam where a short
#: panel used to be a tall one.
BACKDROP = "#23262b"

#: How often to try for a frame. A floor, not a rate: the grab itself costs
#: something, which is why durations are measured instead of assumed.
CAPTURE_MS = 40

#: Let the app paint before recording it. Tk maps the windows and the pill's own
#: 30 ms tick draws the first frame some time after `mainloop` starts — record
#: from zero and the reel opens on an unpainted black rectangle, which is what
#: the first take did.
WARMUP_MS = 700

#: GIF is 256 colours at most, and Flow's surfaces are flat. 128 with no dither
#: holds the palette, the accents and the blends between them; dithering a flat
#: UI triples the file for noise nobody asked for.
COLOURS = 128

#: Transcribed the way a partial actually arrives — lower case, no punctuation,
#: no final stop. Streamed in over the draft it becomes, because the difference
#: between these two strings is the product.
PARTIAL = ("hey samar i wanted to check whether we are still good for the review "
           "on tuesday afternoon and whether you had a chance to look at the "
           "updated figures")

#: Where the partial pauses on its way in, in words. Uneven on purpose: a decoder
#: does not emit at a metronome, and a reel that does looks like a mock.
PAUSES = (2, 5, 8, 12, 15, 19, 23, 27)


def timeline(pill, sess):
    """The recording, as (hold_ms, action) pairs. `None` holds without acting.

    Ordered as the shortest honest answer to "what is this?": it hears you, it
    writes what you said, you talk to what it wrote, and then it either goes into
    another window or answers you back.
    """
    def state(st, activity=None, hearing=True, armed=True):
        def fn():
            sess.state, sess.activity, sess.hearing = st, activity, hearing
            pill.armed = armed
            # `shots.build` records what this line is for: without it
            # `_apply_idle_dim` keeps counting from the disarmed pill the walk
            # opens with and every later frame records at 55 % of its colour.
            pill._disarmed_since = None if armed else time.perf_counter()
        return fn

    words = PARTIAL.split()
    steps: list[tuple[int, object]] = [
        # -- it is off, and it is small ---------------------------------------
        (700, state(State.IDLE, armed=False)),
        (500, state(State.LISTENING)),
        # -- it hears you ------------------------------------------------------
        (900, None),
    ]
    # -- and writes down what you said, as you say it --------------------------
    for n in PAUSES:
        steps.append((230, lambda n=n: sess.push("partial", " ".join(words[:n]))))
    steps += [
        (700, lambda: sess.push("partial", PARTIAL)),
        # The clean sentence replacing the raw one is the single most explanatory
        # moment in the reel, so it gets its own beat either side.
        (0, lambda: (setattr(sess.draft, "text", DRAFT),
                     setattr(sess, "can_rescue", True),
                     setattr(pill.bubble, "_partial", ""),
                     sess.push("draft", DRAFT))),
        (0, state(State.DRAFT)),
        (1600, None),
        # -- you talk to what it wrote ----------------------------------------
        (0, state(State.REFINING, Activity("refining", True))),
        (1500, None),                       # the dots march in the meter's slot
        (0, lambda: sess.push("edit", "changed “thursday” to “Tuesday”")),
        (0, state(State.DRAFT)),
        (1600, None),                       # the note, and the Undo beside it
        # -- and it goes where you were typing --------------------------------
        (0, lambda: pill._send()),
        (2400, None),                       # "Bring it back", counting down
        (0, lambda: pill.bubble.hide()),
        # -- or it answers you -------------------------------------------------
        (500, lambda: (setattr(sess, "mode", CONVERSE), sess.push("mode"))),
        (0, state(State.LISTENING)),
        (1300, None),                       # green travelling to violet
        (0, lambda: (setattr(sess, "auto_ask_in", 2.2),
                     pill.card.show_partial(QUESTION))),
        (1200, None),                       # ask in 2s, or press it yourself
        (0, lambda: (setattr(sess, "auto_ask_in", None), pill.card.ask(QUESTION))),
        (0, state(State.ASKING, Activity("asking", True))),
        (1500, None),
        (0, lambda: (setattr(sess, "can_take_reply", True), sess.push("reply", ANSWER))),
        (0, state(State.IDLE)),
        (2200, None),
    ]
    return steps


gdi32 = ctypes.windll.gdi32
SRCCOPY, DIB_RGB_COLORS, BI_RGB = 0x00CC0020, 0, 0
#: `DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`, for the length of one BitBlt.
PER_MONITOR_V2 = ctypes.c_void_p(-4)

#: Declared, because the default would be `int`. This call hands back the
#: previous DPI context as a 64-bit handle, and ctypes truncating it to 32 bits
#: means the restore silently fails — after which Tk answers `winfo_rootx` in
#: framebuffer pixels, the recorder asks for a region three times too big, and
#: the reel comes out 1296 px wide off a 464 px window. Cost one take to find.
user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def _blit_here(sx: int, sy: int, w: int, h: int) -> Image.Image:
    """Copy one rectangle of the screen, in framebuffer pixels.

    `ImageGrab.grab` is the obvious way and was the first one: it copies all 8.3
    million pixels of a 4K display to keep the hundred thousand a reel frame
    needs, which measured 180 ms and held the recording to 5 fps — too slow to
    show a meter following a voice, which is most of what the reel is for. This
    blits the region and nothing else, at about 12 ms.
    """
    screen = mem = bmp = None
    try:
        screen = user32.GetDC(0)
        mem = gdi32.CreateCompatibleDC(screen)
        bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
        gdi32.SelectObject(mem, bmp)
        gdi32.BitBlt(mem, 0, 0, w, h, screen, sx, sy, SRCCOPY)
        hdr = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32,
                               BI_RGB, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(hdr), DIB_RGB_COLORS)
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        if bmp:
            gdi32.DeleteObject(bmp)
        if mem:
            gdi32.DeleteDC(mem)
        if screen:
            user32.ReleaseDC(0, screen)


def _wbox(w) -> tuple[int, int, int, int]:
    """Where a window actually is, asked of Win32 rather than of Tk.

    `winfo_rootx`/`winfo_rooty` answer out of Tk's own cache, which is stale for
    a frame or two after a window is mapped or moved — a panel that has been
    deiconified but not yet placed reports 0,0, and `update_idletasks` does not
    reliably settle it. A still taken after a 900 ms pause never sees this, which
    is why `shots.py` can use `winfo_*` happily; a reel sampling every 40 ms
    caught the conversation card at the origin on 31 frames of 223, and since the
    canvas is a union of boxes, those 31 stretched all 223 onto a 1511 px canvas
    that was three-quarters empty.

    `GetWindowRect` has no cache to be stale. These are `overrideredirect`
    windows, so the frame rect and the client rect are the same thing.
    """
    r = wintypes.RECT()
    user32.GetWindowRect(ui.toplevel_hwnd(w), ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


class Blitter(threading.Thread):
    """Runs every blit on one thread that is DPI-aware and stays that way.

    A virtualized process blits the *scaled* desktop, so the capture has to
    happen under per-monitor awareness or it comes back soft. Doing that around
    each blit on Tk's own thread and restoring afterwards is the obvious shape,
    and it is what the second take did — the restore failed intermittently, and
    every frame after a failure measured its windows in framebuffer pixels. The
    union of those boxes with the honest ones produced a 2266 px canvas out of a
    464 px window, silently, in a file that still played.

    Awareness is a property of the *thread*, so a thread of its own is the whole
    fix: this one is aware for its entire life, Tk's is never touched, and there
    is no restore to fail.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._want: tuple[int, int, int, int] | None = None
        self._got: Image.Image | None = None
        self._ask = threading.Event()
        self._done = threading.Event()
        self._ready = threading.Event()
        self.start()
        self._ready.wait(5)

    def run(self) -> None:
        user32.SetThreadDpiAwarenessContext(PER_MONITOR_V2)
        self._ready.set()
        while True:
            self._ask.wait()
            self._ask.clear()
            try:
                self._got = _blit_here(*self._want)
            except Exception:
                traceback.print_exc()
                self._got = None
            self._done.set()

    def blit(self, sx: int, sy: int, w: int, h: int) -> Image.Image | None:
        self._want, self._got = (sx, sy, w, h), None
        self._done.clear()
        self._ask.set()
        self._done.wait(5)
        return self._got


class Recorder:
    """Grabs the window stack on a timer and keeps every frame in memory.

    Each frame is stored at Tk's own coordinate scale rather than the
    framebuffer's — a DPI-virtualized process on a 4K display would otherwise
    hold nine times the pixels of the GIF it is going to write, and a fifteen
    second reel does not fit in memory at that size.
    """

    def __init__(self, pill, scale: float) -> None:
        self.pill, self.scale = pill, scale
        self.frames: list[tuple[tuple[int, int, int, int], Image.Image]] = []
        self.parts: list[list[tuple[str, tuple[int, int, int, int]]]] = []
        self.unplaced = 0
        self.claims: set[tuple[int, int, int]] = set()
        self.times: list[float] = []
        self._last = time.perf_counter()
        self._k = _ratio(ImageGrab.grab(all_screens=True))
        self._vx = user32.GetSystemMetrics(76)
        self._vy = user32.GetSystemMetrics(77)
        self._blitter = Blitter()
        #: The invariant the second take broke. Tk answers this in the coordinate
        #: space it is currently in, so it is constant for the whole run — unless
        #: something has moved this thread's DPI awareness, which is exactly the
        #: failure that produced a canvas five times too wide without erroring.
        self._sw, self._sh = pill.winfo_screenwidth(), pill.winfo_screenheight()

    def grab(self) -> None:
        pill = self.pill
        _front(pill)
        pill.update_idletasks()
        if pill.winfo_screenwidth() != self._sw:
            raise RuntimeError(
                f"the coordinate space moved mid-recording: Tk said "
                f"{self._sw} px wide and now says {pill.winfo_screenwidth()}")
        self.claims.add((pill.x, pill.pill_w, pill._docked_w))
        parts = [(type(w).__name__, _wbox(w)) for w in _visible(pill)]
        boxes = [b for _n, b in parts]
        if not boxes:
            return
        # A placed window is never at the origin: `reposition` clamps to at least
        # `EDGE_AIR` from the work area on both axes. (0, 0) means deiconified and
        # not yet moved — one or two frames of a transition that no still ever
        # sees, and that the union canvas would otherwise make permanent.
        if any(b[0] <= 0 and b[1] <= 0 for b in boxes):
            self.unplaced += 1
            return
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        k, s = self._k, self.scale
        img = self._blitter.blit(
            round((box[0] - self._vx) * k), round((box[1] - self._vy) * k),
            round((box[2] - box[0]) * k), round((box[3] - box[1]) * k))
        if img is None:
            return
        w = max(1, round((box[2] - box[0]) * s))
        h = max(1, round((box[3] - box[1]) * s))
        self.frames.append((box, img.resize((w, h), Image.LANCZOS)))
        self.parts.append(parts)
        now = time.perf_counter()
        self.times.append(now - self._last)
        self._last = now

    def report(self) -> None:
        """Say what geometry the run actually saw, per window.

        The canvas is a union, so one frame with a wrong box silently inflates
        every frame — a 464 px window came out on a 1511 px canvas twice before
        this printed the boxes and named which window was doing it.
        """
        from collections import Counter
        seen = Counter(tuple(p) for p in self.parts)
        undocked = 0
        for parts, n in seen.most_common():
            shape = "  ".join(f"{name} {b[2] - b[0]}x{b[3] - b[1]}@{b[0]},{b[1]}"
                              for name, b in parts)
            # The pill and whatever panel is up share one column — that is what
            # docking means, and `_sync_dock` holds the right edge to get it. When
            # they disagree the pill is drawing outside the panel it is joined to,
            # which on the right-hand edge of the screen means drawing off it.
            bad = len(parts) > 1 and any(b[0] != parts[0][1][0] for _n, b in parts)
            undocked += n if bad else 0
            print(f"  {n:4d} frames  {shape}{'   <- NOT DOCKED' if bad else ''}",
                  flush=True)
        print(f"  pill said (x, pill_w, _docked_w): {sorted(self.claims)}", flush=True)
        if self.unplaced:
            print(f"  ({self.unplaced} frames skipped: a window was still at 0,0)",
                  flush=True)
        if undocked:
            print(f"  ! {undocked} frames have the pill outside its panel's column",
                  file=sys.stderr)

    def compose(self, margin: int) -> tuple[list[Image.Image], list[int]]:
        """Paste every frame onto one canvas, positioned where it really was."""
        # Clamped to the desktop, because a window is allowed to extend past it
        # and the blit of anything beyond the edge comes back black. The pill does
        # exactly that while docked — see `report`'s NOT DOCKED line — and without
        # this the reel carries a 200 px black band down its right-hand side.
        left = max(0, min(b[0] for b, _ in self.frames) - margin)
        top = max(0, min(b[1] for b, _ in self.frames) - margin)
        right = min(self._sw, max(b[2] for b, _ in self.frames) + margin)
        bottom = min(self._sh, max(b[3] for b, _ in self.frames) + margin)
        s = self.scale
        size = (round((right - left) * s), round((bottom - top) * s))
        out = []
        for box, img in self.frames:
            canvas = Image.new("RGB", size, BACKDROP)
            canvas.paste(img, (round((box[0] - left) * s), round((box[1] - top) * s)))
            out.append(canvas)
        # The first interval is the time before the first frame existed, not a
        # duration the reel should sit on.
        gaps = self.times[1:] + [self.times[-1] if self.times else 0.1]
        return out, [max(20, min(600, round(g * 1000))) for g in gaps]


def write_gif(frames, durations, path: Path) -> None:
    """One palette for the whole reel, built from a sample of it.

    Per-frame palettes are what make a GIF of flat surfaces shimmer: the
    quantizer picks slightly different greys for the same panel each frame and
    the background crawls. Sampling across the reel instead means the palette has
    seen the violet before it has to draw it.
    """
    step = max(1, len(frames) // 24)
    sample = frames[::step]
    strip = Image.new("RGB", (sample[0].width, sample[0].height * len(sample)))
    for i, f in enumerate(sample):
        strip.paste(f, (0, i * f.height))
    pal = strip.quantize(colors=COLOURS, method=Image.MEDIANCUT)
    flat = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    # `disposal=1` — leave each frame in place — is what makes the file small
    # enough to put on a README. Flow's surfaces barely change between frames:
    # the meter moves, a label changes, the rest of the panel is identical, and
    # leaving the previous frame up lets the encoder store only the rectangle
    # that differs. `disposal=2` clears to the background first, so every frame
    # has to carry the whole canvas again — the same reel, four times the bytes.
    flat[0].save(path, save_all=True, append_images=flat[1:], duration=durations,
                 loop=0, optimize=True, disposal=1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "flow.gif")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="output pixels per unit of Tk's coordinate space")
    ap.add_argument("--margin", type=int, default=22)
    args = ap.parse_args()

    sess = FakeSession()
    hotkeys = SimpleNamespace(
        chosen={"toggle": "ctrl+alt+space", "send": "ctrl+alt+enter",
                "cancel": "ctrl+alt+esc", "mode": "ctrl+alt+M",
                "quit": "ctrl+alt+Q"},
        failed=[], stop=lambda: None, drain=lambda: [])
    pill = Pill(sess, hotkeys=hotkeys)
    ui.owned_by_flow = lambda _h: True

    back = tk.Toplevel(pill)
    back.overrideredirect(True)
    back.configure(bg=BACKDROP)
    back.geometry(f"{pill.winfo_screenwidth()}x{pill.winfo_screenheight()}+0+0")
    ui._no_activate(back)
    back.attributes("-topmost", True)
    back.update_idletasks()
    back.lower(pill)

    # Both panels freeze their redraw while the pointer is inside them — a cursor
    # parked over the panel would record fifteen seconds of a still image.
    #
    # Bottom-left, not `shots.py`'s 60,60. A panel that has been deiconified but
    # not yet positioned sits at 0,0, so 60,60 is *inside* it — and `_render`
    # skips `reposition()` while the pointer is in the window, which is the right
    # rule for a window under a hand and the wrong one for a window that has
    # never been placed. The conversation card stayed at the origin for 31 frames
    # of 223 because of it, and the reel's canvas is a union of window boxes, so
    # those 31 stretched the other 192 onto a canvas three times too wide.
    #
    # Inside the *work area*, so it lands above the taskbar rather than on it — a
    # hover there raises a preview flyout over the backdrop, and into the reel.
    home = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(home))
    user32.SetCursorPos(pill.work[0] + 8, pill.work[3] - 8)

    rec = Recorder(pill, args.scale)
    steps = timeline(pill, sess)
    print(f"recording {len(steps)} beats -> {args.out}", flush=True)
    running = True

    def capture():
        if running:
            try:
                rec.grab()
            except Exception:
                traceback.print_exc()
            pill.after(CAPTURE_MS, capture)

    def run(i=0):
        nonlocal running
        if i >= len(steps):
            running = False
            user32.SetCursorPos(home.x, home.y)
            pill.after(200, pill.quit_app)
            return
        hold, fn = steps[i]

        def go():
            if fn is not None:
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
            run(i + 1)

        pill.after(hold, go)

    pill.after(3 * 60 * 1000, pill.quit_app)  # hard stop, whatever happens
    pill.after(WARMUP_MS, capture)
    pill.after(WARMUP_MS, run)
    pill.mainloop()

    if not rec.frames:
        print("no frames captured", file=sys.stderr)
        raise SystemExit(1)
    rec.report()
    frames, durations = rec.compose(args.margin)
    write_gif(frames, durations, args.out)
    kb = args.out.stat().st_size / 1024
    print(f"\n{len(frames)} frames, {sum(durations) / 1000:.1f}s, "
          f"{frames[0].width}x{frames[0].height}, {kb:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
