var
  GremlinExUpdateChecked: Boolean;

<event('CurPageChanged')>
procedure CheckGremlinExUpdate(CurPageID: Integer);
var
  Progress: TOutputProgressWizardPage;
  StatusFile, Params: String;
  UpdateInfo: TArrayOfString;
  ExitCode: Integer;
begin
  if GremlinExUpdateChecked or WizardSilent then exit;
  GremlinExUpdateChecked := True;

  Progress := CreateOutputProgressPage('GremlinEx updates', 'Checking GitHub for a newer M77 installer');
  Progress.SetText('Checking for updates...', '');
  Progress.Show;
  try
    try
      ExtractTemporaryFile('release.ps1');
      StatusFile := ExpandConstant('{tmp}\gremlinex-update.txt');
      Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
        ExpandConstant('{tmp}\release.ps1') + '" -Action check-installer' +
        ' -CurrentVersion "{#AppFilenameVersion}" -Destination "' + StatusFile + '"';
      if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
        Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then begin
        Log('Unable to check for a newer GremlinEx installer.');
        exit;
      end;
      if not FileExists(StatusFile) then exit;
      if not LoadStringsFromFile(StatusFile, UpdateInfo) then exit;
      if GetArrayLength(UpdateInfo) <> 2 then exit;
    except
      Log('Unable to check for a newer GremlinEx installer: ' + GetExceptionMessage);
      exit;
    end;
  finally
    Progress.Hide;
  end;

  if MsgBox('A newer GremlinEx installer is available.' + #13#10 + #13#10 +
    'Current setup: {#AppVersion}' + #13#10 +
    'Download: ' + UpdateInfo[0] + #13#10 + #13#10 +
    'Open the download in your browser?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then exit;

  try
    if ShellExecAsOriginalUser('open', UpdateInfo[1], '', '', SW_SHOWNORMAL, ewNoWait, ExitCode) then exit;
  except
    Log('Unable to open the GremlinEx download: ' + GetExceptionMessage);
  end;
  MsgBox('Unable to open the download in your browser. You can continue with this setup.', mbInformation, MB_OK);
end;
