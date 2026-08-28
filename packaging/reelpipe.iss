; inno setup script for the windows installer. compiled by ci (or locally) after
; pyinstaller has produced dist\ReelPipe. pass the version in: iscc /DAppVer=0.1.0

#ifndef AppVer
#define AppVer "0.0.0"
#endif

[Setup]
AppId={{8F0E6E1C-5A34-4D7B-9C2E-1B7D3A9F42E1}
AppName=ReelPipe
AppVersion={#AppVer}
AppPublisher=WYBC
; per-user install: no admin prompt, lands in %localappdata%\Programs
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\ReelPipe
DefaultGroupName=ReelPipe
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
OutputDir=..
OutputBaseFilename=ReelPipe-Windows-Setup
UninstallDisplayIcon={app}\ReelPipe.exe
SetupIconFile=..\packaging\icon.ico

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\ReelPipe\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\ReelPipe"; Filename: "{app}\ReelPipe.exe"
Name: "{userdesktop}\ReelPipe"; Filename: "{app}\ReelPipe.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ReelPipe.exe"; Description: "Launch ReelPipe"; Flags: nowait postinstall skipifsilent
