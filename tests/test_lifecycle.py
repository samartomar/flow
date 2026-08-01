"""What happens to the CLI process when nobody is waiting for it any more.

The only tests in the suite that start a real process. Everything else about the CLI
adapter can be proved against a fake, but not this: the defect is that a process
outlives the thing that started it, and a fake process cannot outlive anything.

Two of them are deliberately slow — proving something did *not* happen means waiting
long enough for it to have happened. The margins are sized against a child that would
report itself finished 0.8 s after it starts, which is most of what this module costs
the suite, and it buys the one guarantee no other layer can see.
"""

import sys
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


if __name__ == "__main__":
    unittest.main()
