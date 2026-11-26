#ifndef FlowVersion
  #error FlowVersion must be read from pyproject.toml
#endif
[Setup]
AppId=SamarTomar.Flow
AppName=Flow
AppVersion={#FlowVersion}
AppPublisher=Samar Tomar
AppPublisherURL=https://github.com/samartomar/flow
DefaultDirName={localappdata}\Programs\Flow
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplicationsFilter=flow.exe,Flow Desktop.exe
RestartApplications=no
UninstallDisplayIcon={app}\Flow Desktop.exe
SetupIconFile=..\flow\assets\flow.ico
OutputBaseFilename=Flow-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\flow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Flow"; Filename: "{app}\Flow Desktop.exe"; Parameters: "--home"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Flow Desktop.exe"; Parameters: "--home"; WorkingDir: "{app}"; Description: "Open Flow"; Flags: nowait postinstall skipifsilent
