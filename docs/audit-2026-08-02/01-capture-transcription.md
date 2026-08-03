# Focus area 1 — Capture, transcription, filtering, and accuracy

## Scope and product contract

Reviewed `audio.py`, `asr.py`, `clean.py`, the capture/decode portions of `session.py`,
their tests and probes, and the P1–P4 acceptance evidence in `docs/product.md` and
`docs/roadmap.md`. The critical contracts are that every transcript stays associated with
its utterance, pausing cannot replay old audio, bounded queues report recoverable loss, and
the documented accuracy gates are supported by current measurements.

## Findings

| ID | Severity | Finding |
|---|---|---|
| CAP-01 | High | Final decode results are not bound to their source audio. |
| CAP-02 | High | Pause/re-arm can leave captured audio that is decoded in a later interaction. |
| CAP-03 | Medium | PortAudio callback status is ignored, hiding input overflow/underflow. |
| CAP-04 | High | Decode work queues are unbounded. |
| CAP-05 | High | Queue overflow is reported but the promised recovery action is absent. |
| CAP-06 | High | P1/P3/P4 product acceptance remains failed or unproven. |
| CAP-07 | Medium | ASR model identity is mutable and not verified. |

## Detailed evidence and remediation

### CAP-01 — Result/audio association can cross utterances

`session.py:188-224` queues decode work without a durable utterance object, while
`session.py:296-299`, `session.py:966-988`, and `session.py:1314-1316` reuse mutable
`_last_audio`. Result handling and rescue at `session.py:1389-1394` can therefore pair a
final transcript with audio replaced by a later utterance.

**Failure scenario:** utterance A is decoding; utterance B finishes capture and replaces
`_last_audio`; A's result arrives and establishes rescue metadata pointing at B. “Was a
command” then re-decodes the wrong sound.

**Fix:** create an immutable utterance record containing ID, audio, capture timestamps,
decode generation, mode, and revision. Carry it through every queue/result and accept rescue
only for the exact record. Add a deliberately interleaved A/B test.

### CAP-02 — Pause/re-arm retains stale capture state

*Citation corrected 2026-08-03: `audio.py:102-106` is `Mic.stop()`, which closes the PortAudio
stream and touches no gate state at all. The finding stands on a different mechanism, below.*

`session.pause()` at `session.py:557-570` stops the microphone, stops any reply, and sets
`State.IDLE`. It does not establish an utterance boundary: `self._utter` keeps whatever blocks
it held, `gate.reset()` is never called — the two lines that do both sit together at
`session.py:1796-1797`, on the send path — and the 256-block `Mic` queue (`audio.py:65`) is
never drained, so blocks captured before the pause are still queued when the stream reopens.
Nothing consumes them in between, because `ui.py:1147` skips `session.tick()` entirely while
disarmed. Every piece survives to the next arm.

**Impact:** audio spoken before or during a pause can appear in the next transcript, breaking
user intent and privacy expectations.

**Fix:** make pause an atomic boundary: stop accepting callback frames, discard the active
utterance and preroll as specified, drain decode handoff state, increment a capture generation,
then re-arm. Test pause during speech, during finalization, and immediately before re-arm.

### CAP-03 — Audio device faults are silent

The callback in `audio.py:71-86` ignores its PortAudio `status` argument. Overflow can omit
speech while the UI continues as though capture were complete.

**Fix:** count and surface status flags in bounded diagnostics, mark the utterance degraded,
and offer retry instead of silently accepting it. Test status injection without logging audio.

### CAP-04 — Decode queues have no admission bound

The deques created and consumed in `session.py:188-230` can grow without a hard item or byte
limit if capture outpaces inference.

**Impact:** increasing latency and memory, with old work completing after the user's context
has changed.

**Fix:** impose a small generation-aware bound, cancel/supersede obsolete partial work, retain
only required finals, and expose a recoverable overload event. Load-test slow inference.

### CAP-05 — Bounded capture loss has no real recovery

The UI path at `ui.py:1191-1194` displays a note when frames are dropped but does not preserve
or retry the utterance. This falls short of P2's recoverability requirement.

**Fix:** invalidate the affected transcript and provide a concrete retry/re-record action,
or retain a safe bounded source segment for a retry. Test that a drop cannot silently become a
sendable “successful” draft.

### CAP-06 — Accuracy acceptance is not closed

The current roadmap records read-register P1 evidence only for three of four speakers,
conversational WER around 15.1–23.4%, the first Indian-English P3 speaker at 0/10 command
recall, and no current measured proof of the P4 ≥90% adaptive-acceptance requirement. A later
biasing implementation does not itself satisfy that outcome gate.

**Fix:** keep these as open product blockers, publish a single dated acceptance table tied to
model revision/hardware/corpus, and rerun all required speakers and registers. Do not replace
missing human cohorts with synthetic command tests.

### CAP-07 — Model provenance is not immutable

`asr.py:221-229` loads model names without revision/checksum; `diag.py:217-231` records but
does not pin them; `packaging/flow.spec:20-23` may download during a release build.

**Fix:** pin immutable upstream revisions, verify manifests/checksums, cache by identity, and
include that identity in diagnostics and release provenance.

## Strengths and validation

The gate/preroll design, decode-option ownership, attribution filter, and diagnostic bounds
are generally well separated and well tested. The unit suite passed. The command benchmark
reproduced its stored synthetic/adversarial/real-utterance routing figures, but it is not a
substitute for the missing human ASR acceptance cohorts. Microphone- and model-heavy human
checks were not rerun in this audit.
