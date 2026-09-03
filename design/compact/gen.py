"""Generate the Flow, compact artboards. Pill/foot markup is shared so every frame agrees."""
from pathlib import Path

OUT = Path(__file__).resolve().parent

BG, SHELL, TEXT, MUTED, DIM = "#16181D", "#1A1D23", "#E6E8ED", "#949AA6", "#656B78"
CHIP, RING, RING_TOP, RING_OUTER, CODE, PLACEHOLDER = "#22262E", "#2E323B", "#3A404B", "#0B0D10", "#C7CBD4", "#7E8590"
HEARING, WAITING, ERROR, RECOVER = "#3ECF8E", "#7AA2F7", "#F2584A", "#E8A33D"
TYPE, REFINE, ASK = "#E6E8ED", "#E1B75C", "#B48EF5"
DIMBAR = {HEARING: HEARING, WAITING: WAITING, ERROR: "#4A2F2D", RECOVER: "#4A3C26", None: DIM}

HEAD = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <style>
    body { margin: 0; background: %(BG)s; font-family: "IBM Plex Sans", system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
    a { color: %(WAITING)s; } a:hover { color: #a8c1fa; }
    .h { font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase; color: %(DIM)s; font-family: "IBM Plex Mono", ui-monospace, monospace; margin: 0; }
    .cap { font-size: 12px; line-height: 16px; color: %(MUTED)s; margin: 0; text-wrap: pretty; }
    .lead { font-size: 15px; line-height: 21px; color: %(TEXT)s; margin: 0; text-wrap: pretty; }
    .body { font-size: 13px; line-height: 18px; color: %(TEXT)s; margin: 0; text-wrap: pretty; }
    .raw { font-size: 13px; line-height: 18px; color: %(PLACEHOLDER)s; margin: 0; text-wrap: pretty; }
    .mono { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; color: %(CODE)s; }
    .tag { font-size: 10px; letter-spacing: 1.4px; text-transform: uppercase; color: %(DIM)s; font-family: "IBM Plex Mono", ui-monospace, monospace; }
    .kbd { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 10px; color: %(PLACEHOLDER)s; border: 1px solid %(RING)s; border-radius: 4px; padding: 1px 5px; }
    .rule { height: 1px; background: %(RING)s; }
    .sw { width: 10px; height: 10px; border-radius: 5px; flex-shrink: 0; }
    .chip { height: 26px; padding: 0 12px; border-radius: 13px; background: %(CHIP)s; color: %(CODE)s; font-size: 12px; display: flex; align-items: center; gap: 6px; }
    .send { height: 26px; padding: 0 14px; border-radius: 13px; background: #EAECF1; color: #15171C; font-size: 12px; font-weight: 600; letter-spacing: .2px; display: flex; align-items: center; }
    /* the pill: one window, colour-keyed, no alpha - three hairlines instead of a shadow */
    .pill { height: 34px; width: 120px; box-sizing: border-box; border-radius: 17px; background: %(SHELL)s; border: 1px solid %(RING_OUTER)s;
            box-shadow: inset 0 1px 0 %(RING_TOP)s; display: flex; align-items: center; padding: 0 12px; gap: 9px; flex-shrink: 0; }
    /* docked under a panel: the top corners square off and the seam is one line, drawn by the panel */
    .foot { width: 100%%; border-radius: 0 0 17px 17px; border-top: 0; box-shadow: none; }
    .meter { display: flex; align-items: center; gap: 2px; height: 14px; flex-grow: 1; }
    .meter i { display: block; width: 2px; height: 3px; border-radius: 1px; background: %(DIM)s; }
    .shell { width: 400px; background: %(SHELL)s; border: 1px solid %(RING_OUTER)s; border-radius: 18px 18px 0 0; border-bottom: 1px solid %(RING)s; }
    .strip { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-bottom: 1px solid %(RING)s; background: #15181D; border-radius: 17px 17px 0 0; }
    .wsname { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 11px; color: %(CODE)s; letter-spacing: .2px; }
    .wsnote { font-size: 11px; color: %(DIM)s; margin-left: auto; }
    .stack { width: 400px; display: flex; flex-direction: column; }
  </style>
</helmet>
""" % dict(BG=BG, SHELL=SHELL, TEXT=TEXT, MUTED=MUTED, DIM=DIM, CHIP=CHIP, RING=RING, RING_TOP=RING_TOP,
           RING_OUTER=RING_OUTER, CODE=CODE, PLACEHOLDER=PLACEHOLDER, WAITING=WAITING)

TAIL = """</x-dc>
</body>
</html>
"""

HEAR = [5, 9, 14, 8, 12, 6, 11, 14, 7, 10, 4, 8, 13, 6, 3]


def mic(color, size=1.0, slash=False):
    w, h = round(14 * size, 1), round(18 * size, 1)
    s = '<path d="M1.6 1.8 12.4 16.2"></path>' if slash else ""
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 14 18" fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round">'
            f'<rect x="4.3" y="1.2" width="5.4" height="9.6" rx="2.7"></rect>'
            f'<path d="M1.8 8.4a5.2 5.2 0 0 0 10.4 0"></path><path d="M7 13.6V16.4"></path>{s}</svg>')


def bars(state=None, heights=None, n=15, lit=None):
    """`lit` = how many leading bars carry the state colour (the blue left-to-right run)."""
    out = []
    for i in range(n):
        h = heights[i % len(heights)] if heights else 3
        if state is None:
            c = DIM
        elif lit is not None:
            c = state if i < lit else "#333B49"
        else:
            c = DIMBAR[state]
        out.append(f'<i style="height:{h}px; background:{c}"></i>')
    return "".join(out)


def pill(mode=TYPE, state=None, heights=None, foot=False, n=15, lit=None, slash=False, extra=""):
    ring = f"box-shadow: inset 0 1px 0 {RING_TOP}, 0 0 0 1px {state}" if state and not foot else ""
    if foot and state:
        ring = f"box-shadow: 0 0 0 1px {state}"
    cls = "pill foot" if foot else "pill"
    return (f'<div class="{cls}" style="{ring}{extra}">{mic(mode if not slash else state)}'
            f'<div class="meter">{bars(state, heights, n, lit)}</div></div>')


def strip(ws="~/dev/products/flow", note="on mic-view", color=HEARING, empty=False):
    if empty:
        icon = (f'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="{DIM}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
                '<circle cx="8" cy="8" r="5.8"></circle><path d="M8 5.4v2.8M8 10.6h.01"></path></svg>')
        name = f'<span class="wsname" style="color: {PLACEHOLDER}">{ws}</span>'
    else:
        icon = (f'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M1.8 4.2A1.4 1.4 0 0 1 3.2 2.8h3l1.4 1.7h4.2a1.4 1.4 0 0 1 1.4 1.4v6.3a1.4 1.4 0 0 1-1.4 1.4H3.2a1.4 1.4 0 0 1-1.4-1.4z"></path></svg>')
        name = f'<span class="wsname">{ws}</span>'
    close = (f'<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="{DIM}" stroke-width="1.4" stroke-linecap="round">'
             '<path d="M4 4l8 8M12 4l-8 8"></path></svg>')
    return f'<div class="strip">{icon}{name}<span class="wsnote">{note}</span>{close}</div>'


COPY_ICON = (f'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="{MUTED}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
             '<rect x="5.5" y="5.5" width="8.2" height="8.2" rx="1.8"></rect>'
             '<path d="M10.5 5.5V4a1.6 1.6 0 0 0-1.6-1.6H3.9A1.6 1.6 0 0 0 2.3 4v5a1.6 1.6 0 0 0 1.6 1.6h1.6"></path></svg>')
FOLDER = lambda c: (f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="{c}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
                    '<path d="M1.8 4.2A1.4 1.4 0 0 1 3.2 2.8h3l1.4 1.7h4.2a1.4 1.4 0 0 1 1.4 1.4v6.3a1.4 1.4 0 0 1-1.4 1.4H3.2a1.4 1.4 0 0 1-1.4-1.4z"></path></svg>')


def row(left, text, gap=18):
    return (f'<div style="display: flex; align-items: center; gap: {gap}px">{left}'
            f'<div style="display: flex; align-items: center; gap: 9px; flex-grow: 1">{text}</div></div>')


def legend(color, text):
    return f'<div class="sw" style="background: {color}"></div><p class="cap" style="margin: 0">{text}</p>'


def section(title, *parts, gap=14):
    return (f'<div style="display: flex; flex-direction: column; gap: {gap}px"><p class="h">{title}</p>'
            + "".join(parts) + "</div>")


def page(*blocks, pad="36px 34px", gap=28):
    return HEAD + f'<div style="padding: {pad}; display: flex; flex-direction: column; gap: {gap}px">' + \
        '<div class="rule"></div>'.join(blocks) + "</div>" + TAIL


# ---------------------------------------------------------------- Main
main = page(
    '<div style="display: flex; flex-direction: column; gap: 8px">'
    '<p class="h">1 &nbsp;&middot;&nbsp; Mini mic</p>'
    '<p class="lead">Hold the pill. Speak. Let go.</p>'
    '<p class="cap">Nothing written on it. The glyph says which of the three things you are doing; the ring says what Flow is doing right now. 120 &times; 34.</p>'
    '</div>',

    section("Which of the three &mdash; the glyph",
        '<div style="display: flex; flex-direction: column; gap: 16px">'
        + row(pill(TYPE), legend(TYPE, "<b style=\"color:#E6E8ED; font-weight:500\">Type</b>&nbsp; lands in the window you were in. No panel, no CLI."))
        + row(pill(REFINE), legend(REFINE, "<b style=\"color:#E6E8ED; font-weight:500\">Refine</b>&nbsp; comes back shaped for the repo, in a panel, for you to send."))
        + row(pill(ASK), legend(ASK, "<b style=\"color:#E6E8ED; font-weight:500\">Ask</b>&nbsp; comes back to you as an answer."))
        + '</div>',
        '<div style="display: flex; align-items: center; gap: 8px">'
        '<span class="kbd">tap</span><p class="cap">cycles Type &rarr; Refine &rarr; Ask.</p>'
        '<span class="kbd" style="margin-left: 6px">right-click</span><p class="cap">picks one by name. It stays where you left it.</p>'
        '</div>'),

    section("What Flow is doing &mdash; the ring",
        '<div style="display: flex; flex-direction: column; gap: 16px">'
        + row(pill(REFINE, HEARING, HEAR), legend(HEARING, "Hearing you. The meter is the only motion."))
        + row(pill(REFINE, WAITING, lit=4), legend(WAITING, "The CLI has it. The meter fills left to right."))
        + row(pill(REFINE, ERROR, slash=True), legend(ERROR, "Something is wrong. The panel says what."))
        + row(pill(REFINE), legend(DIM, "No ring &mdash; resting. Grey claims no state."))
        + '</div>'),

    section("Where the panel goes",
        '<div style="display: flex; align-items: flex-end; gap: 28px">'
        '<div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start">'
        + pill(REFINE)
        + '<p class="cap">Type mode, or any mode at rest: the pill alone.</p></div>'
        '<div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start; flex-grow: 1">'
        '<div style="width: 100%; display: flex; flex-direction: column">'
        f'<div style="background: {SHELL}; border: 1px solid {RING_OUTER}; border-bottom: 1px solid {RING}; border-radius: 18px 18px 0 0; height: 96px; display: flex; flex-direction: column; justify-content: flex-end; padding: 12px 14px; gap: 5px">'
        f'<div style="height: 6px; width: 78%; border-radius: 3px; background: {RING}"></div>'
        f'<div style="height: 6px; width: 92%; border-radius: 3px; background: {RING}"></div>'
        f'<div style="height: 6px; width: 55%; border-radius: 3px; background: {RING}"></div>'
        '</div>'
        + pill(REFINE, foot=True, n=40)
        + '</div>'
        '<p class="cap">Refine or Ask: the panel rises above the pill and the pill becomes its foot &mdash; one window, one seam.</p></div>'
        '</div>',
        '<p class="cap">The foot is still the pill. Hold it again to say more or to reply. Send, Esc, or a click anywhere else closes the panel, and the pill is 120 wide again. It never hides and never moves.</p>'),

    section("Actual size",
        '<div style="height: 76px; display: flex; align-items: center"><div style="transform: scale(2); transform-origin: left center">'
        + pill(REFINE, HEARING, [6, 11, 14, 7, 12, 5, 10, 14, 8, 9, 4, 7, 13, 6, 3])
        + '</div></div>',
        '<p class="cap">Drawn at 2&times; here. Drag it anywhere; it never takes focus.</p>'),
)

# ---------------------------------------------------------------- Refine
bullet = lambda t: (f'<div style="display: flex; gap: 8px; align-items: baseline"><span style="width: 3px; height: 3px; border-radius: 2px; background: {DIM}; flex-shrink: 0; transform: translateY(-3px)"></span>'
                    f'<p class="body">{t}</p></div>')

refine = page(
    '<div style="display: flex; flex-direction: column; gap: 8px">'
    '<p class="h">2 &nbsp;&middot;&nbsp; Refine, against your repo</p>'
    '<p class="lead">The prompt comes back knowing where it is going.</p>'
    '<p class="cap">Flow already holds a workspace. The CLI is handed that repo as its system role, so this is not generic tidying &mdash; it names your files, your commands, your vocabulary.</p>'
    '</div>',

    '<div class="stack">'
    '<div class="shell">'
    + strip()
    + f'<div style="padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 6px; border-bottom: 1px solid {RING}">'
    '<span class="tag">heard</span>'
    '<p class="raw">make the pill not show any controls just the mic and when i let go it should paste in the window i was in before and also update the doc</p>'
    '</div>'
    '<div style="padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 10px">'
    f'<span class="tag" style="color: {REFINE}">refined for this repo</span>'
    '<p class="body">Strip every control from the push-to-talk pill in <span class="mono">flow/ui.py</span> &mdash; leave the mic glyph and the meter.</p>'
    '<div style="display: flex; flex-direction: column; gap: 6px">'
    + bullet('On release, inject the draft into the window that held focus before the pill (<span class="mono">flow/inject.py</span>), not the clipboard.')
    + bullet('Keep the 34 px height and the <span class="mono">PILL_HOLD_SEC</span> threshold as they are.')
    + bullet('Update <span class="mono">docs/product.md</span> to match.')
    + '</div></div>'
    '<div style="padding: 0 16px 14px; display: flex; align-items: center; gap: 8px">'
    f'<div class="chip">{COPY_ICON}Copy</div>'
    '<p class="cap" style="font-size: 11px">hold the mic to say more</p>'
    '<div style="margin-left: auto"><div class="send">Send</div></div>'
    '</div></div>'
    + pill(REFINE, foot=True, n=40)
    + '</div>'
    '<p class="cap" style="width: 400px">Send pastes it into the window you were in and closes the panel. Copy leaves the panel up.</p>',

    section("Spoken punctuation, resolved",
        '<p class="cap">You say the key; the text carries the shape. This part is local, so Type mode gets it too, with no CLI.</p>'
        '<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px">'
        f'<div style="background: {SHELL}; border: 1px solid {RING}; border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 5px">'
        '<span class="tag">said</span><p class="raw" style="font-size: 12px">&hellip; press enter press enter then tab dash fix the tests</p></div>'
        f'<div style="background: {SHELL}; border: 1px solid {RING}; border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 5px">'
        f'<span class="tag" style="color: {REFINE}">pasted</span><p class="mono" style="margin: 0; line-height: 17px; white-space: pre-line">&hellip;\n\n    - fix the tests</p></div>'
        '</div>'),
)

# ---------------------------------------------------------------- Ask
card = lambda inner, color=ASK: f'<div style="border-left: 2px solid {color}; padding-left: 12px; display: flex; flex-direction: column; gap: 6px">{inner}</div>'

ask = page(
    '<div style="display: flex; flex-direction: column; gap: 8px">'
    '<p class="h">3 &nbsp;&middot;&nbsp; Ask</p>'
    '<p class="lead">Speak a question. It answers about this repo &mdash; or, with no workspace, about anything.</p>'
    '<p class="cap">Same pill, same hold. The only difference is that the answer comes back to you instead of into the window you were typing in.</p>'
    '</div>',

    '<div class="stack">'
    '<div class="shell">'
    + strip(note="grounded")
    + '<div style="padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 12px">'
    '<p class="body">Where does the pill decide it was a hold and not a tap?</p>'
    + card('<p class="body"><span class="mono">PILL_HOLD_SEC</span> in <span class="mono">flow/ui.py</span> &mdash; 0.30&nbsp;s, with a 4&nbsp;px drag slop beside it so a nudge while holding is not read as a move.</p>'
           '<p class="body">Anything shorter is a tap, which now cycles the mode.</p>')
    + '</div>'
    '<div style="padding: 0 16px 14px; display: flex; align-items: center; gap: 8px">'
    f'<div class="chip">{COPY_ICON}Copy</div>'
    '<p class="cap" style="font-size: 11px">hold the mic to reply</p>'
    '</div></div>'
    + pill(ASK, foot=True, n=40)
    + '</div>'
    '<p class="cap" style="width: 400px">The thread lives in the panel. Esc, or a click anywhere else, closes it; the next hold starts fresh.</p>',

    section("No workspace set",
        '<div class="stack"><div class="shell">'
        + strip(ws="no workspace", note="plain talk with your CLI", empty=True)
        + '<div style="padding: 14px 16px; display: flex; flex-direction: column; gap: 12px">'
        '<p class="body">What is the difference between a mora-timed and a syllable-timed accent?</p>'
        + card('<p class="body">Mora-timed speech gives every mora roughly equal duration &mdash; Japanese counts a long vowel as two. Syllable-timed speech, like Spanish, spends that time per syllable instead&hellip;</p>', RING)
        + '</div></div>'
        + pill(ASK, foot=True, n=40)
        + '</div>',
        '<p class="cap">Nothing is broken without a repo. It is just a conversation, and the strip says so rather than hiding it.</p>'),
)

# ---------------------------------------------------------------- Workspace (right-click)
check = (f'<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="{HEARING}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
         '<path d="M3 8.4 6.6 12 13 4.8"></path></svg>')
blank = '<span style="width: 12px; height: 12px; display: block"></span>'


def mrow(icon, label, right="", bg=""):
    style = f' style="background: {bg}"' if bg else ""
    return (f'<div class="mrow"{style}>{icon}<span class="mtxt">{label}</span>'
            f'<span style="margin-left: auto" class="mhint">{right}</span></div>')


menu = (
    '<div class="menu">'
    + mrow(check, "Type", "", CHIP)
    + mrow(blank, "Refine")
    + mrow(blank, "Ask")
    + '<div class="msub">tap the pill to cycle</div>'
    '<div class="sep"></div>'
    + mrow(FOLDER(HEARING), "Switch workspace")
    + '<div class="msub">~/dev/products/flow</div>'
    '<div class="sep"></div>'
    + mrow((f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="{MUTED}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M2.6 11.8 8 6.4l1.6 1.6 3.8-3.8"></path><path d="M2.6 13.6h10.8"></path></svg>'), "Workbench setup")
    + '<div class="msub">mic, CLI, where it pastes</div>'
    '</div>'
)

MENU_CSS = f"""<style>
    .menu {{ width: 216px; background: {SHELL}; border: 1px solid {RING_OUTER}; border-radius: 10px; box-shadow: inset 0 1px 0 {RING_TOP}; padding: 5px 0; }}
    .mrow {{ display: flex; align-items: center; gap: 9px; padding: 7px 12px; }}
    .mtxt {{ font-size: 12px; color: {TEXT}; }}
    .mhint {{ font-size: 10px; color: {DIM}; }}
    .msub {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 11px; color: {DIM}; padding: 2px 12px 7px 33px; }}
    .sep {{ height: 1px; background: {RING}; margin: 4px 0; }}
    .box {{ width: 360px; background: {SHELL}; border: 1px solid {RING_OUTER}; border-radius: 18px; overflow: hidden; }}
    .field {{ display: flex; align-items: center; gap: 9px; padding: 12px 14px; border-bottom: 1px solid {RING}; }}
    .typed {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 13px; color: {TEXT}; }}
    .caret {{ width: 1px; height: 14px; background: {HEARING}; }}
    .row {{ display: flex; align-items: center; gap: 10px; padding: 9px 14px; }}
    .name {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; color: {CODE}; }}
    .hit {{ color: {TEXT}; background: rgba(62, 207, 142, .16); border-radius: 3px; }}
    .when {{ font-size: 11px; color: {DIM}; margin-left: auto; }}
  </style>"""


def wsrow(name_html, when, color=DIM, bg="", empty=False):
    style = f' style="background: {bg}"' if bg else ""
    if empty:
        icon = (f'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="{DIM}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
                '<circle cx="8" cy="8" r="5.8"></circle><path d="M8 5.4v2.8M8 10.6h.01"></path></svg>')
    else:
        icon = FOLDER(color).replace('width="14" height="14"', 'width="13" height="13"')
    w = f'<span class="when">{when}</span>' if when else ""
    return f'<div class="row"{style}>{icon}<span class="name">{name_html}</span>{w}</div>'


search_icon = (f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="{DIM}" stroke-width="1.4" stroke-linecap="round">'
               '<circle cx="7.2" cy="7.2" r="4.6"></circle><path d="M10.6 10.6 13.6 13.6"></path></svg>')

workspace = page(
    MENU_CSS +
    '<div style="display: flex; flex-direction: column; gap: 8px">'
    '<p class="h">Right-click the pill</p>'
    '<p class="lead">One menu. Mode, workspace, setup.</p>'
    '<p class="cap">There is no preferences window and no tray menu. The pill is the only thing you can right-click, and this is everything it offers.</p>'
    '</div>'
    '<div style="display: flex; align-items: flex-start; gap: 16px; margin-top: 14px">' + pill(TYPE) + menu + '</div>',

    section("Switch workspace",
        '<div class="box">'
        f'<div class="field">{search_icon}<span class="typed">flo</span><span class="caret"></span></div>'
        '<div style="padding: 6px 0 8px; display: flex; flex-direction: column">'
        + wsrow('~/dev/products/<span class="hit">flo</span>w', "today", HEARING, CHIP)
        + wsrow('~/dev/products/<span class="hit">flo</span>w-lite-notes', "Tue")
        + wsrow('~/work/river<span class="hit">flo</span>w', "Aug 21")
        + wsrow(f'<span style="color: {PLACEHOLDER}">No workspace &mdash; just talk</span>', "", empty=True)
        + '</div>'
        f'<div style="display: flex; align-items: center; gap: 8px; padding: 9px 14px; border-top: 1px solid {RING}">'
        '<span class="kbd">&crarr;</span><span class="cap" style="font-size: 11px">set</span>'
        '<span class="kbd" style="margin-left: 6px">esc</span><span class="cap" style="font-size: 11px">leave it</span>'
        '</div></div>',
        '<p class="cap">Type a few letters, take the top hit. Closed by choosing. Any folder you have ever pointed Flow at is in the list; a new one is typed as a path.</p>'),

    section("Workbench setup",
        '<div class="box">'
        f'<div class="row" style="border-bottom: 1px solid {RING}; padding: 12px 14px">'
        f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="{HEARING}" stroke-width="1.4" stroke-linecap="round"><rect x="5" y="1.6" width="6" height="9" rx="3"></rect><path d="M2.4 8.2a5.6 5.6 0 0 0 11.2 0"></path></svg>'
        f'<span class="mtxt">Microphone</span><span class="when" style="color: {MUTED}">Yeti Nano</span></div>'
        f'<div class="row" style="border-bottom: 1px solid {RING}; padding: 12px 14px">'
        f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="{HEARING}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5.6 6.8 8 4 10.4M8.6 10.8h3.4"></path><rect x="1.6" y="2.6" width="12.8" height="10.8" rx="2"></rect></svg>'
        f'<span class="mtxt">Agent CLI</span><span class="when" style="color: {MUTED}">claude</span></div>'
        '<div class="row" style="padding: 12px 14px">'
        f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="{MUTED}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.6v8M4.6 7.2 8 10.6l3.4-3.4"></path><path d="M2.6 13.4h10.8"></path></svg>'
        f'<span class="mtxt">On release</span><span class="when" style="color: {MUTED}">paste into last window</span></div>'
        '</div>',
        '<p class="cap">Three lines, each already answered by what Flow found on the machine. Open it when something is wrong; otherwise never.</p>'),
)

# ---------------------------------------------------------------- States
CASE_CSS = f"""<style>
    .case {{ display: flex; flex-direction: column; gap: 9px; padding: 14px 16px; background: {SHELL}; border: 1px solid {RING}; border-radius: 12px; }}
    .when {{ font-size: 11px; letter-spacing: 1.4px; text-transform: uppercase; color: {DIM}; font-family: "IBM Plex Mono", ui-monospace, monospace; }}
    .said {{ font-size: 13px; line-height: 18px; color: {TEXT}; margin: 0; text-wrap: pretty; }}
    .does {{ font-size: 12px; line-height: 17px; color: {MUTED}; margin: 0; text-wrap: pretty; }}
    .act {{ height: 24px; padding: 0 11px; border-radius: 12px; background: {CHIP}; color: {CODE}; font-size: 11px; display: flex; align-items: center; flex-shrink: 0; }}
  </style>"""


def case(when, p, said, does, act=""):
    a = f'<div class="act">{act}</div>' if act else ""
    return (f'<div class="case"><span class="when">{when}</span>'
            f'<div style="display: flex; align-items: center; gap: 12px">{p}<p class="said" style="flex-grow: 1">{said}</p></div>'
            f'<div style="display: flex; align-items: center; gap: 8px"><p class="does" style="flex-grow: 1">{does}</p>{a}</div></div>')


states = page(
    CASE_CSS +
    '<div style="display: flex; flex-direction: column; gap: 8px">'
    '<p class="h">When it cannot do the thing</p>'
    '<p class="lead">Every fallback keeps the words you already said.</p>'
    '<p class="cap">The rule under all of these: Type never depends on the CLI, and nothing you spoke is thrown away because a later step failed. The ring goes red; the panel says the one sentence that explains it and offers the one thing left to do.</p>'
    '</div>'
    '<div style="display: grid; grid-template-columns: repeat(1, minmax(0, 1fr)); gap: 12px; margin-top: 18px">'
    + case("No agent CLI on PATH", pill(TYPE),
           "Type still works. Refine and Ask are simply not offered &mdash; tapping does not cycle to them.",
           f'Grey, not red: a smaller Flow, not a broken one. Workbench setup shows <span class="mono">Agent CLI &mdash; none found</span> and takes a path.')
    + case("Microphone blocked or unplugged", pill(TYPE, ERROR, slash=True),
           "No input device. Holding does nothing but say so.",
           "The one case where the pill refuses the gesture outright, because pretending to listen is worse.", "Open sound settings")
    + case("Held, but nothing was said", pill(TYPE),
           "Straight back to grey. No panel, no toast, no apology.",
           "Silence is a normal thing to do with a push-to-talk button.")
    + case("Refine failed or took too long", pill(REFINE, ERROR, slash=True),
           "The panel opens holding the raw dictation, exactly as heard.",
           "The CLI's own last line is the message, not a generic failure. Send is still there: unrefined text beats no text.", "Try again")
    + case("Workspace moved or deleted", pill(TYPE, RECOVER),
           'Amber once, at launch: <span class="mono">~/work/riverflow</span> is gone.',
           "It falls back to no workspace rather than refining against a path that no longer exists.", "Pick another")
    + case("Cannot type into the window (Lite, macOS and Linux)", pill(TYPE, HEARING, [8, 12, 6, 10, 4, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3]),
           'The text lands on the clipboard and a line under the pill says <span class="mono">copied &mdash; press Ctrl+V</span>.',
           "Not an error state. It is the last inch of the same flow, done by you instead of by Flow.")
    + '</div>',
)

for name, html in [("Main", main), ("Refine", refine), ("Ask", ask), ("Workspace", workspace), ("States", states)]:
    (OUT / f"{name}.dc.html").write_text(html, encoding="utf-8")
    print(name, len(html))
