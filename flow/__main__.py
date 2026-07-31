"""Entry point: `uv run flow` (or `uv run python -m flow`).

Wires the real pieces together — mic, ASR, router, CLI refine, pill, hotkeys, paste —
and nothing else. All the behaviour lives in the modules.
"""

from __future__ import annotations

import argparse
import sys

from .asr import FINAL_MODEL, PARTIAL_MODEL
from .lexicon import DEFAULT_PATH, NUL_PATH, Lexicon
from .hotkey import DEFAULT_BINDINGS, Hotkeys
from .inject import paste, take_warnings
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
    ap.add_argument(
        "--partial-model", default=PARTIAL_MODEL,
        help="fast model for live partials (latency-bound, R4)",
    )
    ap.add_argument(
        "--final-model", default=FINAL_MODEL,
        help="stronger model for the text that gets pasted (accuracy-bound)",
    )
    ap.add_argument(
        "--model", default=None,
        help="pin BOTH tiers to one model (benchmarking, or a low-memory machine)",
    )
    ap.add_argument(
        "--lexicon", default=None,
        help=f"personal terms to bias decoding toward (default {DEFAULT_PATH})",
    )
    ap.add_argument(
        "--no-lexicon", action="store_true",
        help="ignore the lexicon file without deleting it",
    )
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

    partial_name = args.model or args.partial_model
    final_name = args.model or args.final_model
    say(f"models: {partial_name} for partials, {final_name} for finals")

    lexicon = Lexicon(NUL_PATH if args.no_lexicon else args.lexicon)
    n_terms = len(lexicon.terms())
    if args.no_lexicon:
        say("lexicon: disabled")
    elif n_terms:
        # The count is worth printing: biasing costs accuracy on speech that contains
        # none of the terms (see flow/lexicon.py), so a lexicon nobody remembers
        # creating is a plausible cause of "it got worse".
        say(f"lexicon: {n_terms} terms from {lexicon.path}")
    else:
        say(f"lexicon: none - create {lexicon.path} to bias names and jargon")

    session = Session(
        asr=WhisperTranscriber(partial_name, final_name, lexicon=lexicon),
        device=args.device,
    )

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
