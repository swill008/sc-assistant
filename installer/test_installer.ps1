# Installs, upgrades and uninstalls the TEST edition of the installer and
# checks each step. Silent.
#   installer\build_installer.ps1 -Test
#   installer\test_installer.ps1 -Setup dist\SCAssistant-X.Y.Z-TEST-Setup.exe [-RunApp]
#
# The test edition ("SC Assistant Test") has its own AppId, Start menu folder
# and uninstall entry, so a real install is never touched, and it never waits
# on or stops a running Citizen Assistant (its AppMutex is the new name only).
#
# -RunApp also starts the installed program (steps 2, 3, 5b and the first half
# of 6). It registers the global hotkeys and needs no SC Assistant or Citizen
# Assistant running (the program refuses to start next to either), so it is
# off by default: leave it off while someone is playing on this PC.
#
# With -NewerSetup (a test edition built with -TestVersion, e.g. 1.2.99) and
# -RunApp it also checks the in-app update hand-off: the real
# app.updater.run_installer waits for the running program to quit, runs that
# Setup silently, and Setup starts the new version.
#
# Step 8 checks the update from the old name (ONE-TIME, rename to SC
# Assistant): a "Citizen Assistant Test" edition built from the last
# installer\citizen_assistant.iss in git is installed, then this Setup.
param([Parameter(Mandatory)][string]$Setup, [string]$Dir = "$env:TEMP\ca-install-test",
      [string]$NewerSetup = "", [switch]$RunApp, [switch]$SkipUpgrade)

$ErrorActionPreference = "Stop"
$Setup = (Resolve-Path $Setup).Path
if ((Split-Path $Setup -Leaf) -notmatch '-TEST-Setup\.exe$') {
    throw "Use the test edition (installer\build_installer.ps1 -Test); a normal Setup would replace a real install."
}
$repo = Split-Path -Parent $PSScriptRoot
$version = [regex]::Match((Split-Path $Setup -Leaf), '(\d+\.\d+\.\d+)').Groups[1].Value
$appName = "SC Assistant Test"
$uninstRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
$uninstKey = "$uninstRoot\{6F1D2A0B-5E51-4C59-9B67-2B7C0F3A9D14}_is1"
$programs = [Environment]::GetFolderPath("Programs")
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $programs $appName
# The real settings folders: the installer must never remove anything in them.
$userDataDirs = @((Join-Path $env:APPDATA "SC Assistant"), (Join-Path $env:APPDATA "Citizen Assistant"))
$exe = Join-Path $Dir "SCAssistant.exe"
$tmpData = Join-Path $env:TEMP "ca-install-test-appdata"
$failures = 0
$skipped = @()

function Check([string]$label, [bool]$ok, [string]$detail = "") {
    Write-Host ("  {0}  {1}{2}" -f ($(if ($ok) { "PASS" } else { "FAIL" }), $label, $(if ($detail) { "  $detail" } else { "" })))
    if (-not $ok) { $script:failures++ }
}

function Skip([string]$label) {
    Write-Host "  SKIP  $label  (needs -RunApp)"
    $script:skipped += $label
}

function Snapshot([string]$path) {
    if (-not (Test-Path $path)) { return "" }
    (Get-ChildItem $path -Recurse -File | Sort-Object FullName | ForEach-Object {
        "$($_.FullName)|$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" }) -join "`n"
}

# File names only: a running real copy may rewrite its own files meanwhile,
# but nothing may go missing.
function FileList([string]$path) {
    if (-not (Test-Path $path)) { return @() }
    @(Get-ChildItem $path -Recurse -File -Force | ForEach-Object { $_.FullName })
}

function RunSetupFile([string]$file, [string[]]$extra) {
    $log = Join-Path $env:TEMP "ca-setup-$([guid]::NewGuid().ToString('N').Substring(0,8)).log"
    $args = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$log`"") + $extra
    $p = Start-Process -FilePath $file -ArgumentList $args -Wait -PassThru
    return @{ Code = $p.ExitCode; Log = $log }
}

function RunSetup([string[]]$extra) {
    RunSetupFile $Setup (@("/DIR=`"$Dir`"", "/TASKS=`"`"") + $extra)
}

function Uninstall([string]$folder, [string]$program) {
    $p = Start-Process -FilePath "$folder\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
    # The uninstaller finishes in a copy of itself; give it a moment.
    $end = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $end -and (Test-Path $program)) { Start-Sleep -Milliseconds 500 }
    Start-Sleep 2
    return $p.ExitCode
}

function LinkTarget([string]$path) {
    if (-not (Test-Path $path)) { return "" }
    (New-Object -ComObject WScript.Shell).CreateShortcut($path).TargetPath
}

# Uninstall entries of either test edition name.
function TestEntries {
    @(Get-ChildItem $uninstRoot | ForEach-Object { Get-ItemProperty $_.PSPath } |
        Where-Object { $_.DisplayName -in @("SC Assistant Test", "Citizen Assistant Test") })
}

# The installed program, run for real with a temporary settings folder.
function StartApp {
    if (Test-Path $tmpData) { Remove-Item -Recurse -Force $tmpData }
    New-Item -ItemType Directory "$tmpData\SC Assistant" | Out-Null
    # Keep the program off the main (game) screen: no nav bar, and the scanner
    # panel on the first secondary monitor (Qt logical position, from Qt).
    $pos = & (Join-Path $repo ".venv\Scripts\python.exe") -c "from PySide6.QtGui import QGuiApplication as G; a = G([]); p = G.primaryScreen(); s = next((x for x in G.screens() if x is not p), p).geometry(); print(s.x() + 60, s.y() + 60)"
    $xy = ($pos -split ' ') | ForEach-Object { [int]$_ }
    @{ nav_visible = $false; voice_enabled = $false; mining_panel_pos = $xy } | ConvertTo-Json |
        Set-Content "$tmpData\SC Assistant\config.json" -Encoding utf8
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

function NoLeftovers([string]$folder = $Dir) {
    -not (Test-Path "$folder\_internal.old") -and -not (Test-Path "$folder\SCAssistant.exe.old") -and
        -not (Test-Path "$folder\CitizenAssistant.exe.old") -and -not (Test-Path "$folder\.update-in-progress")
}

if (Get-Process SCAssistant -ErrorAction SilentlyContinue) {
    throw "SC Assistant is running. Quit it first: Setup (AppMutex) and the program refuse to run next to it."
}
if ($RunApp -and (Get-Process CitizenAssistant -ErrorAction SilentlyContinue)) {
    throw "Citizen Assistant is running: SC Assistant refuses to start next to it, so -RunApp cannot work. Quit it, or leave out -RunApp."
}
if (@(TestEntries).Count -gt 0) {
    throw "A test edition is already installed (an earlier test did not finish). Uninstall it from Settings > Apps first."
}
if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
$dataBefore = @{}
foreach ($d in $userDataDirs) { $dataBefore[$d] = FileList $d }
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
Check "installed apps shows $appName v$version" ($entry.DisplayName -eq $appName -and $entry.DisplayVersion -eq $version) "($($entry.DisplayName) $($entry.DisplayVersion))"
Check "per-user install (no admin)" ($uninstKey -like "HKCU:*")
Check "Start menu shortcut" (Test-Path "$startMenu\$appName.lnk")
Check "Start menu uninstall shortcut" (Test-Path "$startMenu\Uninstall $appName.lnk")
$target = LinkTarget "$startMenu\$appName.lnk"
Check "shortcut points at the installed program" ($target -eq $exe) "($target)"

# 2. The installed program starts -------------------------------------------
Write-Host "2. Installed program starts"
if ($RunApp) {
    $app = StartApp
    Check "program is still running after 12 s" (-not $app.HasExited) $(if ($app.HasExited) { "(exit $($app.ExitCode))" } else { "" })
    $errLog = Join-Path $tmpData "SC Assistant\error.log"
    Check "no error.log written" (-not (Test-Path $errLog)) $(if (Test-Path $errLog) { (Get-Content $errLog -Tail 3) -join " | " } else { "" })
} else { Skip "2. installed program starts, no error.log" }

# 3. Update while the real program runs -------------------------------------
Write-Host "3. Update while the program is running"
$exeHash = (Get-FileHash $exe).Hash
if ($RunApp) {
    $r = RunSetup @()
    Check "setup stops while the program runs" ($r.Code -ne 0) "(exit $($r.Code))"
    Check "log says it is running" ((Get-Content $r.Log -Raw) -match "(?i)running|mutex")
    Check "program kept running" (-not $app.HasExited)
    Check "nothing changed on disk" ((Get-FileHash $exe).Hash -eq $exeHash -and (Test-Path "$Dir\_internal\python313.dll") -and (NoLeftovers))
    StopApp $app
} else { Skip "3. setup stops while the program runs" }

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

# 5b. In-app update hand-off --------------------------------------------------
if ($NewerSetup -and -not $RunApp) { Skip "5b. in-app update hand-off" }
if ($NewerSetup -and $RunApp) {
    Write-Host "5b. In-app update hand-off (app.updater.run_installer)"
    $NewerSetup = (Resolve-Path $NewerSetup).Path
    $newVersion = [regex]::Match((Split-Path $NewerSetup -Leaf), '(\d+\.\d+\.\d+)').Groups[1].Value
    $py = Join-Path $repo ".venv\Scripts\python.exe"
    $app = StartApp
    # The hand-off and the Setup/app it starts inherit this temporary settings
    # folder, so the relaunched program never reads real settings.
    $savedAppData = $env:APPDATA
    $env:APPDATA = $tmpData
    try {
        & $py -c "import sys; sys.path.insert(0, r'$repo'); from pathlib import Path; from app import updater; updater.run_installer(Path(r'$NewerSetup'), wait_for_pid=$($app.Id))"
    } finally { $env:APPDATA = $savedAppData }
    Start-Sleep 3
    Check "Setup waits while the program runs" ((Get-ItemProperty $uninstKey).DisplayVersion -eq $version -and -not $app.HasExited)
    # The program quits, as SC Assistant does right after the hand-off.
    StopApp $app
    $end = (Get-Date).AddSeconds(90); $relaunched = $null
    while ((Get-Date) -lt $end) {
        $now = (Get-ItemProperty $uninstKey -ErrorAction SilentlyContinue).DisplayVersion
        $relaunched = Get-Process SCAssistant -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
        if ($now -eq $newVersion -and $relaunched) { break }
        Start-Sleep 1
    }
    Check "Setup ran after the quit: v$newVersion installed" ($now -eq $newVersion) "(DisplayVersion $now)"
    Check "the new version was started (/LAUNCH=1)" ($null -ne $relaunched)
    Check "no leftovers after the update" (NoLeftovers)
    $relaunched | ForEach-Object { $_.Kill(); $_.WaitForExit(5000) | Out-Null }
    Start-Sleep 1
}

# 6. Uninstall while the real program runs, then after quitting --------------
Write-Host "6. Uninstall"
if ($RunApp) {
    $app = StartApp
    $p = Start-Process -FilePath "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
    Start-Sleep 3
    Check "uninstall stops while the program runs" ((Test-Path $exe) -and (Test-Path $uninstKey)) "(exit $($p.ExitCode))"
    StopApp $app
} else { Skip "6. uninstall stops while the program runs" }
$code = Uninstall $Dir $exe
Check "uninstaller exits 0" ($code -eq 0) "(exit $code)"
Check "program removed" (-not (Test-Path $exe) -and -not (Test-Path "$Dir\_internal"))
Check "removed from installed apps" (-not (Test-Path $uninstKey))
Check "Start menu shortcuts removed" (-not (Test-Path "$startMenu\$appName.lnk"))

# 7. User data --------------------------------------------------------------
Write-Host "7. Settings"
foreach ($d in $userDataDirs) {
    $gone = @($dataBefore[$d] | Where-Object { $_ -and -not (Test-Path -LiteralPath $_) })
    Check "nothing removed from $d" ($gone.Count -eq 0) $(if ($gone) { "($($gone.Count) gone, e.g. $($gone[0]))" } else { "" })
}

# 8. Update from the old name ------------------------------------------------
# ONE-TIME (rename to SC Assistant): remove with the installer's one-time
# clean-up once no 1.2.x installs remain.
function BuildOldSetup([string]$work) {
    # The last installer\citizen_assistant.iss in git: at HEAD before the
    # rename is committed, else in the parent of the commit that removed it.
    $ErrorActionPreference = "Continue"     # git's stderr is not an error here
    $ref = "HEAD"
    git -C $repo cat-file -e "HEAD:installer/citizen_assistant.iss" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $ref = (git -C $repo rev-list -1 HEAD -- installer/citizen_assistant.iss) + "^"
    }
    New-Item -ItemType Directory -Force "$work\installer", "$work\dist\CitizenAssistant\_internal" | Out-Null
    $iss = (git -C $repo show "${ref}:installer/citizen_assistant.iss") -join "`n"
    if (-not $iss) { throw "Could not read installer/citizen_assistant.iss from git ($ref)." }
    # The user's real Citizen Assistant may be running: the old test edition
    # must not wait for it (the real old edition did, through this mutex).
    $iss = $iss -replace '(?m)^AppMutex=.*$', ''
    Set-Content "$work\installer\citizen_assistant.iss" $iss -Encoding utf8
    foreach ($f in "LICENSE", "app.ico", "CHANGES.md") { Copy-Item (Join-Path $repo $f) $work }
    # A stand-in program: the test never starts it, only the files matter.
    Copy-Item $env:ComSpec "$work\dist\CitizenAssistant\CitizenAssistant.exe"
    Set-Content "$work\dist\CitizenAssistant\_internal\old.txt" "old program" -Encoding ascii
    $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    & $iscc /Q "/DMyAppVersion=1.2.98" "/DDistDir=$work\dist\CitizenAssistant" "/DOutDir=$work\out" "/DTestBuild=1" "$work\installer\citizen_assistant.iss" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed for the old test edition ($LASTEXITCODE)." }
    return (Get-ChildItem "$work\out\*-TEST-Setup.exe" | Select-Object -First 1).FullName
}

if ($SkipUpgrade) {
    Write-Host "8. Update from Citizen Assistant: skipped (-SkipUpgrade)"
} else {
    Write-Host "8. Update from Citizen Assistant (old name)"
    $oldName = "Citizen Assistant Test"
    $oldDir = Join-Path $env:LOCALAPPDATA "Programs\$oldName"
    $newDir = Join-Path $env:LOCALAPPDATA "Programs\$appName"
    $oldGroup = Join-Path $programs $oldName
    $oldDesktop = Join-Path $desktop "$oldName.lnk"
    $newDesktop = Join-Path $desktop "$appName.lnk"
    $custom = Join-Path $env:TEMP "ca-install-test-custom"
    foreach ($p in $oldDir, $newDir, $oldGroup, $oldDesktop, $newDesktop) {
        if (Test-Path $p) { throw "$p exists (an earlier test did not finish): remove it first." }
    }
    $work = Join-Path $env:TEMP "ca-old-edition"
    if (Test-Path $work) { Remove-Item -Recurse -Force $work }
    $oldSetup = BuildOldSetup $work
    # Test settings of the test edition's own name, which no install may touch.
    $testData = Join-Path $env:APPDATA $oldName
    New-Item -ItemType Directory -Force $testData | Out-Null
    Set-Content "$testData\config.json" '{"test": true}' -Encoding ascii
    $testDataBefore = Snapshot $testData
    try {
        # 8a. Old install in the old default folder -> new default folder.
        $r = RunSetupFile $oldSetup @("/TASKS=`"desktopicon`"")
        Check "old edition installs (exit 0)" ($r.Code -eq 0) "(exit $($r.Code))"
        Check "old edition in $oldDir" (Test-Path "$oldDir\CitizenAssistant.exe")
        Check "old Start menu and desktop shortcuts" ((Test-Path "$oldGroup\$oldName.lnk") -and (Test-Path $oldDesktop))
        $r = RunSetupFile $Setup @("/TASKS=`"desktopicon`"")
        Check "new edition installs over it (exit 0)" ($r.Code -eq 0) "(exit $($r.Code))"
        Check "new program in $newDir" (Test-Path "$newDir\SCAssistant.exe")
        Check "old program folder removed" (-not (Test-Path $oldDir))
        Check "old Start menu folder removed" (-not (Test-Path $oldGroup))
        Check "old desktop shortcut removed" (-not (Test-Path $oldDesktop))
        Check "new Start menu shortcut" ((LinkTarget "$startMenu\$appName.lnk") -eq "$newDir\SCAssistant.exe")
        Check "new desktop shortcut" ((LinkTarget $newDesktop) -eq "$newDir\SCAssistant.exe")
        $entries = @(TestEntries)
        Check "a single uninstall entry, the new one" ($entries.Count -eq 1 -and $entries[0].DisplayName -eq $appName -and
            $entries[0].InstallLocation.TrimEnd('\') -eq $newDir) "($($entries.Count): $($entries.DisplayName -join ', '))"
        Check "test settings untouched" ((Snapshot $testData) -eq $testDataBefore)
        $code = Uninstall $newDir "$newDir\SCAssistant.exe"
        Check "uninstall exits 0" ($code -eq 0) "(exit $code)"
        Check "uninstall leaves no entry, folder or shortcut" (@(TestEntries).Count -eq 0 -and -not (Test-Path "$newDir\SCAssistant.exe") -and
            -not (Test-Path $newDesktop) -and -not (Test-Path $startMenu))

        # 8b. Old install in a folder the user chose -> updated in place.
        if (Test-Path $custom) { Remove-Item -Recurse -Force $custom }
        $r = RunSetupFile $oldSetup @("/DIR=`"$custom`"", "/TASKS=`"`"")
        Check "old edition installs in a chosen folder" ($r.Code -eq 0 -and (Test-Path "$custom\CitizenAssistant.exe"))
        $r = RunSetupFile $Setup @("/TASKS=`"`"")
        Check "new edition updates it in place (exit 0)" ($r.Code -eq 0 -and (Test-Path "$custom\SCAssistant.exe")) "(exit $($r.Code))"
        Check "old program file gone, no leftovers" (-not (Test-Path "$custom\CitizenAssistant.exe") -and (NoLeftovers $custom))
        Check "old runtime replaced" (-not (Test-Path "$custom\_internal\old.txt") -and (Test-Path "$custom\_internal\python313.dll"))
        Check "old Start menu folder removed" (-not (Test-Path $oldGroup))
        Check "nothing put in the new default folder" (-not (Test-Path $newDir))
        Check "test settings untouched" ((Snapshot $testData) -eq $testDataBefore)
        $code = Uninstall $custom "$custom\SCAssistant.exe"
        Check "uninstall exits 0" ($code -eq 0) "(exit $code)"
        Check "no test edition left installed" (@(TestEntries).Count -eq 0)
    } finally {
        # Clean up whatever a failed step left behind.
        foreach ($e in @(TestEntries)) {
            $u = ($e.UninstallString -replace '"', '')
            if (Test-Path $u) { Start-Process $u -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait | Out-Null; Start-Sleep 3 }
        }
        foreach ($p in $oldDir, $newDir, $custom, $oldGroup, $oldDesktop, $newDesktop, $testData, $work) {
            if ($p -and (Test-Path $p)) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
        }
    }
}

Remove-Item -Recurse -Force $tmpData -ErrorAction SilentlyContinue
if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir -ErrorAction SilentlyContinue }
Write-Host ("-" * 70)
if ($skipped) { Write-Host "Skipped (no -RunApp): $($skipped -join '; ')" }
if ($failures -eq 0) { Write-Host "ALL INSTALLER CHECKS PASSED" } else { Write-Host "$failures INSTALLER CHECK(S) FAILED" }
exit $failures
