# Flow

Local English dictation with a talk-to-it refine loop, and a prompt workshop against the
agent CLI you already have. Speak, watch the text build, correct it by voice — then paste
it into the window you were working in, or work the prompt over with the CLI first and
paste the version you settled on.

Windows. English only. Three declared dependencies. No API key.

```bash
uv tool install git+https://github.com/samartomar/flow
flow
```

No Python on the machine? Take
[`flow-windows-x64.zip`](https://github.com/samartomar/flow/releases/latest/download/flow-windows-x64.zip)
instead — that link always serves the newest release — or browse
[Releases](https://github.com/samartomar/flow/releases). [Install](#install) has both, and
the clone.

Click the pill to arm it, speak, and the draft floats up above it. Talk to the draft to
correct it, keep talking to add more, type into it when that is faster, then **Send**
(pastes) or **Ask** (converse mode).

> Flow is built for developers who speak English as a second language, with a strong
> accent — Spanish, Indian, Russian and Japanese L1 speakers anchor the design and the
> benchmarks. [docs/product.md](docs/product.md) states why, and what that changes.

---

## Contents

- [What it does](#what-it-does) · [Install](#install) · [Requirements](#requirements)
- [Running it](#running-it) — [flags](#flags), [hotkeys](#hotkeys), [the pill](#the-pill-and-the-bubble)
- [Dictate mode](#dictate-mode) — [saying the send](#sending-it-without-touching-anything) · [Talking to the draft](#talking-to-the-draft)
- [Converse mode](#converse-mode-p9) — [the workspace](#where-the-question-is-asked-from), [taking the answer](#taking-the-answer)
- [Calibration](#calibration-p8) · [Vocabulary](#vocabulary-p4)
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
| **Work the prompt over** | Converse mode puts the draft to `codex`/`claude` as a prompt to improve, reads the reply back, and **Use this** makes that reply the draft |
| **Fix it by hand** | The **Edit** chip turns the draft into a text box; the mic stands down while you type |
| **Say the send** | "boom" pastes, "enter boom" pastes and presses Enter — whole utterance only |
| **Remember the thread** | Send doesn't erase — "follow up", "follow and …", and "bring back my last prompt" all work |
| **Silence stays silent** | Whisper invents words on silence and noise; those are filtered out, and every rejection is shown |
| **Adapts to you** | One 60-second calibration measures your room and your voice instead of guessing |
| **Send** | Pastes into the window you were working in, and presses Enter only if you asked for it |

## Install

**Windows 10/11 only.** The paste and hotkey layer is 96 Win32 call sites and the timing
behaviour around them was measured on Windows, so a macOS port means re-taking those
measurements rather than swapping a few calls — it waits for Mac users asking and Mac
hardware to measure on. Run Flow on anything else and it says so in one sentence and
exits, rather than throwing a `ctypes` traceback at you.

### With `uv` — nothing to clone

```bash
uv tool install git+https://github.com/samartomar/flow
flow
```

[`uv`](https://docs.astral.sh/uv/) is a single static binary; it fetches Python 3.12 and
the three dependencies itself, and `uv tool install` puts `flow` on your PATH (run
`uv tool update-shell` once if your shell has never seen uv's bin directory).
`uv tool upgrade flow` takes a newer version, `uv tool uninstall flow` removes it.

### Without Python at all — the binary

Download
[`flow-windows-x64.zip`](https://github.com/samartomar/flow/releases/latest/download/flow-windows-x64.zip),
unzip it anywhere, and run `flow.exe`. That URL is version-free on purpose: the asset name
never changes, so the link serves whatever release is newest and no cached page can hand
you a stale zip. [Releases](https://github.com/samartomar/flow/releases) is there to browse
the notes and older builds. Nothing to install and no Python on the machine. **126 MB zipped, 323 MB
unpacked** (measured on the v0.2.0 asset itself, downloaded from the link above). The two speech models are *not* in the zip —
they download to your Hugging Face cache on the first decode, exactly as they do for
every other install, and the startup line names the path. Bundling them would have made
this a 730 MB download and frozen two files `--model` is meant to swap.

The download is **unsigned**, and the honest version of that is telling you what you will
see rather than letting it look like a virus alert: the first launch shows Windows
SmartScreen's "Windows protected your PC" panel, and it takes **More info → Run anyway**,
once, per machine. A code-signing certificate is a yearly subscription, so it waits for
someone who actually needs it; when that happens, this paragraph is what changes. The zip
is built by GitHub Actions from a tagged commit, and the workflow runs the full test
suite before it builds — a release that skips the gate is not a release.

### From a clone — to change it

```bash
uv sync && uv run flow
```

Downloads ~244 MB of packages (28 distributions, measured) and installs Flow itself into
the venv in editable mode, which is what puts the `flow` command on the path. The two
models are fetched on first use, not at install: `base.en` (141 MiB) drives the live
partials and `small.en` (464 MiB) produces the text that actually gets pasted.

### The agent CLI is optional, and Flow says which it found

Dictation, voice corrections, the lexicon, calibration and paste need nothing but Flow.
An agent CLI — `codex` or `claude` on PATH, already signed in — adds the three things the
local grammar cannot do: semantic rewrites, the "make it a proper prompt" polish, and
converse mode's prompt workshop. With neither installed, startup prints `refine CLI: NONE
- semantic rewrites disabled` and everything else works; you find out at the top rather
than at the moment you first ask for a rewrite. No API key is read, stored or passed
anywhere in this codebase — see [Requirements](#requirements) for exactly what a CLI call
does and does not send.

**Install the native build, not `npm -g`.** A `.cmd` launcher — what a global npm install
writes on Windows — passes its arguments through `cmd.exe`, which stops at the first
newline, and every prompt Flow sends is multi-line: the CLI would receive the framing,
none of your words, and answer confidently about nothing. Flow refuses a CLI that resolves
to a `.cmd` or `.bat` before it starts anything, and says so with the cure in the message.

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

## Requirements

- Windows 10/11
- [`uv`](https://docs.astral.sh/uv/) (it fetches Python 3.12 and the deps itself)
- A microphone
- Optional: `codex` or `claude` on PATH, already signed in. Needed for semantic rewrites,
  prompt polish and converse mode. Everything else works without them.

**No API key is read, stored or passed anywhere in this codebase.** Semantic rewrites and
converse mode shell out to a CLI you have already authenticated.

That is a *process* boundary, not a data one, and the difference is worth being exact
about: `codex` and `claude` are cloud-backed, so starting a local executable is not the
same as staying local. Audio, the utterance buffers, the lexicon, the profile, every local
edit and the spoken replies never leave. What does leave is what you hand to the CLI — the
draft tail on a rewrite; the question, the thread tail and the workshop preamble on an
Ask. That preamble names your workspace, so **a filesystem path leaves the machine along
with the words**, and a project path can identify an employer, a client or a codebase. Set
no workspace and nothing of the kind is sent. Send also puts the draft on the Windows
clipboard, where any clipboard manager or cloud-clipboard sync you run will see it.

### When a CLI is slow or stuck

`codex` is tried first and `claude` is the fallback — and the fallback is real: if the
first one fails to start, exits non-zero, returns nothing, or **times out**, the next one
gets the same prompt. A CLI that answers *badly* has still answered, so that case is left
to the output guards rather than paying for a second call.

The cost of a fallback is the first one's whole timeout before the second even starts, so
if you already know which CLI is answering today, pin it:

```bash
uv run flow --cli claude
```

or pick it mid-session from **Agent CLI** in the right-click menu — the current choice is
marked, and **Automatic** puts the fallback back. A pinned CLI is a decision and is never
second-guessed, so it does not fall through.

Everything that names a provider reads the pin: the converse marker on the pill, the note
when you switch modes, and the notes before a rewrite and before a question. What is on
screen is the CLI that will be called, not the first one on PATH.

`--cli-timeout SEC` raises the 20 s budget. It was chosen when a call measured 5.7–7.3 s;
`codex` now measures 6.6–8.5 s here for a one-word answer, so a long question can breach
it.

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
  (falls back to claude if it fails)
CLI timeout: 20s per call
models: base.en for partials, small.en for finals
profile: room -96.5 dB, margin 18.0 dB, 2 learned pairs
trace: C:\Users\you\.flow\diag.jsonl (timings and state only, no words; --no-profile to disable)
lexicon: none - right-click > Open settings folder, or create C:\Users\you\.flow\lexicon.txt, to add names and corrections
speech: on, voice Microsoft Susan (9 installed; --voice, or the right-click menu, to change)
workshop: not set - Ask runs without a project
mode: DICTATE - Send pastes into the focused window (--converse, or ctrl+alt+M, to ask instead)
hotkey  toggle   ctrl+alt+space
hotkey  send     ctrl+alt+enter
hotkey  cancel   ctrl+alt+esc
hotkey  mode     ctrl+alt+M
hotkey  quit     ctrl+alt+Q
click the pill to arm | right-click for the menu | ctrl+alt+Q quits
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
| `--voice X` | voice for spoken replies: a name, part of one, or `male`/`female` |
| `--no-auto-ask` | in converse mode, wait for the Ask button instead of a pause |
| `--cli NAME` | pin the agent CLI (`codex` or `claude`) instead of trying each in turn |
| `--cli-timeout SEC` | how long to wait for one CLI call (default 20) |
| `--cwd PATH` | the project converse-mode questions are asked from; overrides the stored `workspace` ([P9](#converse-mode-p9)) |

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
| quit | `ctrl+alt+Q` | `ctrl+shift+Q` |

Combos already owned by another app fall back automatically, in that order. The startup
log prints which one actually registered, so a dead shortcut is never a silent mystery;
if every alternative for an action is taken, that is printed too. **Right-click ▸ Help ▸
Commands & shortcuts** answers the same question after the log has scrolled away: a
read-only window listing the combos that registered on your machine this launch — not the
primaries in the table above — along with your trigger words and one example of every
command. It is regenerated every time you open it, so it is never describing a machine you
are not sitting at. Scroll it with the wheel or by dragging the page; the Close chip shuts
it. It never takes the focus from whatever you were typing in.

Quit used to be `Esc`, and `Esc` was a Tk key binding on the pill. The pill does not take
keyboard focus any more — that is what makes Send land in the window you were working in
— so that binding could never fire again, and a documented shortcut that silently does
nothing is worse than no shortcut. It is a global hotkey now, like the rest.

### The pill and the bubble

Right-click the pill for **Send**, **Converse/Dictate mode**, **Clear draft** and
**Quit**, plus any corrections Flow is offering. Everything you set once — **Trigger
word**, **Agent CLI**, **Voice**, **Mute/Speak replies** (only when a speech engine was
found), the auto-ask toggle and **Open settings folder** — lives under **Settings ▸**, and
**Help ▸** has the command sheet and this guide. Drag the pill anywhere — it stays inside
the desktop work area.

**Neither window takes the focus while you are dictating.** Both carry
`WS_EX_NOACTIVATE`, so clicking the pill, dragging it, or pressing Send leaves the
foreground exactly where it was — in the editor or terminal you are dictating into. Two
things borrow it deliberately and give it back: the right-click menu, because a Windows
popup menu only receives input while its owner is in front and otherwise posts and never
closes; and the hand editor, because a text box you cannot type into is not one. Both are
reached by clicking, which is what lets Windows grant the foreground at all.

The pill's colour is the state:

| Colour | Meaning |
|---|---|
| slate | idle or disarmed |
| green | listening |
| amber | draft held, waiting on you |
| blue | agent CLI is rewriting |
| violet | agent CLI is answering a question (converse mode) |
| red | something failed (the draft is never lost) |

In converse mode the pill also carries a standing **converse marker** under the mic glyph,
because "there was no spoken reply" and "I was never in converse mode" otherwise look
identical. The marker reads `codex` or `claude` — the name of the CLI that would answer,
pin included — and falls back to **ASK** when none is on PATH, since naming a provider
that is not there is worse than naming the mode. A longer name than those two also falls
back to **ASK**: the slot sits beside the level bars, and a clipped name reads as a
different CLI.

The eighteen bars are the answer to "am I being heard". They move with your voice while
Flow is listening and drop to a **flat line** the moment it stops listening — which
happens exactly once, while a converse-mode reply is playing, because there is no echo
cancellation here and Flow cannot tell your voice from its own coming back through the
speakers. A flat line, not an empty box: the meter is still running, it just has nothing
honest to report.

The bubble rises above the pill whenever there is something to show. Above the buttons it
carries **one line saying what Flow is doing**, with three marching dots when the wait has
no knowable length:

| Indicator | What is happening | Can it hear you? |
|---|---|---|
| — (bars moving) | listening | yes |
| ⋯ `loading the model` | first decode of a tier, about a second | yes |
| ⋯ `decoding` | you stopped talking and the model is working | yes |
| — (`Ask 4s` on the button) | draft held, counting down to the question | yes |
| ⋯ `refining` | the agent CLI is rewriting the draft, about 6 s | yes |
| ⋯ `asking` | the agent CLI is answering, about 8–10 s | yes |
| ▬ `speaking - not listening` | the reply is playing | **no** |
| ▬ `editing - not listening` | the draft is open in the hand editor | **no** |

Only the last two mean *stop talking*; the rest mean *wait a moment*. That is why they are
drawn as a flat line rather than dots, and why the bars on the pill go flat at the same
instant — the same fact, in the two places you are already looking. The two deafnesses are
named apart because only one of them is your own doing: told "not listening" with no
reason, somebody typing would read it as a fault. If a wait starts when
there is nothing else on screen, the bubble comes up to carry it and goes away again when
the wait ends.

The chips:

| Chip | What it does |
|---|---|
| **Refine** | force the next utterance to be an instruction |
| **Continue** | force the next utterance to be dictation |
| **Was a command** | re-read the last dictation as an instruction (only shown when there is something to re-read) |
| **Edit** | open the draft in a text box and type (only shown when there is a draft) |
| **Done** / **Cancel** | keep what you typed, or throw it away — the only two chips while the editor is open |
| **Use this** | make the answer on screen the draft (converse mode, once there is a reply) |
| **Send** / **Ask** | hand the draft off — pasted in dictate mode, put to the CLI in converse mode |
| **Put it back** | return the words a Send just took (shown on the sent card, for 4 s) |

Refine and Continue are the escape hatch for when the router guesses wrong. They apply to
the **next** utterance and expire after 30 seconds, so a chip pressed and then forgotten
cannot silently reroute an unrelated sentence a minute later.

After a Send in dictate mode the bubble does not vanish. It holds what was just sent for
four seconds, dimmed, under a **sent** label, with a **Put it back** chip counting down —
so a Send that went somewhere unexpected costs one click rather than the whole utterance.
The words are in the thread either way and *"bring back my last prompt"* still works long
afterwards; the chip is there because a mis-aimed Send and a good one used to leave
exactly the same empty screen behind.

### Editing the draft by hand

Some things are faster to type than to say — a URL, a flag, one wrong character in the
middle of a word. **Edit** turns the draft into a real text box in the bubble, and
**Done** or **Cancel** closes it. `Esc` cancels and `Ctrl+Enter` keeps; a bare `Enter`
inserts a newline rather than committing, because the thing being edited is a prompt and
prompts have paragraphs.

**The microphone stands down for as long as the editor is open**, and says so —
`editing - not listening` on the bubble, flat bars on the pill, and a note when it starts
and when it ends. Without that, whatever the room said while you were typing would be
appended to the very text you were typing. The auto-ask countdown is held for the same
reason.

This is the one window that deliberately takes the focus, and the guarantees around Send
survive it: Flow only ever remembers a foreground window that is *not* its own, so a Send
after an edit still aims at the window you were dictating into, and a paste that would
land in Flow itself is refused and says so. Windows can decline to hand over the
foreground; when it does, the editor closes itself and tells you, rather than leaving a
cursor blinking in a box while the keystrokes go somewhere else.

An edit that lands on top of words dictated while the editor was open says so too, and
those words are on the undo stack — displaced is not lost.

Partial text is dimmed and italic: partials come from the faster model and can contain
nonsense at mid-word boundaries, so "not final yet" has to be visible. A converse-mode
reply is rendered in its own colour, because mistaking the model's words for your own is
the one confusion converse mode can create that dictate mode cannot.

## Dictate mode

The default. Send pastes the draft into the window you were working in, via the clipboard
plus a synthetic `Ctrl+V`.

**The window you were working in**, and not "whatever has focus at the time", which is
what this used to say and used to do. Pressing Send is a click, and a click can move the
focus; asking the OS what has focus *after* it is a question with the wrong answer. Flow
polls the foreground every 30 ms, keeps the last one that was not its own window, and
hands that to the paste explicitly. If the paste is somehow still aimed at Flow itself,
it refuses and says so rather than pretending — a Ctrl+V into Flow's own canvas does
nothing at all, and that is a bug to report, not a paste to attempt.

**Flow never presses Enter unless you asked for it by name.** The target window is
classified before the clipboard is touched — by window class *or* process name — and a
draft ending in a newline has that newline stripped when the target is a terminal. That
is the failure worth preventing, because a trailing newline in a shell does not paste, it
*runs*. The one Enter Flow will send is the one spoken as `enter boom` below, and it goes
after the paste, into the window that just accepted the text.

Interior newlines are honestly not a guarantee, and Flow says so instead of pretending: a
terminal with bracketed paste (Windows Terminal, mintty, Alacritty, WezTerm, kitty, Hyper,
ConEmu) hands the whole block to the shell as literal text; one without (`cmd.exe`,
`conhost`) runs each line as it arrives. Flow cannot change that from outside — the
terminal adds the bracket markers itself on `Ctrl+V`, so writing them onto the clipboard
would produce a second, literal pair in your text. Pasting multiple lines into a terminal
that does not bracket prints a warning naming the process — in the bubble, on the card
that holds what was just sent, so it is somewhere you are already looking.

The clipboard is restored about 0.6 s after the paste, so Flow does not permanently own it.

### Sending it without touching anything

Two words press Send, so the last step of the loop does not need the mouse:

```
boom             paste the draft into the window you were working in
enter boom       paste it and press Enter
```

**Only as the whole utterance.** "boom goes the dynamite" is dictation; a false fire needs
you to have said nothing else. Measured against the 580 real accented utterances in the
EdAcc slice, **none of them fires either trigger**. And the pair degrades the safe way: a
decode that drops a word from "enter boom" leaves "enter" (nothing happens) or "boom"
(pastes without submitting), never the other direction.

They press the same button the chip does, refusals included — an empty draft, a rewrite
still out, a paste that would land in Flow itself all behave exactly as they do for a
click. In converse mode `boom` asks the question and the `enter` half says it has nothing
to submit rather than quietly doing nothing.

Both words are stored in `profile.json` as `send_word` and `send_enter_word`, and both
have shipped defaults that work out of the box. Recorded risk: "boom" is a short plosive
and may decode as something else in a strong accent — a `wrong -> right` line in your
lexicon repairs a consistent bend, and if it will not decode at your desk it is a word
worth changing rather than living with.

**Changing it is a tap: right-click ▸ Settings ▸ Trigger word.** The list is short and
closed on purpose — `boom`, `tango`, `mango`, `falcon`, `rocket`, `banana` — and
every word on it has been through the same measurement `boom` passed: zero hits as a whole
utterance across those 580 real utterances, no movement in the command benchmark's
adversarial or recall numbers, and no meaning of its own in the grammar. That last one is
why the list is not longer: "undo" clears the first two checks and would have taken your
undo away. The `enter` variant is derived for you, in the order that degrades safely. For
a word that is nobody's business but yours, `profile.json` still takes anything — and
**Help ▸ Commands & shortcuts** shows whatever is currently set.

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
bring back my last prompt        restore it into the draft
follow up: and add a rollback    mark the new draft as a continuation
follow and mention the rollback  the same thing, with the "up" swallowed
```

That third line is an elision rather than a new verb. Said quickly, the unstressed "up"
between two stressed words disappears, and the first live run lost it — so **"follow
and …"** is read as a follow-up. Bare **"follow"** on its own is still dictation, and so
is "follow the instructions": the form only counts when "and" comes straight after.
Priced before it was admitted — across 580 real accented utterances it changes **nothing**.

A CLI rewrite sees the thread tail **only** on a follow-up, labelled as background and
explicitly excluded from the output, so an ordinary correction never pays for the context.

## Converse mode (P9)

`ctrl+alt+M`, the right-click menu, or `--converse` at launch. Send becomes **Ask**: the
draft goes to your agent CLI instead of into the focused window, the answer renders in the
bubble in its own colour, and it is read aloud.

**It is a prompt workshop, not a general chat.** Every question carries a preamble saying
so — the CLI is helping you refine the prompt you just dictated, which you are about to
hand to an agentic coding CLI, and it is asked to discuss what the prompt leaves
ambiguous, what context it is missing and what it should say instead, rather than to carry
the task out. That framing is the feature. Without it the CLI answers as a general
assistant, and a general assistant with no internet access is a worse one than the browser
you already have open.

Everything before Send is deliberately identical in both modes — the same gate, the same
decode, the same correction grammar shaping the outgoing words. The thing being corrected
is a prompt either way.

- **The answer is added to the thread**, so the next question inherits it. That is what
  makes "and what about the other one?" mean anything.
- **There is no persistent CLI process.** Continuity is re-sent from the thread, not held
  open, so a crashed or upgraded CLI cannot take the conversation with it.
- **Answers are asked to be short** — at most three sentences of plain prose — because the
  reply is read on a floating bubble and spoken aloud, and neither survives an essay. The
  exception is asking for a piece of *work*: "give me a prompt for…", a plan, a list. Then
  the ceiling comes off, because truncating the thing the conversation was for is the one
  failure worse than a tall bubble. Which brief applies is decided from your request,
  never from the answer.
- **A pause sends the question.** Stop talking for 4 seconds and the draft goes on its
  own — see [Asking without pressing anything](#asking-without-pressing-anything).
- **Flow goes deaf while it talks, and says so.** The microphone is ignored for as long as
  a reply is playing, because it is hearing the speakers and there is no echo cancellation
  to tell that from your voice. The pill's bars go flat and the bubble says
  `speaking - not listening`, so the one state where talking is wasted breath is the one
  state that announces itself. See [Interrupting a reply](#interrupting-a-reply).
- **Failure is non-destructive.** An absent, slow or broken CLI degrades converse mode to
  dictate mode rather than losing what was said.

### Where the question is asked from

Advice about *your* project beats advice about nothing, so converse mode is grounded in a
working directory:

```bash
uv run flow --cwd D:\dev\yourproject
```

The flag wins, then the `workspace` field in `~/.flow/profile.json`, then nothing — the
same order `--voice` follows. The CLI is run there, and the preamble names the path, so
the answer can assume the prompt will be run in that project.

The cost is stated rather than hidden: a workspace set today goes stale silently when the
project moves, and Flow cannot tell. The mitigation is visibility, so it is said out loud
in two places — at startup, and every time you switch into converse mode:

```
workshop: D:\dev\yourproject
workshop: not set - Ask runs without a project
workshop: D:\dev\oldpath no longer exists - Ask runs without a project
```

A path that has gone is reported and then ignored. A startup that refused over a stale
setting would be worse than an ungrounded question — the project moved, and Flow is not
the thing that should stop working.

### Taking the answer

The loop is: dictate a rough prompt, work it over with the CLI, then send the version you
settled on to your terminal. That last step used to mean re-typing it — Send hands over
the *draft*, and the version you wanted was in the *reply*. Two ways across:

| | |
|---|---|
| the **Use this** chip | one click, and it cannot be misheard |
| *"use that answer"* | also "use that reply", "take that answer", "keep that response" — whole utterance only, so "use that answer in the summary" stays dictation |

It **replaces** the draft rather than appending to it: an answer is a whole thing, and
gluing it onto a half-written question makes a third thing nobody asked for. One undo
brings your text back, and the note names what was displaced.

Taking an answer **flips back to dictate mode**, and says so, because it changes what the
button under your cursor does. Staying in converse would make the next Send re-ask Flow's
own answer back at the CLI, which is the confusion this verb exists to remove.

### Hearing the reply

Spoken replies are **on by default in converse mode** — entering converse mode is the
opt-in, and a conversation you have to read is not the feature. `--no-speak` refuses the
engine at launch; **Mute replies** in the right-click menu toggles it mid-session and cuts
off whatever is mid-sentence.

Speech goes through `System.Speech` in one long-lived PowerShell host, not a subprocess per
reply. That is not an optimisation: a subprocess that has already been launched cannot be
told to stop talking, and PowerShell costs ~700 ms of startup before the first phoneme.
Nothing is installed and nothing leaves the machine.

### Choosing the voice

Flow used to speak in whatever voice the engine defaulted to, which was never chosen by
anyone — on the development machine, the oldest voice installed. Pick one instead:

```bash
uv run python scripts/voices.py --speak      # hear each installed voice in turn
uv run flow --voice susan                    # a name, part of one, or male / female
```

…or **right-click → Voice**, which lists what is installed and ticks the one in use. The
choice is saved to `~/.flow/profile.json` immediately, so it survives a restart. A saved
voice that has since been uninstalled falls back to the engine default and *says so* at
startup rather than quietly speaking in something else.

**Every Windows voice on offer sounds dated, and installing better ones does not fix it.**
This was documented the other way round until it was tested. Measured on the development
machine, which has `MicrosoftWindows.Voice.en-US.AvaHD.1`, `…en-US.Guy.2` and
`…en-GB.Sonia.1` installed through *Settings → Accessibility → Narrator → Add natural
voices*: **not one of them appears in the menu.**

The reason is more specific than "Windows registers no token", and worth writing down
because it closes off the obvious workarounds. The package *does* ship a complete, valid
SAPI token — `TTS_MS_en-US_AvaNeural_11.0`, with an engine CLSID and a proper attribute
set. Two things make it inert. It declares its `categoryBase` as
`HKLM\SOFTWARE\Microsoft\Speech Server\v11.0`, **a hive that does not exist** on the
machine; a registry-wide search for the token name returns nothing. And the engine CLSID
`{a12bdfa1-…}` is **registered in no COM store**, so even hand-writing the token into a
store that *is* read would produce a voice with nothing behind it. The definition lives
only in the package's private `Registry.dat`, which Narrator loads in-process under
package identity. `Windows.Media.SpeechSynthesis.AllVoices` returns the same six OneCore
voices, so WinRT is not a way round it either.

So there is no registry hack and no alternate API. Every *Windows* voice Flow can offer is
the 2013 `MSTTS_V110` generation — three classic `TTS_MS_*_11.0` tokens and six
`MSTTS_V110_*`. Shipping a different engine is the only thing that changes the answer,
which is what the Piper support below is for.

One measured detail that decides what you can reach: `System.Speech` is a .NET API with
two implementations, and they do not enumerate the same voices. Windows PowerShell 5.1
reads only the legacy SAPI5 store; PowerShell 7 also reads the OneCore store. On the
development machine that is the difference between **3 voices and 9**, which is worth
having — Susan, George and Mark beat the Desktop pair — but it buys *more* of the same
generation rather than a better one. Flow therefore prefers `pwsh`
and falls back to `powershell`, and uses the same executable to list and to speak — a
menu offering voices the host cannot select would fail silently, which is how you end up
choosing a voice and hearing a different one.

### A better voice, if you want one

Windows is the floor, not the ceiling. Install the `voice` extra and any Piper voices you
want, and they appear in the same right-click → **Voice** menu, listed above the Windows
ones and chosen the same way. Nothing else about Flow changes.

```bash
uv pip install -e ".[voice]"
```

```bash
python -m piper.download_voices en_GB-cori-high --data-dir ~/.flow/voices
```

`python -m piper.download_voices` with no arguments lists everything available — around
forty English voices and many other languages. Models land in `~/.flow/voices/` as an
`.onnx` and an `.onnx.json` sidecar, and **both halves are required**: the sidecar carries
the sample rate, and a guessed rate produces audio at the wrong pitch rather than audio
that fails.

That is the whole install. With the extra absent, or with no models downloaded, the menu
looks exactly as it always did.

**Why Piper and not the voices you already have.** The obvious answer is `edge-tts`, which
serves the very Ava/Guy/Sonia voices sitting unusable on the disk. It is ruled out twice
over. **R16** caps declared dependencies — but this is an *optional* extra, so a default
install still fetches three, the same reading already applied to `[cuda]`. **R9** is the
promise that nothing leaves the machine, which `product.md` records as non-negotiable, and
a WebSocket carrying the text of every spoken reply to Microsoft breaks it whether or not
it needs an API key. Piper synthesises locally, so R9 holds. It is also why spoken replies
work on macOS, where there is no SAPI half at all.

**Loaded once, in the background.** Flow uses Piper in-process rather than shelling out to
its CLI, and that is a measurement rather than a preference. The CLI takes **3.30 s to
produce its first sample**, and the figure barely moves between a 61 MB model and a 109 MB
one — so it is not model loading, it is Python start-up and the `onnxruntime` import, paid
again on every single reply. Three seconds of silence before each answer is not a
conversation. In-process, the same sentence and model measure `import piper` 0.33 s,
`PiperVoice.load` 3.16 s, then **0.13–0.22 s to the first audio** with 5.6 s of speech
synthesised in 0.95 s. The load is hoisted onto a background thread the moment you pick the
voice, so by the time you say anything it has usually finished — and the microphone is
gated from the instant a reply starts, even while the model is still coming in.

**Genders are mostly blank, on purpose.** Piper sidecars carry no gender field — verified
against the installed models, which describe the dataset, language, and phoneme tables and
nothing about the speaker. Unless the name says so outright (`hfc_female`,
`northern_english_male`), Flow leaves it unset rather than reading a gender off a first
name. The consequence is worth knowing: `--voice female` will not select such a voice, so
it stays on the Windows ones. Asking by name — `--voice cori` — always works.

### Asking without pressing anything

A conversation where you press a button after every sentence is not a conversation. In
converse mode a draft that stops changing is put to the CLI on its own after **4 seconds**
of silence, and the Ask button counts down — `Ask 4s`, `Ask 3s` — so it is never a
surprise.

**The draft stays correctable the whole time.** Anything you do resets the clock: speaking,
a correction landing, pressing Refine or Continue. The countdown only runs while the mic is
live and nothing else is happening — it will not fire while you are talking, while a decode
is still running, while the previous answer is playing, or after you disarm the pill.

Four seconds is measured rather than chosen. On the one volunteer recording where every
item was located, the pauses a speaker leaves between separate spoken items run
**1.4–3.3 s** (median 2.5 s), and each of those gaps also contains a spoken item number, so
the real silence is shorter still. Anything under ~3.3 s fires while someone is mid-thought.

**Dictate mode never does this.** Pasting into a focused window is irreversible, so it stays
a deliberate act forever. Asking a question is not, and its answer is additive — that is the
whole distinction. `--no-auto-ask`, or **Ask only when I press it** in the right-click menu,
turns it off.

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
(the library silently truncates mid-term at 223 tokens). A second kind of line,
`wrong -> right`, is for the word the recogniser keeps getting wrong *despite* the
biasing: it rewrites the decoder's output directly — whole words, left side
case-insensitive, right side verbatim — and biases nothing, because a correction you
had to declare is one biasing already failed on.

**What Flow learned from you** — a spoken correction is a confusion pair you labelled
yourself: the model wrote X, you wanted Y. Say the same fix **twice** and Y joins the
decode bias, live, with no file to edit and no restart. Only Y: the wrong reading is what
the model already produces unaided, so feeding it back would bias toward the mistake.
These live in the profile, not in your file — the file stays something you typed and own.

Both phrasings teach, and they agree with each other:

```
capitalize sameer          -> learns Sameer
change sameer to Samir     -> learns Samir
all caps nasa              -> learns NASA
change cube cuttle to kubectl -> learns kubectl
```

Two things deliberately teach nothing. **Lower-casing** (`lowercase RELEASE NOTES`) is
formatting rather than vocabulary, and biasing a decoder toward a common phrase is the
measured harm below, not the benefit. And **one correction is not enough** — once is as
likely to be you changing your mind as the model mishearing; twice is a pattern.

The catch is that this rides on the correction grammar, so it only fires when a
correction is *recognised*. If you phrase corrections descriptively rather than as
commands, nothing is learned either — see the register limitation in
[Known limitations](#known-limitations).

**And it will offer to write the arrow line for you.** A pair you have corrected twice is
also a candidate for a `wrong -> right` substitution, but a guess from a word-level diff
is not consent to rewrite what you said — so Flow asks instead of acting. Right-click and
up to three of them sit in the menu:

```
Add correction:  semir → Samir
Never offer  ▸   semir → Samir
```

One tap appends the line to `~/.flow/lexicon.txt`, and it applies to the very next
utterance. **That tap is the only thing that ever writes to your lexicon** — Flow appends
one line, at the end, and never edits, reorders, removes or reformats one, so everything
already in the file comes back byte for byte. (The one other write is creating the file
from a template of comments, if the menu's **Open settings folder** finds it missing.)
A pair already in the file stops being offered; **Never offer** drops one without
unlearning the bias, which never needed consent because it rewrites nothing.

Undo-straight-after-append is also recorded, as the signature of a command read as
dictation. It is **reported**, never applied automatically: changing the alias table
changes what a word means for every future utterance, and "this was a command twice"
cannot establish "this is never dictation".

**Biasing cuts both ways, and the measurement says so loudly.** See
[Known limitations](#known-limitations).

## What Flow stores on disk

| Path | Written by | Contents |
|---|---|---|
| `~/.flow/lexicon.txt` | you, by hand — and by Flow in exactly two cases: creating it from a template of comments if the menu's **Open settings folder** finds it missing, and appending one `wrong -> right` line when you tap an offered correction | terms to bias toward, and `wrong -> right` corrections to apply. The template is comments only, so the opt-in is typing a line that is not a comment. Flow never edits, reorders, removes or reformats a line — what you wrote comes back byte for byte |
| `~/.flow/profile.json` | `--calibrate`, every Send, choosing a voice, and toggling auto-ask | measured room/voice/confidence and the microphone name the room was measured through, learned confusion pairs, misroute signatures, the chosen voice, whether auto-ask is on, the two spoken send words, and the `workspace` a converse question is asked from. Plain JSON, readable and deletable by hand; an older profile loads with the shipped defaults for anything it lacks |
| `~/.cache/huggingface/hub/` | first decode | the models. `base.en` 141 MiB, `small.en` 464 MiB |
| `~/.flow/diag.jsonl` (+ `.1`) | every state change, route, CLI call and device event, unless `--no-profile` | a content-free shadow of the event stream: timestamps, state transitions, route kinds, operation ids, durations, provider names, lengths, error *categories*, and on each route a `confidence` — how well the decoder heard the utterance being routed, or `null` when that is unknown. **No words.** Field names are an allow-list checked against a deny-list at import, so a draft cannot get in by being short. Bounded with one rotation: two files, a known ceiling. Startup names the path out loud |
| `.bench/` | `scripts/` | benchmark audio, results and manifests. **Tracked**, except the downloadable corpora and the volunteer recordings — a recording is a person, so those live outside the repo and out of its history; `.bench/README.md` says where. Every result file carries an `identity` block naming the date, the `faster-whisper`/`ctranslate2` versions and the model revisions that run loaded |

Deleting `~/.flow/profile.json` forgets every inference and nothing else. None of these
files is ever uploaded — the one value in them that can leave the machine is the
`workspace` path, which the workshop preamble names when you ask a question.

### Why `.bench/` is in the repository

It was git-ignored for most of this project's life, on the reasoning that `scripts/`
reproduces it. That is true of the audio and false of everything else:

- **A result is a measurement taken at a moment.** Re-running `accent_bench.py` produces
  a new number, not the old one. The `-shipped` / `-proposed` pairs under
  `.bench/accent/` are the A/B comparisons the tuning decisions were made on, and this
  project decides almost nothing without a before and an after.
- **A recording is a person.** The clips under `.bench/recorded/` came from volunteers
  reading the sheet in [docs/recording-kit.md](docs/recording-kit.md). They are the only
  material that answers P1 and P3 at all, they are not on the internet, and losing that
  directory loses them.
- **The generated fixtures are cheap to store and slow to remake** — a cold self-drive
  run spends minutes synthesising WAVs one at a time through PowerShell.

**The accent corpora are excluded** (`.bench/accent/edacc/`, `edacc-short/`, `aesrc/` —
about 98 MB). They are re-downloadable with `scripts/fetch_accent_data.py`, so storing
them buys only repository size; and the AESRC slice comes from a community re-upload
that declares no licence, which `fetch_accent_data.py` flags as local internal eval only
— not a claim that survives being committed anywhere. Their **manifests are kept**, so a
fresh fetch can be checked against the rows an old result was computed from.

[`.bench/README.md`](.bench/README.md) is the full inventory: what is tracked, what is
not, and which harness remakes each thing that is missing.

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
  lexicon.py   the user's own terms and declared corrections, re-read on change
  thread.py    what has already been sent, bounded (P6)
  speak.py     spoken replies through one long-lived System.Speech host (P9)
  ui.py        the pill, the draft bubble and the hand editor (tkinter), DPI-aware
  inject.py    clipboard + SendInput, and terminal-safe paste (ctypes, P7)
  hotkey.py    RegisterHotKey on its own message-loop thread (ctypes)
  diag.py      the wordless trace, and the identity block every benchmark records
scripts/       benchmarks, probes, the soak test and the self-drive harness
tests/         773 tests: routing, state machine, filters, phonetics, resilience
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

773 tests, ~16 s, no microphone or model required — the fakes are injectable precisely so
the routing logic, where the subtle bugs live, can be tested without either.

The end-to-end harness is the one that catches what unit tests cannot:

```bash
uv run python scripts/selfdrive.py
```

A Windows SAPI voice speaks each utterance to a WAV; the WAV is fed to a real `Session` as
microphone blocks, through the real gate, the real two-tier decoder, the real router and
the real apply. 64 checks covering dictation, five correction shapes, undo, rescue, send,
converse against the live CLI, a spoken follow-up, the asking-state UI, calibration, the
learning loop, window placement and the chips. It found two real defects on its first
outings, both of which every layer-specific harness had missed.

There is one thing it cannot see, and it is the one that mattered most. It clicks chips
with `event_generate`, which hands Tk an event without Windows ever being involved — so
its clicks cannot move the focus, and for the whole life of the project it stayed green
while a *real* click on Send pasted into nothing at all. That needs a real mouse:

```bash
uv run python scripts/send_check.py --live
```

It opens an ordinary window and a console, clicks Send where the chip is actually drawn,
and reads back what arrived in each. Before the fix: 6 of 12 checks, nothing delivered
anywhere, and Send reporting success. After: 18 of 18.

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
| `send_check.py` | do the words a pressed Send hands over actually arrive — `--live` opens a window and a console and clicks the chip with the real mouse |
| `fetch_accent_data.py` | pull per-accent evaluation slices into `.bench/` |
| `ingest_recordings.py` | turn a volunteer's phone recording into scored clips (P3) |
| `voices.py` | which voices this machine has, and what each one sounds like — `--speak` says a line in each, `--wav` writes them |
| `tk_probe.py` | the window attributes the pill depends on |
| `ui_probe.py` | render the pill and bubble against a fake session that walks every state — `--hold STATE` pins one, `--bare` drops the draft, `--sent` presses Send so the card it leaves behind can be looked at |
| `slim.py` | trim the unreachable dependencies |

Every benchmark writes an `identity` block into its result file — the date, the
`faster-whisper` and `ctranslate2` versions, and the cache revision of each model tier
that run loaded. A number is a measurement *of a build*, and comparing an old result to a
fresh one used to mean hoping nothing underneath had moved. Comparisons that were
byte-for-byte before still are: they drop `identity` and diff the rest.

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
  forces the next utterance to be treated as an instruction, and the **Edit** chip lets
  you type the fix instead of saying it. See
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
| Test suite | **773 tests, 15.9 s**, no mic or model needed |
| End-to-end | `scripts/selfdrive.py`, **64/64 checks**, live CLI round trip |
| Build | `uv build` → wheel + sdist; wheel installs into a clean venv and its `flow` command runs |
| Dependencies | 3 declared, **28 installed**, 243.9 MB venv |
| Models on disk | `base.en` 147.8 MB, `small.en` 486.1 MB (141 / 464 MiB) |
| Agent CLIs found | `codex`, then `claude` as fallback |
| Speech engine | `System.Speech` available |
| Hotkeys | 4 actions, each with 1-3 fallback combos |

Recorded in [PROGRESS.md](docs/history/PROGRESS.md) from earlier runs, not re-measured here:

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
accented commands. [PROGRESS.md](docs/history/PROGRESS.md) is the build log, including the things that
broke.
