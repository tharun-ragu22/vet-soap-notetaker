; Inno Setup script for Vet Soap Notetaker -- the single combined installer the
; vet runs on-site (VetSoapNotetakerSetup.exe). It installs BOTH halves of the appliance
; and wires up everything so the clinic PC is zero-touch after a reboot:
;
;   * the desktop tray app        -> {app}\VetSoapNotetaker.exe
;   * the windowless backend exe  -> {app}\backend\VetSoapNotetakerBackend.exe
;                                    (exactly where backend_supervisor.find_bundled_backend
;                                     looks: <app>\backend\VetSoapNotetakerBackend.exe)
;
; plus: an autostart entry for the desktop app (which in turn launches + babysits
; the backend -- a single autostart brings the whole stack up), a firewall rule so
; the phone can reach the backend, and a seeded config pointing the desktop app at
; the local backend. Uninstall reverses all of it (see [UninstallRun] + [Code]).
;
; Prerequisites -- build BOTH onedir outputs first (PyInstaller is pinned in each
; project's `build` dependency group, so no separate install step is needed):
;   uv run --group build pyinstaller build_spec/vet_soap_notetaker.spec --distpath dist --workpath build
;   (cd backend && uv run --group build pyinstaller build_spec/backend.spec --distpath dist --workpath build)
; Optionally drop a real backend\.env (provider API keys) next to the backend
; source so it ships inside the installer; it's skipped if absent so the repo never
; has to carry secrets.
;
; Then compile:  iscc build_spec/installer.iss  -> dist\installer\VetSoapNotetakerSetup.exe
;
; Admin is required: the firewall rule and a Program Files install both need it.
; This assumes the single everyday Windows user on the clinic PC is the one running
; the installer (autostart + config + data live under that user's profile).

#define MyAppName "Vet Soap Notetaker"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Vet Soap Notetaker"
#define MyAppExeName "VetSoapNotetaker.exe"
#define FirewallRuleName "Vet Soap Notetaker Backend"
#define BackendPort "8443"

[Setup]
AppId={{B6C2E9B0-6F5E-4A7B-9E9B-1A2B3C4D5E6F}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Vet Soap Notetaker
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=VetSoapNotetakerSetup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
; Admin: needed to add the Windows Firewall rule and to install into Program Files.
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; The desktop tray app (PyInstaller onedir) -> install root.
Source: "..\dist\VetSoapNotetaker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The windowless backend exe (its own onedir) -> {app}\backend\, the exact path
; backend_supervisor.find_bundled_backend() resolves.
Source: "..\backend\dist\VetSoapNotetakerBackend\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs
; Provider API keys for the backend, read by config._default_dotenv_path() from
; beside the backend exe when frozen. Optional at build time: the repo carries no
; secrets, so this is skipped unless a real backend\.env was dropped in before
; compiling the shipped installer.
Source: "..\backend\.env"; DestDir: "{app}\backend"; Flags: skipifsourcedoesntexist
; Seed the desktop app's config at ~\.vetscribe\config.json pointing at the LOCAL
; backend over plain http (the bundled backend serves http; config.DEFAULT_CONFIG
; defaults to https). onlyifdoesntexist so we never clobber a config already tuned
; on this PC.
Source: "clinic_config.json"; DestDir: "{%USERPROFILE}\.vetscribe"; DestName: "config.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Autostart the desktop app on login. Same HKCU Run key + value name the in-app
; autostart module manages (src/vet_soap_notetaker/autostart.py: RUN_KEY_PATH / APP_NAME),
; so the app's Settings toggle stays consistent with what the installer wrote.
; The frozen exe takes no args (unlike the dev `-m vet_soap_notetaker.main` form).
; uninsdeletevalue removes it on uninstall so nothing relaunches afterwards.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VetSoapNotetakerAssistant"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[Run]
; Open the backend's port so the phone on the clinic Wi-Fi can reach it.
Filename: "{sys}\netsh.exe"; \
  Parameters: "advfirewall firewall add rule name=""{#FirewallRuleName}"" dir=in action=allow protocol=TCP localport={#BackendPort}"; \
  Flags: runhidden; StatusMsg: "Allowing the phone to reach the backend..."
; Offer to launch the tray app right after a non-silent install.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Reverse the firewall rule on uninstall.
Filename: "{sys}\netsh.exe"; \
  Parameters: "advfirewall firewall delete rule name=""{#FirewallRuleName}"""; \
  Flags: runhidden; RunOnceId: "DelVetSoapNotetakerFirewall"

[Code]
// Stop the running appliance so its exe/DLLs aren't locked while files are added
// or removed. Order matters: kill the desktop app FIRST -- it's the backend's
// supervisor and relaunches the backend every few seconds -- then the backend,
// so it can't be resurrected mid-operation. taskkill is best-effort: a nonzero
// exit just means the process wasn't running, which is fine.
procedure StopAppliance;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM VetSoapNotetaker.exe',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM VetSoapNotetakerBackend.exe',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// Before copying files (fresh install, or an upgrade over a running instance),
// make sure nothing is holding the old files open.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StopAppliance;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: string;
  ProfileDir: string;
begin
  // Stop the appliance before removing files, otherwise the running exe locks
  // them and the uninstall fails with "some entries could not be removed".
  if CurUninstallStep = usUninstall then
    StopAppliance;

  // After the program files are gone, offer to remove the data too. A prompt (not
  // automatic) so uninstall is reversible without being silently destructive: the
  // vet keeps their exam history if they might reinstall.
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('Also delete Vet Soap Notetaker data on this PC?' + #13#10 + #13#10 +
              'This removes exam history, saved config, logs and any failed ' +
              'recordings. Leave them if you might reinstall later.',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      AppDataDir := ExpandConstant('{userappdata}\VetScribe');   // logs, recordings
      ProfileDir := ExpandConstant('{%USERPROFILE}\.vetscribe'); // config, exams
      DelTree(AppDataDir, True, True, True);
      DelTree(ProfileDir, True, True, True);
    end;
  end;
end;
