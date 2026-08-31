"""Paste into the app you were looking at, on macOS.

`inject.py` is Win32 to the bone — `SendInput`, `OpenClipboard`, window handles — and
none of it exists here. This is its opposite number, satisfying the same two-function
contract `__main__.on_send` is written against: `paste(text, submit=…) -> bool`, and
`take_warnings()` for the reasons behind a False.

**Why it had to exist.** Off Windows Flow ran in Lite, where Send copies the draft to the
clipboard and stops. That is a fine fallback and a poor product: the whole point is to
speak into the window you are already working in, and "now press Cmd-V yourself" is the
step Flow was built to remove. Everything else about the Mac was made to work first — the
window stays up, takes clicks, sits above the Dock — and the thing it all leads to still
handed you a clipboard.

**System Events rather than CGEvent, for now.** Posting a synthetic Cmd-V through
`CGEventPost` is faster and needs no `osascript` process, and it is where this should
eventually go — `native/flow_stt.swift` is already a compiled binary with a build step.
It is also an entitlement question and a second thing to be right about before anybody
could try this once. `osascript` is on every Mac, needs no dependency (R16 holds at
three) and asks the OS for the same permission the compiled route would.

**The permission is the thing that will actually bite.** Synthesising keystrokes needs
Accessibility, and macOS grants it to the *responsible* process — the terminal Flow was
started from, not Python and not Flow. Denied, System Events fails with `-1719` or `1002`
and does nothing at all, which from the user's side is indistinguishable from the Send
button being broken. So that case is detected by its error number and answered with the
exact path through System Settings, rather than left as a silent no-op (invariant 4).
"""

import subprocess
import threading
import time

#: How long the target app gets to read the clipboard before Flow puts the old contents
#: back. `inject.py`'s reasoning applies unchanged: the keystroke is queued, not waited
#: on, so restoring immediately would hand back the old text before the new text had been
#: read. The number is its number, for the same reason.
RESTORE_DELAY_SEC = 8.0

#: How long any one `osascript` call may take. Generous for a process that normally
#: answers in well under a second, and finite so a wedged System Events cannot hang the
#: send — the property `refine.sane_timeout` exists to protect, applied here too.
SCRIPT_TIMEOUT_SEC = 10.0

#: What System Events says when the terminal has not been granted Accessibility. `-1719`
#: is "not allowed assistive access" and `1002` is the keystroke-specific refusal; both
#: appear on stderr with the number in them. Matched on the numbers rather than the
#: prose, which is localised.
DENIED_CODES = ("-1719", "1002", "-25211")

#: Names a frontmost process can have when the thing in front is Flow itself. Flow
#: pasting into its own draft box is the one outcome that would destroy the text being
#: sent, and `ui._bare_window` is what should make it impossible — this is the belt to
#: that pair of braces.
FLOW_NAMES = ("python", "python3", "flow", "tk", "wish")

#: Warnings from the last paste, drained by the UI. A module-level queue for `inject.py`'s
#: reason: `paste` already returns success, and a caller that ignores the warning must
#: still see it. Locked because the restore runs on its own thread.
_warnings: list[str] = []
_lock = threading.Lock()


def _warn(line: str) -> None:
    with _lock:
        _warnings.append(line)


def take_warnings() -> list[str]:
    with _lock:
        out, _warnings[:] = list(_warnings), []
    return out


def _run(argv: list[str], stdin: str | None = None) -> tuple[bool, str]:
    """One child process. Returns `(ok, output-or-reason)` and never raises.

    A send that dies on an OSError from a helper nobody has heard of is worse than one
    that reports what it could not do, so everything below treats failure as a sentence
    to show the user rather than an exception to propagate.
    """
    try:
        done = subprocess.run(
            argv, input=stdin, capture_output=True, text=True,
            timeout=SCRIPT_TIMEOUT_SEC, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        return False, f"{argv[0]} would not start: {exc}"
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} did not answer in {SCRIPT_TIMEOUT_SEC:.0f}s"
    if done.returncode != 0:
        return False, (done.stderr or done.stdout or "").strip() or f"{argv[0]} failed"
    return True, done.stdout or ""


def denied(reason: str) -> bool:
    return any(code in reason for code in DENIED_CODES)


def permission_note() -> str:
    """The one message worth getting right, because it is the only one most people see.

    Names the terminal rather than Flow or Python, because that is what the permission is
    actually attached to — macOS assigns it to the responsible process — and looking for
    "Flow" in that list is a dead end.
    """
    return ("not pasted: macOS has not granted permission to send keystrokes. Open "
            "System Settings > Privacy & Security > Accessibility and switch on the "
            "terminal you started Flow from, then try again. The text is on the "
            "clipboard, so Cmd-V works in the meantime.")


def frontmost() -> str:
    """The name of the app that will receive the paste, or "" if it cannot be asked."""
    ok, out = _run(["osascript", "-e",
                    'tell application "System Events" to get name of first process '
                    "whose frontmost is true"])
    return out.strip() if ok else ""


def get_clipboard_text() -> str | None:
    ok, out = _run(["pbpaste"])
    return out if ok else None


def set_clipboard_text(text: str) -> bool:
    """`pbcopy` rather than Tk's clipboard, and the difference matters.

    Tk owns its selection for as long as the interpreter lives and serves it on request,
    so a draft copied that way disappears the moment Flow exits. `pbcopy` hands the text
    to the pasteboard server, where it behaves like anything else you have ever copied.
    """
    ok, reason = _run(["pbcopy"], stdin=text)
    if not ok:
        _warn(f"could not reach the clipboard: {reason}")
    return ok


def _restore_later(previous: str | None) -> None:
    """Put the old clipboard back, once the paste has had time to happen.

    A daemon thread, so quitting Flow between the paste and the restore does not hold the
    process open. The cost of losing the restore is the draft staying on the clipboard,
    which is the state Lite mode leaves it in anyway.
    """
    if previous is None:
        return

    def worker() -> None:
        time.sleep(RESTORE_DELAY_SEC)
        _run(["pbcopy"], stdin=previous)

    threading.Thread(target=worker, name="flow-clipboard-restore", daemon=True).start()


def paste(
    text: str,
    *,
    hwnd: int | None = None,
    restore_clipboard: bool = True,
    submit: bool = False,
) -> bool:
    """Put `text` on the clipboard and send Cmd-V to whatever is frontmost.

    `hwnd` exists for the signature `__main__.on_send` is written against and is ignored:
    macOS has no window handle to aim at, and it does not need one. Flow's own windows are
    built without the `titled` bit and never take focus (`ui._bare_window`), so the app
    that was frontmost when you started speaking is still frontmost now — which is why the
    window work had to come first.

    **The clipboard is written before the keystroke is attempted**, deliberately, and it
    is the same decision `inject.py` made: if the keystroke is refused, the text is still
    somewhere the user can reach with their own Cmd-V.
    """
    if not text:
        return False

    # Asked before anything is touched, so the refusal costs no clipboard.
    front = frontmost()
    if front.lower() in FLOW_NAMES:
        _warn(f"not pasted: {front} had the focus, not the window you were aiming at")
        return False

    previous = get_clipboard_text() if restore_clipboard else None
    if not set_clipboard_text(text):
        return False

    # One script rather than two calls: each `osascript` is a process launch, and the gap
    # between a Cmd-V and a Return is exactly where another window could come forward and
    # take the Return.
    keys = ['keystroke "v" using command down']
    if submit:
        # `key code 36` is Return. Spelled as a code because `keystroke return` sends the
        # character, and an app that tells them apart gets a newline instead of a send.
        # The delay lets the paste land first — without it both events arrive in the same
        # turn of the target's run loop and the Return can win.
        keys += ["delay 0.05", "key code 36"]
    script = chr(10).join(['tell application "System Events"', *keys, "end tell"])
    ok, reason = _run(["osascript", "-e", script])
    if not ok:
        _warn(permission_note() if denied(reason) else f"not pasted: {reason}")
        return False

    if restore_clipboard:
        _restore_later(previous)
    return True
