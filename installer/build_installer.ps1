# Builds the installer from dist\CitizenAssistant (run PyInstaller first).
# The version comes from app/version.py so the file name matches the release.
#   installer\build_installer.ps1                    # dist\CitizenAssistant -> dist\
#   installer\build_installer.ps1 -DistDir X -OutDir Y
#   installer\build_installer.ps1 -Test             # "Citizen Assistant Test" edition for test_installer.ps1
#   installer\build_installer.ps1 -Test -TestVersion 1.2.99   # a "newer" test edition for the update test
# (PowerShell names ignore case: the override must not be called $Version.)
param([string]$Iscc = "", [string]$DistDir = "", [string]$OutDir = "", [switch]$Test, [string]$TestVersion = "")

$root = Split-Path -Parent $PSScriptRoot
$line = Select-String -Path (Join-Path $root "app\version.py") -Pattern '^VERSION\s*=\s*"([^"]+)"'
$version = $line.Matches[0].Groups[1].Value
if ($TestVersion) {
    if (-not $Test) { throw "-TestVersion is only for test builds: a release must match app/version.py." }
    $version = $TestVersion
}
if (-not $Iscc) {
    $Iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "ISCC.exe not found: install Inno Setup 6 or pass -Iscc." }
if (-not $DistDir) { $DistDir = Join-Path $root "dist\CitizenAssistant" }
if (-not $OutDir) { $OutDir = Join-Path $root "dist" }
$DistDir = (Resolve-Path $DistDir).Path
if (-not (Test-Path (Join-Path $DistDir "CitizenAssistant.exe"))) {
    throw "$DistDir has no CitizenAssistant.exe: run pyinstaller citizen-assistant.spec first."
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
# Resolved paths, not installer\..\dist: Qt's deepest files are close to the
# 260 character path limit.
$defines = @("/DMyAppVersion=$version", "/DDistDir=$DistDir", "/DOutDir=$((Resolve-Path $OutDir).Path)")
if ($Test) { $defines += "/DTestBuild=1" }
& $Iscc @defines (Join-Path $PSScriptRoot "citizen_assistant.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)." }
