# Flow

Local English dictation with a talk-to-it refine loop, and a voice conversation with the
agent CLI you already have. Speak, watch the text build, correct it by voice — then paste
it into whatever has focus, or ask it as a question and hear the answer back.

Windows. English only. Three declared dependencies. No API key.

```bash
uv sync && uv run flow
```

Click the pill to arm it, speak, and the draft floats up above it. Talk to the draft to
correct it, keep talking to add more, then **Send** (pastes) or **Ask** (converse mode).

> Flow is built for developers who speak English as a second language, with a strong
> accent — Spanish, Indian, Russian and Japanese L1 speakers anchor the design and the
> benchmarks. [docs/product.md](docs/product.md) states why, and what that changes.

---

## Contents

- [What it does](#what-it-does) · [Requirements](#requirements) · [Install](#install)
- [Running it](#running-it) — [flags](#flags), [hotkeys](#hotkeys), [the pill](#the-pill-and-the-bubble)
- [Dictate mode](#dictate-mode) · [Talking to the draft](#talking-to-the-draft)
- [Converse mode](#converse-mode-p9) · [Calibration](#calibration-p8) · [Vocabulary](#vocabulary-p4)
- [What Flow stores](#what-flow-stores-on-disk) · [Layout](#layout) · [Development](#development)
- [Known limitations](#known-limitations) · [Measured](#measured) · [Design notes](#design-notes)

## What it does

| | |
|---|---|
| **Live text while you speak** | Partials refresh roughly every second as you talk |
| **Nothing sends itself** | Stopping leaves a held draft, never an automatic send |
| **Correct it by voice** | "change Tuesday to Wednesday" edits the draft in place |
| **Keep talking** | Anything that isn't a correction is appended |
| **Shape it into a prompt** | "make it a proper prompt" restructures dictation via your agent CLI |
| **Ask instead of type** | Converse mode sends the draft to `codex`/`claude` and reads the reply back |
| **Remember the thread** | Send doesn't erase — "follow up" and "bring back my last prompt" both work |
| **Silence stays silent** | Whisper invents words on silence and noise; those are filtered out, and every rejection is shown |
| **Adapts to you** | One 60-second calibration measures your room and your voice instead of guessing |
| **Send** | Pastes into whatever window has focus, without pressing Enter for you |

## Requirements

- Windows 10/11
- [`uv`](https://docs.astral.sh/uv/) (it fetches Python 3.12 and the deps itself)
- A microphone
- Optional: `codex` or `claude` on PATH, already signed in. Needed for semantic rewrites,
  prompt polish and converse mode. Everything else works without them.

**No API key is read, stored or passed anywhere in this codebase.** Semantic rewrites and
converse mode shell out to a CLI you have already authenticated. Nothing leaves the
machine — see [`flow/profile.py`](flow/profile.py), which has no code that could send
anything anywhere.

## Install

```bash
uv sync
```

Downloads ~244 MB of packages (28 distributions, measured) and installs Flow itself into
the venv in editable mode, which is what puts the `flow` command on the path. The two
models are fetched on first use, not at install: `base.en` (141 MiB) drives the live
partials and `small.en` (464 MiB) produces the text that actually gets pasted.

### Slimming it down (optional, ~106 MB)

Two of those packages are unreachable from this app:

| Package | Size | Why it is never used |
|---|---|---|
| `onnxruntime` (+`protobuf`) | 34 MB | Only for faster-whisper's Silero VAD. Flow always passes `vad_filter=False` because it does its own speech gating |
| `av` | 66 MB | Only for decoding audio *files*. Flow feeds numpy arrays from the mic and never calls `decode_audio()` |

```bash
uv run python scripts/slim.py --apply
```

Recorded measurement: **243.5 MB → 137.3 MB**, with the full test suite and a real decode
still passing. `av` is replaced by a small stub because faster-whisper imports it at
package load time; the stub raises a clear error if anything ever does reach for it.

This deliberately breaks a dependency contract, which is why it is opt-in. A future
faster-whisper release could start touching `av` at import time or enable VAD by default.
Nothing is lost either way — `uv sync` rebuilds the full venv, and
`uv run python scripts/slim.py --undo` reinstalls both packages.

## Running it

```bash
uv run flow                  # the installed console script
uv run python -m flow        # identical, and works without installing anything
```

Both are supported and do the same thing. `uv sync` installs the project into the venv in
editable mode, so an edit to `flow/*.py` takes effect on the next run with no reinstall.

Startup prints exactly what it found — which agent CLI, which models, whether a profile
and lexicon exist, which mode Send is in, and which hotkeys actually registered. Those
lines are the first thing to read when something is not working:

```
refine CLI: codex
  (fallbacks: claude)
models: base.en for partials, small.en for finals
profile: room -96.5 dB, margin 18.0 dB, 2 learned pairs
lexicon: none - create C:\Users\you\.flow\lexicon.txt to bias names and jargon
speech: on (converse-mode replies are read aloud; --no-speak to mute)
mode: DICTATE - Send pastes into the focused window (--converse, or ctrl+alt+M, to ask instead)
hotkey  toggle   ctrl+alt+space
hotkey  send     ctrl+alt+enter
hotkey  cancel   ctrl+alt+esc
hotkey  mode     ctrl+alt+M
click the pill to arm | right-click for the menu | esc quits
```

### Flags

| Flag | Effect |
|---|---|
| `--partial-model X` | fast model for live partials (default `base.en`) |
| `--final-model X` | stronger model for the pasted text (default `small.en`) |
| `--model X` | pin BOTH tiers to one model, for a low-memory machine |
| `--lexicon PATH` | personal terms file (default `~/.flow/lexicon.txt`) |
| `--no-lexicon` | ignore that file without deleting it |
| `--device N` | input device index; list them with `scripts/devices.py` |
| `--arm` | start listening immediately, no click needed |
| `--no-paste` | print the draft to stdout instead of pasting it |
| `--no-hotkeys` | skip global hotkey registration |
| `--calibrate` | measure this room and this voice, store the profile, and exit ([P8](#calibration-p8)) |
| `--no-profile` | ignore the stored profile and learn nothing this session |
| `--converse` | start in converse mode: Send asks the agent CLI instead of pasting ([P9](#converse-mode-p9)) |
| `--no-speak` | never read converse-mode replies aloud |

If capture cannot start — no microphone, device held exclusively by another app, a bad
`--device` index — the pill stays slate and the reason appears in a red bubble. It will
not show a green pill that is quietly recording nothing.

### Hotkeys

| Action | Primary | Falls back to |
|---|---|---|
| arm / disarm the mic | `ctrl+alt+space` | `ctrl+shift+space`, `ctrl+alt+\`, `alt+win+space` |
| send the draft | `ctrl+alt+enter` | `ctrl+shift+enter` |
| clear the draft | `ctrl+alt+esc` | `ctrl+shift+esc` |
| dictate ⇄ converse | `ctrl+alt+M` | `ctrl+shift+M` |

Combos already owned by another app fall back automatically, in that order. The startup
log prints which one actually registered, so a dead shortcut is never a silent mystery;
if every alternative for an action is taken, that is printed too.

### The pill and the bubble

Right-click the pill for **Send**, **Converse/Dictate mode**, **Mute/Speak replies**
(only when a speech engine was found), **Clear draft** and **Quit**. Drag it anywhere —
it stays inside the desktop work area. `Esc` quits.

The pill's colour is the state:

| Colour | Meaning |
|---|---|
| slate | idle or disarmed |
| green | listening |
| amber | draft held, waiting on you |
| blue | agent CLI is rewriting |
| violet | agent CLI is answering a question (converse mode) |
| red | something failed (the draft is never lost) |

In converse mode the pill also carries a small **ASK** badge, because "there was no spoken
reply" and "I was never in converse mode" otherwise look identical.

The bubble rises above the pill whenever there is something to show, and carries chips:

| Chip | What it does |
|---|---|
| **Refine** | force the next utterance to be an instruction |
| **Continue** | force the next utterance to be dictation |
| **Was a command** | re-read the last dictation as an instruction (only shown when there is something to re-read) |
| **Send** / **Ask** | hand the draft off — pasted in dictate mode, put to the CLI in converse mode |

Refine and Continue are the escape hatch for when the router guesses wrong. They apply to
the **next** utterance and expire after 30 seconds, so a chip pressed and then forgotten
cannot silently reroute an unrelated sentence a minute later.

Partial text is dimmed and italic: partials come from the faster model and can contain
nonsense at mid-word boundaries, so "not final yet" has to be visible. A converse-mode
reply is rendered in its own colour, because mistaking the model's words for your own is
the one confusion converse mode can create that dictate mode cannot.

## Dictate mode

The default. Send pastes the draft into whatever window has focus, via the clipboard plus
a synthetic `Ctrl+V`.

**Flow never presses Enter for you.** The focused window is classified before the
clipboard is touched — by window class *or* process name — and a draft ending in a newline
has that newline stripped when the target is a terminal. That is the failure worth
preventing, because a trailing newline in a shell does not paste, it *runs*.

Interior newlines are honestly not a guarantee, and Flow says so instead of pretending: a
terminal with bracketed paste (Windows Terminal, mintty, Alacritty, WezTerm, kitty, Hyper,
ConEmu) hands the whole block to the shell as literal text; one without (`cmd.exe`,
`conhost`) runs each line as it arrives. Flow cannot change that from outside — the
terminal adds the bracket markers itself on `Ctrl+V`, so writing them onto the clipboard
would produce a second, literal pair in your text. Pasting multiple lines into a terminal
that does not bracket prints a warning naming the process.

The clipboard is restored about 0.6 s after the paste, so Flow does not permanently own it.

## Talking to the draft

While a draft is held, what you say is routed three ways — and only the third costs a
subprocess:

- **append** — not a correction at all; more dictation
- **local** — a literal correction, applied in microseconds as a string operation
- **semantic** — a genuine rewrite request, handed to the agent CLI

The router decides using the draft as context, so *"Delete key handling is broken"* is
dictated as text while *"delete key handling"* is an instruction — the difference being
whether the target is actually in your draft. When it guesses wrong, **Refine** and
**Continue** force the next utterance either way, and every edit is undoable.

### Local corrections

Applied instantly, no subprocess:

```
change Tuesday to Wednesday        replace the last occurrence
change every Tuesday to Wednesday  every occurrence (also "replace all", "change both")
delete afternoon                   remove a phrase
delete the last two words          or "the last sentence" / "the last line"
delete the bit about the standup   remove the whole sentence that phrase sits in
delete from drop to between        remove a whole range
insert final before report         or "add today after report"
capitalize john                    -> John        (title case)
all caps nasa                      -> NASA        (also "uppercase nasa")
lowercase REPORT                   or "make REPORT lowercase"
new paragraph                      or "new line"
scratch that                       undo (also "never mind", "forget that", "strike that")
```

Three things make this survive an accent:

**Lead-ins are absorbed.** Hesitation and politeness both — *"no, sorry, can you delete
Tuesday"* is the same command as *"delete Tuesday"*. Politeness was the missing half:
a non-native speaker asking a tool to do something reaches for "can you", "could you
please" far more readily than a native speaker barking "delete that".

**Mis-heard verbs are snapped back.** By edit distance, adjacent transposition, suffix
stripping ("deleting" → "delete") and an explicit table of observed mis-hearings
("the lead" → delete, "stop" → swap, "leplace" → replace). A snapped reading is accepted
**only when it produces an edit whose target is really in the draft**, so a guess can
promote a mis-heard command and can never demote your dictation into an edit.

**Targets are matched by sound, not by spelling.** The draft was transcribed from the same
voice moments earlier, so the word you are naming may be spelled differently there.
"Sameer" finds "some ear". Matching is Double Metaphone blended with spelling, thresholded
at 0.82 — swept, not chosen.

Every destructive edit reports the words it removed, and the undo stack still holds them.

### Rewrites via the agent CLI

These take a few seconds and turn the pill blue:

```
make it a proper prompt       restructure dictation into a prompt (request first)
make it more formal
shorten this
turn it into bullet points
fix the grammar
```

`make it a proper prompt` is its own verb rather than free text handed to the model: it
reorders to request → context → constraints, keeps every concrete detail verbatim,
normalises technical numbers where the meaning is certain ("a five hundred" → HTTP 500),
and invents nothing. A reply that balloons is rejected rather than pasted, because that is
the model explaining itself instead of revising.

### When it mishears the *kind* of utterance

If a command gets typed into your draft as text, say **"that was a command"** (or press
the **Was a command** chip). Flow withdraws the append, re-reads those words as an
instruction, and if they still are not one, re-decodes the stored audio biased toward the
command vocabulary and your draft's own words. If nothing works the words go back exactly
where they were — dictation is never the price of a failed guess.

### Continuing a thread

Send does not erase. The prompts you have sent are kept, bounded at 20 turns / 20,000
characters, and two spoken verbs reach them — the only commands that mean anything with an
empty draft, which is exactly the state Send leaves behind:

```
bring back my last prompt      restore it into the draft
follow up: and add a rollback  mark the new draft as a continuation
```

A CLI rewrite sees the thread tail **only** on a follow-up, labelled as background and
explicitly excluded from the output, so an ordinary correction never pays for the context.

## Converse mode (P9)

`ctrl+alt+M`, the right-click menu, or `--converse` at launch. Send becomes **Ask**: the
draft goes to your agent CLI as a question instead of into the focused window, the answer
renders in the bubble in its own colour, and it is read aloud.

Everything before Send is deliberately identical in both modes — the same gate, the same
decode, the same correction grammar shaping the outgoing words. The thing being corrected
is a prompt either way.

- **The answer is added to the thread**, so the next question inherits it. That is what
  makes "and what about the other one?" mean anything.
- **There is no persistent CLI process.** Continuity is re-sent from the thread, not held
  open, so a crashed or upgraded CLI cannot take the conversation with it.
- **Answers are asked to be short** — at most three sentences of plain prose — because the
  reply is read on a floating bubble and spoken aloud, and neither survives an essay.
- **Flow goes deaf while it talks.** The microphone is ignored for as long as a reply is
  playing, because it is hearing the speakers and there is no echo cancellation to tell
  that from your voice. See [Interrupting a reply](#interrupting-a-reply).
- **Failure is non-destructive.** An absent, slow or broken CLI degrades converse mode to
  dictate mode rather than losing what was said.

Spoken replies are **on by default in converse mode** — entering converse mode is the
opt-in, and a conversation you have to read is not the feature. `--no-speak` refuses the
engine at launch; **Mute replies** in the right-click menu toggles it mid-session and cuts
off whatever is mid-sentence.

Speech goes through `System.Speech` in one long-lived PowerShell host, not a subprocess per
reply. That is not an optimisation: a subprocess that has already been launched cannot be
told to stop talking, and PowerShell costs ~700 ms of startup before the first phoneme.
Nothing is installed and nothing leaves the machine.

### Interrupting a reply

Flow will not listen while it is speaking, and that is deliberate. Without it, the
microphone picks up the reply, the speech gate opens on Flow's own voice, and the words it
just spoke are transcribed into your next question — which is exactly what happened the
first time anyone used converse mode for real: the reply *"Yes, we can hear you."* played,
and `Yes.` appeared in the draft.

Separating your voice from the speakers needs acoustic echo cancellation, not a better
voice detector — a VAD, Silero included, would confidently report "this is speech", because
it is. AEC means a dependency, and R16 has no room for one. So the guarantee is half-duplex:
**listen, or talk, not both.**

Three ways to cut a reply short, all explicit:

| Action | Effect |
|---|---|
| `ctrl+alt+esc`, or the **Clear draft** menu item | stops the reply, then clears the draft |
| Click the pill to disarm | stops the reply and stops capturing |
| Right-click → **Mute replies** | stops it and stays silent from then on |

If you use headphones there is no echo to suppress, but Flow cannot tell — the behaviour
is the same either way.

## Calibration (P8)

```bash
uv run flow --calibrate
```

Reads you a passage, listens for 60 seconds, stores what it measured in
`~/.flow/profile.json`, and exits. Three constants in this codebase were tuned on one
machine and one speaker, and each has since been caught being wrong for somebody else:

- **the room.** The gate's starting noise floor is −55 dB. A quiet room with a good USB
  mic measures **−96.7 dB**, which the gate could not descend to, so it never opened at all.
- **the margin.** How far above the floor speech has to rise, which decides whether a soft
  speaker opens the gate.
- **the confidence bar.** `avg_logprob` is not comparable between speakers:
  Spanish-accented English medians −0.62 against −0.27…−0.32 for other groups, so one
  absolute threshold means something different to each of them.

Sixty seconds of reading contains both halves of every comparison — the silence between
your sentences is your room, the sentences are your voice, and decoding a *known* text is
the only honest way to see what your `avg_logprob` looks like when nothing is wrong.

Two design points worth knowing:

**The room/voice split is by the widest gap in the sorted levels, not a percentile.** A
fluent reader pauses for maybe a sixth of the minute, so "the quietest fifth is the room"
lands inside their voice and calibrates the floor to −45 dB.

**Calibration can only ever relax the drop filter, never tighten it.** A speaker whose
clean speech reads −0.19 would otherwise get a stricter bar than the shipped one and start
losing words they never used to lose. Measuring yourself can buy you leniency; it cannot
cost you.

Without a profile Flow works exactly as before, and says so at startup. `--no-profile`
ignores a stored one and learns nothing that session.

## Vocabulary (P4)

Whisper decodes toward what it has seen most, so a name, a repo or a piece of in-house
jargon loses to whatever common word sounds nearest — and it loses harder in an accent.
Two sources bias it back:

**`~/.flow/lexicon.txt`** — one term per line, `#` for comments, re-read whenever it
changes so a name added mid-session lands on the next utterance. Capped at 64 whole terms
(the library silently truncates mid-term at 223 tokens).

**What Flow learned from you** — every "change X to Y" you speak is a confusion pair you
labelled yourself: the model wrote X, you wanted Y. Once a pair recurs, Y joins the decode
bias. Only Y: the wrong reading is what the model already produces unaided, so feeding it
back would bias toward the mistake. These live in the profile, not in your file — the file
stays something you typed and own.

Undo-straight-after-append is also recorded, as the signature of a command read as
dictation. It is **reported**, never applied automatically: changing the alias table
changes what a word means for every future utterance, and "this was a command twice"
cannot establish "this is never dictation".

**Biasing cuts both ways, and the measurement says so loudly.** See
[Known limitations](#known-limitations).

## What Flow stores on disk

| Path | Written by | Contents |
|---|---|---|
| `~/.flow/lexicon.txt` | you, by hand | one term per line. Does not exist until you create it — creating it *is* the opt-in |
| `~/.flow/profile.json` | `--calibrate`, and Send | measured room/voice/confidence, learned confusion pairs, misroute signatures. Plain JSON, readable and deletable by hand |
| `~/.cache/huggingface/hub/` | first decode | the models. `base.en` 141 MiB, `small.en` 464 MiB |
| `.bench/` | `scripts/` | generated benchmark audio and results. Git-ignored, reproducible |

Deleting `~/.flow/profile.json` forgets every inference and nothing else. Nothing here is
ever uploaded.

## Layout

```
flow/
  __main__.py  entry point: parses flags, prints diagnostics, wires the pieces together
  session.py   state machine, threaded decoder, draft + undo, mode, rescue, learning
  edits.py     edit-vs-append routing, verb snapping, and the local string operations
  phonetic.py  vendored Double Metaphone + the span search the router and edits share
  refine.py    agent-CLI adapter: semantic rewrite, prompt polish (P5), converse ask (P9)
  asr.py       faster-whisper in two tiers, behind a two-method interface
  clean.py     rejecting text the model invented rather than heard, with the evidence
  audio.py     mic capture and the speech gate (RMS, adaptive floor, pre-roll)
  calibrate.py first-run measurement of this room and this voice (P8)
  profile.py   what Flow learned about one person, stored locally (P8/P4)
  lexicon.py   the user's own terms, re-read on change, merged with what was learned
  thread.py    what has already been sent, bounded (P6)
  speak.py     spoken replies through one long-lived System.Speech host (P9)
  ui.py        the pill and the draft bubble (tkinter), DPI-aware
  inject.py    clipboard + SendInput, and terminal-safe paste (ctypes, P7)
  hotkey.py    RegisterHotKey on its own message-loop thread (ctypes)
scripts/       benchmarks, probes, the soak test and the self-drive harness
tests/         381 tests: routing, state machine, filters, phonetics, resilience
docs/          what Flow is for, the roadmap, the analysis, the recording kit
```

`tkinter` and `ctypes` are stdlib, which is how the GUI, global hotkeys, text injection,
DPI awareness and speech synthesis all cost zero dependencies.

See [docs/architecture.md](docs/architecture.md) for the runtime data flow, the threads,
the event stream and the tuning constants with the measurements behind them.

## Development

```bash
uv run python -m unittest discover -s tests
```

381 tests, ~4 s, no microphone or model required — the fakes are injectable precisely so
the routing logic, where the subtle bugs live, can be tested without either.

The end-to-end harness is the one that catches what unit tests cannot:

```bash
uv run python scripts/selfdrive.py
```

A Windows SAPI voice speaks each utterance to a WAV; the WAV is fed to a real `Session` as
microphone blocks, through the real gate, the real two-tier decoder, the real router and
the real apply. 29 checks covering dictation, five correction shapes, undo, rescue, send,
converse against the live CLI, a spoken follow-up, the asking-state UI, calibration, the
learning loop and window placement. It found two real defects on its first outings, both
of which every layer-specific harness had missed.

### The scripts

| Script | What it answers |
|---|---|
| `devices.py` | which input devices exist, by index |
| `mic_check.py` | does the real capture path deliver blocks |
| `listen.py` | headless partials-while-speaking, held draft on stop |
| `live_check.py` | a person, a real microphone, this loop — the guided session |
| `selfdrive.py` | does the whole app work, driven by synthesised speech |
| `soak.py` | does a long session drift in memory or latency (R8) |
| `accent_bench.py` | per-accent WER and false-reject rate (P1/P2) |
| `asr_bench.py` | decode latency, and the R4 partial-latency gate |
| `command_bench.py` | does the hardened grammar catch more commands without eating dictation (P3) |
| `rescue_bench.py` | does a biased second decode recover a mis-heard command |
| `lexicon_bench.py` | does biasing actually recover words, and what does it cost (P4) |
| `gate_bench.py` | how much speech does the gate eat, and does pre-roll get it back |
| `guardrail_bench.py` | where a confidence bar on destructive edits would land |
| `hallucination_probe.py` | what the model emits when there is nothing to transcribe |
| `polish_check.py` | does the polish verb keep the facts, and does it fit the budget (P5) |
| `refine_check.py` | end-to-end check of the CLI refine path |
| `inject_check.py` | clipboard and paste-target classification, without side effects |
| `fetch_accent_data.py` | pull per-accent evaluation slices into `.bench/` |
| `ingest_recordings.py` | turn a volunteer's phone recording into scored clips (P3) |
| `tk_probe.py` / `ui_probe.py` | the window attributes the pill depends on; render it |
| `slim.py` | trim the unreachable dependencies |

Benchmark scripts download additional models (`small`, `medium`, `distil-large-v3`) into
the HuggingFace cache — several GB. Only `base.en` and `small.en` are needed to run Flow.

### Building a distributable

```bash
uv build
```

Produces `dist/flow-0.1.0-py3-none-any.whl` and `dist/flow-0.1.0.tar.gz` via `hatchling`.
The wheel carries the 17 `flow/*.py` modules and declares the `flow` console script, so it
installs and runs anywhere with Python 3.12 and a microphone:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv dist/flow-0.1.0-py3-none-any.whl
./.venv/Scripts/flow --help
```

**`hatchling` is a build dependency, not a runtime one** — it is fetched into an isolated
build environment and never enters the venv Flow runs in, so R16's three declared
dependencies are intact. Verified: the runtime venv holds the same 28 distributions it
held before packaging existed, plus `flow` itself.

`scripts/` and `tests/` are deliberately outside the wheel. They are development tools that
want the repo — the benchmarks read `.bench/`, and the self-drive harness shells out.

**There is still no installer.** No MSI, no frozen `.exe`, no code signing, no auto-update.
A user needs `uv` and Python. That is a real gap for non-developer users and it is not
started; the wheel is the unit of distribution today.

## Known limitations

- **Partials refresh about once a second, not per word.** Decode has a ~0.8 s floor on
  CPU, so text arrives in bursts. Wispr Flow feels smoother here.
- **Partials can contain nonsense** at mid-word boundaries. They are shown dimmed and
  are always replaced by the final text.
- **Partials and finals disagree**, because they come from different models — the text
  visibly rewrites itself when an utterance ends. That is the price of the split; see
  the R4 gate in [docs/roadmap.md](docs/roadmap.md) for why one model cannot do both.
- **Elevated windows reject the paste** (Windows UIPI). The draft is put on the
  clipboard first, so `Ctrl+V` by hand still works.
- **Semantic rewrites take ~6 s**, and a converse-mode answer ~8-10 s — the cost of
  starting an agent CLI. This is why only genuine rewrites and questions use one.
- **Accuracy on your own voice is still unmeasured.** The per-accent numbers in
  [docs/roadmap.md](docs/roadmap.md) come from recordings of other people, and the SAPI
  numbers are synthesised. Try `scripts/listen.py` or `scripts/live_check.py`.
- **Voice corrections have to be phrased as commands, and that is a real limitation.**
  *"delete the bit about the standup"* works; *"I feel that it should not contain the
  summary from the stand-up"* is appended to your draft as text. The first recording from
  an Indian-L1 speaker phrased **every** correction the second way, and **0 of 10** were
  recognised — against 7 of 12 local edits for a speaker who read the prompts as written.
  The cause is register rather than accent, and it is unfixed. Until it is, **Refine**
  forces the next utterance to be treated as an instruction. See
  [docs/roadmap.md](docs/roadmap.md#the-first-anchor-group-recording-and-what-it-found-2026-08-01).
- **A personal lexicon cuts both ways.** `~/.flow/lexicon.txt` biases decoding toward your
  names and jargon. Measured on EdAcc with `small.en`: it recovers **27-34%** of the rare
  words the model otherwise missed *when they are actually spoken*, and makes WER
  **14-38% relatively worse** on speech containing none of the terms — 0.201 to 0.278 with
  only eight irrelevant terms. The harm did not scale down with size, so there is no safe
  small-lexicon recommendation. The file therefore does not exist until you create it. Add
  terms you say often, not every term you know.
- **~450 MB resident with both models loaded** (181 MB with only the partial tier).
  An idle session releases both after 5 minutes. `--model base.en` pins one tier if memory
  is tight.
- **~848 MB installed**, or ~742 MB after `scripts/slim.py --apply`. The floor is
  `ctranslate2` (60 MB), numpy (42 MB) and the two models (141 + 464 MiB, measured).
- **Speaking for more than 24 s without a pause can split a word.** Whisper decodes
  inside a single 30 s window, so an utterance is cut and committed before that boundary
  to keep latency flat. The cut lands on an audio block, not on a word, so continuous
  speech past 24 s can produce `think` + `ing`. Any natural pause resets the timer, so
  this needs genuinely unbroken speech to hit.
- **Spanish read-register accuracy is closed as unmeasurable.** No obtainable corpus
  contains it; the only route left is a volunteer recording. See
  [docs/recording-kit.md](docs/recording-kit.md).
- **Windows only.** The GUI is tkinter and portable, but hotkeys, paste, DPI awareness and
  speech are all Win32 via ctypes.

## Measured

Windows 11, CPU-only, int8, 1280x720 RDP session. Latency figures are `base.en`
(the partial tier); accuracy figures are in [docs/roadmap.md](docs/roadmap.md).

Verified on this machine while writing this document:

| | |
|---|---|
| Test suite | **381 tests, 4.2 s**, no mic or model needed |
| End-to-end | `scripts/selfdrive.py`, **29/29 checks**, live CLI round trip |
| Build | `uv build` → wheel + sdist; wheel installs into a clean venv and its `flow` command runs |
| Dependencies | 3 declared, **28 installed**, 243.9 MB venv |
| Models on disk | `base.en` 147.8 MB, `small.en` 486.1 MB (141 / 464 MiB) |
| Agent CLIs found | `codex`, then `claude` as fallback |
| Speech engine | `System.Speech` available |
| Hotkeys | 4 actions, each with 1-3 fallback combos |

Recorded in [PROGRESS.md](PROGRESS.md) from earlier runs, not re-measured here:

|                                                     |                                                               |
| --------------------------------------------------- | ------------------------------------------------------------- |
| Cold start                                          | ~1.4 s (0.40 s import + 0.98 s model load)                    |
| Decode, 1 s of audio                                | 0.75 s                                                        |
| Decode, 8 s of audio                                | 0.91 s — nearly flat, because Whisper pads to one 30 s window |
| Partial decode, worst of 6 accents, 1-8 s of speech | 0.79-1.07 s (R4 budget 1.5 s)                                 |
| Final decode, `small.en`, full 10-20 s utterance    | 3.65 s median, 4.87 s worst                                   |
| Semantic rewrite via `codex`                        | ~5.7 s, ~19.7 k tokens                                        |
| Prompt polish                                       | 5.3 s median, 15/15 detail tokens retained, 0/5 preambles     |
| Converse round trip                                 | 10.4 s first answer, 7.8 s follow-up                          |
| Long session, warm baseline                         | RSS −3.6 MB over 6.5 min; decode latency +3 ms (+0.3%)        |
| Resident memory                                     | 181 MB one tier, 450 MB both, 100 MB after idle unload        |
| Calibration on this machine                         | room −96.5 dB, voice −39.9 dB, gap 56.6 dB, confidence −0.193 |

Accuracy numbers are deliberately absent from this table: the only ones measured on this
machine come from synthesised speech, where WER was 0.000, and that says more about the
test audio than about a real microphone. The real ones, on recordings of accented
speakers, are in [docs/roadmap.md](docs/roadmap.md) with their denominators.

## Design notes

[docs/product.md](docs/product.md) defines what Flow is for — the target user
(developers speaking accented English), the P1-P9 product requirements, and the
non-goals. [docs/architecture.md](docs/architecture.md) is the runtime reference: data
flow, threads, the event stream, the routing table and the tuning constants.
[docs/roadmap.md](docs/roadmap.md) maps the gap between the product definition and this
build, with the accent benchmark that measures it.
[docs/analysis.md](docs/analysis.md) has the requirements breakdown, the four
architectures considered, and the ranked risks with measurements.
[docs/recording-kit.md](docs/recording-kit.md) is what gets sent to a volunteer recording
accented commands. [PROGRESS.md](PROGRESS.md) is the build log, including the things that
broke.
