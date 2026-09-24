"""Record Flow Home with the pill over it, as the README's GIF.

Flow Home is where everything that isn't talking lives, so the reel walks its pages in
the rail's order — Home, History, Voice, Conversations, Models, Settings — and on
Conversations the pill dictates a question into the composer, which pastes it the way it
pastes into any window, and Enter asks it. `compact_reel.py` records the pill against a
drawn terminal; this records the product around it.

Two recordings, joined at the moment the talk keys go down:

- **Flow Home** is the real page, server and API over `flow.home.demo`'s pretend
  session: no microphone, no model, no CLI. A headless Microsoft Edge shows it and
  Playwright photographs the viewport. The pointer is Playwright's, inside that browser,
  so hovers light up the way they do under a mouse; the arrow in the reel is drawn where
  it was.
- **The pill** is the real `CompactPill`, kept by `compact_reel.Tap` from the bitmaps it
  hands Windows, holding for exactly as long as the page's dictation took.

Nothing on the screen is read and the real pointer never moves. The pill does show at the
bottom of the monitor for about six seconds. Drawn rather than recorded: the window's
caption, in the style of the Edge app window Flow Home opens in, and a strip of desk
below it where the pill rests, as it does at the bottom of a screen, so that it never
covers the page. The session's clock is set to the afternoon, so the day it shows reads
as a day whatever time the reel is made, and History names the ordinary place for its
file rather than the demo's temporary folder, which has the user name in it.

    uv run --no-sync --with pillow --with playwright python scripts/home_reel.py
    uv run --no-sync --with pillow --with playwright python scripts/home_reel.py --frames out/

Playwright drives the Edge that Windows ships (`channel="msedge"`), so it downloads no
browser of its own.
"""

from __future__ import annotations

import argparse
import datetime
import io
import math
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

# First among Flow's imports, for its own first line: DPI awareness is fixed for the
# process the moment a window exists, and the pill is recorded later in this one.
import compact_reel as reel  # noqa: E402
import shots  # noqa: E402  — the fake session the pill runs against
from flow import stats  # noqa: E402
from flow.diag import Diag  # noqa: E402
from flow.history import ANSWERED, ASKED, DICTATED, KEEP, REFINED, SET_ASIDE, make_entry, new_id  # noqa: E402
from flow.home import demo  # noqa: E402
from flow.session import DICTATE, RECENT_ANSWERED, RECENT_ASKED, RECENT_SAID, State  # noqa: E402
from flow.ui_compact import CompactPill  # noqa: E402

FONTS = REPO / "flow" / "assets" / "fonts"
ICON = REPO / "flow" / "assets" / "flow.ico"
WINFONTS = Path("C:/Windows/Fonts")

#: Flow Home's viewport: just past `app.css`'s 1080 px breakpoint, so every page has
#: its two columns — Conversations its list beside the thread — and no wider than that,
#: so a README shrinks it as little as it can.
VIEW = (1100, 620)
#: Edge's caption above it, in Windows 11's light theme, as a light desktop shows it.
CAPTION = 32
CAPTION_BG, CAPTION_INK = (243, 243, 243), (26, 26, 26)
#: The strip of desk under the window where the pill rests, and its colour, which is
#: `compact_reel`'s desk. The line between is the window's bottom edge.
DESK_H = 56
DESK, EDGE = reel.DESK, reel.EDGE
#: Where History says its file is. The demo keeps one in a temporary folder whose path
#: has the user name in it; this is where a real one lives, for somebody called "you".
HISTORY_SHOWN = r"C:\Users\you\.flow\history.jsonl"
#: The page's own colours, for the palette to keep exact (`app.css`, `:root`).
TOKENS = ("#16181D", "#1A1D23", "#121418", "#262A32", "#E6E8ED", "#A0A6B2", "#656B78",
          "#C7CBD4", "#8A909C", "#22262E", "#262B34", "#2E323B", "#3A404B", "#3ECF8E",
          "#7AA2F7", "#F2584A", "#E8A33D", "#E1B75C", "#B48EF5", "#EAECF1", "#15171C",
          "#16271F", "#1F3A2C", "#2B2440", "#3D3358", "#D9C7FB", "#F2C27A", "#30353F")
#: A GIF's whole palette: the page has more colours than the pill alone.
COLOURS = 256

#: The afternoon the session lives in, as (hour, minute) of today.
AFTERNOON = (16, 40)
#: Ask's workspace. A plain folder rather than this checkout's own path, which is
#: somebody's own path in a public GIF (`compact_reel.main` took the same care).
WORKSPACE = r"D:\dev\flow"
#: What is dictated into the composer, and so asked. The pretend CLI answers with
#: `demo.DEMO_ANSWER`, which is true of this repository.
QUESTION = reel.QUESTION
#: How long the pretend CLI takes: long enough to see it working.
ANSWER_SEC = 2.2

#: Where the pointer rests before the tour and after it.
START = (566, 186)
NAV = '#nav a[href="#/{}"]'
SHOW = '.seg[aria-label="Show"] button:has-text("{}")'

#: Today in History: (hours ago, kind, what was pasted, fields).
TODAY = [
    (0.9, DICTATED, "claude, look at session.py and find out why the decode worker drops "
                    "the last utterance when I stop talking quickly.",
     {"app": "WindowsTerminal.exe"}),
    (1.6, REFINED, "Strip every control from the push-to-talk pill in flow/ui.py - leave "
                   "the mic glyph and the meter. On release, paste into the window that "
                   "held focus before the pill.",
     {"app": "WindowsTerminal.exe", "cli": "claude", "secs": 6.1,
      "heard": "make the pill not show any controls just the mic and when i let go it "
               "should paste in the window i was in before"}),
    (2.3, SET_ASIDE, "Thank you.", {"reason": "filler"}),
    (2.8, DICTATED, "Hey Marco, are we still good for the review on Tuesday afternoon, and "
                    "did you get a chance to look at the updated figures?",
     {"app": "slack.exe"}),
    (3.4, DICTATED, "Thanks, I will send the updated figures by Friday.",
     {"app": "OUTLOOK.EXE"}),
    (4.2, DICTATED, "Rename the config flag to decode_device, and keep the old name working "
                    "for one release with a warning.",
     {"app": "Code.exe"}),
    (5.1, DICTATED, "Sounds good, let's ship it after the demo tomorrow.",
     {"app": "slack.exe"}),
]
#: Earlier conversations, for the list beside the composer: (hours ago, question, answer).
EARLIER = [
    (22.0, "What does the send word do when the pill is in Refine?",
     "It sends the shaped prompt rather than what you said: Refine's Send pastes the "
     "prompt the CLI wrote."),
    (8 * 24.0, "Three names for a send word that nobody says by accident",
     "Boom, ship it, and send it - each measured against hundreds of recordings so none "
     "fires by accident."),
]


# -- the clock ---------------------------------------------------------------------


def shift_clock() -> float:
    """Move this process's wall clock to this afternoon, and return where it now reads.

    History groups by day and Home counts today's words, so a reel made after midnight
    would open on an empty today. Only `time.time` moves: every time Flow Home shows is
    formatted from a timestamp it read there, and the intervals that pace the reel are
    `perf_counter` and `monotonic`, which a constant offset would not touch anyway.
    """
    real = time.time
    now = real()
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    offset = midnight + AFTERNOON[0] * 3600 + AFTERNOON[1] * 60 - now
    time.time = lambda: real() + offset
    return time.time()


# -- Flow Home, over the demo's session ----------------------------------------------


def build_home():
    """The demo's Home and session, holding a day of use and no conversation yet."""
    home, session = demo.build()
    profile = session.profile
    now = time.time()
    session.workspace = WORKSPACE
    profile.note_workspace(WORKSPACE)
    profile.history = KEEP
    profile.save()
    # The conversation `demo.seed` always puts on screen is the one this reel asks.
    session.new_conversation()
    session.answer_sec = ANSWER_SEC
    session.capturing, session.level_db = False, -90.0
    entries, pastes = [], []
    for hours, kind, text, fields in TODAY:
        at = now - hours * 3600
        fields = dict(fields)
        if kind != SET_ASIDE:
            words = len(text.split())
            fields.update(how="pasted", words=words)
            pastes.append((at, words))
        entries.append(make_entry(kind, text, at=at, **fields))
    for hours, question, answer in EARLIER:
        conv, at = new_id(), now - hours * 3600
        entries.append(make_entry(ASKED, question, at=at, conv=conv, ws=WORKSPACE, via="voice"))
        entries.append(make_entry(ANSWERED, answer, at=at + 5, conv=conv, cli="claude",
                                  secs=4.8))
    # In the order they happened, which is the order the file is read back in.
    for entry in sorted(entries, key=lambda e: e["at"]):
        session.history.keep(entry)
    session.history.flush()
    # Today's words are counted from the trace, where the session writes a record for
    # every paste; History keeps only what was said. `Diag` stamps a record with the
    # clock, so the clock is set to each paste's moment while its record is written.
    shifted = time.time
    try:
        for at, words in sorted(pastes):
            time.time = lambda at=at: at
            Diag(home.trace_path).write(stats.RECORD, words=words, ms=round(words / 2.4 * 1000))
    finally:
        time.time = shifted
    session._recent = [(RECENT_SAID, TODAY[0][2])]
    shown_path(home)
    return home, session


def shown_path(home) -> None:
    """History's footer names `HISTORY_SHOWN` instead of the demo's temporary file."""
    api = home.api
    for key, route in list(api.routes.items()):
        if route == api.history_page:
            def page(body, route=route):
                return {**route(body), "path": HISTORY_SHOWN}
            api.routes[key] = page


@dataclass
class Shot:
    """One photograph of the page, and the pointer and keys at that moment."""
    t: float
    png: bytes
    cursor: tuple
    keys: tuple


class Director:
    """Flow Home's side of the reel: the tour, photographed as it goes."""

    def __init__(self, page, home, session) -> None:
        self.page, self.home, self.session = page, home, session
        self.shots: list[Shot] = []
        self.clicks: list[float] = []
        self.marks: dict[str, float] = {}
        self.cursor = START
        self.keys: tuple = ()
        self._talking_since: float | None = None

    # -- the camera -------------------------------------------------------------

    def shoot(self) -> None:
        if self._talking_since is not None:
            # The rail's meter reads the session's level at every poll, as it does while
            # a real hold lasts: a voice's envelope, in syllables.
            u = time.perf_counter() - self._talking_since
            self.session.level_db = -30 + 9 * math.sin(u * 11) * math.sin(u * 2.3 + 0.6)
        t = time.perf_counter()
        png = self.page.screenshot(type="png", caret="initial")
        self.shots.append(Shot(t, png, self.cursor, self.keys))

    def wait(self, sec: float) -> None:
        end = time.perf_counter() + sec
        while True:
            self.shoot()
            if time.perf_counter() >= end:
                return

    # -- the hand ----------------------------------------------------------------

    def move(self, target, sec: float) -> None:
        """Glide the pointer to `target`, easing in and out, a photograph per step."""
        (x0, y0), (x1, y1) = self.cursor, target
        began = time.perf_counter()
        while True:
            u = min(1.0, (time.perf_counter() - began) / sec)
            e = u * u * (3 - 2 * u)
            self.cursor = (x0 + (x1 - x0) * e, y0 + (y1 - y0) * e)
            self.page.mouse.move(*self.cursor)
            self.shoot()
            if u >= 1.0:
                return

    def to(self, selector: str, sec: float, dx: float = 0.0, dy: float = 0.0) -> None:
        box = self.page.locator(selector).first.bounding_box()
        self.move((box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy), sec)

    def click(self) -> None:
        self.page.mouse.down()
        self.page.mouse.up()
        self.clicks.append(time.perf_counter())
        self.shoot()

    def press(self, key: str) -> None:
        self.keys = (key,)
        self.shoot()
        self.marks[key] = time.perf_counter()
        self.page.keyboard.press(key)
        self.wait(0.45)
        self.keys = ()

    def dictate(self, text: str, sec: float) -> None:
        """Hold the talk keys for `sec` while the pill hears it, then let go: the words
        paste into whatever has focus, which here is the composer."""
        s = self.session
        self.keys = ("Ctrl", "Win")
        s.capturing = True
        self.marks["hold"] = self._talking_since = time.perf_counter()
        self.wait(sec)
        self._talking_since = None
        s.capturing, s.level_db = False, -90.0
        self.keys = ()
        self.marks["release"] = time.perf_counter()
        self.page.keyboard.insert_text(text)
        # What the session does with any paste: History, and today's words.
        s.target_app = "msedge.exe"
        s.delivered(text)
        Diag(self.home.trace_path).write(stats.RECORD, words=len(text.split()),
                                         ms=round(sec * 1000))
        s._recent.append((RECENT_SAID, text))
        self.shoot()

    # -- the tour ----------------------------------------------------------------

    def tour(self) -> None:
        self.page.mouse.move(*START)
        self.marks["begin"] = time.perf_counter()
        self.wait(2.4)                                # Home: the two things Flow does
        self.to(NAV.format("history"), 0.6)
        self.click()
        self.wait(1.4)                                # History: what went where
        self.to(SHOW.format("Refined"), 0.6)
        self.click()
        self.wait(2.0)                                # what was heard, and what was sent
        self.to(NAV.format("voice"), 0.7)
        self.click()
        self.wait(2.4)                                # Voice: tuning, the check, the dictionary
        self.to(NAV.format("ask"), 0.6)
        self.click()
        self.wait(1.0)                                # Conversations, a new one
        self.to("#ask-text", 0.7, dx=-150)
        self.click()
        self.wait(0.6)
        self.dictate(QUESTION, 2.8)                   # hold ctrl+win, talk, let go
        self.wait(1.2)
        self.press("Enter")                           # and Enter asks it
        self.wait(ANSWER_SEC + 2.8)
        self.session._recent += [(RECENT_ASKED, QUESTION),
                                 (RECENT_ANSWERED, reel.ANSWER)]
        self.to(NAV.format("models"), 0.7)
        self.click()
        self.wait(2.4)                                # Models: what hears you, on what
        self.to(NAV.format("settings"), 0.6)
        self.click()
        self.wait(2.4)                                # Settings: the rest
        self.to(NAV.format("home"), 0.7)
        self.click()
        self.wait(1.2)
        self.move(START, 0.6)                         # back where it began, for the loop
        self.wait(0.4)
        self.marks["end"] = time.perf_counter()


def warm(page) -> None:
    """Every page once before the take, so none opens on its first fetch: Models scans
    the speech-model cache, and each page's first draw loads its fonts."""
    for name in ("history", "voice", "ask", "models", "settings", "home"):
        page.evaluate(f"location.hash = '#/{name}'")
        page.wait_for_timeout(1500 if name == "models" else 800)


def record_home(home, session) -> Director:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page(viewport={"width": VIEW[0], "height": VIEW[1]},
                                    device_scale_factor=1)
            # The page's one clock read, the seconds an answer has been awaited, must
            # agree with the session's afternoon.
            page.clock.install(time=datetime.datetime.fromtimestamp(time.time()))
            page.goto(home.url("home"))
            page.wait_for_selector(NAV.format("home"))
            warm(page)
            director = Director(page, home, session)
            director.tour()
            return director
        finally:
            browser.close()


# -- the pill ------------------------------------------------------------------------


@dataclass
class PillTake:
    frames: list
    marks: dict
    k: float


def record_pill(hold_sec: float) -> PillTake:
    """The real pill, holding for `hold_sec` between two rests, as `compact_reel` does."""
    sess = shots.FakeSession()
    sess.workspace = WORKSPACE
    pill = CompactPill(sess)
    pill._outside_click_now = lambda: False
    pill._clicked_off_pill = lambda: False
    tap = reel.Tap(pill)
    marks: dict[str, float] = {}

    def rest():
        sess.state = State.IDLE
        pill.armed = False

    def hold():
        sess.mode, sess.state, sess.hearing = DICTATE, State.LISTENING, True
        pill.armed = True
        marks["hold"] = time.perf_counter()

    def let_go():
        rest()
        marks["release"] = time.perf_counter()

    steps = [(0, rest), (900, hold), (round(hold_sec * 1000), let_go), (900, None)]
    ks: list[float] = []

    def run(i=0):
        if i == 0:
            ks.append(pill.dev(1000) / 1000)
        if i >= len(steps):
            marks["end"] = time.perf_counter()
            pill.after(200, pill.quit_app)
            return
        wait_ms, fn = steps[i]

        def go():
            if fn is not None:
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
            run(i + 1)

        pill.after(wait_ms, go)

    pill.after(30_000, pill.quit_app)  # hard stop, whatever happens
    pill.after(reel.WARMUP_MS, run)
    pill.mainloop()
    if not tap.frames or "end" not in marks:
        raise SystemExit(f"no pill: {len(tap.frames)} frames, finished={'end' in marks}")
    return PillTake(tap.frames, marks, ks[0])


def pill_sprite(f, k: float) -> np.ndarray:
    """A pill frame as premultiplied RGBA at the page's scale, its constant alpha folded
    in. Resampled channel by channel: premultiplied colour is linear in coverage, so it
    scales without the dark fringe straight alpha gets."""
    src = np.frombuffer(f.px, np.uint8).reshape(f.h, f.w, 4)
    rgba = np.concatenate([src[..., 2::-1], src[..., 3:4]], axis=-1)
    if abs(k - 1.0) > 1e-3:
        size = (round(f.w / k), round(f.h / k))
        rgba = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(rgba[..., i]))
                                    .resize(size, Image.LANCZOS)) for i in range(4)], axis=-1)
    return (rgba.astype(np.uint16) * f.ca + 127) // 255


def blend(out: np.ndarray, sprite: np.ndarray, x: int, y: int) -> None:
    """Premultiplied `sprite` over `out` at (x, y), clipped to it, in place."""
    h, w = sprite.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(out.shape[1], x + w), min(out.shape[0], y + h)
    if x0 >= x1 or y0 >= y1:
        return
    s = sprite[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.uint16)
    under = out[y0:y1, x0:x1].astype(np.uint16)
    a = s[..., 3:4]
    out[y0:y1, x0:x1] = np.minimum(255, s[..., :3] + (under * (255 - a) + 127) // 255)


def premultiplied(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGBA")).astype(np.uint16)
    a[..., :3] = (a[..., :3] * a[..., 3:4] + 127) // 255
    return a


# -- what is drawn rather than recorded ---------------------------------------------


def _font(path: Path, px: int, fallback: str = "IBMPlexSans-Regular.ttf"):
    try:
        return ImageFont.truetype(str(path), px)
    except OSError:
        return ImageFont.truetype(str(FONTS / fallback), px)


def caption(width: int) -> np.ndarray:
    """Edge's caption for an app window: the page's icon and title, and the three
    buttons, in Segoe as Windows draws them."""
    img = Image.new("RGB", (width, CAPTION), CAPTION_BG)
    try:
        icon = Image.open(ICON)
        icon.size = (16, 16)
        icon = icon.convert("RGBA")
    except (OSError, ValueError):
        icon = Image.open(ICON).convert("RGBA").resize((16, 16), Image.LANCZOS)
    img.paste(icon, (10, (CAPTION - 16) // 2), icon)
    d = ImageDraw.Draw(img)
    d.text((36, CAPTION // 2), "Flow", font=_font(WINFONTS / "segoeui.ttf", 12),
           fill=CAPTION_INK, anchor="lm")
    glyphs = _font(WINFONTS / "SegoeIcons.ttf", 10)
    for i, glyph in enumerate(("\ue8bb", "\ue922", "\ue921")):   # close, maximise, minimise
        cx = width - 23 - 46 * i
        d.text((cx, CAPTION // 2), glyph, font=glyphs, fill=CAPTION_INK, anchor="mm")
    return np.asarray(img)


def pointer() -> tuple[np.ndarray, tuple[int, int]]:
    """Windows' arrow, white with a black edge and a soft shadow, and where its tip is."""
    s, pad = 8, 3
    shape = [(0, 0), (0, 16.6), (4.1, 12.8), (6.7, 18.9), (9.0, 17.9), (6.5, 12.0), (11.7, 12.0)]
    w, h = 16 + 2 * pad, 22 + 2 * pad
    pts = [((x + pad) * s, (y + pad) * s) for x, y in shape]
    shadow = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(shadow).polygon([(x + s, y + s) for x, y in pts], fill=90)
    shadow = shadow.filter(ImageFilter.GaussianBlur(s * 1.2))
    arrow = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    arrow.putalpha(shadow)
    arrow = Image.alpha_composite(arrow, _arrow(pts, w * s, h * s, s))
    return premultiplied(arrow.resize((w, h), Image.LANCZOS)), (pad, pad)


def _arrow(pts, w, h, s) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255),
                                width=s)
    return img


def ripple(u: float) -> np.ndarray:
    """The ring a click leaves, `u` of the way through its 0.3 s."""
    s, r = 4, 5 + 12 * u
    size = 36
    img = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    c = size * s / 2
    ImageDraw.Draw(img).ellipse((c - r * s, c - r * s, c + r * s, c + r * s),
                                outline=(255, 255, 255, round(170 * (1 - u))), width=2 * s)
    return premultiplied(img.resize((size, size), Image.LANCZOS))


def keycaps(keys: tuple) -> np.ndarray:
    """The keys being pressed, as Flow Home draws a shortcut (`.kbd` in app.css), a size
    up so a README can read them."""
    mono = _font(FONTS / "IBMPlexMono-Medium.ttf", 12)
    sans = _font(FONTS / "IBMPlexSans-Regular.ttf", 12)
    parts = []
    for i, key in enumerate(keys):
        if i:
            parts.append(("plus", "+"))
        parts.append(("key", key))
    if keys == ("Ctrl", "Win"):
        parts.append(("label", "hold, talk, let go"))
    widths = [mono.getlength(t) + 16 if kind == "key" else
              (mono.getlength(t) if kind == "plus" else sans.getlength(t) + 4)
              for kind, t in parts]
    gap, h = 6, 24
    w = int(sum(widths) + gap * (len(parts) - 1)) + 2
    s = 4
    shapes = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(shapes)
    x = 0.0
    for (kind, _t), pw in zip(parts, widths):
        if kind == "key":
            d.rounded_rectangle((x * s, 0, (x + pw) * s - 1, h * s - 1), radius=5 * s,
                                fill=(46, 50, 59, 255))
            d.rounded_rectangle((x * s + s, s, (x + pw) * s - 1 - s, (h - 2) * s - 1),
                                radius=4 * s, fill=(34, 38, 46, 255))
        x += pw + gap
    img = shapes.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    x = 0.0
    for (kind, t), pw in zip(parts, widths):
        cy = (h - 2) / 2
        if kind == "key":
            d.text((x + pw / 2, cy), t, font=mono, fill=(199, 203, 212, 255), anchor="mm")
        elif kind == "plus":
            d.text((x + pw / 2, cy), t, font=mono, fill=(101, 107, 120, 255), anchor="mm")
        else:
            d.text((x + 4, cy), t, font=sans, fill=(160, 166, 178, 255), anchor="lm")
        x += pw + gap
    return premultiplied(img)


# -- composing -----------------------------------------------------------------------


def compose(director: Director, take: PillTake):
    """The reel on a 40 ms grid: the page as photographed, the pill where it rests, and
    the pointer, the keys and the clicks drawn over them. Identical frames are merged."""
    shots_ = director.shots
    begin, end = director.marks["begin"], director.marks["end"]
    width, height = VIEW[0], CAPTION + VIEW[1] + DESK_H
    top = caption(width)
    desk = np.empty((DESK_H, width, 3), np.uint8)
    desk[:] = DESK
    desk[0] = EDGE

    # The pill: its frames on the page's clock, and its resting capsule for an anchor.
    shift = director.marks["hold"] - take.marks["hold"]
    pframes = take.frames
    ptimes = [f.t + shift for f in pframes]
    rest_i = max((i for i, f in enumerate(pframes) if f.t <= take.marks["hold"]), default=0)
    rest = pill_sprite(pframes[rest_i], take.k)
    ys, xs = np.nonzero(rest[..., 3] > 24)
    cap_left, cap_right, cap_bottom = xs.min(), xs.max() + 1, ys.max() + 1
    cap_top = ys.min()
    # Where the resting frame's top-left goes, so that its capsule sits in the middle of
    # the desk; every other frame is placed relative to it.
    ax = round(width / 2 - (cap_left + cap_right) / 2)
    ay = round(height - DESK_H / 2 - (cap_top + cap_bottom) / 2)
    R = pframes[rest_i]
    sprites: dict[int, np.ndarray] = {}

    def pill_at(i: int):
        if i not in sprites:
            sprites[i] = pill_sprite(pframes[i], take.k)
        f = pframes[i]
        return sprites[i], ax + round((f.x - R.x) / take.k), ay + round((f.y - R.y) / take.k)

    arrow, tip = pointer()
    rings = [ripple(u / 7) for u in range(8)]
    caps: dict[tuple, np.ndarray] = {}
    keys_right = ax + cap_left - 14
    keys_mid = ay + (cap_top + cap_bottom) / 2

    decoded: dict[int, np.ndarray] = {}

    def page_at(i: int) -> np.ndarray:
        if i not in decoded:
            decoded.clear()
            decoded[i] = np.asarray(Image.open(io.BytesIO(shots_[i].png)).convert("RGB"))
        return decoded[i]

    slots = []
    si = max((i for i, s in enumerate(shots_) if s.t <= begin), default=0)
    pi = rest_i
    t = begin
    while t <= end:
        while si + 1 < len(shots_) and shots_[si + 1].t <= t:
            si += 1
        while pi + 1 < len(pframes) and ptimes[pi + 1] <= t:
            pi += 1
        ring = next((min(7, int((t - c) / 0.3 * 8)) for c in reversed(director.clicks)
                     if 0 <= t - c < 0.3), None)
        slots.append((si, pi if ptimes[pi] <= t else rest_i, ring))
        t += STEP_MS_S

    def draw(key) -> np.ndarray:
        si, pi, ring = key
        shot = shots_[si]
        out = np.empty((height, width, 3), np.uint8)
        out[:CAPTION] = top
        out[CAPTION:CAPTION + VIEW[1]] = page_at(si)
        out[CAPTION + VIEW[1]:] = desk
        sprite, x, y = pill_at(pi)
        blend(out, sprite, x, y)
        if shot.keys:
            if shot.keys not in caps:
                caps[shot.keys] = keycaps(shot.keys)
            k = caps[shot.keys]
            blend(out, k, round(keys_right - k.shape[1]), round(keys_mid - k.shape[0] / 2))
        cx, cy = round(shot.cursor[0]), round(shot.cursor[1]) + CAPTION
        if ring is not None:
            r = rings[ring]
            blend(out, r, cx - r.shape[1] // 2, cy - r.shape[0] // 2)
        blend(out, arrow, cx - tip[0], cy - tip[1])
        return out

    keys, durations = [], []
    for key in slots:
        if keys and key == keys[-1]:
            durations[-1] += reel.STEP_MS
        else:
            keys.append(key)
            durations.append(reel.STEP_MS)
    return keys, durations, draw


STEP_MS_S = reel.STEP_MS / 1000


def palette(keys, draw) -> Image.Image:
    """One palette for the whole reel, from frames across all of it plus a swatch of the
    page's own colours: small things — the violet Ask button, a green tick — must not
    lose their colour to the greys that cover most of every frame."""
    step = max(1, len(keys) // 40)
    sample = [draw(k) for k in keys[::step]]
    h, w = sample[0].shape[:2]
    swatch = np.zeros((48, w, 3), np.uint8)
    for i, hexa in enumerate(TOKENS):
        rgb = tuple(int(hexa[j:j + 2], 16) for j in (1, 3, 5))
        swatch[:, i * (w // len(TOKENS)):(i + 1) * (w // len(TOKENS))] = rgb
    strip = np.concatenate(sample + [swatch] * 6, axis=0)
    return Image.fromarray(strip).quantize(colors=COLOURS, method=Image.Quantize.MEDIANCUT)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "flow.gif")
    ap.add_argument("--frames", type=Path, default=None,
                    help="also write every output frame as a PNG here, to look at")
    args = ap.parse_args()

    shift_clock()
    home, session = build_home()
    try:
        print("recording Flow Home in a headless Edge...", flush=True)
        director = record_home(home, session)
    finally:
        home.close()
    hold = director.marks["release"] - director.marks["hold"]
    print(f"{len(director.shots)} photographs; recording the pill for a {hold:.2f} s hold",
          flush=True)
    take = record_pill(hold)
    keys, durations, draw = compose(director, take)
    pal = palette(keys, draw)
    flat = []
    for i, key in enumerate(keys):
        rgb = draw(key)
        if args.frames:
            args.frames.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb).save(args.frames / f"{i:04d}.png")
        flat.append(Image.fromarray(rgb).quantize(palette=pal, dither=Image.Dither.NONE))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    flat[0].save(args.out, save_all=True, append_images=flat[1:], duration=durations,
                 loop=0, optimize=True, disposal=1)
    kb = args.out.stat().st_size / 1024
    print(f"{len(take.frames)} pill frames at {take.k:g}x; {len(flat)} frames in the reel, "
          f"{sum(durations) / 1000:.1f} s, {flat[0].width}x{flat[0].height}, "
          f"{kb:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
