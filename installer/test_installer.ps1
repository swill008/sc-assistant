# Installs, upgrades and uninstalls the TEST edition of the installer in a
# throwaway folder and checks each step. Silent.
#   installer\build_installer.ps1 -Test
#   installer\test_installer.ps1 -Setup dist\CitizenAssistant-X.Y.Z-TEST-Setup.exe
#
# The test edition ("Citizen Assistant Test") has its own AppId, Start menu
# folder and uninstall entry, so a real install is never touched. It runs the
# installed program for real, which needs no Citizen Assistant running (they
# share the single-instance mutex): quit it first. Settings in
# %APPDATA%\Citizen Assistant must come through unchanged, and are checked.
param([Parameter(Mandatory)][string]$Setup, [string]$Dir = "$env:TEMP\ca-install-test")

$ErrorActionPreference = "Stop"
$Setup = (Resolve-Path $Setup).Path
if ((Split-Path $Setup -Leaf) -notmatch '-TEST-Setup\.exe$') {
    throw "Use the test edition (installer\build_installer.ps1 -Test); a normal Setup would replace a real install."
}
$version = [regex]::Match((Split-Path $Setup -Leaf), '(\d+\.\d+\.\d+)').Groups[1].Value
$appName = "Citizen Assistant Test"
$uninstKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F1D2A0B-5E51-4C59-9B67-2B7C0F3A9D14}_is1"
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) $appName
$userData = Join-Path $env:APPDATA "Citizen Assistant"
$exe = Join-Path $Dir "CitizenAssistant.exe"
$tmpData = Join-Path $env:TEMP "ca-install-test-appdata"
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
    $args = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$Dir`"", "/LOG=`"$log`"", "/TASKS=`"`"") + $extra
    $p = Start-Process -FilePath $Setup -ArgumentList $args -Wait -PassThru
    return @{ Code = $p.ExitCode; Log = $log }
}

# The installed program, run for real with a temporary settings folder.
function StartApp {
    if (Test-Path $tmpData) { Remove-Item -Recurse -Force $tmpData }
    New-Item -ItemType Directory $tmpData | Out-Null
    $psi = New-Object Diagnostics.ProcessStartInfo $exe
    $psi.UseShellExecute = $false
    $psi.EnvironmentVariables["APPDATA"] = $tmpData
    $p = [Diagnostics.Process]::Start($psi)
    Start-Sleep 12
    return $p
}

function StopApp($p) {
    if ($p -and -not $p.HasExited) { $p.Kill(); $p.WaitForExit(5000) | Out-Null }
    Start-Sleep 1
}

function NoLeftovers {
    -not (Test-Path "$Dir\_internal.old") -and -not (Test-Path "$Dir\CitizenAssistant.exe.old") -and -not (Test-Path "$Dir\.update-in-progress")
}

if (Get-Process CitizenAssistant -ErrorAction SilentlyContinue) {
    throw "Citizen Assistant is running. Quit it first: the test runs the installed program, and only one copy can run."
}
if (Test-Path $uninstKey) {
    throw "$appName is already installed (an earlier test did not finish). Uninstall it from Settings > Apps first."
}
if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
$dataBefore = Snapshot $userData
Write-Host "Testing $Setup (v$version) in $Dir"

# 1. Fresh install --------------------------------------------------------
Write-Host "1. Fresh install"
$r = RunSetup @()
Check "setup exits 0" ($r.Code -eq 0) "(exit $($r.Code))"
Check "program installed" (Test-Path $exe)
Check "runtime folder installed" (Test-Path "$Dir\_internal")
Check "CHANGES.md installed" (Test-Path "$Dir\CHANGES.md")
Check "uninstaller installed" (Test-Path "$Dir\unins000.exe")
$entry = Get-ItemProperty $uninstKey -ErrorAction SilentlyContinue
Check "listed in installed apps" ($null -ne $entry)
Check "installed apps shows v$version" ($entry.DisplayVersion -eq $version) "(DisplayVersion $($entry.DisplayVersion))"
Check "per-user install (no admin)" ($uninstKey -like "HKCU:*")
Check "Start menu shortcut" (Test-Path "$startMenu\$appName.lnk")
Check "Start menu uninstall shortcut" (Test-Path "$startMenu\Uninstall $appName.lnk")
$sh = (New-Object -ComObject WScript.Shell).CreateShortcut("$startMenu\$appName.lnk")
Check "shortcut points at the installed program" ($sh.TargetPath -eq $exe) "($($sh.TargetPath))"

# 2. The installed program starts -------------------------------------------
Write-Host "2. Installed program starts"
$app = StartApp
Check "program is still running after 12 s" (-not $app.HasExited) $(if ($app.HasExited) { "(exit $($app.ExitCode))" } else { "" })
$errLog = Join-Path $tmpData "Citizen Assistant\error.log"
Check "no error.log written" (-not (Test-Path $errLog)) $(if (Test-Path $errLog) { (Get-Content $errLog -Tail 3) -join " | " } else { "" })

# 3. Update while the real program runs -------------------------------------
Write-Host "3. Update while the program is running"
$exeHash = (Get-FileHash $exe).Hash
$r = RunSetup @()
Check "setup stops while the program runs" ($r.Code -ne 0) "(exit $($r.Code))"
Check "log says it is running" ((Get-Content $r.Log -Raw) -match "(?i)running|mutex")
Check "program kept running" (-not $app.HasExited)
Check "nothing changed on disk" ((Get-FileHash $exe).Hash -eq $exeHash -and (Test-Path "$Dir\_internal\python313.dll") -and (NoLeftovers))
StopApp $app

# 4. Update after quitting --------------------------------------------------
Write-Host "4. Update after quitting"
$r = RunSetup @()
Check "update exits 0" ($r.Code -eq 0) "(exit $($r.Code))"
Check "program in place" ((Test-Path $exe) -and (Get-FileHash $exe).Hash -eq $exeHash)
Check "old copies cleaned up, no unfinished-update marker" (NoLeftovers)

# 5. Update while a file is locked by something else -----------------------
Write-Host "5. Update while another program holds a file"
$locked = [IO.File]::Open($exe, "Open", "Read", "None")
try {
    # /NOCLOSEAPPLICATIONS: do not let setup close this PowerShell, which holds the lock.
    $r = RunSetup @("/NOCLOSEAPPLICATIONS")
} finally { $locked.Close() }
Check "setup refuses" ($r.Code -ne 0) "(exit $($r.Code))"
Check "says the program is still running" ((Get-Content $r.Log -Raw) -match "still running")
Check "previous version put back intact" ((Test-Path "$Dir\_internal\python313.dll") -and (Get-FileHash $exe).Hash -eq $exeHash)
Check "no half-moved files left" (NoLeftovers)

# 6. Uninstall while the real program runs, then after quitting --------------
Write-Host "6. Uninstall"
$app = StartApp
$p = Start-Process -FilePath "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
Start-Sleep 3
Check "uninstall stops while the program runs" ((Test-Path $exe) -and (Test-Path $uninstKey)) "(exit $($p.ExitCode))"
StopApp $app
$p = Start-Process -FilePath "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
# The uninstaller finishes in a copy of itself; give it a moment.
$end = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $end -and (Test-Path $exe)) { Start-Sleep -Milliseconds 500 }
Start-Sleep 2
Check "uninstaller exits 0" ($p.ExitCode -eq 0) "(exit $($p.ExitCode))"
Check "program removed" (-not (Test-Path $exe) -and -not (Test-Path "$Dir\_internal"))
Check "removed from installed apps" (-not (Test-Path $uninstKey))
Check "Start menu shortcuts removed" (-not (Test-Path "$startMenu\$appName.lnk"))

# 7. User data --------------------------------------------------------------
Write-Host "7. Settings"
Check "%APPDATA%\Citizen Assistant unchanged" ((Snapshot $userData) -eq $dataBefore)

Remove-Item -Recurse -Force $tmpData -ErrorAction SilentlyContinue
if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir -ErrorAction SilentlyContinue }
Write-Host ("-" * 70)
if ($failures -eq 0) { Write-Host "ALL INSTALLER CHECKS PASSED" } else { Write-Host "$failures INSTALLER CHECK(S) FAILED" }
exit $failures
