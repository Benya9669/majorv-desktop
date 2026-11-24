#ifndef AppVersion
  #error Pass the version from VERSION via /DAppVersion=X.Y.Z
#endif
[Setup]
AppId=MajorVDesktop.Benya9669
AppName=Major V Desktop
AppPublisher=Benya9669
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
DefaultDirName={localappdata}\Programs\Major V Desktop
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
WizardStyle=modern
UninstallDisplayIcon={app}\majorv-desktop.exe
SetupIconFile=..\majorv\assets\majorv.ico
Compression=lzma2/fast
SolidCompression=yes
OutputDir=..\dist\release
OutputBaseFilename=majorv-desktop-{#AppVersion}-windows-x64

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "..\dist\majorv-desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Major V Desktop"; Filename: "{app}\majorv-desktop.exe"
