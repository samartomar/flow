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

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path

# Not a new dependency and not a test-only one: `uv.lock` carries PyYAML twice over as a
# transitive of `faster-whisper` (ctranslate2 requires it, and so does huggingface-hub),
# so it is present anywhere `flow` can be imported at all. What it buys is that the
# workflow and the manifests are *parsed* below rather than string-matched, so a file this
# repo breaks fails as a parse error rather than as a substring that happens to survive.
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
LICENSE = ROOT / "LICENSE"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "guide.md"
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"
SCOOP = ROOT / "packaging" / "scoop" / "flow.json"
WINGET = ROOT / "packaging" / "winget"

#: The one asset name every one of these files has to agree on. It never changes between
#: versions on purpose, which is what makes `releases/latest/download/...` true forever.
ASSET = "flow-windows-x64.zip"

#: The exe's path *inside* that zip. Not a guess: `packaging/flow.spec` names both the
#: COLLECT directory and the exe `flow`, and the workflow compresses `dist/flow` rather
#: than `dist/flow/*`, so the directory itself is the archive's root entry.
IN_ZIP_EXE = "flow\\flow.exe"


def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def scoop() -> dict:
    return json.loads(SCOOP.read_text(encoding="utf-8"))


def winget(name: str) -> dict:
    """One of the three files a winget submission is made of."""
    return yaml.safe_load((WINGET / name).read_text(encoding="utf-8"))


def asset_url() -> str:
    """The versioned download, built from the metadata rather than typed a third time."""
    project = pyproject()["project"]
    repo = project["urls"]["Repository"]
    return f"{repo}/releases/download/v{project['version']}/{ASSET}"


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

    def test_which_platforms_get_what_is_stated_before_the_feature_tour(self):
        # This asked for "Windows" and "macOS" inside the install section, which was the
        # right shape while the answer was "Windows, and nothing else runs". It is not:
        # `__main__.py` starts Flow Lite off Windows rather than refusing, and a README
        # that omits that turns working software into software a Mac user never tries.
        #
        # So the region checked is install through to the feature tour — the part read by
        # someone deciding whether this runs at all — and both halves of the answer have
        # to be in it.
        deciding = self.readme.split("## Install", 1)[1].split("## The loop", 1)[0]
        self.assertIn("Windows", deciding)
        self.assertIn("macOS", deciding)
        self.assertIn("Lite", deciding)

    def test_and_that_the_agent_cli_is_optional(self):
        install = self.readme.split("## Install", 1)[1].split("\n## ", 1)[0]
        for phrase in ("codex", "claude", "PATH"):
            self.assertIn(phrase, install, phrase)

    def test_install_comes_before_the_reference_material(self):
        # "At the top" as a check rather than a hope: someone who arrived to try it
        # should not have to scroll past the flag table to find out how.
        #
        # The flag table used to be further down this same file. On 2026-08-09 the README
        # went from 1,266 lines to a landing page and the reference material moved to
        # `docs/guide.md`, which is a stronger version of what this test wanted — so what
        # it checks now is that the README stayed a landing page: install above, and the
        # depth reached by a link rather than by scrolling.
        self.assertLess(self.readme.index("## Install"), self.readme.index("## Docs"))
        self.assertIn("docs/guide.md", self.readme)
        self.assertNotIn("### Flags", self.readme)

    def test_and_the_guide_still_leads_with_install_too(self):
        guide = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
        self.assertLess(guide.index("## Install"), guide.index("### Flags"))
        self.assertLess(guide.index("## Install"), guide.index("## Running it"))


class TestTheFlagTableIsTheFlags(unittest.TestCase):
    """Every flag the parser accepts, in the table that claims to list them.

    The table drifted by two before anyone noticed: `--decode-device` and `--lite` were
    both parsed and neither was written down, and `--lite` is the whole reason Flow runs
    on a Mac at all. A reference table missing a row is worse than no table, because it
    reads as a complete list — so the parser is asked rather than trusted.
    """

    @classmethod
    def setUpClass(cls):
        import contextlib
        import importlib
        import io as _io

        # The parser is built inside `main()`, so `--help` is how it is reached without a
        # desktop. Its text is the same on every platform: nothing above argparse branches
        # on `sys.platform` any more.
        with contextlib.redirect_stdout(_io.StringIO()) as out:
            with contextlib.suppress(SystemExit):
                importlib.import_module("flow.__main__").main(["--help"])
        cls.parsed = set(re.findall(r"^\s+(--[a-z0-9-]+)", out.getvalue(), re.M))
        cls.parsed.discard("--help")
        cls.table = set(re.findall(r"^\| `(--[a-z0-9-]+)", GUIDE.read_text(
            encoding="utf-8"), re.M))
        assert cls.parsed, "no flags came back from --help"

    def test_every_flag_the_parser_takes_is_written_down(self):
        self.assertEqual(self.parsed - self.table, set())

    def test_and_the_table_invents_none(self):
        self.assertEqual(self.table - self.parsed, set())


class TestTheReleaseWorkflow(unittest.TestCase):
    """The three files that have to agree about one download.

    The README names an artifact, the workflow builds it, and the spec says what goes
    inside — and none of them imports the others, so nothing but a check like this
    notices when one is renamed. The failure it prevents is quiet and total: a Releases
    page whose only asset is called something the README never mentions.
    """

    WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
    SPEC = ROOT / "packaging" / "flow.spec"

    @classmethod
    def setUpClass(cls):
        cls.yml = cls.WORKFLOW.read_text(encoding="utf-8")

    def test_the_workflow_and_the_spec_are_both_committed(self):
        self.assertTrue(self.WORKFLOW.is_file())
        self.assertTrue(self.SPEC.is_file())

    def test_it_builds_the_artifact_the_readme_sends_people_to(self):
        self.assertIn("flow-windows-x64.zip", self.yml)
        self.assertIn("flow-windows-x64.zip",
                      README.read_text(encoding="utf-8"))

    def test_and_builds_it_from_the_spec_that_is_in_the_repo(self):
        self.assertIn("packaging/flow.spec", self.yml)

    def test_the_suite_runs_before_the_build(self):
        # Order, not presence. A gate after the build is a gate that reports on a zip
        # already sitting in the release.
        gate = self.yml.index("unittest discover")
        build = self.yml.index("pyinstaller --noconfirm")
        self.assertLess(gate, build)

    def test_the_version_is_read_rather_than_typed(self):
        # The tag and pyproject have to be the same number, and the workflow is where
        # that is enforced — hand-typing it into the workflow is the mistake this
        # prevents, not the one it catches.
        self.assertIn("pyproject.toml", self.yml)
        self.assertIn("GITHUB_REF_NAME", self.yml)
        self.assertNotIn(pyproject()["project"]["version"], self.yml)

    def test_only_a_tag_triggers_it(self):
        self.assertIn('tags: ["v*"]', self.yml)

    def test_the_bundle_is_onedir_and_unsquashed(self):
        # onefile trips AV heuristics and pays an unpack per launch; UPX is the single
        # strongest AV signal there is, and this build is already unsigned.
        spec = self.SPEC.read_text(encoding="utf-8")
        self.assertIn("exclude_binaries=True", spec)
        self.assertNotIn("upx=True", spec)

    def test_the_bundle_carries_the_metadata_the_version_flag_reads(self):
        # `flow --version` is `importlib.metadata.version("flow")`, and PyInstaller
        # collects modules rather than distributions — so without `copy_metadata` the exe
        # answers "no package metadata". That is the worst copy to leave unable to name
        # itself: the zip is what a stranger downloads, the link always serves the newest
        # one, and the exe is the only thing that can tell them which they got.
        spec = self.SPEC.read_text(encoding="utf-8")
        self.assertIn("copy_metadata", spec)
        self.assertIn('copy_metadata("flow")', spec)

    def test_and_the_models_are_not_in_it(self):
        # 605 MiB of weights that every other install downloads on first use. If a
        # future spec starts bundling them, the README's "not in the zip" paragraph is
        # a lie and this is where that gets caught.
        spec = self.SPEC.read_text(encoding="utf-8")
        for name in ("base.en", "small.en"):
            self.assertNotIn(f'"{name}"', spec, name)


if __name__ == "__main__":
    unittest.main()


#: What the sdist may weigh, compressed. The product is 19 files and 536 KB; the bound is
#: generous against that and still an order of magnitude under what was shipping.
SDIST_MAX_BYTES = 2_000_000


class TestTheSdistCarriesOnlyWhatAnInstallNeeds(unittest.TestCase):
    """RELEASE-07: `.bench/` is the owner's decoded speech, and it shipped.

    Measured on the tree of 2026-08-03, before this: **15,603,458 B compressed, 384
    files**, of which `.bench/` was 82 files and 14.7 MB and `.claude/` was 185 files and
    16.7 MB — the two of them 93% of the bytes, against 19 files and 536 KB of `flow/`.
    The audit filed it as a size complaint. The size is the smaller half: a benchmark
    corpus of recorded speech is a recording of the person who recorded it, and an sdist
    is the artifact `uv tool install git+...` builds.

    This builds the real thing rather than reading the config, because the config is a
    claim about what hatchling will do and this is what it did. It costs about a second,
    which is what the only instrument that can be wrong about the answer is worth.
    """

    @classmethod
    def setUpClass(cls):
        uv = shutil.which("uv")
        if uv is None:  # the suite is run through `uv run`, so this is theoretical
            raise unittest.SkipTest("uv is not on PATH; nothing can build an sdist")
        cls._tmp = tempfile.TemporaryDirectory()
        out = subprocess.run(
            [uv, "build", "--sdist", "--out-dir", cls._tmp.name],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        )
        if out.returncode != 0:
            cls._tmp.cleanup()
            raise unittest.SkipTest(f"uv build failed: {out.stderr[-300:]}")
        cls.tarball = next(Path(cls._tmp.name).glob("*.tar.gz"))
        with tarfile.open(cls.tarball) as t:
            cls.names = [m.name for m in t.getmembers() if m.isfile()]

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_tmp"):
            cls._tmp.cleanup()

    def carried(self, fragment: str) -> list[str]:
        return [n for n in self.names if fragment in n]

    def test_the_recorded_speech_is_not_in_it(self):
        self.assertEqual(self.carried("/.bench/"), [])

    def test_nor_is_the_agent_working_directory(self):
        # Bigger than `.bench/` and nobody's business: transcripts, settings and
        # whatever a session wrote. Found by the item 46 validation rebuild, not by the
        # audit, which is why it is named here rather than inferred from a pattern.
        self.assertEqual(self.carried("/.claude/"), [])

    def test_nor_the_two_files_that_are_this_round_talking_to_itself(self):
        for name in ("LOOP_PLAN.md", "NEEDS_YOU.md"):
            with self.subTest(name=name):
                self.assertEqual(self.carried(f"/{name}"), [])

    def test_the_thing_being_installed_is_still_in_it(self):
        # The half a whitelist gets wrong. An sdist that excludes the package is a
        # smaller failure to notice than one that ships too much.
        for needed in ("/flow/__main__.py", "/pyproject.toml", "/LICENSE",
                       "/README.md"):
            with self.subTest(needed=needed):
                self.assertTrue(self.carried(needed), f"{needed} was excluded")

    def test_it_is_small_enough_that_nobody_has_to_think_about_it(self):
        size = self.tarball.stat().st_size
        self.assertLess(size, SDIST_MAX_BYTES, f"{size:,} B")


class TestThePyprojectSaysSoOutLoud(unittest.TestCase):
    """The same facts where a reviewer reads them, and in a form a diff shows.

    The build test above is the one that cannot be fooled; this one is what fails in a
    pull request when somebody deletes a line, without waiting to find out what
    hatchling made of it.
    """

    def excluded(self) -> list[str]:
        sdist = pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"]
        return sdist["exclude"]

    def test_every_directory_the_item_named_is_excluded(self):
        for path in (".bench/", ".claude/", "tests/", "LOOP_PLAN.md",
                     "NEEDS_YOU.md", "docs/decisions.md", "docs/history/"):
            with self.subTest(path=path):
                self.assertIn(path, self.excluded())

    def test_the_wheel_is_untouched_and_still_packages_the_module(self):
        # Two targets, two questions. The wheel never carried any of this — it packages
        # `flow` and nothing else — so a change here that quietly narrowed it would be
        # fixing the wrong artifact.
        wheel = pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]
        self.assertEqual(wheel["packages"], ["flow"])


class TestTheSuiteGatesEveryPush(unittest.TestCase):
    """RELEASE-01: the release path claimed things nothing checked until a tag.

    `release.yml` runs the suite, and it only runs on `v*` — so between tags there was
    no gate at all, and the first thing to find a broken push was a release. This is the
    gate that runs before anything is called a version.
    """

    CI = ROOT / ".github" / "workflows" / "ci.yml"

    @classmethod
    def setUpClass(cls):
        cls.yml = cls.CI.read_text(encoding="utf-8") if cls.CI.is_file() else ""

    def test_there_is_one(self):
        self.assertTrue(self.CI.is_file(), "no CI workflow")

    def test_it_runs_on_a_pull_request_and_on_main(self):
        self.assertIn("pull_request:", self.yml)
        self.assertIn("push:", self.yml)
        self.assertIn("main", self.yml)

    def test_it_is_not_gated_on_a_tag(self):
        # The defect, stated as a rule: a gate that waits for a tag is the release.
        self.assertNotIn('tags:', self.yml)

    def test_it_runs_on_the_three_platforms_the_suite_claims(self):
        # Item 34's law — the platform decides what imports, `lite` decides what
        # happens — is a claim about three operating systems, and it was only ever run
        # on one of them.
        for runner in ("windows-latest", "macos-latest", "ubuntu-latest"):
            with self.subTest(runner=runner):
                self.assertIn(runner, self.yml)

    def test_the_install_is_locked(self):
        # `uv sync --frozen` and not `uv sync`: a CI run that silently resolves a newer
        # dependency is testing a tree nobody has.
        self.assertIn("uv sync --frozen", self.yml)

    def test_it_runs_the_suite_the_gate_is_named_for(self):
        self.assertIn("unittest discover", self.yml)

    def test_and_the_two_checks_that_catch_what_a_unit_test_cannot(self):
        # `compileall` catches a syntax error in a module no test imports; `--help`
        # catches an entry point that cannot boot at all.
        self.assertIn("compileall", self.yml)
        self.assertIn("--help", self.yml)

    def test_the_release_workflow_is_still_a_deliberate_act(self):
        # Adding a push gate must not turn tagging into something that happens by
        # itself. Release stays tag-only.
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8")
        self.assertIn('tags: ["v*"]', release)
        self.assertNotIn("pull_request", release)


class TestTheScoopManifest(unittest.TestCase):
    """A file whose whole job is to be right about a URL nothing here dereferences.

    Homebrew was the most-upvoted request in the competitor's tracker; on Windows that
    request is Scoop and winget, and both are answered by a small file naming a download,
    its checksum and the executable inside it. `packaging/PUBLISHING.md` is how it gets
    submitted; this is what stops it going stale afterwards.

    The failure it prevents is quiet rather than loud. `pyproject.toml` moves to 0.6.0,
    the tag moves, the workflow builds and attaches the new zip, and this manifest still
    names v0.5.1, which still downloads, still installs and still runs. Nobody finds out
    from an error; they find out from a bug report about something fixed two versions ago.

    So the version is read out of `pyproject.toml` and the URL rebuilt from it rather than
    typed twice, which is the trick `TestTheInstallSection` already plays on the README.
    """

    def test_it_is_committed_and_it_parses(self):
        self.assertTrue(SCOOP.is_file(), "no Scoop manifest to submit")
        self.assertIsInstance(scoop(), dict)

    def test_the_version_it_names_is_the_version_pyproject_names(self):
        self.assertEqual(scoop()["version"], pyproject()["project"]["version"])

    def test_and_the_download_is_the_release_asset_for_that_version(self):
        self.assertEqual(scoop()["architecture"]["64bit"]["url"], asset_url())

    def test_the_metadata_agrees_with_the_metadata_beside_it(self):
        # Same argument as the licence tests above: two places to state one fact is one
        # place to get it wrong, and this is the copy strangers read in a search result.
        manifest, project = scoop(), pyproject()["project"]
        self.assertEqual(manifest["license"], project["license"])
        self.assertEqual(manifest["homepage"], project["urls"]["Repository"])

    def test_checkver_watches_this_repository(self):
        self.assertEqual(scoop()["checkver"]["github"],
                         pyproject()["project"]["urls"]["Repository"])

    def test_and_autoupdate_templates_the_version_rather_than_freezing_it(self):
        # The half of the manifest that has to survive the *next* release without being
        # edited. A literal version number in here is the same defect as one in the
        # workflow, and it is checked the same way.
        auto = scoop()["autoupdate"]
        url = auto["architecture"]["64bit"]["url"]
        self.assertIn("$version", url)
        self.assertNotIn(pyproject()["project"]["version"], url)
        # And the hash comes from the `.sha256` the workflow now uploads, so a version
        # bump costs one small request instead of re-downloading 126 MB to learn a number.
        self.assertEqual(auto["hash"]["url"], "$url.sha256")


class TestTheWingetManifests(unittest.TestCase):
    """Three files that are one submission, and every one of them repeats the version.

    winget will not take a package as a single file: a version manifest, an installer
    manifest and a locale manifest go up together, and a disagreement between them is
    rejected before a human reads the pull request. Which means the version is written
    three more times, in three files that cannot read `pyproject.toml`, and the drift this
    guards against is the same one the Scoop manifest has with three times the surface.
    """

    NAMES = ("SamarTomar.Flow.yaml",
             "SamarTomar.Flow.installer.yaml",
             "SamarTomar.Flow.locale.en-US.yaml")

    def test_all_three_files_a_submission_needs_are_committed(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertTrue((WINGET / name).is_file(), name)

    def test_they_agree_on_which_package_this_is(self):
        identifiers = {winget(name)["PackageIdentifier"] for name in self.NAMES}
        self.assertEqual(identifiers, {"SamarTomar.Flow"})

    def test_and_all_three_name_the_version_pyproject_names(self):
        version = pyproject()["project"]["version"]
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertEqual(str(winget(name)["PackageVersion"]), version)

    def test_the_installer_downloads_the_release_asset_for_that_version(self):
        installer = winget("SamarTomar.Flow.installer.yaml")["Installers"][0]
        self.assertEqual(installer["InstallerUrl"], asset_url())
        self.assertEqual(installer["Architecture"], "x64")

    def test_and_describes_it_as_what_it_is(self):
        # A zip with a portable exe inside, which is the honest description of a
        # PyInstaller onedir tree: it runs from wherever it is unpacked, writes no
        # registry keys and has nothing to uninstall.
        doc = winget("SamarTomar.Flow.installer.yaml")
        self.assertEqual(doc["InstallerType"], "zip")
        self.assertEqual(doc["NestedInstallerType"], "portable")

    def test_the_licence_it_publishes_is_the_licence_in_the_repository(self):
        # Same failure as a wheel whose METADATA says Apache while LICENSE says MIT,
        # except this copy is the one shown to everyone running `winget show`.
        locale = winget("SamarTomar.Flow.locale.en-US.yaml")
        self.assertEqual(locale["License"], pyproject()["project"]["license"])
        self.assertEqual(locale["PackageUrl"],
                         pyproject()["project"]["urls"]["Repository"])


class TestBothManifestsPointAtTheSameFileInTheSameZip(unittest.TestCase):
    """`flow.exe` is not at the root of the zip, and two package managers depend on that.

    The path is established by two lines that live nowhere near each other.
    `packaging/flow.spec` names the COLLECT directory and the exe `flow`, so PyInstaller
    writes `dist/flow/flow.exe`, which is the path the workflow then runs `--help` against. And
    `Compress-Archive -Path dist/flow` names the *directory*, not its contents, so the
    directory itself becomes the archive's root entry and the exe sits one level down.

    Scoop's `bin` and winget's `RelativeFilePath` both encode that conclusion. Neither can
    check it, and getting it wrong does not fail loudly: Scoop shims a path that is not
    there and winget installs a package whose command does not exist. So the premise is
    asserted here, beside the two files that depend on it. Change the zip's shape and
    this fails, naming the manifests that have to move with it.
    """

    @classmethod
    def setUpClass(cls):
        cls.yml = RELEASE_YML.read_text(encoding="utf-8")

    def test_the_workflow_still_zips_the_directory_and_not_its_contents(self):
        self.assertIn(f"Compress-Archive -Path dist/flow -DestinationPath {ASSET}",
                      self.yml)
        # `dist/flow/*` would flatten the archive and silently invalidate both manifests.
        self.assertNotIn("dist/flow/*", self.yml)

    def test_and_the_bundle_it_zips_is_still_the_one_the_spec_builds(self):
        # The other half of the premise: the exe is `flow.exe` inside a directory called
        # `flow`, which is what makes the in-zip path one level deep rather than two or
        # none. The workflow launches exactly that path before it zips anything.
        self.assertIn("dist/flow/flow.exe --help", self.yml)
        spec = (ROOT / "packaging" / "flow.spec").read_text(encoding="utf-8")
        self.assertEqual(spec.count('name="flow"'), 2, "EXE and COLLECT both name it")

    def test_and_both_package_managers_name_that_path(self):
        nested = winget("SamarTomar.Flow.installer.yaml")["NestedInstallerFiles"][0]
        self.assertEqual(nested["RelativeFilePath"], IN_ZIP_EXE)
        self.assertEqual(scoop()["bin"], IN_ZIP_EXE)

    def test_and_leave_the_same_command_behind_as_a_source_install(self):
        # `uv tool install` puts `flow` on PATH, so a reader who arrives by either route
        # types the same word. Scoop shims by the exe's basename; winget is told outright.
        nested = winget("SamarTomar.Flow.installer.yaml")["NestedInstallerFiles"][0]
        self.assertEqual(nested["PortableCommandAlias"], "flow")
        self.assertIn("flow", pyproject()["project"]["scripts"])

    def test_and_both_state_the_same_checksum(self):
        # The one number in either file that this repo cannot derive, because it is a
        # fact about a file on a Releases page. `packaging/PUBLISHING.md` is the runbook
        # for filling it; what is checked here is that it is filled the same way in both
        # places, and that it is either the placeholder or something the shape of a
        # SHA-256. A half-pasted hash is the failure that would otherwise ship.
        hashes = {scoop()["architecture"]["64bit"]["hash"],
                  winget("SamarTomar.Flow.installer.yaml")["Installers"][0][
                      "InstallerSha256"]}
        self.assertEqual(len(hashes), 1, f"the two manifests disagree: {hashes}")
        stated = hashes.pop()
        if stated != "FILL-ME-SHA256":
            self.assertRegex(stated, r"^[A-Fa-f0-9]{64}$")


class TestTheReleasePublishesAChecksumBesideTheZip(unittest.TestCase):
    """A package manifest has to state a SHA-256, so the release has to publish one.

    Before this, the number existed only on whichever machine last downloaded the zip,
    which is the wrong place for it: a checksum read off a download proves that the
    download is the download. Computed on the runner, beside the bytes it just built, it
    is worth something, and `winget install` and `scoop install` both refuse an artifact
    that does not match it.

    The workflow is parsed rather than grepped here, because the change added a step to a
    file whose existing gates are load-bearing, and "still valid YAML" is the cheapest
    proof that nothing above it was disturbed.
    """

    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))
        cls.runs = [step.get("run", "") for step in cls.doc["jobs"]["release"]["steps"]]

    def step_running(self, fragment: str) -> int:
        found = [i for i, run in enumerate(self.runs) if fragment in run]
        self.assertEqual(len(found), 1, f"{fragment!r} runs in {len(found)} steps")
        return found[0]

    def test_the_workflow_is_still_a_yaml_file_with_a_release_job_in_it(self):
        self.assertIsInstance(self.doc, dict)
        self.assertIn("release", self.doc["jobs"])
        self.assertTrue(self.runs, "the release job has no steps that run anything")

    def test_the_checksum_is_taken_after_the_zip_exists_and_before_it_is_uploaded(self):
        # Order, not presence, for the same reason the suite is asserted to run before
        # the build: a checksum computed at the wrong moment is a checksum of nothing.
        zipped = self.step_running("Compress-Archive")
        hashed = self.step_running("Get-FileHash")
        attached = self.step_running("gh release")
        self.assertLess(zipped, hashed)
        self.assertLess(hashed, attached)

    def test_and_the_line_it_writes_is_the_shape_sha256sum_reads(self):
        # `<hash> *<file>`: the hash, a space, `*` for binary mode, the name. That is what
        # `sha256sum -c` accepts and what Scoop's autoupdate looks for in a hash file, so
        # the format is the interface and not a detail.
        run = self.runs[self.step_running("Get-FileHash")]
        self.assertIn("SHA256", run)
        self.assertIn(f"*{ASSET}", run)
        self.assertIn(f"{ASSET}.sha256", run)
        self.assertIn(".ToLower()", run)

    def test_and_it_goes_up_beside_the_zip_however_the_release_is_made(self):
        # Two branches, because a re-run of a failed release uploads to a release that
        # already exists. A checksum attached in only one of them is the branch nobody
        # tests until the day it runs.
        run = self.runs[self.step_running("gh release")]
        self.assertIn("gh release upload", run)
        self.assertIn("gh release create", run)
        self.assertEqual(run.count(f"{ASSET}.sha256"), 2, run)

    def test_and_no_third_party_action_was_added_to_do_it(self):
        # The workflow's own argument, unchanged: the runner already has `gh` and
        # PowerShell, and this is the workflow that builds what strangers download.
        uses = [step.get("uses", "") for step in self.doc["jobs"]["release"]["steps"]]
        self.assertEqual([u.split("@")[0] for u in uses if u],
                         ["actions/checkout", "astral-sh/setup-uv"])
