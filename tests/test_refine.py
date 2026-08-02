"""Tests for the CLI adapter's guards (R11), and for saying what they did.

These guards are the reason the agent CLI cannot hurt the user: bounded input, hard
timeout, and a refusal to paste commentary into their text. All of them only matter in
failure cases, which is exactly the code least likely to be exercised by hand.

The bound on input is the one the user can *feel* without being told — a long draft is
refined only at the end, and from outside that looks like the CLI ignoring most of what
was asked. The last class here is about that being said out loud.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import flow.refine as refine_mod
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_env import no_off_path_installs  # noqa: E402
from flow.refine import MAX_CHARS, Cli, _split_tail, refine  # noqa: E402
from flow.session import Session  # noqa: E402

CLI = Cli("codex", ("codex", "exec"))


def fake_proc(stdout: str = "", returncode: int = 0, stderr: str = "", *,
              hang: bool = False):
    """A `Popen` with the surface `_invoke` uses, and nothing else.

    `hang=True` never completes, which is how a timeout is reproduced without waiting
    for one. `poll` reports an exit either way, so the guard that kills a live tree is
    not asked to kill a mock. What that guard does to a real process tree is measured
    in `test_lifecycle.py`, which is the only place a real one is started.
    """
    proc = mock.Mock(returncode=returncode, pid=0)
    if hang:
        proc.communicate.side_effect = subprocess.TimeoutExpired("codex", 0)
    else:
        proc.communicate.return_value = (stdout, stderr)
    proc.poll.return_value = returncode
    return proc


class TestTailSplit(unittest.TestCase):
    def test_short_text_is_sent_whole(self):
        head, tail = _split_tail("short enough")
        self.assertEqual(head, "")
        self.assertEqual(tail, "short enough")

    def test_long_text_sends_only_the_tail(self):
        text = "A sentence. " * 400  # ~4800 chars
        head, tail = _split_tail(text)
        self.assertLessEqual(len(tail), MAX_CHARS)
        self.assertEqual(head + tail, text, "splitting must be lossless")

    def test_split_lands_on_a_sentence_boundary(self):
        text = "Alpha. " * 500
        _head, tail = _split_tail(text)
        self.assertTrue(tail.startswith("Alpha"), f"fragment: {tail[:20]!r}")


class TestGuards(unittest.TestCase):
    def test_head_is_preserved_and_tail_replaced(self):
        text = "Old sentence. " * 300
        head, tail = _split_tail(text)
        with mock.patch("subprocess.Popen", return_value=fake_proc("REVISED")):
            out, note = refine(text, "shorten this", cli=CLI)
        self.assertEqual(note, "codex")
        self.assertEqual(out, head + "REVISED")
        self.assertNotIn("REVISED", head)

    def test_commentary_is_refused(self):
        # A ballooning reply is the model explaining itself, not revising.
        chatty = "Certainly! Here is the revised version you asked for. " * 40
        with mock.patch("subprocess.Popen", return_value=fake_proc(chatty)):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("commentary", note)

    def test_timeout_is_non_destructive(self):
        with mock.patch("subprocess.Popen", return_value=fake_proc(hang=True)):
            out, note = refine("ship it", "make it formal", cli=CLI, timeout=0.2)
        self.assertIsNone(out)
        self.assertIn("timed out", note)

    def test_nonzero_exit_is_reported(self):
        with mock.patch(
            "subprocess.Popen", return_value=fake_proc("", 1, "not logged in\nmore")
        ):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("not logged in", note)

    def test_empty_output_is_refused(self):
        with mock.patch("subprocess.Popen", return_value=fake_proc("   \n")):
            out, note = refine("ship it", "make it formal", cli=CLI)
        self.assertIsNone(out)
        self.assertIn("nothing", note)

    def test_code_fences_are_stripped(self):
        with mock.patch("subprocess.Popen", return_value=fake_proc("```\nShip it.\n```")):
            out, _note = refine("ship it", "make it formal", cli=CLI)
        self.assertEqual(out, "Ship it.")

    def test_stdin_is_closed(self):
        """codex blocks reading stdin; without DEVNULL the call hangs to the timeout."""
        with mock.patch("subprocess.Popen", return_value=fake_proc("ok")) as popen:
            refine("ship it", "make it formal", cli=CLI)
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_missing_cli_is_reported_not_raised(self):
        with mock.patch("flow.refine.available", return_value=[]):
            out, note = refine("ship it", "make it formal")
        self.assertIsNone(out)
        self.assertIn("no agent CLI", note)


class Silent:
    """No mic, no model. These tests are about what the session *says*."""

    level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        return []

    @property
    def active(self) -> bool:
        return True

    def load(self) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


#: Long enough to be cut, and made of sentences so the cut lands on a boundary rather
#: than at exactly MAX_CHARS — which is what makes the reported number worth checking.
LONG = "Alpha bravo charlie. " * 300


class TestTheBoundOnInputIsVisible(unittest.TestCase):
    """R11 caps what the CLI is handed, and that used to happen in silence.

    A Refine keeps the head verbatim and reattaches it, so nothing is lost — but "I
    asked it to shorten this and it only shortened the end" is a defect report waiting
    to be filed unless the app says which part it sent. An Ask is worse: the head of an
    over-long question is never sent at all, so the answer is to a question the user did
    not ask, and nothing anywhere said so.
    """

    def session(self) -> Session:
        s = Session(asr=Silent(), mic=Silent())
        self.addCleanup(s.close)
        return s

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def refined(self, text: str) -> str:
        s = self.session()
        s.draft.set(text)
        with mock.patch("flow.session.refine", return_value=("REVISED", "codex")):
            s._start_refine("make it formal")
        return self.notes(s)

    def asked(self, text: str) -> str:
        s = self.session()
        with mock.patch("flow.session.ask", return_value=("answer", "codex")):
            s._start_ask(text)
        return self.notes(s)

    def test_a_short_draft_says_nothing_about_length(self):
        self.assertNotIn("characters", self.refined("ship it on Friday"))

    def test_a_long_draft_says_how_much_of_it_went(self):
        self.assertIn("characters", self.refined(LONG))

    def test_and_says_the_rest_is_left_alone(self):
        # The head is reattached verbatim, so this is a promise, not a hedge.
        self.assertIn("left as it is", self.refined(LONG))

    def test_the_number_is_the_real_cut_not_the_constant(self):
        # `_split_tail` walks forward to a sentence boundary, so the tail is shorter
        # than MAX_CHARS. A note quoting 2000 would be a guess dressed as a measurement.
        note = self.refined(LONG)
        sent = int(next(w for w in note.replace("—", " ").split() if w.isdigit()))
        self.assertEqual(sent, len(_split_tail(LONG)[1]))
        self.assertLess(sent, MAX_CHARS)

    def test_a_short_question_says_nothing_about_length(self):
        self.assertNotIn("characters", self.asked("how do I widen a column"))

    def test_an_over_long_question_says_the_start_never_went(self):
        note = self.asked(LONG)
        self.assertIn("characters", note)
        self.assertIn("never saw", note)

    def test_the_two_notes_do_not_make_the_same_promise(self):
        # A Refine keeps what it did not send; an Ask discards it. Saying the same
        # thing about both would make one of them a lie.
        self.assertNotIn("left as it is", self.asked(LONG))


class TestTailSent(unittest.TestCase):
    def test_a_short_text_goes_whole(self):
        from flow.refine import tail_sent

        self.assertEqual(tail_sent("short enough"), len("short enough"))

    def test_a_long_text_reports_only_what_the_cli_sees(self):
        from flow.refine import tail_sent

        self.assertEqual(tail_sent(LONG), len(_split_tail(LONG)[1]))
        self.assertLessEqual(tail_sent(LONG), MAX_CHARS)


if __name__ == "__main__":
    unittest.main()


class TestTheFallbackIsReal(unittest.TestCase):
    """`CANDIDATES` was always documented as a preference order and startup always
    printed "(fallbacks: claude)" — but both entry points took the first available CLI
    and stopped there. A `codex` timeout produced a dead feature and a message naming a
    second CLI that was installed, working, and never tried.
    """

    BOTH = (refine_mod.Cli("codex", ("codex",)), refine_mod.Cli("claude", ("claude",)))

    def _with(self, results):
        """Patch _invoke to answer per CLI name, and record the order tried."""
        tried = []

        def fake(cli, prompt, *, timeout, cwd=None, cancel=None):
            tried.append(cli.name)
            return results[cli.name]

        return tried, mock.patch.object(refine_mod, "_invoke", fake)

    def test_a_timeout_falls_through_to_the_next_cli(self):
        tried, patched = self._with({
            "codex": (None, "codex timed out after 20s"),
            "claude": ("Use ALTER TABLE.", ""),
        })
        with mock.patch.object(refine_mod, "available", lambda: list(self.BOTH)), patched:
            answer, note = refine_mod.ask("how do I widen a column")
        self.assertEqual(answer, "Use ALTER TABLE.")
        self.assertEqual(note, "claude")
        self.assertEqual(tried, ["codex", "claude"])

    def test_a_working_first_cli_is_not_second_guessed(self):
        tried, patched = self._with({
            "codex": ("Use ALTER TABLE.", ""),
            "claude": ("never asked", ""),
        })
        with mock.patch.object(refine_mod, "available", lambda: list(self.BOTH)), patched:
            answer, note = refine_mod.ask("how do I widen a column")
        self.assertEqual(note, "codex")
        self.assertEqual(tried, ["codex"], "it paid for a second CLI it did not need")

    def test_every_failure_is_reported_when_all_of_them_fail(self):
        tried, patched = self._with({
            "codex": (None, "codex timed out after 20s"),
            "claude": (None, "claude exited 1"),
        })
        with mock.patch.object(refine_mod, "available", lambda: list(self.BOTH)), patched:
            answer, note = refine_mod.ask("how do I widen a column")
        self.assertIsNone(answer)
        self.assertIn("codex timed out", note)
        self.assertIn("claude exited 1", note)

    def test_refine_falls_through_too(self):
        tried, patched = self._with({
            "codex": (None, "codex failed to start: nope"),
            "claude": ("Tidied.", ""),
        })
        with mock.patch.object(refine_mod, "available", lambda: list(self.BOTH)), patched:
            revised, note = refine_mod.refine("rambling text", "tidy it")
        self.assertEqual(revised, "Tidied.")
        self.assertEqual(tried, ["codex", "claude"])

    def test_pinning_a_cli_is_a_decision_and_is_not_second_guessed(self):
        tried, patched = self._with({
            "codex": (None, "codex timed out after 20s"),
            "claude": ("would have worked", ""),
        })
        with mock.patch.object(refine_mod, "available", lambda: list(self.BOTH)), patched:
            answer, note = refine_mod.ask("q", cli=self.BOTH[0])
        self.assertIsNone(answer)
        self.assertEqual(tried, ["codex"], "a pinned CLI must not fall through")

    def test_no_cli_at_all_says_so(self):
        with mock.patch.object(refine_mod, "available", list):
            answer, note = refine_mod.ask("q")
        self.assertIsNone(answer)
        self.assertIn("no agent CLI", note)

    def test_named_looks_one_up_and_rejects_nonsense(self):
        self.assertEqual(refine_mod.named("claude").name, "claude")
        self.assertEqual(refine_mod.named("  CODEX ").name, "codex")
        self.assertIsNone(refine_mod.named("gpt"))


def only(*names):
    """A `shutil.which` that finds exactly these, so PATH is not the test's variable."""
    return lambda cmd, *a, **kw: f"/somewhere/{cmd}" if cmd in names else None


#: What kiro-cli actually put on stdout here on 2026-08-02, captured through the same
#: `Popen` shape `_invoke` uses. A cleaner is only as good as the furniture it was shown,
#: and these are transcribed rather than imagined.
KIRO_ANSWER = "\x1b[m> \x1b[0mThe deploy failed this morning because of the migration."
KIRO_MULTILINE = "\x1b[m> \x1b[0mApples\x1b[0m\x1b[0m\nPears\x1b[0m\x1b[0m\nPlums"
#: The same call with the streams merged, which is how the status line reaches stdout at
#: all — `_invoke` keeps them apart, and there it stays on stderr.
KIRO_MERGED = (
    "\x1b[mWARNING: \x1b[0m--trust-tools arg for custom tool \x1b[m\x1b[0m needs to be "
    "prepended with \x1b[m@{MCPSERVERNAME}/\x1b[0m\n\n\x1b[m\x1b[0m\x1b[?25l\x1b[m> "
    "\x1b[0mPONG\x1b[0m\x1b[0m\n\x1b[m\n ▸ Credits: 0.05 • Time: 1s\n\n\x1b[0m\x1b[1G"
    "\x1b[0m\x1b[0m\x1b[?25h"
)


class TestKiroCliIsWiredFromAMeasurement(unittest.TestCase):
    """The fourth verified entry, and the first that prints anything but its answer.

    Verified live on this machine on 2026-08-02, all four legs: `--version` →
    `kiro-cli-chat 2.16.0`; a one-shot `chat --no-interactive --trust-tools= "<prompt>"`
    answering in ~1 s at exit 0; and — the leg `opencode` failed — a SECRET on the last
    line of a three-line prompt coming back **verbatim** through `Popen` list-argv, because
    this is a native exe rather than a shim.

    Round five's rejection of `kiro` stands and was about a different binary: the `kiro` on
    PATH is the IDE launcher.
    """

    def kiro(self):
        return refine_mod.named("kiro-cli")

    def test_the_entry_carries_the_shape_that_was_run(self):
        self.assertEqual(
            self.kiro().argv,
            ("kiro-cli", "chat", "--no-interactive", "--trust-tools="),
        )
        self.assertTrue(self.kiro().verified)

    def test_kiro_the_ide_launcher_is_still_not_a_candidate(self):
        # Two names, one of which opens an editor window instead of answering.
        self.assertIsNone(refine_mod.named("kiro"))
        self.assertIsNotNone(refine_mod.named("kiro-cli"))

    def test_codex_is_still_first(self):
        self.assertEqual([c.name for c in refine_mod.CANDIDATES][:2], ["codex", "claude"])


class TestFindingAnInstallThatIsNotOnPath(unittest.TestCase):
    """Detection is PATH first, with one probe behind it, and the probe earns its place.

    The MSI adds `%LOCALAPPDATA%\\Kiro-Cli\\` to the *user* PATH, so a fresh shell finds
    `kiro-cli` the ordinary way. A process started from a shell that predates the install
    does not — measured here, in this session: `shutil.which("kiro-cli")` returned `None`
    while the executable sat at the probe path and answered a real prompt. So the probe is
    not hypothetical insurance; it is the difference between working and not in the
    environment an installer leaves behind until the next sign-in.
    """

    def test_path_is_asked_first(self):
        with mock.patch("shutil.which", only("kiro-cli")):
            found = refine_mod.resolve(refine_mod.named("kiro-cli"))
        self.assertEqual(found, "/somewhere/kiro-cli")

    def test_the_probe_answers_when_path_does_not(self):
        with mock.patch("shutil.which", only()), \
                mock.patch("os.path.isfile", lambda p: p.endswith("kiro-cli.exe")):
            found = refine_mod.resolve(refine_mod.named("kiro-cli"))
        self.assertTrue(found and found.endswith("kiro-cli.exe"), found)

    def test_a_missing_probe_target_is_not_a_resolution(self):
        with mock.patch("shutil.which", only()), \
                mock.patch("os.path.isfile", lambda p: False):
            self.assertIsNone(refine_mod.resolve(refine_mod.named("kiro-cli")))

    def test_entries_without_a_probe_are_unaffected(self):
        # Every other entry resolves by PATH alone, and a probe that fired for them would
        # be exactly the guessed shape `verified` exists to forbid.
        with mock.patch("shutil.which", only()), \
                mock.patch("os.path.isfile", lambda p: True):
            for name in ("codex", "claude", "opencode"):
                with self.subTest(cli=name):
                    self.assertIsNone(refine_mod.resolve(refine_mod.named(name)))

    def test_the_launch_uses_whatever_resolved_it(self):
        # The invariant from `TestWhatWhichFindsIsWhatRuns`, extended to the probe: a CLI
        # found off PATH must be *started* from where it was found, or detection and
        # launch disagree again one seam along.
        with mock.patch("shutil.which", only()), \
                mock.patch("os.path.isfile", lambda p: p.endswith("kiro-cli.exe")), \
                mock.patch("subprocess.Popen", side_effect=OSError("stopped")) as run:
            refine_mod._invoke(refine_mod.named("kiro-cli"), "a prompt", timeout=30)
        self.assertTrue(run.call_args.args[0][0].endswith("kiro-cli.exe"))


class TestTheFurnitureIsStrippedForOneCliAndNoOther(unittest.TestCase):
    """kiro-cli prints its answer inside a little chrome. Only its answer is the answer.

    Keyed per CLI rather than applied to everything, because a cleaner that fires for
    every entry is a parser — and this module's docstring is an argument against needing
    one. codex and claude write the answer alone to stdout and must come through untouched.
    """

    def clean(self, out: str, name: str = "kiro-cli") -> str:
        return refine_mod._clean(out, refine_mod.named(name))

    def test_the_real_answer_comes_out_alone(self):
        self.assertEqual(self.clean(KIRO_ANSWER),
                         "The deploy failed this morning because of the migration.")

    def test_a_multi_line_answer_keeps_its_lines(self):
        self.assertEqual(self.clean(KIRO_MULTILINE), "Apples\nPears\nPlums")

    def test_the_status_line_goes_when_the_streams_were_together(self):
        cleaned = self.clean(KIRO_MERGED)
        self.assertNotIn("Credits", cleaned)
        self.assertNotIn("\x1b", cleaned)
        self.assertIn("PONG", cleaned)

    def test_the_word_credits_inside_an_answer_survives(self):
        # The status line is a shape, not a word. An answer about billing is still an
        # answer, and eating a sentence out of it would be the cleaner becoming a parser.
        answer = "\x1b[m> \x1b[0mCredits are consumed per call, so batch the requests."
        self.assertEqual(self.clean(answer),
                         "Credits are consumed per call, so batch the requests.")

    def test_an_angle_bracket_inside_an_answer_survives(self):
        # Only the leading prompt marker goes. A quoted shell line or a diff is content.
        answer = "\x1b[m> \x1b[0mRun it as:\n> git push --force-with-lease"
        self.assertEqual(self.clean(answer),
                         "Run it as:\n> git push --force-with-lease")

    def test_codex_output_is_not_touched(self):
        # The negative that makes this per-CLI rather than global. Both of these would be
        # damaged by the kiro cleaner.
        for out in ("> git status\n> git push", "Credits: see the billing page."):
            with self.subTest(out=out):
                self.assertEqual(self.clean(out, "codex"), out)
                self.assertEqual(self.clean(out, "claude"), out)

    def test_and_neither_is_output_from_a_cli_nobody_named(self):
        # `_clean(out)` with no CLI is still the old defensive tidy and nothing more.
        self.assertEqual(refine_mod._clean("> an answer"), "> an answer")

    def test_the_generic_tidy_still_runs_afterwards(self):
        # Fences and surrounding quotes were always stripped; the per-CLI pass is in
        # front of that rather than instead of it.
        self.assertEqual(self.clean("\x1b[m> \x1b[0m```\nShip it.\n```"), "Ship it.")


class TestAnUnverifiedEntryIsInert(unittest.TestCase):
    """Detection ships everywhere; invocation shapes are run or they do not exist.

    The adapter grew past `codex`/`claude` (decisions.md, "Flow Lite"), and the whole risk
    of growing it is that a plausible argv is indistinguishable from a measured one once
    both are written in the same tuple. So `verified=False` means detection only, and the
    negatives below are the ones that matter: not what an inert entry does, but that
    nothing can reach it.
    """

    def unverified(self):
        return [c for c in refine_mod.CANDIDATES if not c.verified]

    def test_there_are_some_and_they_carry_no_shape_at_all(self):
        # The mechanical form of "never asserted from memory". An entry with a guessed
        # `("gemini", "-p")` in it would pass every other check in this class.
        pending = self.unverified()
        self.assertTrue(pending, "the inert entries went missing")
        for cli in pending:
            with self.subTest(cli=cli.name):
                self.assertEqual(cli.argv, (cli.name,))

    def test_available_never_offers_one_however_the_path_is_arranged(self):
        # `no_off_path_installs` throughout this class: PATH is what these tests declare,
        # and a machine that happens to have kiro-cli installed must not answer instead.
        with no_off_path_installs():
            with mock.patch("shutil.which", only("gemini", "copilot", "codex")):
                self.assertEqual([c.name for c in refine_mod.available()], ["codex"])
            with mock.patch("shutil.which", only("gemini", "copilot")):
                self.assertEqual(refine_mod.available(), [])

    def test_and_no_process_is_started_for_one(self):
        # Asserted on `Popen` rather than on the return value: a check that only looked at
        # the answer would pass just as well if the call was made and failed.
        with no_off_path_installs(), mock.patch("shutil.which", only("gemini")), \
                mock.patch("subprocess.Popen") as started:
            answer, note = refine_mod.ask("q")
        self.assertIsNone(answer)
        started.assert_not_called()

    def test_the_reason_names_what_was_found_and_not_run(self):
        with no_off_path_installs(), mock.patch("shutil.which", only("gemini")), \
                mock.patch("subprocess.Popen"):
            _answer, note = refine_mod.ask("q")
        self.assertIn("no agent CLI found on PATH", note)
        self.assertIn("gemini", note)
        self.assertIn("not yet verified", note)

    def test_detected_is_the_only_thing_that_names_them(self):
        with no_off_path_installs(), mock.patch("shutil.which", only("gemini", "codex")):
            self.assertEqual([c.name for c in refine_mod.detected()],
                             ["codex", "gemini"])
            self.assertEqual([c.name for c in refine_mod.unverified()], ["gemini"])

    def test_a_pin_can_still_look_one_up_so_the_refusal_can_be_honest(self):
        # `named` searching the inert entries is what lets `--cli gemini` say the true
        # reason instead of "not on PATH", which is a lie about the one thing the user
        # can check themselves.
        self.assertFalse(refine_mod.named("gemini").verified)
        self.assertTrue(refine_mod.named("codex").verified)

    def test_kiro_is_not_a_candidate_at_all(self):
        # Verified live on 2026-08-02 and the answer was that it is not an agent CLI: the
        # `kiro` on PATH is the IDE launcher, and invoking it opens an editor window.
        # "Not yet verified" would be the wrong thing to say about it — it is verified.
        self.assertIsNone(refine_mod.named("kiro"))
        self.assertNotIn("kiro", [c.name for c in refine_mod.CANDIDATES])

    def test_opencode_is_inert_despite_answering_once(self):
        # The most instructive entry in the tuple. `opencode run "<one line>"` exits 0
        # with the answer on stdout, which looks exactly like a verified shape — and every
        # prompt this module sends is multi-line, where it returns an answer to a question
        # it never received. Whether that is opencode or the `.cmd` shim it is installed
        # behind is unknown, and unknown is what inert is for.
        cli = refine_mod.named("opencode")
        self.assertFalse(cli.verified)
        self.assertEqual(cli.argv, ("opencode",), "a shape it does not have")

    def test_codex_stays_first_and_the_new_names_come_after(self):
        # R10's preference order is not something a new entry may quietly reorder.
        names = [c.name for c in refine_mod.CANDIDATES]
        self.assertEqual(names[:2], ["codex", "claude"])


class TestWhatWhichFindsIsWhatRuns(unittest.TestCase):
    """`shutil.which` and `CreateProcess` disagree about what a bare name means.

    Found on a Hyper-V VM, 2026-08-02, minutes after the repo went public: startup said
    `refine CLI: codex` and every Ask came back **"codex failed to start; [WinError 2]
    The system cannot find the file specified"**. Both statements were true at once.

    `available()` asks `shutil.which`, which honours `PATHEXT` and so finds `codex.cmd`.
    `_invoke` handed `subprocess.Popen` the bare string `"codex"`, and `CreateProcess`
    searches `PATH` appending only `.exe` — it does not read `PATHEXT`. So on any machine
    where an agent CLI is installed as a `.cmd` shim, which is what `npm -g` produces and
    what both CLIs document, Flow reported a CLI it could never start.

    It never showed up here because this machine installed both through WinGet, which
    puts real `codex.EXE` and `claude.EXE` on the path. One install method away from a
    product whose headline feature does not work at all.
    """

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="cmd-shim-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        old = os.environ["PATH"]
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        os.environ["PATH"] = self.dir + os.pathsep + old

    def _shim(self, name: str, says: str = "SHIMMED") -> str:
        p = Path(self.dir) / f"{name}.cmd"
        p.write_text(f"@echo {says}\n", encoding="utf-8")
        return str(p)

    def test_a_cmd_shim_is_found_and_then_refused(self):
        # This used to assert the shim *ran*, which was the right answer to the WinError 2
        # defect and the wrong answer to the one underneath it: a `.cmd` starts fine and
        # then truncates the prompt at the first newline. Resolution is still the thing
        # being pinned — `which` finds it and the launch would use what `which` returned —
        # and what changed is that finding it is now a reason to stop.
        self._shim("faketool")
        cli = Cli("faketool", ("faketool",))
        self.assertIsNotNone(shutil.which("faketool"), "which must find the shim")
        out, reason = refine_mod._invoke(cli, "a prompt", timeout=30)
        self.assertIsNone(out)
        self.assertIn("faketool", reason)

    def test_what_which_finds_is_what_available_reports(self):
        # The first half of the invariant, on a real PATH: `which` honours `PATHEXT`, so a
        # `.cmd` on PATH *is* a CLI that has been found — which is what made the old
        # "not on PATH" answer a lie. Whether it may then be called is the refusal's
        # question, one class down, and a different one.
        shim = self._shim("codex")
        self.assertIn("codex", [c.name for c in refine_mod.available()])
        self.assertEqual(shutil.which("codex").lower(), shim.lower())

    def test_the_launch_uses_the_path_the_lookup_returned(self):
        # The second half, stated once: presence and launch must not use two different
        # resolvers. Asserted on the argv rather than by running anything, because on a
        # machine that has a real codex.EXE further down PATH the bare name *does* start
        # something — just not the one `which` found, which is a quieter version of the
        # same bug and would have made a launch-based test pass here.
        found = str(Path(self.dir) / "codex.exe")
        with mock.patch("shutil.which", resolves_to(found)), \
                mock.patch("subprocess.Popen", side_effect=OSError("stopped here")) as run:
            refine_mod._invoke(refine_mod.named("codex"), "a prompt", timeout=30)
        self.assertEqual(run.call_args.args[0][0], found)
        self.assertNotEqual(run.call_args.args[0][0], "codex", "the bare name was launched")

    def test_a_cli_that_is_genuinely_absent_still_reports_absent(self):
        # The fix must not paper over the real not-found case with a fabricated path.
        cli = Cli("nosuchtool", ("nosuchtool",))
        self.assertIsNone(shutil.which("nosuchtool"))
        out, reason = refine_mod._invoke(cli, "a prompt", timeout=30)
        self.assertIsNone(out)
        self.assertIn("nosuchtool", reason)


def resolves_to(path: str):
    """A `shutil.which` that resolves every name to `path`, whatever PATH says."""
    return lambda cmd, *a, **kw: path


class TestAShimAnswersAboutNothing(unittest.TestCase):
    """The defect the refusal exists for, proved rather than described.

    A `.cmd` launcher — the shape `npm -g` writes on Windows, and the install both agent
    CLIs document — forwards `%*` through cmd.exe, which stops at the first newline. Every
    prompt this module sends is multi-line, so the CLI receives the framing and none of the
    user's text, **exits 0, and answers fluently about nothing**.

    Kept after the refusal ships, and that is the point of it: the refusal is a claim about
    what cmd.exe does, and a claim about another program's behaviour has to keep being
    measured or it becomes folklore. Windows only, because `.cmd` and cmd.exe are.
    """

    @unittest.skipUnless(sys.platform == "win32",
                         "a .cmd shim is a Windows shape and cmd.exe is what truncates it")
    def test_a_cmd_forwards_only_the_first_line_of_its_argument(self):
        folder = tempfile.mkdtemp(prefix="shim-repro-")
        self.addCleanup(shutil.rmtree, folder, True)
        shim = Path(folder) / "echoer.cmd"
        shim.write_text("@echo off\necho %*\n", encoding="utf-8")

        # The exact argv `_invoke` builds: the executable, then the prompt as one element.
        proc = subprocess.Popen(
            [str(shim), "line one\nline two\nline three"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
        )
        out, _err = proc.communicate(timeout=30)
        self.assertIn("line one", out)
        self.assertNotIn("line three", out,
                         "cmd.exe stopped forwarding at the newline — that is the defect")
        self.assertEqual(proc.returncode, 0, "and it exits 0, which is what makes it silent")


class TestAShimIsRefusedBeforeAnythingStarts(unittest.TestCase):
    """Loud beats fluent-and-wrong (decisions.md, "The npm-shim defect").

    The repair that would actually fix this is per-CLI and cannot be picked on a machine
    with no npm shim of either CLI to verify against, so what ships now is the refusal —
    which is verifiable here, today, with four lines of batch file.
    """

    def _invoke_resolving_to(self, path: str, cli=None):
        with mock.patch("shutil.which", resolves_to(path)), \
                mock.patch("subprocess.Popen", return_value=fake_proc("ok")) as started:
            out, reason = refine_mod._invoke(
                cli or Cli("codex", ("codex", "exec")), "a\nprompt", timeout=30
            )
        return out, reason, started

    def test_no_process_is_started_for_a_cmd(self):
        # Asserted on `Popen` rather than on the return value: a call that was made and
        # then failed would satisfy a check that only read the answer.
        out, _reason, started = self._invoke_resolving_to("C:/npm/codex.cmd")
        self.assertIsNone(out)
        started.assert_not_called()

    def test_nor_for_a_bat(self):
        _out, _reason, started = self._invoke_resolving_to("C:/npm/codex.BAT")
        started.assert_not_called()

    def test_the_reason_names_the_cli_the_cause_and_the_cure(self):
        _out, reason, _started = self._invoke_resolving_to("C:/npm/codex.cmd")
        self.assertIn("codex", reason)
        self.assertIn("npm", reason)  # the cause, in the words of what produced it
        self.assertIn("native", reason)  # the cure

    def test_a_real_executable_is_not_refused(self):
        _out, _reason, started = self._invoke_resolving_to("C:/winget/codex.EXE")
        started.assert_called_once()

    def test_nor_is_an_extensionless_one(self):
        # macOS and Linux, and Windows shims that are not batch files.
        _out, _reason, started = self._invoke_resolving_to("/usr/local/bin/codex")
        started.assert_called_once()

    def test_refine_fails_non_destructively_the_way_everything_else_does(self):
        # Invariant 3. A refusal is still a `(None, reason)`, so the caller keeps the
        # pre-edit draft and a loud failure costs nobody their words.
        with mock.patch("shutil.which", resolves_to("C:/npm/codex.cmd")), \
                mock.patch("subprocess.Popen", return_value=fake_proc("ok")) as started:
            revised, reason = refine_mod.refine("the draft", "make it formal",
                                                cli=Cli("codex", ("codex", "exec")))
        self.assertIsNone(revised)
        self.assertIn("codex", reason)
        started.assert_not_called()

    def test_and_so_does_ask(self):
        with mock.patch("shutil.which", resolves_to("C:/npm/codex.cmd")), \
                mock.patch("subprocess.Popen", return_value=fake_proc("ok")) as started:
            answer, reason = refine_mod.ask("a question",
                                            cli=Cli("codex", ("codex", "exec")))
        self.assertIsNone(answer)
        self.assertIn("codex", reason)
        started.assert_not_called()


class TestStdinIsACapabilityAndNotAGuess(unittest.TestCase):
    """The repair, shipped off by default because nothing here can measure it on.

    A shim that reads its prompt from stdin never sees `%*`, so `stdin_ok` is what makes a
    `.cmd` usable — on a machine where somebody has run that CLI that way. codex is
    measured *hanging* on an open stdin ("Reading additional input from stdin..."), which
    is why `_invoke` pins `stdin=DEVNULL` and why this cannot be a global switch.
    """

    def test_it_is_off_unless_somebody_says_otherwise(self):
        self.assertFalse(Cli("anything", ("anything",)).stdin_ok)

    def test_no_shipped_entry_has_it_on(self):
        # The same discipline `verified` carries: a flag flipped from memory is exactly
        # what the shape rule already forbids. It goes on when a machine has run it.
        for cli in refine_mod.CANDIDATES:
            with self.subTest(cli=cli.name):
                self.assertFalse(cli.stdin_ok)

    def test_a_stdin_cli_is_not_refused_for_being_a_cmd(self):
        cli = Cli("shimmed", ("shimmed",), stdin_ok=True)
        with mock.patch("shutil.which", resolves_to("C:/npm/shimmed.cmd")), \
                mock.patch("subprocess.Popen", return_value=fake_proc("ok")) as started:
            out, _reason = refine_mod._invoke(cli, "a\nprompt", timeout=30)
        self.assertEqual(out, "ok")
        started.assert_called_once()

    def test_the_prompt_leaves_the_argv_when_it_travels_on_stdin(self):
        # Both halves matter. Sending it twice would hand a CLI the prompt as an argument
        # *and* on stdin, which is the truncation plus a duplicate.
        cli = Cli("shimmed", ("shimmed", "run"), stdin_ok=True)
        proc = fake_proc("ok")
        with mock.patch("shutil.which", resolves_to("C:/npm/shimmed.cmd")), \
                mock.patch("subprocess.Popen", return_value=proc) as started:
            refine_mod._invoke(cli, "a\nprompt", timeout=30)
        argv = started.call_args.args[0]
        self.assertEqual(argv, ["C:/npm/shimmed.cmd", "run"])
        self.assertEqual(started.call_args.kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(proc.communicate.call_args.kwargs.get("input"), "a\nprompt")

    def test_kiro_cli_is_not_the_exception(self):
        # The newest verified entry is a native exe and takes its prompt on the argv like
        # the other two. Named here so "the new one" cannot quietly become the first
        # thing to carry an unmeasured flag.
        self.assertFalse(refine_mod.named("kiro-cli").stdin_ok)

    def test_argv_clis_still_get_a_closed_stdin(self):
        # codex hangs on an open one, measured, which is the whole reason this is per-CLI.
        proc = fake_proc("ok")
        with mock.patch("shutil.which", resolves_to("/usr/bin/codex")), \
                mock.patch("subprocess.Popen", return_value=proc) as started:
            refine_mod._invoke(Cli("codex", ("codex", "exec")), "a\nprompt", timeout=30)
        self.assertEqual(started.call_args.args[0][-1], "a\nprompt")
        self.assertEqual(started.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIsNone(proc.communicate.call_args.kwargs.get("input"))
