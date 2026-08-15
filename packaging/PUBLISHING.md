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

Nothing here has been submitted, and neither manifest works yet, because both carry the
literal string `FILL-ME-SHA256` where the checksum goes. Filling that is step one and it
is the only step that cannot be done from inside the repository, because it is a fact
about a file on a Releases page rather than a fact about this tree.

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
beside the zip, and the number can be read without downloading 126 MB:

```powershell
(Invoke-RestMethod https://github.com/samartomar/flow/releases/download/v0.5.1/flow-windows-x64.zip.sha256).Split(" ")[0]
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

Check that it took before submitting anything: `git diff` should show two changed lines
and no remaining `FILL-ME-SHA256`.

## 2. Scoop: where the manifest lives

The manifest is finished; the question is which repository it sits in, and there are two
answers with a real trade between them.

**Your own bucket.** Create `samartomar/scoop-flow`, put the manifest at `bucket/flow.json`
(Scoop looks in a `bucket/` subdirectory first, then the repository root), and push. Users
then run:

```powershell
scoop bucket add flow https://github.com/samartomar/scoop-flow
scoop install flow/flow
```

**Or submit it to `ScoopInstaller/Extras`.** Fork it, add `bucket/flow.json`, open a pull
request. Users then run `scoop install extras/flow` with no bucket to add, because
`extras` is one of the buckets Scoop ships knowing about.

The trade in one sentence: your own bucket ships the moment you push and nobody can tell
you no, but nobody finds it either unless you hand them the `scoop bucket add` line, while
`extras` is already on every Scoop install and costs you a review you do not control plus
a manifest maintained to somebody else's house rules.

Either way the `checkver` and `autoupdate` blocks are what keep it current. `checkver`
watches this repository's releases; `autoupdate` rewrites the URL for the new version and
reads the hash out of the `.sha256` asset rather than downloading the zip to compute it.
In your own bucket, that is driven by the Scoop bucket template's
`.\bin\checkver.ps1 flow -Update`; in `extras`, their automation runs it for you.

## 3. winget: submitting

Both tools below open the pull request against `microsoft/winget-pkgs` for you, where the
files belong at `manifests/s/SamarTomar/Flow/0.5.1/`. Both need a GitHub token with
`public_repo`, and both will fork the repository under your account the first time.

**wingetcreate** takes the prepared directory as it stands:

```powershell
wingetcreate submit --token <github-token> packaging\winget
```

It validates the three files first, so a `FILL-ME-SHA256` that was not replaced fails here
rather than in front of a reviewer. That failure is expected and is the whole reason the
placeholder is a word rather than a plausible-looking string of hex.

For the *next* version, the shorter path is to let it build the manifests from the release:

```powershell
wingetcreate update SamarTomar.Flow --version 0.5.2 --urls https://github.com/samartomar/flow/releases/download/v0.5.2/flow-windows-x64.zip --submit --token <github-token>
```

**komac** does the same job and computes the checksum itself, from the URL these prepared
files name, so the placeholder never has to be filled on this path:

```powershell
komac update SamarTomar.Flow --version 0.5.1 --urls https://github.com/samartomar/flow/releases/download/v0.5.1/flow-windows-x64.zip --submit
```

To send the prepared files verbatim instead of regenerating them, komac takes the
directory: `komac submit packaging\winget`. Its flags move between major versions more
than wingetcreate's do, so check `komac --help` if it argues.

After either submission the pull request runs Microsoft's validation, which installs the
package on a clean VM. A portable zip has little to fail on, but the run is not instant
and a first submission from a new publisher is reviewed by a person.

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

- `packaging/scoop/flow.json` - `version`, and the `v0.5.1` in the architecture URL
- `packaging/winget/SamarTomar.Flow.yaml` - `PackageVersion`
- `packaging/winget/SamarTomar.Flow.installer.yaml` - `PackageVersion`, and the `v0.5.1`
  in `InstallerUrl`
- `packaging/winget/SamarTomar.Flow.locale.en-US.yaml` - `PackageVersion`

And the checksum changes with every build, so step 1 runs again for every version.

This is not left to memory. `tests/test_packaging.py` reads the version out of
`pyproject.toml` and fails if either manifest disagrees with it, in the same way the
release workflow already fails when a tag disagrees with it. A version bump that forgets
these files turns the suite red on the next run, before a tag exists and long before a
manifest pointing at a release that was never built reaches a stranger.
