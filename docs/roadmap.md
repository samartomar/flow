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
| Per-accent WER, every anchor group (P1) | **read register: 5.2–6.3% (small.en), 5.8–8.5% (base.en)** — target met for **3 of 4** groups. **Spanish is closed as unmeasurable**: no obtainable read-register corpus contains it (see below). Conversational EdAcc: 15.1–23.4% (small.en), Spanish 16.3% | **≤ 12% floor** (not average) |
| Filter false-reject on real speech (P2) | 0 drops on 300 clips ≥ 1.5 s; on 280 clips < 1.5 s the user sees nothing on 1.1% (base.en) / 2.1% (small.en), of which correct content lost is 0% / 0.36% — and **every drop is now logged with its signals** | **< 1%**, every drop logged |
| Command recognition, accented (P3) | **10/11 end-to-end from phone audio, 1 speaker (us-control)** — decode + route, not transcripts. Synthetic grammar: 100% recall on all six corruption classes, 0/580 misroutes on real speech | **≥ 95%**; silent misroutes ≈ 0 |
| Personal-lexicon entity accuracy (P4) | no biasing exists | **≥ 90%** |
| Partial latency (R4) | base.en **clean to 8 s of speech** (worst 1.07 s) after the Phase 1 decode fix, breaching only at ≥ 12 s (1.98 s worst); small.en 2.66–3.78 s median at every length | **< 1.5 s, preserved** |

Benchmark composition (all local, redistribution-safe for internal eval):
**EdAcc** (CC BY-SA — the only open corpus with Spanish/Russian/Japanese/Indian slices
under one L1 metadata schema; conversational, treat as stress test) + **AESRC2020**
(community re-upload, no declared licence, local eval only; read register, Indian +
Japanese + Russian + US control, **no Spanish**) + **VoxPopuli
`en_accented`** (CC0, 5 Spanish clips — too few to quote). *Svarah and L2-ARCTIC were
in this list and are both dropped — see the corpus table below.* No published
per-model numbers exist for
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
| Svarah (`ai4bharat/Svarah`) | **401** — gated (CC BY 4.0, not paid: someone accepts the terms and supplies an `HF_TOKEN`). **Dropped** — see below; AESRC answered the question it was for |
| VoxPopuli `en_accented` (CC0) | paged `rows` endpoint returns **500** on every attempt (3 retries, all splits); only `first-rows` works, giving 100 rows whose L1s are European — **5 Spanish clips and none of the other anchor groups** |
| Common Voice (read speech, L1-labelled) | official repos **401**, community mirror **501** |
| L2-ARCTIC | request form, not on the datasets-server. **Dropped** — unobtainable here, and it was the last read-register corpus with Spanish |

**Svarah is dropped, and not because it is gated.** It was queued to answer one
question — is the accent gap smaller in dictation register than in EdAcc's conversation?
— and AESRC2020 answered it below: read register is 2.3–4.8× easier and the accent gap
nearly vanishes there. Fetching Svarah would corroborate a result that already passes
its target, and it holds no commands, so it does nothing for P3, the one metric still
genuinely open. The human action it costs competes with the only human action worth
spending: recording accented speakers saying commands, which no public corpus contains.
Its published baselines stay cited above as a reference point; the data is not needed.

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

**Dictation-register slice (2026-07-31) — done, and it reframes the premise.**
Svarah stayed gated, but AESRC2020 (`pengyizhou/accented_english`, a community
re-upload) is reachable, carries transcripts and speaker IDs, and covers Indian,
Japanese and Russian plus an American control. `fetch_accent_data.py --corpus aesrc`
pulled 60 clips per group, 17.3 min of **read** speech. Same harness, same shipped
decode config as the EdAcc numbers above:

| group | EdAcc (conversation) | AESRC (read) | ratio |
|---|---|---|---|
| indian | 0.231 / 0.219 | **0.085 / 0.055** | 2.7× / 4.0× |
| japanese | 0.281 / 0.234 | **0.059 / 0.052** | 4.8× / 4.5× |
| russian | 0.178 / 0.151 | **0.077 / 0.063** | 2.3× / 2.4× |
| us-control | 0.276 / 0.221 | **0.058 / 0.052** | 4.8× / 4.2× |

*(base.en / small.en)*

**Read register is 2.3–4.8× easier than conversation, and the accent gap nearly
disappears in it.** Against the US control on small.en: Japanese **+0.000**, Indian
**+0.003**, Russian **+0.011**. On base.en the gap is larger but still small — Indian
+0.027, Russian +0.019, Japanese +0.001.

**P1's ≤ 12% floor is already met in the register the product actually operates in**:
worst group 8.5% on base.en, 6.3% on small.en. The 18–31% figures that motivated the
whole accuracy track are conversational EdAcc — a stress test, and *not* how anyone
dictates a prompt. That does not make the Phase 1 work wasted (latency, silent
deletion, and the command grammar were real defects on their own evidence), but it does
mean the headline accuracy problem was largely a property of the benchmark.

Four things keep this honest rather than triumphant:
- **Spanish is absent from AESRC, and now permanently.** L2-ARCTIC (request form) and
  Common Voice (401) were the alternatives and neither is obtainable, so the Spanish
  read-register cell is closed as unmeasurable rather than left open. It does not
  become a new gap: the only way to fill it is a Spanish volunteer recording, which is
  the ask already outstanding. One of the four anchor groups is unmeasured in this
  register, and it is the one EdAcc rated hardest after Japanese.
- **AESRC is prompted studio-ish read speech**, so it is an optimistic bound just as
  EdAcc is a pessimistic one. Real use sits between them.
- **The re-upload declares no licence.** Local internal eval only.
- **One real-voice sample lands at 0.203 / 0.171** (base.en / small.en) — the project
  owner's own voice, phone, real room, 187 reference words, reading a known text. That
  is 2.4× worse than AESRC read speech in the same register, which says the corpus
  numbers flatter real conditions. It is a single speaker who also ad-libbed against the
  reference, so it over-counts errors — an upper bound against an optimistic bound.

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

- ~~Pass explicit `no_speech_threshold` / `log_prob_threshold`; log every dropped
  segment (defect 2 → P2)~~ **done 2026-07-31.** `no_speech_threshold=None` turns the
  library's invisible filter off; every rejection is now Flow's own, recorded as a
  `Drop` (text, rule, both signals, partial-or-final) in a bounded log and emitted as
  its own event kind.

  **Correction to the audit, and to this file's earlier claim.** "5 of 9 short-clip
  drops happen inside the library" was an artefact of running the library's rule first.
  The library skips on `no_speech_prob > 0.6 AND avg_logprob < −1.0`, and `< −1.0`
  implies `< −0.8`, so **every segment it ate was already failing Flow's own rule** —
  verified across all 681 segments of the short slice: 5 library-skips, 5 also dropped
  by clean.py. Defect 2 is real as an *observability* defect, not as extra deletion.
  It also has to be fixed before P8 can mean anything: once thresholds are calibrated
  per user, Flow's rule can be looser than the library's, and then the hidden filter
  would start eating speech Flow intended to keep.

  `log_prob_threshold` is `None` for the same measured reason: retrying a decode
  because the model was *unsure* buys nothing (five accent groups within run-to-run
  noise, 300 clips) and costs a lot on near-silence, where confidence is low and a
  retry cannot help — one 5 s noise clip went 0.84 s → 3.66 s with it set. Degenerate
  output still retries, through `compression_ratio_threshold`, which is the case where
  a hotter sample actually fixes something.
- ~~Thin rule requires two signals again; drops become visible events (defect 3 → P2)~~
  **done 2026-07-31.** Shortness is no longer evidence of anything. A segment is
  dropped when the model doubts it was speech **and** a second signal agrees: either
  the whole utterance is in the known-hallucination list, or the token confidence is
  poor. The filler list is what keeps the digital-silence 'You' (0.691 / −0.711 — short
  but *confident*) caught, which a naive "require two signals" would have re-admitted.

  **Measured, and the honest reading:** across 1416 decoded segments the two rules
  disagree on **29**, all `thin → kept`, and all from a single degenerate clip where
  `"I'm sorry."` looped — text the model was *sure* about (`avg_logprob` −0.11) that the
  old rule deleted purely for being two words long. Cost: Spanish app WER 0.183 → 0.187,
  every other group unchanged, false-reject unchanged (3 and 6 clips). The case this
  rule exists for — a short spoken command — **cannot be measured on EdAcc, which
  contains none**; it is pinned as a test instead ("delete that line", 0.9 / −0.3,
  kept). This change is justified by the failure mode, not by a corpus win.
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
- ~~`hotwords` from a user-editable lexicon file — names, repo terms, jargon (P4 seed)~~
  **done 2026-07-31, and the measurement changed its shape.** `~/.flow/lexicon.txt`,
  one term per line, re-read on change, capped at 64 whole terms (the library truncates
  mid-term at 223 tokens, silently). Both tiers are biased; `--lexicon` / `--no-lexicon`
  override. `scripts/lexicon_bench.py` is the new harness.

  **Biasing is a trade, not a win** (`small.en`, EdAcc): it recovers **27–34%** of the
  rare reference words a decode missed *when those words are spoken* (~3% relative WER),
  and it makes WER **14–38% relatively worse** on speech containing none of the terms —
  0.223 → 0.265 and 0.221 → 0.252 at 61 terms, 0.201 → 0.278 at **eight**. The harm did
  not shrink with the lexicon, so there is no safe-small-lexicon advice to give. The
  file therefore does not exist until the user creates it, and creating it *is* the
  opt-in. Phase 3's constrained re-decode is the targeted fix: bias only when the first
  pass produced something phonetically near a term, so the cost is paid where it pays.
- ~~Grammar hardening: politeness/hedge prefixes on all patterns, fuzzy verb-snapping,
  alias table, `re.escape` fix, stale force-next fix~~ **done 2026-07-31.** Every
  pattern takes a repeatable lead-in (politeness was the missing half — "can you delete
  Tuesday" was being appended as dictation). A mis-heard verb is snapped by edit
  distance, adjacent transposition, suffix stripping, or an explicit alias table; the
  snapped reading is accepted **only if it produces a local edit whose target is really
  in the draft**, so a guess can promote a mis-heard command and can never demote
  dictation. `replace_all` substitutes through a function, so a dictated `` or a
  Windows path stays literal. The Refine/Continue override is consumed on every routed
  utterance and expires after 30 s.

  Measured with the new `scripts/command_bench.py`:

  | corruption (synthetic) | n | patterns only | + snapping |
  |---|---|---|---|
  | clean | 14 | 100% | 100% |
  | politeness lead-in | 112 | 100% | 100% |
  | verb suffix ("deleting") | 14 | 0% | **100%** |
  | one substituted letter | 14 | 14% | **100%** |
  | adjacent transposition | 14 | 14% | **100%** |
  | known mis-hearing ("the lead") | 12 | 0% | **100%** |

  and the precision it costs: **zero**. On 20 adversarial sentences that *start* like
  commands with drafts full of their own words, snapping adds no misroutes (4 of 20
  either way — all four are the exact grammar's own shape heuristic, undoable by
  design). On 580 real EdAcc utterances, 0 misroutes both ways — though `snap()` alters
  only one of those 580, so that column bounds the risk on conversational dictation
  rather than proving much.
- ~~Code-switch guardrail: low-confidence utterances cannot trigger destructive
  edits.~~ **done 2026-07-31, and not the way it was written.** Two stricter forms were
  built and both were measured and rejected. A bar on `avg_logprob` is an accent tax:
  at −0.7 it puts **38% of ordinary Spanish speech** behind a confirmation against 0–5%
  for every other group (Spanish median −0.62 vs −0.27…−0.32 for the rest), while still
  passing a misheard "Release the bit about the stand up" at −0.65. Refusing snapped
  verbs for `delete_last` — the one destructive op with no target to verify — works,
  but costs 100% → 92.9% recall on three corruption classes to prevent something that
  fires **0 times in 580 real utterances**. So the shipped guarantee is P2's, extended
  from dropped speech to deleted speech: a deletion may happen, it may not happen
  *unexplained*. Every destructive edit now reports the words it removed.

### Phase 2 — Model decision (accuracy track, from Phase 0 data) — **shipped 2026-07-31**

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

**Implemented and measured under the shipped decode config** (beam 5, capped ladder,
one filter), 300 clips, model WER `base.en` → `small.en`:

| group | base.en | small.en | relative |
|---|---|---|---|
| indian | 0.231 | **0.219** | −5% |
| japanese | 0.281 | **0.234** | −17% |
| russian | 0.178 | **0.151** | −15% |
| spanish | 0.187 | **0.166** | −11% |
| us-control | 0.276 | **0.221** | −20% |

`small.en` finals run at RTF 0.36–0.51. The second resident model costs **+268 MB**
(181 MB with the partial tier alone, 450 MB with both, 100 MB after the idle unload),
and 464 MB more on disk. `--model base.en` pins both tiers to one model where that
matters. Each tier loads lazily and independently, so a session that never finalises an
utterance never pays for `small.en` at all.

### Phase 3 — Correction loop that survives accents (both tracks)

- ~~Phonetic target matching: one `find_span()` replacing both exact-match sites~~
  **done 2026-07-31.** `flow/phonetic.py` vendors Double Metaphone (~200 lines, stdlib
  only, R16 intact) plus a `similarity()` that blends sound with spelling, and
  `find_span()` / `find_spans()` search word windows sized around the target's own word
  count ±1 — a mis-transcription moves word boundaries as readily as letters
  ("Sameer" → "some ear"). Both exact-match sites now go through it: `in_draft()` in
  the router, and every span operation in `apply_local()`.

  **The threshold was swept, not chosen** — ten real mis-transcription pairs against
  354 real utterances paired with a genuinely absent word:

  | threshold | pairs found | false spans |
  |---|---|---|
  | 0.75 | 10/10 | 19/354 |
  | 0.80 | 10/10 | 10/354 |
  | **0.82** | **10/10** | **4/354** |
  | 0.85 | 7/10 | 4/354 |
  | 0.90 | 5/10 | 3/354 |

  0.82 keeps full recall where the false-span rate has already flattened; stricter
  costs three of ten recoveries and buys nothing until 0.90, which trades half the
  recall for one span. **All 10 corrections whose target the draft spells differently
  now stay local (no ~7 s CLI call) and edit the right span** — the escalation this
  defect caused is gone on the measured set.
- ~~Constrained re-decode of suspected commands, biased with the trigger lexicon +
  draft tokens via `hotwords`~~ **done 2026-07-31.** A semantic plan now records
  *why* it is semantic: `escalated=True` means the shape was a correction but the
  target was nowhere in the draft, which is likelier a mis-hearing than a request for
  judgement. Those get one re-decode of the same audio, biased by
  `edits.command_bias()` — every trigger verb plus the draft's own long words, capped
  at 48 terms — before any CLI call. A genuine "make it more formal" is not marked and
  goes straight to the CLI as before.

  Measured with `scripts/rescue_bench.py`: the command inventory synthesised through
  two SAPI voices, buried in white noise at falling SNR, `small.en`.

  | SNR | first read routes correctly | after the biased re-read | re-read cost |
  |---|---|---|---|
  | clean | 23/24 | **24/24** | 2.06 s |
  | 15 dB | 23/24 | **24/24** | 2.01 s |
  | 10 dB | 21/24 | **24/24** | 2.01 s |
  | 5 dB | 20/24 | **24/24** | 2.04 s |
  | 0 dB | 15/24 | **21/24** | 2.05 s |

  Every first-read failure is recovered down to 5 dB, and two thirds of them at 0 dB,
  for **~2.0 s against the ~7 s CLI call** it replaces — and the result is a correct
  local edit rather than a CLI asked to edit text not containing the word. SAPI is a
  US-English synthesiser, so this measures the *mechanism*, not the population;
  accented command recordings remain the missing benchmark.
- ~~Post-hoc "that was a command" rescue chip~~ **done 2026-07-31.** A spoken trigger
  ("that was a command / an instruction / an edit", with the usual lead-ins) and a
  chip that appears only when there is something to re-read. It withdraws the last
  append *first* — so the re-plan sees the draft as it was when the command was
  spoken — then re-plans those words, and if they are still not a command re-decodes
  the stored audio with the command bias. If nothing works the words go back exactly
  where they were: dictation is never the price of a failed guess.

  **Measured, and it reframes the previous item.** Splitting the misroutes in
  `scripts/rescue_bench.py` by how they present:

  | SNR | first read | silent appends | escalations | after the re-read |
  |---|---|---|---|---|
  | clean | 23/24 | 1 | 0 | 24/24 |
  | 15 dB | 23/24 | 1 | 0 | 24/24 |
  | 10 dB | 21/24 | 3 | 0 | 24/24 |
  | 5 dB | 20/24 | 3 | 1 | 24/24 |
  | 0 dB | 15/24 | 8 | 1 | 21/24 |

  Of 17 misroutes across all levels, **16 arrived as silent appends and one as an
  escalation**. So the automatic constrained re-decode — which only fires on
  escalations — covers about 6% of the failures, and this chip covers the rest. The
  two mechanisms share a re-read; they differ entirely in how often they get to run.
- ~~Pre-roll ring buffer in the gate~~ **done 2026-07-31** (defect 5 → P2). The gate
  keeps the last 4 blocks (256 ms) it heard while quiet and hands them back when it
  opens, so the head of the word that opened it is not already gone. Measured with the
  new `scripts/gate_bench.py`, which runs the production gate over 80 real clips,
  reassembles what the session *would have captured*, and decodes that (deterministic
  single-temperature decode, because the finals ladder's sampling noise is the same
  size as the effect):

  | condition | WER | audio kept |
  |---|---|---|
  | ungated (whole clip) | 0.284 | 100% |
  | gated, no pre-roll | 0.291 | 97.4% |
  | gated, 128 ms | 0.278 | 98.0% |
  | gated, 256 ms | 0.282 | 98.2% |
  | gated, 512 ms | 0.281 | 98.4% |

  Gating without pre-roll deletes **2.6% of the audio** and costs ~2.5% relative WER;
  any pre-roll from 128 ms up returns WER to the ungated level. The three settings are
  indistinguishable at this denominator (spread 0.004 ≈ 6 edits in ~1400 reference
  words), so 256 ms is the middle of a measured-equivalent range rather than a tuned
  optimum. Gate retune (noise floor, hangover) remains open.
- ~~**Prompt polish (P5):** "make it a proper prompt" as a first-class semantic verb~~
  **done 2026-07-31.** Its own verb in the grammar (checked before the generic
  `make it …` rewrite pattern, which would otherwise swallow it) carrying `op="polish"`,
  and its own CLI instruction in refine.py: order as context, then constraints, then the
  ask; keep every concrete detail verbatim; invent nothing; no preamble. The spoken
  phrase is *not* passed to the CLI — the user named a transformation, they did not
  write an instruction to be interpreted. The commentary guard is looser for a polish
  (8× + 600 rather than 4× + 200) because structure legitimately costs words.

  **Measured** with the new `scripts/polish_check.py`, five rambling technical
  dictations through `codex`:

  | | |
  |---|---|
  | detail retention (versions, paths, names, error codes) | **15/15 tokens** |
  | latency | median **5.3 s**, max 8.3 s |
  | growth | median **×1.1** — restructured, not padded |
  | preamble despite being forbidden | **0/5** |

  Whether the result is *better* is the judgement P5 leaves to a reviewer, so the raw
  before/after pairs go to `.bench/polish.json` for a human rather than being scored.
  One unedited example: *"write a migration that adds a nullable column called
  last_seen_at to the users table, postgres fifteen, and it has to be online, no table
  lock"* → *"The database is PostgreSQL 15. / The migration must be online and use no
  table lock. / Write a migration that adds a nullable column called last_seen_at to
  the users table."*
- ~~**Terminal-safe send (P7):** bracketed paste / newline suppression per target
  class~~ **done 2026-07-31.** `inject.py` classifies the focused window before it
  touches the clipboard — window class *or* process name, via ctypes, R16 intact — and
  `prepare()` decides what is safe to send.

  **The guarantee:** a draft ending in a newline never reaches a shell with that
  newline attached. That is the failure worth preventing, because it does not paste,
  it *runs*. The user presses Enter when they mean to.

  **What is honestly not a guarantee:** interior newlines. A terminal with bracketed
  paste hands the whole block to the shell as literal text; one without runs each line
  as it arrives — and Flow cannot change that from outside, because the terminal adds
  the bracket markers itself on Ctrl-V. Writing them onto the clipboard would produce a
  second, literal pair in the user's text. So Flow reports it instead of pretending:
  pasting multiple lines into `cmd.exe` prints a warning naming the process. Interior
  newlines are never rewritten — silently reflowing someone's text to make it safe is
  worse than telling them.

  **Measured** against the windows actually open on this machine (`scripts/inject_check.py
  survey_targets`): **16 visible top-level windows, 2 classified as terminals** (both
  Windows Terminal, both bracket-paste capable), **0 false positives among the other
  14** — Notepad, Obsidian, Chrome, Edge, explorer, VS Code, Settings and the rest all
  correctly ordinary.

### Phase 4 — The product grows a memory and a voice (product track)

- ~~**Thread continuity (P6):** Send appends to a session thread instead of erasing~~
  **done 2026-07-31.** `flow/thread.py` keeps the sent prompts; Send appends rather
  than erasing. Two spoken verbs, and they are the only commands that mean anything
  with an empty draft — which is exactly the state Send leaves behind: *"bring back my
  last prompt"* restores it, *"follow up"* (optionally carrying its own words: *"follow
  up: and add a rollback"*) marks the new draft as a continuation. A CLI rewrite sees
  the thread tail **only** on a follow-up, labelled as background and explicitly
  excluded from the output, so an ordinary correction never pays for the context.

  **Measured** — the two properties this feature has to bound:

  | | |
  |---|---|
  | 5,000 sends of a realistic prompt | **20 turns, 1,640 chars** (caps: 20 / 20,000) |
  | tail handed to the CLI | 18 turns, **1,476 chars** (cap 1,500) |
  | CLI prompt with context attached | 220 → 1,823 chars (**+1.6 kB**, follow-ups only) |
  | one 200,000-char send | kept whole, as 1 turn |

  The last row is deliberate: a single oversized prompt is never dropped, because
  "bring back my last prompt" has to work for a long one too. It is the one case where
  the store exceeds its character cap, and it is bounded by the utterance limit above
  it. Recall also refuses to overwrite a draft that is already on screen — it appends,
  because history is not worth losing live text for.
- ~~**Converse mode (P9)**~~ **done 2026-07-31.** `Session.mode` routes Send to
  `refine.ask()` instead of the focused window; the reply renders in the bubble in its
  own colour, is added to the thread so the next question inherits it, and Ctrl+Alt+M
  switches modes without touching the draft. There is no persistent CLI process —
  continuity is re-sent from the P6 thread, which keeps R11 and R8 and means a crashed
  or upgraded CLI cannot take the conversation with it. Measured end to end against
  codex: 10.4 s first answer, 7.8 s follow-up, and the follow-up resolved "a good
  system" from context without repeating the first question. Spoken replies via
  `--speak` are one long-lived PowerShell `System.Speech` host, not a subprocess per
  reply: that is what makes them interruptible when the user talks over the answer.
- ~~**Personalisation (P8/P4)**~~ **done 2026-07-31.** `flow --calibrate` listens for
  60 s of a read passage and stores the room, the voice and this speaker's own
  `avg_logprob` in `~/.flow/profile.json`; the gate's floor and margin come from that
  file instead of from constants tuned on one machine. The room/voice split is by the
  widest gap in the sorted levels, not a percentile — a fluent reader is silent for
  about a sixth of the minute, and "the quietest fifth is the room" calibrates their
  floor to −45 dB. Every "change X to Y" is recorded as a confusion pair and, once it
  recurs, its target joins the decode bias (P4); only the target, since the wrong
  reading is what the model already produces unaided. Undo-straight-after-append is
  recorded as a misroute signature and **reported**, not applied: adding to `_ALIASES`
  changes what a word means for every future utterance, and "this was a command twice"
  cannot establish "this is never dictation". No egress — there is no code in
  `profile.py` that could send anything anywhere (R9).

## What this explicitly defers

- Accent-specific fine-tunes: helps one L1 group, does not generalise across four;
  personalisation is the scalable substitute. Revisit only if Phase 2 + biasing leave a
  measured gap.
- Streaming/word-level partials (the Wispr smoothness gap): architecture-level, and
  worthless until the words being streamed are the right ones.
- The command-phrase recorded benchmark: **the pipeline is done and scored** (recording
  sheet, `scripts/ingest_recordings.py`, `command_bench.py --recorded`), and one control
  speaker has been through it end to end. What is still missing is people — zero
  recordings exist for any of the four L1 anchor groups.
