"""A word for Send, and a word for Send-then-Enter.

The last keyboard step in the workshop loop — item 21 takes the reply, this sends it —
becomes voice. First feature to run at R5 and P7 directly, and the safety comes from
inheriting Send's existing refusals rather than from new machinery: the trigger presses
the same button the chip does, so every refusal that already exists applies unchanged.

Two things carry the risk and both are pinned here. **Whole-utterance matching** is what
makes a false fire rare: the word is a command only when it is the entire thing said, so
a mis-fire needs the speaker to have said nothing else. And **the order of the two
defaults is the safe one** — a decode that loses a word from "enter boom" yields "enter"
(no trigger at all) or "boom" (paste without submit). Degradation falls away from
execution, never toward it.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.edits import (  # noqa: E402
    SEND_ENTER_WORD,
    SEND_WORD,
    SEND_WORD_PRESETS,
    enter_word,
    plan,
)
from flow.profile import Profile  # noqa: E402
from flow.session import CONVERSE, Session  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)
DRAFT = "Ship the release notes on Tuesday."


class FakeMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeAsr:
    loading = False

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


def session(**kw) -> Session:
    return Session(asr=FakeAsr(), mic=FakeMic(), **kw)


def notes(s) -> str:
    return " | ".join(e.text for e in s.events() if e.kind == "note")


def sends(s) -> list[str]:
    return [e.text for e in s.events() if e.kind == "send"]


def routed(text: str) -> str:
    p = plan(text, DRAFT)
    return f"{p.kind}/{p.op}"


def routed_with(text: str, triggers: tuple[str, str]) -> str:
    p = plan(text, DRAFT, triggers)
    return f"{p.kind}/{p.op}"


class TestTheWordIsTheWholeUtterance(unittest.TestCase):
    """Both directions in one class, because they are one diff apart."""

    def test_the_defaults_are_the_ones_the_owner_chose(self):
        self.assertEqual(SEND_WORD, "boom")
        self.assertEqual(SEND_ENTER_WORD, "enter boom")

    def test_each_alone_routes_to_its_trigger(self):
        self.assertEqual(routed("boom"), "send_trigger/")
        self.assertEqual(routed("Boom."), "send_trigger/")
        self.assertEqual(routed("enter boom"), "send_trigger/enter")
        self.assertEqual(routed("Enter boom!"), "send_trigger/enter")

    def test_the_same_word_inside_a_sentence_is_dictation(self):
        for s in ("boom goes the dynamite",
                  "and then boom",
                  "the deploy went boom last night",
                  "enter boom into the log",
                  "press enter boom is the word"):
            with self.subTest(s=s):
                self.assertEqual(routed(s), "append/")

    def test_degradation_falls_away_from_execution(self):
        # The order of the two words is the safety argument, so it is asserted rather
        # than described: losing either word from "enter boom" can never *upgrade* a
        # paste into a submit.
        self.assertEqual(routed("enter"), "append/", "a lost word must not execute")
        self.assertEqual(routed("boom"), "send_trigger/", "and the other loses only Enter")

    def test_a_hedge_in_front_still_counts(self):
        self.assertEqual(routed("okay, boom"), "send_trigger/")


class Pressed:
    """A pill whose Send goes to a list instead of to a window.

    Driven the way `send_check.py`'s fixture is, and at that layer deliberately: the
    refusals this item must inherit live in `session.send()`, which the *UI* calls — so
    a check that stopped at the session would be asserting that an event was emitted,
    not that a paste was refused.
    """

    def __init__(self, s: Session) -> None:
        import flow.ui as ui

        self.pastes: list[tuple[str, bool]] = []
        self.pill = ui.Pill.__new__(ui.Pill)
        self.pill.session = s
        self.pill.on_send = self._on_send
        self.pill.paste_target = 0x22
        self.pill.bubble = mock.Mock()
        self.pill._flash = 0
        self.session = s

    def _on_send(self, text: str, target=None, submit: bool = False) -> str:
        self.pastes.append((text, submit))
        return ""

    def say(self, utterance: str) -> None:
        """Route an utterance and pump the events the way `Pill._frame` does.

        Pumped until the queue is empty, because `send()`'s own refusal notes are
        emitted *during* the `_send` this loop calls — in the real app they arrive on
        the following frame, 30 ms later, and a single drain would miss exactly the
        lines these checks are about.
        """
        self.session._route(utterance)
        while events := self.session.events():
            for ev in events:
                if ev.kind == "send":
                    self.pill._send(submit=ev.text == "enter")
                elif ev.kind == "note":
                    self.pill.bubble.note(ev.text)

    def notes(self) -> str:
        return " | ".join(str(c.args[0]) for c in self.pill.bubble.note.call_args_list)


class TestTheWordsAreNotThingsPeopleSay(unittest.TestCase):
    """The admission gate, asked of the words directly rather than of an aggregate.

    `command_bench.py`'s precision leg reports 0 misroutes on these 580 utterances, but
    that is a number about the whole grammar. The question a *trigger* word raises is
    narrower and sharper: does anyone in this corpus say it, alone, as a whole thing?
    """

    def test_no_real_utterance_fires_either_trigger(self):
        from flow.edits import _trigger

        bench = Path(__file__).resolve().parent.parent / ".bench" / "accent"
        refs: list[str] = []
        for mf in sorted(bench.glob("manifest-edacc*.jsonl")):
            with mf.open(encoding="utf-8") as fh:
                refs += [json.loads(ln)["ref"] for ln in fh if ln.strip()]
        if not refs:
            self.skipTest("no EdAcc manifest in this tree")
        self.assertGreaterEqual(len(refs), 500, "the corpus shrank")
        fired = [r for r in refs if _trigger(r, (SEND_WORD, SEND_ENTER_WORD)) is not None]
        self.assertEqual(fired, [])

    def test_and_the_one_that_nearly_does_still_does_not(self):
        # Measured: exactly one of the 580 contains either word — "…MAYBE ENTERING
        # THERE BECAUSE…" — and whole-utterance matching is what makes it harmless.
        from flow.edits import _trigger

        near = "YEAH WELL NOT I DON'T KNOW NOT NECESSARILY MAYBE ENTERING THERE BECAUSE "
        self.assertIsNone(_trigger(near, (SEND_WORD, SEND_ENTER_WORD)))


def _bench():
    """`scripts/command_bench.py` as a module, so the gate uses the shipped corpora.

    Imported rather than restated: the adversarial sentences and the corruption classes
    are the numbers a grammar change is checked against, and a copy of them in here would
    start agreeing with itself the first time one of them moved.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import command_bench

    return command_bench


def _corpus() -> list[str]:
    bench = Path(__file__).resolve().parent.parent / ".bench" / "accent"
    refs: list[str] = []
    for mf in sorted(bench.glob("manifest-edacc*.jsonl")):
        with mf.open(encoding="utf-8") as fh:
            refs += [json.loads(ln)["ref"] for ln in fh if ln.strip()]
    return refs


class TestEveryPresetIsAsSafeAsTheDefault(unittest.TestCase):
    """The gate a word passes before the menu is allowed to offer it.

    The menu makes the trigger a one-tap choice, which means the words in it ship with
    the product and nobody measures them again. So each is put through the discipline
    "boom" went through, and the check runs over `SEND_WORD_PRESETS` rather than over a
    list written here — a word added to that tuple pays this price or fails the suite.

    Four legs. The fourth is not decoration: legs 1-3 pass "undo" — its corpus hits are
    0, and `command_bench`'s recall cases are whole commands like "delete Tuesday", never
    a bare verb — while making "undo" a trigger would silently take undo away from the
    person who said it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.cb = _bench()
        cls.refs = _corpus()

    #: No trigger at all, so `plan()` reads the word with the rest of the grammar. Asking
    #: with the shipped pair installed would answer a different question: "boom" is a
    #: `send_trigger` today, which says nothing about whether it means anything else.
    NONE = ("", "")

    def hits(self, word: str) -> list[str]:
        from flow.edits import _trigger

        trig = (word, enter_word(word))
        return [r for r in self.refs if _trigger(r, trig) is not None]

    def adversarial(self, word: str) -> int:
        trig = (word, enter_word(word))
        return sum(1 for u, d in self.cb.ADVERSARIAL
                   if plan(u, d, trig).kind in ("local", "undo"))

    def recall(self, word: str) -> tuple[int, int]:
        """(routed correctly, cases) over every corruption class, with `word` installed."""
        trig = (word, enter_word(word))
        cases: list[tuple[str, str]] = []
        for utterance, op in self.cb.COMMANDS:
            cases.append((utterance, op))
            cases += [(lead + utterance, op) for lead in self.cb.LEAD_INS]
            cases.append((self.cb._suffix(utterance), op))
            cases.append((self.cb._substitute(utterance), op))
            cases.append((self.cb._transpose(utterance), op))
            if (aliased := self.cb._alias(utterance)) is not None:
                cases.append((aliased, op))
        return sum(1 for u, op in cases if plan(u, self.cb.DRAFT, trig).op == op), len(cases)

    def means_alone(self, word: str) -> str:
        return plan(word, self.cb.DRAFT, self.NONE).kind

    # -- the four legs, asked of every shipped preset -----------------------

    def test_no_real_utterance_fires_any_preset(self):
        if not self.refs:
            self.skipTest("no EdAcc manifest in this tree")
        self.assertGreaterEqual(len(self.refs), 500, "the corpus shrank")
        for word in SEND_WORD_PRESETS:
            with self.subTest(word=word):
                self.assertEqual(self.hits(word), [])

    def test_no_preset_moves_the_adversarial_count(self):
        # 5/20 is the shipped number, and a trigger is matched ahead of every pattern in
        # plan() — so a preset that is also a command word would eat it here.
        for word in SEND_WORD_PRESETS:
            with self.subTest(word=word):
                self.assertLessEqual(self.adversarial(word), 5)

    def test_no_preset_costs_a_single_point_of_recall(self):
        for word in SEND_WORD_PRESETS:
            with self.subTest(word=word):
                hit, n = self.recall(word)
                self.assertEqual(hit, n)

    def test_no_preset_already_means_something(self):
        for word in SEND_WORD_PRESETS:
            with self.subTest(word=word):
                self.assertEqual(self.means_alone(word), "append")

    # -- and the gate can say no --------------------------------------------

    def test_it_rejects_words_people_say_on_their_own(self):
        # Rule 1: a gate that has never refused anything is not evidence. Measured on
        # this corpus — "yeah" is a whole utterance 44 times, "okay" 10, "yes" 12.
        if not self.refs:
            self.skipTest("no EdAcc manifest in this tree")
        for word in ("yeah", "okay", "yes"):
            with self.subTest(word=word):
                self.assertTrue(self.hits(word), f"{word} passed leg 1")
                self.assertNotIn(word, SEND_WORD_PRESETS)

    def test_it_rejects_a_word_the_grammar_already_owns(self):
        # The case legs 1-3 are blind to, which is why leg 4 exists.
        self.assertEqual(self.hits("undo"), [], "leg 1 was supposed to be blind here")
        self.assertLessEqual(self.adversarial("undo"), 5, "as was leg 2")
        self.assertEqual(self.means_alone("undo"), "undo")
        self.assertNotIn("undo", SEND_WORD_PRESETS)


class TestTheListIsTheOwnersToChooseFrom(unittest.TestCase):
    def test_the_shipped_default_can_be_chosen_back(self):
        # Otherwise the menu is a one-way door out of the word that works today.
        self.assertIn(SEND_WORD, SEND_WORD_PRESETS)

    def test_the_shipped_list_is_the_one_the_owner_approved(self):
        # Pinned rather than described, because the list moved once already. "goose" was
        # here, passed all four legs, and was taken out at review on taste — which is a
        # different question from the gate's: passing says a word is *admissible*, the
        # review says which admissible words are worth a row in the menu. Its numbers
        # stand in the record and nothing was re-run to remove it.
        self.assertEqual(SEND_WORD_PRESETS,
                         ("boom", "tango", "mango", "falcon", "rocket", "banana"))
        self.assertNotIn("goose", SEND_WORD_PRESETS)

    def test_the_enter_variant_is_derived_in_the_order_that_degrades_safely(self):
        for word in SEND_WORD_PRESETS:
            with self.subTest(word=word):
                self.assertEqual(enter_word(word), f"enter {word}")
                # The safety argument, asserted per preset rather than described once:
                # losing either word can never upgrade a paste into a submit.
                pair = (word, enter_word(word))
                self.assertEqual(routed_with("enter", pair), "append/")
                self.assertEqual(routed_with(word, pair), "send_trigger/")
                self.assertEqual(routed_with(enter_word(word), pair),
                                 "send_trigger/enter")

    def test_the_list_has_no_duplicates(self):
        self.assertEqual(len(set(SEND_WORD_PRESETS)), len(SEND_WORD_PRESETS))


class TestItPressesTheSameButton(unittest.TestCase):
    """Check 2: every refusal Send already has, inherited rather than re-implemented."""

    def test_a_spoken_trigger_pastes_the_draft(self):
        p = Pressed(session())
        p.session.draft.set(DRAFT)
        p.say("boom")
        self.assertEqual(p.pastes, [(DRAFT, False)])

    def test_and_the_enter_variant_asks_for_the_submit(self):
        p = Pressed(session())
        p.session.draft.set(DRAFT)
        p.say("enter boom")
        self.assertEqual(p.pastes, [(DRAFT, True)])

    def test_an_empty_draft_refuses_with_no_paste_and_no_enter(self):
        p = Pressed(session())
        p.say("enter boom")
        self.assertEqual(p.pastes, [], "something was pasted with nothing to send")
        self.assertIn("nothing to send", p.notes())

    def test_a_question_in_flight_refuses_the_same_way_the_chip_does(self):
        p = Pressed(session())
        p.session.draft.set(DRAFT)
        p.session._ask_op = 7  # `send()` refuses on the call itself, not on `state`
        p.say("boom")
        self.assertEqual(p.pastes, [])
        self.assertIn("still waiting", p.notes())

    def test_a_rewrite_in_flight_refuses_too(self):
        p = Pressed(session())
        p.session.draft.set(DRAFT)
        p.session._refine_op = 7
        p.say("boom")
        self.assertEqual(p.pastes, [])
        self.assertIn("still rewriting", p.notes())

    def test_the_trigger_word_never_lands_in_the_draft(self):
        s = session()
        s.draft.set(DRAFT)
        s._route("boom")
        self.assertEqual(s.draft.text, DRAFT, "the trigger was dictated into the draft")

    def test_the_session_asks_rather_than_pasting_on_its_own(self):
        # The paste belongs to the UI thread, which is the only place that knows the
        # window Send is aimed at. The session's whole part is the request.
        s = session()
        s.draft.set(DRAFT)
        s._route("enter boom")
        self.assertEqual(sends(s), ["enter"])


class TestConverseIgnoresTheSuffix(unittest.TestCase):
    """Check 4: nothing is pasted, so there is nothing for Enter to submit."""

    def test_both_variants_ask_and_neither_pastes_anything(self):
        # The suffix is not stripped on the way through — the session says what was
        # said, and `send()` returning "" in converse is what makes the submit
        # unreachable. One place decides, and it is the one that already refuses.
        for word in ("boom", "enter boom"):
            with self.subTest(word=word):
                p = Pressed(session())
                p.session.toggle_mode()
                self.assertEqual(p.session.mode, CONVERSE)
                p.session.draft.set("what is a rollback")
                with mock.patch("flow.session.ask",
                                return_value=("an answer", "codex")):
                    p.say(word)
                    p.session.wait_idle(timeout=5.0)
                self.assertEqual(p.pastes, [], "converse pasted the question")
                self.assertEqual(p.session.reply, "an answer", "it did not ask either")
                p.session.close()

    def test_the_note_about_the_suffix_is_said_once_and_only_for_enter(self):
        s = session()
        s.toggle_mode()
        s.draft.set("what is a rollback")
        s.events()
        with mock.patch("flow.session.ask", return_value=("an answer", "codex")):
            s._route("enter boom")
            s.wait_idle(timeout=5.0)
        said = notes(s)
        self.assertIn("nothing to submit", said)
        self.assertEqual(said.count("nothing to submit"), 1)
        s.close()


class TestTheWordsAreThePersonsOwn(unittest.TestCase):
    """Check 5: defaults must work out of the box, because nobody will edit JSON."""

    def tmp_profile(self) -> Profile:
        return Profile(Path(tempfile.mkdtemp()) / "profile.json")

    def test_a_profile_with_nothing_stored_uses_the_shipped_words(self):
        p = self.tmp_profile()
        self.assertEqual(p.send_word, SEND_WORD)
        self.assertEqual(p.send_enter_word, SEND_ENTER_WORD)

    def test_stored_words_win_and_survive_a_reload(self):
        p = self.tmp_profile()
        p.send_word, p.send_enter_word = "zap", "enter zap"
        self.assertTrue(p.save())
        again = Profile(p.path)
        self.assertEqual((again.send_word, again.send_enter_word), ("zap", "enter zap"))

    def test_a_stored_blank_falls_back_rather_than_disabling_the_feature(self):
        # `""` would match nothing and read as a silent switch-off; absent and blank are
        # the same thing, the way `auto_ask` treats a stored null.
        p = self.tmp_profile()
        p.path.parent.mkdir(parents=True, exist_ok=True)
        p.path.write_text('{"schema": 1, "send_word": "", "send_enter_word": null}',
                          encoding="utf-8")
        self.assertTrue(p.load())
        self.assertEqual(p.send_word, SEND_WORD)
        self.assertEqual(p.send_enter_word, SEND_ENTER_WORD)

    def test_a_session_with_a_profile_routes_the_stored_word(self):
        p = self.tmp_profile()
        p.send_word, p.send_enter_word = "zap", "enter zap"
        s = session(profile=p)
        s.draft.set(DRAFT)
        s._route("zap")
        self.assertEqual(sends(s), [""])

    def test_and_the_shipped_word_stops_working_when_one_is_stored(self):
        # Otherwise "boom" is a permanent second trigger nobody chose — a live word in
        # somebody's vocabulary that they believed they had renamed away.
        #
        # This is also the check that caught `_route` calling `plan()` a second time
        # without the stored words: "boom" came back as a `send_trigger` nothing
        # handled, fell into `_escalate`, and started a ~7 s CLI call on an empty
        # instruction. The draft assertion is what noticed.
        p = self.tmp_profile()
        p.send_word, p.send_enter_word = "zap", "enter zap"
        s = session(profile=p)
        s.draft.set(DRAFT)
        s._route("boom")
        self.assertEqual(sends(s), [])
        self.assertEqual(s.draft.text, f"{DRAFT} boom")

    def test_no_profile_at_all_still_has_working_defaults(self):
        s = session(profile=None)
        s.draft.set(DRAFT)
        s._route("boom")
        self.assertEqual(sends(s), [""])


def recording_send(into: list):
    """A `SendInput` that records its burst *and answers like the real one*.

    This was `lambda *a: keys.append(a)`, which returns None — fine while nobody read the
    answer, and a refused paste from 2026-08-03, when `paste()` started requiring a
    complete insertion. The same shape of unrealistic fake the audit found next door in
    `test_inject_target.py`: a mock that records the call and invents the result.
    """
    def sender(*events):
        into.append(events)
        return len(events)

    return sender


@unittest.skipUnless(sys.platform == "win32", "Windows-only: ctypes.WinDLL")
class TestTheEnterGoesWithThePaste(unittest.TestCase):
    """Check 3: to the validated target, after the paste, and never on its own."""

    def test_paste_sends_enter_only_when_asked(self):
        import flow.inject as inject

        for submit, expected in ((False, 0), (True, 1)):
            with self.subTest(submit=submit):
                keys: list = []
                with mock.patch.object(inject, "resolve",
                                       return_value=inject.Target("ConsoleWindowClass",
                                                                  "cmd.exe")), \
                        mock.patch.object(inject, "set_clipboard_text",
                                          return_value=True), \
                        mock.patch.object(inject, "get_clipboard_text",
                                          return_value=None), \
                        mock.patch.object(inject, "_send",
                                          side_effect=recording_send(keys)):
                    self.assertTrue(inject.paste("deploy it\n", hwnd=0x22, submit=submit))
                self.assertEqual(len(keys), 1 + expected)

    def test_a_refused_paste_never_reaches_the_enter(self):
        # The one ordering that matters: no paste, no submit. A stray Enter into a
        # terminal runs whatever was already on its prompt.
        import flow.inject as inject

        keys: list = []
        inject.take_warnings()
        with mock.patch.object(inject, "resolve",
                               return_value=inject.Target("TkTopLevel", "python.exe",
                                                          is_flow=True)), \
                mock.patch.object(inject, "_send",
                                  side_effect=lambda *a: keys.append(a)):
            self.assertFalse(inject.paste("deploy it\n", hwnd=0x22, submit=True))
        self.assertEqual(keys, [], "an Enter was sent into a refused paste")

    def test_the_payload_still_loses_its_trailing_newline(self):
        # P7's one guarantee is untouched: the Enter is the submit, and it is the *only*
        # submit — a payload that kept its newline would press it twice.
        import flow.inject as inject

        written: list = []
        with mock.patch.object(inject, "resolve",
                               return_value=inject.Target("ConsoleWindowClass",
                                                          "cmd.exe")), \
                mock.patch.object(inject, "set_clipboard_text",
                                  side_effect=lambda t: written.append(t) or True), \
                mock.patch.object(inject, "get_clipboard_text", return_value=None), \
                mock.patch.object(inject, "_send"):
            inject.paste("deploy it\n", hwnd=0x22, submit=True)
        self.assertEqual(written, ["deploy it"])


if __name__ == "__main__":
    unittest.main()


class TestTheDecoderIsNeverToldTheSendWord(unittest.TestCase):
    """The reversal of Root 5's first half, and the reason is a safety one.

    b7bc6aa put the send words into `hotwords` on every final decode, reasoning that the
    one word whose recognition decides whether a spoken command works should not be the
    only word Flow never biased toward. The reasoning is fine and the mechanism is not:
    faster-whisper spends `hotwords` as `<|startofprev|>` context — the slot
    `condition_on_previous_text=False` exists to keep empty — so the bias does not teach
    the decoder a word, it gives it a word to guess with.

    Measured against no bias at all, `small.en`, EdAcc:

      - 300 conversational clips: the send word appears in text nobody said 4 times
        against 0; pooled WER moves -0.007, inside the sampling noise.
      - 280 short clips: 26 against 0, WER 0.534 -> 0.624, and **6 decode to exactly
        "boom"** — "MM HMM", "UM", "YEAH THAT'S COOL", "MM HMM TRUE", "I THINK THAT WAS
        WHAT HAPPEND". A whole-utterance match is a Send.
      - `large-v3-turbo` on the same 280 is no safer: 14 against 0, and the same 6 false
        sends. This is not a weak-model problem.

    Whole-utterance matching was doing its job. The bias was manufacturing whole
    utterances for it to match, which is the one direction a spoken execute trigger may
    not fail in — the same standing refusal that keeps edit distance from firing a send.
    """

    def transcriber(self, terms=()):
        from flow.asr import WhisperTranscriber

        t = WhisperTranscriber.__new__(WhisperTranscriber)
        t.lexicon = mock.Mock()
        t.lexicon.terms.return_value = list(terms)
        return t

    def test_the_bias_is_the_lexicon_and_nothing_else(self):
        self.assertEqual(self.transcriber(terms=["Sameer", "Priya"])._standing_bias(),
                         "Sameer Priya")

    def test_an_empty_lexicon_biases_nothing_at_all(self):
        # None rather than "", because an empty string still makes the library build a
        # prompt prefix — and a prompt that biases toward nothing is the whole defect in
        # miniature.
        self.assertIsNone(self.transcriber()._standing_bias())

    def test_the_lexicon_is_still_capped(self):
        from flow.lexicon import MAX_TERMS

        joined = self.transcriber(
            terms=[f"term{i}" for i in range(MAX_TERMS + 20)])._standing_bias()
        self.assertEqual(len(joined.split()), MAX_TERMS)

    def test_no_send_word_reaches_a_real_decode(self):
        # Through `text()`, because the defect was never in a helper: it was that the
        # array handed to the model carried a prompt. Both tiers, since a partial that
        # decoded to "boom" would still be shown to the user as their own words.
        from flow import SAMPLE_RATE
        from flow.asr import WhisperTranscriber

        lexicon = mock.Mock()
        lexicon.terms.return_value = []
        lexicon.apply.side_effect = lambda s: s
        asr = WhisperTranscriber(lexicon=lexicon)
        model = mock.Mock()
        model.transcribe.return_value = ([], None)
        asr._models = {True: model, False: model}
        asr.load = lambda final=None: None

        for seconds in (0.6, 1.5, 12.0):
            for final in (False, True):
                asr.text(np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32),
                         final=final)
                self.assertIsNone(
                    model.transcribe.call_args.kwargs.get("hotwords"),
                    f"{seconds}s final={final}")

    def test_a_caller_supplied_rescue_bias_still_works(self):
        # The rescue re-decode is a different thing and keeps its bias: it is aimed at
        # one utterance the router already suspects, and it cannot fire a Send — the
        # trigger is tested before any rescue happens.
        from flow import SAMPLE_RATE
        from flow.asr import WhisperTranscriber

        lexicon = mock.Mock()
        lexicon.terms.return_value = []
        lexicon.apply.side_effect = lambda s: s
        asr = WhisperTranscriber(lexicon=lexicon)
        model = mock.Mock()
        model.transcribe.return_value = ([], None)
        asr._models = {True: model, False: model}
        asr.load = lambda final=None: None

        asr.text(np.zeros(SAMPLE_RATE, dtype=np.float32), final=True,
                 hotwords="Tuesday Wednesday")
        self.assertEqual(model.transcribe.call_args.kwargs["hotwords"],
                         "Tuesday Wednesday")

    def test_the_session_hands_the_decoder_no_trigger(self):
        # `_finalise` used to publish the live profile's send words onto the transcriber
        # before every final. Nothing does now, and this pins that: a Transcriber with
        # no such attribute must survive a finalise.
        from flow.audio import BLOCK
        from flow.session import Session

        with tempfile.TemporaryDirectory() as tmp:
            p = Profile(Path(tmp) / "profile.json")
            p.send_word, p.send_enter_word = "tango", "enter tango"
            s = Session(asr=_FakeAsr(), mic=_FakeMic(), profile=p)
            s._utter = [np.full(BLOCK, 0.2, dtype=np.float32)]
            s._finalise()
            self.assertFalse(hasattr(s.asr, "trigger_words"))
            # The words are still the profile's — they just reach the router, not the
            # decoder, which is the whole point.
            self.assertEqual(s.send_words, ("tango", "enter tango"))
            s.close()


class _FakeAsr:
    loading = False

    def load(self, final=None) -> None: ...

    def text(self, a, *, final=False, hotwords="") -> str:
        return ""


class _FakeMic:
    level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list:
        return []


class TestANearMissSpeaksUp(unittest.TestCase):
    """Root 5's second half, and the point where Flow is better than its reference.

    The trigger fails silently: the match is exact whole-utterance equality, so a miss
    lands in the draft as text and the user's only evidence that the feature exists is
    that nothing happened. Wispr Flow shares this flaw — an unrecognised spoken command
    types itself, quietly.

    **Notify, never execute.** Letting edit distance fire a send is a standing refusal:
    a send is irreversible in dictate mode, and the whole grammar rests on a wrong edit
    costing one undo while a wrong send costs a paragraph in a stranger's terminal.
    """

    def session(self, word="tango"):
        from flow.session import Session

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Profile(Path(tmp.name) / "profile.json")
        p.send_word, p.send_enter_word = word, enter_word(word)
        s = Session(asr=_FakeAsr(), mic=_FakeMic(), profile=p)
        self.addCleanup(s.close)
        return s

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_a_near_miss_is_named(self):
        s = self.session("tango")
        s._route("tan go")
        said = self.notes(s)
        self.assertIn("tango", said)
        self.assertIn("sends the draft", said)

    def test_and_the_words_still_land_in_the_draft(self):
        # Notify only. Routing is untouched, which is what makes this safe to be
        # sensitive about.
        s = self.session("tango")
        s._route("tan go")
        self.assertEqual(s.draft.text, "tan go")

    def test_an_exact_match_still_sends(self):
        s = self.session("tango")
        s._route("tango")
        self.assertEqual(s.draft.text, "")
        self.assertIn("send", [e.kind for e in s.events()])

    def test_ordinary_speech_says_nothing(self):
        s = self.session("tango")
        for utterance in ("the deploy failed", "yes", "okay then", "hello"):
            with self.subTest(utterance=utterance):
                s.draft.set("")
                s.events()
                s._route(utterance)
                self.assertNotIn("sends the draft", self.notes(s))

    def test_a_long_utterance_that_happens_to_score_is_a_sentence(self):
        # Two words at most, because that is the shape a trigger has.
        s = self.session("tango")
        s.events()
        s._route("tan go and do the thing")
        self.assertNotIn("sends the draft", self.notes(s))

    def test_it_follows_the_configured_word(self):
        s = self.session("banana")
        s._route("bananas")
        self.assertIn("banana", self.notes(s))
        other = self.session("falcon")
        other._route("bananas")
        self.assertNotIn("sends the draft", self.notes(other))

    def test_the_threshold_is_the_swept_one_and_not_the_editing_one(self):
        # 0.78 is the lowest bar with zero false fires over 4 866 real one- and two-word
        # sequences; `MATCH_THRESHOLD` is 0.82 and fires an *edit*. A notify rule can
        # afford to be more sensitive than an editing one.
        from flow.phonetic import MATCH_THRESHOLD
        from flow.session import NEAR_MISS_SIMILARITY

        self.assertEqual(NEAR_MISS_SIMILARITY, 0.78)
        self.assertNotEqual(NEAR_MISS_SIMILARITY, MATCH_THRESHOLD)

    def test_no_word_in_the_corpus_scores_high_enough(self):
        # The sweep, kept: every distinct one- and two-word sequence in the 580 real
        # EdAcc utterances, against all six presets and their enter-variants. Zero fires
        # at the shipped threshold, which is the whole reason it is the shipped one.
        from flow.edits import SEND_WORD_PRESETS
        from flow.phonetic import similarity
        from flow.session import NEAR_MISS_SIMILARITY

        bench = Path(__file__).resolve().parent.parent / ".bench" / "accent"
        manifests = sorted(bench.glob("manifest-edacc*.jsonl"))
        if not manifests:
            self.skipTest("no EdAcc manifest - run scripts/fetch_accent_data.py")
        grams = set()
        for mf in manifests:
            with mf.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    words = json.loads(line)["ref"].split()
                    grams.update(words)
                    grams.update(" ".join(words[i:i + 2])
                                 for i in range(len(words) - 1))
        grams = {g.strip(" .,!?") for g in grams if g.strip(" .,!?")}
        fired = []
        for gram in grams:
            for word in SEND_WORD_PRESETS:
                trigs = (word, enter_word(word))
                if gram.lower() in [t.lower() for t in trigs]:
                    continue
                if max(similarity(gram, t) for t in trigs) >= NEAR_MISS_SIMILARITY:
                    fired.append((gram, word))
                    break
        self.assertEqual(fired, [],
                         f"{len(fired)} false fires in {len(grams)} sequences")
