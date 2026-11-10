// Shared by the bundled and online installers. Do not use the packaged
// vJoyInterface.dll as evidence of an installed vJoy driver.
var
  DependencyRestartRequired: Boolean;
  BridgeStatusChecked, BridgeInstalled, BridgeCanInstall: Boolean;
  BridgeInstalledVersion, BridgeLatestVersion: String;
  BridgeConnectionState, BridgeConnectionMessage: String;
  BridgeCheckProgress: TOutputProgressWizardPage;
  BridgeConnectionLabel: TNewStaticText;
  BridgeTestButton: TNewButton;

function NeedsHidHide: Boolean;
var
  Version: String;
begin
  Result := not (
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\HidHide') or
    RegQueryStringValue(HKCR64, 'Installer\Dependencies\NSS.Drivers.HidHide.x64', 'Version', Version) or
    RegQueryStringValue(HKCR32, 'Installer\Dependencies\NSS.Drivers.HidHide.x64', 'Version', Version));
end;

function IsMaestroBridgeInstalled: Boolean;
begin
  Result := (
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService') or
    RegKeyExists(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1') or
    RegKeyExists(HKLM32, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1') or
    FileExists(ExpandConstant('{autopf}\GEXMaestroBridge\GEXMaestroBridgeService.exe')) or
    FileExists(ExpandConstant('{sd}\GremlinEx\GEXMaestroBridge\GEXMaestroBridgeService.exe')));
end;

procedure CheckMaestroBridgeStatus(ConnectionOnly: Boolean);
var
  StatusFile, Params, BridgeAction: String;
  ExitCode: Integer;
begin
  if BridgeStatusChecked and not ConnectionOnly then exit;
  BridgeStatusChecked := True;
  BridgeConnectionState := 'not_tested';
  BridgeConnectionMessage := 'The localhost bridge connection could not be checked. Check Tools > Maestro Devices after setup.';
  if not ConnectionOnly then begin
    BridgeInstalled := IsMaestroBridgeInstalled;
    BridgeCanInstall := not BridgeInstalled and
      not RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\vjoy');
  end;
  // Keep a useful local status if PowerShell or the online version check fails.
  if BridgeInstalled then begin
    if not RegQueryStringValue(HKLM64,
      'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1',
      'DisplayVersion', BridgeInstalledVersion) then
      RegQueryStringValue(HKLM32,
        'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1',
        'DisplayVersion', BridgeInstalledVersion);
  end;
  if not ConnectionOnly and not BridgeInstalled and not BridgeCanInstall then begin
    BridgeConnectionState := 'not_installed';
    BridgeConnectionMessage := 'GEX Maestro Bridge is not installed; vJoy is already installed.';
    exit;
  end;

  ExtractTemporaryFile('dependencies.ps1');
  StatusFile := ExpandConstant('{tmp}\maestro-bridge-status.ini');
  if FileExists(StatusFile) then DeleteFile(StatusFile);
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\dependencies.ps1') + '" -Component bridge -CheckOnly -StatusFile "' + StatusFile + '"';
  if ConnectionOnly then Params := Params + ' -ConnectionOnly';
  if BridgeCheckProgress = nil then
    BridgeCheckProgress := CreateOutputProgressPage('Optional components', 'Checking GEX Maestro Bridge');
  if not WizardSilent then begin
    BridgeCheckProgress.SetText('Testing the bridge OSC connection on localhost...', '');
    BridgeCheckProgress.Show;
  end;
  try
    if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0) and FileExists(StatusFile) then begin
      BridgeInstalled := GetIniString('Bridge', 'Installed', '0', StatusFile) = '1';
      BridgeInstalledVersion := GetIniString('Bridge', 'InstalledVersion', '', StatusFile);
      if not ConnectionOnly then begin
        BridgeLatestVersion := GetIniString('Bridge', 'LatestVersion', '', StatusFile);
        BridgeAction := GetIniString('Bridge', 'Action', 'none', StatusFile);
        BridgeCanInstall := (BridgeAction = 'install') or (BridgeAction = 'upgrade');
      end;
      BridgeConnectionState := GetIniString('Bridge', 'ConnectionState', 'not_tested', StatusFile);
      BridgeConnectionMessage := GetIniString('Bridge', 'ConnectionMessage', 'The localhost bridge connection was not tested.', StatusFile);
    end else
      Log('Unable to check the installed Maestro Bridge version; an unconfirmed upgrade will not be offered.');
  finally
    if not WizardSilent then BridgeCheckProgress.Hide;
  end;
  Log('Maestro Bridge connection: ' + BridgeConnectionState + ': ' + BridgeConnectionMessage);
  if BridgeConnectionLabel <> nil then BridgeConnectionLabel.Caption := BridgeConnectionMessage;
end;

function ShowMaestroBridge: Boolean;
begin
  CheckMaestroBridgeStatus(False);
  // Keep the installed-version note visible even when no component needs installing.
  Result := BridgeInstalled or BridgeCanInstall;
end;

function NeedsMaestroBridge: Boolean;
begin
  CheckMaestroBridgeStatus(False);
  Result := BridgeCanInstall;
end;

function MaestroBridgeDescription(Param: String): String;
begin
  CheckMaestroBridgeStatus(False);
  if not BridgeInstalled then begin
    Result := 'Install GEX Maestro Bridge for HIDMaestro virtual controllers';
    if BridgeLatestVersion <> '' then Result := Result + ' (' + BridgeLatestVersion + ')';
  end else if BridgeCanInstall then
    Result := 'Upgrade GEX Maestro Bridge from ' + BridgeInstalledVersion + ' to ' + BridgeLatestVersion
  else if BridgeInstalledVersion = '' then
    Result := 'GEX Maestro Bridge is already installed (version unavailable; upgrade not offered)'
  else if BridgeLatestVersion = '' then
    Result := 'GEX Maestro Bridge ' + BridgeInstalledVersion + ' is already installed (update check unavailable)'
  else
    Result := 'GEX Maestro Bridge ' + BridgeInstalledVersion + ' is already installed (latest: ' + BridgeLatestVersion + '; no upgrade needed)';
end;

<event('CurPageChanged')>
procedure UpdateDependencyChoices(CurPageID: Integer);
var
  I: Integer;
begin
  if CurPageID <> wpSelectTasks then exit;
  BridgeConnectionLabel.Caption := BridgeConnectionMessage;
  BridgeTestButton.Enabled := BridgeInstalled;
  for I := 0 to WizardForm.TasksList.Items.Count - 1 do begin
    if WizardForm.TasksList.Items[I] = MaestroBridgeDescription('') then begin
      if not BridgeCanInstall then WizardForm.TasksList.Checked[I] := False;
      WizardForm.TasksList.ItemEnabled[I] := BridgeCanInstall;
    end;
  end;
end;

procedure NotifyBridgeConnection;
begin
  if BridgeConnectionState = 'connected' then
    SuppressibleMsgBox(BridgeConnectionMessage, mbInformation, MB_OK, IDOK)
  else
    SuppressibleMsgBox(BridgeConnectionMessage, mbError, MB_OK, IDOK);
end;

procedure RetestBridgeConnection(Sender: TObject);
begin
  CheckMaestroBridgeStatus(True);
  NotifyBridgeConnection;
end;

procedure InitializeDependencies;
begin
  WizardForm.SelectTasksLabel.Caption :=
    'Select optional components to install or upgrade after GremlinEx is installed. ' +
    'Driver installation may require a restart.';
  BridgeConnectionLabel := TNewStaticText.Create(WizardForm);
  BridgeConnectionLabel.Parent := WizardForm.SelectTasksPage;
  BridgeConnectionLabel.AutoSize := False;
  BridgeConnectionLabel.WordWrap := True;
  BridgeConnectionLabel.ShowAccelChar := False;
  BridgeConnectionLabel.SetBounds(WizardForm.TasksList.Left,
    WizardForm.TasksList.Top + WizardForm.TasksList.Height - ScaleY(88),
    WizardForm.TasksList.Width, ScaleY(54));
  WizardForm.TasksList.Height := WizardForm.TasksList.Height - ScaleY(96);
  BridgeTestButton := TNewButton.Create(WizardForm);
  BridgeTestButton.Parent := WizardForm.SelectTasksPage;
  BridgeTestButton.SetBounds(BridgeConnectionLabel.Left, BridgeConnectionLabel.Top + ScaleY(58), ScaleX(160), ScaleY(25));
  BridgeTestButton.Caption := 'Test localhost bridge';
  BridgeTestButton.OnClick := @RetestBridgeConnection;
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
    if Component = 'bridge' then
      SuppressibleMsgBox('GEX Maestro Bridge requires a Windows restart before its connection can be tested.', mbInformation, MB_OK, IDOK);
    exit;
  end else if ExitCode = 0 then begin
    if Component = 'bridge' then begin
      CheckMaestroBridgeStatus(True);
      NotifyBridgeConnection;
    end;
    exit;
  end
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
