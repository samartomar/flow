"""Converse mode is a prompt workshop, and the questions say where they are asked from.

General conversation failed at the desk on its own merits — the CLI answered that it has
no internet access, and hallucinated — so P9's "ChatGPT Voice mode against the CLI" is
the stale half. What the owner asked for instead is narrower and buildable: "predefined
skills to help write better prompt … discuss and refine prompts only nothing more".

Two things were missing under that. `refine_cwd` existed and was never given a value, so
every question was asked from nowhere; and nothing told the CLI what the conversation was
*for*, so it answered as a general assistant. The cost of grounding, argued once and
accepted by the owner: a workspace set today goes stale silently when the project moves.
The mitigation is visibility, not magic — startup and the mode-switch note both name it.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.profile import Profile, resolve_workspace  # noqa: E402
from flow.refine import MAX_CHARS  # noqa: E402
from flow.session import CONVERSE, WORKSHOP, Session  # noqa: E402
from flow.thread import CONTEXT_CHARS  # noqa: E402


class FakeMic:
    def __init__(self) -> None:
        self.level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list:
        return []


class FakeAsr:
    loading = False

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


def session(**kw) -> Session:
    return Session(asr=FakeAsr(), mic=FakeMic(), **kw)


def notes(s) -> str:
    return " | ".join(e.text for e in s.events() if e.kind == "note")


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)

    def profile(self, **kw) -> Profile:
        p = Profile(self.dir / "profile.json")
        for k, v in kw.items():
            setattr(p, k, v)
        return p


class TestWhereTheQuestionIsAskedFrom(Temp):
    """Precedence matches `--voice`: flag, then profile, then nothing."""

    def test_the_flag_wins(self):
        p = self.profile(workspace=str(self.dir))
        path, note = resolve_workspace(str(self.dir), p)
        self.assertEqual(path, str(self.dir))
        self.assertIn(str(self.dir), note)

    def test_the_profile_is_used_when_there_is_no_flag(self):
        p = self.profile(workspace=str(self.dir))
        path, note = resolve_workspace(None, p)
        self.assertEqual(path, str(self.dir))

    def test_neither_is_not_an_error(self):
        path, note = resolve_workspace(None, self.profile())
        self.assertIsNone(path)
        self.assertIn("not set", note)

    def test_no_profile_at_all_still_resolves(self):
        # `--no-profile` is a supported way to run, and so is a first launch.
        path, note = resolve_workspace(None, None)
        self.assertIsNone(path)
        path, note = resolve_workspace(str(self.dir), None)
        self.assertEqual(path, str(self.dir))

    def test_a_stored_path_that_is_gone_says_so_and_runs_without_it(self):
        # A startup that refuses over a stale setting is worse than an ungrounded ask:
        # the project moved, and Flow is not the thing that should stop working.
        missing = self.dir / "moved-away"
        p = self.profile(workspace=str(missing))
        path, note = resolve_workspace(None, p)
        self.assertIsNone(path, "a path that does not exist was used anyway")
        self.assertIn(str(missing), note)
        self.assertIn("no longer", note)

    def test_a_file_is_not_a_workspace(self):
        f = self.dir / "notes.txt"
        f.write_text("x", encoding="utf-8")
        path, note = resolve_workspace(str(f), None)
        self.assertIsNone(path)

    def test_the_field_is_additive_and_survives_a_reload(self):
        p = self.profile(workspace=str(self.dir))
        self.assertTrue(p.save())
        self.assertEqual(Profile(p.path).workspace, str(self.dir))

    def test_an_older_profile_loads_with_none(self):
        p = Profile(self.dir / "old.json")
        p.path.write_text('{"schema": 1}', encoding="utf-8")
        self.assertTrue(p.load())
        self.assertIsNone(p.workspace)


class TestTheQuestionCarriesTheWorkshop(Temp):
    """What `_invoke` actually receives — asserted there, not at `ask()`'s door."""

    def framed(self, question: str, workspace=None, context=()) -> str:
        seen: list[str] = []
        s = session(refine_cwd=workspace)
        s.toggle_mode()
        for turn in context:
            s.thread.add(turn)
        s.thread.add(question)

        def fake_invoke(cli, prompt, **kw):
            seen.append(prompt)
            return "an answer", ""

        with mock.patch("flow.refine._invoke", fake_invoke):
            s._start_ask(question)
            s.wait_idle(timeout=5.0)
        s.close()
        self.assertTrue(seen, "the CLI was never invoked")
        return seen[0]

    def test_the_draft_and_the_workspace_both_reach_the_cli(self):
        prompt = self.framed("write a migration for last_seen_at",
                             workspace=r"D:\dev\products\syntegris")
        self.assertIn("write a migration for last_seen_at", prompt)
        self.assertIn(r"D:\dev\products\syntegris", prompt)

    def test_it_says_what_the_conversation_is_for(self):
        prompt = self.framed("write a migration", workspace=str(self.dir))
        self.assertIn("refine", prompt.lower())
        self.assertIn("prompt", prompt.lower())

    def test_with_no_workspace_it_still_frames_and_claims_no_project(self):
        prompt = self.framed("write a migration")
        self.assertIn("write a migration", prompt)
        self.assertIn("refine", prompt.lower())
        self.assertNotIn("WORKSPACE:", prompt)

    def test_the_thread_context_still_rides_along(self):
        # A workshop with amnesia between turns is not a workshop.
        prompt = self.framed("and mention the rollback",
                             context=["how do I add a column"])
        self.assertIn("how do I add a column", prompt)
        self.assertIn("EARLIER IN THIS CONVERSATION", prompt)

    def test_a_question_past_max_chars_still_carries_the_workspace(self):
        # The framing trails the question deliberately: `ask()` keeps the *tail* of an
        # over-long input, so anything placed in front of it is the first thing thrown
        # away — and it would be thrown away for exactly the long prompts a workshop is
        # most likely to be handling.
        long = "x" * (MAX_CHARS + 3_000)
        prompt = self.framed(long, workspace=str(self.dir))
        self.assertIn(str(self.dir), prompt)
        self.assertIn("refine", prompt.lower())

    def test_the_preamble_is_a_constant_rather_than_a_string_in_the_call(self):
        self.assertIn("{workspace}", WORKSHOP)
        self.assertTrue(WORKSHOP.strip())


class TestTheWorkspaceIsVisible(Temp):
    """The visibility that pays for the stale-path risk the owner accepted."""

    def test_the_mode_switch_note_names_it(self):
        s = session(refine_cwd=r"D:\dev\products\syntegris")
        s.toggle_mode()
        self.assertEqual(s.mode, CONVERSE)
        self.assertIn(r"D:\dev\products\syntegris", notes(s))

    def test_and_says_so_when_there_is_none(self):
        s = session()
        s.toggle_mode()
        said = notes(s)
        self.assertIn("converse mode", said)
        self.assertIn("no project", said.lower())

    def test_going_back_to_dictate_does_not_claim_a_workspace(self):
        s = session(refine_cwd=str(self.dir))
        s.toggle_mode()
        s.events()
        s.toggle_mode()
        self.assertNotIn(str(self.dir), notes(s))


class TestP9SaysWhatItNowIs(unittest.TestCase):
    """The definition follows the evidence, and the build follows the definition."""

    def product(self) -> str:
        return (Path(__file__).resolve().parent.parent / "docs" / "product.md"
                ).read_text(encoding="utf-8")

    def row(self, marker: str) -> str:
        """The requirement's own table row. Anchored on `| Pn |`, not on `Pn` — the
        rows cross-reference each other now, so a bare search finds the mention rather
        than the definition."""
        body = self.product()
        i = body.find(f"| {marker} |")
        self.assertGreater(i, 0, f"{marker} has no row in product.md")
        return body[i:body.index("\n", i)].lower()

    def test_p9_is_described_as_a_prompt_workshop(self):
        row = self.row("P9")
        self.assertIn("workshop", row)
        self.assertIn("workspace", row)
        self.assertIn("refine", row)

    def test_the_react_question_is_no_longer_promised(self):
        # It was the scenario for general conversation, and general conversation is what
        # failed at the desk — so it cannot stay as a promise. It *does* stay as a
        # record: a definition that changed without saying what it used to be, and why,
        # is a definition somebody will change back.
        body = self.product()
        self.assertNotIn("debounce a resize handler", body,
                         "the general-conversation scenario is still being promised")
        self.assertTrue("React" in body, "and the reason it went is not recorded")
        self.assertIn("hallucinated", body)

    def test_the_half_duplex_caveat_survives(self):
        self.assertIn("half-duplex", self.product().lower())

    def test_p5_distinguishes_the_one_shot_polish_from_the_workshop(self):
        row = self.row("P5")
        self.assertIn("workshop", row)
        self.assertIn("one-shot", row)


if __name__ == "__main__":
    unittest.main()
