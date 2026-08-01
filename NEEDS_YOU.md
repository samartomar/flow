# NEEDS_YOU — things only you can do

Updated 2026-08-01 after your review session. Done and gone from this file: live_check
(first run — capture/gate/latency/target pass, commands 7/11, follow-ups are plan
items 13–14), P1 artifact profiles (commit `50c2068`), the late-warning drain
(commit `6008cfd`), and P4's rewrite (executed — see the one command below).

## One command, now

~~The force-push~~ — **done, verified: origin/main carries the rewritten history and
the voices are off the remote.** Two measurement commits (live runs 2 and 3) are
ahead; a normal push carries them whenever you like:

```bash
git push
```

## Decisions still open

- [ ] **Auto-ask default.** Stays ON (your choice persists in the profile now). Feedback
  recommended manual-by-default; flipping it is product feel, and diag.jsonl will soon
  show how often the countdown fires prematurely for you.
- [ ] **Converse mode has no working context — and `docs/product.md` specified it that
  way.** (2026-08-01, surfaced while deciding the provider badge.) Named at the desk:
  you switch to converse to discuss the thing you are building, and the answers come back
  generic, because the CLI is never told what you are building. Checked — the seam is
  built and unwired: `refine_cwd` threads `Session.__init__` → `session.py:1434`
  `ask(question, cwd=self._refine_cwd, …)` → `refine._invoke(cwd=cwd)`, and
  `flow/__main__.py` never sets it. It is `None`, so both CLIs inherit whatever directory
  Flow was launched from. Not to be confused with `CONTEXT_CHARS` (1500): that is Flow's
  *own* conversation thread, which works — it disambiguates a follow-up and knows nothing
  about your repo.
  This is not a loop bug, it is a definition gap: product.md's converse scenario asks
  *"what's the cleanest way to debounce a resize handler in React?"* — a context-free
  question — so P9 was written for exactly the generic conversation that turns out not to
  be the one you want. Yours to decide is **which directory**, and they differ by an order
  of magnitude in cost:
  - Flow's launch directory — one line in `__main__.py`, and wrong every time you start
    from a shortcut;
  - a `--cwd` flag plus a menu entry — explicit and correct, one more thing to set, and
    it goes stale the moment you change projects without telling it;
  - the directory behind the window Send is aimed at — `inject.resolve()` already names
    the process (`WindowsTerminal.exe` in all three live runs), but a terminal's *current*
    directory is not readable from a window handle without per-shell tricks.
  The product question underneath the plumbing: is converse mode a general assistant, or a
  pair for the work in front of you? P9 says the first and you want the second.
  **Deferred by the owner, 2026-08-01, to be picked up cold.** Not blocked on evidence —
  blocked on wanting a scoping session rather than one exchange, because the honest answer
  probably changes P9 in `docs/product.md` before it changes a line in `__main__.py`.
- [ ] **Model revision pinning.** The trace records revisions; pinning properly needs a
  table covering every model the benchmarks name, plus a policy for a cache holding a
  different revision. Until then runs drift and say so.
- [ ] **Selfdrive flake watch.** One sighting of 63/64 on a live-ASR check
  (`capitalize sameer`), four green runs since. If it recurs, the Rules' 64/64 gate
  needs a policy (rerun-once vs quarantine that check).
- [ ] **A sanity gate before garbled CLI escalations?** Live run 3 measured it: 2 of 33
  spoken commands decoded to nonsense ("Make it a drop a drop.") and routed `semantic`
  — in the app that is a ~7 s CLI call applying a garbled instruction to your draft,
  the failure mode the original feedback ranked highest-impact. Undo covers it, but a
  gate — refuse escalation when the instruction's content words appear in neither the
  draft nor the command vocabulary — would trade a rare wrong rewrite for a rare
  refused command. Which rarity you would rather live with is product feel. **The
  fixtures landed** (plan item 14, commit `3152bde`): both utterances are pinned in
  `tests/test_live_replay.py` as routing `semantic/` today, so whichever way you decide,
  the test says which rows move.

- [ ] **Three live-sheet misses are pinned as fixtures, not fixed** (2026-08-01, plan
  item 14). Each needs something the loop is not allowed to decide alone:
  - **"delete the bit about the standard"** (runs 1 and 3). Not the missing article —
    run 3 said it *with* the article and still missed, and there is a test proving the
    article changes nothing either way. "standard" scores **0.667** against the draft's
    "standup", under `MATCH_THRESHOLD` 0.82. Lowering it is a re-measurement, not a
    tweak: 0.82 was swept against 354 false-span candidates, and 0.75 takes corpus
    false spans from 4 to 19.
  - **"follow and mention the roleback plan"** (run 1). "roleback" was never the
    problem — 0.938 against "rollback". The missing "up" was. Admitting bare "follow"
    into `_FOLLOWUP` would route "follow the steps in the README" as a follow-up, which
    is a precision trade you should make, not me.
  - **"Insert before release nodes"** (run 3) lost the word being inserted, so there is
    no "insert X before Y" left to match at all; "nodes" would have reached "notes" at
    0.900. No grammar recovers a word the decoder never produced — this is decode-time
    command bias, i.e. the constrained re-decode already sketched as Phase 3.

- [ ] **Should Flow apply what it *inferred*, not just what you declared?**
  (2026-08-01, raised by plan item 13.) Every "change X to Y" you speak is already
  counted in `profile.json`, and after two sightings the right-hand side becomes a
  hotword — selfdrive watches `sameer -> Samir` do exactly that. Item 13 makes a pair
  *you typed* a substitution on the decoder's output, on the grounds that declaring a
  confusion is stronger evidence than hinting at one. The open question is whether an
  inferred pair should ever be promoted the same way, and after how many sightings. It
  is not symmetric: a declared pair is a sentence you wrote, an inferred one is a guess
  from a word-level diff, and promoting it would silently rewrite words you never asked
  to have rewritten. Deliberately not implemented.

## At the desk

- [ ] **Record more L1 anchor groups** per `docs/recording-kit.md` — two groups exist,
  the smoke benchmark wants 3–5 speakers per anchor group. New clips go to
  `D:\dev\flow-recordings\recorded\inbox\`, then copy into `.bench/recorded/` and run
  `scripts/ingest_recordings.py` (git ignores them now).
- [ ] **Next desk session — the one measurement this round could not take:**

  ```bash
  uv run python scripts/live_check.py --stage D --takes 3
  ```

  Items 13 and 14 have both landed, so there are two named predictions to check and a
  correction to record. Three single takes measured 7/11, 8/11 and 6/11, no two miss
  sets alike, and — correcting what this file said before, which the item-14 fixtures
  caught — **only items 3 and 11 held across all three**, not 2, 3 and 11: run 1 heard
  "Change Semir to Samir" on item 2 and escalated to the CLI.

  What should move, if the fixes are real: **item 4** ("lowercase release notes")
  should now hold whichever way Whisper spells it, and **item 9** ("make it a proper
  prompt") should reach `semantic/polish` even when the noun comes back as "brown".
  What will not move without you: items 5, 7 and 10 (see the fixture entry above).
  And with `semir -> Samir` in `~/.flow/lexicon.txt` — right-click → **Open settings
  folder** writes the file — item 2 should stop escalating. **Checked 2026-08-01:
  `~/.flow/lexicon.txt` does not exist**, so that third prediction is not testable until
  the menu entry has been used once and the arrow line typed. `profile.json` also holds
  `"pairs": {}` — no confusion pair has ever been learned from your speech, which is the
  standing evidence base the "inferred vs declared" decision below argues over.

  Per-item stability is the number that means something; a single run cannot show
  whether a change helped, which is what `--takes` is for.
- [ ] **Eyeball the converse marker** once LOOP_PLAN item 15 lands: arm converse mode and
  look at the pill. The unit test can only prove the string is right and ≤6 characters;
  whether `codex` at 6 pt collides with the bottom of a tall level bar (bars run y 8–32,
  the marker's baseline is y 33) is a thing eyes decide.
- [ ] **Consent scope:** `docs/recording-kit.md` — one paragraph telling volunteers
  where recordings are stored (a private folder; a private repo's *history* no
  longer; keep it true).

- [x] **README is behind the lexicon file** — done in the review session, commit
  `Catch the README up…`, plus a fifth stale spot the entry missed: the storage table
  still said the volunteer recordings were tracked. (Original entry below for the
  record.)
  (2026-08-01, mechanical, ~10 minutes).
  Plan item 13 (commit `ea8d2bb`) gave `~/.flow/lexicon.txt` a second kind of line and
  Flow a reason to write it. `docs/architecture.md` was synced in that commit; the
  Rules scope a commit to the item's named files, so `README.md` was not. Four places
  now describe less than the file does:
  - line 111 — the sample startup output still says "create … to bias names and
    jargon"; the app now prints "right-click > Open settings folder, or create …, to
    add names and corrections".
  - line 521 — "one term per line, `#` for comments" needs the arrow form beside it:
    `wrong -> right`, whole words, left side case-insensitive, right side verbatim,
    and that it biases nothing.
  - line 562 — the writes table says "you, by hand … does not exist until you create
    it — creating it *is* the opt-in". Flow now writes it once, from the menu, if it
    is missing; the template is comments only, so creating it is still not the opt-in
    (typing a line that is not a comment is).
  - line 610 — the module map's one-liner for `lexicon.py`.
  Nothing here is a decision — it is out of the loop's commit scope, not out of its
  competence, so hand it straight back if you would rather not do it by hand.

## Parked — the evidence these wait on does not exist yet (2026-08-01)

`~/.flow/` holds one file: `profile.json`, 158 bytes, calibrated today.
**There is no `diag.jsonl`, and no `diag.jsonl.1`.** The writer landed in commit
`069f869` and `flow/__main__.py` creates it on every launch that is not `--no-profile`,
so its absence means the app has not been run through `__main__` since item 9 shipped —
the three live_check runs are a script and write nothing here. Both entries below were
written as "waiting for volume". They are waiting for the **first record**.

**What unblocks both, once:** use Flow for ordinary work — `uv run python -m flow`,
without `--no-profile` — for three sessions. The trace is content-free and bounded at
two files; the cost of collecting is a startup line naming the path.

- [ ] **What a stale rewrite should cost.** Today it loses to newer words, visibly. The
  third option — re-run the instruction against the moved draft, once, for ~7 s more —
  needs the rate at which you speak inside a rewrite window. **Enough is ≥30 completed
  refine operations across ≥3 sessions.** A measured rewrite runs 5.7–7.3 s (§8
  `TIMEOUT_SEC`), so the window is real but narrow; under 30 rewrites a single incident
  reads as 3% or 10% depending on nothing, and either number would pick a different
  design. The trace already carries operation ids, durations and state transitions —
  no new instrument, just sessions.
- [ ] **P2 — adaptive auto-ask timeout.** Collect first: within-utterance pause
  distribution is already derivable from `~/.flow/diag.jsonl` state transitions; ~200
  pauses over ≥3 sessions before offering adaptive; then p95 + 0.5 s clamped [3.0, 8.0]
  as a profile field. The bar was always right; the file is empty of records because it
  is absent.

## Proposals still waiting (unchanged)

- [ ] **P3 — streaming replies.** Both CLIs stream JSONL today; ask-only, sentence
  buffer in `_pump_ask`, late chunks gated by the operation ids that now exist. The
  felt gain is on-screen only (SAPI cannot append to an utterance), which is why this
  waits.

## Decided

### 2026-08-01 — Suite split: declined

All 616 tests stay in the commit gate, `test_lifecycle.py` included. The 15.0 s is an
annoyance that has never once reduced compliance, so a split would buy no change in
behaviour at the gate, while removing the repo's only real process-lifecycle coverage —
the module that exists because a 0.4 s timeout was measured returning at 1.37 s with the
CLI's grandchild still alive — would trade the most valuable 5.5 s in the suite for the
most expensive. The iteration cost that prompted this is answered by running the one
module instead: `uv run python -m unittest discover -s tests -p "test_edits.py"` measured
**0.46 s for 62 tests** against the full suite's 15.0 s, a 32× win where a `tests/slow/`
split offered 1.6×. Rule 2 is unchanged, so nothing goes to the loop.
**Revisit when** the full gate crosses ~60 s, or when a gate run is skipped for time —
and then split by *speed*, not by module, with `test_lifecycle` staying in the gate.

### 2026-08-01 — Provider badge: the pill's existing marker names the CLI, and nothing else moves

No `Converse · codex · networked` badge. The pill is 152×40 with 4 px spare once the mic
glyph and 18 level bars are drawn, so that string costs level-meter bars (R13) — but the
6 pt marker at `ui.py:637` is *already drawn* in converse mode and its presence is what
signals the mode, so its text is free to carry the provider at zero new pixels: `ASK`
becomes `codex`. Chosen over the alternative (`Ask 4s` → `Ask codex 4s` on the countdown
chip) because that chip is on screen for `AUTO_ASK_SEC` = 4 s, and auto-ask is the one
path where words leave with no press — a marker you must be looking at during those four
seconds is the wrong instrument for the case that matters most.
Recorded honestly: the owner said transparency was wanted but that no moment of real
confusion had ever occurred, so this buys a value rather than repairs a failure — which
is why it is bounded at a string change and not a redesign. Spec'd as LOOP_PLAN item 15.
