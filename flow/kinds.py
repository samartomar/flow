"""What Refine writes, decided by where the words are going.

Refine had one voice. Whatever was dictated came back as "a clear prompt for an AI coding
assistant", because that is the request this product was built around - and it is the
wrong answer to most of what people dictate. Measured on 2026-11-22 through `claude`, an
email spoken in the ordinary way ("I need to write to Priya about the release ... ask her
to let the QA team know") came back as *"Write a message to Priya proposing that we move
the release..."*: a prompt asking somebody else to write the email. The brief was obeyed
exactly, which is the proof it was the wrong brief for that window.

So Refine has **kinds**: a prompt, an email, a chat message, or the same words tidied up.
The kind is chosen from the window the words are headed for, because that is the one fact
about the text Flow already has before anything is spoken - `inject.classify` has named
the foreground process on every paste since P7, and nothing was using it for this.

Three rules decide the design, and each one is a failure seen in the field survey of
2026-11-22 (every comparable tool picks its behaviour from the focused app, and the
complaint that follows them all is *edits that changed what I meant*):

**A wrong guess must cost little.** An app Flow does not recognise gets TIDY, the kind
that changes least: the same words, cleaned up, in the same order. Turning a ticket
comment into a "REQUEST / CONTEXT / CONSTRAINTS" prompt is a worse mistake than leaving a
prompt as clean prose, so the unknown case fails toward clean prose.

**No information is not the same as an unrecognised app.** Lite, `--no-paste` and a pill
that has not seen a foreground window yet have no destination at all, and there Refine
does what it has always done - a prompt. That keeps every install with no hands behaving
exactly as it did.

**The title is read and never kept.** A browser is one process for mail, chat and an AI
tab alike, so the only way to tell them apart without a UI Automation dependency (R16)
is the window title, where the site puts its own name. It is matched here against a short
list of site names and then dropped: `diag.NEVER` already refuses `title` and `window`
as trace fields, history records the process name only, and nothing in this module
returns the title or any part of it.

Pure and platform-neutral on purpose. `inject.py` binds `user32` at import and cannot be
loaded on a Mac; this module is imported by the session on every platform, so it takes a
process name and a title as plain strings and knows nothing about where they came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PROMPT = "prompt"
EMAIL = "email"
MESSAGE = "message"
TIDY = "tidy"

#: The setting's fifth value: "work it out from the window". Never a kind a rewrite runs
#: as - `resolve` turns it into one of the four above before anything is sent.
AUTO = "auto"


@dataclass(frozen=True)
class Kind:
    key: str
    #: How Flow Home names it in a list: "Prompt", "Email".
    label: str
    #: With its article, for a sentence: "Refine writes *an email* here".
    noun: str
    #: What the note says while the CLI works: "*writing that as an email* via claude".
    doing: str
    #: What the panel says over the result, in the mode's gold.
    tag: str


KINDS: dict[str, Kind] = {
    PROMPT: Kind(PROMPT, "Prompt", "a prompt", "shaping that into a prompt",
                 "refined as a prompt"),
    EMAIL: Kind(EMAIL, "Email", "an email", "writing that as an email",
                "written as an email"),
    MESSAGE: Kind(MESSAGE, "Chat message", "a chat message",
                  "writing that as a chat message", "written as a chat message"),
    TIDY: Kind(TIDY, "Tidy up", "tidied text", "tidying that up", "tidied up"),
}

#: The order a picker offers them in: the product's first promise, then the two things
#: people write most, then the fallback.
ORDER: tuple[str, ...] = (PROMPT, EMAIL, MESSAGE, TIDY)


def get(key) -> Kind:
    """The kind called `key`, or PROMPT for anything that is not one.

    PROMPT rather than an error, for `_app_note`'s reason: a hand-edited profile, or a
    kind retired by a later version, must cost that one setting and not the rewrite.
    """
    return KINDS.get(key if isinstance(key, str) else "", KINDS[PROMPT])


def valid(key) -> bool:
    return isinstance(key, str) and key in KINDS


# -- where the words are going ----------------------------------------------------------
#
# Matched by process name, lowercase, the way `inject.TERMINAL_PROCESSES` and
# `inject.EDITOR_HOSTS` are. A missing program costs that program the right guess until
# somebody sets it in Flow Home; an entry for a program nobody has installed costs
# nothing. The lists are the common cases on Windows, not a census.

#: Terminals. A dictation into a shell is a prompt for the agent CLI running in it - the
#: product's own first scenario - and never an email. Repeated from `inject` rather than
#: imported: that module cannot be loaded off Windows, and the two lists answer different
#: questions (what is safe to paste; what is being written), so they may drift apart on
#: purpose.
_TERMINALS = frozenset({
    "windowsterminal.exe", "wt.exe", "conhost.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "mintty.exe", "bash.exe", "alacritty.exe", "wezterm-gui.exe",
    "kitty.exe", "hyper.exe", "conemu64.exe", "conemu.exe", "cmder.exe", "warp.exe",
    "tabby.exe", "wsl.exe", "ubuntu.exe",
})

#: Editors with an agent chat in them, and the AI apps themselves.
_AI_APPS = frozenset({
    # VS Code and its forks, JetBrains: what is dictated there is overwhelmingly a
    # message to the assistant panel. A code comment or a commit message is the minority
    # case, and "make it tidy" is one sentence away.
    "code.exe", "code - insiders.exe", "codium.exe", "vscodium.exe", "cursor.exe",
    "windsurf.exe", "positron.exe", "trae.exe", "kiro.exe", "zed.exe", "antigravity.exe",
    "idea64.exe", "idea.exe", "pycharm64.exe", "pycharm.exe", "webstorm64.exe",
    "webstorm.exe", "rider64.exe", "rider.exe", "goland64.exe", "goland.exe",
    "clion64.exe", "clion.exe", "phpstorm64.exe", "phpstorm.exe", "rubymine64.exe",
    "rubymine.exe", "datagrip64.exe", "datagrip.exe", "dataspell64.exe",
    "rustrover64.exe", "fleet.exe", "studio64.exe", "devenv.exe",
    # The assistants' own desktop apps.
    "chatgpt.exe", "claude.exe", "codex.exe", "copilot.exe", "gemini.exe",
    "perplexity.exe", "lm studio.exe", "lmstudio.exe", "msty.exe", "jan.exe",
    "ollama app.exe", "poe.exe", "grok.exe",
})

_MAIL_APPS = frozenset({
    "outlook.exe", "olk.exe", "hxoutlook.exe", "thunderbird.exe", "betterbird.exe",
    "mailspring.exe", "mailbird.exe", "mailclient.exe", "superhuman.exe",
    "spark desktop.exe", "postbox.exe", "protonmail.exe", "proton mail.exe",
    "bluemail.exe", "zohomail.exe",
})

_CHAT_APPS = frozenset({
    "slack.exe", "teams.exe", "ms-teams.exe", "msteams.exe", "discord.exe",
    "discordcanary.exe", "discordptb.exe", "whatsapp.exe", "whatsapp.root.exe",
    "telegram.exe", "signal.exe", "element.exe", "mattermost.exe", "zulip.exe",
    "rocket.chat.exe", "wechat.exe", "weixin.exe", "line.exe", "viber.exe",
    "skype.exe", "lark.exe", "feishu.exe", "dingtalk.exe", "webex.exe",
    "ciscocollabhost.exe", "beeper.exe", "messenger.exe", "googlechat.exe",
})

#: One process for every site, so these are judged by the title instead.
_BROWSERS = frozenset({
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "opera_gx.exe", "vivaldi.exe", "arc.exe", "zen.exe", "librewolf.exe",
    "waterfox.exe", "chromium.exe", "thorium.exe", "floorp.exe", "dia.exe",
    "comet.exe", "duckduckgo.exe", "iexplore.exe", "safari.exe",
})

#: Site names as they appear as a *whole segment* of a window title.
#:
#: A browser title is the page's own title with the browser's name after it, and a site
#: puts its name in a segment of its own: `Inbox (3) - you@example.com - Gmail - Google
#: Chrome`, `Mail - A Name - Outlook - Microsoft Edge`, `general (Channel) - Acme - Slack
#: - Mozilla Firefox`, `Fix the flaky test - Claude - Brave`. Matching whole segments
#: rather than searching the title is what keeps an article called "How Claude handles
#: email in Outlook" a document and not three destinations at once: none of its segments
#: *is* a site name.
#:
#: Only names that are a product's own are listed. "Chat", "Messages", "Teams" and "X"
#: are also what a page that is none of those calls a section of itself, and a generic
#: word as a whole segment is exactly as wrong as a search would have been.
#:
#: What this cannot see is a site that titles its tab with the page alone - ChatGPT names
#: a conversation's tab after the conversation, with nothing after it. Those read as an
#: unrecognised page and get TIDY, which leaves a prompt as clean prose: the cheap
#: failure, by the module's first rule. The cure is the per-app setting, not a longer
#: list.
_MAIL_SITES = frozenset({
    "gmail", "outlook", "outlook.com", "proton mail", "protonmail", "yahoo mail",
    "fastmail", "zoho mail", "icloud mail", "superhuman", "tuta mail", "tutanota",
    "aol mail", "gmx", "mail.com", "hotmail", "roundcube webmail", "missive",
    "shortwave",
})

_CHAT_SITES = frozenset({
    "slack", "microsoft teams", "discord", "whatsapp", "whatsapp web", "telegram",
    "telegram web", "messenger", "google chat", "mattermost", "zulip", "rocket.chat",
    "linkedin messaging", "google messages", "messages for web", "webex",
})

_AI_SITES = frozenset({
    "chatgpt", "claude", "gemini", "google gemini", "copilot", "microsoft copilot",
    "github copilot", "perplexity", "grok", "deepseek", "le chat", "mistral",
    "poe", "v0", "bolt", "bolt.new", "lovable", "replit", "google ai studio",
    "ai studio", "notebooklm", "codex", "cursor", "devin", "meta ai", "kagi assistant",
    "duck.ai", "huggingchat", "openrouter", "t3 chat", "phind", "you.com", "manus",
    "jules", "kiro", "windsurf", "lm studio", "open webui", "librechat",
})

#: The separators a title is built with: a spaced hyphen, en dash, em dash, pipe or
#: middle dot. Spaced, because an unspaced hyphen is part of a word ("co-worker").
_SEGMENT = re.compile(r"\s+[-–—|·]\s+")

#: The unread counter some sites put in front of their own name: `(2) WhatsApp`.
_COUNTER = re.compile(r"^[(\[]\d[\d,+.]*[)\]]\s*")

#: A prefix a site adds to its name on some pages: `Microsoft Copilot: Your AI companion`.
_SUBTITLE = re.compile(r"\s*[:–—]\s.*$")

#: What Edge adds to the active tab's title when a window has others: `Outlook and 4
#: more pages`. Taken off before a segment is compared, or every Edge window with more
#: than one tab would be a page Flow does not recognise.
_MORE_PAGES = re.compile(r"\s+and \d+ more (?:pages?|tabs?)$")

#: Sites that are *about* other things. One of these nearer the browser's name than a
#: mail, chat or AI name means the title is a page of this site and the other name is
#: its subject: `Gmail - Wikipedia`, `slack - Google Search`. Short, because it only
#: has to cover where people look things up.
_ABOUT_OTHERS = frozenset({
    "wikipedia", "google search", "bing", "microsoft bing", "search", "duckduckgo",
    "youtube", "reddit", "github", "stack overflow", "hacker news", "google docs",
    "google sheets", "google drive", "linkedin", "medium", "substack", "amazon",
    "google play", "app store", "microsoft store", "chrome web store", "reuters",
})


def _segments(title: str) -> list[str]:
    """The pieces of a window title, lowercased, with counters and subtitles off."""
    out = []
    for piece in _SEGMENT.split(title or ""):
        piece = _COUNTER.sub("", piece.strip()).strip().lower()
        piece = _MORE_PAGES.sub("", piece).strip()
        if piece:
            out.append(piece)
            head = _SUBTITLE.sub("", piece).strip()
            # Only a name of more than one word may carry a subtitle. `Microsoft
            # Copilot: Your AI companion` is the site naming itself; `Outlook: stocks
            # slide` is a headline that begins with a word, and a single word before a
            # colon is how most headlines begin.
            if head and head != piece and " " in head:
                out.append(head)
    return out


def _site(title: str) -> str | None:
    """Which kind a browser tab's title names, or None when it names none.

    By position: the walk runs from the end of the title backwards, because a site
    puts its own name nearest the browser's, and the first name it meets decides. A
    mail tab open on a message about Slack is `... Slack ... - Gmail - Chrome`, and
    Gmail is met first.

    A site that is about other things ends the walk with no answer (`_ABOUT_OTHERS`):
    past it, any name is the page's subject and not where the words are going.
    """
    for piece in reversed(_segments(title)):
        if piece in _ABOUT_OTHERS or piece.endswith(" search"):
            return None
        if piece in _MAIL_SITES:
            return EMAIL
        if piece in _CHAT_SITES:
            return MESSAGE
        if piece in _AI_SITES:
            return PROMPT
    return None


def detect(app: str = "", title: str = "") -> str:
    """The kind of writing `app` is for, read from its process name and window title.

    `app` is `inject.Target.process` - an executable's file name - and "" when there is
    no destination to speak of, which is Lite, `--no-paste`, and the moment before the
    pill has seen a foreground window. That case is PROMPT: no information means the
    behaviour Refine had before this module existed. A program that is *named* and not
    recognised is TIDY - see the module docstring for why those two differ.
    """
    name = app.strip().lower() if isinstance(app, str) else ""
    if not name:
        return PROMPT
    if name in _TERMINALS or name in _AI_APPS:
        return PROMPT
    if name in _MAIL_APPS:
        return EMAIL
    if name in _CHAT_APPS:
        return MESSAGE
    if name in _BROWSERS:
        return _site(title if isinstance(title, str) else "") or TIDY
    return TIDY


def resolve(app: str = "", title: str = "", table=None, default: str = AUTO) -> str:
    """The kind Refine will write for this window, with the user's own choices applied.

    Three answers in order, and the first one that exists wins:

    1. `table` - the profile's per-app choices, keyed by executable name the way the
       per-app instructions are. Somebody who has said "Notepad is where I draft email"
       has said the one thing detection can never know.
    2. `default`, when it names a kind - "always a prompt", for the person who uses Refine
       for nothing else and does not want it second-guessed.
    3. `detect`.

    Case-insensitive on the name for `_app_note`'s reason. A value that is not a kind is
    passed over rather than obeyed, so a typo in a hand-edited profile falls through to
    the next answer instead of to a kind nobody chose.
    """
    name = app.strip().lower() if isinstance(app, str) else ""
    if name and isinstance(table, dict):
        for exe, kind in table.items():
            if isinstance(exe, str) and exe.strip().lower() == name and valid(kind):
                return kind
    if valid(default):
        return default
    return detect(app, title)


def describe(kind: str, app: str = "") -> str:
    """What Refine will do here, for the one line the pill says when the mode changes.

    The program is named without its extension, the way `Pill.pinned_name` names it:
    "Refine - writes an email for outlook". With no destination it says only what it
    writes, because "for " followed by nothing is worse than no clause at all.
    """
    noun = get(kind).noun
    where = app.rsplit(".", 1)[0].strip() if isinstance(app, str) and app else ""
    return f"writes {noun} for {where}" if where else f"writes {noun}"


# -- what was asked for out loud ----------------------------------------------------------

#: Lead-ins a spoken request may open with. A small copy of `edits._LEAD`'s idea, kept
#: here so this module imports nothing: politeness is the half of a command an accent
#: leaves intact, and "can you make it an email" must not be dictated as words.
_ASK = (r"(?:(?:please|okay|ok|hey|so|now|actually|can you|could you|would you|"
        r"i want you to|i need you to|just|flow)[, ]+)*")

_IT = r"(?:it|this|that|these|those|the text|the draft|my text|my draft)"

#: What a request may trail off with. Required after a bare noun - "email" on its own is
#: a word somebody dictated, "email please" is not. Not "now": "reply now" and "email
#: now" are things people say *in* a message.
_PLEASE = r"(?:,? (?:please|instead|for me))"

_AS = {
    EMAIL: r"(?:an? )?(?:proper |short |quick |professional |formal |polite )?e-?mail",
    # "message" and "dm" stand alone; "text" needs its article. "Turn this into text",
    # "reply" and "chat" are ordinary words in ordinary dictation, and a restyle that
    # fired on them would rewrite somebody's sentence as a chat message.
    MESSAGE: (r"(?:(?:an? )?(?:short |quick )?(?:(?:slack|teams|discord|whatsapp|chat|"
              r"text|direct|instant) )?(?:message|dm)|a (?:short |quick )?text)"),
    PROMPT: r"(?:an? )?(?:proper |good |better |clear |real )?prompt",
}

_SPOKEN = [
    (kind, re.compile(
        "^" + _ASK + r"(?:"
        rf"(?:make|turn|convert|rewrite|write|format|put|do|redo) {_IT} "
        rf"(?:into |in to |as |like |to be |to )?{noun}{_PLEASE}?|"
        rf"(?:make|write|draft|do) (?:{_IT} )?{noun}(?: (?:out )?of {_IT})?{_PLEASE}?|"
        rf"(?:as|into|like) {noun}{_PLEASE}?|"
        rf"{noun}{_PLEASE}"
        r")[.!?]*$", re.I))
    for kind, noun in _AS.items()
]

_SPOKEN.append((TIDY, re.compile(
    "^" + _ASK + r"(?:"
    rf"(?:just )?(?:tidy|clean) {_IT}(?: up)?|"
    rf"(?:just )?(?:tidy|clean) up {_IT}|"
    r"(?:just )?(?:tidy|clean) (?:it )?up|"
    rf"(?:keep|leave) {_IT} as (?:it is|is|i said it)|"
    rf"(?:keep|leave) my (?:own )?words|"
    rf"(?:just )?fix (?:the )?(?:grammar|punctuation)(?: (?:in|of) {_IT})?"
    r")" + _PLEASE + r"?[.!?]*$", re.I)))


def spoken(utterance: str) -> str | None:
    """The kind an utterance asks for, when the whole of it is such a request.

    Whole-utterance only, the send trigger's rule (decisions.md 2026-08-01): "make it an
    email" is a command, and "I told him to make it an email if he preferred" is a
    sentence that happens to contain one. Anchored at both ends so the second never
    fires, which is the mistake that would be worst here - a dictated sentence swallowed
    and the result silently re-written as something else.

    Returns one of the four kinds, or None for anything that is dictation.
    """
    text = utterance.strip() if isinstance(utterance, str) else ""
    if not text or len(text) > 80:
        return None
    for kind, pattern in _SPOKEN:
        if pattern.match(text):
            return kind
    return None
