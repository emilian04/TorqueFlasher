; Inno Setup script for TorqueFlasher (UTF-8 with BOM, for the umlauts). Built by installer\windows\build.bat (or the GitHub release workflow).
; Wizard: license (MIT) -> install folder -> data folder -> shortcuts -> install -> start TorqueFlasher.

#ifndef AppVersion
  #define AppVersion "0.5.0-beta"
#endif
#define AppName "TorqueFlasher"
#define AppExe "TorqueFlasher.exe"

[Setup]
AppId={{B7E4C2A1-5D3F-4E8B-9A61-2F0C7D9E4B13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=emilian04
AppPublisherURL=https://github.com/emilian04/TorqueFlasher
AppSupportURL=https://github.com/emilian04/TorqueFlasher/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=Output
OutputBaseFilename={#AppName}-{#AppVersion}-Windows-Setup
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
english.DataTitle=Data folder
english.DataSub=Where should TorqueFlasher save backups, dumps and logs?
english.DataText=E3 backups, user-data dumps (serial number, mileage) and the OpenOCD logs are saved in this folder. It stays when TorqueFlasher is uninstalled, and it can be changed later in Settings.
german.DataTitle=Datenordner
german.DataSub=Wo soll TorqueFlasher Backups, Dumps und Logs speichern?
german.DataText=E3-Backups, User-Data-Dumps (Seriennummer, Kilometer) und die OpenOCD-Logs landen in diesem Ordner. Er bleibt beim Deinstallieren erhalten und kann später in den Einstellungen geändert werden.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\TorqueFlasher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\torqueflasher-install.json"

[Code]
var
  DataPage: TInputDirWizardPage;

procedure InitializeWizard;
begin
  DataPage := CreateInputDirPage(wpSelectDir, CustomMessage('DataTitle'), CustomMessage('DataSub'),
    CustomMessage('DataText'), False, '');
  DataPage.Add('');
  DataPage.Values[0] := GetPreviousData('DataDir', ExpandConstant('{userdocs}\TorqueFlasher'));
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DataDir', DataPage.Values[0]);
end;

function JsonText(S: String): String;
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '"', '\"', True);
  Result := S;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
begin
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(DataPage.Values[0]);
    SetArrayLength(Lines, 1);
    Lines[0] := '{"data_dir": "' + JsonText(DataPage.Values[0]) + '"}';
    SaveStringsToUTF8File(ExpandConstant('{app}\torqueflasher-install.json'), Lines, False);
  end;
end;
