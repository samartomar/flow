# Dedicated review — Potential failures and reliability

## Method and result

A specialist agent traced failures across capture, decode, draft revisioning, native injection,
persistence, provider processes, speech IPC, UI pumping, and shutdown. It focused on concurrency,
partial failure, stale work, overload, and recovery—not merely exception handling. No files were
changed.

## Failure map

| Surface | Principal failure modes | Canonical report |
|---|---|---|
| Capture/decode | transcript paired to newer audio; stale audio across pause; silent device status; backlog; drop without recovery | [Capture/transcription](01-capture-transcription.md) |
| Draft/routing | substring destruction; stale rescue; missing revision guard; oversized context | [Draft/routing/history](02-draft-routing-history.md) |
| Agent operations | mutable execution context; non-finite timeout; failed Ask recovery; output/process overload | [Refine/Converse](03-agent-refine-converse.md) |
| Speech | replacement watcher race; blocking protocol; host not closed | [Speech](04-speech-output.md) |
| Desktop | unsafe terminal paste; Enter after failure; clipboard loss/borrowed restore; Clear/layout failure | [Desktop integration](05-desktop-ui-os-integration.md) |
| Personal data | wrong-type profile crash; invisible persistence failure; slow/oversized local files | [Personalization](06-personalization-diagnostics.md) |
| Lifecycle | hostile executable lookup; leaked threads/processes; duplicate preload; unnecessary provider probes | [CLI/lifecycle](07-cli-lite-lifecycle.md) |
| Delivery | late/single-OS CI; mutable inputs; maintenance script fail-open; hostile developer inputs | [Packaging/release](08-packaging-release-tooling.md) |

## Highest-risk event chains

1. **Stalled UI → capture overflow → nonrecoverable transcript:** synchronous planning or a
   native popup stops the pump; the microphone queue fills; the UI later shows only a note,
   leaving the user without the P2 recovery action.
2. **Partial native paste → unrelated submission:** Ctrl-V insertion is blocked/partial; the
   code ignores the count; Enter acts on existing text in a shell or another application.
3. **Overlapping utterances → wrong rescue:** mutable `_last_audio` is replaced before an old
   final arrives; rescue then re-decodes audio from a different utterance.
4. **New draft activity → stale rescue/refine result:** incomplete generation/revision guards
   let old intent act against newer state.
5. **Persistence appears successful → restart loss/crash:** callers accept in-memory changes
   despite a failed save, while independently malformed but valid JSON can prevent startup.

## Reliability acceptance needed

Use deterministic schedulers/fakes to enumerate result-order permutations; impose explicit
queue, byte, time, and thread budgets; make each resource single-owner and idempotently closable;
and verify a visible recovery action for every intentional drop/refusal. The existing unit suite
passes but does not cover these event chains.
