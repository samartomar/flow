param(
    [string]$Installer = './Flow-Setup.exe'
)

$ErrorActionPreference = 'Stop'
$testDir = Join-Path ([IO.Path]::GetTempPath()) ("Flow install smoke " + [guid]::NewGuid())
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Flow.lnk'
$installed = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/SamarTomar.Flow_is1'
if ((Test-Path $shortcut) -or (Test-Path $installed)) {
    throw "The installer smoke test needs a Windows account without an existing Flow installation"
}

function Install-Flow {
    $setup = Start-Process -FilePath $Installer -Wait -PassThru -WindowStyle Hidden `
        -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$testDir`""
    if ($setup.ExitCode -ne 0) { throw "Setup exited with code $($setup.ExitCode)" }
}

Install-Flow
$desktop = Join-Path $testDir 'Flow Desktop.exe'
try {
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    if ($link.TargetPath -ne $desktop -or $link.Arguments -ne '--home') {
        throw "The Flow Start menu shortcut is missing or incorrect"
    }
    $launch = Start-Process -FilePath $desktop -ArgumentList '--help' -Wait -PassThru -WindowStyle Hidden
    if ($launch.ExitCode -ne 0) { throw "The desktop executable did not start" }

    # Simulate metadata and a retained optional runtime from an earlier version.
    $oldMetadata = "$testDir/_internal/flow-0.0.0.dist-info"
    New-Item -ItemType Directory $oldMetadata, "$testDir/cuda" | Out-Null
    Set-Content "$testDir/cuda/preserve-on-upgrade" 'CUDA installation marker'
    Install-Flow
    if ((Test-Path $oldMetadata) -or !(Test-Path "$testDir/cuda/preserve-on-upgrade")) {
        throw "Upgrade must replace packaged files and keep the optional CUDA runtime"
    }
}
finally {
    $uninstall = Start-Process -FilePath "$testDir/unins000.exe" -Wait -PassThru -WindowStyle Hidden `
        -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
    if ($uninstall.ExitCode -ne 0 -or (Test-Path $shortcut) -or
        (Test-Path $desktop) -or (Test-Path "$testDir/cuda")) {
        throw "Uninstall did not remove Flow and its shortcut"
    }
}
