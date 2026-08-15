"""Which copy of Flow this is, and — only when somebody types the flag — whether there
is a newer one.

Two questions with one number between them, which is why they share a file. The number
is the one `pyproject.toml` carries and `release.yml` gates a tag against, read back out
of the installed metadata rather than copied into a `__version__` here: a second copy of
a version is a second thing to keep true, and the copy that goes stale is always the one
nobody re-reads.

**Nothing calls the check but the flag.** No timer, no startup call, no "there is an
update" bubble — `--check-update` runs once, when asked, and exits. That is not a
courtesy setting; it is what keeps `docs/architecture.md` § "What leaves the machine"
a complete list rather than an approximate one. A product whose privacy claim is an
enumeration cannot afford one path that phones home on its own schedule, because then
the enumeration is a description of the common case instead of a guarantee.

What goes out is the request and nothing else: no version number (the comparison happens
here, after the answer arrives), no query string, no token, no account. GitHub sees an
anonymous GET from an address, and a User-Agent that names the product and not the copy.

Stdlib `urllib`, for the reason R16 gives — three runtime dependencies, and an HTTP
client is not going to be the fourth.
"""

from __future__ import annotations

import re

#: What `version()` answers when there is nothing to read. It names what is absent and
#: not why, because from in here the two causes are indistinguishable: a source tree that
#: was never installed, and a frozen bundle built without `copy_metadata("flow")`. Short
#: enough that `flow --version` stays one line on a narrow console — argparse fills the
#: version text to the terminal width, so a long answer would arrive wrapped.
UNKNOWN = "unknown - no package metadata"

#: Where a newer copy comes from. The asset name is constant across releases so this link
#: is true forever (decisions.md, 2026-08-03) — which is exactly why "am I current?" is
#: the only question a download page cannot answer for you.
RELEASES_URL = "https://github.com/samartomar/flow/releases"

#: The one endpoint anything in Flow reaches on the user's behalf without a CLI in
#: between. Anonymous, so GitHub allows 60 an hour from one address — 59 more than a
#: check somebody types will ever want.
LATEST_URL = "https://api.github.com/repos/samartomar/flow/releases/latest"

#: How long somebody stands at a prompt for an answer they asked for. Long enough for a
#: handshake and a few KB of JSON on a working connection, short enough that a machine
#: with no route out says so instead of looking hung — which is the case worth being
#: quick about, because it is the one that happens on a plane rather than in a test.
TIMEOUT_SEC = 3.0

#: Required rather than decorative: GitHub's API answers a request with no User-Agent
#: with 403. It names the product and not this copy — no version, no identifier — because
#: the comparison happens on this machine after the answer arrives, so there is nothing
#: the request needs to say about who is asking.
USER_AGENT = "flow"

#: A tag, in the shape this project has ever cut one: `v0.5.1`. Matched before it is
#: echoed, not after. Whatever comes back is server-controlled text on its way to a
#: console that may be cp437 (see `__main__.say`), and a tag carrying an en-dash would
#: turn an answer into a UnicodeEncodeError — so anything outside this shape is refused
#: with a reason instead of printed.
_TAG = re.compile(r"v?(\d[0-9A-Za-z.+-]{0,31})\Z")

#: The leading dotted integers of a version, which are the whole of what decides newer.
_NUMBERS = re.compile(r"\d+(?:\.\d+)*")


def version() -> str:
    """This copy's version, or `UNKNOWN`. Never raises.

    `importlib.metadata` is not free and this is on the startup path: measured
    2026-08-14, importing it costs ~75 ms in a bare interpreter and the flag it feeds
    moved import-and-parse of `flow --help` from 352 ms to 405 ms — about 55 ms of a
    launch that puts the pill on screen in 0.40 s. Every launch pays it, because
    argparse's version action wants the string at the moment the parser is built, and
    nothing knows yet whether `--version` is what was typed. The import is in here
    rather than at the top so that the cost at least belongs to the call: `ui.py` loads
    this module too, for one row of the Help sheet.

    Every failure answers `UNKNOWN` rather than propagating: `--version` exists to answer
    a question, and a traceback is not an answer. Broad, and knowingly — a half-written
    `dist-info` raises things that are not `PackageNotFoundError`, and none of them are
    worth ending a launch over.
    """
    import importlib.metadata as md

    try:
        return md.version("flow")
    except Exception:
        return UNKNOWN


def _numbers(text: str) -> tuple[int, ...]:
    """`0.5.1` as `(0, 5, 1)`.

    Compared as numbers because text order gets it wrong at exactly the moment it starts
    to matter: `"0.10.0" < "0.5.1"` as strings, so a string comparison would tell the
    holder of 0.5.1 that 0.10.0 is not out yet. Anything past the numbers — an `rc1`, a
    build suffix — is ignored rather than refused; it decides nothing here, and a tag
    shaped a little differently is no reason to withhold the answer.
    """
    found = _NUMBERS.match(text)
    return tuple(int(part) for part in found.group(0).split(".")) if found else ()


def check_update() -> tuple[str, bool]:
    """One line for `--check-update`, and whether the check actually ran.

    Called by the flag and by nothing else — see the module docstring for why that is a
    property of this file rather than a habit.

    The bool is the exit code's business. "Nothing newer" and "no answer" are different
    facts and a script wrapping this has to be able to tell them apart, so the first is
    an exit of 0 and the second an exit of 1, both of them one calm line either way.

    Every reason is built out of literals and a tag that has been through `_TAG`, so the
    line survives a cp437 console whatever comes back off the wire. The catch-all at the
    end is the same promise one level wider: a `http.client` exception is not an `OSError`
    and would otherwise end a one-shot command in a traceback.
    """
    import json
    import urllib.error
    import urllib.request

    here = version()
    if here == UNKNOWN:
        return ("could not check for updates: this copy carries no package metadata, "
                "so there is no version to compare a release against"), False
    request = urllib.request.Request(LATEST_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as answer:
            body = json.loads(answer.read())
    except urllib.error.HTTPError as exc:
        # 403 is what an anonymous caller over the hourly allowance gets, and it is the
        # one HTTP answer worth translating: "forbidden" reads like a permissions problem
        # somebody has to fix, when the fix is to come back later.
        if exc.code in (403, 429):
            return ("could not check for updates: GitHub answered HTTP "
                    f"{exc.code} - rate-limited, so try again later"), False
        return f"could not check for updates: GitHub answered HTTP {exc.code}", False
    except OSError:
        # `URLError` and a read timeout are both `OSError`, and so is a TLS failure. The
        # reason is not interpolated: an OS error string is localised, and this line has
        # to encode on a legacy console code page.
        return ("could not check for updates: no answer from GitHub within "
                f"{TIMEOUT_SEC:.0f}s - offline, or blocked"), False
    except ValueError:
        # `json.JSONDecodeError` is a `ValueError`, and an HTML error page is the usual
        # way to get one here: a proxy or a captive portal answering instead of GitHub.
        return "could not check for updates: GitHub's answer was not JSON", False
    except Exception as exc:  # noqa: BLE001 - a one-shot must not end in a traceback
        return ("could not check for updates: the request failed "
                f"({type(exc).__name__})"), False

    tag = body.get("tag_name") if isinstance(body, dict) else None
    found = _TAG.match(tag) if isinstance(tag, str) else None
    if found is None:
        return ("could not check for updates: GitHub's answer carried no release "
                "number"), False

    newest = found.group(1)
    if _numbers(newest) > _numbers(here):
        return f"flow {newest} is out (you have {here}) - {RELEASES_URL}", True
    if _numbers(newest) < _numbers(here):
        # Ahead of the newest tag rather than behind it, which is what a working tree or
        # a bumped-but-untagged build looks like from here. Said plainly instead of
        # rounded to "you are up to date": the two are not the same fact, and the person
        # most likely to see this is the one who would notice.
        return (f"flow {here} is newer than the newest release ({newest}) - "
                "nothing to update to"), True
    return f"flow {here} is the newest release", True
