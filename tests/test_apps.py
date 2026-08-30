"""Per-app notes: a standing instruction that depends on which app is in front.

The feature is one sentence — *"this text is going into slack.exe, bear it in mind"* —
appended to the rewrite prompt when the profile has something to say about the app that
holds the foreground. Almost none of it is new machinery. `Pill._track_target` already
polls the foreground every frame so Send can be aimed, `inject.classify` already names
the process behind a window because the terminal detection needed it, and `refine()`
already builds its call out of named prompt constants. What this adds is the table, the
lookup, and the two places that could get it wrong.

Which is where the tests are aimed, because those two are the whole risk:

  **It must not out-shout what the user just said.** A per-app note is a *standing*
  preference, and the entire point of speaking an instruction is to override a standing
  preference on this one occasion. So the note is phrased as a destination rather than a
  rule, and it is placed before the request rather than after it — the sentence nearest
  the text is the one that wins ties, and that sentence has to be the user's.

  **It must cost nothing when there is nothing to say.** No profile, no table, an app
  with no entry, a blank entry, an entry that is not a string, Lite, a window the OS
  will not name: every one of those has to come out as a rewrite that behaves exactly
  the way every rewrite behaved before this existed.

The frame budget gets its own test in `tests/test_lite.py` (`classify` opens a process
handle, and this is polled at 30 fps), because that is where the polling lives.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow.profile import Profile, _apps  # noqa: E402
from flow.refine import _POLISH_PROMPT, _PROMPT, Cli, app_note  # noqa: E402
from flow.session import Session  # noqa: E402


class Silent:
    """The `asr`/`mic` surface `Session` needs and none of these tests exercise."""

    def __getattr__(self, _name):
        return lambda *_a, **_kw: None


class TestTheNoteIsBuiltOnlyWhenThereIsSomethingToSay(unittest.TestCase):
    """`app_note`, on every shape a hand-written table can produce."""

    def test_an_app_and_an_instruction_make_a_block(self):
        block = app_note("slack.exe", "keep it informal")
        self.assertIn("slack.exe", block)
        self.assertIn("keep it informal", block)

    def test_it_names_the_destination_rather_than_giving_an_order(self):
        # The phrasing is the safeguard, not decoration. "This text is going into Slack"
        # is a fact the model weighs against the request; "always be informal" is a
        # competing order, and a competing order beats the instruction the user just
        # spoke — which would make the feature worse than not having it.
        block = app_note("slack.exe", "keep it informal").lower()
        self.assertIn("going into", block)
        self.assertIn("without letting it override", block)

    def test_every_way_of_having_nothing_to_say_is_the_empty_string(self):
        # Each of these is a rewrite that behaves exactly as it did before per-app notes
        # existed, which is the only acceptable degraded path for a feature nobody asked
        # to have switched on.
        for app, note in (
            ("slack.exe", ""),
            ("slack.exe", "   "),
            ("slack.exe", None),
            ("slack.exe", 7),
            ("slack.exe", ["informal"]),
            ("", "keep it informal"),
        ):
            with self.subTest(app=app, note=note):
                self.assertEqual(app_note(app, note), "")

    def test_the_instruction_is_trimmed_but_not_otherwise_touched(self):
        # A `lexicon.txt`-shaped bargain: Flow does not reformat what somebody wrote in
        # their own file. Whitespace goes because trailing space in JSON is invisible and
        # never deliberate; nothing else does.
        self.assertIn("Use British spelling.",
                      app_note("word.exe", "  Use British spelling.  "))


class TestTheNoteGoesInFrontOfTheRequest(unittest.TestCase):
    """Position is the second safeguard, and it is the one a refactor would lose."""

    def _prompt(self, polish: bool) -> str:
        from flow import refine as refine_mod

        seen = {}

        def capture(_cli, prompt, **_kw):
            seen["prompt"] = prompt
            # A real `Cli`, because `_clean` reads `.name` off whatever comes back to
            # decide which CLI's furniture to strip.
            return "REVISED", "", Cli("codex", ("codex", "exec"))

        with mock.patch.object(refine_mod, "_invoke_any", capture):
            refine_mod.refine("shipping on friday", "make it formal", polish=polish,
                              app=app_note("slack.exe", "keep it informal"))
        return seen["prompt"]

    def test_a_semantic_rewrite_carries_the_note(self):
        self.assertIn("slack.exe", self._prompt(polish=False))

    def test_a_polish_carries_it_too(self):
        # The polish ignores the spoken instruction entirely, which makes it the pass
        # with the *most* to gain from knowing where the words are headed: a prompt bound
        # for a terminal and one bound for a chat window differ in exactly this way.
        self.assertIn("slack.exe", self._prompt(polish=True))

    def test_the_users_own_instruction_sits_nearer_the_text_than_the_note(self):
        # The sentence nearest the text wins ties. A per-app note is a standing
        # preference and speaking is how you override one on this occasion, so the
        # spoken instruction has to be the closer of the two.
        prompt = self._prompt(polish=False)
        self.assertLess(prompt.index("slack.exe"), prompt.index("make it formal"))

    def test_neither_prompt_mentions_an_app_when_there_is_no_note(self):
        # The default path for everybody who never writes an `apps` table, which is
        # almost everybody: the prompt has to be byte-for-byte what it always was.
        self.assertNotIn("going into", _PROMPT)
        self.assertNotIn("going into", _POLISH_PROMPT)


class TestTheTableIsCarriedThroughUntouched(unittest.TestCase):
    """`profile._apps`, which checks the shape and deliberately stops there."""

    def test_a_table_survives(self):
        self.assertEqual(_apps({"code.exe": "be terse"}), {"code.exe": "be terse"})

    def test_anything_that_is_not_a_table_degrades_to_nothing(self):
        for value in (None, "code.exe", 3, ["code.exe"], True):
            with self.subTest(value=value):
                self.assertEqual(_apps(value), {})

    def test_an_entry_is_never_refused_by_name(self):
        # The difference from the `hotkeys` table, and it is worth being explicit about.
        # An action name has five right answers, so a typo is knowable. An executable
        # name has as many right answers as there are programs in the world — an entry
        # for an app that is not installed is not a mistake, it is somebody who has not
        # opened it yet. So nothing is dropped and nothing is reported; a key that never
        # matches simply never fires.
        table = {"nothing-like-this.exe": "be terse", "": "x", "7": "y"}
        self.assertEqual(_apps(table), table)

    def test_it_survives_a_save_and_a_load(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            p = Profile(path)
            p.apps = {"code.exe": "be terse"}
            self.assertTrue(p.save())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["apps"],
                             {"code.exe": "be terse"})
            again = Profile(path)
            self.assertTrue(again.load())
            self.assertEqual(again.apps, {"code.exe": "be terse"})
            self.assertNotIn("apps", again.faults)

    def test_an_empty_table_lands_in_every_saved_profile(self):
        # The only advertisement this feature gets, in a project with no settings dialog
        # to put it in — the same job `"hotkeys": {}` already does.
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            self.assertTrue(Profile(path).save())
            self.assertIn("apps", json.loads(path.read_text(encoding="utf-8")))


class TestTheSessionLooksTheAppUp(unittest.TestCase):
    """`Session._app_note`: the join between the window in front and the table."""

    def session(self, apps=None, app="") -> Session:
        s = Session(asr=Silent(), mic=Silent())
        self.addCleanup(s.close)
        if apps is not None:
            s.profile = type("P", (), {"apps": apps})()
        s.target_app = app
        return s

    def test_the_app_in_front_selects_its_entry(self):
        s = self.session({"code.exe": "be terse", "slack.exe": "be informal"},
                         app="slack.exe")
        self.assertIn("be informal", s._app_note())
        self.assertNotIn("be terse", s._app_note())

    def test_the_match_ignores_case(self):
        # "Code.exe" and "code.exe" are the same program. A table that cared would be one
        # whose entries silently stop matching the day a vendor changes the
        # capitalisation of a shipped binary.
        for written, running in (("Code.exe", "code.exe"), ("code.exe", "CODE.EXE"),
                                 ("  code.exe  ", "Code.Exe")):
            with self.subTest(written=written, running=running):
                s = self.session({written: "be terse"}, app=running)
                self.assertIn("be terse", s._app_note())

    def test_an_app_with_no_entry_gets_nothing(self):
        s = self.session({"code.exe": "be terse"}, app="notepad.exe")
        self.assertEqual(s._app_note(), "")

    def test_every_way_of_having_no_table_gets_nothing(self):
        for apps in ({}, None):
            with self.subTest(apps=apps):
                self.assertEqual(self.session(apps, app="code.exe")._app_note(), "")

    def test_no_profile_at_all_gets_nothing(self):
        # `--no-profile`, and the launch before one has ever been saved.
        s = self.session(app="code.exe")
        s.profile = None
        self.assertEqual(s._app_note(), "")

    def test_no_app_in_front_gets_nothing(self):
        # Lite, which has no target-window awareness at all, and the moments when the OS
        # declines to name the foreground.
        s = self.session({"code.exe": "be terse"}, app="")
        self.assertEqual(s._app_note(), "")

    def test_a_key_that_is_not_a_string_cannot_break_the_lookup(self):
        # `_apps` carries entries through untouched by design, so this table is
        # reachable — and a rewrite that raised because of one bad key would cost the
        # user the words they had already spoken.
        s = self.session({7: "be terse", "code.exe": "be brief"}, app="code.exe")
        self.assertIn("be brief", s._app_note())

    def test_a_blank_instruction_is_the_same_as_no_entry(self):
        # How somebody switches one app off without deleting the line they wrote.
        s = self.session({"code.exe": "   "}, app="code.exe")
        self.assertEqual(s._app_note(), "")


class TestItSaysWhenItUsedOne(unittest.TestCase):
    """P2: a rewrite that quietly obeyed an invisible rule is one nobody can debug."""

    def session(self, apps, app) -> Session:
        s = Session(asr=Silent(), mic=Silent())
        self.addCleanup(s.close)
        s.profile = type("P", (), {"apps": apps})()
        s.target_app = app
        return s

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_the_note_is_named_when_it_applies(self):
        s = self.session({"slack.exe": "keep it informal"}, "slack.exe")
        s.draft.set("shipping on friday")
        with mock.patch("flow.session.refine", return_value=("REVISED", "codex")):
            s._start_refine("make it formal")
        self.assertIn("slack.exe", self.notes(s))

    def test_and_nothing_is_said_when_none_applies(self):
        # The common case by far. A line about a note that did not exist would be noise
        # in the one channel that has to stay believable.
        s = self.session({"slack.exe": "keep it informal"}, "notepad.exe")
        s.draft.set("shipping on friday")
        with mock.patch("flow.session.refine", return_value=("REVISED", "codex")):
            s._start_refine("make it formal")
        self.assertNotIn("note", self.notes(s).replace("notes", ""))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
