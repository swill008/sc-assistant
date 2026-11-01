# Installs, upgrades and uninstalls a built Setup.exe into a throwaway folder
# and checks each step. Silent; nothing is launched.
#   installer\test_installer.ps1 -Setup dist\CitizenAssistant-1.2.17-Setup.exe
#
# It uses the real AppId, so it removes itself at the end; run it when no
# real installed copy is wanted in the test folder's place. Settings in
# %APPDATA%\Citizen Assistant must come through unchanged, and are checked.
param([Parameter(Mandatory)][string]$Setup, [string]$Dir = "$env:TEMP\ca-install-test")

$ErrorActionPreference = "Stop"
$Setup = (Resolve-Path $Setup).Path
$version = [regex]::Match((Split-Path $Setup -Leaf), '(\d+\.\d+\.\d+)').Groups[1].Value
$appId = "{C4736091-9D04-4E7B-B53D-4FA025CCB796}_is1"
$uninstKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$appId"
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Citizen Assistant"
$userData = Join-Path $env:APPDATA "Citizen Assistant"
$failures = 0

function Check([string]$label, [bool]$ok, [string]$detail = "") {
    Write-Host ("  {0}  {1}{2}" -f ($(if ($ok) { "PASS" } else { "FAIL" }), $label, $(if ($detail) { "  $detail" } else { "" })))
    if (-not $ok) { $script:failures++ }
}

function Snapshot([string]$path) {
    if (-not (Test-Path $path)) { return "" }
    (Get-ChildItem $path -Recurse -File | Sort-Object FullName | ForEach-Object {
        "$($_.FullName)|$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" }) -join "`n"
}

function RunSetup([string[]]$extra) {
    $log = Join-Path $env:TEMP "ca-setup-$([guid]::NewGuid().ToString('N').Substring(0,8)).log"
    $args = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$Dir`"", "/LOG=`"$log`"") + $extra
    $p = Start-Process -FilePath $Setup -ArgumentList $args -Wait -PassThru
    return @{ Code = $p.ExitCode; Log = $log }
}

if (Test-Path $uninstKey) {
    throw "Citizen Assistant is already installed (uninstall entry exists); this test would replace it. Uninstall it first."
}
if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
$dataBefore = Snapshot $userData
Write-Host "Testing $Setup (v$version) in $Dir"

# 1. Fresh install --------------------------------------------------------
Write-Host "1. Fresh install"
$r = RunSetup @("/TASKS=`"`"")
Check "setup exits 0" ($r.Code -eq 0) "(exit $($r.Code))"
Check "program installed" (Test-Path "$Dir\CitizenAssistant.exe")
Check "runtime folder installed" (Test-Path "$Dir\_internal")
Check "CHANGES.md installed" (Test-Path "$Dir\CHANGES.md")
Check "uninstaller installed" (Test-Path "$Dir\unins000.exe")
$entry = Get-ItemProperty $uninstKey -ErrorAction SilentlyContinue
Check "listed in installed apps" ($null -ne $entry)
Check "installed apps shows v$version" ($entry.DisplayVersion -eq $version) "(DisplayVersion $($entry.DisplayVersion))"
Check "per-user install (no admin)" ($uninstKey -like "HKCU:*")
Check "Start menu shortcut" (Test-Path "$startMenu\Citizen Assistant.lnk")
Check "Start menu uninstall shortcut" (Test-Path "$startMenu\Uninstall Citizen Assistant.lnk")
$sh = (New-Object -ComObject WScript.Shell).CreateShortcut("$startMenu\Citizen Assistant.lnk")
Check "shortcut points at the installed program" ($sh.TargetPath -eq "$Dir\CitizenAssistant.exe") "($($sh.TargetPath))"

# 1b. The installed program starts ------------------------------------------
# Only one copy may run (a named mutex), so this needs no other copy open. It
# runs with a temporary settings folder so real settings are never used.
Write-Host "1b. Installed program starts"
if (Get-Process CitizenAssistant -ErrorAction SilentlyContinue | Where-Object { $_.Path -ne "$Dir\CitizenAssistant.exe" }) {
    Write-Host "  SKIP  another Citizen Assistant is running; quit it to test start-up"
} else {
    $tmpData = Join-Path $env:TEMP "ca-install-test-appdata"
    if (Test-Path $tmpData) { Remove-Item -Recurse -Force $tmpData }
    New-Item -ItemType Directory $tmpData | Out-Null
    $psi = New-Object Diagnostics.ProcessStartInfo "$Dir\CitizenAssistant.exe"
    $psi.UseShellExecute = $false
    $psi.EnvironmentVariables["APPDATA"] = $tmpData
    $proc = [Diagnostics.Process]::Start($psi)
    Start-Sleep 15
    $alive = -not $proc.HasExited
    Check "program is still running after 15 s" $alive $(if (-not $alive) { "(exit $($proc.ExitCode))" } else { "" })
    $errLog = Join-Path $tmpData "Citizen Assistant\error.log"
    Check "no error.log written" (-not (Test-Path $errLog)) $(if (Test-Path $errLog) { (Get-Content $errLog -Tail 3) -join " | " } else { "" })
    if ($alive) { $proc.Kill(); $proc.WaitForExit(5000) | Out-Null }
    Remove-Item -Recurse -Force $tmpData -ErrorAction SilentlyContinue
}

# 2. Upgrade over the same version ------------------------------------------
Write-Host "2. Upgrade in place"
$exeHash = (Get-FileHash "$Dir\CitizenAssistant.exe").Hash
$r = RunSetup @("/TASKS=`"`"")
Check "upgrade exits 0" ($r.Code -eq 0) "(exit $($r.Code))"
Check "program still there" ((Test-Path "$Dir\CitizenAssistant.exe") -and (Get-FileHash "$Dir\CitizenAssistant.exe").Hash -eq $exeHash)
Check "old copies cleaned up" (-not (Test-Path "$Dir\_internal.old") -and -not (Test-Path "$Dir\CitizenAssistant.exe.old"))
Check "no unfinished-update marker" (-not (Test-Path "$Dir\.update-in-progress"))

# 3. Upgrade while the program's files are in use ---------------------------
Write-Host "3. Upgrade while files are in use (simulated running copy)"
$locked = [IO.File]::Open("$Dir\CitizenAssistant.exe", "Open", "Read", "None")
try {
    # /NOCLOSEAPPLICATIONS: do not let setup close this PowerShell, which holds the lock.
    $r = RunSetup @("/TASKS=`"`"", "/NOCLOSEAPPLICATIONS")
} finally { $locked.Close() }
Check "setup refuses while in use" ($r.Code -ne 0) "(exit $($r.Code))"
Check "says the program is still running" ((Get-Content $r.Log -Raw) -match "still running")
Check "previous version put back intact" ((Test-Path "$Dir\_internal\python313.dll") -and (Get-FileHash "$Dir\CitizenAssistant.exe").Hash -eq $exeHash)
Check "no half-moved files left" (-not (Test-Path "$Dir\_internal.old") -and -not (Test-Path "$Dir\CitizenAssistant.exe.old") -and -not (Test-Path "$Dir\.update-in-progress"))

# 4. Uninstall -------------------------------------------------------------
Write-Host "4. Uninstall"
$p = Start-Process -FilePath "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
# The uninstaller finishes in a copy of itself; give it a moment.
$end = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $end -and (Test-Path "$Dir\CitizenAssistant.exe")) { Start-Sleep -Milliseconds 500 }
Start-Sleep 2
Check "uninstaller exits 0" ($p.ExitCode -eq 0) "(exit $($p.ExitCode))"
Check "program removed" (-not (Test-Path "$Dir\CitizenAssistant.exe") -and -not (Test-Path "$Dir\_internal"))
Check "removed from installed apps" (-not (Test-Path $uninstKey))
Check "Start menu shortcuts removed" (-not (Test-Path "$startMenu\Citizen Assistant.lnk"))

# 5. User data --------------------------------------------------------------
Write-Host "5. Settings"
Check "%APPDATA%\Citizen Assistant unchanged" ((Snapshot $userData) -eq $dataBefore)

if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir -ErrorAction SilentlyContinue }
Write-Host ("-" * 70)
if ($failures -eq 0) { Write-Host "ALL INSTALLER CHECKS PASSED" } else { Write-Host "$failures INSTALLER CHECK(S) FAILED" }
exit $failures
