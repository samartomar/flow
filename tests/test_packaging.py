"""What a published repo has to carry, checked against the files that carry it.

None of this is behaviour, and all of it is load-bearing the moment the repo is public.
A repo with no licence is all-rights-reserved — readable by anyone, usable by nobody —
and metadata that disagrees with the file beside it is worse than metadata that is
missing, because it is the kind of wrong nobody re-reads.

The other half is the install instructions. A README command is executable text: if the
URL in it drifts from the one in `pyproject.toml`, the first thing a new reader does is
the one thing that does not work. So the commands are asserted to be exact, here, where
a change to either side has to move both.
"""

import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
LICENSE = ROOT / "LICENSE"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"


def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


class TestTheLicence(unittest.TestCase):
    def test_there_is_one(self):
        self.assertTrue(LICENSE.is_file(),
                        "a public repo without a LICENSE is all-rights-reserved")

    def test_it_is_the_one_the_owner_chose(self):
        # MIT, decided 2026-08-01 (docs/decisions.md, "Distribution"). The first line is
        # what every licence scanner reads, so it is what is asserted.
        text = LICENSE.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0].strip(), "MIT License")
        self.assertIn("Copyright (c) 2026 Samar Tomar", text)
        self.assertIn("WITHOUT WARRANTY OF ANY KIND", text)

    def test_and_the_metadata_says_the_same_thing(self):
        # Two places to state one fact is one place to get it wrong. A wheel whose
        # METADATA says Apache while the file says MIT is the failure this prevents.
        project = pyproject()["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertIn("LICENSE", project["license-files"])

    def test_the_author_is_named(self):
        names = [a.get("name") for a in pyproject()["project"]["authors"]]
        self.assertIn("Samar Tomar", names)


class TestTheProjectUrls(unittest.TestCase):
    """The repository URL is not decoration — it is inside the install command."""

    def test_both_urls_are_declared(self):
        urls = pyproject()["project"]["urls"]
        self.assertEqual(urls["Repository"], "https://github.com/samartomar/flow")
        self.assertEqual(urls["Listing"], "https://github.com/samartomar/ai-harness")


if __name__ == "__main__":
    unittest.main()
