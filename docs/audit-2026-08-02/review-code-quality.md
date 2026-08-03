# Dedicated review — Code quality and correctness

## Method and result

A specialist agent reviewed all 19 runtime modules, packaging/release configuration, all 38
test modules, support scripts, and product/architecture documentation. It independently ran
the complete unit suite: 1,089 tests passed. This pass changed no source files.

Passing tests do not establish the product invariants at several native, concurrent, and
adversarial boundaries. The following issues were retained after deduplication into the
surface reports.

| Theme | Severity | Canonical finding(s) |
|---|---|---|
| Partial-word edit corruption | High | [DRAFT-01](02-draft-routing-history.md#draft-01--exact-edit-targets-are-substrings) |
| False-success paste followed by Enter | High | [DESKTOP-02](05-desktop-ui-os-integration.md#desktop-02--submission-ignores-the-actual-sendinput-result) |
| Speech replacement generation race | Medium | [SPEECH-01](04-speech-output.md#speech-01--replacement-generation-race) |
| Clear bypasses Session state | Medium | [DESKTOP-05](05-desktop-ui-os-integration.md#desktop-05--ui-clear-violates-state-ownership) |
| Primary workshop chips clipped | Medium | [DESKTOP-07](05-desktop-ui-os-integration.md#desktop-07--primary-actions-can-be-clipped) |
| Profile wrong-type crash | High | [PERSONAL-01](06-personalization-diagnostics.md#personal-01--schema-number-is-checked-field-schema-is-not) |
| Nested Markdown fences destroyed | Medium | [AGENT-07](03-agent-refine-converse.md#agent-07--cleanup-strips-meaningful-inner-fences) |
| Missing cross-platform PR CI | Medium | [RELEASE-01](08-packaging-release-tooling.md#release-01--tests-run-too-late-and-on-one-os) |
| Mutable build inputs | Medium | [RELEASE-02](08-packaging-release-tooling.md#release-02--release-identity-can-move) |
| Incomplete shutdown ownership | Medium | [CLI-02](07-cli-lite-lifecycle.md#cli-02--cleanup-ownership-is-incomplete) |
| Clipboard erased on failed write | High | [DESKTOP-03](05-desktop-ui-os-integration.md#desktop-03--clipboard-transaction-loses-user-data) |
| Public/source documentation drift | Low | [CLI-04](07-cli-lite-lifecycle.md#cli-04--lite-documentation-drift), [RELEASE-06](08-packaging-release-tooling.md#release-06--documentation-is-not-tied-to-ci-evidence) |

## Negative findings

No additional correctness issue was retained in decode option ownership, attributable filtering,
hotkey registration, calibration calculations, lexicon parsing/atomic replacement, diagnostic
event bounds, help generation, or PyInstaller collectors. Draft/Thread history is generally
bounded, and several asynchronous Refine results already have useful stale-operation guards.

## Testing implication

The missing tests are mainly negative/interleaving tests: targets inside larger words, partial
native injection counts, focus changes, reply replacement races, wrong-type-but-valid JSON,
large/repetitive drafts, and exceptional lifecycle exits. Each canonical report lists concrete
regression cases.
