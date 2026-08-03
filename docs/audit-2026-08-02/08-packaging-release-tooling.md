# Focus area 8 — Packaging, release, scripts, tests, and documentation

## Scope and release contract

Reviewed `pyproject.toml`, `uv.lock`, `packaging/`, `.github/workflows/release.yml`, all support
scripts/benchmarks/probes, the 38 test modules, and current README/product/architecture/decision/
roadmap documents. A release should be tested before tagging, reproducible from immutable
inputs, attestable, and representative of all claimed platforms.

## Findings

| ID | Severity | Finding |
|---|---|---|
| RELEASE-01 | Medium | There is no PR/push gate and no real cross-platform Lite CI. |
| RELEASE-02 | Medium | Build actions/tools/backends and model inputs are not immutably pinned. |
| RELEASE-03 | Medium | Published binary lacks signing, checksums, SBOM, and provenance. |
| RELEASE-04 | Medium | `slim.py` can ignore failed destructive/maintenance subprocesses. |
| RELEASE-05 | Medium | Developer ingestion scripts insufficiently bound or isolate hostile inputs. |
| RELEASE-06 | Low | Public docs and recorded acceptance evidence have drifted. |
| RELEASE-07 | Medium | The source distribution embeds benchmark audio and session transcripts. |

## Detailed evidence and remediation

### RELEASE-01 — Tests run too late and on one OS

The only workflow, `.github/workflows/release.yml:16-28`, runs on version tags and
`windows-latest`. Normal pull requests/pushes have no enforced suite; claimed macOS/Linux Lite
surfaces are never imported or started on their native OS.

**Fix:** add required PR/push jobs for supported Python versions on Windows/macOS/Ubuntu, with
locked install, unit tests, compile/import, `--help`, and a headless or virtual-display Lite
startup smoke. Keep bundle construction Windows-only but make release depend on that tested
commit. Add targeted native clipboard/Send tests on Windows.

### RELEASE-02 — Release identity can move

Workflow action tags at `.github/workflows/release.yml:27-28` are mutable; PyInstaller at
`.github/workflows/release.yml:49-50` is unversioned; hatchling is unconstrained at
`pyproject.toml:34-36`; runtime declarations at `pyproject.toml:15-19` are lower bounds; and the
ASR model may download without immutable revision/checksum (`packaging/flow.spec:20-23`).

**Fix:** SHA-pin actions, exact-pin build tooling in a release lock, use `uv sync --frozen`,
pin/verify model artifacts, record Python/OS/tool/model identities, and separately test the
supported range promised to direct installers.

### RELEASE-03 — Artifact trust metadata is missing

The release publishes an unsigned executable without a separately published SHA-256, SBOM,
or build provenance; the workflow has write-capable repository permissions.

**Fix:** minimize job permissions, use a protected environment, sign the executable, publish
checksums plus SPDX/CycloneDX SBOM and SLSA-compatible provenance, and verify them in a clean
download smoke test.

### RELEASE-04 — Maintenance script fails open

`scripts/slim.py:69-72`, `scripts/slim.py:93-100`, and `scripts/slim.py:117-132` invoke tools
without consistently treating nonzero results as fatal. A cleanup/rebuild step can fail while
the script continues and reports a misleading completed state.

**Fix:** resolve tools safely, use checked subprocess results, stop at the first failed
precondition, print the exact retained/recoverable state, and add temp-repository integration
tests for every failure stage. Keep deletion targets explicitly contained.

### RELEASE-05 — Developer inputs need resource and path containment

`scripts/fetch_accent_data.py:127-148` permits unbounded downloads and lacks immutable dataset/
audio checksums; `scripts/fetch_accent_data.py:203-217` uses caller-provided tags in paths;
`scripts/ingest_recordings.py:76-111` decodes volunteer/native media without size/duration or
process isolation. Several PowerShell helper scripts interpolate repository paths into source,
and `scripts/slim.py:69-72` invokes bare `uv`.

**Fix:** validate/contain path components, stream with byte/time limits, pin sources and verify
hashes, sandbox native media decoding, encode rather than source-interpolate PowerShell values,
and execute trusted absolute tool paths. These scripts are developer-only but operate on
untrusted or destructive inputs.

### RELEASE-06 — Documentation is not tied to CI evidence

README claims conflict with Lite and release implementation, test counts are stale, and product
acceptance tables combine missing, old, and implementation-only evidence. This makes release
readiness difficult to audit.

**Fix:** generate test/platform/artifact facts in CI, date and identify every acceptance run,
link results to the exact commit/model/corpus, and keep unmet gates explicitly open.

### RELEASE-07 — Source artifact is dominated by internal data

*Re-measured 2026-08-03, and the finding was understated in both its numbers and its cause.*

The cited `pyproject.toml:38-39` is `[tool.hatch.build.targets.wheel]` with `packages =
["flow"]` — the **wheel** target, and it is correctly narrow, which the 172,905-byte wheel
proves. The defect is that no `[tool.hatch.build.targets.sdist]` block exists at all, so the
sdist falls back to "everything not ignored".

A rebuild with `uv build` measured a **172,905-byte wheel** against a **15,524,140-byte source
tarball** — roughly **90×**, not the 54× first reported. What fills it, by uncompressed bytes:

| Path in the sdist | Files | Bytes |
|---|---:|---:|
| `.claude/` | 184 | 16,668,150 |
| `.bench/` | 82 | 14,695,822 |
| `tests/` | 39 | 612,909 |
| `docs/` | 23 | 572,508 |
| `flow/` | 19 | 484,204 |

`flow/` — the only directory a source distribution of this package needs — is 3% of what ships.
The severity is raised to **Medium** on the first row rather than the size: `.bench/` holds the
owner's decoded speech and `.claude/` holds session transcripts, so this is a privacy leak
wearing a size complaint's clothes, and it is the larger of the two that nobody had noticed.

**Fix:** add a `[tool.hatch.build.targets.sdist]` block that excludes `.claude/`, `.bench/`,
`tests/`, and planning/internal material, or publish benchmark data separately. Add artifact
content and compressed-size assertions.

## Strengths and validation

The repository has a locked development environment, a structured PyInstaller spec, a bundled
`--help` smoke check, 1,089 passing unit tests, and unusually thorough product/architecture
documentation. `compileall` and CLI help passed. Bandit reported no high findings; pip-audit
reported no known vulnerability in installed third-party packages (the local package was
skipped). Those checks do not address agent authority, native UI behavior, or mutable build
inputs, which require the controls above.
