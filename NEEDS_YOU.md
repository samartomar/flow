# NEEDS_YOU — things only you can do

Updated 2026-08-01, end of the day the decisions were made and built. Every decision
that was open in the morning is closed or parked on named evidence: the standing record
with each decision's why and its reopen bar is **[docs/decisions.md](docs/decisions.md)**;
the 25 items they spec'd are done, with their evidence archived in
[docs/history/loop-rounds-1-3.md](docs/history/loop-rounds-1-3.md). This file holds only
what is live: desk work, and the two decisions parked on evidence.

## Decisions still open

(none — the record is [docs/decisions.md](docs/decisions.md); two evidence-parked
entries are further down)

## Found while building, out of the item's scope

(resolved — the `Session._provider()` pin mismatch became LOOP_PLAN item 24 and is
done, commit `a18b619`: the notes now name the CLI the call will actually make)

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
  **Item 10 has joined the predictions**: plan item 20's gate passed on 2026-08-01 —
  `follow and` is admitted, priced at 0/580 misroutes with the whole `command_bench`
  output identical bar its date, so run 1's "follow and mention the roleback plan"
  should now route as a follow-up. Bare "follow" is still dictation, deliberately.
  What will not move without you: items 5 and 7 — theirs is Phase 3
  (see [docs/decisions.md](docs/decisions.md), the pinned-misses entry).
  And with `semir -> Samir` in `~/.flow/lexicon.txt` — right-click → **Open settings
  folder** writes the file — item 2 should stop escalating. **Checked 2026-08-01:
  `~/.flow/lexicon.txt` does not exist**, so that third prediction is not testable until
  the menu entry has been used once and the arrow line typed. `profile.json` also holds
  `"pairs": {}` — no confusion pair has ever been learned from your speech, the fact the
  inferred-pairs decision ([docs/decisions.md](docs/decisions.md)) was made on.

  Per-item stability is the number that means something; a single run cannot show
  whether a change helped, which is what `--takes` is for.
- [ ] **Is a grounded answer actually less generic?** The felt half of item 23, and the
  one thing no unit test can settle. Ask the *same* question about your real repo twice,
  once with the workspace set and once without, and keep both transcripts:

  ```bash
  uv run python -m flow --converse --cwd D:\dev\products\syntegris
  ```

  Then the same again with no `--cwd`. Startup names which it got either way ("workshop:
  …" / "workshop: not set"), so there is no ambiguity about what you measured. What to
  look for: whether the grounded answer names real files, real conventions and real
  constraints from that project, or whether it is the same generic advice with a path
  mentioned in it. If it is the latter, the preamble is the thing to change, not the
  setting — the workspace reaches the CLI as text, and `codex`/`claude` decide for
  themselves whether to go and look. Worth recording either way, because the stale-path
  risk you accepted is only worth accepting if the grounding buys something.
  To make it permanent afterwards, `workspace` is a field in `profile.json` — or say the
  word and it becomes a menu entry, since you will not hand-edit it.
- [ ] **Eyeball the converse marker** — item 15 landed (`d1d2b51`), so this is live now:
  arm converse mode and look at the pill. The unit test can only prove the string is right and ≤6 characters;
  whether `codex` at 6 pt collides with the bottom of a tall level bar (bars run y 8–32,
  the marker's baseline is y 33) is a thing eyes decide.
- [ ] **Consent scope:** `docs/recording-kit.md` — one paragraph telling volunteers
  where recordings are stored (a private folder; a private repo's *history* no
  longer; keep it true).
- [ ] **The wake experiment** — run it the next time a spoken reply plays, with the
  predictions written down first so it is a measurement, not an impression. Prediction:
  while the reply plays *and for roughly its own duration again after the audio ends*,
  nothing spoken wakes Flow — shouting included, by design (the audio is discarded as
  presumed echo, and the discard is not level-based; `WORDS_PER_SEC` = 1.5 is
  deliberately half the measured rate, so estimated deafness runs ~2× the audio). The
  test is when the level bars respond to your voice again: almost immediately after the
  audio stops → the estimate is fine, nothing to fix; a dead stretch about as long as
  the reply itself → the 2× estimate is confirmed, and the fix to spec is ending
  deafness when the SAPI child actually exits. Separate case, by design not defect:
  every fresh launch starts disarmed (`arm=False`), so the first Ctrl+Alt+Space of a
  session is a choice — if *that* is the annoyance, an arm-on-launch preference is a
  cheap separate decision.
- [x] **README is behind the lexicon file** — done in the review session, commit
  `Catch the README up…`, plus a fifth stale spot the entry missed: the storage table
  still said the volunteer recordings were tracked.

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

