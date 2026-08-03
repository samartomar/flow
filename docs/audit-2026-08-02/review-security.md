# Dedicated review — Security, privacy, and trust boundaries

## Method and result

A specialist agent reviewed all runtime and operational surfaces against the documented local/
provider/OS boundaries. Static analysis was supplemented by local help inspection for the
installed Codex, Claude, and Kiro CLIs and a safe Windows executable-resolution probe. No
adversarial provider prompt or malicious binary was executed; no files were changed.

## Confirmed priorities

| Security theme | Severity | Canonical finding(s) |
|---|---|---|
| Agent tools/config/workspace authority exceeds the visible prompt boundary | High | [AGENT-01](03-agent-refine-converse.md#agent-01--the-documented-ai-boundary-is-not-the-executed-boundary) |
| Current-directory executable hijacking | High | [CLI-01](07-cli-lite-lifecycle.md#cli-01--current-directory-executable-hijacking) |
| Integrated/ambiguous terminals fail open | High | [DESKTOP-01](05-desktop-ui-os-integration.md#desktop-01--terminal-safety-is-incomplete-and-too-late) |
| Enter can follow failed paste | High | [DESKTOP-02](05-desktop-ui-os-integration.md#desktop-02--submission-ignores-the-actual-sendinput-result) |
| Full-format clipboard data loss | High | [DESKTOP-03](05-desktop-ui-os-integration.md#desktop-03--clipboard-transaction-loses-user-data) |
| Prompt in argv and ambient secret inheritance | Medium | [AGENT-02](03-agent-refine-converse.md#agent-02--prompt-and-secrets-cross-ambient-os-boundaries) |
| Oversized thread disclosure | Medium | [DRAFT-05](02-draft-routing-history.md#draft-05--thread-tail-can-exceed-its-own-cap) |
| Unbounded child output | Medium | [AGENT-03](03-agent-refine-converse.md#agent-03--output-bounds-are-applied-after-allocation) |
| Mutable ASR provenance | Medium | [CAP-07](01-capture-transcription.md#cap-07--model-provenance-is-not-immutable) |
| Release supply-chain gaps | Medium | [RELEASE-02](08-packaging-release-tooling.md#release-02--release-identity-can-move), [RELEASE-03](08-packaging-release-tooling.md#release-03--artifact-trust-metadata-is-missing) |

## Boundary conclusion

The architecture currently understates provider authority: Refine/Ask start agent-capable CLIs
inside the chosen repository with ambient configuration, tools, services, environment, and
possibly network/write access. That gap must be resolved in code and documentation before Flow
claims a prompt-only boundary.

The desktop boundary also cannot claim “paste, never execute” until ambiguous terminals fail
closed and native insertion counts/focus are checked atomically.

## Negative and accepted findings

The review found no `shell=True`, `eval`, unsafe pickle loading, direct prompt-to-shell
interpolation, raw speech-text PowerShell injection, general keystroke logging, or raw dictated
words in bounded diagnostics. Auto-Ask, spoken physical disclosure, and cross-provider fallback
are documented product choices, but first-use disclosure and single-provider defaults would make
egress more predictable.
