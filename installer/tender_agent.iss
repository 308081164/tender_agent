; 标书智能体 Windows 安装包 (Inno Setup 6)
; 从项目根目录运行: .\package-desktop.ps1
#define MyAppName "标书智能体"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "TenderAgent"
#define MyAppURL "https://github.com/308081164/tender_agent"
#define MyAppExeName "TenderAgent.exe"
#define MyAppMutex "Global\\TenderAgentDesktopElectron"
#define MyUninstallRegKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\B8C4D2E1-5F3A-4B9C-8D2E-202608080001_is1"

[Setup]
AppId={{B8C4D2E1-5F3A-4B9C-8D2E-202608080001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\TenderAgent
DisableProgramGroupPage=yes
LicenseFile=
OutputDir=..\dist
OutputBaseFilename=TenderAgentSetup
SetupIconFile=..\assets\brand\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=force
CloseApplicationsFilter=*.exe
AppMutex={#MyAppMutex}
LanguageDetectionMethod=uilanguage
ShowLanguageDialog=auto

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinesesimplified.AppComment=铁路行业标书 AI 辅助编写系统
chinesesimplified.LaunchApp=启动 {#MyAppName}
english.AppComment=Railway tender document AI assistant
english.LaunchApp=Launch {#MyAppName}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\tender-agent-installer-stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "{cm:AppComment}"; IconFilename: "{app}\icon.ico"; IconIndex: 0
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; IconIndex: 0; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\TenderAgent"

[Code]
function GetDefaultInstallDir(): String;
begin
  Result := ExpandConstant('{autopf}\TenderAgent');
end;

function GetExistingInstallDir(): String;
var
  Dir: String;
begin
  if RegQueryStringValue(HKCU, '{#MyUninstallRegKey}',
    'InstallLocation', Dir) then
  begin
    if DirExists(Dir) then
    begin
      Result := Dir;
      Exit;
    end;
  end;
  if RegQueryStringValue(HKLM, '{#MyUninstallRegKey}',
    'InstallLocation', Dir) then
  begin
    if DirExists(Dir) then
    begin
      Result := Dir;
      Exit;
    end;
  end;
  Result := GetDefaultInstallDir();
end;

procedure KillTenderAgentProcesses(InstallDir: String);
var
  ResultCode: Integer;
  DataDir: String;
  PsCmd: String;
  RuntimeNeedle: String;
begin
  Exec('taskkill.exe', '/F /IM {#MyAppExeName} /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if InstallDir <> '' then
  begin
    RuntimeNeedle := LowerCase(InstallDir + '\runtime');
    PsCmd := 'Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq ''python.exe'' -or $_.Name -eq ''uvicorn.exe'' -or $_.Name -eq ''postgres.exe'' -or $_.Name -eq ''minio.exe'') -and $_.CommandLine -and $_.CommandLine.ToLower().Contains(''' + RuntimeNeedle + ''') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }';
    Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PsCmd + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  DataDir := ExpandConstant('{localappdata}\TenderAgent\data');
  if FileExists(DataDir + '\server.json') then
  begin
    PsCmd := '$s=Get-Content -Raw ''' + DataDir + '\server.json'' | ConvertFrom-Json; if($s.pid){taskkill /F /T /PID $s.pid}';
    Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PsCmd + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  Sleep(800);
end;

function InitializeSetup(): Boolean;
begin
  KillTenderAgentProcesses(GetExistingInstallDir());
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    KillTenderAgentProcesses(ExpandConstant('{app}'));
end;

