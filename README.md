# Flow

Hold a key, talk, let go: the words paste into the window you were working in. Or tap the
pill to hand them to the agent CLI you already use — shaped into a prompt for your
project, or asked as a question and answered above the pill.

Speech recognition runs on your machine. No API key.

**English only · three dependencies · Windows in full, macOS and Linux in
[Lite](#flow-lite-macos-and-linux)**

![Flow: a line dictated into a terminal, one word fixed by voice, a rough instruction refined into a prompt, then a question answered by the agent](docs/flow.gif)

*The real pill against a scripted session, recorded by [`scripts/compact_reel.py`](scripts/compact_reel.py).*

## Install

```bash
uv tool install git+https://github.com/samartomar/flow
flow
```

You need [`uv`](https://docs.astral.sh/uv/), which fetches Python and the three
dependencies itself, and a microphone. No Python? On Windows, [Scoop](https://scoop.sh)
installs the release build:

```powershell
scoop bucket add flow https://github.com/samartomar/scoop-flow
scoop install flow/flow    # flow/ matters: Scoop's main bucket has a different "flow"
```

Or download
[`flow-windows-x64.zip`](https://github.com/samartomar/flow/releases/latest/download/flow-windows-x64.zip),
unzip it and run `flow.exe`. It is unsigned, so the first launch shows SmartScreen:
**More info → Run anyway**.

An agent CLI — `codex` or `claude` on PATH, signed in — is optional. It adds Refine, Ask
and rewrites; dictation and spoken corrections work without it.
[The guide](docs/guide.md#install) has the rest.

## Flow Lite (macOS and Linux)

Off Windows, Flow runs as **Lite**: the same recognition, corrections and agent loop, but
Send copies the draft and you paste it yourself. No injection and no global hotkeys, so
there is nothing to grant but the microphone — hold the pill to talk. There is no Mac or
Linux download; install with uv. [What Lite is, and is not](docs/product.md#flow-lite--the-portable-body).

## The loop

1. **Hold `ctrl+win`** (or the pill) and talk.
2. **Let go.** The words paste where you were typing.
3. **Said it wrong?** Hold again and say *"change Tuesday to Thursday"* or *"scratch
   that"*. Flow fixes its last paste until you type or click there.
4. **Wrong window?** Click the right one and press **Paste last** (`alt+shift+Z`).
5. **Want an answer?** Hold **`ctrl+alt+win`** and ask.

On first run, Flow Home walks you through the microphone, the model download, a
45-second tuning to your voice, and whether to keep a history. Every step can be skipped.

## Three modes, one tap

- **Type** (white): speak, let go, it pastes.
- **Refine** (gold): `codex` or `claude` turns what you said into a prompt for your
  project. Nothing pastes until you press Send.
- **Ask** (violet): the question goes to your agent CLI, and the answer appears above the
  pill and is read aloud. **Continue in Flow** opens the conversation in a window.

Point Refine and Ask at a project (Flow Home ▸ Settings ▸ Workspaces, or `--cwd`) and the
answers are about your code. The Classic pill — a draft you correct by voice before
sending — is one switch away in Settings.

## Flow Home

Right-click the pill ▸ **Open Flow**, or run `flow --home`: one window for everything that
isn't talking. Speech models download with progress and swap without a restart; the
microphone, shortcuts, workspaces, agent CLI and reading voice are all set there.
**Voice** tunes Flow to you, **History** shows what you dictated (if you keep one), and
**Conversations** is Ask in a window. The pill never grows a setting.

## Who it is for

Developers who speak English as a second language, with a strong accent. Spanish, Indian,
Russian and Japanese L1 speakers anchor the design and the benchmarks
([why](docs/product.md)).

## What leaves your machine

- **Nothing, by default.** Audio, recognition, corrections, your lexicon and your profile
  stay local. No API key is read, stored or passed anywhere in this codebase.
- **Whatever you hand an agent CLI** goes to its cloud: the draft or the question, plus
  your workspace path if you set one.
- **History** is kept only if you choose to, in `~/.flow/history.jsonl`.
- **Pasting** goes through the Windows clipboard for a moment, where clipboard managers
  and cloud sync can see it.
- **A Microsoft voice**, if you choose one, sends each spoken answer's text to Microsoft.
  Every other voice is local.

Flow Home is served on `127.0.0.1`, only to the window Flow opens, with a new token each
launch. [The exact boundary](docs/architecture.md#what-leaves-the-machine).

## Known limits

- **Corrections must be phrased as commands.** *"delete the bit about the standup"* works;
  *"I feel it should not contain the summary"* is typed as words.
- **A personal lexicon cuts both ways.** It recovers 27–34% of the rare words the model
  missed, and makes WER 14–38% relatively worse on speech without them (EdAcc,
  `small.en`). Add the words you say often.
- **Live text refreshes about once a second**, is shown dimmed, and is always replaced by
  the final text.
- **Accuracy depends on the voice.** Flow Home ▸ Voice ▸ **How well Flow hears you**
  measures yours in five sentences.

All of them are in [the guide](docs/guide.md#known-limitations).

## Docs

| | |
|---|---|
| [guide](docs/guide.md) | the manual: every flag, spoken command, mode and setting |
| [product](docs/product.md) | who Flow is for, the P1–P9 requirements, the non-goals |
| [architecture](docs/architecture.md) | data flow, threads, events, and the tuned constants with their measurements |
| [roadmap](docs/roadmap.md) | what is left, and the accent benchmark that measures it |
| [development](docs/development.md) | layout, tests, harnesses, and building a release |
| [decisions](docs/decisions.md) | why things are the way they are |

## Contributing

Especially welcome: anyone who speaks accented English and can tell me where Flow
mishears them. That is the one thing I cannot measure alone.

```bash
git clone https://github.com/samartomar/flow && cd flow
uv sync && uv run flow                          # run it
uv run python -m unittest discover -s tests     # ~3,200 tests, ~90 s, no mic needed
```

Open an [issue](https://github.com/samartomar/flow/issues) for a mishearing (what you
said, and what appeared) or a pull request for anything else.

MIT licensed.
