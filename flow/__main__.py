"""Entry point: `uv run flow` (or `uv run python -m flow`).

Wires the real pieces together — mic, ASR, router, CLI refine, pill, hotkeys, paste —
and nothing else. All the behaviour lives in the modules.
"""

from __future__ import annotations

import argparse
import sys

from .hotkey import DEFAULT_BINDINGS, Hotkeys
from .inject import paste
from .refine import available
from .session import Session
from .ui import Pill


def say(msg: str) -> None:
    """Startup diagnostics, flushed.

    These lines report which agent CLI was found and which hotkeys actually
    registered, so they are exactly the output a user needs when something is not
    working. Python block-buffers stdout when it is not a tty, which meant they were
    invisible whenever the app was piped or redirected.
    """
    print(msg, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="flow", description=__doc__)
    ap.add_argument("--model", default="base.en", help="faster-whisper model")
    ap.add_argument("--device", type=int, default=None, help="input device index")
    ap.add_argument(
        "--no-hotkeys", action="store_true", help="skip global hotkey registration"
    )
    ap.add_argument(
        "--no-paste", action="store_true", help="print the draft instead of pasting"
    )
    ap.add_argument(
        "--arm", action="store_true", help="start listening immediately, no click needed"
    )
    args = ap.parse_args(argv)

    from .asr import WhisperTranscriber

    clis = [c.name for c in available()]
    # Console strings are ASCII on purpose: redirected stdout uses the locale encoding,
    # and a legacy console code page (cp437/cp850) cannot encode chars like en-dash or
    # middle-dot, which would turn a startup message into a UnicodeEncodeError crash.
    say(f"refine CLI: {clis[0] if clis else 'NONE - semantic rewrites disabled'}")
    if clis:
        say(f"  (fallbacks: {', '.join(clis[1:]) or 'none'})")

    session = Session(asr=WhisperTranscriber(args.model), device=args.device)

    hotkeys = None
    if not args.no_hotkeys:
        hotkeys = Hotkeys(DEFAULT_BINDINGS)
        if hotkeys.start():
            for action, combo in hotkeys.chosen.items():
                say(f"hotkey  {action:8s} {combo}")
            if hotkeys.failed:
                say(f"hotkeys unavailable (every alternative taken): {hotkeys.failed}")
        else:
            say("hotkey thread did not start; continuing without hotkeys")
            hotkeys = None

    def on_send(text: str) -> None:
        if args.no_paste:
            say(f"\n--- draft ---\n{text}\n")
        elif not paste(text):
            # Never fail silently: the user pressed Send and expects something.
            print(
                "could not take the clipboard - draft not pasted",
                file=sys.stderr,
                flush=True,
            )

    say(
        ("listening | " if args.arm else "click the pill to arm | ")
        + "right-click for the menu | esc quits"
    )
    Pill(session, on_send=on_send, hotkeys=hotkeys, arm=args.arm).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
