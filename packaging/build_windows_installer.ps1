param(
    [string]$OutputDir = "."
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$output = (Resolve-Path -LiteralPath $OutputDir).Path
$temp = New-Item -ItemType Directory (Join-Path ([IO.Path]::GetTempPath()) ("flow-inno-" + [guid]::NewGuid()))
$compilerSetup = Join-Path $temp 'inno.exe'
$compilerDir = Join-Path $temp 'compiler'
$compilerUrl = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe'
$compilerSha = 'a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c'

Push-Location $repo
try {
    $version = uv run --locked python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0) { throw "Could not read the Flow version" }

    Invoke-WebRequest -Uri $compilerUrl -OutFile $compilerSetup
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $compilerSetup).Hash -ne $compilerSha) {
        throw "Inno Setup download failed SHA-256 verification"
    }
    $compilerArgs = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /PORTABLE=1 /DIR=`"$compilerDir`""
    $install = Start-Process -FilePath $compilerSetup -ArgumentList $compilerArgs -PassThru -Wait -WindowStyle Hidden
    if ($install.ExitCode -ne 0) { throw "Inno Setup exited with code $($install.ExitCode)" }

    & (Join-Path $compilerDir 'ISCC.exe') "/DFlowVersion=$version" "/O$output" packaging/windows-installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Could not build Flow Setup" }
}
finally {
    Pop-Location
    $target = Get-Item -LiteralPath (Resolve-Path -LiteralPath $temp.FullName).Path
    if ($target.Parent.FullName -eq (Resolve-Path ([IO.Path]::GetTempPath())).Path.TrimEnd('\') -and $target.Name -eq $temp.Name) {
        Remove-Item -LiteralPath $target.FullName -Recurse -Force
    }
}
