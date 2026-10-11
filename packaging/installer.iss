; FreeDictate installer (Inno Setup 6.5+). Built by scripts\build.ps1, which passes
; /DAppVersion and /DSourceDir. Installs per user by default (no admin prompt);
; the "all users" choice is offered on the first page.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\FreeDictate"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{7C8F2A4E-5D1B-4B7E-9C3A-FD1C7A7E3D10}
AppName=FreeDictate
AppVersion={#AppVersion}
AppVerName=FreeDictate {#AppVersion}
AppPublisher=DavidHiFi
AppPublisherURL=https://github.com/DavidHiFi/freedictate
AppSupportURL=https://github.com/DavidHiFi/freedictate/issues
AppUpdatesURL=https://github.com/DavidHiFi/freedictate/releases
AppCopyright=Copyright (C) 2026 DavidHiFi. MIT license.
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\FreeDictate
DefaultGroupName=FreeDictate
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=FreeDictate-{#AppVersion}-Setup
SetupIconFile=..\assets\freedictate.ico
UninstallDisplayIcon={app}\FreeDictate.exe
UninstallDisplayName=FreeDictate
; lzma2/ultra64 with solid compression exhausts the 32-bit compiler's 2 GB
; address space on a PyInstaller tree this size (measured: Out of memory after
; a full pass). lzma2/max stays inside it and compresses within a few percent.
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern dynamic windows11
WizardSizePercent=110
CloseApplications=yes
RestartApplications=no
SetupMutex=FreeDictateSetup
LicenseFile=..\LICENSE
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start FreeDictate when I sign in"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "Add a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files from an older build that the new one no longer ships.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\FreeDictate"; Filename: "{app}\FreeDictate.exe"; AppUserModelID: "DavidHiFi.FreeDictate"; Comment: "Offline dictation: hold a shortcut, speak, let go"
Name: "{autodesktop}\FreeDictate"; Filename: "{app}\FreeDictate.exe"; AppUserModelID: "DavidHiFi.FreeDictate"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FreeDictate"; ValueData: """{app}\FreeDictate.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\FreeDictate.exe"; Description: "Open FreeDictate now"; Flags: nowait postinstall skipifsilent
; Silent updates started from inside the app relaunch it in the tray.
Filename: "{app}\FreeDictate.exe"; Parameters: "--background"; Flags: nowait; Check: IsAppUpdate

[UninstallRun]
Filename: "{app}\FreeDictate.exe"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitApp"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn FreeDictate /f"; Flags: runhidden; RunOnceId: "RemoveTask"

[Code]
function IsAppUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  Exe: String;
begin
  Result := '';
  Exe := ExpandConstant('{app}\FreeDictate.exe');
  if FileExists(Exe) then
  begin
    { Ask a running copy to quit, so its files can be replaced. }
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(1500);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{userappdata}\FreeDictate');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox('Also delete your FreeDictate settings and dictation history?' + #13#10 + #13#10 +
                'Downloaded speech models stay in your Hugging Face cache.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(Data, True, True, True);
        DelTree(ExpandConstant('{localappdata}\FreeDictate'), True, True, True);
      end;
  end;
end;
