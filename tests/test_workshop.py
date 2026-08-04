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
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling helpers

from flow.profile import Profile, resolve_workspace  # noqa: E402
from flow.refine import MAX_CHARS  # noqa: E402
from flow.session import (  # noqa: E402
    AUTO_ASK_SEC, CONVERSE, GROUNDING, Session, ask_framing,
)
from flow.thread import CONTEXT_CHARS  # noqa: E402
from cli_env import cli_on_path  # noqa: E402


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


class TestTheQuestionAsksForAnAnswer(Temp):
    """What `_invoke` actually receives — asserted there, not at `ask()`'s door.

    This class used to pin the opposite (`test_it_says_what_the_conversation_is_for`
    asserted "refine" and "prompt" in the framing) and it was green through the whole of
    root 1: three outside users asked questions and got their phrasing critiqued, because
    the framing told codex to critique it and codex obeyed. The inversion is the item.
    """

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

        # `cli_on_path` because `_invoke` is only reached once `_invoke_any` has found
        # a CLI to reach it with, and that lookup is a PATH lookup. Without it this
        # asserts nothing on a machine with no agent CLI installed — which is how a
        # clean CI runner found it.
        with cli_on_path(), mock.patch("flow.refine._invoke", fake_invoke):
            s._start_ask(question)
            s.wait_idle(timeout=5.0)
        s.close()
        self.assertTrue(seen, "the CLI was never invoked")
        return seen[0]

    def test_the_draft_and_the_workspace_both_reach_the_cli(self):
        prompt = self.framed("write a migration for last_seen_at",
                             workspace=r"D:\dev\products\acme")
        self.assertIn("write a migration for last_seen_at", prompt)
        self.assertIn(r"D:\dev\products\acme", prompt)

    def test_it_asks_for_an_answer_rather_than_a_critique(self):
        # The exact sentence the users met, gone: "Discuss and improve the prompt
        # itself … Do not carry out the task it describes."
        prompt = self.framed("write a migration", workspace=str(self.dir))
        tail = prompt[prompt.index("---\n") + 4:]
        self.assertIn("answer the question above", tail.lower())
        for word in ("do not carry out", "improve the prompt", "refine the prompt"):
            self.assertNotIn(word, tail.lower(), f"the workshop framing survived: {word}")

    def test_the_workspace_clause_grants_rather_than_instructs(self):
        # "consult it when the question concerns it" — a question about the weather
        # must not send the CLI reading source files, and one about the project must.
        prompt = self.framed("how is this structured", workspace=str(self.dir))
        self.assertIn("consult it when the question concerns it", prompt)

    def test_with_no_workspace_it_still_frames_and_claims_no_project(self):
        prompt = self.framed("write a migration")
        self.assertIn("write a migration", prompt)
        self.assertIn("Answer the question above", prompt)
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
        # away — and it would be thrown away for exactly the long questions this is
        # most likely to be handling.
        long = "x" * (MAX_CHARS + 3_000)
        prompt = self.framed(long, workspace=str(self.dir))
        self.assertIn(str(self.dir), prompt)
        self.assertIn("Answer the question above", prompt)

    def test_the_preamble_is_a_constant_rather_than_a_string_in_the_call(self):
        self.assertIn("{workspace}", GROUNDING)
        self.assertTrue(GROUNDING.strip())

    def test_the_budget_keeps_the_framed_question_inside_max_chars(self):
        # What makes `ask()`'s sentence-boundary walk a no-op rather than a coin toss.
        # It is arithmetic against `len(ask_framing(...))`, so it has to be re-asserted
        # whenever the framing changes length — which is what this item did.
        for cwd in (None, str(self.dir), "D:\\" + "d" * 200):
            framing = ask_framing(cwd)
            budget = max(0, MAX_CHARS - len(framing))
            question = "y" * (MAX_CHARS * 3)
            self.assertLessEqual(len(question[-budget:] + framing), MAX_CHARS)

    def test_no_workspace_means_no_workspace_line_at_all(self):
        self.assertNotIn("WORKSPACE", ask_framing(None))
        self.assertIn("WORKSPACE", ask_framing("D:\\dev\\flow"))


class TestTheWorkspaceIsVisible(Temp):
    """The visibility that pays for the stale-path risk the owner accepted."""

    def test_the_mode_switch_note_names_it(self):
        # The note names the provider as well as the workspace, and `_provider()` is a
        # PATH lookup — so with no agent CLI installed this note is a different
        # sentence. The workspace half is what is under test; the CLI is declared.
        with cli_on_path():
            s = session(refine_cwd=r"D:\dev\products\acme")
            s.toggle_mode()
            self.assertEqual(s.mode, CONVERSE)
            self.assertIn(r"D:\dev\products\acme", notes(s))

    def test_and_says_so_when_there_is_none(self):
        with cli_on_path():
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


class TestTheGroundIsNamedAtEgress(Temp):
    """Item 36's first half: the moment a question leaves names the workspace leaf.

    The misfire that decided this asked about one project while grounded in another,
    and both signals that were supposed to catch it — the startup line, the mode-switch
    note — had scrolled away hours before. The asking note fires at the one moment the
    name is worth reading; the countdown's firing note is the path where words leave
    with no press at all.
    """

    def asked(self, refine_cwd=None) -> list[str]:
        with cli_on_path(), mock.patch("flow.session.ask",
                                       return_value=("a", "codex")):
            s = session(refine_cwd=refine_cwd)
            s.toggle_mode()
            s.events()
            s._start_ask("q")
            said = [e.text for e in s.events() if e.kind == "note"]
            s.close()
        return [n for n in said if n.startswith("asking")]

    def test_the_asking_note_carries_the_workspace_leaf(self):
        ws = self.dir / "acme"
        ws.mkdir()
        self.assertEqual(self.asked(str(ws)), ["asking codex · acme…"])

    def test_with_no_workspace_the_note_is_what_it_has_always_been(self):
        # Byte-for-byte. A "· (not set)" suffix is noise nobody asked for: the absence
        # of a name is itself legible, and the ungrounded case is the common one.
        self.assertEqual(self.asked(None), ["asking codex…"])

    def test_the_leaf_is_bounded_like_every_string_nobody_here_wrote(self):
        long = self.dir / ("x" * 60)
        long.mkdir()
        (note,) = self.asked(str(long))
        self.assertIn("x" * 23 + "…", note)
        self.assertNotIn("x" * 24, note)

    def fired(self, refine_cwd=None) -> list[str]:
        with cli_on_path(), mock.patch("flow.session.ask",
                                       return_value=("a", "codex")):
            s = session(refine_cwd=refine_cwd)
            s.toggle_mode()
            s.draft.set("can you hear me")
            s._after_draft_change()
            s.events()
            s._settled_at -= AUTO_ASK_SEC + 0.1
            s._pump_auto_ask()
            said = [e.text for e in s.events() if e.kind == "note"]
            s.close()
        return [n for n in said if "no more speech" in n]

    def test_the_countdown_final_state_carries_it_too(self):
        # Auto-ask is the one path where words leave with no press, which is exactly
        # why its firing note cannot stay anonymous about where they are going.
        ws = self.dir / "acme"
        ws.mkdir()
        self.assertEqual(self.fired(str(ws)),
                         ["no more speech - asking · acme"])

    def test_and_without_a_workspace_the_countdown_note_is_untouched(self):
        self.assertEqual(self.fired(None), ["no more speech - asking"])


class TestSwitchingTheGround(Temp):
    """Item 36's second half: one tap switches, and a switch is a topic switch.

    The nailed behaviour comes from the decision entry, not from taste: carrying one
    project's conversation into another project's grounding is precisely the
    contamination the switch exists to end, so switching clears the thread and the
    note says both things in one line. The refusals are the honest edges: a folder
    that is gone, an answer still in flight, a profile that will not save.
    """

    def grounded(self, ws, profile=None) -> Session:
        s = session(refine_cwd=ws, profile=profile)
        s.toggle_mode()
        s.events()
        return s

    def test_a_switch_reaches_the_next_ask_and_its_preamble(self):
        old, new = self.dir / "old", self.dir / "new"
        old.mkdir()
        new.mkdir()
        seen: list[str] = []
        s = self.grounded(str(old))
        self.assertTrue(s.set_workspace(str(new)))
        self.assertEqual(s.workspace, str(new))

        def fake_invoke(cli, prompt, **kw):
            seen.append(prompt)
            return "an answer", ""

        with cli_on_path(), mock.patch("flow.refine._invoke", fake_invoke):
            s._start_ask("q")
            s.wait_idle(timeout=5.0)
        s.close()
        self.assertTrue(seen, "the CLI was never invoked")
        self.assertIn(str(new), seen[0])
        self.assertNotIn(str(old), seen[0])

    def test_a_switch_clears_the_thread_and_says_both_things_in_one_line(self):
        new = self.dir / "acme"
        new.mkdir()
        s = self.grounded(str(self.dir))
        s.thread.add("about the old project")
        s.events()
        self.assertTrue(s.set_workspace(str(new)))
        self.assertEqual(len(s.thread), 0)
        self.assertIn("workshop: acme — new conversation", notes(s))

    def test_a_same_workspace_tap_is_a_no_op_and_clears_nothing(self):
        s = self.grounded(str(self.dir))
        s.thread.add("still mine")
        s.events()
        self.assertFalse(s.set_workspace(str(self.dir)))
        self.assertEqual(s.thread.turns, ["still mine"])
        self.assertEqual(notes(s), "")

    def test_the_same_workspace_spelt_differently_is_still_the_same(self):
        # Path identity, not string identity: a separator or a trailing slash must
        # not be able to clear somebody's conversation.
        s = self.grounded(str(self.dir))
        s.thread.add("still mine")
        s.events()
        respelt = str(self.dir).replace("\\", "/") + "/"
        self.assertFalse(s.set_workspace(respelt))
        self.assertEqual(len(s.thread), 1)

    def test_unsetting_the_workspace_is_a_switch_too(self):
        # "(not set)" is a real entry, so choosing it is a real topic switch — one
        # rule, no special case.
        s = self.grounded(str(self.dir))
        s.thread.add("grounded talk")
        s.events()
        self.assertTrue(s.set_workspace(None))
        self.assertIsNone(s.workspace)
        self.assertEqual(len(s.thread), 0)
        self.assertIn("workshop: not set — new conversation", notes(s))

    def test_a_missing_path_is_refused_with_the_reason_and_switches_nothing(self):
        # resolve_workspace's stale-path honesty, extended to the menu: shown, said,
        # and nothing cleared on the strength of a folder that is not there.
        gone = self.dir / "moved-away"
        s = self.grounded(str(self.dir))
        s.thread.add("kept")
        s.events()
        self.assertFalse(s.set_workspace(str(gone)))
        self.assertEqual(s.workspace, str(self.dir))
        self.assertEqual(len(s.thread), 1)
        self.assertIn("no longer exists", notes(s))

    def test_a_switch_mid_ask_is_refused_like_send_is(self):
        # The answer in flight would land in a thread about a different project —
        # `_pump_ask` adds the reply as a turn, and the op id would still match.
        new = self.dir / "new"
        new.mkdir()
        s = self.grounded(str(self.dir))
        s._ask_op = 1  # the in-flight fact itself, as send() reads it
        self.assertFalse(s.set_workspace(str(new)))
        self.assertEqual(s.workspace, str(self.dir))
        self.assertIn("waiting", notes(s).lower())

    def test_a_switch_is_stored_and_survives_a_reload(self):
        # Saved on the tap like the trigger word: a choice made just before closing
        # the app is still a choice — and next launch grounds the new project.
        new = self.dir / "acme"
        new.mkdir()
        p = self.profile()
        s = self.grounded(str(self.dir), profile=p)
        self.assertTrue(s.set_workspace(str(new)))
        self.assertEqual(p.workspace, str(new))
        self.assertEqual(p.workspaces[0], str(new))
        self.assertEqual(Profile(p.path).workspace, str(new))

    def test_a_switch_that_cannot_be_saved_says_so_and_still_switches(self):
        # The session state moved; what failed is persistence, and next launch will
        # ground the old project — which is exactly the trap this item exists to end,
        # so it is said rather than swallowed.
        new = self.dir / "acme"
        new.mkdir()
        p = self.profile()
        s = self.grounded(str(self.dir), profile=p)
        with mock.patch.object(Profile, "save", return_value=False):
            self.assertTrue(s.set_workspace(str(new)))
        self.assertEqual(s.workspace, str(new))
        self.assertIn("could not save", notes(s))

    def test_no_profile_still_switches_for_this_session(self):
        new = self.dir / "new"
        new.mkdir()
        s = self.grounded(str(self.dir))
        self.assertTrue(s.set_workspace(str(new)))
        self.assertEqual(s.workspace, str(new))

    def test_the_draft_survives_a_switch(self):
        # R5: the words are the user's, whatever ground they stand on.
        new = self.dir / "new"
        new.mkdir()
        s = self.grounded(str(self.dir))
        s.draft.set("half a prompt")
        self.assertTrue(s.set_workspace(str(new)))
        self.assertEqual(s.draft.text, "half a prompt")


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
