#define AppName "Joystick GremlinEx"
#define AppGuid "{{F9D1B5A3-96B6-46D5-AB89-DC36D9C40D1E}"
[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion=1.0
AppVerName=Joystick GremlinEx (GitHub release)
DefaultDirName={autopf}\Joystick GremlinEx
UsePreviousAppDir=yes
DefaultGroupName=Joystick GremlinEx
OutputDir=..\dist\installer
OutputBaseFilename=GremlinEx-Setup
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=Joystick GremlinEx
[Files]
Source: "release.ps1"; Flags: dontcopy
[Icons]
Name: "{autoprograms}\Joystick GremlinEx"; Filename: "{app}\gremlinEx.exe"; Check: IsManaged
[Code]
var
  ReleasePage: TWizardPage;
  ReleaseList: TNewComboBox;
  RefreshButton, PortableButton: TNewButton;
  ReleaseInfo: TNewStaticText;
  InstalledVersion: String;
  SelectedAsset: String;
  PortableDone: Boolean;

function IsManaged: Boolean;
begin
  Result := not PortableDone;
end;

function Q(S: String): String;
begin
  Result := '"' + S + '"';
end;

function RunHelper(Action, Asset, Destination: String): Boolean;
var
  Params: String;
  ExitCode: Integer;
begin
  ExtractTemporaryFile('release.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File ' +
    Q(ExpandConstant('{tmp}\release.ps1')) +
    ' -Action ' + Action +
    ' -Asset ' + Q(Asset) +
    ' -Destination ' + Q(Destination);
  Result := Exec('powershell.exe', Params, '', SW_SHOW, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
end;

procedure LoadReleases(Sender: TObject);
var
  Lines: TArrayOfString;
  I: Integer;
  FileName: String;
begin
  ReleaseList.Items.Clear;
  FileName := ExpandConstant('{tmp}\gremlinex-releases.txt');
  if FileExists(FileName) then DeleteFile(FileName);
  if not RunHelper('list', '', FileName) then begin
    MsgBox('Unable to retrieve GitHub release assets. Check your connection.', mbError, MB_OK);
    exit;
  end;
  if LoadStringsFromFile(FileName, Lines) then begin
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Trim(Lines[I]) <> '' then ReleaseList.Items.Add(Lines[I]);
  end;
  if ReleaseList.Items.Count > 0 then ReleaseList.ItemIndex := 0
  else MsgBox('No supported GremlinEx ZIP releases were found.', mbError, MB_OK);
end;

procedure ExtractPortable(Sender: TObject);
var
  Dir: String;
begin
  if ReleaseList.ItemIndex < 0 then begin
    MsgBox('Select a release first.', mbError, MB_OK);
    exit;
  end;
  Dir := ExpandConstant('{userdocs}\GremlinEx');
  if not BrowseForFolder('Choose the portable extraction directory', Dir, False) then exit;
  if not RunHelper('portable', ReleaseList.Text, Dir) then begin
    MsgBox('Portable extraction failed. The destination may contain partial files.', mbError, MB_OK);
    exit;
  end;
  PortableDone := True;
  MsgBox('GremlinEx was extracted to ' + Dir + '. No installer registration was created.', mbInformation, MB_OK);
  WizardForm.Close;
end;

procedure InitializeWizard;
begin
  InstalledVersion := GetPreviousData('GremlinExAsset', '');
  ReleasePage := CreateCustomPage(wpSelectDir, 'GitHub release', 'Select a GremlinEx package or extract a portable copy');
  ReleaseInfo := TNewStaticText.Create(ReleasePage);
  ReleaseInfo.Parent := ReleasePage.Surface;
  ReleaseInfo.SetBounds(0, 8, ReleasePage.SurfaceWidth, 55);
  ReleaseInfo.AutoSize := False;
  ReleaseInfo.WordWrap := True;
  ReleaseInfo.Caption := 'Installed package: ' + InstalledVersion + #13#10 +
    'Production, RC, and test builds are identified by the ZIP filename.';
  ReleaseList := TNewComboBox.Create(ReleasePage);
  ReleaseList.Parent := ReleasePage.Surface;
  ReleaseList.Style := csDropDownList;
  ReleaseList.SetBounds(0, 74, ReleasePage.SurfaceWidth, 25);
  RefreshButton := TNewButton.Create(ReleasePage);
  RefreshButton.Parent := ReleasePage.Surface;
  RefreshButton.SetBounds(0, 110, 120, 27);
  RefreshButton.Caption := 'Refresh releases';
  RefreshButton.OnClick := @LoadReleases;
  PortableButton := TNewButton.Create(ReleasePage);
  PortableButton.Parent := ReleasePage.Surface;
  PortableButton.SetBounds(135, 110, 200, 27);
  PortableButton.Caption := 'Extract portable copy...';
  PortableButton.OnClick := @ExtractPortable;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = ReleasePage.ID) and (ReleaseList.Items.Count = 0) then LoadReleases(nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ReleasePage.ID then begin
    Result := ReleaseList.ItemIndex >= 0;
    if Result then SelectedAsset := ReleaseList.Text;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then begin
    if not RunHelper('managed', SelectedAsset, ExpandConstant('{app}')) then
      RaiseException('GremlinEx installation failed. Review the PowerShell output.');
  end;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'GremlinExAsset', SelectedAsset);
end;
