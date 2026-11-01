; SC Assistant installer (Inno Setup 6).
;
; Per-user install, no admin rights: Program Files would need them, and an
; install the user owns can be updated without a UAC prompt. Same design as
; the Gremlin-Platforms installer.
;
; Build with installer\build_installer.ps1 (after PyInstaller), or by hand:
;   ISCC /DMyAppVersion=1.2.17 /DDistDir=<repo>\dist\SCAssistant installer\sc_assistant.iss

#ifndef MyAppVersion
  #error Pass the version: ISCC /DMyAppVersion=X.Y.Z
#endif
#ifndef DistDir
  #define DistDir "..\dist\SCAssistant"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

#define MyAppPublisher "swill008"
#define MyAppURL "https://github.com/swill008/sc-assistant"
#define MyAppExeName "SCAssistant.exe"
; ONE-TIME (rename to SC Assistant): the program file before 1.0.0.
#define OldExeName "CitizenAssistant.exe"
#ifdef TestBuild
  ; installer\test_installer.ps1 builds this edition: its own name, AppId and
  ; folders, so testing never touches a real install.
  #define MyAppName "SC Assistant Test"
  #define MyAppIdGuid "{{6F1D2A0B-5E51-4C59-9B67-2B7C0F3A9D14}"
  #define MyOutputName "SCAssistant-" + MyAppVersion + "-TEST-Setup"
  ; ONE-TIME (rename to SC Assistant): the test edition's name before 1.0.0.
  #define OldAppName "Citizen Assistant Test"
  ; Only the new name: the user's real Citizen Assistant may be running while
  ; the test runs, and the test edition must never wait on or stop it.
  #define MyAppMutex "SCAssistantOverlay"
#else
  #define MyAppName "SC Assistant"
  ; The same AppId as Citizen Assistant: 1.0.0 updates that install, it is
  ; not a second program.
  #define MyAppIdGuid "{{C4736091-9D04-4E7B-B53D-4FA025CCB796}"
  #define MyOutputName "SCAssistant-" + MyAppVersion + "-Setup"
  ; ONE-TIME (rename to SC Assistant): the name before 1.0.0.
  #define OldAppName "Citizen Assistant"
  ; ONE-TIME (rename to SC Assistant): CitizenAssistantOverlay is the mutex
  ; of a running 1.2.x copy, which must quit before its folder is replaced.
  #define MyAppMutex "SCAssistantOverlay,CitizenAssistantOverlay"
#endif

[Setup]
; Never change the AppId: updates and uninstall find the install by it.
AppId={#MyAppIdGuid}
; The app holds this mutex while it runs (app/main.py, single instance).
; Setup and the uninstaller check it before changing anything: interactively
; they ask you to quit SC Assistant; silently they stop. Without it a
; running copy's files were renamed aside, the update "succeeded" and the old
; version kept running.
AppMutex={#MyAppMutex}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
; An update goes where the previous version is, except the old default folder
; ...\Programs\Citizen Assistant: InitializeWizard sends that one to
; ...\Programs\SC Assistant, and RemoveOldInstall deletes the old folder once
; the install has finished.
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; The Start menu folder is always the app's name (there is no page to choose
; it). Without this an update reuses the folder the previous version used, so
; Citizen Assistant's folder would have held the SC Assistant shortcut.
UsePreviousGroup=no
LicenseFile=..\LICENSE
OutputDir={#OutDir}
OutputBaseFilename={#MyOutputName}
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
Name: "startup"; Description: "Start SC Assistant when Windows starts"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

; The old version's program files are not deleted up front: PrepareToInstall
; moves them aside (_internal.old, SCAssistant.exe.old) and they are
; removed only once the new ones are in, or put back if the install fails.
; Settings, notes and caches live in %APPDATA%\SC Assistant (the app moves
; them there from %APPDATA%\Citizen Assistant) and are never touched, by
; install or uninstall.

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
; ONE-TIME (rename to SC Assistant): a 1.2.x program file an update set aside.
Type: files; Name: "{app}\{#OldExeName}.old"

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

{ True when the chosen folder holds SC Assistant (its program, the copy an
  update set aside, or an update that did not finish). ONE-TIME (rename to SC
  Assistant): or Citizen Assistant, the same program before 1.0.0. }
function OursIsHere: Boolean;
begin
  Result := ExistsAt(AppFile('{#MyAppExeName}')) or
    ExistsAt(AppFile('{#MyAppExeName}.old')) or FileExists(MarkerFile) or
    ExistsAt(AppFile('{#OldExeName}')) or ExistsAt(AppFile('{#OldExeName}.old'));
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
        '_internal folder. Choose an empty folder for SC Assistant. ' +
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
    { ONE-TIME (rename to SC Assistant) }
    if ExistsAt(AppFile('{#OldExeName}.old')) then
      RemovePath(AppFile('{#OldExeName}'));
    MovedAside := True;
    Exit;
  end;
  { Leftovers of a finished install that could not delete them. }
  RemovePath(AppFile('_internal.old'));
  RemovePath(AppFile('{#MyAppExeName}.old'));
  RemovePath(AppFile('{#OldExeName}.old'));   { ONE-TIME (rename to SC Assistant) }
  if not MoveAside('_internal') then
  begin
    Result := 'SC Assistant is still running, so it could not be updated. ' +
      'Quit it (QUIT on the nav bar, or the tray icon) and run setup again. ' +
      'Nothing was changed.';
    Exit;
  end;
  if not MoveAside('{#MyAppExeName}') then
  begin
    PutBack('_internal');
    Result := 'SC Assistant is still running, so it could not be updated. ' +
      'Quit it (QUIT on the nav bar, or the tray icon) and run setup again. ' +
      'Nothing was changed.';
    Exit;
  end;
  { ONE-TIME (rename to SC Assistant): a 1.2.x install in a folder the user
    chose is updated in place, and its CitizenAssistant.exe goes too. }
  if not MoveAside('{#OldExeName}') then
  begin
    PutBack('{#MyAppExeName}');
    PutBack('_internal');
    Result := 'Citizen Assistant is still running, so it could not be updated. ' +
      'Quit it (QUIT on the nav bar, or the tray icon) and run setup again. ' +
      'Nothing was changed.';
    Exit;
  end;
  MovedAside := True;
  if ExistsAt(AppFile('_internal.old')) or ExistsAt(AppFile('{#MyAppExeName}.old'))
    or ExistsAt(AppFile('{#OldExeName}.old')) then
    SaveStringToFile(MarkerFile, 'update in progress', False);
end;

{ ---------------------------------------------------------------------------
  ONE-TIME (rename to SC Assistant): moving a 1.2.x install out of
  ...\Programs\Citizen Assistant. Can go once no 1.2.x installs remain.
  Only the program is touched: its folder and the shortcuts that start it.
  User data in %APPDATA% is never touched here. The test edition works on
  "Citizen Assistant Test" names only, so it never reaches a real install.
  --------------------------------------------------------------------------- }

{ The folder 1.2.x installed into by default. }
function OldDefaultDir: String;
begin
  Result := ExpandConstant('{autopf}\{#OldAppName}');
end;

function SamePath(const A, B: String): Boolean;
begin
  Result := CompareText(RemoveBackslashUnlessRoot(A),
    RemoveBackslashUnlessRoot(B)) = 0;
end;

{ ONE-TIME (rename to SC Assistant): an update of a 1.2.x install in the old
  default folder (UsePreviousAppDir offers that folder) goes to the new
  default folder instead. A folder the user chose, or /DIR= naming another
  folder, is kept. }
procedure InitializeWizard;
begin
  if SamePath(WizardForm.DirEdit.Text, OldDefaultDir) then
  begin
    Log('Installing into the new folder instead of ' + OldDefaultDir);
    WizardForm.DirEdit.Text := ExpandConstant('{autopf}\{#MyAppName}');
  end;
end;

{ The file a shortcut starts, or '' when it can't be read. }
function LinkTarget(const Path: String): String;
var
  Shell, Link: Variant;
begin
  Result := '';
  try
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(Path);
    Result := Link.TargetPath;
  except
    Result := '';
  end;
end;

{ ONE-TIME (rename to SC Assistant): removes a shortcut named after 1.2.x
  when it starts that program (CitizenAssistant.exe) or an uninstaller in the
  old or the current program folder. A shortcut of that name that starts
  anything else (e.g. a source copy) is left alone. }
procedure RemoveOldShortcut(const Path: String);
var
  Target: String;
begin
  if not FileExists(Path) then
    Exit;
  Target := LinkTarget(Path);
  if (CompareText(ExtractFileName(Target), '{#OldExeName}') = 0) or
     ((CompareText(Copy(ExtractFileName(Target), 1, 5), 'unins') = 0) and
      (SamePath(ExtractFileDir(Target), OldDefaultDir) or
       SamePath(ExtractFileDir(Target), WizardDirValue))) then
  begin
    Log('Removing the old shortcut ' + Path);
    DeleteFile(Path);
  end;
end;

{ ONE-TIME (rename to SC Assistant): runs once the new version is in. }
procedure RemoveOldInstall;
var
  Group: String;
begin
  { The old program folder: only when it holds the old program and is not
    where this install went. }
  if not SamePath(OldDefaultDir, WizardDirValue) and
     FileExists(AddBackslash(OldDefaultDir) + '{#OldExeName}') then
  begin
    Log('Removing the old program folder ' + OldDefaultDir);
    if not DelTree(OldDefaultDir, True, True, True) then
      Log('Could not remove all of ' + OldDefaultDir);
  end;
  Group := ExpandConstant('{userprograms}\{#OldAppName}');
  RemoveOldShortcut(AddBackslash(Group) + '{#OldAppName}.lnk');
  RemoveOldShortcut(AddBackslash(Group) + 'Uninstall {#OldAppName}.lnk');
  RemoveDir(Group);       { only when nothing else is left in it }
  RemoveOldShortcut(ExpandConstant('{userdesktop}\{#OldAppName}.lnk'));
  RemoveOldShortcut(ExpandConstant('{userstartup}\{#OldAppName}.lnk'));
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
    RemovePath(AppFile('{#OldExeName}.old'));   { ONE-TIME (rename to SC Assistant) }
    RemoveOldInstall;                           { ONE-TIME (rename to SC Assistant) }
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
    PutBack('{#OldExeName}');                   { ONE-TIME (rename to SC Assistant) }
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
    Probe := AddBackslash(Dir) + '.sc_assistant_write_test';
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
