# Dedicated review — Performance and resource behavior

## Method and result

A dedicated performance-only agent turn examined all eight product surfaces after the general
failure review. It used bounded targeted microbenchmarks plus static queue/thread/process/I/O
analysis. No source files were changed. Measurements are host-specific signals, not universal
service-level guarantees.

## Findings

| # | Severity | Finding | Evidence / canonical report |
|---:|---|---|---|
| 1 | Medium | Absent-target phonetic planning scales linearly and runs repeatedly on the UI pump. | Direct scan, **words**: 50 ms/2k, 440 ms/20k, 4.40 s/200k, 44.83 s/2M; full route 184 ms/2k and 1.79 s/20k. The canonical report measures the same scan in **characters** — ~5× smaller numbers for the same draft. [DRAFT-04](02-draft-routing-history.md#draft-04--missing-target-search-freezes-interaction) |
| 2 | High | Repetitive-text change diffs are quadratic. | 65 ms/500 words, 268 ms/1k, 1.10 s/2k, 6.91 s/5k. [DRAFT-06](02-draft-routing-history.md#draft-06--repetitive-text-diffs-are-quadratic) |
| 3 | High | Final/rescue/result decode deques and per-frame draining are unbounded. | A 30 s float32 utterance is ~1.92 MB; 100 queued finals retain ~192 MB before inference overhead. [CAP-04](01-capture-transcription.md#cap-04--decode-queues-have-no-admission-bound) |
| 4 | High | Provider output caps run after `communicate()` buffers everything. | [AGENT-03](03-agent-refine-converse.md#agent-03--output-bounds-are-applied-after-allocation) |
| 5 | Medium | Sequential providers multiply the operation wait budget. | [AGENT-09](03-agent-refine-converse.md#agent-09--fallback-has-no-overall-deadline) |
| 6 | Medium | Re-arming creates duplicate preload waiters; shutdown leaks resources. | 100 blocked arm/pause cycles produced 100 preload threads; live speech host measured ~84 MB working set. [CLI-02/05](07-cli-lite-lifecycle.md) |
| 7 | Medium | Speech pipe reads/writes can block indefinitely. | [SPEECH-02](04-speech-output.md#speech-02--host-protocol-read-can-hang-a-watcher) |
| 8 | Medium | Native popup stalls the only pump while capture remains armed. | Queue capacity corresponds to the documented ~16 s stall edge. [DESKTOP-08](05-desktop-ui-os-integration.md#desktop-08--ui-thread-latency-has-more-than-one-source) |
| 9 | Medium | Clipboard restore uses one sleeping thread per send. | 300 mocked pastes created 300 threads in 52 ms. [DESKTOP-09](05-desktop-ui-os-integration.md#desktop-09--clipboard-restore-creates-unbounded-short-lived-threads) |
| 10 | Medium | Voice enumeration blocks first-window startup. | Cold measurement 439 ms; timeout permits 15 s. [SPEECH-05](04-speech-output.md#speech-05--voice-enumeration-blocks-startup) |
| 11 | Medium | Configuration/diagnostic whole-file I/O occurs synchronously. | [PERSONAL-05](06-personalization-diagnostics.md#personal-05--user-controlled-files-have-no-byte-or-latency-budget) |
| 12 | Medium | Source distribution includes benchmark payloads and session transcripts. | Rebuilt 2026-08-03: wheel 172,905 B; sdist 15,524,140 B, ~90×. `.bench` 82 files/14.7 MB and `.claude` 184 files/16.7 MB raw. [RELEASE-07](08-packaging-release-tooling.md#release-07--source-artifact-is-dominated-by-internal-data) |

## Resource-budget recommendations

- Establish budgets for UI tick work, decode items/audio bytes, provider stdout/stderr bytes,
  overall provider deadline, preload/speech/clipboard thread counts, and local file size/I/O time.
- Make overload visible and recoverable; never silently discard a final utterance merely to meet
  a benchmark.
- Add adversarial repeated-text and slow-component soak tests to CI, keeping microbenchmarks in
  a non-flaky trend job where appropriate.

## Negative findings

No additional performance defect was identified in the bounded microphone queue itself,
latest-wins partial scheduling, bounded draft renderer, calibration sample windows, hotkey
registration, help generation, PyInstaller onedir/model exclusion, or release workflow runtime.
