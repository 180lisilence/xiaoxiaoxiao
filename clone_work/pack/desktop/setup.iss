; 小笑肖 · 在线生活工作台 —— Windows 安装包脚本
; 构建：ISCC.exe setup.iss

#define MyAppName "小笑肖"
#define MyAppVer "2.0.0"
#define MyAppPublisher "小笑肖"
#define MyAppExeName "小笑肖.exe"

[Setup]
AppId={{8F3A1C62-7B4D-4E19-9A55-6C2E0D71B4A3}
AppName={#MyAppName}
AppVersion={#MyAppVer}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=小笑肖-安装包-{#MyAppVer}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 装到当前用户目录，全程不请求管理员权限，绝不弹 UAC
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chs"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
