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


class TestTheInstallSection(unittest.TestCase):
    """What a stranger reads first, checked against what the project actually is.

    Until the repo went public the README's install line was `uv sync`, which is the
    command for someone who has already cloned — the one thing a reader arriving from a
    link has not done. These assertions are the ones that would have caught that.
    """

    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_the_uv_command_names_the_repository_pyproject_declares(self):
        # Built from the metadata rather than typed twice: a repo that is renamed moves
        # this URL in one place and fails here until the README follows.
        repo = pyproject()["project"]["urls"]["Repository"]
        self.assertIn(f"uv tool install git+{repo}", self.readme)

    def test_and_the_command_that_runs_it_afterwards_is_there_too(self):
        # `uv tool install` puts `flow` on the PATH; a reader who is not told that goes
        # looking for a directory that does not exist.
        self.assertIn("uv tool install", self.readme)
        self.assertRegex(self.readme, r"uv tool install [^\n]+\nflow\b")

    def test_the_binary_download_names_the_artifact_the_release_carries(self):
        self.assertIn("flow-windows-x64.zip", self.readme)
        self.assertIn("/releases", self.readme)

    def test_and_says_what_windows_will_do_the_first_time(self):
        # Unsigned, by decision — signing is a subscription with no buyer today. The
        # honest version of that decision is telling people about the warning before
        # they meet it, rather than letting it look like a virus alert.
        self.assertIn("SmartScreen", self.readme)
        self.assertIn("Run anyway", self.readme)

    def test_windows_only_is_stated_where_someone_deciding_will_read_it(self):
        install = self.readme.split("## Install", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Windows", install)
        self.assertIn("macOS", install)

    def test_and_that_the_agent_cli_is_optional(self):
        install = self.readme.split("## Install", 1)[1].split("\n## ", 1)[0]
        for phrase in ("codex", "claude", "PATH"):
            self.assertIn(phrase, install, phrase)

    def test_install_comes_before_the_reference_material(self):
        # "At the top" as a check rather than a hope: someone who arrived to try it
        # should not have to scroll past the flag table to find out how.
        self.assertLess(self.readme.index("## Install"), self.readme.index("### Flags"))
        self.assertLess(self.readme.index("## Install"),
                        self.readme.index("## Running it"))


if __name__ == "__main__":
    unittest.main()
