"""Build the repository's social preview: a 1280x640 card with the README's reel playing
in its right half.

GitHub shows this image wherever a link to the repo is shared. Settings ▸ General ▸ Social
preview takes a PNG, JPG or GIF under 1 MB, and has no API, so the upload is by hand. X,
Slack and LinkedIn show only a GIF's first frame, so the card opens on the reel's answered
question, with the pointer resting clear of it, and plays the tour on from there wherever
GIFs move.

The left half is HTML in Flow Home's own fonts and colours, photographed once by a
headless Edge. The right half is `docs/flow.gif`, frame by frame, so re-record that with
`scripts/home_reel.py` first and this follows it:

    uv run --no-sync --with pillow --with playwright python scripts/social_card.py

It writes `docs/social-preview.gif`, which git ignores (GitHub keeps the uploaded copy),
and says so if the result is over GitHub's limit.
"""

from __future__ import annotations

import argparse
import io
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
FONTS = REPO / "flow" / "assets" / "fonts"
ICON = REPO / "flow" / "assets" / "flow.svg"

#: GitHub's numbers: 1280x640 displays best, and the file has to be under 1 MB.
CARD = (1280, 640)
LIMIT = 1_000_000

#: The reel at 80 %, so the window and the desk strip with the pill fit the card's
#: height. Its right edge runs off the card.
SCALE = 0.8
AT = (572, 37)
RADIUS = 10

#: Seconds into the reel where the card opens: the question answered, the hand resting
#: under the conversation list. Most places that show the card show only this frame.
OPEN_AT = 22.6
#: How long that frame holds, where the GIF does play.
OPEN_MS = 2400

#: Flow Home's rail, flat: a gradient would band in a GIF's 256 colours.
BG = (18, 20, 24)
EDGE = (46, 50, 59)
COLOURS = 256

LEFT = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Plex; src: url("{fonts}/IBMPlexSans-Regular.ttf"); font-weight: 400; }}
@font-face {{ font-family: Plex; src: url("{fonts}/IBMPlexSans-Medium.ttf"); font-weight: 500; }}
@font-face {{ font-family: Plex; src: url("{fonts}/IBMPlexSans-SemiBold.ttf"); font-weight: 600; }}
@font-face {{ font-family: PlexMono; src: url("{fonts}/IBMPlexMono-Regular.ttf"); }}
html, body {{ margin: 0; }}
body {{ width: {w}px; height: {h}px; background: rgb{bg}; color: #E6E8ED; overflow: hidden;
        font-family: Plex, sans-serif; position: relative; }}
.left {{ position: absolute; left: 64px; top: 76px; width: 480px; }}
.icon {{ width: 76px; height: 76px; display: block; }}
h1 {{ font-size: 80px; line-height: 1; font-weight: 600; margin: 26px 0 18px; letter-spacing: -1px; }}
p {{ font-size: 30px; line-height: 42px; margin: 0; color: #C7CBD4; }}
.keys {{ margin-top: 28px; display: flex; align-items: center; gap: 10px; font-size: 20px;
         color: #A0A6B2; }}
kbd {{ font: 500 18px Plex, sans-serif; color: #E6E8ED; background: #22262E; border-radius: 8px;
       border: 1px solid #3A404B; border-bottom-width: 3px; padding: 3px 11px; }}
.plus {{ color: #656B78; }}
.os {{ margin-top: 22px; display: flex; gap: 10px; }}
.chip {{ font-size: 15px; font-weight: 500; border-radius: 999px; padding: 5px 12px; border: 1px solid; }}
.on {{ background: #16271F; border-color: #1F3A2C; color: #3ECF8E; }}
.soon {{ background: #2C2515; border-color: #3F331C; color: #F2C27A; }}
.url {{ position: absolute; left: 64px; bottom: 40px; font: 17px PlexMono, monospace; color: #656B78; }}
</style></head><body>
<div class="left">
  <img class="icon" src="{icon}" alt="">
  <h1>Flow</h1>
  <p>Local English dictation<br>with a talk-to-it refine loop</p>
  <div class="keys"><kbd>Ctrl</kbd><span class="plus">+</span><kbd>Win</kbd><span>&nbsp;hold, talk, let go</span></div>
  <div class="os"><span class="chip on">Windows 10 · 11</span><span class="chip soon">macOS · Linux: Lite, in progress</span></div>
</div>
<div class="url">github.com/samartomar/flow</div>
</body></html>"""


def left_half() -> Image.Image:
    """The card without the reel: the words, photographed once."""
    from playwright.sync_api import sync_playwright

    html = LEFT.format(fonts=FONTS.as_uri(), icon=ICON.as_uri(), w=CARD[0], h=CARD[1], bg=BG)
    # From a file rather than `set_content`: a page with no origin may not read the fonts
    # and the icon off the disk.
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        page_file = Path(tmp) / "card.html"
        page_file.write_text(html, encoding="utf-8")
        browser = p.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page(viewport={"width": CARD[0], "height": CARD[1]},
                                    device_scale_factor=1)
            page.goto(page_file.as_uri())
            page.evaluate("document.fonts.ready.then(() => true)")
            png = page.screenshot(type="png")
        finally:
            browser.close()
    return Image.open(io.BytesIO(png)).convert("RGB")


def timeline(reel: Image.Image) -> tuple[list[int], int]:
    """Every frame's duration, and the index of the one showing at `OPEN_AT`."""
    durations, start, t = [], 0, 0
    for i in range(reel.n_frames):
        reel.seek(i)
        d = reel.info["duration"]
        if t <= OPEN_AT * 1000 < t + d:
            start = i
        durations.append(d)
        t += d
    return durations, start


def framer(left: Image.Image, size: tuple[int, int]):
    """A function from one frame of the reel to one frame of the card."""
    w, h = round(size[0] * SCALE), round(size[1] * SCALE)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), RADIUS, fill=255)
    box = (AT[0] - 1, AT[1] - 1, AT[0] + w, AT[1] + h)

    def card(frame: Image.Image) -> Image.Image:
        out = left.copy()
        out.paste(frame.convert("RGB").resize((w, h), Image.LANCZOS), AT, mask)
        ImageDraw.Draw(out).rounded_rectangle(box, RADIUS + 1, outline=EDGE, width=1)
        return out

    return card


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reel", type=Path, default=REPO / "docs" / "flow.gif")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "social-preview.gif")
    args = ap.parse_args()

    reel = Image.open(args.reel)
    durations, start = timeline(reel)
    order = list(range(start, reel.n_frames)) + list(range(start))
    card = framer(left_half(), reel.size)

    def frame(i: int) -> Image.Image:
        reel.seek(i)
        return card(reel)

    # One palette for all of it, from frames across the whole tour, as the reel's is.
    sample = [frame(i) for i in order[::max(1, len(order) // 40)]]
    strip = Image.new("RGB", (CARD[0], CARD[1] * len(sample)))
    for n, img in enumerate(sample):
        strip.paste(img, (0, n * CARD[1]))
    pal = strip.quantize(colors=COLOURS, method=Image.Quantize.MEDIANCUT)

    flat = [frame(i).quantize(palette=pal, dither=Image.Dither.NONE) for i in order]
    shown = [durations[i] for i in order]
    shown[0] = max(shown[0], OPEN_MS)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    flat[0].save(args.out, save_all=True, append_images=flat[1:], duration=shown,
                 loop=0, optimize=True, disposal=1)
    size = args.out.stat().st_size
    print(f"{len(flat)} frames, {sum(shown) / 1000:.1f} s, {CARD[0]}x{CARD[1]}, "
          f"{size / 1024:.0f} KB -> {args.out}")
    if size >= LIMIT:
        sys.exit(f"GitHub takes a social preview under 1 MB; this is {size:,} bytes. "
                 "Lower SCALE, or re-record a shorter reel.")


if __name__ == "__main__":
    main()
