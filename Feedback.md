
# Improvements I would make

## 1. Correct the trust-boundary claim

The architecture diagram says the out-of-process band means **“nothing leaves the machine.”** But `refine()` and `ask()` call an agent CLI, and verification selects `codex` and then `claude`. The document does not establish that those backends are local-only. The user’s draft, question, or conversation context may therefore leave the machine, depending on the configured CLI.

This is the most important correction because it affects user trust.

Replace the current statement with something precise:

> Audio, the personal lexicon, and the profile remain local. Refine and Converse may submit transcript text and conversation context to the configured model provider. The active provider must be visible to the user.

Also document these boundaries separately:

- **Always local:** microphone buffers, profile, lexicon, local edit routing, SAPI.
    
- **Potentially remote:** Refine draft, Converse question, thread context.
    
- **Network-dependent but not user-content transmission:** first-time model downloads.
    
- **External desktop boundary:** clipboard and the focused target window.
    

The UI should visibly show something like:

> Converse · Codex · networked

or:

> Refine · Local model · offline

Do not imply local-only operation merely because the application starts a local CLI executable.

---

## 2. Add operation identity and stale-result protection

Every Refine or Ask operation starts a subprocess, and results are collected later using separate locks. The architecture documents the locks but does not describe request IDs, draft revisions, cancellation, or stale-result rejection.

That creates a possible race:

1. The user starts Refine on draft A.
    
2. The user changes the draft to B, changes mode, recalls another prompt, or starts another operation.
    
3. The result for A arrives.
    
4. The old result is applied to the current state.
    

Even when the state machine currently makes this difficult, correctness should not depend on incidental UI sequencing.

Add an operation token:

```python
@dataclass(frozen=True)
class OperationToken:
    operation_id: int
    kind: Literal["refine", "ask"]
    draft_revision: int
    mode: str
    source_hash: str
```

When a result returns:

- Apply it only if the operation is still current.
    
- For Refine, verify that the source draft revision/hash is unchanged.
    
- For Ask, verify that the thread turn is still current.
    
- Otherwise discard it and emit a visible `stale_result` note.
    
- Cancel or terminate the previous operation when superseded.
    
- On quit, terminate the full subprocess tree, not just the immediate child.
    

This is a small addition with substantial reliability value.

---

## 3. Reconcile “nothing is dropped silently”

The microphone queue is bounded and **drops the oldest blocks when full**. Yet one of the architecture invariants says nothing is dropped silently. The documented `drop` event concerns ASR filtering, not necessarily microphone queue overflow.

Queue overflow should produce:

- A monotonically increasing dropped-block count.
    
- An event containing the approximate milliseconds lost.
    
- A user-visible warning when it affects an active utterance.
    
- A diagnostic counter even when it does not affect the current draft.
    

This matters because the UI thread can stop pumping while the native right-click menu owns the modal loop. The audio callback can continue filling the queue during that period.

Also decide what should happen while the menu is open:

- Temporarily pause capture, or
    
- Continue capture but explicitly report overflow.
    

Silently losing the beginning of an utterance would violate the architecture’s strongest user-facing invariant.

---

## 4. Fix long-draft Refine semantics

`refine.MAX_CHARS` is 2,000, and the architecture says that beyond this limit **only the tail is sent**, cut at a sentence boundary. It does not say what happens to the omitted prefix or whether the user is warned.

This is dangerous. A Refine operation must not appear to process the whole draft when it has seen only its tail.

Choose one explicit policy:

### Recommended

Preserve the prefix and refine only the selected tail:

```text
[untouched prefix]

[refined final section]
```

The UI should say:

> Refined the final 1,942 characters. Earlier text was left unchanged.

Alternative acceptable policies are:

- Refuse refinement and ask the user to select a section.
    
- Chunk the draft and refine each section with a final consistency pass.
    
- Use a larger-context backend when configured.
    

What should not happen is silent truncation followed by replacement of the complete draft.

---

## 5. Reconcile automatic Ask with the explicit-send invariant

The architecture says:

> Nothing sends itself. Send is always explicit.

But Converse automatically submits after `AUTO_ASK_SEC = 4`. The document explains that asking is less irreversible than pasting, but the invariant remains written as an absolute statement.

There are two valid directions.

### Better default

Make Converse submission manual by default, with optional automatic submission:

```text
Converse send:
  Manual
  Auto after 4 seconds
  Adaptive
```

### Acceptable alternative

Keep automatic submission but rewrite the invariant:

> Flow never pastes into another application without explicit Send. Converse may submit to the configured model after a visible, cancellable countdown.

The current four-second value is based on one recording. That is not strong enough evidence for every speaker, accent, or thinking style. A better approach is:

- Start with manual submission.
    
- Record the user’s natural within-utterance pause distribution.
    
- Offer an adaptive timeout after enough samples.
    
- Always show a countdown and allow immediate cancellation or extension.
    

This is especially important because submitting to a model provider may transmit text outside the machine.

---

## 6. Do not impose a fixed three-sentence limit on every Ask response

`ASK_SENTENCES = 3` is described as enough for an answer and caveat. That may be suitable for ordinary conversational answers, but it conflicts with this important flow:

> Based on our conversation, give me a complete reusable prompt.

A good prompt can require several paragraphs, requirements, constraints, examples, and acceptance criteria.

Use response profiles rather than one universal ceiling:

|Request type|Response policy|
|---|---|
|Normal conversational question|Concise, around three sentences|
|Explanation requested|Moderate detail|
|“Give me a prompt for this”|Complete standalone prompt|
|Structured output requested|Honor requested structure|
|Read-aloud response|Concise spoken summary plus complete text|

The best behavior for prompt generation is:

1. Render the complete prompt in the bubble.
    
2. Speak only a short confirmation or summary.
    
3. Provide Copy, Send, and Refine controls.
    

Do not read a 500-word generated prompt aloud unless the user specifically requests it.

---

## 8. Separate model transport from Refine and Converse policy

`refine.py` currently owns both rewriting and conversational Ask, although the implementation correctly keeps `ask()` distinct from `refine()`.

Keep that semantic separation, but introduce a small backend interface:

```python
class ModelBackend(Protocol):
    def complete(
        self,
        request: ModelRequest,
        cancel: threading.Event,
    ) -> ModelResult:
        ...
```

Then structure it as:

```text
Refiner ─────┐
             ├── ModelBackend ── CodexCLIBackend
Converser ───┘                 ├─ ClaudeCLIBackend
                               └─ Future local/API backend
```

Benefits:

- Refine and Converse retain different system instructions and validators.
    
- Provider selection becomes explicit.
    
- CLI invocation, timeout, cancellation, version collection, and errors live in one place.
    
- A local model or direct streaming API can be added without modifying the state machine.
    
- Tests can use a deterministic fake backend.
    

Do not turn this into a large plugin framework. One protocol and two policy classes are enough.

---

## 9. Improve first-response latency with streaming

Current measured behavior is approximately:

- Refine: around six seconds.
    
- Ask: around eight to ten seconds.
    
- Only after completion is the reply rendered and spoken.
    

That is functional, but it will not feel like ChatGPT voice. The most valuable UX improvement after correctness is:

> Begin rendering immediately, and begin speaking after the first complete sentence.

A future streaming path could be:

```text
Model backend
   │ token chunks
   ▼
sentence buffer
   ├── UI partial reply
   └── completed sentence → TTS queue
```

Important constraints:

- Keep half-duplex unless true echo cancellation is intentionally added.
    
- Stop queued speech when the user presses Interrupt.
    
- Do not speak incomplete sentences.
    
- Maintain a single operation ID so late chunks from cancelled answers are discarded.
    

The existing complete-response CLI backend should remain as the fallback.

---

## 10. Harden clipboard restoration and target selection

The real-mouse test and `WS_EX_NOACTIVATE` correction are excellent. The architecture correctly recognizes that classifying the window and delivering the keystroke are separate concerns.

Two additional race conditions should be closed.

### Foreground target changed

Immediately before sending Ctrl-V:

```python
current = GetForegroundWindow()
if current != expected_target:
    refuse("The target window changed before Send.")
```

Do not paste into whichever application happens to have focus after the original target was captured.

### User copied something during the 0.6-second restore period

The clipboard-restore thread currently sleeps and restores the old clipboard.

Use `GetClipboardSequenceNumber()`:

1. Capture sequence number.
    
2. Write Flow text.
    
3. Capture the new sequence number.
    
4. Before restoring, verify the sequence is unchanged.
    
5. If the user or another application changed the clipboard, do not overwrite it.
    

Also provide an optional **secure send** mode because clipboard managers and cloud clipboard synchronization may retain prompt contents even after Flow restores the old value.

---

## 11. Resolve the model preload contradiction

The thread table says the preload thread warms both tiers. Later, the loading section says a session that never finalizes an utterance never pays for `small.en`, and the diagram associates `small.en` loading with the first final decode. Both cannot be true simultaneously.

Choose and document one actual policy:

### Recommended balance

- On arm: preload `base.en`.
    
- On first detected speech: begin background loading of `small.en`.
    
- On final: use `small.en` if ready; otherwise show “loading final model” and wait.
    
- After five idle minutes with no draft: unload both.
    

This gives partial responsiveness without allocating the full final model merely because the application was armed.

The code and architecture diagram should then be verified against the same measured memory timeline.

---

## 12. Complete the human/accent release gate

The testing architecture itself admits the remaining gap: synthetic SAPI speech cannot validate accents, and the human layer requires recordings that do not yet exist.

Before making broad recognition claims, measure at least:

- Final transcription word error rate.
    
- Command-intent recognition rate.
    
- False command activation rate.
    
- Literal target-match success.
    
- Detail retention after Refine.
    
- Time to correct a misrecognition.
    
- Auto-Ask premature submission rate.
    
- User-rated readability of the refined prompt.
    
- End-to-end latency.
    

The previously discussed 3–5 speakers per L1 anchor group is appropriate as an **early smoke benchmark**, not evidence of broad accent coverage.

The highest-risk metric is not ordinary WER. It is:

> How often does normal dictation accidentally become a command or semantic operation?

A wrong word is visible and editable. A false delete, rewrite, or externally submitted Ask has a greater impact.

---

## 13. Add local, redacted diagnostics

The architecture has useful events and measured constants, but production troubleshooting will need a persistent local trace.

Record by default:

```text
timestamp
session state
route selected
operation ID
draft revision
model tier
decode duration
refine/ask duration
provider and CLI version
queue overflow count
stale result count
device reconnect
target-window mismatch
clipboard restore skipped
error category
```

Do **not** record by default:

- Raw audio.
    
- Full transcripts.
    
- Draft contents.
    
- Conversation text.
    
- Clipboard contents.
    
- Personal lexicon terms.
    

Provide a one-click **Export diagnostics** action that lets the user explicitly include content when needed.

---

## 14. Pin the components that influence measured behavior

The architecture measures exact Whisper behavior and also relies on Codex or Claude CLI responses. However, model revisions, CLI versions, and selected remote models are not part of the documented verification identity.

Record and, where practical, pin:

- `faster-whisper` version.
    
- CTranslate2 version.
    
- Hugging Face model revision and checksum.
    
- Codex/Claude CLI version.
    
- Selected provider model.
    
- Prompt-template version.
    
- Profile schema version.
    
- Windows build and audio-device identity.
    

Otherwise, a benchmark can change even when your repository does not.

For remote-model backends, exact reproducibility may be impossible. In that case, label the result honestly:

> Verified against provider/model/version reported on this date.

---

## 15. Improve microphone device recovery

The current health pump detects that a PortAudio stream stopped delivering blocks, but the architecture does not describe automatic recovery when:

- A USB microphone is unplugged.
    
- A Bluetooth headset changes profile.
    
- The Windows default input device changes.
    
- The device disappears during sleep/resume.
    
- The sample rate changes.
    

Add a device recovery state:

```text
HEALTHY
  → STALLED
  → REOPENING
  → RECOVERED

or

  → NEEDS_USER_SELECTION
```

Calibration should be keyed to the actual input device. A noise-floor and confidence profile measured on a USB microphone should not automatically be applied to a laptop microphone.

# Documentation contradictions to correct immediately

These do not all require code changes, but a “runtime reference” should not leave them ambiguous. The document explicitly positions itself as the source to read before changing code.

|Current statements|Required resolution|
|---|---|
|“Nothing leaves the machine” while Codex/Claude CLI handles Refine and Ask|Document the real provider/network boundary|
|“Nothing sends itself” while Converse auto-submits after four seconds|Narrow the invariant or change the default|
|“Nothing is dropped silently” while the mic queue drops oldest blocks|Emit overflow evidence|
|Preload warms both models, but `small.en` supposedly loads only on first final|Select one lifecycle and measure it|
|Long Refine input is reduced to the tail|Define exactly what happens to the omitted prefix|
|Ask is constrained to three sentences|Add an exception for prompt/artifact generation|
|Volunteer recordings are tracked in Git|Move raw recordings to controlled private storage|

# Recommended implementation order

## First: trust and data safety

1. Correct local/remote claims.
    
2. Remove raw volunteer recordings from Git.
    
3. Show active model provider.
    
4. Clarify production audio retention.
    
5. Make auto-Ask behavior explicit and configurable.
    

## Second: correctness under races

1. Add operation IDs and draft revisions.
    
2. Discard stale Refine/Ask results.
    
3. Manage subprocess cancellation and shutdown.
    
4. Revalidate foreground target.
    
5. Protect clipboard restoration with the sequence number.
    
6. Surface microphone queue overflow.
    
7. Define safe long-draft behavior.
    

## Third: product acceptance

1. Run real-speaker accent tests.
    
2. Measure false command activation.
    
3. Test microphone unplug/reconnect.
    
4. Add long-running and cancellation chaos tests.
    
5. Pin model and CLI identities.
    

## Fourth: experience improvements

1. Dynamic Ask response length.
    
2. Prompt generation from the conversation.
    
3. Streaming reply rendering.
    
4. Sentence-level TTS.
    
5. Adaptive or user-configurable Ask timeout.
    
6. Optional GPU and local-model backends.
    

# What I would not change

Do **not** replace:

- The single-UI-thread rule.
    
- The pump model.
    
- The local fast path for literal edits.
    
- The bounded queues and histories.
    
- The non-destructive failure behavior.
    
- The real Windows focus/injection tests.
    
- The separation between `refine()` and `ask()` semantics.
    
- The half-duplex rule unless actual echo cancellation becomes a deliberate product investment.
    

Those are the strongest parts of the architecture.

## Final judgment

The architecture is **technically strong and already beyond prototype quality**, but it has several places where the written guarantees are stronger than what the documented behavior can support.

The most important improvement is not another model or feature. It is to make these four statements true and measurable:

1. The user always knows when text may leave the machine.
    
2. An old asynchronous result can never overwrite newer intent.
    
3. No audio or prompt content is truncated or dropped without evidence.
    
4.   

Once those are addressed, streaming and better voice UX become worthwhile improvements rather than polish layered over unresolved trust and race conditions.