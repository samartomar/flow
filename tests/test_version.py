"""Which copy this is, and the one flag that asks GitHub about it.

Two flags that both exit before Flow starts, and between them one property worth more
than either: **nothing checks for updates on its own.** `docs/architecture.md`'s "What
leaves the machine" is an enumeration, and an enumeration is only worth reading if it is
complete — so the call-site test below is not decoration, it is the assertion that keeps
the document true. `tests/test_main.py` carries the other half, that a real launch opens
no socket.

The exact printed lines are asserted rather than matched loosely. This is a one-shot
command whose entire output is one line: if the line is wrong, there is nothing else on
screen to correct it, and "prints something about an update" is not a behaviour anybody
can rely on. They are also asserted to encode on a legacy console code page, for the
reason `__main__.say` documents — a `UnicodeEncodeError` in place of an answer is the
failure mode the tag pattern in `flow/version.py` exists to prevent, and GitHub's answer
is the one string here that Flow did not write.
"""

import contextlib
import io
import json
import sys
import tomllib
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow import version as version_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: The version these tests hold, pinned rather than read off the installed metadata.
#: Half this file is about a comparison, and a fixture that moved with every release
#: would take the assertions about that comparison with it.
HERE = "0.5.1"


class _Answer:
    """The two things `check_update` asks of a `urlopen` result, and nothing else."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_Answer":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def answers(body: bytes) -> mock.Mock:
    """A `urlopen` that hands back `body` however it is called."""
    return mock.Mock(return_value=_Answer(body))


def released(tag: str) -> mock.Mock:
    """GitHub answering as it really does: one object, with the tag among its fields."""
    return answers(json.dumps({"tag_name": tag, "name": tag, "draft": False}).encode())


def refuses(error: Exception) -> mock.Mock:
    return mock.Mock(side_effect=error)


def holding(here: str | None):
    """This machine holding version `here`, or `None` for a copy with no metadata.

    `importlib.metadata.version` is patched rather than the module's own `version()`, so
    the resolution under test is the real one — the same seam `test_diag.py` uses.
    """
    if here is None:
        return mock.patch("importlib.metadata.version", side_effect=Exception("nope"))
    return mock.patch("importlib.metadata.version", return_value=here)


def run_flag(argv, urlopen=None, here=HERE):
    """`flow <argv>`, with the metadata and GitHub's answer both decided here."""
    import flow.__main__ as mod

    out = io.StringIO()
    with holding(here), \
            mock.patch("urllib.request.urlopen",
                       urlopen or refuses(AssertionError("asked GitHub"))), \
            contextlib.redirect_stdout(out):
        code = mod.main(list(argv))
    return code, out.getvalue()


def run_version(here=HERE) -> tuple[object, str]:
    """`flow --version`, whose exit is the behaviour, so it is caught rather than raised.

    The opener is booby-trapped as it is everywhere else in this file: the version is
    read off this machine, and asking anybody about it is the other flag's job.
    """
    import flow.__main__ as mod

    out, code = io.StringIO(), "did not exit"
    with holding(here), \
            mock.patch("urllib.request.urlopen",
                       refuses(AssertionError("--version asked GitHub"))), \
            contextlib.redirect_stdout(out):
        try:
            mod.main(["--version"])
        except SystemExit as left:
            code = left.code
    return code, out.getvalue()


def check(urlopen, here=HERE) -> tuple[int, str]:
    """`flow --check-update`, returning the exit code and the one line it printed."""
    code, out = run_flag(["--check-update"], urlopen, here=here)
    assert out.count("\n") == 1, f"one line, not {out.count(chr(10))}: {out!r}"
    return code, out.rstrip("\n")


class TestTheVersionFlagAnswersFromTheMetadata(unittest.TestCase):
    """`flow --version`, which is the question a download link cannot answer.

    The link always serves the newest zip, so the only thing a user cannot find out for
    themselves is which copy is already on their disk. If this resolves to the wrong
    number — or to a traceback — every bug report that quotes it is quoting a fiction.
    """

    def test_it_prints_the_version_and_exits_where_help_exits(self):
        code, _out = run_version("1.2.3")
        self.assertEqual(code, 0)

    def test_and_the_line_is_the_product_and_the_number(self):
        _code, out = run_version("1.2.3")
        self.assertEqual(out, "flow 1.2.3\n")

    def test_the_number_is_the_one_pyproject_carries(self):
        # The source of truth is `pyproject.toml`, because that is what `release.yml`
        # gates a tag against — a flag that answered from anywhere else could disagree
        # with the zip it was built into and nothing would notice.
        if version_mod.version() == version_mod.UNKNOWN:
            raise unittest.SkipTest("flow is not installed here; no metadata to read")
        declared = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
        self.assertEqual(version_mod.version(), declared)

    def test_missing_metadata_is_an_answer_rather_than_a_traceback(self):
        # The source-checkout edge, and the frozen-bundle edge with it: PyInstaller
        # collects modules and not distributions, so a bundle built without
        # `copy_metadata("flow")` lands here too. Defined, both times.
        import importlib.metadata as md

        with mock.patch("importlib.metadata.version",
                        side_effect=md.PackageNotFoundError("flow")):
            self.assertEqual(version_mod.version(), version_mod.UNKNOWN)

    def test_and_so_is_a_metadata_layer_that_raises_something_else(self):
        # A half-written `dist-info` does not raise `PackageNotFoundError`, and nothing
        # about identifying yourself is worth ending a launch over.
        with holding(None):
            self.assertEqual(version_mod.version(), version_mod.UNKNOWN)

    def test_the_flag_still_prints_one_line_when_there_is_no_metadata(self):
        # argparse fills the version text to the terminal width, so a long answer would
        # arrive wrapped — and "one line" is the whole contract of both these flags.
        code, out = run_version(None)
        self.assertEqual(code, 0)
        self.assertEqual(out, f"flow {version_mod.UNKNOWN}\n")


class TestTheUpdateCheckSaysExactlyOneThing(unittest.TestCase):
    """Every answer `--check-update` can give, asserted to the character.

    The exit code is asserted beside each one because it carries what the line cannot:
    0 when the check ran and 1 when it could not, so a script wrapping this can tell
    "nothing newer" from "no answer" without parsing English.
    """

    def test_a_newer_release_is_named_along_with_the_page_it_is_on(self):
        code, line = check(released("v0.6.0"))
        self.assertEqual(code, 0)
        self.assertEqual(line, "flow 0.6.0 is out (you have 0.5.1) - "
                               "https://github.com/samartomar/flow/releases")

    def test_the_same_number_back_is_the_end_of_it(self):
        code, line = check(released("v0.5.1"))
        self.assertEqual(code, 0)
        self.assertEqual(line, "flow 0.5.1 is the newest release")

    def test_a_tag_without_the_v_is_read_the_same_way(self):
        # GitHub hands back whatever was tagged, and `v` is a convention rather than a
        # rule. A leading letter must not be able to turn "same version" into "newer".
        _code, line = check(released("0.5.1"))
        self.assertEqual(line, "flow 0.5.1 is the newest release")

    def test_a_copy_ahead_of_the_newest_tag_is_told_that_rather_than_rounded(self):
        # What a bumped-but-untagged working tree sees. "You are up to date" would be a
        # different fact, and the person holding this copy is the one who would notice.
        code, line = check(released("v0.5.0"))
        self.assertEqual(code, 0)
        self.assertEqual(line, "flow 0.5.1 is newer than the newest release (0.5.0) - "
                               "nothing to update to")

    def test_the_comparison_is_numbers_and_not_text(self):
        # `"0.10.0" < "0.5.1"` as strings, which would hide a release from everybody
        # holding the version before it. The one case where getting this wrong is
        # silent, so it is pinned rather than left to the pair of tests above.
        _code, line = check(released("v0.10.0"))
        self.assertIn("0.10.0 is out", line)

    def test_an_offline_machine_gets_a_reason_and_a_nonzero_exit(self):
        code, line = check(refuses(urllib.error.URLError("no route to host")))
        self.assertEqual(code, 1)
        self.assertEqual(line, "could not check for updates: no answer from GitHub "
                               "within 3s - offline, or blocked")

    def test_a_read_timeout_reads_the_same_as_being_offline(self):
        # Same sentence on purpose: from the prompt they are the same event, and a
        # second wording would be a distinction nobody can act on.
        code, line = check(refuses(TimeoutError("timed out")))
        self.assertEqual(code, 1)
        self.assertIn("no answer from GitHub within 3s", line)

    def test_being_rate_limited_says_so_instead_of_saying_forbidden(self):
        # 403 is what an anonymous caller past the hourly allowance gets, and
        # "forbidden" reads like a permissions problem somebody has to fix — when the
        # fix is to come back later.
        code, line = check(refuses(urllib.error.HTTPError(
            version_mod.LATEST_URL, 403, "rate limit exceeded", {}, None)))
        self.assertEqual(code, 1)
        self.assertEqual(line, "could not check for updates: GitHub answered HTTP 403 "
                               "- rate-limited, so try again later")

    def test_any_other_http_answer_names_its_code(self):
        code, line = check(refuses(urllib.error.HTTPError(
            version_mod.LATEST_URL, 404, "Not Found", {}, None)))
        self.assertEqual(code, 1)
        self.assertEqual(line, "could not check for updates: GitHub answered HTTP 404")

    def test_a_page_that_is_not_json_is_named_as_that(self):
        # The captive-portal shape: something answered, and it was not GitHub.
        code, line = check(answers(b"<html>sign in to continue</html>"))
        self.assertEqual(code, 1)
        self.assertEqual(line, "could not check for updates: GitHub's answer was "
                               "not JSON")

    def test_json_with_no_tag_in_it_is_named_as_that(self):
        code, line = check(answers(json.dumps({"message": "Not Found"}).encode()))
        self.assertEqual(code, 1)
        self.assertEqual(line, "could not check for updates: GitHub's answer carried "
                               "no release number")

    def test_and_so_is_json_that_is_not_even_an_object(self):
        code, line = check(answers(b"[1, 2, 3]"))
        self.assertEqual(code, 1)
        self.assertIn("carried no release number", line)

    def test_a_tag_that_is_not_a_release_number_is_refused_rather_than_echoed(self):
        # The refusal that keeps the line printable: whatever comes back is
        # server-controlled text on its way to a console that may be cp437, so it is
        # matched against the shape this project cuts tags in before it is repeated.
        for tag in ("nightly", "v1.0–beta", "v" + "9" * 64):
            with self.subTest(tag=tag):
                code, line = check(released(tag))
                self.assertEqual(code, 1)
                self.assertEqual(line, "could not check for updates: GitHub's answer "
                                       "carried no release number")

    def test_a_copy_with_no_metadata_says_it_has_nothing_to_compare(self):
        # The check is a comparison and half of it is missing, so it is refused with the
        # reason rather than answered with a guess — and refused here, without putting a
        # question to GitHub whose answer could not have been used either way.
        urlopen = released("v9.9.9")
        code, out = run_flag(["--check-update"], urlopen, here=None)
        self.assertEqual(code, 1)
        self.assertEqual(urlopen.call_count, 0)
        self.assertEqual(out.strip(), "could not check for updates: this copy carries "
                                      "no package metadata, so there is no version to "
                                      "compare a release against")

    def test_the_request_names_flow_and_says_nothing_else_about_this_copy(self):
        # GitHub's API refuses a request with no User-Agent, so there has to be one; it
        # carries no version because the comparison happens here, after the answer
        # arrives. This is the assertion behind the architecture doc's claim that the
        # request carries nothing but the request.
        urlopen = released("v0.5.1")
        check(urlopen)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, version_mod.LATEST_URL)
        self.assertEqual(list(request.header_items()), [("User-agent", "flow")])
        self.assertIsNone(request.data)
        self.assertNotIn(HERE, request.full_url)


class TestNothingChecksOnItsOwn(unittest.TestCase):
    """The property the privacy claim rests on, asserted structurally.

    `docs/architecture.md` § "What leaves the machine" is an enumeration, and it is only
    worth reading if it is complete. A background check added later would not fail any
    other test in this suite — it would just quietly make that document a description of
    the common case. So the call sites are counted.
    """

    def test_the_flag_is_the_only_thing_in_the_package_that_calls_it(self):
        callers = {
            path.name for path in (ROOT / "flow").glob("*.py")
            if "check_update" in path.read_text(encoding="utf-8")
        }
        self.assertEqual(callers, {"version.py", "__main__.py"})

    def test_and_nothing_else_in_the_package_opens_a_url(self):
        # `flow/edge.py` reaches Microsoft's speech service through `edge-tts`, which is
        # an extra you have to install and a voice you have to choose; it is enumerated
        # in the same document. Nothing else in the package holds a URL opener at all.
        openers = {
            path.name for path in (ROOT / "flow").glob("*.py")
            if "urlopen" in path.read_text(encoding="utf-8")
        }
        self.assertEqual(openers, {"version.py"})


class TestEveryLineSurvivesALegacyConsole(unittest.TestCase):
    """`say()` prints these, and a redirected stdout uses the locale encoding.

    A cp437 console cannot encode an en-dash, so a line carrying one raises
    `UnicodeEncodeError` instead of printing — and for a one-shot flag that line is the
    entire output. GitHub's tag is the one string here Flow did not write, which is why
    it is in the list twice: once as a number, once as something with a dash in it.
    """

    def lines(self) -> list[str]:
        out = [f"flow {version_mod.UNKNOWN}", "flow 1.2.3"]
        for urlopen in (released("v9.9.9"), released("v0.5.1"), released("v0.0.1"),
                        released("v1.0–beta"), released("nightly"),
                        answers(b"not json"), answers(b"{}"),
                        refuses(urllib.error.URLError("no route")),
                        refuses(TimeoutError()),
                        refuses(urllib.error.HTTPError(
                            version_mod.LATEST_URL, 403, "no", {}, None)),
                        refuses(urllib.error.HTTPError(
                            version_mod.LATEST_URL, 500, "no", {}, None)),
                        refuses(RuntimeError("something else entirely"))):
            with holding(HERE), mock.patch("urllib.request.urlopen", urlopen):
                out.append(version_mod.check_update()[0])
        with holding(None):
            out.append(version_mod.check_update()[0])
        return out

    def test_every_line_either_flag_can_print_encodes_to_cp437_and_ascii(self):
        for line in self.lines():
            with self.subTest(line=line):
                line.encode("cp437")
                line.encode("ascii")

    def test_and_every_one_of_them_is_a_single_line(self):
        for line in self.lines():
            with self.subTest(line=line):
                self.assertNotIn("\n", line)


class TestTheHelpSheetNamesIt(unittest.TestCase):
    """The GUI half of "which copy is this".

    Startup says the version into a console a GUI user does not have open — the same
    gap the welcome card was built for (decisions.md 2026-08-03). The sheet is the
    surface that is always reachable, so the number is on it, at the bottom, where it
    answers the question without becoming part of the reading.
    """

    def sheet(self, here=HERE) -> list[tuple[str, str, str]]:
        import flow.ui as ui

        shown: list[list] = []
        pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(send_words=("goose", "enter goose"), workspace=None)
        pill.hotkeys = None
        pill.lite = True
        pill._help = mock.Mock(show=shown.append)
        with holding(here):
            pill._open_commands()
        return shown[0]

    def test_the_last_row_is_the_version_and_nothing_else(self):
        self.assertEqual(self.sheet()[-1], ("note", f"Flow {HERE}", ""))

    def test_it_is_below_everything_the_sheet_says_about_this_machine(self):
        # Unobtrusive is the requirement: a version banner at the top would push the
        # combos somebody opened the sheet to read further down it.
        rows = self.sheet()
        flat = " ".join(left for _kind, left, _right in rows[:-1])
        self.assertIn("Talking to the draft", flat)
        self.assertNotIn(HERE, flat)

    def test_and_it_fits_the_row_budget_even_with_no_metadata(self):
        # The window draws one line per row and does not wrap — a row over budget runs
        # off the edge rather than wrapping — and this row is built in `ui.py` without
        # going through `help._fitted`, so the budget is kept by keeping the string
        # short. `version.UNKNOWN` is the longest it can be.
        from flow.help import MAX_NOTE

        row = self.sheet(here=None)[-1]
        self.assertEqual(row[1], f"Flow {version_mod.UNKNOWN}")
        self.assertLessEqual(len(row[1]), MAX_NOTE)


if __name__ == "__main__":
    unittest.main()
