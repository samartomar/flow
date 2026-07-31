# Roadmap: from working prototype to the product in [product.md](product.md)

Written 2026-07-31, after a full audit of the codebase against the actual target user —
a developer speaking accented English (Spanish, Indian, Russian, Japanese L1). This file
records what the audit found, the measurable targets, and the order of work. It follows
the project's standing rule: no claim without a number, and check the denominator.

## Where the build stands

The v0.1 loop is real and sound: mic → RMS speech gate → faster-whisper `base.en` int8 →
live partials → held draft → three-way routing (local regex edits / append / agent-CLI
rewrite) → clipboard+SendInput paste. ~1,660 lines, 10 modules, 3 dependencies, 79
tests, soak-tested for drift. The engineering discipline is the project's biggest asset.

Its accuracy, however, has never been measured on anything but SAPI-synthesised US
English (WER 0.000 — [README.md](../README.md) itself calls the number meaningless).
The open "risk 2" in [analysis.md](analysis.md) — real-voice accuracy — is where the
entire target population lives, and the audit found the current build is biased against
them at five specific points.

## The five defects that matter (all verified, file:line)

1. **Weakest possible model for accents.** `base.en` ([flow/asr.py:32](../flow/asr.py))
   is the smallest English-only tier. Published Svarah (Indian-English) numbers:
   multilingual base 13.6% WER, medium 8.3%, vs ~3–4% on LibriSpeech. English-only and
   distil variants rank *worse* on accented sets than their leaderboard positions.
   Expected real WER for strong accents on base.en: 15–25%+.

2. **A hidden second filter silently deletes accented speech.** Flow does not override
   faster-whisper's `no_speech_threshold=0.6` / `log_prob_threshold=-1.0`
   ([flow/asr.py:63-71](../flow/asr.py)), so segments failing both are dropped *inside
   the library* — before [clean.py](../flow/clean.py) runs, unlogged. Accented speech
   systematically scores worse on exactly these two signals.

3. **Flow's own filter breaks its two-signal doctrine.** The "thin" rule
   ([clean.py:110-112](../flow/clean.py)) drops any ≤3-word utterance on
   `no_speech_prob > 0.6` alone. Short utterances are what spoken corrections look like.
   All thresholds were calibrated on one voice, one machine.

4. **The command grammar shatters under accent.** Exact regex verbs + exact substring
   target match ([flow/edits.py](../flow/edits.py)): a mis-heard trigger ("delete"→"the
   lead", "swap"→"stop", "replace"→"leplace") silently APPENDS the command as text; a
   draft-mis-transcription makes the spoken (correct) target unfindable, so the free
   local fix escalates to a 7 s CLI call over text that doesn't contain the word. Undo
   phrases share the same fragility. No fuzzy or phonetic matching exists.

5. **The speech gate clips accented speech.** No pre-roll (soft onsets permanently
   lost), noise floor can ratchet to −25 dB (soft speakers gated out in noisy rooms),
   800 ms hangover fragments syllable-/mora-timed delivery into exactly the short
   segments defect 3 preferentially drops ([flow/audio.py](../flow/audio.py)).

Unused free levers: `hotwords` and `initial_prompt` (both supported by the installed
faster-whisper 1.2.1), final beam 2 vs library default 5, uncapped temperature fallback.

## Targets

| Metric | Today | Target |
|---|---|---|
| Per-accent WER, every anchor group (P1) | 18.7–30.6% on EdAcc (conversational; see Phase 0 results) | **≤ 12% floor** (not average) |
| Filter false-reject on real speech (P2) | 0 drops on 300 clips ≥ 1.5 s; on 280 clips < 1.5 s the user sees nothing on 1.1% (base.en) / 2.1% (small.en), of which correct content lost is 0% / 0.36% | **< 1%**, every drop logged |
| Command recognition, accented (P3) | unmeasured | **≥ 95%**; silent misroutes ≈ 0 |
| Personal-lexicon entity accuracy (P4) | no biasing exists | **≥ 90%** |
| Partial latency (R4) | base.en **clean to 8 s of speech** (worst 1.07 s) after the Phase 1 decode fix, breaching only at ≥ 12 s (1.98 s worst); small.en 2.66–3.78 s median at every length | **< 1.5 s, preserved** |

Benchmark composition (all local, redistribution-safe for internal eval):
**EdAcc** (CC BY-SA — the only open corpus with Spanish/Russian/Japanese/Indian slices
under one L1 metadata schema; conversational, treat as stress test) + **Svarah** (CC BY
4.0, Indian at scale, published baselines to sanity-check against) + **L2-ARCTIC**
(CC BY-NC, read speech ≈ dictation register, Spanish + Hindi) + **VoxPopuli
`en_accented`** (CC0, Spanish supplement). No published per-model numbers exist for
Russian- or Japanese-accented English — this harness produces new data.

## Phases

Two tracks. The accuracy track makes speech survive; the product track makes the result
worth speaking into. They interleave — each phase is independently shippable.

### Phase 0 — Measure (accuracy track, the foundation)

`scripts/fetch_accent_data.py` pulls per-L1 slices into `.bench/accent/` with a
`manifest.jsonl`; `scripts/accent_bench.py` decodes each clip per model and reports,
per accent group: **model WER** (all segments kept) vs **app WER** (simulating the
library's internal skip + `clean.is_invented`, i.e. what Flow would actually show), the
false-reject counts for both filters, and decode latency. The command-phrase benchmark
(P3) needs recorded accented speakers and is deferred until there are users to record —
the script inventory in [edits.py](../flow/edits.py) is the source of its prompt set.

**First run (2026-07-31, dev CPU, int8, 60 EdAcc clips/group, 31 min audio):**

| group | base.en | small.en | small | medium | small.en vs base.en |
|---|---|---|---|---|---|
| indian | 0.236 | 0.227 | 0.230 | 0.197 | −4% rel |
| japanese | 0.306 | **0.234** | 0.240 | 0.224 | **−23% rel** |
| russian | 0.187 | **0.149** | 0.150 | 0.150 | −20% rel |
| spanish | 0.189 | 0.163 | **0.159** | 0.148 | −16% rel |
| us-control | 0.282 | 0.224 | 0.227 | 0.199 | −20% rel |
| mean RTF | 0.19 | 0.51 | 0.43 | **1.44** | |

Read with the denominator in mind: EdAcc is *conversational* dialogue with cross-talk,
so absolute WER runs far above dictation register and even us-control scores 22–28%.
Valid signals are within-group model deltas, not group-vs-group absolutes. What the run
established:

- **`small.en` beats `base.en` by 16–23% relative on four of five groups** — largest on
  Japanese, the worst-served accent (30.6% → 23.4%). The Indian slice barely moved on
  this conversational data; the Svarah read-speech benchmark (base 13.6 → medium 8.3 in
  the literature) says the dictation-register gain is bigger — measure it next.
- **`small` (multilingual) ≈ `small.en` on every group.** The theorised multilingual
  accent advantage did not materialise at this tier on this data — the .en model is
  fine, and it removes the Hindi-transliteration failure mode debate.
- **RTF ~0.5 at small tier** — finals stay comfortably real-time; the R4 partial-prefix
  gate must be re-run before switching the default (asr_bench.py's prefix section).
- **Zero filter drops in 900 clip-decodes** (both the library skip and clean.is_invented,
  clips ≥ 1.5 s). The silent-deletion risk (defects 2–3) is *not* visible in energetic
  conversational speech; it remains untested exactly where the audit predicted it lives —
  short, quiet, borderline utterances. The probe for that is a short-clip (< 1.5 s)
  extension of this harness, not a reason to relax the Phase 1 observability fixes.

- **`medium` is where the Indian gain finally appears** (22.7 → 19.7 vs small.en, −13%
  rel) and it leads every group — but at **RTF 1.44 it is slower than real time on this
  CPU**, which rules it out even as a finals-only tier here: a 10 s utterance would take
  ~14 s to commit. It becomes viable only with faster hardware or a quantised/distilled
  variant worth a separate measurement.

**Decision from this data: `small.en` as the default.** The R4 prefix-latency gate and
the short-clip false-reject probe are done — results below.

**The dictation-register slice is blocked on a human (2026-07-31).** Every open route
was tried and none works from this machine:

| corpus | status |
|---|---|
| Svarah (`ai4bharat/Svarah`) | **401** — gated; needs someone to accept the terms on the dataset page and supply an `HF_TOKEN` |
| VoxPopuli `en_accented` (CC0) | paged `rows` endpoint returns **500** on every attempt (3 retries, all splits); only `first-rows` works, giving 100 rows whose L1s are European — **5 Spanish clips and none of the other anchor groups** |
| Common Voice (read speech, L1-labelled) | official repos **401**, community mirror **501** |
| L2-ARCTIC | distributed by request form, not on the datasets-server |

So the dictation-register question — is the accent gap smaller when people speak in
dictation register than in EdAcc's conversation? — stays open, and every WER number in
this document remains a conversational stress test. Unblocking it is one human action:
accept the Svarah terms and export `HF_TOKEN`, after which
`fetch_accent_data.py --tag svarah` needs only an auth header to work.

**R4 prefix-latency gate (2026-07-31, dev CPU, int8) — done.**
`scripts/asr_bench.py --prefix-only` now cuts growing prefixes from the *longest real
accented clip in each L1 group* (16–20 s of EdAcc speech) plus the SAPI `long.wav`
control, decodes each with production partial parameters (`beam_size=1`,
`condition_on_previous_text=False`), and gates on the **worst source**, not the average
— a user does not experience a median. Each cell is the median of 5 repeats (base.en,
195 timed decodes) or 3 (small.en, 117).

| prefix | base.en median | base.en worst | small.en median | small.en worst |
|---|---|---|---|---|
| 1 s | 0.78 | **1.67** ✗ | 2.60 | 2.62 ✗ |
| 2 s | 0.80 | 0.84 | 2.66 | 2.75 ✗ |
| 3 s | 0.83 | 0.86 | 2.79 | 3.02 ✗ |
| 5 s | 0.85 | 0.93 | 3.06 | 3.42 ✗ |
| 8 s | 0.93 | 0.98 | 3.11 | 3.30 ✗ |
| 12 s | 1.02 | **1.76** ✗ | 3.37 | 6.34 ✗ |
| 16 s | 1.21 | **1.87** ✗ | 3.75 | 3.97 ✗ |

- **`small.en` cannot drive partials: it fails the 1.5 s budget at every length,
  including 1 s.** Whisper pads every input to one 30 s mel window, so cost is nearly
  flat in prefix length — there is no short-utterance regime where this tier is fast.
  The breach is 1.7–2.5×, not marginal, so no tuning recovers it on this CPU.
- **`base.en` holds 2–8 s (worst 0.98 s) and breaches either side of that.** At ≥ 12 s
  the Spanish clip costs 1.73–1.91 s reproducibly — dense speech, more tokens, real
  work. Past ~12 s of continuous speech the current design therefore already misses
  R4: open question for Phase 3, either partials decode a trailing window instead of
  the whole utterance, or the utterance is cut before 24 s.
- **The 1 s breach is the temperature-fallback cascade, and it is measured.** The
  Japanese 1 s prefix scores `avg_logprob` −1.15, below faster-whisper's
  `log_prob_threshold` of −1.0, so the library silently re-decodes up the whole
  temperature ladder: **1.69–3.24 s with the default ladder vs 0.69–0.76 s at
  `temperature=[0.0]` — 2.4–4.7× slower, and nondeterministic.** The Spanish 12 s cell
  is unaffected (`avg_logprob` −0.21), confirming the two breaches have different
  causes. Capping the ladder at (0.0, 0.2, 0.4) is now a measured latency fix aimed
  exactly at low-confidence accented audio, not a tidiness item.
- **The SAPI control passes every cell at 0.73–0.79 s** — reproducing the original
  stage-2b "R4 gate passed: 0.75–0.91 s" number precisely. That old gate did not fail
  because it was run wrong; it failed because it was run on synthesised US English.
  Check the denominator.

**Short-clip false-reject probe (2026-07-31) — done.** The ≥ 1.5 s run showed zero
filter drops in 900 decodes, which proved nothing about the regime the audit actually
predicts: short, quiet, borderline utterances. `fetch_accent_data.py --tag short
--min-sec 0.3 --max-sec 1.5 --min-words 1` pulled a **separate** 280-clip slice
(0.31–1.48 s, median 0.70 s; spanish/russian/indian/us-control 60 each, japanese 40 —
EdAcc has no more), and `accent_bench.py --manifest manifest-edacc-short.jsonl` now
scores per clip whether Flow would have shown the user *nothing at all*.

| | base.en | small.en |
|---|---|---|
| utterances where the user sees nothing (model produced text, filters ate it) | 3/280 = **1.1%** | 6/280 = **2.1%** |
| …of which the deleted text was actually **correct** | **0** | **1** (0.36%) |
| same, under the proposed two-signal thin rule | 3 (1.1%) | 5 (1.8%) |
| segment drops by path | lib-skip 2, thin+unconfident 2 | lib-skip 3, thin+unconfident 2, thin 1 |
| model WER on this slice | 0.54–1.59 | 0.39–0.62 |

- **The silent-deletion risk is real but small, and it is mostly the filter working.**
  Of the nine drops across both models, eight discarded a *mis-hearing* of a
  backchannel — "UH" heard as "Mm.", "OKAY" as "Gay.", "NICE MM HMM" as "You". Exactly
  one lost correct content: `small.en` transcribed a 0.31 s Russian "YEAH" correctly
  and the library skipped it. Content loss is therefore 0% (base.en) and 0.36%
  (small.en) — inside P2's 1% bound; the *user-visible silence* rate is not.
- **The dominant drop path is the library's, not Flow's** — 5 of 9 drops happen inside
  faster-whisper's internal skip, unlogged and unattributable today. That is defect 2,
  and it is now the Phase 1 item with measured impact.
- **The proposed thin-rule change is nearly a no-op here** (3→3 and 6→5 clips) *and*
  it has a cost: the digital-silence hallucination measured in
  [clean.py](../flow/clean.py) ('You', `no_speech` 0.691, `avg_logprob` −0.711) is thin
  but **not** unconfident, so deleting the thin test re-admits it. Phase 1 must add a
  third signal — the whole-utterance filler list, currently reachable only when no
  probabilities exist — rather than simply requiring two. Pinned in
  `tests/test_bench.py`.
- **Denominator caveat, stated plainly: 31% of this slice (87/280) is pure
  backchannel** ("MM HMM", "YEAH", "UH"), because that is what sub-1.5 s conversational
  speech mostly *is*. EdAcc contains no short spoken *commands*, which is the case the
  audit really worries about. The command-phrase benchmark still needs recorded
  speakers; this probe bounds the filter's behaviour on short speech in general, not on
  "delete that line".
- **`small.en` is far better on short clips** (Japanese 1.59 → 0.62 WER, Indian
  0.97 → 0.57): short utterances are where `base.en` collapses hardest, which
  strengthens the split-tier decision below. RTF 4–5 on sub-1.5 s clips confirms the
  flat 30 s window — a 0.7 s utterance still costs `small.en` ~3.5 s.

**Finals cost (same sources, full 10–20 s utterances, median/worst of 6):**
base.en beam 2 **1.12 / 1.53 s**, beam 5 **1.37 / 2.52 s**; small.en beam 2
**4.07 / 4.90 s**, beam 5 **4.87 / 6.12 s** (at a typical 5 s utterance, small.en beam 2
is 3.04 s). Finals are not latency-bound the way partials are — the draft is held on
screen (R5) — so small.en is affordable there and beam 5 costs it ~20% more.

### Phase 1 — Stop the bleeding (accuracy track, small diffs)

- Pass explicit `no_speech_threshold` / `log_prob_threshold`; log every dropped segment
  (defect 2 → P2). **Measured as the dominant drop path: 5 of 9 short-clip drops happen
  inside the library, invisible to Flow.** Do this one first.
- Thin rule requires two signals again; drops become visible events (defect 3 → P2).
  Measured as nearly a no-op on its own (3→3 / 6→5 clips), and deleting the thin test
  outright re-admits the digital-silence 'You' — so the rule needs the whole-utterance
  filler list as its second signal, not just `avg_logprob`.
- ~~Final beam 5, temperature fallback capped at (0.0, 0.2, 0.4)~~ **done 2026-07-31.**
  Partials pay for *no* retries (`temperature=(0.0,)`); finals get beam 5 and the capped
  ladder. `flow.asr.decode_options()` is now the single source both the app and the
  benches decode with. **R4 longest clean prefix: none → 8 s of speech**; the 1 s
  accented cell 1.67 → 0.79 s worst; a 5 s noise clip 8.52 → 1.37 s worst on the partial
  path. WER improves or ties on all five groups (Japanese 0.41 → 0.28), and the
  uncapped ladder's run-to-run instability (Japanese 0.299/0.312/0.412 across three
  runs) collapses to 0.281/0.286/0.289. Cost: capping removes Whisper's own escape from
  repetition loops, so `clean.collapse_phrase_repeats()` now breaks them deterministically
  — without it, one Spanish clip returned "I'm so sorry." ×30 (87 edits on a 4-word
  reference) and one Indian clip a 7-word phrase ×22 (207 edits).
- `hotwords` from a user-editable lexicon file — names, repo terms, jargon (P4 seed).
- Grammar hardening: politeness/hedge prefixes on all patterns, fuzzy verb-snapping
  (edit distance ≤ 1 + suffix stripping), alias table, `re.escape` fix, stale
  force-next fix (defect 4, first half → P3).
- Code-switch guardrail: low-confidence utterances cannot trigger destructive edits.

### Phase 2 — Model decision (accuracy track, from Phase 0 data) — **decided**

The R4 gate settled it: **split tiers.** `base.en` stays on partials (0.78–0.93 s
median, the only tier that fits the budget at all) and `small.en` becomes the model for
the final that is actually pasted — 16–23% relative WER improvement on four of five
accent groups, at 4.07 s median for a full utterance, absorbed by the held draft (R5).
Multilingual `small` is dropped: it matched `small.en` on every group, so it buys
nothing and costs the Hindi-transliteration failure mode. `medium` remains out at
RTF 1.44.

The cost of the split is a visible partial→final rewrite on screen, since the two tiers
disagree on ~1 word in 5 for accented speech. That is the trade the numbers force, and
it is the same trade Wispr makes.

### Phase 3 — Correction loop that survives accents (both tracks)

- Phonetic target matching: one `find_span()` (double-metaphone, vendored ~100 lines,
  + `difflib` ratio) replacing both exact-match sites — *"change Sameer to Samir"*
  finds "summer" in the draft (defect 4, second half → P3).
- Constrained re-decode of suspected commands, biased with the trigger lexicon + draft
  tokens via `hotwords` (~1 s, replaces the 7 s CLI escalation).
- Post-hoc "that was a command" rescue chip; pre-roll ring buffer + gate retune
  (defect 5 → P2).
- **Prompt polish (P5):** "make it a proper prompt" as a first-class semantic verb with
  a purpose-built CLI instruction (structure: context → constraint → ask).
- **Terminal-safe send (P7):** bracketed paste / newline suppression per target class.

### Phase 4 — The product grows a memory and a voice (product track)

- **Thread continuity (P6):** Send appends to a session thread instead of erasing;
  "follow up" / "bring back my last prompt"; CLI rewrites see the bounded thread tail.
- **Converse mode (P9):** route Send to the agent CLI instead of the focused window,
  render the reply above the pill, keep the CLI session alive across turns — ChatGPT
  Voice mode against `claude`/`codex`. Optional spoken replies via Windows SAPI
  (ctypes-reachable, R16 intact).
- **Personalisation (P8/P4):** first-run calibration (gate floor + per-user threshold
  profile from a 60 s read); lexicon growth from corrections (every "change X to Y" is
  a labelled confusion pair); local misroute telemetry (undo-after-append signature)
  growing the alias table. No egress, ever (R9).

## What this explicitly defers

- Accent-specific fine-tunes: helps one L1 group, does not generalise across four;
  personalisation is the scalable substitute. Revisit only if Phase 2 + biasing leave a
  measured gap.
- Streaming/word-level partials (the Wispr smoothness gap): architecture-level, and
  worthless until the words being streamed are the right ones.
- The command-phrase recorded benchmark: needs real accented speakers; prompt inventory
  is ready when they are.
