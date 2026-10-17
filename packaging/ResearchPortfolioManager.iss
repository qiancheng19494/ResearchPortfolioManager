#define AppVersion "1.2.0"
[Setup]
AppId={{D04131C2-33E3-4429-B8B9-73A07F03D480}
AppName=ResearchPortfolioManager
AppVersion={#AppVersion}
AppVerName=ResearchPortfolioManager {#AppVersion}
AppPublisher=ResearchPortfolioManager
DefaultDirName={localappdata}\Programs\ResearchPortfolioManager
DefaultGroupName=ResearchPortfolioManager
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=ResearchPortfolioManager_v1.2.0_Windows_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ResearchPortfolioManager.exe
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\ResearchPortfolioManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\科研档案管理系统"; Filename: "{app}\ResearchPortfolioManager.exe"
Name: "{autodesktop}\科研档案管理系统"; Filename: "{app}\ResearchPortfolioManager.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Run]
Filename: "{app}\ResearchPortfolioManager.exe"; Description: "启动科研档案管理系统"; Flags: nowait postinstall skipifsilent
