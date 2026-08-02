# Decisions — the standing record, with each decision's why and its reopen bar

Moved here 2026-08-01 from NEEDS_YOU.md when the decision session closed. Each entry
records what was decided, the measurement it stood on, and — where one exists — the
numbered condition that reopens it. The items these decisions spec'd are archived with
their evidence in [history/loop-rounds-1-3.md](history/loop-rounds-1-3.md). New
decisions append here when NEEDS_YOU.md closes them.

### 2026-08-02 — Flow Lite: a cross-platform clipboard-out mode; the native port waits on its evidence

Flow's value — accented dictation, the correction loop, the workshop — is welded to
Windows only by the hands: 96 Win32 call sites in `inject`/`hotkey`/`ui`, while the
brain and ear are portable Python with cross-platform wheels. **Lite** ships the
portable part everywhere: dictate, correct by voice, refine in the workshop, then the
draft is *copied* — Tk's own clipboard, OS-agnostic — and the user pastes. No
injection, no global hotkeys, no synthesized keystrokes, and therefore no OS
permission beyond the microphone; arming is a click on the pill instead of a global
combo. Demand starts with the design-center user, whose own environments include
macOS. What Lite deliberately is not: there is no "boom", no "enter boom", no
auto-paste, no target-window awareness — the hands-free magic is the price, and
paying it knowingly is the point, because **the clipboard hop is the measurement**:
sustained Lite use is what decides whether a native macOS body (weeks, plus re-taking
every §7/§8 measurement per OS) is ever funded. The CLI adapter generalizes beyond
`codex`/`claude` to the agent CLIs users actually have (candidates: `kiro`,
`copilot`, `gemini`, `opencode`) — detection ships everywhere, but invocation shapes
are verified on a machine that has the CLI, never asserted; an unverified entry stays
inert with a note. Development and the full test suite run on Windows — clipboard-out
is OS-agnostic, and item 27's platform guard relaxes to "non-Windows runs Lite, and
says so" instead of refusing outright. product.md gains an Environments paragraph and
a one-page Lite definition whose fence is explicit: features land in full Flow first,
and reach Lite only if they survive without hands.

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

### 2026-08-01 — First public feedback: Help in the menu, and trigger words become a
### measured preset choice — still no settings dialog

Same evening as the release, two asks: a Help surface (commands, shortcuts, the guide)
and a way for users to change the trigger words ("goose" / "enter goose") without an
editor. Help is a gap, plainly — nothing in-app names a single command or the hotkey
that arms the mic — and ships as a menu section: "Commands & shortcuts" opens a
*generated* text file (regenerated on every open, so it shows the hotkey combos that
actually registered on this machine and the trigger words currently configured, not
the defaults), and "Open the guide" opens the public README. The trigger setting had
three shapes and the chosen one keeps two standing decisions intact: **a preset
submenu** — a curated list of trigger words, each admitted only after the same 0/580
corpus gate "boom" passed, one tap to select, the enter-variant derived automatically
in the safe order. Rejected: a free-text micro-dialog (breaches the no-settings-dialog
stance that has now survived four challenges, and free text cannot be pre-measured
safe) and speak-to-set (writing config through an accented decoder is the failure
class the product exists to fight). Fully custom words remain hand-editable in
`profile.json`; Help displays whatever is current. The menu is reorganized under
submenus (Settings ▸, Help ▸) with the one-tap essentials — mode toggle, pair offers,
"Was a command" — staying top-level, inside the same modal-stall budget item 19
bounded. Items 30 and 31 are spec'd into LOOP_PLAN and executed by the next session,
from this entry as the authority.

### 2026-08-01 — Distribution, final: public in place, one repo — the split is superseded

Third position in one evening, and the one that closed it deliberately rather than by
mood: **flip this repo public as it stands.** The working notes ship — NEEDS_YOU, this
file, docs/history/, the live-check rows with the owner's decoded utterances — because
the owner's real objection dissolved on inspection: the personal-layer problem is what
their own **ai-continuum** exists to solve ("that was the reason i am building
ai-continuum — so i can store my personal notes there and you can still refer to
them"). Going forward, personal working notes belong in ai-continuum, referable by
agents and decoupled from any repo; the repo keeps the engineering record, which is its
credibility. Audio verified clean before the word was taken: all 49 tracked WAVs are
machine-synthesized or script-remade fixtures, the volunteer recordings are untracked,
outside the repo, and rewritten out of history (P4, force-push verified), and the
license-murky corpora were never committed. The one-way door was named and accepted:
public is permanent in practice — clones and mirrors survive any later flip back.
**Item 29 (publish script) and the gosaminfo transfer are retired unexecuted**; the
split entry below stands as the record of a position held for one hour. Parked,
owner-paced: migrating the live personal layer (NEEDS_YOU-style notes, future
decisions) into ai-continuum — a workflow change, not a tonight change.

**Corrected 2026-08-02, at the sweep, before the flip.** Two facts above were wrong, and
the decision survived both — but a record that keeps the wrong reason is worth less than
the decision it records, so here is what was measured.

*"Rewritten out of history (P4, force-push verified)"* was true of every branch and false
of GitHub. A force-push moves a ref; it does not remove objects. The pre-rewrite remote
tip `50d16f5` was still served by the API at sweep time, and its tree still held
`.bench/recorded/inbox/` — five clips, two of them named after a volunteer — and
`manifest-recorded.jsonl`, the file that names people. Private, that cost nothing;
public, it would have handed a stranger a volunteer's voice by SHA, three hours after
this repo committed a paragraph telling volunteers that could not happen. **So the flip
was done by deleting `samartomar/flow` and recreating it from the clean history**
(owner-decided 2026-08-02, chosen over a GitHub Support purge for being certain rather
than promised). Same name, same URL, one repo, nothing lost — 0 stars, 0 forks, one
branch, one day old. "Public in place" survives intact; only the server-side object
store did not.

*"All 49 tracked WAVs are machine-synthesized or script-remade"* was true of 45. The four
48 kHz speech fixtures are the owner at their own microphone, ~44 s, verified by
transcribing them. **Owner-decided the same day: they ship**, because `gate_bench`'s
published numbers are only re-runnable by a stranger if the audio ships with them, and
the content is two sentences about OAuth and Kubernetes. `.bench/README.md` now says
what they are instead of claiming a script remakes them. The volunteer clips keep the
opposite answer, and the difference is consent, not sensitivity.

One thing the sweep found that this entry never covered: `D:\dev\products\acme` reads
that way in the docs and the workshop test because the real path named a client.
**Owner-decided 2026-08-02: replaced everywhere.** "The working notes ship" is a decision
the owner can make about their own notes; the client's name was never theirs to publish.

### 2026-08-01 — Distribution amendment, superseded same evening: split repos — private working, public snapshot

Supersedes the single-repo flip below, on the owner's actual constraint surfacing: the
working layer (NEEDS_YOU.md, LOOP_PLAN.md, decisions.md, docs/history/,
docs/recording-kit.md, .bench/ with the owner's decoded utterances) is not for
publication. Architecture: the full repo moves private to **gosaminfo/flow** (GitHub
transfer, preserving history and issues), and **samartomar/flow is recreated public**
holding a curated source snapshot — `flow/`, `tests/`, `scripts/`, the reference docs
(README, product, architecture, analysis, roadmap as curated), LICENSE, pyproject, and
the release workflow — because "release only" cannot work: `uv tool install git+…`
needs source and CI needs code to build the zip from. The named cost, accepted: two
repos is a standing sync problem, so publishing is automated as a **publish script**
(LOOP_PLAN item 29) that copies the whitelist, proves the snapshot self-sufficient
(zero dangling links to excluded files; the unit suite green *inside the snapshot*),
and pushes it — one command per release, no hand-exporting to rot. Contributors get
snapshots, not history; public issues live on the public repo; the provenance religion
(identity blocks in bench results, measured constants in architecture.md) survives in
the public set without the personal layer.

### 2026-08-01 — Distribution (original): public via ai-harness, uv install; installer and Mac parked

Flow goes public and is listed in the owner's public
[ai-harness](https://github.com/samartomar/ai-harness) ("Enterprise AI Bootstrapping
Harness" — claude-code/codex/cli topics), whose audience is terminal-comfortable
developers already running agent CLIs. For them the dependency-free story is `uv`
(a single static binary) plus `uv tool install git+…/flow` — no bundler, no code
signing, no SmartScreen. **Widened same day by the owner:** a public **binary
release on the flow repo itself** — a PyInstaller onedir zip attached to GitHub
Releases, built by CI on tag push, so people outside ai-harness download and run
`flow.exe` with no Python at all (LOOP_PLAN item 28). Ships unsigned with the README
stating the one-time SmartScreen "Run anyway" honestly; **code signing and a proper
installer stay parked** until real non-developer demand exists (signing is a
subscription — a cost with no buyer today). The **macOS port waits for actual Mac users
asking, plus Mac hardware** — measured 2026-08-01: the three runtime deps all have Mac
wheels and the brain (asr, routing, session, lexicon, diag) is portable, but the body is
**96 Win32 call sites** (inject.py 61, ui.py 18, hotkey.py 17, SAPI via PowerShell), §7
and §8 are Windows-*measured* behaviour, and the live harnesses that verified them are
Windows-bound — a port re-takes those measurements or ships claims the repo's own rules
forbid. Prerequisites before the visibility flip (LOOP_PLAN item 27 + owner steps in
NEEDS_YOU): a LICENSE (none exists — a public repo without one is all-rights-reserved),
pyproject license/author metadata, a README install section, a friendly `sys.platform`
guard so a Mac user's first impression is one honest sentence instead of a ctypes
traceback, and the consent paragraph in recording-kit.md, which public visibility
converts from desk item to mandatory. The agent CLI stays unbundled by design (R9):
dictation works without it and the notes say so.

### 2026-08-01 — P9 decided from use: converse is a prompt workshop, grounded in a workspace setting

The scoping session this waited for happened at the desk instead: the owner tried
general conversation and it failed on its own merits — the CLI answered that it has no
internet access, and hallucinated. So P9's "ChatGPT Voice mode against the CLI" is the
stale half, and converse mode becomes what the owner named: **dedicated prompt
refinement, nothing more** — discuss and refine the prompt in conversation, take the
result (item 21), send it (item 22). Grounding: an **explicit workspace setting** (e.g.
`D:\dev\products\acme`) — the owner chose the explicit-path option over launch-dir
and over reading the target window's directory. Its cost, argued once and accepted: a
workspace set once goes stale silently when the project changes; the mitigation is
visibility, not magic — the converse-mode note and the startup line name the workspace
every time, so a wrong grounding is on screen. The owner's own words for why grounding
matters: "so prompt are grounded as well … and we also know what we are sending
properly." Spec'd as LOOP_PLAN item 23, which includes the P9 rewrite in
`docs/product.md` — the build follows the definition, and the definition follows the
evidence.
