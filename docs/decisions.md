# Decisions — the standing record, with each decision's why and its reopen bar

Moved here 2026-08-01 from NEEDS_YOU.md when the decision session closed. Each entry
records what was decided, the measurement it stood on, and — where one exists — the
numbered condition that reopens it. The items these decisions spec'd are archived with
their evidence in [history/loop-rounds-1-3.md](history/loop-rounds-1-3.md). New
decisions append here when NEEDS_YOU.md closes them.

### 2026-09-01 — The compact pass: the marks move to the pill row, and everything else pulls in

Decided from a measured survey and the surface screenshots (`scripts/shots.py`), after
the felt-latency pass the same day. Two numbers made the case: the idle pill row was
420 px wide with ~150 px of nothing between the meter and the icons, and a three-line
draft sat inside ~178 px of panel of which 108 px was furniture — 34 of it a band that
existed only to hold four 26 px marks.

**The marks live on the pill row** (`Pill._draw_marks`): right-anchored against the
three icons, laid out right-to-left so the rightmost keeps a fixed address whatever
the set is — the argument the corner cluster already made, kept. The bubble and the
card publish their secondaries (`_marks`) and draw only the primary at the foot; the
pill binds each tag once and dispatches through the surface's live list at the click,
so a repaint never rebinds and a Copy that means a different answer is one binding
reading a different list. The hover word goes in the label slot on the right (`REFINE`,
`COMMAND`, `NEW CHAT`): a tip drawn above a 34 px row would be clipped by its own
canvas, and the state word is the one thing on the row that is already text.

**What moved, in pixels.** `PILL_H` 40 → 34; `ICON_SIZE` 16 → 14 and `ICON_GAP` 12 → 8;
`APP_SLOT_W` 72 → 44; `METER_X` 40 → 30; label gap and pad 12 → 8; the label's +.1em
tracking retired (7 px, spent on the marks); `PAD` 14 → 10; `CHIP_H` 26 → 22; marks
20 px in the row, glyphs still on their 16 px grid (`MARK_GLYPH`); `PANEL_MIN_H` 96 → 64
and `CARD_MIN_H` 120 → 80; `PANEL_MAX_H` 183, on the snap grid (`PANEL_MIN_H` + 7 lines)
so the ceiling is a height `_settled_h` can land on; `FONT_BODY` 14 → 13 px, which
measures the same 17 px line, so `BODY_CHARS_PER_LINE` is 64 at the 380 px column;
`PANEL_R` 18 → 12 and chips at `CHIP_R` = 11; `PANEL_WIDTHS` 420/520/640 → 400/480/580;
the help sheet at 520 px, 17 px lines and 6 px gaps, ceiling 1 090 from a measured 1 075.
The sent card no longer reserves the empty band, the activity row shares the note's
line when there is no note, and the elided count is back on a line of its own above
the draft (the band it shared is gone; the body gives that line back at the ceiling).

**Why 400 and not 360.** The first proposal was 360/440/540. With the marks on the row
the floor is the row's: app slot, mic, meter, four marks, three icons and the label sum
to ~393 px at these sizes, and `tests/test_compact.py` adds them up against the
narrowest width so the floor cannot drift below the marks again. Reopen if the row
ever has to carry a fifth mark, or if the app-name slot at 44 px proves too short for
what people actually dictate into — the slot, the meter's bar count and the label's
pitch are the three places the row can still give.

### 2026-09-01 — The felt-latency pass: what the trace said, what moved, and what did not

Every number here is from this machine's own `~/.flow/diag.jsonl` (6 442 decode records,
GTX 1070, `large-v3` on CUDA) or from a measurement taken the same day.

**Where the time went.** Partials p50 **795 ms**, p90 1 357 ms. Finals p50 **1 523 ms**,
p90 2 640 ms — and finals for utterances under three seconds still p50 823 ms, because
Whisper pads every input to a 30 s mel window and the encoder costs the same for one word
as for twenty. The final queued behind whichever partial was running (one decode thread,
no cancel). With the profile's `toggle` gesture the spoken send word was a second
utterance in full: 800 ms hangover plus ~800 ms decode, 1.6–2.5 s from "boom" to the
paste. Everything else on the release path — three 30 ms frame quantisations, a mic
reopen per hold (111–266 ms to the first block), two `profile.save()` and three
`Diag.write()` calls on the UI thread, the paste itself at 1–3 ms — summed to well under
a tenth of the decode.

**What moved, and the bar for each.**

- *The partial tier on the GPU is `small` again* (`asr.CUDA_PARTIAL_MODEL`). The
  one-model decision of 2026-08-05 bought "no partial→final rewrite" at 795 ms a partial;
  a partial that lands eight tenths of a second late is a caption, not a preview. Finals
  are unchanged. Reopen if the rewrite on accented speech is reported as worse than the
  delay was — the trade is stated in `asr.py` beside the constant.
- *A final makes the running partial stale* (`DecodeWorker._partial_stale`); a
  `cancellable` transcriber stops between segments, any other's result is discarded on
  arrival.
- *The send word fires on the silence after it* (`Session._hear_trigger`,
  `TRIGGER_QUIET_BLOCKS` = 3, `TRIGGER_MAX_SEC` = 3): the partial already heard it; ~200
  ms of quiet after a short utterance spends it without a final. Reopen if a trigger ever
  fires inside a sentence — the quiet requirement and the length cap are the two knobs.
- *The release stops reading, not the stream* (`MIC_LINGER_SEC` = 60): the next hold
  inside a minute captures from the press rather than from 111–266 ms after it. An open,
  unread stream is the idle unload's posture already; if that is ever not acceptable for
  hold mode specifically, the constant goes to zero and `talk_end` is what it was.
- *A 5 ms clock for the gesture* (`Pill._fast_tick`, `FAST_TICK_MS`), only while a hold
  or a paste wait is in flight, and `timeBeginPeriod(1)` for the process so `after()`
  means what it says on Windows' 15.6 ms timer.
- *Nothing writes a file on the frame that pastes*: the trace appends from its own thread
  (`Diag(background=True)`, bounded, flushed at close), and the profile save is owed by
  the routing frame and paid by the next (`Session._pump_saves`).
- *The pill repaints only when something it draws has changed* (`Pill._draw_key`). It
  rebuilt ~50 canvas items every 30 ms while idle — and `_row_icons` called `tag_bind`
  three times a frame, each a Tcl command Tkinter never frees (verified against
  `Misc._bind`): ~100 leaked a second for the life of the window. Bound once now, and the
  bubble's `draft` tag the same.
- *One partial render per frame, the newest; the draft body's layout and the card's
  answer layout are cached against their inputs; `place()` only when the band changes;
  the pointer's monitor is polled every fourth frame.*
- *Startup*: the voice enumeration (two PowerShell starts, now one, and off the path),
  the CUDA probe (310 ms, now on a thread after the pill), `sounddevice` imported on
  first use (172 ms), and `record_identity` ten seconds later rather than beside the
  model load. Pill-on-screen loses roughly a second on a stock machine.
- *A warm decode after each model load* (`WhisperTranscriber.warmup`), so the first real
  decode is a decode and not cuDNN's autotuning.

**What did not move, and why.** `FINAL_BEAM` stays at 5: on the three `.bench` reference
clips `large-v3` decodes 2.0 s of audio in 764 ms at beam 5 and 722 ms at beam 1 — the
padded encoder is the floor and the beam is noise beside it. Optimistic paste (paste the
last partial on release, reconcile with the final) was designed and not built: a paste
cannot be taken back in a terminal, and with the cheap partial tier the residual wait is
the final itself. **That floor is the engine's**, not this code's: FluidVoice on this
same machine runs NVIDIA Parakeet TDT 0.6B v3 (a q8 GGUF through parakeet.cpp with a
CUDA runtime), whose log shows ~500 ms per utterance and a 390 ms model load, and a TDT
decoder does not pad to 30 s. A Parakeet tier behind the `Transcriber` seam is the next
latency decision and is its own entry when it is measured, not this one.

### 2026-08-15 — The interpreter is pinned, and `trusted()` stops asking it what "absolute" means

A venv built on **CPython 3.14.7** ran the suite seven red; **3.12.13** ran the same tree
green. `ntpath.isabs("/x/pwsh")` is True on 3.12 and **False on 3.13+**, where a single
leading slash is correctly read as "the current drive" rather than as a location — and
`refine.trusted()` calls `os.path.isabs`. So seven tests that mocked `shutil.which` with
drive-less fakes had their declared CLI refused, resolved nothing, and left a mocked `Popen`
untouched. That is the Linux leg's failure of 2026-08 exactly (`tests/cli_env.py` records
it), arriving this time from the interpreter instead of from the platform. `requires-python`
allows `>=3.12`, so this was reachable by any user who let `uv` pick.

**The tests were wrong, not the code.** A fake path has to survive the predicate that will
judge it, and "absolute" is not a property a literal carries by looking like one.
`cli_env._FAKE_DIR` had already made that argument and then hedged it, choosing by asking
`os.path.isabs` — the same guess, one step closer. It asks `refine.trusted` itself now, and
`fake_exe` is the single spelling of "where a declared CLI pretends to live" across
`test_refine`, `test_voice` and `test_main`.

**But `trusted()` had the hole 3.13 closed by accident, and it was live on the version this
project pins.** Measured here: `trusted(r"\codex.EXE")` returned that path on 3.12.13 and
`None` on 3.14.7. A rooted path with no drive is `.\codex.EXE` one directory up — it names
the root of whichever drive the process is on, which `--cwd` hands to the user's project and
never to this code — and the cwd rule cannot catch it, because a drive root is not the
working directory. So the function states the rule with `splitdrive` rather than inheriting
it: the same answer on every Python. A security predicate whose answer arrives from the venv
is not a predicate, which is the general form of this and the reason it is written down.

**And the development interpreter is declared.** `.python-version` holds `3.12` — what CI
installs and what the README promises `uv` fetches — so `uv sync` builds one venv rather than
whichever the machine had. `requires-python` deliberately stays `>=3.12`: the pin is for
reproducibility, not a claim that 3.13+ is unsupported, and the suite is green on both.

**Reopens if** development wants a newer interpreter — the pin is one line, and what makes
moving it safe is that both versions are green today. The gap this leaves is named rather
than closed: **nothing runs the suite on 3.14**, so the next divergence is found by whoever
builds a venv without the pin. A second CI leg (`windows-latest` at 3.14, ~35 s) is the
answer if that happens twice; one occurrence is not yet evidence of a pattern.

**Update 2026-08-15, the same day:** the leg exists — the owner chose not to wait for a
second occurrence. `ci.yml` now runs `windows-latest` twice, 3.12 and 3.14, the second
named in the workflow for what it is: one leg past the pin, so the next divergence is
found by a machine that runs on purpose rather than by whoever builds an unpinned venv.

### 2026-08-09 — The idle pill goes 168 → 205, because the bar label is worth more than the mock

§02 of the v2 design gives the pill a status word — `Bar label · Plex Mono 11 · +.1em` —
and §03 heads its idle mock `168 idle`. Those two do not both fit. At 11 px mono with
`.1em` tracking, `LISTENING` is 71 px; a 168 px pill has 110 px for the meter and the
label together, and twelve bars need 70 of it. The spec's own HTML resolves this by
making the meter `flex:1`, so a longer word simply eats bars: at `LISTENING` there is
room for six of the twelve.

Decided: **the pill widens, the meter keeps all twelve bars, and the label gets a slot
reserved at its widest word.** The meter is the instrument that answers *am I being
heard*; one that halves the moment you start speaking is a worse lie than a wider pill,
and it fails in exactly the state the meter exists for. Reserving at the widest label —
rather than fitting the current one — is the rule §07 already states for the Ask chip's
countdown numeral, and for the same reason: a fitted slot moves the meter's right edge
on every state change. `PILL_W` is now derived from its parts (`METER_X + METER_W +
LABEL_GAP + LABEL_SLOT_W + LABEL_PAD`), and `LABEL_SLOT_W` is computed over the label
strings themselves, so adding a longer one widens the pill instead of silently drawing
through the twelfth bar.

The cost, stated: the all-day footprint grows 37 px, against a redesign that explicitly
protected it ("within a few pixels of today's 152×40"). What makes that acceptable is
where the pixels land — `_sync_dock` pins the right edge, so the pill grows leftward,
which is the direction it already grows every time a panel docks to it. Nothing moves
under a hand that was already aiming at something.

**Reopens if** the owner reads 205×40 as too much desk. The fallback is not a narrower
slot but shorter words — the label set is one dict, and dropping `LISTENING` to `HEAR`
buys back 35 px without touching the meter.

### 2026-08-08 — Listen joins the menu: a third control, for consoles that keep the keyboard

Reported from the desk: working inside a Hyper-V console, the guest owns the keyboard,
so the arm hotkey never reaches Flow — and the mouse still does. The pill click toggles
capture there already, but it is the one control in the app with no words on it, and
the welcome card that says what it does is shown once.

Decided: **Listen / Stop listening** is the first row of the right-click menu, running
the same `_toggle` as the pill click and the hotkey. It is knowingly a third control
for one action — the argument that kept "Was a command" off this menu — but that
refusal was about severing a control from the utterance it acts on, and Listen acts on
the microphone, which is everywhere the menu is. The label names the flip, as the mode
toggle's does; first row, because it starts the cycle the rest of the menu acts on.

Reopen bar: none. A row costs a row, and the menu's stall budget (§9) is unchanged by
one entry.

### 2026-08-06 — Four from one screenshot set, and a fallback that had never once fired

Five observations from one converse session, reported together. Four were real defects and
three of them shared a shape: the app knew something and did not say it.

**The fallback chain was unreachable on a timeout, which is the only failure that ever
happens.** AGENT-09 gave the walk one deadline sized `max(timeout, largest floor)` — the
size of a *single* call — so the first candidate could spend all of it and a timeout left
nothing for the second. That was known and defended: a genuine hang is one of four failure
modes, and the other three cost milliseconds. **The trace says the frequencies were
backwards.** Every ask failure in `~/.flow/diag.jsonl`, 11 of 11 across five weeks, is
`reason:"timeout"` at ~20.3 s with `provider:null`, against 39 successes spread over all
three CLIs. The rare fourth case was every case, and with codex, claude and kiro-cli all
installed and answering — 14.9 s, 19.2 s, 13.8 s when run directly — the fallback had never
rescued a single call. Reproduced on the real functions with two fakes at a 3 s budget:
`hangs timed out after 3s; then no time left to try answers`, 3 156 ms, no answer, while
the second CLI would have answered in 50 ms.

Decided: the budget covers the candidates it has to walk — each one's own wait, plus the
`ABANDON_SEC` reap an abandoned call costs. The half of AGENT-09 that stands is the half
about *division*: the per-call wait is still the user's number and is never shared out,
because shortening every call turns a slow but working codex into a failing one. The bill
is stated rather than hidden — at the shipped defaults a walk where nothing answers is
20 + 5 + 20 + 5 + 60 = **110 s**, so `--cli-timeout` is how long any one CLI may take, not
how long Ask may take. The owner took that trade on being shown both numbers. *Reopens if*
a real session waits out the full walk and the owner would rather have had the failure at
20 s — the fix then is a per-pool ceiling, not a return to a budget the size of one call.

**A fallback that rescued a call left no trace of the rescue.** `_invoke_any` dropped every
earlier reason the moment a later CLI answered, so a codex timeout saved by kiro-cli was
indistinguishable from a run where codex was never installed — in the note, in the trace,
everywhere. That is invariant 5 read from the other side: a refusal is not silent because
something else eventually said yes. `skipped` is now carried out to the session, which
names it in one sentence ("answered via kiro-cli, after codex timed out after 20s") and
records the categories in the trace. It is an out-parameter rather than a third return
value because the two-tuple is unpacked at fifteen call sites that do not care.

**kiro-cli's tool narration was rendering as the answer.** The cleaner was built on a
2026-08-02 capture taken from a prompt that ran no tools, and "the marker is on the first
line only" is not a property of the output — it is a property of that prompt. Re-measured
2026-08-06 in a real workspace: kiro-cli prefixes *everything it says* with `> `, so with
tools the old strip took the marker off the preamble and handed the card 350 characters of
grep receipts above the answer. The obvious repair — cut at the last marker — passes that
capture and breaks `test_an_angle_bracket_inside_an_answer_survives`, an answer that quotes
a shell line. So the landmark is the narration itself, matched as a shape the way the
Credits line already is: everything up to the last tool receipt is the CLI talking about
its own work. It decides where the answer began and never removes a line from inside one.
1 145 chars → 359 on the live call. *Reopens if* an answer about kiro-cli's own output gets
cut short — the fix then is asking the CLI for machine-readable output, not a cleverer
shape.

**A conversation on screen was larger than the conversation the CLI was given.** Converse
inherited `refine`'s 1 500-character context budget, and that number's whole justification
is about rewrites: enough thread to know what "the other endpoint" refers to. A
conversation *is* its context, and P9's card renders every turn — so a constant sized for
disambiguation was deciding how much of a visible conversation the CLI could remember, and
replies are stored as turns too and are the longer half, so every answer evicted a
question. Rebuilt from the owner's own session: five turns on the card, 1 765 characters,
three of the four prior turns sent. The CLI then answered "I only have this conversation,
which started with a question about a step-by-step plan" — an accurate report of what it
was handed, read as amnesia inside one session. `ASK_CONTEXT_CHARS = 8 000` is a separate
number from the rewrite's, still under half the 20 000-char store so R8's bound holds, and
**the cut now says so when it happens**: the silence was the worse half. *Reopens if* a
session outruns 8 000 in ordinary use — per-workspace CLI session resume is the better fix
and is still unbuilt, blocked on `codex exec resume` rejecting `-s read-only`.

**"nothing to send - the draft is empty", under a chip that says Ask, at a card showing
five turns.** Not a defect in the refusal — the draft really was empty — but three names
for two things, and it read as Flow denying the conversation it was displaying. Converse
now says "nothing to ask - say a question first".

The fifth observation is unresolved: the filler dropper ate "Thank you.", and separately a
10-character "Thank you." reached the CLI as a question and cost 3.2 s and a thread turn.
Left open pending the owner saying which of the two they meant.

### 2026-08-06 — An answer that outlives its mode is held, not dropped and not forced

Reported from a screenshot: a dictate draft with the conversation card standing behind it.
The sequence was ask in converse, clear, switch to dictate, start a new draft from the
clipboard — and the CLI, still working, answered several seconds into a mode that had
moved on. `Pill._swap_surfaces` promises exactly one window is up afterwards and that was
true when it ran; the reply branch then reopened the card on top of the bubble, from
behind, with nothing on screen explaining it. The owner's words were **"both modes got
activated"**, which is precisely what two windows look like.

**The defect was a comment that proved the wrong thing.** The branch read "converse only,
by construction: `Session.send()` returns "" in dictate mode and never asks". That is
true, and it constrains where a question *leaves*. It says nothing about where the answer
*arrives* — and between the two sits the whole 4-20 s the CLI takes, during which one
keypress changes the mode. A constraint on the send path was being spent on the receive
path.

**Decided: file it, do not raise it, and say so.** `ConversationCard.answer` takes
`surface=`; the text lands on the card whichever mode is up, and the window opens only
when the card is the surface that mode owns. In dictate the bubble gets `ANSWER_HELD`
instead, through `surface()` rather than `note()` because the case that needs the line
most is the one with nothing on screen to paint it on. Reading the answer costs one mode
switch: `_swap_surfaces` opens the card and it renders what it was given while down.

**Both alternatives were worse and both keep one window.** Dropping the answer at the mode
switch — the way `new_conversation` drops one at the operation id — throws away seconds of
CLI work and a question that is spent with them, for a user who switched mode to do
something else while waiting, which is the reasonable thing to do. Forcing the card up is
the reported defect. Holding is the only option that keeps the one-window rule *and* the
answer.

**Scope, taken with it:** `_tick`'s crash handler had the same bug in the other direction
— an exception in a converse frame surfaced the *bubble* over the card. It now goes
through `front`, falling back to the bubble, because the surface is a plausible thing to
have just crashed and a raise from inside that handler breaks the `after()` chain it
exists to protect.

The event drain moved out of `_frame` into `Pill._pump_events` to make any of this
testable. Nothing about it changed; it was unreachable without driving a real Tk frame,
which is why a routing rule with an invariant on it had no test to break.

Reopen bar: an answer held and then wanted *without* a mode switch — a chip on the bubble
that opens the card would be the smaller fix, and nobody has asked for one yet.

### 2026-08-06 — A voice from this decade, and the first output path that leaves the machine

Every voice Flow could speak with was from 2013, and no amount of installing better ones
changed that. The mechanism is worth recording because it closes off the obvious fixes:
Windows 11 installs Ava, Guy and Sonia as MSIX packages, each shipping a **complete and
valid SAPI token** — and then registers that token into `HKLM\SOFTWARE\Microsoft\Speech
Server\v11.0`, a hive that **does not exist**, behind an engine CLSID present in **no COM
store**. A registry-wide search for the token name returns nothing. WinRT `AllVoices`
returns the same six OneCore voices. There is no registry hack and no alternate API; the
voices are Narrator-only by construction. Measured against a machine carrying all three.

So: two optional engines, chosen per voice from one menu. `flow/piper.py` (`[voice]`) is
local neural speech. `flow/edge.py` (`[edge]`) reaches the natural voices through
Microsoft's service. R16 holds for both — they are extras, and a default install still
fetches three packages, the reading already applied to `[cuda]`.

**The part that is a real narrowing, taken deliberately.** `[edge]` is the first *output*
path in Flow that sends anything off the machine: the text of each spoken reply, to be
voiced. It was declined once on exactly that ground and then asked for again, which is the
bar this project sets for reopening. It ships because the alternative is not "a local
version of these voices" but "these voices, never" — they are on the disk and unreachable.
The narrowing is bounded and is stated in three places rather than implied: no API key or
account, no audio and no workspace path, and nothing at all unless someone has installed
the extra *and* selected one of its voices. `product.md`'s non-goal on cloud ASR is
untouched — this is not ASR, and audio never leaves.

**Two engines, two audiences, and neither is a stopgap.** The owner's framing when the
narrowing was confirmed, and it is the reason both stay: **most organisations will never
install `[edge]`** — a policy that forbids sending text to a third-party service forbids
this, whatever the guarantees around it — so **Piper carries the load**, and it has to be
good enough to be the primary engine rather than a fallback that exists to be replaced.
`[edge]` is for individuals, who can make that call for themselves and mostly will.

That is why the README leads with Piper, why `speak.py`'s module docstring lists it first,
and why effort spent on Piper's voice quality is not effort spent on a compatibility
shim. Reading `[edge]` as "the good one" and Piper as "the offline compromise" would get
the investment backwards.

**Reopen conditions.** (1) A local engine reaches the natural voices — then `[edge]` is
redundant and should go. (2) The service starts requiring a key or an account, which would
put it back under R9's flat prohibition rather than beside it. Note that neither is "Piper
turns out to be good enough": Piper being good enough is the plan, not the exit.

**The 2013 voices are hidden, not removed.** They vanish from the menu as soon as any
better voice is installed, and come back when none is — a default install has neither
extra, and dropping SAPI outright would leave it silent. Hidden is not withdrawn: `pick`
resolves against the full list, so a profile naming `Microsoft George` still gets it.

One bug worth keeping, because it was found by ear and not by a test. The first `[edge]`
build crackled continuously while the words stayed perfectly clear. A PyAV audio plane is
padded to an alignment boundary, so `bytes(plane)` returns more than was decoded — 1216
bytes for 576 samples, 64 bytes of stale buffer on every one of 133 frames — and all of it
was being written to the device. `edge.pcm` now slices to `samples * 2`, and
`TestEdgePadding` exists so it cannot come back silently.

### 2026-08-05 — The conversation should leave something behind: two verbs, one file

Converse mode answers questions now (below, part 1), and once it did, the mode grew a
gap nobody had specified: **a conversation worth having produced nothing that survived
it**. `Thread` holds what was sent, Recent holds the last twenty of everything — both in
memory, both gone on quit, and neither is a record of what the speaker judged worth
keeping, because neither was *chosen*. The owner asked for the chosen half: talk as long
as you like, mark the good parts as they go by, and have them at the end.

**This is the reopen on part 3 below, taken deliberately.** That entry says the words are
never stored and names the next shape as "an opt-in on-disk history, **never a default
one**". What ships is opt-in twice over rather than once: keeping a note is one explicit
act, writing the file is a second, and a session that takes a dozen notes and is never
told to wrap up leaves the disk untouched — asserted, not intended. The file lands in the
**workspace**, the folder the user already pointed Flow at, never in the settings folder.
Item 65's test that a whole session leaves that folder as it found it keeps passing, and
a second test now says the same thing about this feature by name.

Decided, five parts:

1. **Two verbs, and the shapes were priced before they were admitted.** `keep note` bare
   keeps the exchange on screen — the answer *and* the question that produced it, because
   an answer filed without its question reads a week later as an assertion from nowhere.
   `note that X` keeps dictated words. `wrap up` turns everything kept into one file.
   All three fire **0 times across the 580 real EdAcc utterances** (`command_bench.py`).
   A fourth was written and rejected by that same run: `remember that X` hit a real
   sentence, so it is not in the grammar, and a test pins its absence.
2. **The payload form is gated on an empty draft**, and that gate is the feature's one
   real risk closed. With a draft held, every word being said is going into it — "note
   that the API is deprecated" is a sentence somebody is dictating into a prompt, and
   swallowing it would take the words out of the thing they were being written into. An
   empty draft is exactly the state an answer arrives into, so the shape is unambiguous
   precisely where it is useful.
3. **Flow does not summarise the notes.** R9, not modesty: Flow never generates content
   on its own — it is the microphone, the editor and the courier (product.md). The
   document is what was kept, in the order it was kept, verbatim. It therefore needs no
   CLI, cannot hallucinate, costs no wait, and works on a machine with nothing on PATH.
   Somebody who wants the CLI's reading of it asks for one, which is an ordinary converse
   question and already works.
4. **The menu is the floor, and the reason is measured.** The card's chip row already
   runs to **377 px of `CARD_W`'s 420**; one more chip at its narrowest takes it to 433,
   off the card. So Keep and Wrap up are menu rows. The split that falls out is better
   than the row would have been: Keep is frequent and one tap, and Wrap up — the only act
   in this app that puts the user's words on disk — earns a deliberate two-step.
5. **No workspace, no file.** With nothing set there is no folder this app has any
   business choosing on somebody's behalf, so the notes stop at the card, where Copy
   already takes them. That is Lite's answer to the same question (the last inch is the
   clipboard) rather than a degraded version of it.

**Also settled here: P9's text, which LOOP_PLAN raised at the close of round ten and did
not take.** product.md still called converse mode a prompt workshop and scoped it to
"discuss and refine prompts only, nothing more" — written 2026-08-01, and made false four
days later by part 1 below, which removed `WORKSHOP` from the ask path precisely so the
mode would answer general questions. The mode has answered anything since; only the
document disagreed. Rewritten to say what it does.

**Three defects found by instruments, and two of them by the instrument built for this.**
Worth recording because in each case the written grammar was right and the *spoken* one
was not, which is the gap this product exists inside:

- **"keep note" decodes as "Keep node."** `selfdrive --only notes` failed on it the first
  time it ran, while the same words handed straight to the decoder came back correct —
  the padding and the gate are the difference. Admitted as a mis-hearing, but only where
  English will not carry a competing reading, because "keep node three drained" is a
  sentence and the first fix swallowed it.
- **"wrap up" decodes as "Wrap-up"**, 4 times in 6, because a two-word phrase with
  nothing around it is where Whisper reaches for the compound noun. It passed three
  selfdrive runs and failed the fourth. `follow[- ]?up` had already learned this.
- **A bare `note X` swallowed "note taking is not the same as listening"**, found by a
  new empty-draft adversarial set. The corpus could not have found it: EdAcc is
  conversation and contains "node" zero times in 580 utterances, so it scored the note
  grammar a perfect 0 whatever that grammar admitted. An absence of evidence was reading
  as evidence, and the fix was to write the developer sentences down where the harness
  runs them.

`command_bench.py` gained two columns for this: `MISROUTES` now counts the new kinds
(a grammar priced only on the kinds that existed when the harness was written scores
every new verb as free), and precision is measured against an **empty draft** as well as
a held one, since two of these routes are only reachable with no draft at all.

**And one in the harness itself, whose first fix was wrong and passed anyway.** Every
`Driver` loaded the decoder onto the GPU and none was ever released, so a full
`selfdrive` run exhausted CUDA around the sixth scenario. It presented as three
CLI-shaped failures with no CLI involved, and every affected scenario passed alone —
which is exactly what makes a leak read as flake.

The first fix closed each session between scenarios, and the suite went 62/72 → **73/73**,
which looked like proof and was not. `Session.close` gives back what `start()` took — the
microphone, the worker, the speaker, the preload — and deliberately **not** the models:
the path it was written for is quit, where the process is ending anyway, and the path
that does release them is R8's idle unload, which runs while the session is still alive.
Dropping the last reference does not help either, because CTranslate2 returns nothing on
`__del__`. Measured over four create/close cycles, `close()` + `gc.collect()` read
**+3870, +5179, +5195, +5219 MiB** — a plateau, not a release. The suite went green
because the plateau happened to sit under the ceiling for this mix of scenarios, which is
a different fact from the one the fix claimed.

Calling `asr.unload()` as well reads **+104, +371, +341, +357 MiB** over the same four
cycles, and the whole run now sits flat at its baseline scenario to scenario. **This is a
harness fix and not a product one**: the app runs one session per process and already
releases on idle (R8, `IDLE_UNLOAD_SEC`), while the harness is the only thing that builds
a dozen sessions in one interpreter. Three runs since: 73/73, 72/73, 72/73, the single
failure each time being the pre-existing `insert draft before release notes` decode
flake, which passes in isolation.

**Recorded because the near-miss is the lesson.** A green suite was taken as evidence for
a mechanism nobody had measured, and the number that would have caught it — GPU memory
after teardown — took four minutes to obtain. `measure-before-and-after` applies to
instrument fixes exactly as it does to product ones.

**Reopen bars.** If a user reports a sentence swallowed by a note verb, the payload form
loses its remaining ground and becomes bare-only. If a third mis-heard spelling of "note"
turns up, the list stops growing and decode-time command bias is the honest fix instead.
If anyone asks where their notes went after a crash, the buffer gets a periodic write —
and that, not this, is the point where the never-stored stance would actually be spent.

### 2026-08-03 — First contact: three users, one verdict, five roots, and a surface split

Flow met its first three outside users on v0.2.0 and all three reached the same
verdict: garbage. The verdict is earned, and it is not twelve bugs — every complaint
traced to five roots, each with a named mechanism:

1. **Ask answered nothing.** `session.WORKSHOP` told the CLI that every converse
   utterance was "a prompt they will hand to an agentic coding CLI… do not carry out
   the task it describes", from the most recency-weighted position in the prompt — so
   "how are you" came back as a bug-report lecture. Codex obeyed the instruction
   perfectly, which is the proof the instruction was wrong: the users were asking to
   *learn about the project*, and nobody was workshopping a prompt.
2. **CLI furniture read as UI.** Output stripping exists only for kiro-cli; codex's
   diff stats and "Create PR" hints rendered verbatim in the bubble — users quoted
   them back as buttons that would not click — and were stored into the thread as
   context for the next answer.
3. **Chips genuinely failed clicks.** `_render` deletes the whole canvas — every chip
   and its click binding — and repositions the window on every partial decode, every
   countdown second, every activity frame. A chip being aimed at is destroyed
   mid-aim, and the codebase already records one drawn-but-dead chip as precedent.
4. **The prompt vanished, uncommanded.** Auto-ask is ON by default: a 4 s pause sent
   the words, the send cleared the draft, converse mode has no sent card and no Put
   it back, and Clear draft left the thread, the reply and the mode alive — "clear
   prompt did not start fresh", mechanism by mechanism.
5. **The trigger word fails every voice but the owner's, silently.** The decoder is
   never told the word exists (the hotwords parameter is wired and nothing ever puts
   the send word in it), the match is exact whole-utterance equality, and a miss
   lands in the draft as text with no note. Recognition was measured at exactly one
   mic; the 2026-07 accent audit predicted exactly this failure.

A 1251-test suite sat green through all five because it measures mechanisms, and
nothing measured a stranger's first five minutes. First contact is now an instrument:
the reopen bar on everything below is what the next stranger reports.

**The reference was studied before deciding.** Wispr Flow — the app the users
compared against — was examined live on this machine plus its docs. What it teaches:
surfaces are separated by job (dictation streams into the focused app; drafting is a
separate, opt-in scratchpad); recovery is a history, not a rescue chip; idle presence
is a neutral, near-invisible dash; states are taught once in a hold-speak-release
tutorial rather than by legend; and its one flaw shared with Flow is that an
unrecognized spoken command types itself as text, silently — the near-miss note below
makes Flow better than the reference at precisely that point.

Decided, six parts:

1. **Ask answers.** WORKSHOP comes out of the ask path. The CLI is told to answer,
   grounded in the workspace ("consult it if the question concerns it"); the
   improve-this-prompt instruction survives only in Refine, where a prompt exists.
2. **Two surfaces, two jobs.** Converse gets its own conversation card — the question
   pinned above the answer it produced, older turns in a scrolling viewport (the Help
   sheet already built the machinery), chips Ask / Use this / Copy / New conversation.
   The draft bubble becomes dictation-only and never shows a reply again. Amber and
   violet stop being one card's moods and become window identities; the pill
   simplifies toward mic states. New conversation clears thread, card and reply in
   one act — no more half-clear.
3. **Recent, in memory only.** The last ~20 utterances, questions and answers behind
   the right-click menu, with Copy. Gone on quit, nothing on disk — the
   words-never-stored stance holds by construction. Reopen: if quit-loss actually
   bites someone, the next shape is an opt-in on-disk history, never a default one.
4. **Auto-ask stays ON in converse, with a first-entry notice.** With the question
   pinned, a premature send no longer loses anything. The first converse entry states
   on-screen that a pause sends, and names the setting that turns it off. Reopen bar:
   one stranger reporting a surprise send flips the default to OFF.
5. **The trigger word is taught, not assumed.** The configured send words join the
   final decode's hotword bias; a near-miss — phonetically close, not equal — draws a
   note naming the word. Notify, never execute: the standing refusal to let edit
   distance fire a send stands. The recording kit gains the trigger words, so
   recognition across accents becomes measurable instead of assumed.
6. **A welcome card, shaped like a tutorial.** First launch only: the arm gesture,
   right-click for the menu, the trigger word by name, and what the colors mean — the
   load-bearing lines that today print to a console no GUI user reads. The Help sheet
   gains the legend permanently.

Also in the round: codex furniture measured and stripped (and never stored into the
thread), the chip teardown replaced with a persistent row proven by a synthetic
click-storm instrument, Edit gaining a scrollbar and its earlier-lines hint while
editing, a new-draft-from-clipboard menu entry, and the draft body opening Edit on
click — the promise `help.exits_note` already makes. Spec'd as round ten, items 60–72.

### 2026-08-03 — The download must not trail the repo: v0.2.0 now, and links that cannot go stale

The owner caught it in one sentence: anyone downloading the current release misses the
updates. Measured: the only tag is **v0.1.0**, main is **53 commits past it**, and
item 59's release workflow fires on tag push alone — deliberately, so nothing refreshes
the zip by itself. The stale binary is not just short on features (trigger words, the
workspace switcher, the long-draft fixes, the kiro-cli adapter all postdate it); it
predates **round nine's security fixes**, so the download ships flaws the repo already
fixed. Decided, three parts:

1. **Cut v0.2.0 now.** Bump `pyproject.toml`, tag, and let release.yml do what item 59
   built it to do: gate on the suite, build, smoke-run, publish. The auto-generated
   notes are then replaced with a written summary of what changed since v0.1.0 — every
   claim traceable to this file, `docs/architecture.md`, or a commit message, with a
   plain line telling v0.1.0 holders to replace the binary and why.
2. **README download links go through `releases/latest/download/flow-windows-x64.zip`.**
   The asset name stays constant across versions precisely so this URL stays true
   forever — a link written today serves whatever is newest, so no old clone or cached
   page can hand someone a stale zip again. The measured size figures in the README are
   re-taken from the v0.2.0 asset, since the first-build numbers stop being true the
   moment a second build exists.
3. **The standing cadence: a round that changes behavior owes a tag.** Not per commit —
   per landed round (or accumulation of owner-visible change), the version bumps and
   the tag ships. The release costs one command now; staleness costs a stranger a
   binary with known, already-fixed defects. Reopen bar: if tagging ever stops being
   one command — the workflow gains steps a human must babysit — the cadence gets
   re-decided rather than silently skipped.

*(Noted for a future round, not this release: nothing in the app tells a user which
version they hold — a `--version` flag and a line in Help would let "am I current?" be
answered without guesswork. Parked in NEEDS_YOU rather than smuggled into a release.)*

### 2026-08-02 — Five words from the owner: the round-seven residue decided

1. **The selfdrive tripwire resolves as a fix, not a quarantine.** `capitalize
   sameer` — two flakes in two runs, both following sustained CPU load — stops
   traveling the speaker-to-microphone loop: that one check feeds its cached SAPI
   wav directly to the decoder, keeping the learning-promotion assertion (the only
   live one the gate has) while removing the room, the fan, and the acoustic
   variance that made a marginal decode flip. The other 63 checks keep the acoustic
   loop; the gate stays 64/64-shaped.
2. **The marker nickname stands.** The pill's badge says `kiro`; the menu, the
   notes, and the Help sheet say `kiro-cli` in full. A marker is a glanceable tag,
   not an identifier, and in a four-CLI product the short form collides with
   nothing.
3. **The bubble anchors below as a fallback.** Above by default exactly as today;
   below only when the pill sits high enough that "above" has no room. A fallback,
   not a mode — tooltip behavior, and the 36-placement geometry harness from item
   42 is the instrument that proves both directions.
4. **P10 ships as shape (b): the head window.** A reply renders its first lines —
   the ones triage reads — with "… N more lines" at the foot, and Copy / Use this
   carry the whole text as they already do. Shape (c), a real reading viewport, is
   deliberately not built: a bubble that becomes a document reader drifts Flow from
   courier toward viewer, against its own non-goals; if the desk ever proves
   artifacts get read in-bubble, the Help sheet's viewport is the clean upgrade
   path. §8's row tells the truth it now has.
5. **The 39-second workshop turn is parked on the owner's hands**: real kiro-cli
   turns in the MCP workspace decide it. If the owner finds themselves always
   tapping codex there, a per-workspace CLI preference becomes an entry; if the
   wait reads as the employer-brain thinking, it does not.
Alongside, a Rules line from a twice-paid papercut: loop commit messages are
written via bash heredoc, never PowerShell here-strings — two rounds each mangled
a subject to `@` and repaired it by amending an unpushed tip against Rule 3's
letter; the sentence ends the class.

### 2026-08-02 — kiro-cli's 20-second wall, the six-character marker, and the cut bubble

Three findings from the owner's first real workshop session on kiro-cli, the first
one measured to its root: **"ask failed (kiro-cli timed out after 20s)" is
structural, not flaky.** The identical one-line call measured **4.3 s in a bare
directory and 35.8 s inside a workspace whose `.kiro` settings declare MCP servers**
— kiro-cli spawns the project's MCP servers on every `chat` invocation (uvx-resolved,
cold), and Flow's global `TIMEOUT_SEC` = 20 executes the call at second twenty, every
time, in exactly the workspaces the workshop is for. No flag skips MCP startup
(`--require-mcp-startup` exists; its inverse does not), and Flow altering the user's
kiro settings is out of bounds — Flow does not reconfigure other tools. So:
1. **Per-CLI timeout.** `Cli` entries gain `timeout_sec` (default: the global 20);
   kiro-cli ships at **60**, basis 35.8 measured plus headroom. The timeout note
   already names the CLI and the seconds; §8's TIMEOUT_SEC row gains the reason a
   CLI may need more than the constant. The honest residue, stated: ~36 s per turn
   in MCP-heavy workspaces is kiro-cli's startup cost, not Flow's — the cure lives
   upstream (a persistent serve mode someday, or a trimmed server list), and until
   then the pin menu makes "codex for this workspace" one tap.
2. **The marker gets a display alias.** "kiro-cli" at 8 characters overflows item
   15's 6-character bound and falls back to `ASK` — the owner read that as "Kiro is
   not captured". Cli entries gain a marker alias ("kiro"), bounded at 6; the menu
   and the notes keep the full name.
3. **The bubble can still leave the screen by position.** Item 37 capped its height;
   the owner's screenshots show the top border cut off at the display edge — the cap
   bounds size, nothing clamps placement. The bubble's geometry must be clamped
   inside the work area at every pill position, instrumented the way item 37 was:
   position measured at the corners, before and after.

### 2026-08-02 — The long-draft incident: no draft may disable its own rescue

A very long dictation took down five layers in a chain, live at the owner's desk: the
bubble re-lays-out the whole draft on every partial, so render cost grows with the
draft until the UI thread stalls; the stall overflows the mic queue (the measured
~16 s modal-menu stall, reproduced by rendering); the dead mic decodes nothing, so
`IDLE_UNLOAD_SEC` unloads the models; now every spoken rescue is impossible — "boom"
needs a decode, a decode needs the models, the models need the mic the render killed
— while the visual rescue, the Send chip, sits below a bubble that grew past the
screen because the draft path (unlike the artifact-reply path) has no height cap.
The keyboard send hotkey worked the whole time and was announced once, at startup,
in a console. Four fixes, one principle — a draft must never disable its own exits:
1. **The chips never leave the screen.** The bubble gets a height cap; the draft
   body scrolls inside it, tail-following like a terminal; the chip row is pinned
   and always visible. The artifact path already scrolls — the draft path joins it.
2. **Render cost stops growing with the draft.** Only the visible tail is laid out
   per partial (a bounded window of characters, "… N earlier lines" above), so a
   two-hour dictation costs what a two-minute one costs — invariant 7 extended to
   rendering. Instrumented before fixing: render time vs draft size, the number
   that proves the stall and then proves it gone.
3. **When voice is down, Flow says what still works.** Mic overflow with a
   non-empty draft, or a model unload with a non-empty draft, emits one note naming
   the living exits with the *registered* combos ("voice is down — Ctrl+Alt+Enter
   still sends; click the draft to edit"), from `hotkeys.chosen`, never hardcoded.
4. **Copy joins the menu.** Lite built `_copy`; full mode gets it as a menu entry —
   the universal, model-free, target-free exit that would have ended this incident
   in one tap.

Found by item 35's live verification and measured against a synthetic shim: a `.cmd`
launcher — the shape `npm -g` writes on Windows — forwards `%*` through cmd.exe,
which stops at the first newline. Every prompt `refine.py` sends is multi-line, so a
CLI installed that way receives the framing and none of the user's text, **exits 0,
and answers fluently about nothing** — the silent-wrong-answer class this project
ranks above every other failure. This machine's `codex` and `claude` are native
builds and unaffected, which is exactly why the *repair* cannot be picked here: the
candidate that matters (stdin delivery) is per-CLI — codex was measured hanging on
an open stdin, which is why `_invoke` pins `stdin=DEVNULL` — and there is no real
npm shim of either CLI on this machine to verify against. So the decision is staged
by what can be proven today:
1. **Refusal ships now.** A resolved CLI whose executable ends `.cmd`/`.bat` is
   refused *before* the call, with the cure in the message: install the native
   build. Loud beats fluent-and-wrong; verifiable today with the four-line shim.
2. **The repair ships as a capability, off by default.** A per-CLI `stdin_ok` flag:
   where verified true on a machine that has that install, the prompt travels on
   stdin and a shim becomes usable — item 35's verify-per-machine discipline, not a
   guess. codex stays argv with the measured hang recorded beside it.
3. README's agent-CLI paragraph gains one sentence steering installs to native
   builds and saying Flow will refuse a shim and why.

### 2026-08-02 — Workspace grounding: proven by a misfire, so the ground becomes
### switchable and named at egress

First real workshop session, biggest prompt yet — asked about one project while the
workspace was still grounded in another, set at the command line and forgotten. The
answer was project-specific enough that the mismatch surfaced and the CLI asked for
clarification. Two readings, both recorded: **the grounding works** — a grounded
answer is concrete enough to be *wrong about the wrong project*, which is the
opposite of generic and substantially answers the A/B desk question — and **the
accepted stale-workspace cost came due on day one**: the mitigations (startup line,
mode-switch note) are transient signals for persistent state, the same
lesson already paid for twice (the converse marker, the editor's countdown hold).
Two fixes, one decision:
1. **The moment of egress names the ground.** The asking note becomes
   "asking codex · acme…" (workspace leaf name, bounded length), and the
   converse countdown's final state carries it too — visible at the only moment it
   matters, when the question leaves.
2. **Settings ▸ Workspace ▸** — a recents submenu, radio-checked like the trigger
   presets, one tap to switch, "(not set)" included. Every path that arrives via
   `--cwd` joins an additive `workspaces` recents list in the profile (bounded, most
   recent first, cap small per the menu-stall budget). No free text — new paths
   enter once via the flag, then live in the list.
Nailed here so the spec cannot guess: **switching the workspace starts a fresh
conversation** — the thread is cleared and the note says so. A workspace switch is a
topic switch; carrying one project's conversation into another project's grounding
is precisely the contamination this decision exists to end. Rejected again, same
reason as the original decision: inferring the "right" project from the target
window — a wrong guess is worse than a visible, tappable setting.

Owner review of the shipped Help and menu (items 30/31): structure and presets
approved, two changes, one ratification. **(1)** "goose" leaves the shipped preset
list — taste, not measurement; its gate numbers stand, and the thirteen passed-but-
unshipped words remain swappable without new measurement. **(2)** Commands &
shortcuts stops opening a text file in Notepad — the owner's words: "which is not
help" — and renders inside Flow itself: a read-only window in the app's own visual
idiom (the bubble's palette), fed by the *same* generated data — `help.COMMANDS`,
the live `hotkeys.chosen`, the currently configured trigger words — regenerated on
every open, with item 30's route-checked tests surviving unchanged. Presentation
moves; the guarantees do not. Constraints that survive: R16 (tkinter only), Flow's
windows stay out of the activation chain (a help window needs no keyboard — mouse
scroll and a click-to-close are the whole interaction), and the text-file path is
removed rather than kept as a second surface. "Open the guide" still opens the
README in the browser — the long-form guide belongs where links work. **(3)**
Ratified: the round's flagged deviation stands — "Was a command" stays a chip on the
bubble beside the utterance it rescues, with no menu duplicate. Spec'd and built as
item 32 by the next session, from this entry.

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
