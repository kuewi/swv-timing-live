; Installer fuer SWV Live-Ranking (Inno Setup 6). Gebaut im GitHub-Workflow:
;   iscc /DAppVersion=1.9.0 installer\swv_live_ranking.iss
; Feste AppId: eine neue Version ersetzt die installierte, die Daten im Ordner
; Dokumente\SWV Live-Ranking bleiben bei Update und Deinstallation erhalten.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "SWV Live-Ranking"
#define AppExe "SWV_LiveRanking.exe"
#define AppGuid "{B4DE1EDF-776D-4410-9796-2B4B03D4C710}"

[Setup]
AppId={{#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Stefan Küng
AppPublisherURL=https://github.com/kuewi/swv-timing-live
AppSupportURL=https://github.com/kuewi/swv-timing-live/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist
OutputBaseFilename=SWV_LiveRanking_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
CloseApplications=force
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{userdocs}\{#AppName}"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Datenordner (Logs, Autosave, Fehlerberichte)"; Filename: "{userdocs}\{#AppName}"
Name: "{group}\{#AppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function VersionPart(var S: String): Integer;
var P: Integer;
begin
  P := Pos('.', S);
  if P = 0 then begin
    Result := StrToIntDef(S, 0);
    S := '';
  end else begin
    Result := StrToIntDef(Copy(S, 1, P - 1), 0);
    Delete(S, 1, P);
  end;
end;

function CompareVersions(A, B: String): Integer;
var I, X, Y: Integer;
begin
  Result := 0;
  for I := 1 to 4 do begin
    X := VersionPart(A);
    Y := VersionPart(B);
    if X <> Y then begin
      if X > Y then Result := 1 else Result := -1;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
var Installed: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1',
                         'DisplayVersion', Installed) then
  begin
    if CompareVersions(Installed, '{#AppVersion}') > 0 then
      Result := MsgBox('Installiert ist bereits die neuere Version ' + Installed + '.' + #13#10 +
                       'Trotzdem auf Version {#AppVersion} zurückgehen?', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;
