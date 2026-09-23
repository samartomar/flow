"""History, Paste last and Conversations (decisions.md 2026-09-23, "History").

Pinned here:

- **the store keeps nothing until somebody chooses to keep**, and "off" deletes what was
  kept; a choice that changes between a Send and its write is honoured at the write;
- **the file is plain, bounded and forgiving**: one JSON line per entry, pruned by age and
  by count, a hand-broken line costing that line and not the page;
- **the session records what happened**, never what it guessed: a handover as dictated or
  refined, a final's rejection as set aside, both halves of an Ask — and a typed question
  from Flow Home is answered on the page, not read aloud and not raised on the pill;
- **Flow Home's two pages** read and change all of it through the API: the choice, the
  retention, a fix that can reach the dictionary, a kept conversation carried on;
- **Paste last** waits for the keys that asked for it, hands the foreground back after the
  tray, and pastes through the one `on_send` every paste goes through;
- **Continue in Flow** is Ask's footer chip, where Send would be.

Nothing here opens a microphone, loads a model, calls an agent CLI or touches `~/.flow`.
"""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.history as history  # noqa: E402
from flow import tray  # noqa: E402
from flow.history import (  # noqa: E402
    ANSWERED,
    ASKED,
    DICTATED,
    DICTATION,
    KEEP,
    OFF,
    REFINED,
    SET_ASIDE,
    History,
    NullHistory,
    make_entry,
)
from flow.home import Home  # noqa: E402
from flow.home import api as home_api  # noqa: E402
from flow.home.demo import FakeSession  # noqa: E402
from flow.profile import Profile  # noqa: E402
from flow.session import CONVERSE, DICTATE, Event, Session  # noqa: E402

from test_artifact import FakeAsr, FakeMic, FakeSpeaker  # noqa: E402


def folder(test: unittest.TestCase) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name)


def kept(test: unittest.TestCase, choice=KEEP, days=30) -> History:
    """A history over a profile of its own, with `choice` made."""
    where = folder(test)
    profile = Profile(where / "profile.json")
    profile.history = choice
    profile.history_days = days
    h = History(where / "history.jsonl", profile)
    test.addCleanup(h.flush)
    return h


def lines(h: History) -> list[dict]:
    h.flush()
    if not h.path.exists():
        return []
    return [json.loads(line) for line in h.path.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------------------ the store


class TestNothingIsKeptUntilSomebodyChooses(unittest.TestCase):
    def test_not_chosen_keeps_nothing_and_writes_nothing(self):
        h = kept(self, choice=None)
        self.assertEqual(h.choice, "")
        self.assertFalse(h.keeping)
        self.assertIsNone(h.add(DICTATED, "a secret sentence"))
        h.flush()
        self.assertFalse(h.path.exists())
        self.assertEqual(h.entries(), [])

    def test_off_keeps_nothing(self):
        h = kept(self, choice=OFF)
        self.assertIsNone(h.add(DICTATED, "a secret sentence"))
        h.flush()
        self.assertFalse(h.path.exists())

    def test_no_profile_is_nowhere_to_have_chosen(self):
        # `--no-profile` promises nothing is traced and nothing is counted; nothing is
        # kept either, because there is nowhere a choice could have been made.
        h = History(folder(self) / "history.jsonl", None)
        self.assertEqual(h.choice, "")
        self.assertIsNone(h.add(DICTATED, "words"))

    def test_keep_writes_one_json_line_per_entry(self):
        h = kept(self)
        h.add(DICTATED, "Send the report to Bob.", app="slack.exe", words=5, how="pasted")
        h.add(DICTATED, "Add the rollback plan.", words=4, how="pasted")
        rows = lines(h)
        self.assertEqual([r["text"] for r in rows],
                         ["Send the report to Bob.", "Add the rollback plan."])
        self.assertEqual(rows[0]["app"], "slack.exe")
        self.assertEqual({r["kind"] for r in rows}, {DICTATED})

    def test_entries_are_newest_first_and_filter_by_kind_and_words(self):
        h = kept(self)
        h.add(DICTATED, "first thing")
        h.add(SET_ASIDE, "Thank you.", reason="filler")
        h.add(REFINED, "second thing", heard="second thang")
        self.assertEqual([e["text"] for e in h.entries()],
                         ["second thing", "Thank you.", "first thing"])
        self.assertEqual([e["text"] for e in h.entries((SET_ASIDE,))], ["Thank you."])
        self.assertEqual([e["text"] for e in h.entries(query="THANG")], ["second thing"])

    def test_paused_keeps_nothing_and_leaves_the_choice_alone(self):
        h = kept(self)
        h.paused = True
        self.assertFalse(h.keeping)
        self.assertIsNone(h.add(DICTATED, "a password, said aloud"))
        self.assertEqual(h.choice, KEEP)
        h.paused = False
        h.add(DICTATED, "after")
        self.assertEqual([r["text"] for r in lines(h)], ["after"])

    def test_off_chosen_after_a_send_is_honoured_at_the_write(self):
        # The Send enqueues; somebody chooses off before the writer takes it. The entry
        # must not land after the wipe — that would be a file of words nobody kept.
        h = kept(self)
        h.flush()
        gate = threading.Event()
        h._ops.put((gate.wait, (), None))  # hold the writer
        h.add(DICTATED, "said just before choosing off")
        h.profile.history = OFF
        gate.set()
        h.flush()
        self.assertFalse(h.path.exists())

    def test_forget_deletes_the_file(self):
        h = kept(self)
        h.add(DICTATED, "words")
        h.flush()
        self.assertTrue(h.path.exists())
        h.profile.history = OFF
        self.assertTrue(h.forget())
        self.assertFalse(h.path.exists())
        self.assertIsNone(h.newest)


class TestTheFileIsBoundedAndForgiving(unittest.TestCase):
    def test_old_entries_are_dropped_by_the_retention(self):
        h = kept(self, days=7)
        now = time.time()
        h.keep(make_entry(DICTATED, "ten days ago", at=now - 10 * 86400))
        h.keep(make_entry(DICTATED, "yesterday", at=now - 86400))
        self.assertEqual([e["text"] for e in h.entries()], ["yesterday"])
        self.assertEqual([r["text"] for r in lines(h)], ["yesterday"])

    def test_a_shorter_retention_applies_at_the_next_read(self):
        h = kept(self, days=90)
        h.keep(make_entry(DICTATED, "a month ago", at=time.time() - 31 * 86400))
        self.assertEqual(len(h.entries()), 1)
        h.profile.history_days = 30
        self.assertEqual(h.entries(), [])

    def test_the_count_ceiling_drops_the_oldest(self):
        h = kept(self)
        with mock.patch.object(history, "MAX_ENTRIES", 3):
            for i in range(5):
                h.add(DICTATED, f"entry {i}")
            texts = [e["text"] for e in h.entries()]
        self.assertEqual(texts, ["entry 4", "entry 3", "entry 2"])

    def test_a_broken_line_costs_that_line_and_is_counted(self):
        where = folder(self)
        profile = Profile(where / "profile.json")
        profile.history = KEEP
        good = make_entry(DICTATED, "kept words")
        (where / "history.jsonl").write_text(
            "\n".join([
                json.dumps(good),
                "{not json",
                json.dumps({"id": "x", "at": True, "kind": DICTATED, "text": "t"}),
                json.dumps({"id": "y", "at": 1.0, "kind": "shouted", "text": "t"}),
                "",
            ]), encoding="utf-8")
        h = History(where / "history.jsonl", profile)
        self.addCleanup(h.flush)
        self.assertEqual([e["text"] for e in h.entries()], ["kept words"])
        self.assertEqual(h.unreadable, 3)

    def test_a_field_of_the_wrong_type_is_dropped_not_coerced(self):
        where = folder(self)
        profile = Profile(where / "profile.json")
        profile.history = KEEP
        raw = make_entry(DICTATED, "words")
        raw.update({"words": True, "app": 7, "secs": float("inf"), "invented": "x"})
        (where / "history.jsonl").write_text(json.dumps(raw) + "\n", encoding="utf-8")
        h = History(where / "history.jsonl", profile)
        self.addCleanup(h.flush)
        (entry,) = h.entries()
        for field in ("words", "app", "secs", "invented"):
            self.assertNotIn(field, entry)

    def test_the_same_set_aside_words_in_a_row_are_kept_once(self):
        # Whisper writes "Thank you." at the end of many holds; twelve of them in a
        # row is a page nobody reads down.
        h = kept(self)
        for _ in range(3):
            h.add(SET_ASIDE, "Thank you.", reason="filler")
        h.add(SET_ASIDE, "something else", reason="unconfident")
        self.assertEqual([e["text"] for e in h.entries()], ["something else", "Thank you."])

    def test_update_remove_and_clear(self):
        h = kept(self)
        a = h.add(DICTATED, "check the cube control logs")
        b = h.add(DICTATED, "second")
        h.add(ASKED, "a question", conv="c1")
        fixed = h.update(a["id"], text="check the kubectl logs", fixed=True)
        self.assertEqual(fixed["text"], "check the kubectl logs")
        self.assertTrue(fixed["fixed"])
        self.assertTrue(h.remove(b["id"]))
        self.assertFalse(h.remove(b["id"]))
        self.assertEqual(h.clear(DICTATION), 1)
        self.assertEqual([r["kind"] for r in lines(h)], [ASKED])

    def test_newest_is_what_paste_last_falls_back_to(self):
        h = kept(self)
        h.add(DICTATED, "first")
        h.add(SET_ASIDE, "Thank you.")
        h.add(REFINED, "second")
        h.flush()
        self.assertEqual(h.newest["text"], "second")
        # And after a restart, read back off the file.
        again = History(h.path, h.profile)
        self.addCleanup(again.flush)
        again.flush()
        self.assertEqual(again.newest["text"], "second")

    def test_conversations_are_grouped_and_titled_by_their_first_question(self):
        h = kept(self)
        now = time.time()
        for kind, text, conv, at in [(ASKED, "old question", "c1", now - 50),
                                     (ANSWERED, "old answer", "c1", now - 49),
                                     (ASKED, "new question", "c2", now - 10),
                                     (ASKED, "follow-up", "c1", now - 5)]:
            h.keep(make_entry(kind, text, conv=conv, at=at, ws="D:\\dev\\acme"))
        convs = h.conversations()
        self.assertEqual([c["conv"] for c in convs], ["c1", "c2"])
        self.assertEqual(convs[0]["title"], "old question")
        self.assertEqual(convs[0]["asked"], 2)
        self.assertEqual(convs[0]["ws"], "D:\\dev\\acme")
        self.assertEqual([e["text"] for e in h.conversation("c1")],
                         ["old question", "old answer", "follow-up"])
        self.assertEqual(h.remove_conversation("c1"), 3)
        self.assertEqual([c["conv"] for c in h.conversations()], ["c2"])

    def test_null_history_answers_every_question_with_nothing(self):
        n = NullHistory()
        self.assertFalse(n.keeping)
        self.assertIsNone(n.add(DICTATED, "x"))
        self.assertEqual((n.entries(), n.conversations(), n.conversation("c")), ([], [], []))
        self.assertIsNone(n.get("x"))
        self.assertTrue(n.forget() and n.flush())


# ------------------------------------------------------------------------------ the profile


class TestTheChoiceIsAProfileField(unittest.TestCase):
    def test_it_starts_unchosen_and_round_trips(self):
        path = folder(self) / "profile.json"
        p = Profile(path)
        self.assertIsNone(p.history)
        self.assertEqual(p.history_days, 30)
        p.history, p.history_days = KEEP, 90
        p.save()
        again = Profile(path)
        self.assertEqual((again.history, again.history_days), (KEEP, 90))
        self.assertEqual(again.faults, [])

    def test_a_stray_value_is_no_choice_and_is_named(self):
        path = folder(self) / "profile.json"
        path.write_text(json.dumps({"schema": 1, "history": "yes", "history_days": 45}),
                        encoding="utf-8")
        p = Profile(path)
        self.assertIsNone(p.history)
        self.assertEqual(p.history_days, 30)
        self.assertIn("history", p.faults)
        self.assertIn("history_days", p.faults)


# ------------------------------------------------------------------------------ the session


def session(test, choice=KEEP, **kw) -> tuple[Session, History]:
    h = kept(test, choice=choice)
    s = Session(asr=FakeAsr(), mic=FakeMic(), profile=h.profile, history=h, **kw)
    test.addCleanup(s.close)
    return s, h


class TestTheSessionRecordsHandovers(unittest.TestCase):
    def test_a_paste_is_kept_as_dictated_with_where_it_went(self):
        s, h = session(self)
        s.target_app = "WindowsTerminal.exe"
        s.delivered("check the logs for the staging pod")
        (e,) = h.entries()
        self.assertEqual((e["kind"], e["app"], e["words"], e["how"]),
                         (DICTATED, "WindowsTerminal.exe", 7, "pasted"))

    def test_a_refusal_is_kept_as_not_pasted_with_its_reason(self):
        s, h = session(self)
        s.delivered("words", "not pasted: Flow had the focus")
        (e,) = h.entries()
        self.assertEqual(e["how"], "not pasted")
        self.assertIn("Flow had the focus", e["note"])

    def test_a_warning_is_still_a_paste(self):
        s, h = session(self)
        s.delivered("words", "your clipboard held an image - it will not be restored")
        self.assertEqual(h.entries()[0]["how"], "pasted")

    def test_a_copy_is_a_copy(self):
        s, h = session(self)
        s.delivered("words", copied=True)
        s.delivered("more words", "could not copy: busy", copied=True)
        self.assertEqual([e["how"] for e in h.entries()], ["not copied", "copied"])

    def test_the_refine_result_is_kept_as_refined_with_what_was_heard(self):
        s, h = session(self)
        s._refined = {"text": "Strip every control.", "heard": "make it plain",
                      "cli": "claude", "secs": 6.1}
        s.delivered("Strip every control.")
        (e,) = h.entries()
        self.assertEqual((e["kind"], e["heard"], e["cli"], e["secs"]),
                         (REFINED, "make it plain", "claude", 6.1))

    def test_raw_words_after_a_failed_refine_are_dictation(self):
        s, h = session(self)
        s._refined = {"text": "something the CLI made", "heard": "x", "cli": "c",
                      "secs": 1.0}
        s.delivered("the raw dictation")
        self.assertEqual(h.entries()[0]["kind"], DICTATED)

    def test_paste_last_is_this_launch_first_then_the_kept_file(self):
        s, h = session(self)
        self.assertEqual(s.last_handed, "")
        h.add(DICTATED, "from yesterday")
        h.flush()
        self.assertEqual(s.last_handed, "from yesterday")
        s.delivered("just now")
        self.assertEqual(s.last_handed, "just now")

    def test_paste_last_needs_no_history(self):
        s, _h = session(self, choice=None)
        s.delivered("just now")
        self.assertEqual(s.last_handed, "just now")

    def test_a_finals_rejection_is_kept_as_set_aside_and_a_partials_is_not(self):
        from flow.asr import Drop

        s, h = session(self)
        s.asr.take_drops = lambda: [Drop(" Thank you.", "filler", 0.9, -1.0, True),
                                    Drop(" you", "filler", 0.9, -1.0, False)]
        s._pump_drops()
        (e,) = h.entries()
        self.assertEqual((e["kind"], e["text"], e["reason"]),
                         (SET_ASIDE, "Thank you.", "filler"))

    def test_a_whole_session_with_history_unchosen_writes_nothing(self):
        # Item 65's stance, kept: unchosen is the state every profile starts in.
        s, h = session(self, choice=None)
        s.delivered("a secret sentence nobody may store")
        s._start_ask = mock.Mock()
        h.flush()
        self.assertEqual(sorted(p.name for p in h.path.parent.iterdir()), [])


class TestTheSessionRecordsAsks(unittest.TestCase):
    def ask(self, s, question="how do I widen a column", answer=("ALTER TABLE.", "codex"),
            typed=False):
        with mock.patch("flow.session.ask", return_value=answer), \
                mock.patch.object(Session, "_provider", return_value="codex"):
            if typed:
                self.assertEqual(s.ask(question), "")
            else:
                s.draft.set(question)
                s.send()
            s.wait_idle(timeout=5.0)

    def test_both_halves_are_on_the_page_and_in_the_file(self):
        s, h = session(self)
        s.toggle_mode(to=CONVERSE)
        self.ask(s)
        self.assertEqual([e["kind"] for e in s.exchanges], [ASKED, ANSWERED])
        self.assertEqual(s.exchanges[0]["via"], "voice")
        self.assertEqual(s.exchanges[1]["cli"], "codex")
        kept_rows = h.conversation(s.conversation)
        self.assertEqual([e["text"] for e in kept_rows], ["how do I widen a column",
                                                          "ALTER TABLE."])

    def test_the_page_keeps_the_conversation_even_with_history_off(self):
        s, h = session(self, choice=OFF)
        s.toggle_mode(to=CONVERSE)
        self.ask(s)
        self.assertEqual(len(s.exchanges), 2)
        h.flush()
        self.assertFalse(h.path.exists())

    def test_a_failed_ask_is_an_answer_that_did_not_come(self):
        s, _h = session(self)
        s.toggle_mode(to=CONVERSE)
        self.ask(s, answer=(None, "codex timed out"))
        last = s.exchanges[-1]
        self.assertEqual((last["kind"], last["failed"]), (ANSWERED, "codex timed out"))

    def test_a_typed_question_is_answered_on_the_page_and_not_read_aloud(self):
        sp = FakeSpeaker()
        s, _h = session(self, speaker=sp)
        self.ask(s, typed=True)
        kinds = [ev.kind for ev in s.events()]
        self.assertIn("answer", kinds)
        self.assertNotIn("reply", kinds)
        self.assertEqual(sp.said, [])
        self.assertEqual(s.exchanges[0]["via"], "typed")
        # The pill's mode is left alone: typing on the page is not a mode switch.
        self.assertEqual(s.mode, DICTATE)
        self.assertEqual(s.reply, "ALTER TABLE.")

    def test_a_spoken_question_still_raises_the_pill_and_is_read(self):
        sp = FakeSpeaker()
        s, _h = session(self, speaker=sp)
        s.toggle_mode(to=CONVERSE)
        self.ask(s)
        self.assertIn("reply", [ev.kind for ev in s.events()])
        self.assertEqual(sp.said, ["ALTER TABLE."])

    def test_typed_refusals_are_said(self):
        s, _h = session(self)
        self.assertEqual(s.ask("   "), "type a question first")
        with mock.patch.object(Session, "_provider", return_value=""):
            self.assertIn("no agent CLI", s.ask("a question"))
        s._ask_op = 7
        self.assertEqual(s.ask("a question"), "still waiting on the last answer")

    def test_a_new_conversation_or_a_workspace_switch_starts_a_new_id(self):
        s, _h = session(self)
        first = s.conversation
        s.exchanges.append(make_entry(ASKED, "q"))
        s.new_conversation()
        self.assertNotEqual(s.conversation, first)
        self.assertEqual(list(s.exchanges), [])
        second = s.conversation
        s.exchanges.append(make_entry(ASKED, "q"))
        s.set_workspace(str(folder(self)))
        self.assertNotEqual(s.conversation, second)
        self.assertEqual(list(s.exchanges), [])

    def test_resume_rebuilds_the_thread_the_cli_is_told(self):
        s, _h = session(self)
        entries = [make_entry(ASKED, "first question", conv="c9"),
                   make_entry(ANSWERED, "first answer", conv="c9"),
                   make_entry(ANSWERED, "", conv="c9", failed="timed out"),
                   make_entry(ASKED, "second question", conv="c9")]
        self.assertEqual(s.resume("c9", entries), "")
        self.assertEqual(s.conversation, "c9")
        self.assertEqual(s.thread.turns, ["first question", "(reply) first answer",
                                          "second question"])
        self.assertEqual(s.reply, "first answer")
        self.assertEqual(len(s.exchanges), 4)

    def test_resume_refuses_while_an_answer_is_coming(self):
        s, _h = session(self)
        s._ask_op = 3
        self.assertIn("still waiting", s.resume("c9", [make_entry(ASKED, "q")]))

    def test_keep_note_can_name_the_question(self):
        s, _h = session(self)
        self.assertTrue(s.keep_note("an older answer", question="an older question"))
        (note,) = s.notes.all
        self.assertEqual((note.text, note.question), ("an older answer", "an older question"))

    def test_homes_wrap_up_is_an_answer_not_a_reply(self):
        s, _h = session(self)
        s.keep_note("worth keeping")
        s.events()
        self.assertTrue(s.wrap_up(pill=False))
        kinds = [ev.kind for ev in s.events()]
        self.assertIn("answer", kinds)
        self.assertNotIn("reply", kinds)
        self.assertEqual(s.wrapped_to, "")


# ------------------------------------------------------------------------------ the API


class Pumped:
    """A Home over the demo's FakeSession, pumped on a thread as a pill's frames would."""

    def __init__(self, test: unittest.TestCase, choice=None) -> None:
        self.folder = folder(test)
        self.profile = Profile(self.folder / "profile.json")
        self.profile.history = choice
        self.session = FakeSession(self.profile)
        self.session.answer_sec = 0.05
        test.addCleanup(self.session.history.flush)
        self._stop = threading.Event()
        threading.Thread(target=self._pump, daemon=True).start()
        test.addCleanup(self._stop.set)
        self.home = Home(self.session, profile=self.profile, hotkeys=None, lite=False,
                         lexicon_path=self.folder / "lexicon.txt",
                         trace_path=self.folder / "diag.jsonl")
        test.addCleanup(self.home.close)

    def _pump(self) -> None:
        while not self._stop.is_set():
            self.session.run_posted()
            time.sleep(0.005)

    def call(self, path: str, body: dict | None = None, method: str = "POST"):
        return self.home.api.handle(method, path, body or {})


class TestTheHistoryPage(unittest.TestCase):
    def test_unchosen_asks_and_shows_nothing(self):
        h = Pumped(self)
        code, page = h.call("/api/history", method="GET")
        self.assertEqual(code, 200)
        self.assertEqual((page["choice"], page["entries"]), ("", []))

    def test_choosing_keep_then_a_paste_shows_up(self):
        h = Pumped(self)
        code, page = h.call("/api/history/choice", {"choice": "keep"})
        self.assertEqual((code, page["choice"], page["keeping"]), (200, "keep", True))
        self.assertEqual(Profile(h.profile.path).history, KEEP)
        h.session.delivered("Thanks, I will send the figures by Friday.")
        h.session.history.flush()
        _c, page = h.call("/api/history", method="GET")
        (e,) = page["entries"]
        self.assertEqual((e["app"], e["day"], e["words"]), ("Windows Terminal", "Today", 8))
        self.assertEqual(page["today"]["pastes"], 1)

    def test_choosing_off_deletes_what_was_kept(self):
        h = Pumped(self, choice=KEEP)
        h.session.delivered("words")
        h.session.history.flush()
        self.assertTrue(h.session.history.path.exists())
        code, page = h.call("/api/history/choice", {"choice": "off"})
        self.assertEqual((code, page["choice"]), (200, "off"))
        self.assertFalse(h.session.history.path.exists())

    def test_a_choice_that_is_neither_is_refused(self):
        h = Pumped(self)
        code, _page = h.call("/api/history/choice", {"choice": "maybe"})
        self.assertEqual(code, 400)

    def test_retention_is_one_of_three(self):
        h = Pumped(self, choice=KEEP)
        self.assertEqual(h.call("/api/history/days", {"days": 45})[0], 400)
        self.assertEqual(h.call("/api/history/days", {"days": True})[0], 400)
        code, page = h.call("/api/history/days", {"days": 7})
        self.assertEqual((code, page["days"]), (200, 7))

    def test_pause_filter_search_delete_and_clear(self):
        h = Pumped(self, choice=KEEP)
        for text in ("check the logs", "send the report"):
            h.session.delivered(text)
        h.session.history.add(SET_ASIDE, "Thank you.", reason="filler")
        h.session.history.flush()
        _c, page = h.call("/api/history/list", {"kind": "set_aside"})
        self.assertEqual([e["text"] for e in page["entries"]], ["Thank you."])
        self.assertIn("room", page["entries"][0]["why"])
        _c, page = h.call("/api/history/list", {"query": "REPORT"})
        self.assertEqual([e["text"] for e in page["entries"]], ["send the report"])
        self.assertEqual(page["counts"], {"all": 3, "dictated": 2, "refined": 0,
                                          "set_aside": 1})
        _c, page = h.call("/api/history/pause", {"paused": True})
        self.assertTrue(page["paused"])
        target = page["entries"][0]["id"]
        _c, page = h.call("/api/history/delete", {"id": target})
        self.assertEqual(page["counts"]["all"], 2)
        self.assertEqual(h.call("/api/history/delete", {"id": target})[0], 400)
        _c, page = h.call("/api/history/clear", {})
        self.assertEqual(page["counts"]["all"], 0)

    def test_fix_here_changes_the_entry_and_nothing_else(self):
        h = Pumped(self, choice=KEEP)
        h.session.delivered("check the cube control logs")
        h.session.history.flush()
        entry = h.session.history.entries()[0]
        code, page = h.call("/api/history/fix", {"id": entry["id"], "wrong": "Cube Control",
                                                 "right": "kubectl"})
        self.assertEqual(code, 200)
        self.assertEqual(page["entries"][0]["text"], "check the kubectl logs")
        self.assertTrue(page["entries"][0]["fixed"])
        self.assertFalse((h.folder / "lexicon.txt").exists())

    def test_always_fix_it_reaches_the_dictionary(self):
        h = Pumped(self, choice=KEEP)
        h.session.delivered("check the cube control logs")
        h.session.history.flush()
        entry = h.session.history.entries()[0]
        code, _page = h.call("/api/history/fix", {"id": entry["id"], "wrong": "cube control",
                                                  "right": "kubectl", "always": True})
        self.assertEqual(code, 200)
        _c, voice = h.call("/api/voice", method="GET")
        self.assertIn({"wrong": "cube control", "right": "kubectl"},
                      voice["dictionary"]["corrections"])

    def test_a_fix_for_words_that_are_not_there_is_refused(self):
        h = Pumped(self, choice=KEEP)
        h.session.delivered("check the logs")
        h.session.history.flush()
        entry = h.session.history.entries()[0]
        for body, why in [({"wrong": "cube", "right": "kube"}, "is not in this entry"),
                          ({"wrong": "logs", "right": "logs"}, "the same words"),
                          ({"wrong": "", "right": "x"}, "say what Flow wrote")]:
            code, page = h.call("/api/history/fix", {"id": entry["id"], **body})
            self.assertEqual(code, 400)
            self.assertIn(why, page["error"])
        # A correction the dictionary refuses leaves the entry as it was.
        code, _page = h.call("/api/history/fix", {"id": entry["id"], "wrong": "logs",
                                                  "right": "a # comment", "always": True})
        self.assertEqual(code, 400)
        self.assertEqual(h.session.history.entries()[0]["text"], "check the logs")

    def test_a_fix_replacement_is_taken_literally(self):
        # The user's words are a replacement, never a pattern: `\1` is two characters.
        h = Pumped(self, choice=KEEP)
        h.session.delivered("the dir is here")
        h.session.history.flush()
        entry = h.session.history.entries()[0]
        _c, page = h.call("/api/history/fix", {"id": entry["id"], "wrong": "dir",
                                               "right": "C:\\1"})
        self.assertEqual(page["entries"][0]["text"], "the C:\\1 is here")


class TestTheConversationsPage(unittest.TestCase):
    def wait_for(self, h, test, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if test():
                return
            time.sleep(0.02)
        self.fail("it never happened")

    def test_a_typed_question_is_asked_and_answered(self):
        h = Pumped(self, choice=KEEP)
        code, page = h.call("/api/ask/question", {"text": "where is the hold decided?"})
        self.assertEqual(code, 200)
        self.assertTrue(page["current"]["asking"])
        self.assertEqual(page["current"]["title"], "where is the hold decided?")
        self.wait_for(h, lambda: not h.session.asking)
        _c, page = h.call("/api/ask", method="GET")
        kinds = [e["kind"] for e in page["current"]["exchanges"]]
        self.assertEqual(kinds, [ASKED, ANSWERED])

    def test_the_composer_refuses_an_empty_or_enormous_question(self):
        h = Pumped(self)
        self.assertEqual(h.call("/api/ask/question", {"text": "  "})[0], 400)
        code, page = h.call("/api/ask/question",
                            {"text": "x" * (home_api.MAX_QUESTION_CHARS + 1)})
        self.assertEqual(code, 400)
        self.assertIn("characters", page["error"])

    def test_kept_conversations_are_listed_and_viewed_and_carried_on(self):
        h = Pumped(self, choice=KEEP)
        hist = h.session.history
        hist.keep(make_entry(ASKED, "an old question", conv="old", ws="D:\\dev\\acme",
                             at=time.time() - 9 * 86400))
        hist.keep(make_entry(ANSWERED, "an old answer", conv="old",
                             at=time.time() - 9 * 86400 + 4))
        hist.flush()
        _c, page = h.call("/api/ask", method="GET")
        (past,) = page["past"]
        self.assertEqual((past["title"], past["ws_leaf"]), ("an old question", "acme"))
        _c, page = h.call("/api/ask/view", {"conv": "old"})
        self.assertEqual([e["text"] for e in page["viewing"]["exchanges"]],
                         ["an old question", "an old answer"])
        code, page = h.call("/api/ask/continue", {"conv": "old"})
        self.assertEqual(code, 200)
        self.assertEqual(page["current"]["conv"], "old")
        self.assertEqual(page["past"], [])

    def test_the_conversation_on_screen_cannot_be_deleted_from_under_it(self):
        h = Pumped(self, choice=KEEP)
        code, page = h.call("/api/ask/delete", {"conv": h.session.conversation})
        self.assertEqual(code, 400)
        self.assertIn("on screen", page["error"])

    def test_keep_note_keeps_the_answer_with_its_question(self):
        h = Pumped(self, choice=KEEP)
        h.call("/api/ask/question", {"text": "which file?"})
        self.wait_for(h, lambda: not h.session.asking)
        answer = h.session.exchanges[-1]
        code, _page = h.call("/api/ask/note", {"id": answer["id"]})
        self.assertEqual(code, 200)
        (note,) = h.session.notes.all
        self.assertEqual(note.question, "which file?")
        code, page = h.call("/api/ask/wrap", {})
        self.assertEqual(code, 200)
        self.assertEqual(page["wrapped"]["count"], 1)
        self.assertIn("which file?", page["wrapped"]["doc"])
        code, page = h.call("/api/ask/wrap", {})
        self.assertEqual(code, 400)

    def test_read_aloud_speaks_the_answer_it_names(self):
        h = Pumped(self)
        h.call("/api/ask/question", {"text": "which file?"})
        self.wait_for(h, lambda: not h.session.asking)
        answer = h.session.exchanges[-1]
        code, _page = h.call("/api/ask/say", {"id": answer["id"]})
        self.assertEqual(code, 200)
        self.assertEqual(h.session.speaker.said, [answer["text"]])
        self.assertEqual(h.call("/api/ask/say", {"id": "nope"})[0], 404)

    def test_the_live_strip_says_when_the_conversation_moved(self):
        h = Pumped(self)
        _c, state = h.call("/api/state", method="GET")
        self.assertEqual((state["asking"], state["exchanges"]), (False, 0))
        self.assertEqual(state["conversation"], h.session.conversation)


class TestThePagesAgainstARealSession(unittest.TestCase):
    """The demo's FakeSession is what the page tests above drive; this is the same routes
    over the real `Session`, pumped the way a pill pumps it, so the two cannot drift."""

    def test_ask_note_wrap_and_history_end_to_end(self):
        h = kept(self)
        s = Session(asr=FakeAsr(), mic=FakeMic(), profile=h.profile, history=h)
        self.addCleanup(s.close)
        stop = threading.Event()

        def pump():
            while not stop.is_set():
                s.pump_results()
                time.sleep(0.005)

        threading.Thread(target=pump, daemon=True).start()
        self.addCleanup(stop.set)
        home = Home(s, profile=h.profile, hotkeys=None, lite=False,
                    lexicon_path=h.path.parent / "lexicon.txt", trace_path=None)
        self.addCleanup(home.close)
        call = home.api.handle
        with mock.patch("flow.session.ask", return_value=("ALTER TABLE.", "codex")), \
                mock.patch.object(Session, "_provider", return_value="codex"):
            code, page = call("POST", "/api/ask/question", {"text": "how do I widen a column"})
            self.assertEqual(code, 200, page)
            deadline = time.time() + 5
            while s.asking and time.time() < deadline:
                time.sleep(0.02)
        code, page = call("GET", "/api/ask", {})
        self.assertEqual(code, 200, page)
        answer = page["current"]["exchanges"][-1]
        self.assertEqual((answer["kind"], answer["text"]), (ANSWERED, "ALTER TABLE."))
        self.assertEqual(call("POST", "/api/ask/note", {"id": answer["id"]})[0], 200)
        code, page = call("POST", "/api/ask/wrap", {})
        self.assertEqual(code, 200, page)
        self.assertIn("how do I widen a column", page["wrapped"]["doc"])
        self.assertEqual(page["wrapped"]["path"], "")
        s.delivered("check the logs")
        h.flush()
        code, page = call("GET", "/api/history", {})
        self.assertEqual([e["text"] for e in page["entries"]], ["check the logs"])
        code, state = call("GET", "/api/state", {})
        self.assertEqual(state["exchanges"], 2)
        self.assertEqual(state["conversation"], s.conversation)
        # And the kept file holds both halves of the question, under the same id.
        self.assertEqual([e["kind"] for e in h.conversation(s.conversation)], [ASKED, ANSWERED])


class TestHowThePagesSayThings(unittest.TestCase):
    def test_programs_are_called_what_people_call_them(self):
        self.assertEqual(home_api.app_name("WindowsTerminal.exe"), "Windows Terminal")
        self.assertEqual(home_api.app_name("OUTLOOK.EXE"), "Outlook")
        self.assertEqual(home_api.app_name("notepad++.exe"), "Notepad++")
        self.assertEqual(home_api.app_name("MyTool.exe"), "MyTool")
        self.assertEqual(home_api.app_name(""), "")
        self.assertEqual(home_api.app_name(None), "")

    def test_days_read_as_today_yesterday_and_a_date(self):
        now = time.mktime((2026, 9, 23, 10, 0, 0, 0, 0, -1))
        self.assertEqual(home_api._day(now - 3600, now), "Today")
        self.assertEqual(home_api._day(now - 20 * 3600, now), "Yesterday")
        self.assertEqual(home_api._day(now - 3 * 86400, now), "Sunday 20 September")
        self.assertEqual(home_api._when(now - 3 * 86400, now), "Sunday")
        self.assertEqual(home_api._when(now - 9 * 86400, now), "14 Sep")


# ------------------------------------------------------------------------------ the surfaces


import flow.ui_compact as uc  # noqa: E402
from test_menu import FakeMenu, FakeVar  # noqa: E402
from test_ui_compact import panel_pill, pill  # noqa: E402


class TestTheCompactSurfaceHandsOver(unittest.TestCase):
    def test_a_paste_is_reported_after_it_happens(self):
        sent = []
        p = pill(on_send=lambda text, target=None: sent.append(text) or "")
        p._deliver("the words")
        self.assertEqual(sent, ["the words"])
        p.session.delivered.assert_called_once_with("the words", "", False)

    def test_a_lite_copy_is_reported_as_a_copy(self):
        p = pill(on_send=None)
        p._say = mock.Mock()
        with mock.patch.object(uc, "_copy_to_clipboard", return_value=""):
            p._deliver("the words")
        p.session.delivered.assert_called_once_with("the words", "", True)

    def test_the_target_is_named_on_the_edge_and_the_taskbar_is_skipped(self):
        from flow.inject import Target

        p = pill(lite=False)
        p.session.target_app = ""
        with mock.patch.object(uc, "foreground_hwnd", return_value=11), \
                mock.patch.object(uc, "owned_by_flow", return_value=False), \
                mock.patch.object(uc, "classify",
                                  return_value=Target("CASCADIA", "WindowsTerminal.exe")) as c:
            p._track_target()
            p._track_target()
        self.assertEqual((p.paste_target, p.session.target_app), (11, "WindowsTerminal.exe"))
        c.assert_called_once_with(11)
        with mock.patch.object(uc, "foreground_hwnd", return_value=22), \
                mock.patch.object(uc, "owned_by_flow", return_value=False), \
                mock.patch.object(uc, "classify", return_value=Target("Shell_TrayWnd", "explorer.exe")):
            p._track_target()
        self.assertEqual((p.paste_target, p.session.target_app), (11, "WindowsTerminal.exe"))


class TestPasteLast(unittest.TestCase):
    def pasting(self, last="the last words", on_send=True):
        sent = []
        p = pill(on_send=(lambda text, target=None: sent.append((text, target)) or "")
                 if on_send else None)
        p.session.last_handed = last
        p.paste_target = 0xBEEF
        p._say = mock.Mock()
        return p, sent

    def test_it_waits_for_the_keys_then_pastes_into_the_target(self):
        p, sent = self.pasting()
        with mock.patch.object(uc, "modifiers_held", return_value=True):
            p._paste_last()
            p._pump_paste_last()
        self.assertEqual(sent, [])
        with mock.patch.object(uc, "modifiers_held", return_value=False):
            p._pump_paste_last()
        self.assertEqual(sent, [("the last words", 0xBEEF)])
        self.assertIsNone(p._paste_last_wait)
        # Paste last hands over something already kept: it is never kept again.
        p.session.delivered.assert_not_called()

    def test_keys_held_past_the_ceiling_paste_nothing_and_say_so(self):
        p, sent = self.pasting()
        with mock.patch.object(uc, "modifiers_held", return_value=True):
            p._paste_last()
            p._paste_last_wait = ("the last words", time.perf_counter() - 60, False)
            p._pump_paste_last()
        self.assertEqual(sent, [])
        self.assertIn("press it again", p._say.call_args[0][0])

    def test_the_tray_hands_the_foreground_back_first(self):
        p, sent = self.pasting()
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
                mock.patch.object(uc, "_user32") as user32:
            p._paste_last(restore=True)
            p._pump_paste_last()
            user32.SetForegroundWindow.assert_called_once_with(0xBEEF)
            self.assertEqual(sent, [])
            p._pump_paste_last()
        self.assertEqual(sent, [("the last words", 0xBEEF)])

    def test_nothing_sent_yet_is_said(self):
        p, sent = self.pasting(last="")
        p._paste_last()
        self.assertIsNone(p._paste_last_wait)
        self.assertIn("nothing to paste", p._say.call_args[0][0])

    def test_lite_copies(self):
        p, _sent = self.pasting(on_send=False)
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
                mock.patch.object(uc, "_copy_to_clipboard", return_value="") as copy:
            p._paste_last()
            p._pump_paste_last()
        copy.assert_called_once_with(p, "the last words")

    def test_the_shortcut_and_the_tray_both_reach_it(self):
        p, _sent = self.pasting()
        p._paste_last = mock.Mock()
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["paste_last"]
        p._drain_hotkeys()
        p._paste_last.assert_called_once_with()
        p._tray = mock.Mock()
        p._tray_events = __import__("queue").Queue()
        p._tray_events.put(tray.PASTE_LAST)
        p._drain_tray()
        p._paste_last.assert_called_with(restore=True)

    def test_the_menu_row_quotes_what_it_would_paste(self):
        p, _sent = self.pasting(last="Thanks, I will send the updated figures by Friday.")
        p.session.workspace = "~/dev/products/flow"
        m = FakeMenu()
        with mock.patch.object(uc.tk, "StringVar", FakeVar), \
                mock.patch.object(uc, "_dark_menu", FakeMenu):
            p._populate_menu(m)
        i = m.order.index("Paste last")
        self.assertTrue(m.order[i + 1].startswith("\u201cThanks, I will send"))
        self.assertTrue(m.order[i + 1].endswith("\u2026\u201d"))
        self.assertIsNotNone(m.commands["Paste last"])

    def test_the_hotkey_ships_bound_away_from_plain_text_paste(self):
        from flow.hotkey import DEFAULT_BINDINGS, describe

        combos = [describe(*b) for b in DEFAULT_BINDINGS["paste_last"]]
        self.assertEqual(combos[0], "ctrl+alt+V")
        self.assertNotIn("ctrl+shift+V", combos)

    def test_the_tray_menu_has_the_row(self):
        self.assertEqual(tray.PASTE_LAST, "paste_last")


import flow.ui as ui  # noqa: E402
from test_pill import pill as classic_pill  # noqa: E402


class TestTheClassicSurface(unittest.TestCase):
    """The design being retired gets the same two doors: every Send is reported, and
    Paste last arrives from the shortcut and the tray. Its menu is left as it was."""

    def classic(self, sent, **attrs):
        p = classic_pill(on_send=lambda text, target=None, **kw: sent.append((text, target)) or "",
                         **attrs)
        p.bubble = mock.Mock()
        p.card = mock.Mock()
        p.paste_target = 7
        return p

    def test_a_send_is_reported_after_the_paste(self):
        sent = []
        p = self.classic(sent, lite=False)
        p.session.send.return_value = "the words"
        p._send()
        self.assertEqual(sent, [("the words", 7)])
        p.session.delivered.assert_called_once_with("the words", "", False)

    def test_paste_last_waits_for_the_keys_and_the_tray_hands_focus_back(self):
        sent = []
        p = self.classic(sent)
        p.session.last_handed = "again"
        with mock.patch.object(ui, "modifiers_held", return_value=False), \
                mock.patch.object(ui, "_user32") as user32:
            p._paste_last(restore=True)
            p._pump_paste_last()
            user32.SetForegroundWindow.assert_called_once_with(7)
            p._pump_paste_last()
        self.assertEqual(sent, [("again", 7)])
        p.session.delivered.assert_not_called()

    def test_the_shortcut_reaches_it(self):
        p = self.classic([])
        p._paste_last = mock.Mock()
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = ["paste_last"]
        p._drain_hotkeys()
        p._paste_last.assert_called_once_with()


class TestContinueInFlow(unittest.TestCase):
    def test_asks_footer_carries_the_conversation_to_the_page(self):
        p = panel_pill(mode=CONVERSE)
        p._panel_open = True
        p._panel_result = "the answer"
        p.session.home = mock.Mock()
        p.session.home.open.return_value = ""
        rect = uc._continue_rect(p._panel_layout().footer_y)
        p._panel_click(mock.Mock(x=rect[0] + 6, y=rect[1] + 6))
        p.session.home.open.assert_called_once_with("ask")
        self.assertFalse(p._panel_open)

    def test_refine_has_send_there_instead(self):
        self.assertFalse(uc.PANEL_SPEC[uc.REFINE].get("continue"))
        self.assertTrue(uc.PANEL_SPEC[CONVERSE]["continue"])

    def test_the_chip_fits_beside_the_hint(self):
        # Right of the hold hint, inside the band, the same height as Copy.
        x1, y1, x2, y2 = uc._continue_rect(100)
        copy = uc._chip_rects(100)[0]
        self.assertGreater(x1, copy[2] + 150)
        self.assertLessEqual(x2, uc.PANEL_W - 16)
        self.assertEqual(y2 - y1, uc.CHIP_H)


if __name__ == "__main__":
    unittest.main()
