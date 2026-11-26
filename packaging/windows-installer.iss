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
AppMutex=Local\SamarTomar.Flow.Running
UsePreviousTasks=no
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

[Tasks]
Name: "cuda"; Description: "Use faster NVIDIA CUDA acceleration (download up to 870 MB)"; Flags: unchecked; Check: CudaAvailable

[Files]
Source: "..\dist\flow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"; Check: UpgradingFlow

[Icons]
Name: "{userprograms}\Flow"; Filename: "{app}\Flow Desktop.exe"; Parameters: "--home"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Flow Desktop.exe"; Parameters: "--home"; WorkingDir: "{app}"; Description: "Open Flow"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\cuda"

[Code]
var
  CudaChecked, HasCudaDevice: Boolean;
  DownloadPage: TDownloadWizardPage;

function UpgradingFlow: Boolean;
var
  PreviousDir: String;
begin
  Result := RegQueryStringValue(HKCU64,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\SamarTomar.Flow_is1',
    'InstallLocation', PreviousDir);
  if Result then
    Result := (CompareText(RemoveBackslashUnlessRoot(PreviousDir), ExpandConstant('{app}')) = 0)
      and FileExists(ExpandConstant('{app}\flow.exe'));
end;

function MajorNumber(Value: String): Integer;
var
  Dot: Integer;
begin
  Value := Trim(Value);
  Dot := Pos('.', Value);
  if Dot > 0 then
    Value := Copy(Value, 1, Dot - 1);
  Result := StrToIntDef(Value, 0);
end;

function DriverSupportsCuda(Value: String): Boolean;
var
  DriverMajor, DriverMinor: Integer;
begin
  Value := Trim(Value);
  DriverMajor := MajorNumber(Value);
  DriverMinor := StrToIntDef(Copy(Value, Pos('.', Value) + 1, Length(Value)), 0);
  { NVIDIA's Windows driver for CUDA 12.9 Update 2 is 576.57. }
  Result := (DriverMajor > 576) or ((DriverMajor = 576) and (DriverMinor >= 57));
end;

function CudaAvailable: Boolean;
var
  Smi, Row: String;
  ExitCode, I, Separator: Integer;
  Output: TExecOutput;
begin
  if not CudaChecked then
  begin
    CudaChecked := True;
    Smi := ExpandConstant('{sys}\nvidia-smi.exe');
    if not FileExists(Smi) then
      Smi := ExpandConstant('{commonpf64}\NVIDIA Corporation\NVSMI\nvidia-smi.exe');
    if FileExists(Smi) then
      if ExecAndCaptureOutput(Smi,
          '--query-gpu=compute_cap,driver_version --format=csv,noheader,nounits', '',
          SW_SHOWNORMAL, ewWaitUntilTerminated, ExitCode, Output) then
        if (ExitCode = 0) and not Output.Error then
          for I := 0 to GetArrayLength(Output.StdOut) - 1 do
          begin
            Row := Output.StdOut[I];
            Separator := Pos(',', Row);
            if Separator > 0 then
              if (MajorNumber(Copy(Row, 1, Separator - 1)) >= 6) and
                 DriverSupportsCuda(Copy(Row, Separator + 1, Length(Row))) then
                HasCudaDevice := True;
          end;
    Log(Format('NVIDIA CUDA option available: %d', [Ord(HasCudaDevice)]));
  end;
  Result := HasCudaDevice;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading NVIDIA CUDA support',
    'Flow will keep using the same Parakeet v3 GPU model.', nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  HelperExe: String;
begin
  Result := '';
  if not WizardIsTaskSelected('cuda') then
    exit;
  DownloadPage.Clear;
  DownloadPage.Add('{#CudaBlasUrl}', 'Flow-CUDA-Blas.zip', '{#CudaBlasSha}');
  DownloadPage.Add('{#CudaRuntimeUrl}', 'Flow-CUDA-Runtime.zip', '{#CudaRuntimeSha}');
  HelperExe := ExpandConstant('{%USERPROFILE}\{#CudaHelperExePath}');
  if not FileExists(HelperExe) then
    DownloadPage.Add('{#CudaHelperUrl}', 'Flow-CUDA-Helper.zip', '{#CudaHelperSha}')
  else if CompareText(GetSHA256OfFile(HelperExe), '{#CudaHelperExeSha}') <> 0 then
    DownloadPage.Add('{#CudaHelperUrl}', 'Flow-CUDA-Helper.zip', '{#CudaHelperSha}');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      Result := 'CUDA download failed. Go back and retry, or clear the CUDA option to continue. ' +
        GetExceptionMessage;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('cuda') then
    if not Exec(ExpandConstant('{app}\flow.exe'),
        '--install-cuda-runtime "' + ExpandConstant('{tmp}') + '"',
        '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
      SuppressibleMsgBox('Flow installed successfully. CUDA setup failed. You can run Setup again to retry.',
        mbError, MB_OK, IDOK);
end;
