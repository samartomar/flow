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
import math
import os
import sys

from .asr import CUDA_MODEL, DEVICE, FINAL_MODEL, PARTIAL_MODEL
from .lexicon import DEFAULT_PATH, NUL_PATH, Lexicon
from .refine import MAX_TIMEOUT_SEC
from .refine import TIMEOUT_SEC as REFINE_TIMEOUT_SEC
from .refine import CANDIDATES, available, named, unverified, unverified_note
from .session import AUTO_ASK_SEC, Session
from .stats import TYPING_WPM
from .stats import report as stats_report
from .version import check_update, version

# `.hotkey`, `.inject` and `.ui` are imported inside main() rather than up here, and the
# placement still matters: `hotkey` and `inject` call `ctypes.WinDLL("user32")` at import
# time, so a Lite launch must not reach either. `ui` is the one that changed — it binds
# Win32 behind a `sys.platform` check now, because Lite still draws a pill. The rest of
# the package — session, asr, lexicon, refine, audio — was always portable and stays up
# here, which is also the honest summary of what the body costs and the brain does not.

#: Said on every Lite launch, before anything else, in ASCII for the reason `say()` gives.
#: It names the platform because the two ways into Lite are a flag and an OS, and someone
#: who did not type `--lite` deserves to be told which one they got.
LITE_LINE = (
    "Flow Lite on {platform}: Send copies the draft and you paste it - no injection, "
    "no global hotkeys, nothing to grant but the microphone."
)


def say(msg: str) -> None:
    """Startup diagnostics, flushed.

    These lines report which agent CLI was found and which hotkeys actually
    registered, so they are exactly the output a user needs when something is not
    working. Python block-buffers stdout when it is not a tty, which meant they were
    invisible whenever the app was piped or redirected.
    """
    print(msg, flush=True)


def _timeout_arg(text: str) -> float:
    """`--cli-timeout`, refused at the flag when it is not a wait.

    `type=float` accepted `nan` and `inf`, because both are perfectly good floats — and
    downstream `max(nan, 60.0)` is `nan` while `nan <= 0` is False, so the deadline check
    that ends every CLI call could never fire. A hung provider was then waited on
    forever, microphone open, pill saying "thinking". `0` and negatives are the same hole
    from the other side, where every call times out before it starts.

    Refused here rather than clamped, because at a prompt these are typos and a silent
    substitution would leave somebody wondering why their number did nothing.
    `refine.sane_timeout` is the belt under it for callers who never came through here.
    """
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds")
    if not math.isfinite(value) or not 0 < value <= MAX_TIMEOUT_SEC:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a wait - give a number of seconds "
            f"between 0 and {MAX_TIMEOUT_SEC:.0f}"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    # First, before anything resolves anything. Windows searches the current directory
    # ahead of PATH for a bare executable name, and Flow is launched *inside* project
    # directories by design — the workshop is the product — so a repository carrying
    # `codex.EXE` or `pwsh.EXE` supplies them. One variable closes that search for
    # `shutil.which` *and* for `CreateProcess`, which is what makes it worth a line here
    # rather than a check at each of the four call sites: it is inherited, so the `node`
    # that `codex` starts is covered too, and nothing in this process can reach a
    # resolver before argparse has even been built.
    #
    # `setdefault` rather than assignment: an owner who set this deliberately — including
    # to `0`, wanting the old order for a build script — has said something, and
    # overriding it would be a second surprise rather than a fix. The belt under this is
    # `refine.trusted`, which needs no environment at all.
    os.environ.setdefault("NoDefaultCurrentDirectoryInExePath", "1")

    ap = argparse.ArgumentParser(prog="flow", description=__doc__)
    ap.add_argument(
        "--partial-model", default=None,
        help=f"fast model for live partials (latency-bound, R4; default "
             f"{PARTIAL_MODEL} on CPU, {CUDA_MODEL} on GPU)",
    )
    ap.add_argument(
        "--final-model", default=None,
        help=f"stronger model for the text that gets pasted (accuracy-bound; default "
             f"{FINAL_MODEL} on CPU, {CUDA_MODEL} on GPU)",
    )
    ap.add_argument(
        "--model", default=None,
        help="pin BOTH tiers to one model (benchmarking, or a low-memory machine)",
    )
    ap.add_argument(
        "--decode-device", default=DEVICE, choices=("auto", "cuda", "cpu"),
        help="where decoding runs (default auto: the GPU when there is a working one)",
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
        help="pin the agent CLI instead of trying each in turn "
             f"({', '.join(c.name for c in CANDIDATES if c.verified)})",
    )
    ap.add_argument(
        "--cli-timeout", type=_timeout_arg, default=REFINE_TIMEOUT_SEC, metavar="SEC",
        help=f"how long to wait for a CLI call (default {REFINE_TIMEOUT_SEC:.0f})",
    )
    ap.add_argument(
        "--lite", action="store_true",
        help="clipboard-out mode: Send copies the draft instead of pasting it, and no "
             "hotkeys are registered (automatic off Windows)",
    )
    # Last, because none of these is a way to run Flow: each answers a question about the
    # copy or about what it has already done, and exits. `--version` is argparse's own
    # action, so it prints and leaves where `--help` does, ahead of every flag above it —
    # which is the right order for a question the answer to which cannot depend on any of
    # them.
    ap.add_argument(
        "--version", action="version", version=f"flow {version()}",
        help="print the version and exit",
    )
    ap.add_argument(
        "--check-update", action="store_true",
        help="ask GitHub once whether there is a newer release, print one line and exit "
             "(nothing else ever asks)",
    )
    ap.add_argument(
        "--stats", action="store_true",
        help="print how much has been dictated - today and all time - and exit "
             f"(the typing comparison assumes {TYPING_WPM} words a minute)",
    )
    args = ap.parse_args(argv)

    # Above the body choice and everything under it, because this is a question about
    # the download rather than a launch: one line out, and no pill, no microphone, no
    # profile, not even the Lite banner. The exit code carries what the line cannot - 1
    # when the check could not run at all, so a script wrapping this can tell "nothing
    # newer" from "no answer" without reading English.
    if args.check_update:
        line, ran = check_update()
        say(line)
        return 0 if ran else 1

    # Same place and for the same reason: a question about what has already happened, not
    # a way to make more of it happen. No model is loaded, no microphone is opened and no
    # window is drawn — this reads two files and leaves, which is what makes it cheap
    # enough to run from a prompt whenever somebody wonders.
    #
    # `--no-profile` is passed through rather than ignored. It is the flag that means
    # "ignore the stored profile and learn nothing", and stats that read that profile
    # anyway would make it a promise Flow keeps everywhere except where somebody looks.
    if args.stats:
        report, counted = stats_report(no_profile=args.no_profile)
        for line in report:
            say(line)
        return 0 if counted else 1

    # The platform is read once, here, and only to choose a body. Everything downstream
    # reads `lite`, which is why `--lite` on Windows runs the same code a Mac runs rather
    # than a rehearsal of it — and why every Lite path is a unit test with no desktop.
    #
    # This used to be a refusal above argparse, on the argument that being told a flag is
    # wrong when the platform is the problem answers the smaller question. That was right
    # while the platform *was* the problem; it is not one any more (decisions.md,
    # "Flow Lite").
    lite = args.lite or sys.platform != "win32"
    if lite:
        say(LITE_LINE.format(platform=sys.platform))
        if args.no_paste:
            # Accepted rather than refused: a launcher shared between two machines should
            # not fail on a flag that has simply run out of things to suppress.
            say("  (--no-paste has nothing to suppress here - the copy is the send)")
    # First of the block that follows, because it is the fact the rest of the block are
    # facts *about*: a report naming a hotkey, a model or a decode time has to say which
    # copy produced them, and the download link always serves the newest zip, so the
    # copy on disk is the only thing that knows which one arrived. That nothing checks
    # on its own is said out loud for the reason the trace line names itself unprompted -
    # a promise nobody is told about is one they have no way to believe.
    say(f"version: {version()} (nothing checks for updates on its own; "
        "--check-update asks GitHub)")
    if not lite:
        from .hotkey import DEFAULT_BINDINGS, Hotkeys
        from .inject import paste, take_warnings
    from .ui import Pill

    from .asr import WhisperTranscriber

    clis = [c.name for c in available()]
    pinned = None
    if args.cli:
        pinned = named(args.cli)
        if pinned is None:
            say(f"--cli {args.cli}: not a known CLI "
                f"({', '.join(c.name for c in CANDIDATES)})")
            return 2
        # Before the PATH check, and that order is the point: an inert entry may well be
        # installed, and "not on PATH" would be a lie about the one thing the user can
        # check themselves.
        if not pinned.verified:
            say(f"--cli {pinned.name}: its invocation shape has never been run, so Flow "
                "will not guess it - see NEEDS_YOU for the one command that settles it")
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
    # Said out loud rather than left silent, for the same reason the trace line is: a CLI
    # that is installed and deliberately not used looks exactly like one Flow failed to
    # find, and the person who installed it is the one who can end the difference.
    for cli in unverified():
        say(f"  ({unverified_note(cli)})")
    say(f"CLI timeout: {args.cli_timeout:.0f}s per call")

    # The device first, because which model each tier should be depends on it: a GPU
    # runs one strong model for both paths and a CPU cannot. Named out loud for the same
    # reason the models are — the two answers are a 3.7 s final decode and a 0.3 s one,
    # and somebody whose GPU quietly did not engage has no other way to tell.
    from .asr import default_models, resolve_device

    decode_device = resolve_device(args.decode_device)
    say(f"decoding on: {decode_device}"
        + ("" if decode_device != "cpu" or args.decode_device == "cpu"
           else " (no usable CUDA device found)"))

    default_partial, default_final = default_models(decode_device)
    partial_name = args.model or args.partial_model or default_partial
    final_name = args.model or args.final_model or default_final
    if partial_name == final_name:
        say(f"model: {final_name}, for partials and finals both")
    else:
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
        from .speak import Speaker, default_voice, installed_voices, pick

        # The flag wins over the profile, and the profile over whatever is best. A
        # saved voice that has since been uninstalled resolves to None and is said out
        # loud rather than silently ignored — the reply would otherwise come back in a
        # voice nobody chose, which reads as the setting not working.
        wanted = args.voice or (profile.voice if profile is not None else None)
        chosen = pick(wanted)
        # `default_voice` and not None, so that a machine with a better engine installed
        # does not fall through to `System.Speech`'s own default — which is one of the
        # 2013 voices the menu has stopped offering. See its docstring: hiding them from
        # the list while still speaking in them is the worst of both.
        fallback = default_voice()
        if wanted and chosen is None:
            say(f"voice: {wanted!r} is not installed - using "
                f"{fallback or 'the engine default'}")
        chosen = chosen or fallback
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
    # Every path that arrives via the flag joins the recents the menu offers — the
    # flag is how a new workspace enters, the list is where it lives after (item 36).
    # Only a *resolved* flag: a typo'd --cwd in the recents would be a stale entry
    # from birth, and a stored workspace re-resolved at launch is not an arrival.
    # Saved now rather than at the next Send: a launch that never Sends still arrived.
    if profile is not None and args.cwd and workspace is not None:
        profile.note_workspace(workspace)
        profile.save()

    session = Session(
        asr=WhisperTranscriber(
            partial_name, final_name, lexicon=lexicon,
            baseline=profile.confidence if profile is not None else None,
            device=args.decode_device,
        ),
        device=args.device,
        speaker=speaker,
        profile=profile,
        diag=diag,
        cli=pinned,
        cli_timeout=args.cli_timeout,
        refine_cwd=workspace,
        lite=lite,
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
            # `close()`, not `mic.stop()`. This branch builds a whole Session and then
            # returns down a path that never reaches `__exit__`, so it used to leave the
            # decode thread and — since `speaker.available` starts the host during
            # launch — a live PowerShell behind it.
            session.close()
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
    elif lite:
        say("mode: DICTATE - Send copies the draft, and you paste it "
            "(--converse, or the right-click menu, to ask instead)")
    else:
        say("mode: DICTATE - Send pastes into the focused window "
            "(--converse, or ctrl+alt+M, to ask instead)")

    hotkeys = None
    if not args.no_hotkeys and not lite:
        hotkeys = Hotkeys(DEFAULT_BINDINGS)
        if hotkeys.start():
            for action, combo in hotkeys.chosen.items():
                say(f"hotkey  {action:8s} {combo}")
            if hotkeys.failed:
                say(f"hotkeys unavailable (every alternative taken): {hotkeys.failed}")
        else:
            say("hotkey thread did not start; continuing without hotkeys")
            hotkeys = None
    # Assigned rather than passed: the session is built before `RegisterHotKey` has been
    # asked for anything, and what the session needs is the answer, not the request. It
    # reads this only to say what still works when voice stops working.
    session.hotkeys = hotkeys

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

        Never reached in Lite, and not merely unused there: `paste` and `take_warnings`
        are not imported, so this closure has nothing to resolve — which is why the pill
        is handed `None` rather than a handler that would fail on its first call.
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
        session, on_send=None if lite else on_send, hotkeys=hotkeys, arm=args.arm,
        settings_path=DEFAULT_PATH if args.no_lexicon else lexicon.path,
        lite=lite,
    ).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
