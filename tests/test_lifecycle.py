"""What happens to the CLI process when nobody is waiting for it any more.

The only tests in the suite that start a real process. Everything else about the CLI
adapter can be proved against a fake, but not this: the defect is that a process
outlives the thing that started it, and a fake process cannot outlive anything.

Two of them are deliberately slow — proving something did *not* happen means waiting
long enough for it to have happened. The margins are sized against a child that would
report itself finished 0.8 s after it starts, which is most of what this module costs
the suite, and it buys the one guarantee no other layer can see.
"""

import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.refine import Cli, _invoke  # noqa: E402
from flow.session import Session  # noqa: E402

#: Sleeps, then reports that it got to the end. Stands in for a CLI call in flight.
_SLEEPER = (
    "import pathlib, sys, time\n"
    "pathlib.Path(sys.argv[1]).write_text('x')\n"
    "time.sleep(float(sys.argv[2]))\n"
    "pathlib.Path(sys.argv[3]).write_text('x')\n"
)

#: What `codex` actually is: a launcher whose child does the work and outlives it.
#: `sys.argv[2]` is the grandchild's own script, so this is one file, not two.
_LAUNCHER = (
    "import pathlib, subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[3], sys.argv[4]])\n"
    "pathlib.Path(sys.argv[1]).write_text('x')\n"
    "time.sleep(60)\n"
)

_GRANDCHILD = (
    "import pathlib, sys, time\n"
    "time.sleep(float(sys.argv[1]))\n"
    "pathlib.Path(sys.argv[2]).write_text('x')\n"
)

#: How long the grandchild sleeps before claiming it finished, and how long a test
#: waits before believing it never will.
CHILD_SEC = 0.8
PATIENCE_SEC = 2.0


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeAsr:
    def load(self) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def path(self, name: str) -> Path:
        return self.dir / name


class TestQuittingDoesNotWaitForTheCli(Temp):
    """`Session.close()` used to leave the refine thread inside `subprocess.run`.

    Nothing crashed, which is why it survived: the app window vanished and a `codex`
    kept running behind it, up to `TIMEOUT_SEC`, on a rewrite with no reader left.
    """

    def test_closing_the_session_abandons_a_rewrite_in_flight(self):
        started, done = self.path("started"), self.path("done")
        sleeper = Cli("sleeper", (sys.executable, "-c", _SLEEPER, str(started),
                                  "10", str(done)))
        s = Session(asr=FakeAsr(), mic=FakeMic())
        with mock.patch("flow.refine.available", return_value=[sleeper]):
            s.draft.set("widen the column")
            s._after_draft_change()
            s._route("make it more formal")
            self.assertTrue(wait_for(started.exists), "the CLI never started")
            worker = next(t for t in threading.enumerate() if t.name == "refine")
            s.close()
            worker.join(3.0)
        self.assertFalse(worker.is_alive(), "the call outlived the session it was for")
        self.assertFalse(done.exists(), "the child ran on after the session closed")

    def test_a_call_started_after_close_never_launches(self):
        # The thread can lose the race to `close()`. Spawning a process for a session
        # that is already gone is the same defect, one scheduling slot later.
        started, done = self.path("started"), self.path("done")
        sleeper = Cli("sleeper", (sys.executable, "-c", _SLEEPER, str(started),
                                  "10", str(done)))
        cancel = threading.Event()
        cancel.set()
        out, reason = _invoke(sleeper, "prompt", timeout=10.0, cancel=cancel)
        self.assertIsNone(out)
        self.assertIn("cancelled", reason)
        self.assertFalse(started.exists(), "a process was started for nobody")


class TestKillingReachesWhatTheCliStarted(Temp):
    """`proc.kill()` reaches the launcher, not the launcher's child.

    `codex` is a shim that runs `node`, so killing what Flow launched left the model
    call running — and holding the pipe it inherited, so the read that was supposed to
    end would have blocked on it anyway.
    """

    def launcher(self) -> tuple[Cli, Path, Path]:
        started, marker = self.path("started"), self.path("grandchild")
        return Cli("launcher", (sys.executable, "-c", _LAUNCHER, str(started),
                                _GRANDCHILD, str(CHILD_SEC), str(marker))), \
            started, marker

    def test_a_timeout_ends_the_grandchild_too(self):
        cli, started, marker = self.launcher()
        began = time.perf_counter()
        out, reason = _invoke(cli, "prompt", timeout=0.4)
        elapsed = time.perf_counter() - began
        self.assertIsNone(out)
        self.assertIn("timed out", reason)
        self.assertLess(elapsed, PATIENCE_SEC, "the timeout waited on the grandchild")
        self.assertTrue(started.exists(), "the launcher never ran")
        time.sleep(PATIENCE_SEC)
        self.assertFalse(marker.exists(), "the CLI's own child survived the timeout")

    def test_a_cancel_ends_the_grandchild_too(self):
        cli, started, marker = self.launcher()
        cancel = threading.Event()
        result: list = []
        worker = threading.Thread(
            target=lambda: result.append(
                _invoke(cli, "prompt", timeout=30.0, cancel=cancel)),
            daemon=True,
        )
        worker.start()
        self.assertTrue(wait_for(started.exists), "the launcher never ran")
        cancel.set()
        worker.join(3.0)
        self.assertFalse(worker.is_alive(), "cancelling did not return")
        self.assertIn("cancelled", result[0][1])
        time.sleep(PATIENCE_SEC)
        self.assertFalse(marker.exists(), "the CLI's own child survived the cancel")


class TestACliMayNeedLongerThanTheGlobal(Temp):
    """`Cli.timeout_sec`, proved against a real slow child rather than a patched clock.

    kiro-cli spawns the project's MCP servers on every call — 4.3 s in a bare directory,
    **35.8 s** inside a workspace whose `.kiro` settings declare them — so the global 20 s
    killed the call at second twenty in exactly the workspaces the workshop is for. A wait
    is a wait, so it is measured here where the other real processes are, at seconds the
    suite can afford: this pins that the number `_invoke` waits comes from the entry, and
    a live 36-second call would only prove that this machine is slow.
    """

    def child(self, sleep: float) -> tuple[Cli, Path]:
        done = self.path(f"done-{sleep}")
        return Cli("slow", (sys.executable, "-c", _SLEEPER, str(self.path("started")),
                            str(sleep), str(done))), done

    def test_an_entry_that_declares_longer_gets_it(self):
        # The defect, inverted: 0.4 s of caller budget against a child that needs 0.8,
        # and the entry's own 1.2 is what carries it. Before the field existed there was
        # nowhere to say this, and the call died at the caller's number every time.
        cli, done = self.child(0.8)
        cli = Cli(cli.name, cli.argv, timeout_sec=1.2)
        began = time.perf_counter()
        out, reason = _invoke(cli, "prompt", timeout=0.4)
        elapsed = time.perf_counter() - began
        self.assertEqual(reason, "", "the entry's own timeout was not honoured")
        self.assertIsNotNone(out)
        self.assertGreater(elapsed, 0.4, "it cannot have waited out the child in 0.4 s")

    def test_an_entry_without_one_still_takes_the_callers(self):
        # The other direction, so the floor cannot pass this by being unconditional.
        cli, done = self.child(10.0)
        out, reason = _invoke(cli, "prompt", timeout=0.4)
        self.assertIsNone(out)
        self.assertIn("timed out after 0s", reason)

    def test_the_floor_never_shortens_a_longer_caller(self):
        # `--cli-timeout` is documented as the knob that *raises* the wait. An entry
        # declaring 0.2 must not be able to take that away from the person who asked.
        cli, done = self.child(0.6)
        cli = Cli(cli.name, cli.argv, timeout_sec=0.2)
        out, reason = _invoke(cli, "prompt", timeout=5.0)
        self.assertEqual(reason, "", "a per-CLI value shortened the caller's budget")
        self.assertIsNotNone(out)

    def test_the_note_names_the_seconds_it_actually_waited(self):
        # Not the constant and not the caller's number: with the wait per-CLI, a message
        # quoting either would be right about most entries and wrong about the only one
        # that ever needed saying.
        cli, done = self.child(10.0)
        cli = Cli(cli.name, cli.argv, timeout_sec=1.0)
        out, reason = _invoke(cli, "prompt", timeout=0.4)
        self.assertIsNone(out)
        self.assertEqual(reason, "slow timed out after 1s")


class TestTheOrdinaryCallIsUnchanged(Temp):
    """The helper is one call site for two functions, not a backend. These pin that
    the shape the guards depend on came through the rewrite intact."""

    def test_stdout_comes_back_whole(self):
        echo = Cli("echo", (sys.executable, "-c",
                            "import sys; sys.stdout.write('REVISED')"))
        out, reason = _invoke(echo, "prompt", timeout=10.0)
        self.assertEqual(out, "REVISED")
        self.assertEqual(reason, "")

    def test_a_nonzero_exit_names_the_first_line_of_stderr(self):
        failing = Cli("failing", (sys.executable, "-c",
                                  "import sys; sys.stderr.write('not logged in\\nmore');"
                                  " sys.exit(3)"))
        out, reason = _invoke(failing, "prompt", timeout=10.0)
        self.assertIsNone(out)
        self.assertIn("exited 3", reason)
        self.assertIn("not logged in", reason)
        self.assertNotIn("more", reason)

    def test_a_missing_executable_is_reported_not_raised(self):
        out, reason = _invoke(Cli("ghost", ("definitely-not-on-path-flow",)),
                              "prompt", timeout=10.0)
        self.assertIsNone(out)
        self.assertIn("failed to start", reason)

    def test_output_larger_than_a_pipe_buffer_does_not_deadlock(self):
        # The reason the wait is `communicate` and not `proc.wait`: a child that fills
        # the pipe blocks forever, and a hang is the failure this whole item is about.
        big = Cli("big", (sys.executable, "-c",
                          "import sys; sys.stdout.write('y' * 200000);"
                          " sys.stderr.write('z' * 200000)"))
        out, reason = _invoke(big, "prompt", timeout=15.0)
        self.assertEqual(reason, "")
        self.assertEqual(len(out), 200000)


#: Reads the whole of stdin and writes it back. The other half of a `stdin_ok` CLI, and
#: it has to be a real process for the same reason everything else in this module does:
#: a pipe that is opened, written and closed is not something a mock can be wrong about.
_ECHOES_STDIN = "import sys; sys.stdout.write(sys.stdin.read())"

MULTILINE = ("Repeat the SECRET below verbatim and nothing else.\n\n"
             "SECRET:\nmarmalade-42")


class TestThePromptCanTravelOnStdin(Temp):
    """`stdin_ok`, proved on a real executable rather than on a patched `Popen`.

    A `.cmd` shim truncates an argv prompt at the first newline (`test_refine.py`), and
    the repair the decision stages is per-CLI stdin delivery. This is the delivery half:
    pipe, write, close, and the whole multi-line prompt arrives.
    """

    def test_the_whole_multi_line_prompt_arrives(self):
        reader = Cli("reader", (sys.executable, "-c", _ECHOES_STDIN), stdin_ok=True)
        out, reason = _invoke(reader, MULTILINE, timeout=15.0)
        self.assertEqual(reason, "")
        self.assertEqual(out, MULTILINE)
        # The leg that matters, named the way NEEDS_YOU names it: the last line of a
        # multi-line prompt is what a shim loses, and losing it is silent.
        self.assertIn("marmalade-42", out)

    def test_the_prompt_is_not_also_passed_as_an_argument(self):
        # Sent twice is the truncation plus a duplicate. This child prints its argv, so
        # what it says is what it actually received.
        argv_printer = Cli("argv", (sys.executable, "-c",
                                    "import sys; print(len(sys.argv))"), stdin_ok=True)
        out, reason = _invoke(argv_printer, MULTILINE, timeout=15.0)
        self.assertEqual(reason, "")
        self.assertEqual(out.strip(), "1", "the prompt was passed on the argv as well")

    def test_a_slow_reader_still_gets_its_input(self):
        # `_invoke` polls `communicate` in a loop, and `communicate` may carry `input`
        # exactly once — a second call with it raises "Cannot send input after starting
        # communication". A child that outlives the first poll is what finds that.
        slow = Cli("slow", (sys.executable, "-c",
                            "import sys, time; time.sleep(0.6);"
                            " sys.stdout.write(sys.stdin.read())"), stdin_ok=True)
        out, reason = _invoke(slow, MULTILINE, timeout=15.0)
        self.assertEqual(reason, "")
        self.assertEqual(out, MULTILINE)

    @unittest.skipUnless(sys.platform == "win32",
                         "a .cmd shim is a Windows shape; there is nothing to rescue "
                         "elsewhere")
    def test_a_cmd_shim_that_reads_stdin_is_usable_again(self):
        # The whole point of the capability, end to end: the same launcher shape that
        # loses everything after the first newline on the argv gets the prompt whole.
        folder = tempfile.mkdtemp(prefix="stdin-shim-")
        self.addCleanup(shutil.rmtree, folder, True)
        shim = Path(folder) / "reader.cmd"
        shim.write_text(f'@echo off\n"{sys.executable}" -c "{_ECHOES_STDIN}"\n',
                        encoding="utf-8")
        cli = Cli("reader", (str(shim),), stdin_ok=True)
        out, reason = _invoke(cli, MULTILINE, timeout=20.0)
        self.assertEqual(reason, "", "a stdin CLI must not be refused for being a .cmd")
        self.assertIn("marmalade-42", out)


if __name__ == "__main__":
    unittest.main()
