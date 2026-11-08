"""`scripts/voices.py` hands PowerShell nothing it could read as code.

A dev-only script, but it builds a `-Command` string out of a voice name an engine
registered and an output path under wherever the checkout lives. Either can carry a quote,
and inside a single-quoted PowerShell literal a quote ends the string. So every outside
value goes in base64, and the file name is cut down to characters no shell treats
specially.
"""

import base64
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("voices_script", ROOT / "scripts" / "voices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voices = _load()


class TestNoInputReachesPowerShellRaw(unittest.TestCase):
    NAME = "O'Brien; Remove-Item x"
    PATH = Path("C:/Users/it's me/'; calc; '/O'Brien.wav")

    def command(self):
        with mock.patch.object(voices.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)) as run, \
                mock.patch.object(voices, "host", return_value="pwsh"):
            voices.to_wav(self.NAME, self.PATH)
        argv = run.call_args.args[0]
        return argv[argv.index("-Command") + 1]

    def test_neither_the_name_nor_the_path_appears_in_the_command(self):
        script = self.command()
        self.assertNotIn(self.NAME, script)
        self.assertNotIn(str(self.PATH), script)
        self.assertNotIn("O'Brien", script)
        self.assertNotIn("it's", script)

    def test_every_quote_in_it_is_one_the_script_wrote(self):
        # Strip the script's own `FromBase64String('...')` literals: what remains must
        # hold no quote at all, so none came from the inputs.
        script = self.command()
        for b64 in (voices._b64(voices.SAMPLE), voices._b64(self.NAME),
                    voices._b64(str(self.PATH))):
            self.assertIn(f"FromBase64String('{b64}')", script)
            script = script.replace(f"'{b64}'", "")
        self.assertNotIn("'", script)

    def test_and_the_path_decodes_back_to_itself(self):
        b64 = voices._b64(str(self.PATH))
        self.assertEqual(base64.b64decode(b64).decode("utf-8"), str(self.PATH))


class TestTheFileNameIsPlain(unittest.TestCase):
    def test_only_safe_characters_survive(self):
        self.assertEqual(voices.wav_name("Microsoft O'Brien (Natural)"),
                         "Microsoft-O-Brien--Natural.wav")
        self.assertRegex(voices.wav_name(r"../..\x'y" + '"z'), r"^[A-Za-z0-9._-]+\.wav$")

    def test_a_name_with_nothing_safe_in_it_still_gets_a_file(self):
        self.assertEqual(voices.wav_name("'''"), "voice.wav")


if __name__ == "__main__":
    unittest.main()
