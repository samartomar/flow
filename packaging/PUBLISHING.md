# Publishing Flow to Scoop and winget

Homebrew was the single most-upvoted request in the leading competitor's tracker. On
Windows the same request is Scoop and winget, and both want the same thing: a small file
that names a download, states its checksum, and says which executable is inside it.

The files are written and committed:

| File | What it is |
| --- | --- |
| `packaging/scoop/flow.json` | Scoop manifest |
| `packaging/winget/SamarTomar.Flow.yaml` | winget version manifest |
| `packaging/winget/SamarTomar.Flow.installer.yaml` | winget installer manifest |
| `packaging/winget/SamarTomar.Flow.locale.en-US.yaml` | winget en-US description |

**Submitted on 2026-09-24, as v0.6.1:** Scoop through Flow's own bucket,
[`samartomar/scoop-flow`](https://github.com/samartomar/scoop-flow), and winget as
[microsoft/winget-pkgs#440220](https://github.com/microsoft/winget-pkgs/pull/440220).
**The manifests are ready to send whenever they carry
a real checksum** rather than the literal string `FILL-ME-SHA256`, which holds the place
between a version bump and that version's release (step 5). The first was v0.6.0's,
filled on 2026-09-23 from the `.sha256` the release published and checked against a
download of the zip. The checksum is the one step that cannot be done from inside the
repository, because it is a fact about a file on a Releases page rather than a fact about
this tree.

Everything below runs on the owner's machine. None of it is automated on purpose: a
submission is a pull request to somebody else's repository under the owner's name, which
is not a thing CI should be able to do by itself.

## The path inside the zip, once, since three files depend on it

`flow.exe` is **not** at the root of `flow-windows-x64.zip`. It is at **`flow\flow.exe`**.

`packaging/flow.spec` names both the `COLLECT` directory and the exe `flow`, so PyInstaller
writes `dist/flow/flow.exe` (which is the path `release.yml` then runs `--help` against).
The workflow zips it with `Compress-Archive -Path dist/flow`, and a `-Path` that names a
directory without a trailing `\*` puts the directory itself into the archive. So the
archive's entries begin `flow/flow.exe`, `flow/_internal/...`.

Scoop's `bin` and winget's `RelativeFilePath` both say `flow\flow.exe` for that reason. If
a future spec renames the bundle, both files move with it.

## 1. Fill the checksum

**For a release built after this change**, the workflow uploads `flow-windows-x64.zip.sha256`
beside the zip, and the number can be read without downloading 142 MB:

```powershell
(Invoke-RestMethod https://github.com/samartomar/flow/releases/download/v0.6.1/flow-windows-x64.zip.sha256).Split(" ")[0]
```

**For v0.5.1 itself, and anything older, that asset does not exist** - the checksum step
was added after v0.5.1 was tagged, and a workflow cannot reach back into a release it did
not run for. Download the zip and hash it locally:

```powershell
(Get-FileHash .\flow-windows-x64.zip -Algorithm SHA256).Hash.ToLower()
```

Optional, and worth one minute: `gh release upload v0.5.1 flow-windows-x64.zip.sha256`
puts the missing file on the old release too, so the Scoop `autoupdate` block below has
something to read no matter which version somebody starts from.

Then put the number in both manifests. By hand it is two places - `hash` in the Scoop
manifest and `InstallerSha256` in the winget installer manifest - or in one line from the
repository root:

```powershell
$h = (Get-FileHash .\flow-windows-x64.zip -Algorithm SHA256).Hash.ToLower(); Get-ChildItem packaging\scoop\flow.json, packaging\winget\*.yaml | ForEach-Object { (Get-Content $_ -Raw).Replace("FILL-ME-SHA256", $h) | Set-Content $_ -NoNewline }
```

Then add the release's line to `PUBLISHED_SHA256` in `tests/test_packaging.py`, which is
what the suite checks the two manifests against. The number stays true because the release
workflow refuses to rebuild a release whose `.sha256` is out ("A published release is not
rebuilt"), and because GitHub's release immutability, on for this repository since
2026-09-23, refuses to replace a published release's files. The one exception is v0.6.0.
Its own job predates that step, and it was published before immutability was on, which
does not reach back. So re-running its job from the Actions page would still replace its
zip. Don't re-run it. Check that it took before submitting
anything: `git diff` should show those three changed lines and no remaining
`FILL-ME-SHA256`.

## 2. Scoop: Flow's own bucket

**Flow has its own bucket, [`samartomar/scoop-flow`](https://github.com/samartomar/scoop-flow)**,
made on 2026-09-24 from Scoop's `BucketTemplate`, with this manifest at `bucket/flow.json`.
Users run:

```powershell
scoop bucket add flow https://github.com/samartomar/scoop-flow
scoop install flow/flow
```

`ScoopInstaller/Extras` was not asked, for two reasons found while submitting. Scoop's
main bucket already has a `flow`, Facebook's JavaScript type checker, so Extras would
need another name; that is also why the install above says `flow/flow`. And Extras takes a
pull request only after its maintainers have approved a request issue. An own bucket
ships the moment it is pushed. The price is that nobody finds it without the `scoop bucket
add` line, which the guide and the bucket's README carry, and the `scoop-bucket` topic,
which lets scoop.sh index it.

The bucket keeps itself current. Its Excavator workflow runs every four hours: `checkver`
watches this repository's releases, and `autoupdate` rewrites the URL for the new version
and reads the hash from the `.sha256` asset rather than downloading the zip to compute
it. So a release needs nothing done there. The bucket's own `.\bin\checkver.ps1 flow
-Update` is the same run by hand.

## 3. winget: submitted

**v0.6.1 is [microsoft/winget-pkgs#440220](https://github.com/microsoft/winget-pkgs/pull/440220)**,
opened on 2026-09-24 from a fork under the owner's account, with the three files at
`manifests/s/SamarTomar/Flow/0.6.1/`. Two things changed on the way in:
- The moniker is `flow-dictation`. `flow` belongs to MadrasCheck.flow, and monikers are
  unique. The command on PATH is still `flow`.
- The manifests moved to schema 1.12.0, which the pull request template asks for.

They were sent without this directory's explanatory comments, and `winget validate`
passed on the exact files sent.

Microsoft's bot asks the owner to accept its CLA on the pull request, by replying
`@microsoft-github-policy-service agree`. Validation then installs the package on a
clean VM, and a first package from a new publisher is reviewed by a person.

**For the next version**, wingetcreate builds the update from the release. It needs a
GitHub token with `public_repo`:

```powershell
wingetcreate update SamarTomar.Flow --version 0.6.2 --urls https://github.com/samartomar/flow/releases/download/v0.6.2/flow-windows-x64.zip --submit --token <github-token>
```

komac does the same job and computes the checksum itself, from the URL:

```powershell
komac update SamarTomar.Flow --version 0.6.2 --urls https://github.com/samartomar/flow/releases/download/v0.6.2/flow-windows-x64.zip --submit
```

Its flags move between major versions more than wingetcreate's do, so check
`komac --help` if it argues.

## 4. The binary is unsigned, and that does not change here

Neither package manager signs anything, and neither hides that the download is unsigned.
SmartScreen stands: the first launch shows the "Windows protected your PC" panel and takes
**More info** then **Run anyway**, once, per machine. The README and `docs/guide.md`
already say so, the winget description above says so, and none of them should stop saying
so until a certificate exists. A code-signing certificate is a yearly subscription and it
waits for someone who actually needs it.

What the package managers do change is the checksum. Before this, a download was a file
from a web page. Now `winget install` and `scoop install` both verify the zip against a
number published from the machine that built it, and refuse the install if it differs.

## 5. Both versions move with `pyproject.toml`

`pyproject.toml` is the source of truth for the version. Four files in this directory
repeat it and none of them can read it, so all four are moved by hand at release time:

- `packaging/scoop/flow.json` - `version`, and the `v0.6.1` in the architecture URL
- `packaging/winget/SamarTomar.Flow.yaml` - `PackageVersion`
- `packaging/winget/SamarTomar.Flow.installer.yaml` - `PackageVersion`, and the `v0.6.1`
  in `InstallerUrl`
- `packaging/winget/SamarTomar.Flow.locale.en-US.yaml` - `PackageVersion`

The checksum changes with every build, so **a version bump also puts `FILL-ME-SHA256` back**
in both hash fields, and step 1 runs again once that version's zip exists. Keeping the old
number would pair the new zip's URL with the last zip's checksum. The one-liner in step 1
replaces only the placeholder, so it would silently leave that stale number in place.

This is not left to memory. `tests/test_packaging.py` reads the version out of
`pyproject.toml` and fails if either manifest disagrees with it, in the same way the
release workflow already fails when a tag disagrees with it. A version bump that forgets
these files turns the suite red on the next run, before a tag exists and long before a
manifest pointing at a release that was never built reaches a stranger. The same file
keeps each release's published checksum (`PUBLISHED_SHA256`) and refuses a stated hash
that is not the one for the version the manifests name. Filling step 1 therefore means
adding that release's line there too.
