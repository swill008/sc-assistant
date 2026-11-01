; Citizen Assistant installer (Inno Setup 6).
;
; Per-user install, no admin rights: Program Files would need them, and an
; install the user owns can be updated without a UAC prompt. Same design as
; the Gremlin-Platforms installer.
;
; Build with installer\build_installer.ps1 (after PyInstaller), or by hand:
;   ISCC /DMyAppVersion=1.2.17 /DDistDir=<repo>\dist\CitizenAssistant installer\citizen_assistant.iss

#ifndef MyAppVersion
  #error Pass the version: ISCC /DMyAppVersion=X.Y.Z
#endif
#ifndef DistDir
  #define DistDir "..\dist\CitizenAssistant"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

#define MyAppName "Citizen Assistant"
#define MyAppPublisher "swill008"
#define MyAppURL "https://github.com/swill008/citizen-assistant"
#define MyAppExeName "CitizenAssistant.exe"

[Setup]
; Never change the AppId: updates and uninstall find the install by it.
AppId={{C4736091-9D04-4E7B-B53D-4FA025CCB796}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\Citizen Assistant
DisableDirPage=no
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir={#OutDir}
OutputBaseFilename=CitizenAssistant-{#MyAppVersion}-Setup
SetupIconFile=..\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Close a running copy (it holds its files open) instead of failing.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start Citizen Assistant when Windows starts"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

; The old version's program files are not deleted up front: PrepareToInstall
; moves them aside (_internal.old, CitizenAssistant.exe.old) and they are
; removed only once the new ones are in, or put back if the install fails.
; Settings, notes and caches live in %APPDATA%\Citizen Assistant and are never
; touched, by install or uninstall.

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\CHANGES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
; An updater can run setup silently with /LAUNCH=1 to start the new version.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: LaunchAfterSilentUpdate

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal.old"
Type: files; Name: "{app}\{#MyAppExeName}.old"
Type: files; Name: "{app}\.update-in-progress"

[Code]
var
  { The old program was moved aside and is put back unless the install
    finishes. }
  MovedAside: Boolean;
  Finished: Boolean;
  { The program to start again if a silent update doesn't finish; set once
    setup reaches the install step. }
  AppExe: String;

function LaunchAfterSilentUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:LAUNCH|0}') = '1');
end;

function AppFile(const Name: String): String;
begin
  Result := AddBackslash(WizardDirValue) + Name;
end;

{ Written once the old program is moved aside, removed when the install
  finishes: found at the start of a later install, it means this one stopped
  half-way, so the .old copies are the good ones. }
function MarkerFile: String;
begin
  Result := AppFile('.update-in-progress');
end;

function ExistsAt(const Path: String): Boolean;
begin
  Result := DirExists(Path) or FileExists(Path);
end;

procedure RemovePath(const Path: String);
begin
  if DirExists(Path) then
    DelTree(Path, True, True, True)
  else if FileExists(Path) then
    DeleteFile(Path);
end;

{ Moves Name to Name.old. A copy that is still closing keeps its files locked
  until it has: keep trying for up to 30 seconds. }
function MoveAside(const Name: String): Boolean;
var
  Tries: Integer;
begin
  Result := True;
  if not ExistsAt(AppFile(Name)) then
    Exit;
  for Tries := 1 to 60 do
  begin
    if RenameFile(AppFile(Name), AppFile(Name + '.old')) then
      Exit;
    Sleep(500);
  end;
  Result := False;
end;

procedure PutBack(const Name: String);
begin
  if ExistsAt(AppFile(Name + '.old')) then
  begin
    RemovePath(AppFile(Name));
    RenameFile(AppFile(Name + '.old'), AppFile(Name));
  end;
end;

{ True when the chosen folder holds Citizen Assistant (its program, the copy
  an update set aside, or an update that did not finish). }
function OursIsHere: Boolean;
begin
  Result := ExistsAt(AppFile('{#MyAppExeName}')) or
    ExistsAt(AppFile('{#MyAppExeName}.old')) or FileExists(MarkerFile);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  AppExe := AppFile('{#MyAppExeName}');
  if not OursIsHere then
  begin
    { A new install. Another program's _internal folder must not be moved
      aside and deleted, nor have ours copied into it. }
    if ExistsAt(AppFile('_internal')) then
      Result := 'The folder you chose already holds another program''s ' +
        '_internal folder. Choose an empty folder for Citizen Assistant. ' +
        'Nothing was changed.';
    Exit;
  end;
  if FileExists(MarkerFile) then
  begin
    { An earlier install stopped half-way: keep its .old copies (the last
      working version) and drop the half-copied files. }
    Log('Earlier install did not finish; keeping its backup.');
    if ExistsAt(AppFile('_internal.old')) then
      RemovePath(AppFile('_internal'));
    if ExistsAt(AppFile('{#MyAppExeName}.old')) then
      RemovePath(AppFile('{#MyAppExeName}'));
    MovedAside := True;
    Exit;
  end;
  { Leftovers of a finished install that could not delete them. }
  RemovePath(AppFile('_internal.old'));
  RemovePath(AppFile('{#MyAppExeName}.old'));
  if not MoveAside('_internal') then
  begin
    Result := 'Citizen Assistant is still running, so it could not be updated. ' +
      'Quit it (QUIT on the nav bar, or the tray icon) and run setup again. ' +
      'Nothing was changed.';
    Exit;
  end;
  if not MoveAside('{#MyAppExeName}') then
  begin
    PutBack('_internal');
    Result := 'Citizen Assistant is still running, so it could not be updated. ' +
      'Quit it (QUIT on the nav bar, or the tray icon) and run setup again. ' +
      'Nothing was changed.';
    Exit;
  end;
  MovedAside := True;
  if ExistsAt(AppFile('_internal.old')) or ExistsAt(AppFile('{#MyAppExeName}.old')) then
    SaveStringToFile(MarkerFile, 'update in progress', False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { The new version is in: the old one can go. }
    Finished := True;
    DeleteFile(MarkerFile);
    RemovePath(AppFile('_internal.old'));
    RemovePath(AppFile('{#MyAppExeName}.old'));
  end;
end;

procedure DeinitializeSetup;
var
  ResultCode: Integer;
begin
  { Failed or cancelled after the old program was moved aside: put it back,
    so the version that worked before still starts. }
  if MovedAside and not Finished then
  begin
    Log('Install did not finish; putting the previous version back.');
    PutBack('_internal');
    PutBack('{#MyAppExeName}');
    DeleteFile(MarkerFile);
  end;
  { A silent update that didn't finish: start the version that is there
    again. }
  if (AppExe <> '') and not Finished and LaunchAfterSilentUpdate
    and FileExists(AppExe) then
  begin
    Log('Update did not finish; starting the previous version again.');
    ExecAsOriginalUser(AppExe, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;

{ True when the folder can be written without admin rights. Removes anything
  it had to create for the test. }
function CanWriteTo(const Dir: String): Boolean;
var
  Existed: Boolean;
  Probe: String;
begin
  Existed := DirExists(Dir);
  Result := ForceDirectories(Dir);
  if Result then
  begin
    Probe := AddBackslash(Dir) + '.citizen_assistant_write_test';
    Result := SaveStringToFile(Probe, 'test', False);
    DeleteFile(Probe);
  end;
  if not Existed then
    RemoveDir(Dir);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and not CanWriteTo(WizardDirValue) then
  begin
    MsgBox('This folder needs administrator rights to change, so updates could ' +
      'not be installed into it.' + #13#10#13#10 +
      'Choose a folder you can write to, for example the one suggested.',
      mbError, MB_OK);
    Result := False;
  end;
end;
