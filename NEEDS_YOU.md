# NEEDS_YOU — things only you can do

Updated 2026-08-02, the morning Flow went public. Every decision that was open is closed
or parked on named evidence: the standing record with each decision's why and its reopen
bar is **[docs/decisions.md](docs/decisions.md)**; the 28 items they spec'd are done,
with rounds one to three archived in
[docs/history/loop-rounds-1-3.md](docs/history/loop-rounds-1-3.md). This file holds only
what is live: desk work, and the two decisions parked on evidence.

## Decisions still open

(none — the record is [docs/decisions.md](docs/decisions.md); two evidence-parked
entries are further down)

## Found while building, out of the item's scope

(resolved — the `Session._provider()` pin mismatch became LOOP_PLAN item 24 and is
done, commit `a18b619`: the notes now name the CLI the call will actually make)

## Going public — done 2026-08-02, except two steps that are not on this machine

**Flow is public: https://github.com/samartomar/flow · release
[v0.1.0](https://github.com/samartomar/flow/releases/tag/v0.1.0) with
`flow-windows-x64.zip` (126 MB) attached.** MIT in the sidebar, README rendering with
the `uv tool install` two-liner as its first code block, and
`uv tool install git+https://github.com/samartomar/flow` verified from the public URL in
a throwaway tool directory (`flow --help` exit 0, `uv tool list` → `flow v0.1.0`, then
uninstalled).

- [x] **License word** — MIT, © Samar Tomar 2026 (`LICENSE`, and the metadata says the
  same thing so a wheel cannot disagree with the file beside it).
- [x] **Phase A** — LOOP_PLAN items 26, 27, 28, each instrumented, gated on the full
  suite and committed separately.
- [x] **The flip** — but **not** by `gh repo edit` alone, and this is the part worth
  reading. The sweep found the volunteer recordings still live on GitHub: a force-push
  moves a ref, it does not remove objects, and the pre-rewrite tip `50d16f5` was still
  served by the API with `.bench/recorded/inbox/` intact — five clips, two named after a
  volunteer, plus the manifest that names people. Private that cost nothing; public it
  would have handed a stranger a volunteer's voice by SHA. So the repo was **deleted and
  recreated** (your call, over a Support purge, for being certain rather than promised),
  the clean history pushed, and the old SHA now returns 422. Same name, same URL, one
  repo. `docs/decisions.md`'s "Distribution, final" entry carries the correction.
- [x] **Consent paragraph** — written in `docs/recording-kit.md`. **Your job is still to
  read it and agree it is true**, since it speaks for you to people who trusted you.
- [ ] **List Flow in ai-harness** with the uv one-liner and the Releases link — the
  other machine, so it is still yours:
  `uv tool install git+https://github.com/samartomar/flow`, then
  `https://github.com/samartomar/flow/releases`.
- [ ] **Run the zip on a machine with no Python** — the one thing no harness here can
  prove. CI ran `flow.exe --help` against the bundle it built before zipping it, and the
  same bundle launched here and printed all 17 startup lines, but both machines have
  Python installed. Download `flow-windows-x64.zip`, unzip, run `flow.exe`, and expect
  one-time SmartScreen: **More info → Run anyway**.

Two things the sweep turned up that you have not ruled on, kept here rather than lost:

- [ ] **`docs/record.html:277` still carries the old one-line consent claim** ("stays on
  one laptop, is never uploaded, and is deleted whenever you ask") while
  `recording-kit.md` now carries the full paragraph. Both are true; the guided page is
  the one volunteers are actually walked through, so it is the one that matters more.
  Say the word and it gets the same paragraph.
- [ ] **`.bench/accent/manifest-aesrc.jsonl` is 240 rows of reference transcripts and
  speaker IDs** from a re-upload that, in `fetch_accent_data.py`'s own words, declares no
  licence — and `.gitignore` excludes the audio on exactly that reasoning ("not a claim
  that survives being committed anywhere") while the manifest carrying the text is
  committed. The 580 EdAcc rows are from a published corpus with its own terms and are a
  different question. Nobody has been harmed by this; it is simply inconsistent with the
  argument already written down.

## At the desk

- [ ] **Record more L1 anchor groups** per `docs/recording-kit.md` — two groups exist,
  the smoke benchmark wants 3–5 speakers per anchor group. New clips go to
  `D:\dev\flow-recordings\recorded\inbox\`, then copy into `.bench/recorded/` and run
  `scripts/ingest_recordings.py` (git ignores them now).
- [x] **The `--takes 3` measurement — done 2026-08-01, the best sheet ever recorded:
  29/33 (was 21/33 across the three single takes), takes of 11/11, 9/11, 9/11, seven
  items stable, nothing at zero.** Committed with its identity block (item 18 working
  live). Scored against the four predictions:
  - **Item 4 — confirmed, causally.** 3/3, including take 3 decoding "release nodes"
    and still routing `local/lower`. The spelling-variant fix is real.
  - **Item 9 — confirmed for "brown", and the family is open.** Take 1's "Make it a
    proper brown." — the exact decode that missed in run 1 — now reaches
    `semantic/polish`. But take 3 produced a *new* noun: "Make it a proper **font**."
    → `semantic/` unpolished. The lookup table admits only what is in it; "font" is
    plan item 26, same bounds as "brown".
  - **Item 10 — 3/3, but not attributable to item 20.** All three takes decoded
    "follow **up** and…" with the particle intact, so the admitted `follow and` path
    was never exercised live. The fix stays proven by its fixtures and its 0/580 gate,
    not by this run.
  - **Item 2 — still untestable, and still the weakest item.** 2/3, both hits the
    homophone no-op ("Change Samir to Samir"), the miss a full-sentence mis-decode
    ("It's time to send me" → silent append). **`lexicon.txt` now exists but the
    `semir -> Samir` line has still not been typed** — 30 seconds, right-click →
    Open settings folder, and the next run makes this prediction testable.
  - **Unpredicted:** item 7 went 3/3 *without* its Phase 3 fix — "draft" survived
    decoding all three takes (and "nodes"→"notes" snapped at 0.900, in range all
    along). Item 5 reproduced its pinned miss exactly once ("standard" vs "standup",
    0.667 — the Phase 3 fixture behaving as documented). And item 3 *fell out* of the
    stable set ("Samir" → "some you"): membership of the stable set changed for the
    fourth time in four measurements, which is the whole argument for `--takes`.
  P3's bar is ≥95%; this run is 88%. The gap is now concentrated in decode variance on
  content words — Phase 3 territory — not in the grammar.
- [ ] **Is a grounded answer actually less generic?** The felt half of item 23, and the
  one thing no unit test can settle. Ask the *same* question about your real repo twice,
  once with the workspace set and once without, and keep both transcripts:

  ```bash
  uv run python -m flow --converse --cwd D:\dev\products\acme
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

## Parked — the evidence is now arriving, and is not yet enough (updated 2026-08-01 evening)

**`diag.jsonl` exists — 419 records from ~5 launches on 2026-08-01**: 229 decodes,
26 asks (the workshop got real use), 24 append routes, **2 refines**, and one stale
discard already recorded. The collection both entries wait on has started. Where it
stands against the bars: **2 of ≥30 refines** for the stale-rewrite entry; state
transitions are accumulating toward P2's ~200 pauses but are nowhere near it. Also
noted from the profile: a voice is chosen ("Microsoft George"), `auto_ask` is stored
ON, and `pairs` is still `{}` — no spoken "change X to Y" correction has occurred in
real use yet, so item 19's menu has had nothing to offer.

**What fills both:** keep using Flow plainly. The refine counter is the slow one —
rewrites happen a few per session, so ≥30 is likely two or three more real working
sessions away.

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

