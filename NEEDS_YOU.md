# NEEDS_YOU — things only you can do

Updated 2026-08-01, end of the decision session. **Every decision that was open this
morning is closed or parked on named evidence** — eleven entries in Decided below, two
parked with numeric bars, and LOOP_PLAN carries round three (items 15–23, specs
complete) ready for a fresh loop run. Done and gone from this file: the force-push and
the follow-up push (origin/main now carries the rewritten history, both measurement
commits, and this session's decisions), live_check's first run, P1 artifact profiles
(`50c2068`), the late-warning drain (`6008cfd`), the README catch-up, and the full
text of decided entries — their reasoning lives in Decided and in the LOOP_PLAN specs.

## Decisions still open

(none — see Decided below, and the two evidence-parked entries further down)

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
  If plan item 20's measurement admits `follow and`, **item 10** joins the predictions.
  What will not move without you: items 5 and 7 — theirs is Phase 3 (see Decided).
  And with `semir -> Samir` in `~/.flow/lexicon.txt` — right-click → **Open settings
  folder** writes the file — item 2 should stop escalating. **Checked 2026-08-01:
  `~/.flow/lexicon.txt` does not exist**, so that third prediction is not testable until
  the menu entry has been used once and the arrow line typed. `profile.json` also holds
  `"pairs": {}` — no confusion pair has ever been learned from your speech, the fact the
  inferred-pairs decision (Decided below) was made on.

  Per-item stability is the number that means something; a single run cannot show
  whether a change helped, which is what `--takes` is for.
- [ ] **Eyeball the converse marker** once LOOP_PLAN item 15 lands: arm converse mode and
  look at the pill. The unit test can only prove the string is right and ≤6 characters;
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

### 2026-08-01 — Garbled CLI escalations: no gate. The draft becomes editable instead

**The gate as this file specified it is not built.** "Refuse escalation when the
instruction's content words appear in neither the draft nor the command vocabulary"
describes almost every legitimate free-form rewrite — "make it more formal", "add a
bulleted summary", "turn this into a bug report" — because an instruction about words not
yet in the draft is what *makes* it semantic rather than local. It would sit on
`session.py:1091`, the free-form branch (polish is dispatched at 1082 and never reaches
it), so it refuses that whole class or it refuses nothing. It is also not decisive on its
own two examples: item 14 already measured "drop" at **0.60** against "prompt", between
"problem" (0.62) and "proper" (0.67), and concluded that no bar admits the mis-hearings
without admitting the real words.

**Two numbers in the old entry were wrong about the owner, not about the code.** The 6%
rate (2 of 33) comes from a sheet where 1 of 11 items is semantic; the owner reports
semantic rewriting is the *main* reason they use Flow, so that rate is measured on the
wrong population and does not describe their exposure. And the recovery loop the gate
assumed — "a refusal just means say it again" — is the loop that does not close: with a
heavy L2 accent the retry hits the same decoder, which is why the owner ends up
correcting after Send instead.

**What replaces it: click-to-edit.** With an editable draft, a garbled instruction is a
two-word keyboard fix instead of an unwinnable retry, and a mangled draft is repairable
without noticing in time to reach undo. It touches none of the routing the owner depends
on. Spec'd as LOOP_PLAN item 17.

**Kept from the gate work, as instrument only:** LOOP_PLAN item 16 wires
`asr.take_confidence()` — the worst `avg_logprob` of the kept segments, already
calibrated per speaker (P8; this profile reads −0.193) — through to the router and into
the trace. Today it is computed on every decode and read only by `calibrate.py` and
`scripts/guardrail_bench.py`; the router never sees it. **No behaviour changes.** It
exists so this decision can be re-opened on the owner's real distribution instead of on a
33-utterance sheet, and because confidence-per-route is the field that would make a gate
designable at all.

**Recorded because it belongs in the record:** the owner's account of these failures was
"I have to train myself more, I have a heavy accent." `docs/product.md` makes the heavy
accent the design centre — P1 sets per-accent WER ≤ 12% as a floor and P3 sets ≥ 95%
command recognition. The three live runs scored **55%, 73%, 55%**. The speaker adapting
to Flow is Flow missing its own written requirement, and no decision here is built on the
speaker changing.

### 2026-08-01 — Auto-ask default: stays ON, with a numbered reopen

Kept ON because the case against it is thin by the owner's own account ("very
occasionally" fires mid-thought, said with low confidence and little converse use), and
because the owner's actual complaint runs the other way — the friction named at the desk
was a *missing* hands-free step (the spoken send trigger, now an open entry), not an
excess one. The control Feedback's manual-by-default wanted has shipped since it was
written: countdown on the Ask chip, held by speech, cancellable, OFF persisted
(`2787b2a`). **Reopens if**, once `~/.flow/diag.jsonl` exists, more than **~1 in 10**
auto-fires is cancelled or immediately corrected — derivable from state transitions and
timestamps already in the trace, no new instrument. P2 (adaptive timeout) stays parked
and is the proper fix for the 4 s constant, whose pause measurement came from
sheet-reading, not composition. No code follows; the default is already ON and Rule 4
already freezes it.

### 2026-08-01 — Selfdrive flake: rerun-once codified, with a same-check tripwire

One sighting of 63/64 (`capitalize sameer`, item 2's run, 64/64 on rerun, four green runs
since) becomes written policy in Rule 2: one automatic rerun, both scores and the failing
check's name in the Evidence line, a failed rerun blocks per Rule 8, and the *same* check
flaking in two different runs — even rerun-green — becomes a NEEDS_YOU quarantine-or-fix
entry rather than more noise. The mechanism supports it: the owner's room carries only
constant fan noise, which is stationary and already inside the calibrated floor, so the
flip lives in the decoder — `capitalize sameer` is marginal by design and `asr.py`'s
temperature fallback samples when `avg_logprob` crosses −1.0. **Declined alongside:** a
manual quiet-room/fan-noise selector the owner offered — it would be a guessed duplicate
of the measurement `--calibrate` already takes, aimed at the gate when the variance is in
the decode, and §9's no-settings-dialog stance exists to keep exactly this knob out.
Kept from the offer: if the tripwire fires, first check whether the flaking runs followed
sustained CPU load — the fan ramps under a hot suite, and calibration measured the idle
room. Accepted cost: a real intermittent regression in one live-ASR check gets one free
pass per run, bounded by the rerun and the tripwire.

### 2026-08-01 — Model revision pinning: declined again; benchmark provenance replaces it

Benchmarks run on this machine only, so the HF cache is already a pin — nothing
re-downloads unless it is cleared, and the upstream conversions have been frozen for
years, so a pin table plus an offline-mismatch policy would be bought against a
roughly-never event. Item 10's decline stands for the same reason it gave: `--model`
accepts any name, and a table covering only the defaults misses exactly the runs that
motivate it. **What was wrong in the old entry:** "runs drift and say so" is only true
of the app — identity recording went to the diag trace, and **no bench script records a
revision at all** (checked 2026-08-01: zero mentions across `scripts/`), while §9 tracks
`.bench/` results precisely because a measurement cannot be re-taken. So the tracked
measurements carry no provenance, and the reopen condition for pinning is not currently
checkable. LOOP_PLAN item 18 closes that: every bench output gains an identity block.
**Reopens if** a recorded hash ever changes between runs on this machine, or benchmarks
start running on a second machine.

### 2026-08-01 — Inferred pairs: never silent — offered for one-tap declaration instead

Silent promotion stays out for the reason the open entry gave: an inferred pair is a
guess from a word-level diff, `profile.json` still reads `"pairs": {}` so inference
quality on this voice is unmeasured, and auto-applying it would rewrite words nobody
asked to change. What changed is the other half: the owner states the hand-edited
`lexicon.txt` path will not be used without UI ("unless it is exposed to UI right click
or dedicated settings page i will not be able to use it") — a forecast rather than
experience, since item 13 shipped the same morning, but a forecast from the product's
only user, and it contradicts §9's recorded claim that "the whole gap was that nobody
could find it." So: a pair seen `PROMOTE_AFTER` = 2 times surfaces in the right-click
menu as a one-tap offer that writes the arrow line into `lexicon.txt` on the owner's
behalf. A tap on a shown pair is a declaration — the declared/inferred boundary
survives; only the typing does not. A dedicated settings page stays refused (§9's
reasoning stands; the owner named right-click as an acceptable form). Costs accepted:
Flow gains its first write *into* the user's file (bounded: append one line, on an
explicit tap, never edit or remove), wrong offers are possible until inference quality
is measured (a per-pair "never" is part of the spec), and the modal menu grows.
Spec'd as LOOP_PLAN item 19.

### 2026-08-01 — The three pinned misses: one conditional admission, two named for Phase 3

**"follow and mention the roleback plan":** the elision pattern `follow (up)? and` — never
bare "follow" — is admitted to `_FOLLOWUP` *only if* command_bench measures it at zero
cost: real-utterance misroutes stay 0/580, adversarial stays ≤5/20, recall stays 100%.
Pre-authorized by the owner (follow-ups confirmed as real usage: "yes i use that word"),
so the loop measures and either admits or reports the hits back here — no grammar change
on a failed measurement. Spec'd as LOOP_PLAN item 20.
**"delete the bit about the standard":** `MATCH_THRESHOLD` stays 0.82, permanently. The
sweep already priced the alternative — 0.75 buys this one recovery by taking corpus false
spans from 4 to 19 — and a 5× false-span multiplier is the product deciding to guess.
**"Insert before release nodes":** no grammar recovers a word the decoder never produced.
Both remaining fixtures are explicitly *not* grammar work: they are the acceptance tests
for the Phase 3 constrained re-decode, whenever that is proposed — written here so the
proposal inherits its success criteria instead of inventing them.

### 2026-08-01 — A reply can become the draft: chip + spoken command, replace, flips to dictate

Found in the owner's first ordinary session and decided the same day: `send()` hands
over the draft, a refined prompt lives in the reply, and no verb connected them —
while `docs/product.md` P9 promises one in its own scenario ("turn that last answer
into a code comment"). The owner chose **both** forms: a chip on the rendered reply and
a spoken command, whole-utterance only, admitted through the same zero-false-hit
corpus gate as item 20. Sub-choices closed by recommendation: **replace, never append**
(the draft is empty in the main loop — `send()` cleared it to ask — and undo plus a
note cover the rest; append waits for real demand); **take flips to dictate** (staying
in converse makes the next Send re-ask the answer — the exact which-button-sends-where
confusion the owner reported, rebuilt); and two guards carried from earlier decisions —
**take does not arm the auto-ask countdown** (a taken draft is not a settled utterance;
without this, converse auto-asks your own answer back 4 s after you take it) and
**take stops an in-progress read-aloud**. Spec'd as LOOP_PLAN item 21.

### 2026-08-01 — The spoken send trigger: two configurable words, whole-utterance, refusals inherited

All three cold questions answered. Two trigger words, both the owner's to choose and
both stored as additive `profile.json` fields with shipped defaults — **chosen
2026-08-01: "boom" for Send, "enter boom" for Send-then-Enter.** One presses Send, the
other presses Send-then-Enter so a terminal prompt actually submits. The owner's word
order degrades safely: whole-utterance matching means a decode that loses a word from
"enter boom" yields "enter" (nothing) or "boom" (paste without submit) — both fall away
from execution, never toward it. Whole-utterance-only
confirmed by the owner as natural ("gate opens, word, gate closes") — embedded
mid-sentence stays dictation, which is what makes false fires structurally rare. The
empty-draft case decided itself: `send()` already refuses with "nothing to send", and
the trigger inherits every refusal Send has — including invariant 10's target
revalidation, which the Enter keystroke rides behind. The physics boundary recorded
earlier stands: no spoken word interrupts a playing reply, ever (invariant 6, no AEC).
Honest wrinkle, recorded not hidden: the owner has said they will not hand-edit files,
and the trigger words live in `profile.json` — defaults must therefore work out of the
box, and re-wording them is the one step that still needs an editor. Spec'd as
LOOP_PLAN item 22.

### 2026-08-01 — P9 decided from use: converse is a prompt workshop, grounded in a workspace setting

The scoping session this waited for happened at the desk instead: the owner tried
general conversation and it failed on its own merits — the CLI answered that it has no
internet access, and hallucinated. So P9's "ChatGPT Voice mode against the CLI" is the
stale half, and converse mode becomes what the owner named: **dedicated prompt
refinement, nothing more** — discuss and refine the prompt in conversation, take the
result (item 21), send it (item 22). Grounding: an **explicit workspace setting** (e.g.
`D:\dev\products\syntegris`) — the owner chose the explicit-path option over launch-dir
and over reading the target window's directory. Its cost, argued once and accepted: a
workspace set once goes stale silently when the project changes; the mitigation is
visibility, not magic — the converse-mode note and the startup line name the workspace
every time, so a wrong grounding is on screen. The owner's own words for why grounding
matters: "so prompt are grounded as well … and we also know what we are sending
properly." Spec'd as LOOP_PLAN item 23, which includes the P9 rewrite in
`docs/product.md` — the build follows the definition, and the definition follows the
evidence.
