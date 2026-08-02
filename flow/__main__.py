"""Local English dictation with a talk-to-it refine loop. Run: uv run flow

Wires the real pieces together - mic, ASR, router, CLI refine, pill, hotkeys, paste -
and nothing else. All the behaviour lives in the modules.
"""

# The docstring above is argparse's `description`, so it is what `--help` prints. Two
# constraints follow from that, both learned the hard way.
#
# ASCII only, for the reason `say()` documents below: a redirected stdout on a legacy
# console code page cannot encode an en-dash, and the help text would crash instead of
# printing.
#
# And the invocation in it has to be one that actually runs. This said `uv run flow` while
# pyproject said `package = false`, which installs no console script: that command found
# this file, ran it as a loose script, and died on the relative imports below. So --help
# was printing the one invocation guaranteed to fail. `package = true` fixes it properly —
# both forms work now, and `python -m flow` needs no install at all.

from __future__ import annotations

import argparse
import sys

from .asr import FINAL_MODEL, PARTIAL_MODEL
from .lexicon import DEFAULT_PATH, NUL_PATH, Lexicon
from .refine import TIMEOUT_SEC as REFINE_TIMEOUT_SEC
from .refine import CANDIDATES, available, named
from .session import AUTO_ASK_SEC, Session

# `.hotkey`, `.inject` and `.ui` are imported inside main(), under the platform guard,
# and that placement is the whole point of the guard: each of the three calls
# `ctypes.WinDLL("user32")` at import time, so on a Mac this file cannot even be read
# into memory. A check at the top of a function that is never reached says nothing. The
# rest of the package — session, asr, lexicon, refine, audio — is portable and stays up
# here, which is also the honest summary of what a port would have to do.


def say(msg: str) -> None:
    """Startup diagnostics, flushed.

    These lines report which agent CLI was found and which hotkeys actually
    registered, so they are exactly the output a user needs when something is not
    working. Python block-buffers stdout when it is not a tty, which meant they were
    invisible whenever the app was piped or redirected.
    """
    print(msg, flush=True)


def main(argv: list[str] | None = None) -> int:
    # First, and above argparse: a Mac user's first impression of this product should be
    # a sentence they can act on, not a stack trace from ctypes about a DLL they have
    # never heard of. Above the flags too — being told the flag is wrong when the
    # platform is the problem is the smaller answer to the larger question. The port is
    # parked on Mac users existing and Mac hardware to re-measure on, not on the code
    # being unportable (docs/decisions.md, "Distribution").
    if sys.platform != "win32":
        say("Flow's paste and hotkey layer is Windows-only today, so it cannot run "
            f"on {sys.platform} - see the README's Install section for what a port "
            "would take.")
        return 2

    from .hotkey import DEFAULT_BINDINGS, Hotkeys
    from .inject import paste, take_warnings
    from .ui import Pill

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
        "--cwd", metavar="PATH",
        help="the project converse-mode questions are asked from; overrides the "
             "profile's stored workspace (P9)",
    )
    ap.add_argument(
        "--no-speak", action="store_true",
        help="never read converse-mode replies aloud",
    )
    ap.add_argument(
        "--voice", default=None,
        help="voice for spoken replies: a name, part of one, or male/female "
             "(list them with scripts/voices.py)",
    )
    ap.add_argument(
        "--no-auto-ask", action="store_true",
        help="in converse mode, wait for the Ask button instead of a pause",
    )
    ap.add_argument(
        "--cli", default=None, metavar="NAME",
        help="pin the agent CLI (codex or claude) instead of trying each in turn",
    )
    ap.add_argument(
        "--cli-timeout", type=float, default=REFINE_TIMEOUT_SEC, metavar="SEC",
        help=f"how long to wait for a CLI call (default {REFINE_TIMEOUT_SEC:.0f})",
    )
    args = ap.parse_args(argv)

    from .asr import WhisperTranscriber

    clis = [c.name for c in available()]
    pinned = None
    if args.cli:
        pinned = named(args.cli)
        if pinned is None:
            say(f"--cli {args.cli}: not a known CLI "
                f"({', '.join(c.name for c in CANDIDATES)})")
            return 2
        if pinned.name not in clis:
            say(f"--cli {pinned.name}: not on PATH")
            return 2
    # Console strings are ASCII on purpose: redirected stdout uses the locale encoding,
    # and a legacy console code page (cp437/cp850) cannot encode chars like en-dash or
    # middle-dot, which would turn a startup message into a UnicodeEncodeError crash.
    if pinned is not None:
        say(f"refine CLI: {pinned.name} (pinned; no fallback)")
    else:
        say(f"refine CLI: {clis[0] if clis else 'NONE - semantic rewrites disabled'}")
    if clis and pinned is None:
        rest = ", ".join(clis[1:])
        say(f"  (falls back to {rest} if it fails)" if rest
            else "  (no fallback - only one CLI on PATH)")
    say(f"CLI timeout: {args.cli_timeout:.0f}s per call")

    partial_name = args.model or args.partial_model
    final_name = args.model or args.final_model
    say(f"models: {partial_name} for partials, {final_name} for finals")

    from .diag import Diag
    from .profile import Profile, resolve_workspace

    # Tied to the same flag as the profile, and deliberately: --no-profile means
    # "write nothing about me this session", and a trace is a thing written about
    # somebody even when it holds none of their words.
    profile = None if args.no_profile else Profile()
    diag = None if args.no_profile else Diag()
    learned = profile.learned_terms if profile is not None else None
    if profile is not None and profile.calibrated:
        say(f"profile: room {profile.floor_db:.1f} dB, "
            f"margin {profile.margin_db():.1f} dB, {len(profile.pairs)} learned pairs")
    elif profile is not None:
        say("profile: not calibrated - run `flow --calibrate` once for this room")
    # Said out loud, unprompted. A file that records what somebody did is one they are
    # entitled to know exists and to delete, and the surest way to make it feel like
    # telemetry is for them to find it by accident.
    say(f"trace: {diag.path} (timings and state only, no words; --no-profile to disable)"
        if diag is not None else "trace: off")

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
        say("lexicon: none - right-click > Open settings folder, or create "
            f"{lexicon.path}, to add names and corrections")

    # Built unless refused, not only when asked for. Speech used to be a launch flag
    # while the mode it serves is a runtime toggle, so anyone who discovered converse
    # mode with ctrl+alt+M mid-session had no way to turn the voice on — which is
    # exactly what happened the first time someone tried it. Entering converse mode is
    # the opt-in; a conversation you have to read is not the feature.
    speaker = None
    if not args.no_speak:
        from .speak import Speaker, installed_voices, pick

        # The flag wins over the profile, and the profile over the engine default. A
        # saved voice that has since been uninstalled resolves to None and is said out
        # loud rather than silently ignored — the reply would otherwise come back in a
        # voice nobody chose, which reads as the setting not working.
        wanted = args.voice or (profile.voice if profile is not None else None)
        chosen = pick(wanted)
        if wanted and chosen is None:
            say(f"voice: {wanted!r} is not installed - using the engine default")
        speaker = Speaker(voice=chosen)
        if not speaker.available:
            say("speech: engine unavailable - replies will be silent")
            speaker = None
        else:
            n = len(installed_voices())
            say(f"speech: on, voice {chosen or 'engine default'} "
                f"({n} installed; --voice, or the right-click menu, to change)")

    # Said whichever way it resolves, including "not set". The owner accepted that a
    # stored workspace goes stale silently when a project moves; this line is what they
    # accepted it in exchange for.
    workspace, workspace_note = resolve_workspace(args.cwd, profile)
    say(workspace_note)

    session = Session(
        asr=WhisperTranscriber(
            partial_name, final_name, lexicon=lexicon,
            baseline=profile.confidence if profile is not None else None,
        ),
        device=args.device,
        speaker=speaker,
        profile=profile,
        diag=diag,
        cli=pinned,
        cli_timeout=args.cli_timeout,
        refine_cwd=workspace,
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
    # The flag wins over the profile, and the profile over the default — the same order
    # `--voice` follows. This used to assign unconditionally, so the absence of a flag
    # overwrote a stored preference and switching auto-ask off never survived a restart.
    if args.no_auto_ask:
        session.auto_ask = False
    if args.converse:
        session.toggle_mode()
        say("mode: CONVERSE - the Ask button puts the draft to the agent CLI "
            "and the reply appears in Flow")
        if session.auto_ask:
            say(f"auto-ask: on - a pause of {AUTO_ASK_SEC:.0f}s sends the question "
                "(--no-auto-ask to press it yourself)")
        else:
            say("auto-ask: off - press Ask when you are ready")
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

    def on_send(text: str, target: int | None = None, submit: bool = False) -> str:
        """Paste the draft into `target`, and return what went wrong, or "".

        Converse mode returns "" from send(), so this is dictate-mode only by
        construction: the question must never be pasted into the focused window.

        `target` is the window the pill last saw with the foreground that was not Flow's
        own. Asking the OS here instead — which is what this used to do, one level down
        — asks after the click that got us here, and the answer was Flow.

        The return value is what the bubble shows. Both halves of that are new: the
        warnings were collected and never drained by anybody, and a failure went to a
        stderr nobody is watching while the button reported success.
        """
        if args.no_paste:
            say(f"\n--- draft ---\n{text}{' [+Enter]' if submit else ''}\n")
            return ""
        ok = paste(text, hwnd=target, submit=submit)
        problems = take_warnings()
        if not ok and not problems:
            problems.append("not pasted, and no reason was recorded")
        for line in problems:
            print(line, file=sys.stderr, flush=True)
        return "; ".join(problems)

    quits = (f"{hotkeys.chosen['quit']} quits"
             if hotkeys is not None and "quit" in hotkeys.chosen
             else "quit from the right-click menu")
    if diag is not None:
        # Off the startup path on purpose: two CLI process starts and a handful of file
        # reads, none of which anybody is waiting for. The pill is on screen in 0.40 s
        # and this must not be part of that number.
        import threading as _threading

        from .diag import record_identity

        _threading.Thread(
            target=record_identity, args=(diag, (partial_name, final_name)),
            daemon=True, name="identity",
        ).start()

    say(
        ("listening | " if args.arm else "click the pill to arm | ")
        + f"right-click for the menu | {quits}"
    )
    # `--no-lexicon` points the loader at a path inside the package that must never
    # exist, so the menu is sent to the real settings folder instead: the profile lives
    # there either way, and creating a template beside the source is nobody's idea of
    # settings.
    Pill(
        session, on_send=on_send, hotkeys=hotkeys, arm=args.arm,
        settings_path=DEFAULT_PATH if args.no_lexicon else lexicon.path,
    ).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
