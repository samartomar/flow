"""Every command spoken into a real microphone, replayed against the same draft.

Three live runs of the eleven-item sheet (2026-08-01) scored **7/11, 8/11 and 6/11, and
no two runs missed the same set**. That is the finding, and it survives being looked at
three times: the dominant failure is ASR variance on the command phrase itself, a small
number of stable gaps sit underneath it, and a single take of the sheet is not a
measurement of anything. So a grammar change is judged against all three takes at once,
which is what this table is for — every utterance the microphone actually produced,
with what Flow does with it now, so any edit to `edits.py` shows exactly which rows it
moves and which it does not.

`recorded` is what `scripts/live_check.py` wrote on the day
(`.bench/live/live-check.json` at `5649ee3`, `bdfffb3` and `b268498`); `now` is what the
shipped grammar does. Every one of the 33 rows agreed until this item's two fixes, which
is worth saying: the harness routes through the same `plan()` the app does, and nothing
has drifted underneath the recordings since.

Fixtures are not aspirations. A row whose `now` is a miss pins a *defect*, deliberately,
so that the day it changes is a day somebody chose — several of them want a re-measured
threshold or a design decision, and both are recorded in NEEDS_YOU.md rather than being
guessed at here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from flow.edits import plan  # noqa: E402
from flow.phonetic import MATCH_THRESHOLD, similarity, sounds_like  # noqa: E402
from live_check import COMMANDS, DRAFT, stability  # noqa: E402

#: (run, item, what the microphone produced, what the sheet wanted, what the harness
#: recorded that day, what Flow routes it as now).
ROWS = [
    ("run 1", 1, "Change every Tuesday to Wednesday.", "local/replace_all",
     "local/replace_all", "local/replace_all"),
    ("run 1", 2, "Change Semir to Samir", "local/replace",
     "semantic/", "semantic/"),
    ("run 1", 3, "Capitalized Sabeer", "local/capitalize",
     "local/capitalize", "local/capitalize"),
    ("run 1", 4, "lowercase release notes", "local/lower",
     "local/lower", "local/lower"),
    ("run 1", 5, "Delete the bit about standard.", "local/delete",
     "append/", "append/"),
    ("run 1", 6, "Delete the last sentence", "local/delete_last",
     "local/delete_last", "local/delete_last"),
    ("run 1", 7, "Insert draft before release notes", "local/insert_before",
     "local/insert_before", "local/insert_before"),
    ("run 1", 8, "and do that", "undo/", "undo/", "undo/"),
    ("run 1", 9, "Make it a proper brown.", "semantic/polish",
     "semantic/", "semantic/polish"),
    ("run 1", 10, "follow and mention the roleback plan", "followup/",
     "append/", "followup/"),
    ("run 1", 11, "That was a command.", "rescue/", "rescue/", "rescue/"),

    ("run 2", 1, "Change every Tuesday to Wednesday", "local/replace_all",
     "local/replace_all", "local/replace_all"),
    ("run 2", 2, "Change Samir to Samir", "local/replace",
     "local/replace", "local/replace"),
    ("run 2", 3, "Capitalize Samir", "local/capitalize",
     "local/capitalize", "local/capitalize"),
    ("run 2", 4, "Lower case release notes", "local/lower",
     "append/", "local/lower"),
    ("run 2", 5, "Delete the bit about the standup.", "local/delete",
     "local/delete", "local/delete"),
    ("run 2", 6, "Delete the last sentence", "local/delete_last",
     "local/delete_last", "local/delete_last"),
    ("run 2", 7, "Instead, try before release notes", "local/insert_before",
     "append/", "append/"),
    ("run 2", 8, "I'd do that.", "undo/", "append/", "append/"),
    ("run 2", 9, "Make it a proper prompt.", "semantic/polish",
     "semantic/polish", "semantic/polish"),
    ("run 2", 10, "Follow up and mention the rollback plan.", "followup/",
     "followup/", "followup/"),
    ("run 2", 11, "That was a command.", "rescue/", "rescue/", "rescue/"),

    ("run 3", 1, "Change a bit used into an aspect.", "local/replace_all",
     "semantic/", "semantic/"),
    ("run 3", 2, "Change Samir to Samir", "local/replace",
     "local/replace", "local/replace"),
    ("run 3", 3, "Capitalized Samir.", "local/capitalize",
     "local/capitalize", "local/capitalize"),
    ("run 3", 4, "lowercase release notes", "local/lower",
     "local/lower", "local/lower"),
    ("run 3", 5, "Delete the bit about the standard", "local/delete",
     "append/", "append/"),
    ("run 3", 6, "delete the task sentence", "local/delete_last",
     "append/", "append/"),
    ("run 3", 7, "Insert before release nodes", "local/insert_before",
     "append/", "append/"),
    ("run 3", 8, "and do that", "undo/", "undo/", "undo/"),
    ("run 3", 9, "Make it a drop a drop.", "semantic/polish",
     "semantic/", "semantic/"),
    ("run 3", 10, "Follow up and mention the rollback plant.", "followup/",
     "followup/", "followup/"),
    ("run 3", 11, "That was a command.", "rescue/", "rescue/", "rescue/"),
]

RUNS = ("run 1", "run 2", "run 3")

#: The fourth measurement of the same sheet, and the first taken three takes at a time
#: (2026-08-01, `live_check.py --takes 3`, `.bench/live/live-check.json` at `45ba125`):
#: item 9 only, because item 9 is the one this round's fix comes from. The columns are
#: ROWS' columns with the take standing where the run does — (take, what the microphone
#: produced, what the sheet wanted, what the harness recorded, what Flow routes now).
#:
#: Three takes of one sentence, three different nouns, and only take 2 was the word. The
#: two hits are here to be broken by a careless edit; the miss is what the entry fixes.
ITEM_9_TAKES = [
    (1, "Make it a proper brown.", "semantic/polish", "semantic/polish",
     "semantic/polish"),
    (2, "Make it a proper prompt", "semantic/polish", "semantic/polish",
     "semantic/polish"),
    (3, "Make it a proper font.", "semantic/polish", "semantic/", "semantic/polish"),
]


def routed(text: str) -> str:
    p = plan(text, DRAFT)
    return f"{p.kind}/{p.op}"


class TestTheSheetReplays(unittest.TestCase):
    def test_every_utterance_routes_where_the_table_says(self):
        for run, item, heard, _want, _recorded, now in ROWS:
            with self.subTest(run=run, item=item):
                self.assertEqual(routed(heard), now, heard)

    def test_the_table_covers_all_three_takes_of_all_eleven_items(self):
        self.assertEqual(len(ROWS), 33)
        for run in RUNS:
            self.assertEqual([r[1] for r in ROWS if r[0] == run], list(range(1, 12)))

    def test_the_sheet_here_is_the_sheet_the_harness_speaks(self):
        # A fixture scored against a different sheet measures nothing. `want` comes
        # from the same table `live_check.stage_d` prompts from.
        wanted = {f"{kind}/{op}" for _say, kind, op in COMMANDS}
        self.assertEqual({r[3] for r in ROWS}, wanted)


#: Every row the grammar has moved since the day it was recorded, and why. Adding one
#: is the deliberate act — the test below is what makes it deliberate.
MOVED = {
    ("run 2", 4): "'lower case' as two words, admitted as a spelling variant",
    ("run 1", 9): "'brown' snapped to 'prompt' inside the polish frame",
    ("run 1", 10): "'follow and', the elided particle, priced at 0/580 first",
}


class TestWhatThisItemMoved(unittest.TestCase):
    """Named rows, and nothing else.

    The value of the table is this test: a grammar change that moves a row nobody
    argued for is a regression, and without the recorded column it would look like
    progress.
    """

    def test_exactly_the_named_rows_differ_from_what_was_recorded(self):
        moved = {(run, item) for run, item, _h, _w, rec, now in ROWS if rec != now}
        self.assertEqual(moved, set(MOVED))

    def test_all_of_them_moved_from_a_miss_to_a_hit(self):
        for run, item, _h, want, rec, now in ROWS:
            if (run, item) in MOVED:
                self.assertNotEqual(rec, want, "was recorded as a hit already")
                self.assertEqual(now, want)

    def test_and_each_one_carries_the_reason_it_was_allowed_to_move(self):
        # A row that moved without an argument beside it is the regression this file
        # exists to catch, whichever direction it moved in.
        for key, why in MOVED.items():
            with self.subTest(row=key):
                self.assertTrue(why.strip())


class TestTheFourthMeasurementOfItemNine(unittest.TestCase):
    """The same frame spoken three times in one sitting.

    The three single-take runs above each produced item 9 once, so "brown" read as one
    speaker having one bad decode. Three takes of the same sentence on the same day
    settled that: the noun is what varies, the frame is what holds, and a fix aimed at
    the noun has to be a list because there is no bar between "font" (0.400 against
    "prompt") and "proper" (0.667) that separates a mis-hearing from a real word.
    """

    def test_every_take_routes_where_the_table_says(self):
        for take, heard, _want, _recorded, now in ITEM_9_TAKES:
            with self.subTest(take=take):
                self.assertEqual(routed(heard), now, heard)

    def test_the_two_takes_that_already_worked_still_work(self):
        # The regression half. "brown" was recorded as a hit because the first entry
        # had already shipped when this run was taken — so it is evidence about the
        # table, not about the decoder, and it is the first thing a careless edit loses.
        hits = [t for t in ITEM_9_TAKES if t[3] == t[2]]
        self.assertEqual([t[0] for t in hits], [1, 2])
        for take, heard, want, _recorded, now in hits:
            with self.subTest(take=take):
                self.assertEqual(now, want)

    def test_and_exactly_one_take_moved_from_a_miss_to_a_hit(self):
        moved = [t for t in ITEM_9_TAKES if t[3] != t[4]]
        self.assertEqual([t[0] for t in moved], [3])
        take, heard, want, recorded, now = moved[0]
        self.assertEqual((heard, recorded, now), ("Make it a proper font.",
                                                  "semantic/", "semantic/polish"))
        self.assertEqual(now, want)

    def test_the_run_scored_two_of_three_on_this_item_and_now_scores_three(self):
        self.assertEqual(sum(1 for t in ITEM_9_TAKES if t[3] == t[2]), 2)
        self.assertEqual(sum(1 for t in ITEM_9_TAKES if t[4] == t[2]), 3)


class TestTheScores(unittest.TestCase):
    def test_the_recorded_scores_are_the_ones_the_runs_reported(self):
        got = [sum(1 for r in ROWS if r[0] == run and r[4] == r[3]) for run in RUNS]
        self.assertEqual(got, [7, 8, 6])

    def test_and_each_fix_is_worth_one_item_in_the_run_it_came_from(self):
        # Run 1 gains two (the polish frame's noun snap, and the elided "follow and"),
        # run 2 one (lower case as two words), run 3 none — which is the honest shape:
        # every fix so far came from a specific miss in a specific take, and none of
        # them generalised to a take that did not produce the same mis-hearing.
        got = [sum(1 for r in ROWS if r[0] == run and r[5] == r[3]) for run in RUNS]
        self.assertEqual(got, [9, 9, 6])

    def test_no_item_held_across_all_three_takes_except_three_and_eleven(self):
        # The plan's own summary said "2, 3 and 11 hit every run". Item 2 did not:
        # run 1 heard "Change Semir to Samir" and escalated. Two of eleven held, not
        # three, which makes the point the runs were making slightly sharper.
        held = {item for item in range(1, 12)
                if all(r[4] == r[3] for r in ROWS if r[1] == item)}
        self.assertEqual(held, {3, 11})

    def test_which_items_the_fixes_have_made_stable_across_all_three(self):
        # 4 came from the lower-case variant, 10 from the elided "follow and". Both are
        # stable *because all three takes produced a form the grammar now reads* — not
        # because the underlying mis-hearing stopped happening, which no grammar change
        # can do. Items 1, 5, 6, 7, 8 are still take-dependent and 2 needs a declared
        # correction rather than a rule.
        held = {item for item in range(1, 12)
                if all(r[5] == r[3] for r in ROWS if r[1] == item)}
        self.assertEqual(held, {3, 4, 10, 11})


class TestTheBitAboutQuestion(unittest.TestCase):
    """Whether the missing article was the difference. It was not.

    Run 1 missed without it ("about standard"), run 2 hit with it ("about the
    standup"), and run 3 missed *with* it ("about the standard") — so the article was
    never what separated them. The word was: "standard" is not "standup", and the
    phonetic matcher is right to say so. Moving `MATCH_THRESHOLD` to close that gap is
    a re-measurement (it was swept against 354 false-span candidates), never a quick
    fix, so this pins the behaviour rather than changing it.
    """

    def test_the_article_changes_nothing_either_way(self):
        for text in ("Delete the bit about standard.", "Delete the bit about the standard"):
            self.assertEqual(routed(text), "append/", text)
        for text in ("Delete the bit about standup.", "Delete the bit about the standup."):
            self.assertEqual(routed(text), "local/delete", text)

    def test_the_word_is_what_the_matcher_cannot_reach(self):
        self.assertLess(similarity("standard", "standup"), MATCH_THRESHOLD)
        self.assertGreaterEqual(similarity("standup", "standup"), MATCH_THRESHOLD)


class TestWhatTheMissesActuallyWere(unittest.TestCase):
    """Each remaining miss, and which layer it belongs to.

    Written down because "the grammar missed it" was the assumption going in, and for
    most of these rows it is not true — the phonetic matcher would have reached the
    target if the decode had produced a command at all.
    """

    def test_a_dropped_word_not_a_missing_rule(self):
        # Run 3 item 7 heard "Insert before release nodes": the *thing to insert* is
        # gone, so there is no "insert X before Y" left to match. And "nodes" would
        # have been fine — it reaches "notes" comfortably.
        self.assertEqual(routed("Insert before release nodes"), "append/")
        self.assertGreater(similarity("nodes", "notes"), MATCH_THRESHOLD)
        self.assertEqual(routed("Insert draft before release nodes"),
                         "local/insert_before")

    def test_the_follow_up_verb_lost_its_particle(self):
        # Run 1 item 10: "follow and mention the roleback plan". "roleback" was never
        # the problem — it scores 0.94 against "rollback" — the missing "up" was.
        #
        # This row used to be pinned as a miss, on the grounds that admitting "follow"
        # would route "follow the steps in the README" as a follow-up. That was true of
        # *bare* "follow" and is still refused; what is admitted is the elision only —
        # "follow" immediately before "and" — and it was priced before being admitted:
        # 0/580 misroutes on the real-utterance corpus, unchanged, and the whole
        # command_bench output identical apart from its date. The corpus has no
        # "follow and" utterance in it, so nothing else moved either.
        self.assertEqual(routed("follow and mention the roleback plan"), "followup/")
        self.assertEqual(routed("follow up and mention the roleback plan"), "followup/")
        self.assertEqual(routed("follow the steps in the README"), "append/")
        self.assertGreater(similarity("roleback", "rollback"), MATCH_THRESHOLD)

    def test_a_no_op_replace_still_scores_as_a_hit(self):
        # Runs 2 and 3 both heard "Change Samir to Samir" for "change sameer to Samir".
        # It routes locally and the scorer counts it, and the name in the draft is
        # still wrong afterwards: both homophones decoded identically, so the edit
        # replaces the fuzzy match with the same text it already had. The real fix is
        # a declared correction (`semir -> Samir`, item 13), not a routing change —
        # which is why this fixture exists to say the number is flattering.
        self.assertEqual(routed("Change Samir to Samir"), "local/replace")

    def test_a_garbled_instruction_still_reaches_the_cli(self):
        # Run 3, two of thirty-three: the decode produced nonsense that is still
        # shaped like an instruction, and `semantic/` in the app is a ~7 s CLI call
        # applying it to the draft. A sanity gate is a product decision and is parked
        # in NEEDS_YOU.md; this pins what happens today so the day it changes is
        # visible.
        self.assertEqual(routed("Make it a drop a drop."), "semantic/")
        self.assertEqual(routed("Change a bit used into an aspect."), "semantic/")


class TestTheTwoFixes(unittest.TestCase):
    def test_lower_case_is_two_words_when_it_is_spoken(self):
        self.assertEqual(routed("Lower case release notes"), "local/lower")
        self.assertEqual(routed("lowercase release notes"), "local/lower")

    def test_but_only_when_the_target_is_really_in_the_draft(self):
        # The snapped reading is accepted on the same evidence every other snap needs.
        # Ordinary speech that opens with the same two words stays dictation.
        self.assertEqual(routed("Lower case letters are fine in a branch name"),
                         "append/")

    def test_a_mis_heard_prompt_inside_the_polish_frame_is_still_a_polish(self):
        self.assertEqual(routed("Make it a proper brown."), "semantic/polish")
        self.assertEqual(routed("Make it a proper prompt."), "semantic/polish")

    def test_the_frame_does_not_swallow_a_different_request(self):
        # "make it a proper X" with a word nobody has been heard to say for "prompt"
        # is a different request, and it keeps going to the CLI as free text.
        for text in ("Make it a proper sentence.", "Make it a proper email.",
                     "Make it a proper apology."):
            p = plan(text, DRAFT)
            self.assertEqual((p.kind, p.op), ("semantic", ""), text)

    def test_the_snap_is_a_list_of_what_was_heard_not_a_threshold(self):
        # "brown" scores 0.36 against "prompt" — less than half of MATCH_THRESHOLD,
        # and `sounds_like` is False, so no phonetic route reaches it either. A bar
        # low enough to admit it admits words that mean something else in the very
        # same frame: "proper" scores 0.67 against "prompt" and "drop" 0.60. Hence a
        # table of what was actually heard, which is what `_ALIASES` already is.
        self.assertLess(similarity("brown", "prompt"), MATCH_THRESHOLD / 2)
        self.assertFalse(sounds_like("brown", "prompt"))
        for closer in ("proper", "drop", "problem"):
            self.assertGreater(similarity(closer, "prompt"),
                               similarity("brown", "prompt"), closer)


class TestStabilityScoring(unittest.TestCase):
    """The number a repeated stage D reports.

    A scorer that scores wrongly is worse than no scorer, and this one exists to stop
    a single take being read as a measurement — so what it must never do is report a
    number that looks like agreement when the takes disagreed.
    """

    @staticmethod
    def _rows(*hits: tuple[int, bool]) -> list[dict]:
        return [{"item": i, "hit": h, "text": "", "got": "", "want": ""}
                for i, h in hits]

    def test_an_item_that_held_every_take_is_stable(self):
        out = stability(self._rows((1, True), (1, True), (1, True)))
        self.assertEqual(out["stable"], [1])
        self.assertEqual(out["never"], [])
        self.assertEqual(out["takes"], 3)

    def test_an_item_that_missed_every_take_is_named_too(self):
        out = stability(self._rows((2, False), (2, False)))
        self.assertEqual(out["never"], [2])
        self.assertEqual(out["stable"], [])

    def test_two_of_three_is_neither(self):
        out = stability(self._rows((3, True), (3, False), (3, True)))
        self.assertEqual((out["stable"], out["never"]), ([], []))
        self.assertEqual(out["per_item"][3], 2)
        self.assertEqual(out["attempts"][3], 3)

    def test_the_totals_are_over_every_take_not_every_item(self):
        out = stability(self._rows((1, True), (1, False), (2, True), (2, True)))
        self.assertEqual((out["hit"], out["n"]), (3, 4))

    def test_takes_is_the_most_any_item_got_not_an_average(self):
        # An interrupted run leaves items with different take counts. Reporting the
        # mean would invent a run that did not happen.
        out = stability(self._rows((1, True), (1, True), (1, True), (2, True)))
        self.assertEqual(out["takes"], 3)
        self.assertEqual(out["attempts"], {1: 3, 2: 1})

    def test_one_take_reports_itself_as_one_take(self):
        # The honest degenerate case: with a single take every hit is "stable", and
        # the number that matters is `takes`, which says not to believe it.
        out = stability(self._rows((1, True), (2, False)))
        self.assertEqual(out["takes"], 1)
        self.assertEqual((out["stable"], out["never"]), ([1], [2]))

    def test_nothing_at_all_does_not_divide_by_zero(self):
        out = stability([])
        self.assertEqual((out["n"], out["hit"], out["takes"]), (0, 0, 0))
        self.assertEqual((out["stable"], out["never"]), ([], []))

    def test_the_three_real_runs_score_the_way_they_were_reported(self):
        # The fixtures above, fed through the scorer the harness will use.
        rows = [{"item": item, "hit": rec == want, "text": heard, "got": rec,
                 "want": want} for _run, item, heard, want, rec, _now in ROWS]
        out = stability(rows)
        self.assertEqual((out["hit"], out["n"]), (21, 33))
        self.assertEqual(out["takes"], 3)
        self.assertEqual(out["stable"], [3, 11])
        self.assertEqual(out["never"], [])


if __name__ == "__main__":
    unittest.main()
