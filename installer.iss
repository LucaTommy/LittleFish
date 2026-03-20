; Inno Setup installer script for Little Fish
; Requires Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
;
; To build:
;   1. Run `python build.py` first to create dist/LittleFish.exe and dist/LittleFishLauncher.exe
;   2. Open this file in Inno Setup Compiler and click Build
;   3. Output goes to Output/LittleFishSetup.exe

#define MyAppName "Little Fish"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "Luca & Leonardo"
#define MyAppExeName "LittleFishLauncher.exe"

[Setup]
AppId={{8F3B2A1E-4C5D-6E7F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename=LittleFishSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
SetupIconFile=littlefish.ico
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupentry"; Description: "Launch on Windows startup"; GroupDescription: "Startup:"

[Files]
; Main executables from dist/ folder
Source: "dist\LittleFish.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\LittleFishLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion
; Config
Source: "config\settings.json"; DestDir: "{app}\config"; Flags: onlyifdoesntexist
Source: "version.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "littlefish.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Auto-start launcher on boot (only if user selected the task)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LittleFishLauncher"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startupentry

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\_backup"
