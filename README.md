# Flow

Hold a key, talk, let go: the words paste into whatever window you were working in. Or
tap the pill and hand them to the agent CLI you already have — shaped into a prompt for
your project before anything pastes, or asked as a question and answered above the pill.

Speech recognition runs on your machine. No API key.

**English only · three dependencies · Windows in full, macOS and Linux in
[Lite](#flow-lite-macos-and-linux)**

![Flow: a message dictated word by word, corrected by voice, sent, then a question asked of the agent](docs/flow.gif)

*Recorded by [`scripts/reel.py`](scripts/reel.py) against the real windows — no
microphone, no model, nothing pasted.*

## Install

```bash
uv tool install git+https://github.com/samartomar/flow
flow
```

No Python? Take
[`flow-windows-x64.zip`](https://github.com/samartomar/flow/releases/latest/download/flow-windows-x64.zip)
instead — that link always serves the newest release. It is unsigned, so the first launch
shows Windows SmartScreen and takes **More info → Run anyway**, once.

You need [`uv`](https://docs.astral.sh/uv/), which fetches Python 3.12 and the three
dependencies itself, and a microphone.

An agent CLI — `codex` or `claude` on PATH, already signed in — is **optional**. It adds
semantic rewrites, the prompt polish and converse mode. Without one, startup prints
`refine CLI: NONE` and everything else works.

[The guide](docs/guide.md#install) has the rest: cloning to change it, trimming ~106 MB
of unreachable dependencies, and why a `.cmd` launcher from `npm -g` is refused.

## Flow Lite (macOS and Linux)

Off Windows, Flow starts in **Lite** without being asked — `--lite` runs the same code on
Windows if you want to see it. Startup says which one you got:

```
Flow Lite on darwin: Send copies the draft and you paste it - no injection,
no global hotkeys, nothing to grant but the microphone.
```

**Lite is the brain, the ear and the clipboard.** Both decoder tiers, the correction
loop, the lexicon, the calibrated profile, the prompt polish, the thread and converse
mode are all there, unchanged. What changes is the last inch: **Send copies the draft and
you press Ctrl+V yourself.**

Four things it does not do — exclusions, not gaps: no injection into another
application's window, no global hotkeys, no auto-paste, and no target-window awareness.
What that buys is the property full Flow cannot have: **nothing to grant but the
microphone** — no accessibility permission, no input monitoring, no trusted-application
prompt.

**Push-to-talk works here anyway, and it does not need a hotkey.** Hold the pill, speak,
let go — the words land on your clipboard. A quick click still toggles listening, and
dragging still moves the pill. It is the same gesture Windows gets from `ctrl+win`, on a
button Flow already draws, which is why it costs no permission: a system hotkey is the
part that needs Accessibility and Input Monitoring, and this is not one.

Two requirements Lite cannot meet, named rather than dropped: P7 (safe paste into a
terminal) is a promise about a paste Flow performs, and Lite performs none; and P9's loop
ends on the clipboard, one keystroke short. [docs/product.md](docs/product.md#flow-lite--the-portable-body)
defines the half and the fence around it — features land in full Flow first and reach
Lite only if they survive without hands.

There is no Mac or Linux download. `uv tool install` is the way in, and a native macOS
body is not promised: it is weeks of work plus re-taking every measurement per OS, and
what would fund it is evidence from Lite.

## The loop

1. **Hold `ctrl+win`** — or hold the pill — and talk.
2. **Let go.** The words paste into the window you were working in.
3. **Said it wrong?** Hold again and say *"change Tuesday to Thursday"* or *"scratch
   that"* — Flow fixes what it just pasted, as long as you have not typed or clicked since.
4. **Pasted into the wrong window?** Click the right one and press **Paste last**
   (`alt+shift+Z`, or the pill's right-click menu).
5. **Want an answer instead?** Hold **`ctrl+alt+win`** and ask — whatever the pill is on.

The first time, Flow Home walks you through five steps — the microphone, the speech
model with its download, a 45-second tuning to your voice, and whether to keep a
history — any of which you can skip.

## Three modes, one tap

Tap the pill to cycle it:

- **Type** (white): speak, let go, it pastes.
- **Refine** (gold): what you said is shaped into a prompt for your project by `codex`
  or `claude`, and shown to you; nothing pastes until you press Send.
- **Ask** (violet): the question goes to your agent CLI, and the answer rises above the
  pill and is read aloud. **Continue in Flow** carries the conversation to a window where
  you can read all of it and type the next question. `ctrl+alt+win` asks from any mode —
  the keys Wispr Flow users hold for its Command Mode — and `ctrl+win` goes back to
  dictating.

Point Refine and Ask at a project — Flow Home ▸ Settings ▸ Workspaces, or `--cwd` — and
the answers are about your code.

**The Classic pill** — a draft that floats above the pill, which you correct by voice
(*"change Tuesday to Wednesday"*, *"scratch that"*) and send when it reads right — is one
switch away on Flow Home ▸ Settings ▸ The pill, for this release.

## Flow Home

Right-click the pill ▸ **Open Flow** (or start with `flow --home`) for one window with
everything that isn't talking: which speech model hears you — downloaded with progress
and swapped without a restart, each shown with the error rate measured for it — which
microphone, the shortcuts, the send word, your workspaces, the agent CLI and the voice
that reads answers. **Voice** tunes Flow to you and fixes the words it gets wrong.
**History** shows what you dictated and where it went, if you choose to keep one.
**Conversations** is Ask in a window: type or talk, and carry a conversation on later.
The pill never grows a setting. [The guide](docs/guide.md#flow-home) has the pages.

Pasted into the wrong window? **Paste last** (`alt+shift+Z`, or the pill's menu) pastes
it again into the one in front.

## Who it is for

Developers who speak English as a second language, with a strong accent — Spanish,
Indian, Russian and Japanese L1 speakers anchor the design and the benchmarks. That is
what the correction grammar, the calibration pass and the personal lexicon are for.
[docs/product.md](docs/product.md) states why, and what it changes.

## What leaves your machine

**No API key is read, stored or passed anywhere in this codebase.** Audio, the utterance
buffers, the lexicon, the profile and every local edit stay put. Your words are written to
disk only if you choose to keep a history — Flow asks, with neither answer picked for you
— and then only to `~/.flow/history.jsonl`, which "Stop keeping" deletes.

What leaves is what you hand to an agent CLI, which is cloud-backed: the draft tail on a
rewrite, and the question plus the workshop preamble on an Ask. **That preamble names
your workspace, so a filesystem path leaves the machine along with the words** — and a
project path can identify an employer or a client. Set no workspace and nothing of the
kind is sent.

Send also puts the draft on the Windows clipboard, where any clipboard manager or
cloud-clipboard sync you run will see it.

Flow Home is a page Flow serves on `127.0.0.1` only, from the first time you open it until
Flow quits, and only to the window Flow opened — each launch makes a new token, and a
request from any other page is refused. Nothing it serves leaves the machine.

One optional extra opens a socket: the `[edge]` voice pack sends the *text of each spoken
reply* to Microsoft to be synthesised. Install neither extra, or pick any other voice,
and nothing is sent. [docs/architecture.md](docs/architecture.md) § *What leaves the
machine* states the boundary precisely.

## Known limits

The full list is in [the guide](docs/guide.md#known-limitations). The four worth knowing
before you start:

- **Corrections have to be phrased as commands.** *"delete the bit about the standup"*
  works; *"I feel it should not contain the summary"* is appended to your draft as text.
  The first recording from an Indian-L1 speaker phrased every correction the second way
  and **0 of 10** were recognised. The cause is register rather than accent, and it is
  unfixed — **Refine** forces the next utterance to be read as an instruction, and
  **Edit** lets you type the fix instead.
- **A personal lexicon cuts both ways.** Measured on EdAcc with `small.en`, it recovers
  **27–34%** of the rare words the model otherwise missed, and makes WER **14–38%
  relatively worse** on speech containing none of the terms. Add words you say often, not
  every word you know.
- **Partials refresh about once a second, not per word**, and can contain nonsense
  mid-word. They are shown dimmed and always replaced by the final text.
- **The published accuracy numbers are other people's.** The per-accent numbers come
  from recordings of other people. Yours is five sentences away: Flow Home ▸ Voice ▸
  **How well Flow hears you** scores what it heard in your voice, word by word.

## Docs

| | |
|---|---|
| [docs/guide.md](docs/guide.md) | the manual — every flag, every spoken command, both modes, voices, calibration, vocabulary, what is stored where |
| [docs/product.md](docs/product.md) | what Flow is for: the target user, the P1–P9 requirements, the non-goals |
| [docs/architecture.md](docs/architecture.md) | runtime reference: data flow, threads, the event stream, the tuning constants and their measurements |
| [docs/roadmap.md](docs/roadmap.md) | the gap between the product definition and this build, with the accent benchmark that measures it |
| [docs/analysis.md](docs/analysis.md) | requirements breakdown, the four architectures considered, ranked risks |
| [docs/development.md](docs/development.md) | layout, tests, the harnesses, the scripts, building a distributable |
| [docs/history/PROGRESS.md](docs/history/PROGRESS.md) | the build log, including the things that broke |

## Contributing

Collaborators welcome — especially anyone who speaks accented English and can tell me
where Flow mishears them. That is the one thing I cannot measure alone.

```bash
git clone https://github.com/samartomar/flow && cd flow
uv sync && uv run flow                          # run it
uv run python -m unittest discover -s tests     # ~3,100 tests, ~90 s, no mic needed
uv run python scripts/selfdrive.py              # the end-to-end harness
```

Open an [issue](https://github.com/samartomar/flow/issues) for a mishearing — what you
said, what appeared — or a pull request for anything else.
[docs/development.md](docs/development.md) has the layout, the harnesses and the scripts;
[docs/decisions.md](docs/decisions.md) is why things are the way they are.

MIT licensed.
