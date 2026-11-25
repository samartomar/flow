# Flow on 2026-11-22: where it was weak, what changed, what is next

The brief was to find where Flow has room to improve — looks, function, ease of use,
readiness for end users and for a company — with the owner's own diagnosis as the
starting point: it is not easy enough to get help refining a prompt, writing a better
email, or talking to your code, and something is missing as a whole.

This is the record of what was measured, what was decided from it, and what is left. The
decision itself, with its reopen bars, is in [decisions.md](../decisions.md) under
2026-11-22; the things only the owner can do are at the top of
[NEEDS_YOU.md](../../NEEDS_YOU.md).

## The finding in one paragraph

Flow's dictation is good and its AI half was not being used, including by the person who
built it. The cause was not the models or the latency. **Flow knew which window the words
were going to and did nothing with it, and when something went wrong it changed colour
instead of saying so.** Refine had one answer for every window (a coding prompt), Ask was
cut off at the median time a real answer takes, a broken first-choice CLI was retried on
every call, and the pill's only vocabulary for all of it was a hue.

## What was measured before anything changed

| What | How | Result |
|:---|:---|:---|
| Whether Refine and Ask get used | The owner's own profile and trace, 731 dictated words in | 0 Refines, 0 Asks, Ask mode never entered, no workspace set |
| Refine on a dictated email | `refine.refine(polish=True)` through `claude` | Returned a *prompt asking somebody to write the email* ("Write a message to Priya proposing that…"), 8.2 s |
| Ask on this repository | `refine.ask` through `claude`, seven questions | 11.1, 12.6, 15.5, 19.8, 21.1, 26.5 s and one "timed out after 20s". Three of seven are past the 20 s cutoff |
| A broken first-choice CLI | Unpinned Refine with a `codex` that exits 1 every call | 16.3 s for a rewrite `claude` alone returns in 8.2 — about 8 s wasted on every call |
| What the failure said | The note Flow produced | `codex exited 1: OpenAI Codex v0.163.0` — the banner. The real reason was eleven lines further down |
| Refine's "hold the mic to say more" | Two Sends in Refine mode, reading what the CLI was handed | The second hold went alone, with no context: "and cap it at three attempts" |
| The strip under the pill | Contrast of its text on its fill | 3.16:1, under the 4.5:1 small text needs |
| The suite | `python -m unittest discover -s tests` | 3,794 tests, green, 94.7 s |

## What changed

| | Before | After |
|:---|:---|:---|
| **Refine in a mail window** | A prompt about an email | The email: greeting to the person named, point first, sign-off, your name if you gave one. 5.6–6.4 s |
| **Refine in Slack or Teams** | A coding prompt | A chat message: no greeting, no sign-off |
| **Refine in a window Flow does not know** | A coding prompt | Your own words, tidied — the kind that changes least |
| **Refine in a terminal, an editor, an AI app** | A prompt | The same prompt, from the same brief, untouched |
| **Picked the wrong kind** | — | Say "make it an email" (or a prompt, a message, "tidy it up") at the result; or set the program in Flow Home |
| **A second hold** | Refined on its own | Everything heard so far, written again as the same kind, so "actually make it Wednesday" is a correction |
| **A question about your code** | Cut off at 20 s, three of seven failing | Waits 60 s; the panel says `asking claude - 14 s` |
| **A CLI that fails every call** | Retried first, every call | Tried last for ten minutes after the first failure, named once on the pill and in full on Flow Home ▸ Models |
| **Why a CLI failed** | Its banner | Its own error sentence |
| **`codex` and Flow's Effort setting** | Ignored; ran at the user's own config | Sent as a config override, verified by codex's banner at all five levels |
| **Choosing a mode** | The mic glyph changes hue | One line: `Refine - writes an email for OUTLOOK, then you press Send` |
| **A failure** | A red flash | The flash, and the sentence under it |
| **A tap with no agent CLI** | Nothing | `Refine and Ask need claude or codex - right-click, Open Flow` |
| **Waiting on the CLI** | A blue ring | What is being written, by whom, for how long |
| **The strip's text** | 3.16:1 | 5.97:1 |
| **The suite** | 3,794 tests | 4,002 tests, green |

Measured end to end through the real `Session` and the real CLIs, on the machine whose
`codex` cannot answer: first Refine 13.2 s (codex fails, `claude` writes the email),
second hold 5.6 s (codex not tried), spoken restyle 6.2 s, tidy 5.8 s, a grounded
question 10.3 s.

*Correction, 2026-11-23:* "cannot answer" was true of the codex a development shell
found (0.163.0). The shell Flow is normally started from finds 0.171.0, which answers;
there a rewrite takes about ten seconds through codex. See decisions.md of that date.

An independent review of the change, run before this was written up, found three
things that were then fixed and tested: a Send that did not begin with a hold could still
be read as more of a result closed earlier, sending old words in front of new ones; the
failure-reason picker could return a line of the user's own dictation, because one CLI
echoes its prompt; and several browser titles were misread (Edge's "and 4 more pages", a
headline beginning "Outlook:", `Gmail - Wikipedia`). The decision entry has each.

What the window's title is used for, and what happens to it, is the one new thing Flow
reads: it is matched against a short list of site names when you refine and is never
stored, traced or sent ([architecture.md](../architecture.md#what-leaves-the-machine)).

## Against the field

A survey of comparable tools the same day (Wispr Flow, superwhisper, Aqua Voice, VoiceInk,
FluidVoice, OpenWhispr, Handy, Typeless, Willow, and the voice input in VS Code, Cursor
and Claude Code), from their own documentation and, for the open-source ones, their
shipped prompts.

| What the field does | Flow before | Flow now |
|:---|:---|:---|
| Picks its behaviour from the focused app or browser tab — every leader does | One behaviour for every window | Done, by program name and the site name in a tab's title |
| Email layout: greeting, paragraphs, sign-off, the user's name | None | Done |
| Treats the transcript as data: never answers it, never obeys it — every open-source cleanup prompt carries this line | Not said | In all three new briefs; measured |
| Minimal edits by default; the most common complaint about these tools is an edit that changed the meaning | Restructured everything | "Tidy" is the default for an unknown window; facts and negations are named as untouchable |
| **Select text, say what to do with it** — six tools have it, and it is how each of them answers an email | Missing | **Still missing.** The first proposal in NEEDS_YOU |
| Shows what the agent is doing while it works | A ring | A counter. Tool-by-tool progress is the second proposal |
| Teaches each mode with a practice sentence in onboarding | Dictate and Ask only | Refine is now explained with a spoken example on the first step and on Home; a try-it step is the third proposal |

Where Flow is ahead of the field and should stay: recognition is local, nothing is sent
without a press (most tools rewrite and paste in one step), the agent is the CLI you
already pay for, and Ask can answer from your actual project.

## Ease of use: what a new user meets

From a read of the whole journey, install to tenth dictation. Fixed this round are marked.

1. **Failures were a red flash with no words** — fixed.
2. **A tap silently changed mode**, and the next dictation went to a cloud CLI instead of being pasted — fixed: the tap says what the mode does.
3. **With no agent CLI a tap did nothing** — fixed.
4. **Refine was unexplained**, and its result tag read "refined for this repo" with no workspace set — fixed: the tag names the kind, and the first step and the Home page say what Refine does with an example. A try-it step is open.
5. **CLI failures were raw and waits were blank** — both fixed.
6. Skipping setup leaves no speech model, and the first hold starts a silent download. Open.
7. A quick tap of the talk keys latches hands-free with nothing on screen saying so, until "boom". Open.
8. The download is a console program behind a SmartScreen warning, with no installer, shortcut or start-with-Windows. Open; see below.
9. The guide still describes the Classic pill in places the Compact pill has replaced. Open.
10. Naming drifts: "Type" on the pill, "Dictate" in Flow Home; 45 s in one place and 60 s in another for the same tuning. Open.
11. Shortcuts are typed as text and need a restart. Open.

## Is it shippable

**To one developer: yes.** The release pipeline is careful (tag-gated, suite before build,
pinned actions, published checksum, immutable release), recognition is local, no audio is
written to disk, the trace holds no words, and history is opt-in.

**To a company: no**, and three things decide it.

| Gap | For one user | For a company | Who can fix it |
|:---|:---|:---|:---|
| Nothing is signed: `flow.exe`, and the helper Flow downloads at run time | A SmartScreen click | Blocker — allow-listing is by publisher | The owner buys a certificate; the workflow step is small |
| The zip is labelled MIT and bundles GPL (Piper) and LGPL code with no notices | Not the user's exposure | Blocker — fails an open-source review | A decision: keep it in with notices, or make it a download |
| No setting can be fixed by an administrator | — | Blocker | Code: a read-only machine policy file |
| No installer; update check off by default; winget still pending | Minor | Major | Code, after signing |
| Model downloads ignore a mirror for Parakeet; little proxy guidance | Minor | Major | Code and a doc page |
| The documented list of what goes out misses three fetches (Piper voices, engine installs, the voice catalogue) | Minor | Major | Code: the test that guards the list is not recursive |
| Dictated text enters Windows clipboard history and cloud clipboard | Minor | Major | Code: three clipboard formats |
| No diagnostics export, no crash record, no single-instance guard | Minor | Major | Code |
| No SECURITY.md, changelog or contributing guide | Minor | Major | Docs |
| The pill is invisible to a screen reader and is mouse-and-hotkey only | Minor | Major | A statement now; real work later |

None of these was touched this round. The first three are in NEEDS_YOU as decisions.

## What is next, in the order I would do it

1. **Select it, say what to do with it.** The largest remaining gap against the field and
   the other half of "help me write a better email": the words already on the screen.
2. **Take Piper out of the zip or ship its notices.** The only readiness item worth doing
   before the next release to anyone.
3. **Show the agent's progress** while a question is out.
4. **A try-it step for Refine in the first run**, and re-shoot the README's reel, which
   this round's Settings card and Home line have put out of date.
5. **Sign the build**, then an installer, then the machine policy — in that order,
   because each needs the one before it — if Flow is going to a company.

## Later the same day: the flows between the two good screens

The owner's answer to this round was that the resting pill and Flow Home are right, and
that switching to Refine or Ask and clicking through them is where the experience falls
apart. That became a second round, recorded in [decisions.md](../decisions.md) as "The
pill is an indicator". In one paragraph: **you dictate, and the words land; a rewrite is
one more sentence ("make it an email", "polish that") or one key (`alt+shift+X`), and it
replaces what landed; a question shows nothing but the pill until the answer comes up
on a card that stays.** No panel rises while you talk, nothing waits for a Send, and a
tap on the pill no longer changes mode. The earlier flow is a setting, off.

It also changes item 1 of the list above: select-and-say was specced against a panel
that held the result, and has to be re-argued for a flow where the result lands.

## How to see it

```bash
uv run flow                                           # the app
uv run --with pillow python scripts/compact_shots.py  # every state the pill draws, into .shots/
uv run python -m flow.home.demo                       # Flow Home over a pretend session
uv run python -m unittest discover -s tests           # the suite
```

In the app: put the cursor in Outlook or a Gmail tab, tap the pill until the mic is gold,
read the line under it, hold and dictate an email the way you would say it to a person.
