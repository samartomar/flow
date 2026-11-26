import subprocess
import sys
import unittest
import uuid
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
        raise SystemExit(main(["--home"]))
""", name],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("opening Flow Home", result.stdout)
            self.assertTrue(owner.requested())
            self.assertFalse(owner.requested())
        with DesktopLaunch(name) as replacement:
            self.assertTrue(replacement.primary)
