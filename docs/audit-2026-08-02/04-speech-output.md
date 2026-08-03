# Focus area 4 — Speech output and half-duplex control

## Scope and contract

Reviewed `speak.py`, Session ownership of the speaker, PowerShell host startup/protocol,
voice enumeration, stop/replace behavior, and tests. The core contract is half-duplex:
capture must remain closed for the entire current reply and reopen only for that reply's
verified completion.

## Findings

| ID | Severity | Finding |
|---|---|---|
| SPEECH-01 | Medium | An old watcher can clear speaking state for a replacement reply. |
| SPEECH-02 | Medium | Watcher reads can block indefinitely on a silent/stuck host. |
| SPEECH-03 | Medium | Session shutdown does not own/close the speech host. |
| SPEECH-04 | High | PowerShell resolution is vulnerable to current-directory hijacking. |
| SPEECH-05 | Medium | Voice discovery imposes synchronous cold-start cost. |

SPEECH-04 is remediated with the shared executable-resolution control in
[focus area 7](07-cli-lite-lifecycle.md#cli-01--current-directory-executable-hijacking).

## Detailed evidence and remediation

### SPEECH-01 — Replacement generation race

*Citations un-swapped 2026-08-03: `330-352` is `_watch` and `399-417` is `say`; the finding had
them the other way round.*

`say()` at `speak.py:399-417` starts no new watcher while `_speaking` is already true. The
watcher at `speak.py:330-352` can have queried `Ready` for reply A just before reply B replaces
it, then clear the shared speaking flag after B begins.

**Impact:** capture reopens during B and can transcribe Flow's own voice.

**Fix:** assign a monotonically increasing generation to every `say()` and `stop()`. Every
protocol command and watcher captures its generation; only the current generation may clear
state. Deterministically interleave A-ready, B-say, and A-watcher in a regression test.

### SPEECH-02 — Host protocol read can hang a watcher

The line read at `speak.py:346` is blocking. If PowerShell remains alive but never emits the
expected reply, the daemon watcher cannot restore the half-duplex state.

**Fix:** put host I/O behind a bounded protocol reader or async queue, enforce response
deadlines, terminate/restart a nonresponsive host, and produce a visible recoverable failure.
Test a live host that accepts input but never writes a newline.

### SPEECH-03 — Incomplete resource ownership

`speak.py:426-436` provides close behavior, but `Session.close()` at `session.py:580-588`
does not call it. Exceptional/repeated/embedded runs can leave the persistent PowerShell
process and watcher resources behind.

**Fix:** make Session the idempotent owner of speaker shutdown and invoke it from a top-level
`try/finally`. Bound all joins and cover repeated close, active speech, and failed-host cases.

### SPEECH-05 — Voice enumeration blocks startup

`speak.py:47`, `speak.py:165-196`, and `speak.py:218-245` enumerate even when no requested
voice needs validation; `__main__.py:233-257` also needs the count before UI creation. Cold
enumeration measured 439 ms and the allowed timeout can delay the first window for 15 seconds.

**Fix:** start with a default/unknown voice state, warm the list asynchronously through one
owned task, and update the UI when ready. Add cold and hung-host startup budgets.

## Strengths and validation

Speech text is base64-encoded before it enters PowerShell, so the review found no direct
text-to-PowerShell injection. Stop/replace is intentionally modeled, and the host is separate
from the UI pump. The remaining concurrency behavior needs deterministic generation tests;
the general unit suite passed.
