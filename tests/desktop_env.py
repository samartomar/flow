"""Keep mocked app launches separate from a developer's running Flow."""

import unittest
import uuid
from unittest import mock

from flow.desktop_launch import DesktopLaunch


def isolate_desktop():
    name = rf"Local\SamarTomar.Flow.Test.{uuid.uuid4()}"
    patch = mock.patch("flow.desktop_launch.DesktopLaunch",
                       side_effect=lambda: DesktopLaunch(name))
    patch.start()
    unittest.addModuleCleanup(patch.stop)
