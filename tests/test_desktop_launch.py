import subprocess
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from flow.desktop_launch import DesktopLaunch


@unittest.skipUnless(sys.platform == "win32", "the desktop launch signal uses Win32")
class TestDesktopLaunch(unittest.TestCase):
    def test_a_second_process_signals_the_owner_and_exits(self):
        name = rf"Local\SamarTomar.Flow.Test.{uuid.uuid4()}"
        with DesktopLaunch(name) as owner:
            self.assertTrue(owner.primary)
            self.assertFalse(owner.requested())
            result = subprocess.run(
                [sys.executable, "-c", """
import sys
from unittest.mock import patch
from flow.desktop_launch import DesktopLaunch
from flow.__main__ import main
with patch("flow.desktop_launch.DesktopLaunch", lambda: DesktopLaunch(sys.argv[1])):
    with patch("flow.__main__._run_app", side_effect=AssertionError("second desktop")):
        raise SystemExit(main(sys.argv[2:]))
""", name, "--home"],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("opening Flow Home", result.stdout)
            self.assertTrue(owner.requested())
            self.assertFalse(owner.requested())
        with DesktopLaunch(name) as replacement:
            self.assertTrue(replacement.primary)

    def test_a_contender_can_take_over_after_the_owner_quits(self):
        name = rf"Local\SamarTomar.Flow.Test.{uuid.uuid4()}"
        contender_ready = threading.Event()
        owner_closed = threading.Event()

        def reopen():
            with DesktopLaunch(name) as contender:
                self.assertFalse(contender.primary)
                contender_ready.set()
                self.assertTrue(owner_closed.wait(5))
                self.assertFalse(contender.reopen())
                self.assertTrue(contender.primary)

        with ThreadPoolExecutor(max_workers=1) as pool:
            with DesktopLaunch(name):
                result = pool.submit(reopen)
                self.assertTrue(contender_ready.wait(5))
            owner_closed.set()
            result.result(timeout=5)
