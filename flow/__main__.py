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
    ap.add_argument(
        "--calibrate", action="store_true",
        help="measure this room and this voice, store the profile, and exit (P8)",
    )
    ap.add_argument(
        "--no-profile", action="store_true",
        help="ignore the stored profile and learn nothing this session",
    )
    ap.add_argument(
        "--converse", action="store_true",
        help="start in converse mode: Send asks the agent CLI instead of pasting (P9)",
    )
    ap.add_argument(
        "--no-speak", action="store_true",
        help="never read converse-mode replies aloud",
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

    from .profile import Profile

    profile = None if args.no_profile else Profile()
    learned = profile.learned_terms if profile is not None else None
    if profile is not None and profile.calibrated:
        say(f"profile: room {profile.floor_db:.1f} dB, "
            f"margin {profile.margin_db():.1f} dB, {len(profile.pairs)} learned pairs")
    elif profile is not None:
        say("profile: not calibrated - run `flow --calibrate` once for this room")

    lexicon = Lexicon(
        NUL_PATH if args.no_lexicon else args.lexicon, learned=learned
    )
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

    # Built unless refused, not only when asked for. Speech used to be a launch flag
    # while the mode it serves is a runtime toggle, so anyone who discovered converse
    # mode with ctrl+alt+M mid-session had no way to turn the voice on — which is
    # exactly what happened the first time someone tried it. Entering converse mode is
    # the opt-in; a conversation you have to read is not the feature.
    speaker = None
    if not args.no_speak:
        from .speak import Speaker

        speaker = Speaker()
        if not speaker.available:
            say("speech: engine unavailable - replies will be silent")
            speaker = None
        else:
            say("speech: on (converse-mode replies are read aloud; --no-speak to mute)")

    session = Session(
        asr=WhisperTranscriber(
            partial_name, final_name, lexicon=lexicon,
            baseline=profile.confidence if profile is not None else None,
        ),
        device=args.device,
        speaker=speaker,
        profile=profile,
    )

    if args.calibrate:
        from .calibrate import run as calibrate_run

        if profile is None:
            say("--calibrate needs a profile; drop --no-profile")
            return 2
        session.mic.start()
        try:
            ok = calibrate_run(session.mic, profile, asr=session.asr, log=say)
        finally:
            session.mic.stop()
        return 0 if ok else 1

    # A stored calibration replaces the shipped constants, which were tuned on one
    # machine and one voice and have already been measured wrong for both a quiet room
    # and an accent.
    if profile is not None:
        from .calibrate import apply as apply_profile

        if apply_profile(profile, session.gate):
            say(f"gate: floor {session.gate.floor_db:.1f} dB, "
                f"margin {session.gate.margin_db:.1f} dB (calibrated)")
    # Stated either way, and unprompted. "There was no spoken reply" and "I was never
    # in converse mode" produce identical symptoms, and the first live user hit exactly
    # that: nothing on screen or in the log distinguished them.
    if args.converse:
        session.toggle_mode()
        say("mode: CONVERSE - Send asks the agent CLI and the reply appears in Flow")
    else:
        say("mode: DICTATE - Send pastes into the focused window "
            "(--converse, or ctrl+alt+M, to ask instead)")

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
        # Converse mode returns "" from send(), so this is dictate-mode only by
        # construction: the question must never be pasted into the focused window.
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
