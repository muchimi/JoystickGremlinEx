// Shared by the bundled and online installers. Do not use the packaged
// vJoyInterface.dll as evidence of an installed vJoy driver.
var
  DependencyRestartRequired: Boolean;

function NeedsHidHide: Boolean;
var
  Version: String;
begin
  Result := not (
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\HidHide') or
    RegQueryStringValue(HKCR64, 'Installer\Dependencies\NSS.Drivers.HidHide.x64', 'Version', Version) or
    RegQueryStringValue(HKCR32, 'Installer\Dependencies\NSS.Drivers.HidHide.x64', 'Version', Version));
end;

function NeedsMaestroBridge: Boolean;
begin
  Result := not (
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\vjoy') or
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService') or
    RegKeyExists(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1') or
    RegKeyExists(HKLM32, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1') or
    FileExists(ExpandConstant('{autopf}\GEXMaestroBridge\GEXMaestroBridgeService.exe')));
end;

procedure InitializeDependencies;
begin
  WizardForm.SelectTasksLabel.Caption :=
    'Select optional installers to run after GremlinEx is installed. ' +
    'Installed dependencies are skipped. Driver installation may require a restart.';
end;

procedure InstallDependency(Component, DisplayName: String);
var
  Params, ErrorText: String;
  ExitCode: Integer;
begin
  ExtractTemporaryFile('dependencies.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\dependencies.ps1') + '" -Component ' + Component;
  if WizardSilent then Params := Params + ' -Silent';
  Log('Running optional installer: ' + DisplayName);
  WizardForm.StatusLabel.Caption := 'Installing optional dependency: ' + DisplayName;
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_SHOW, ewWaitUntilTerminated, ExitCode) then
    ErrorText := 'could not be started'
  else if (ExitCode = 3010) or (ExitCode = 1641) then begin
    DependencyRestartRequired := True;
    exit;
  end else if ExitCode = 0 then exit
  else if ExitCode = 1602 then ErrorText := 'was cancelled'
  else ErrorText := 'failed (exit code ' + IntToStr(ExitCode) + ')';
  Log(DisplayName + ' ' + ErrorText);
  SuppressibleMsgBox('GremlinEx was installed, but the optional ' + DisplayName +
    ' installer ' + ErrorText + '. You can install it separately later. ' +
    'For download errors, check the connection and the project''s published releases.',
    mbInformation, MB_OK, IDOK);
end;

procedure InstallQueuedDependencies;
begin
  // Run sequentially, before the [Run] entry can launch GremlinEx.
  if WizardIsTaskSelected('hidhide') and NeedsHidHide then
    InstallDependency('hidhide', 'HidHide');
  if WizardIsTaskSelected('maestrobridge') and NeedsMaestroBridge then
    InstallDependency('bridge', 'GEX Maestro Bridge');
end;

function NeedRestart: Boolean;
begin
  Result := DependencyRestartRequired;
end;
