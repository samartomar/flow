# Keys and Markdown by voice: what to build, and what not to train

Written 2026-09-26 from a design conversation with the owner, after reading
`flow/edits.py`, `flow/asr.py`, `flow/inject.py`, `flow/help.py`, `flow/refine.py`,
`scripts/command_bench.py`, [NEEDS_YOU.md](../NEEDS_YOU.md) and [decisions.md](decisions.md).
**Nothing in Flow was changed.** It is a proposal for the owner to pick up; nothing here is
decided.

Two asks are covered:

1. **Keyboard commands**: *"kb enter"*, *"kb tab"*, *"kb num 121.05"*, *"kb symbol underscore"*.
2. **Markdown by voice**: headings, bullets, checkboxes and code blocks for the Markdown files
   most of Flow's users write.

Both started as "should a small model be trained for this?". The short answer is **no for
understanding the words, maybe for hearing them**.

Status of every claim below, same grading as [analysis.md](analysis.md):
`CONFIRMED` = verified (in code or in Flow's own recorded measurements) · `PLAUSIBLE` =
mechanism known, not yet run · `SPECULATIVE` = pattern-match only.

---

## Summary

- **Understanding is a grammar problem, and Flow's grammar already fits it.** Keyboard
  commands and Markdown shapes are a small closed vocabulary. They belong in the same
  machinery as "change Tuesday to Thursday": instant, exact, testable, measured by
  `command_bench.py`. `CONFIRMED` that it fits; see section 1.
- **A trained text model would make it worse.** It adds a runtime beside Flow's three
  dependencies, adds latency, and a generative model can invent a digit. Typing 121.50 when
  the speaker said 121.05 is worse than missing the command. `PLAUSIBLE`.
- **Hearing is the real risk.** [product.md](product.md) P3 sets ≥ 95% command
  recognition, and the owner's three live runs scored **55%, 73%, 55%** (decisions.md,
  2026-08-01, "Garbled CLI escalations"). decisions.md already says it: *"no grammar recovers a word the decoder never
  produced"*. No text model recovers it either. `CONFIRMED`.
- **A real Enter keystroke is as dangerous as the send word.** `asr.py`'s rule that the
  send word is never biased toward applies to it unchanged. `CONFIRMED` (section 2.3).
- **Markdown is more rows in the existing shape table**, gated by a lead-in word or line
  start. That is the same answer as the open NEEDS_YOU entry *"Spoken punctuation eats five
  ordinary words"*, so one rule settles both. `CONFIRMED` that the conflict exists.
- **If anything gets trained, train Whisper, not an intent model.** A LoRA fine-tune of
  `small.en` on the speaker's own commands. `PLAUSIBLE`.

---

## 1. What Flow already has

All `CONFIRMED`, read in code on 2026-09-26.

| What | Where | Relevance |
|---|---|---|
| Spoken punctuation: "press enter" → newline, "press tab"/"tab" → four spaces, "dash" → `- `, "comma", "period", "colon" and more | `_SHAPE_TABLE`, [flow/edits.py:1129](../flow/edits.py) | Produces **text shape** inside the paste, not keystrokes. Unconditional by design. |
| "new paragraph" / "new line" | `local/break`, [flow/help.py:138](../flow/help.py) | Already covers paragraph breaks. |
| "format it", "bullet point", "turn it into…" → agent CLI rewrite | `_SEMANTIC`, [flow/edits.py:485](../flow/edits.py) | Asked-for restructuring already exists, at ~7 s per call. "bullet point" is taken. |
| Refine keeps headings, bullets or tables only when the speaker names them | [flow/refine.py:128](../flow/refine.py), [:654](../flow/refine.py) | Refine already honours named formatting. |
| Keystrokes via `SendInput` (`INPUT_KEYBOARD`); the foreground window's program via `QueryFullProcessImageNameW` | [flow/inject.py:74](../flow/inject.py), [:604](../flow/inject.py) | Real keys can be sent between pastes; the target app can be identified. |
| Constrained re-decode: `hotwords` bias for one decode of a *suspected* mis-heard command | [flow/asr.py:450](../flow/asr.py), [flow/lexicon.py:34](../flow/lexicon.py) | The safe way to help Whisper hear a command. |
| The send word is never biased toward | [flow/asr.py:209](../flow/asr.py) | The safety rule a real Enter inherits. |
| Recall on corrupted commands, precision on 580 real EdAcc utterances | [scripts/command_bench.py](../scripts/command_bench.py) | The acceptance harness for everything below. |

---

## 2. Keyboard commands

### 2.1 Two different things are called "enter"

- **Shape**: characters inside the pasted text. "press enter" already becomes a newline in
  the paste. Exists.
- **Keys**: real keystrokes sent to the app after or between pastes. Enter submits a chat
  message or runs a terminal command, Tab moves focus, then Escape, arrows, Backspace.
  This is what *"kb enter"* asks for, and it is new.

Keys are the dangerous kind: a false Enter in a chat box sends the message, and in a
terminal it runs the command. They need the send word's safety rules, not the shape table's
"unconditional" convention. `CONFIRMED` that the conventions differ; the risk is plain.

### 2.2 Proposed grammar (sketch, v1)

| Say | Does | Kind |
|---|---|---|
| "keyboard enter" (also "kb enter") | presses Enter | key |
| "keyboard tab tab" / "keyboard tab three times" | presses Tab repeatedly | key |
| "keyboard escape", "keyboard backspace", "keyboard up", … | presses that key | key |
| "keyboard number 121.05" (also "kb num …") | types `121.05` | text |
| "keyboard symbol underscore" (also "kb symbol …") | types `_` | text |

- **Whole utterance only in v1**, like the send trigger: the utterance is just the command.
  A trailing key ("… keyboard enter" at the end of dictation) can be admitted later, through
  the same zero-false-hit bar decisions.md uses for new grammar.
- **Numbers**: take the digits Whisper produced. Normalise spoken forms ("one twenty one
  point oh five") deterministically, extending the `_NUMS` idea in `edits.py`. Never let a
  model generate digits.
- **Symbols**: a fixed table. Underscore, hyphen, slash, backslash, at, hash, dollar,
  percent, caret, ampersand, star/asterisk, plus, equals, pipe, tilde, backtick,
  open/close paren, bracket and brace, less/greater than, quote, apostrophe. Mishearings go
  in `_ALIASES` like every other command; phonetic matching through `phonetic.py`.
- **Inject**: split the paste into text segments and key events. `inject.py` already
  sends `INPUT_KEYBOARD` input.

### 2.3 Hearing: trigger word and bias

- **Trigger word.** *"kb"* is two letter names, and B belongs to the classic confusable
  "E-set" (B, D, E, P, T, V sound alike), worse with an accent. *"keyboard"* is a longer,
  common word Whisper knows well. Keep *"kb"* as an alias, and measure both on the accent
  bench before choosing. `PLAUSIBLE` until measured.
- **No standing bias toward command words.** `asr.py` measured it for the send word:
  biasing "boom" on 280 short EdAcc clips decoded **6 of them to exactly "boom"**, a
  whole-utterance match, which is a Send. `large-v3-turbo` did the same, so model quality
  is not the variable. `CONFIRMED`. A standing "keyboard enter" bias would press Enter on
  "UM".
- **Use the constrained re-decode instead**: bias one decode only when the first pass
  produced something phonetically close to "keyboard <key>", then require the grammar to
  match the result.

### 2.4 Acceptance

- `command_bench.py`: recall cases for the corrupted forms, and **zero key routes on the
  580 EdAcc utterances**. A false Enter is a false Send.
- `help.COMMANDS` rows for each example, so `tests/test_help.py` routes them.

---

## 3. Markdown by voice

### 3.1 How other dictation tools know the formatting

- **Classic dictation** (Dragon, Windows and macOS voice typing): the speaker says the
  formatting ("new paragraph", "bullet"). Fixed commands, the same kind as Flow's.
- **AI dictation** (Wispr Flow and similar): a language model rewrites the transcript,
  guessing the structure from the words and from the app in front. It costs a model call
  per dictation and can change words. `PLAUSIBLE`, from public descriptions, not measured.

Markdown is the easiest formatting target Flow could have: it is plain characters, so it
pastes into any app with no rich-text clipboard handling.

### 3.2 Proposed rows (line start only)

| Say | Pastes |
|---|---|
| "heading one / two / three release plan" | `# Release plan` / `##` / `###` |
| "dash ship the fix" (already works) | `- ship the fix` |
| "checkbox write tests" | `- [ ] write tests` |
| "numbered write tests" | `1. write tests` (Markdown renumbers `1.` items when it renders) |
| "quote …" | `> …` |
| "code block" | ```` ``` ```` on its own line |
| "new paragraph" (already works) | a blank line |

- **Line start only, or after a lead-in.** The shape table is unconditional and is kept
  small on purpose, and "heading", "quote" and "code" occur in ordinary sentences far more
  than "semicolon" does. `command_bench.py` must show zero false hits on the 580 EdAcc
  utterances before a row ships.
- **"bullet point" stays with `_SEMANTIC`** (the rewrite route), which is why the bullet
  row is "dash".
- **Inline bold, italic and code spans are deferred.** Paired markers ("bold … end bold")
  are fragile by voice.
- **Optional app gating.** `inject.py` can identify the program in front, so the Markdown
  rows could be limited to Markdown places (Obsidian, VS Code). The trade-off is behaviour
  that differs by app against fewer false triggers everywhere else. A taste call.

### 3.3 One rule for this and the open NEEDS_YOU entry

NEEDS_YOU's *"Spoken punctuation eats five ordinary words"* asks whether "tab", "period",
"dash", "colon" and "comma" should need a lead-in ("press", "then"). The Markdown rows and
the keyboard commands raise the same question for more words. One rule would settle all
three:

> Words that are also ordinary English need a lead-in ("press", "then", "keyboard") or
> line-start position. Marks that are only ever marks ("question mark", "full stop",
> "newline", "press enter") stay bare.

### 3.4 Asked-for and automatic structure

- **Asked for** ("format it as a checklist", "turn it into a table"): exists, through the
  agent CLI at ~7 s.
- **Automatic** (Flow guessing a list nobody asked for): the Wispr Flow approach. It needs
  a model on every dictation, and the agent CLI is too slow for that, so it would be a local
  model. It must also pass a guard: strip the Markdown from the output and require the
  words to equal the transcript, or paste the plain text. That lets it add structure but
  never change what was said. `SPECULATIVE`. Not for v1.

---

## 4. If something gets trained: Whisper, not an intent model

An intent model on the transcript cannot recover a word Whisper did not produce, and the
grammar beats it on exactness, latency and dependencies. The model that decides P3 is the
recogniser.

- **What**: LoRA fine-tune of `small.en` (`FINAL_MODEL` in [flow/asr.py:44](../flow/asr.py)).
- **Data**: the speaker's own recordings of commands inside ordinary sentences, extra
  voices from Piper for variety, and ordinary dictation in the mix so it does not forget
  general English. **Keep EdAcc out of training**: it is the benchmark.
- **Cost**: hours on a 24 GB card such as an RTX 3090, not days. `PLAUSIBLE`.
- **Shipping**: merge the adapter, convert with `ct2-transformers-converter`, and
  faster-whisper loads the directory like a stock model. No new dependency. Whether Flow's
  model management can point at a custom model directory is an open question.
- **Checks**: accent-bench WER must not regress, `command_bench.py`, and the P3 live runs.
  Watch validation loss during training: rising validation loss is how forgetting shows up.

---

## 5. Order of work

1. **Owner decisions** (below).
2. **Keyboard route, v1**: whole-utterance keys, symbols and numbers in `edits.py`; key
   events in `inject.py`; `command_bench.py` cases; `help.COMMANDS` rows.
3. **Markdown line-start rows**, measured the same way.
4. **Constrained re-decode for suspected keyboard near-misses.**
5. **Whisper fine-tune experiment**, on a branch, measured against the accent bench.
6. **Automatic structure experiment**, only after 2–4 land and are measured.

## Open questions for the owner

- [ ] Trigger word: "keyboard", "kb", or both (measure both first)?
- [ ] Keys whole-utterance only in v1, or also trailing?
- [ ] The one lead-in rule in 3.3: adopt it? It also closes the NEEDS_YOU five-words entry.
- [ ] Which Markdown rows ship first?
- [ ] Gate the Markdown rows by app, or keep them the same everywhere?
