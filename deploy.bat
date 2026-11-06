@echo off
setlocal

REM Build locally, build and publish with --push, or publish existing files with --push-only.
set "PUSH_TO_GITHUB=0"
set "PUSH_ONLY=0"
if /I "%~1"=="--push" (
    set "PUSH_TO_GITHUB=1"
    shift /1
) else if /I "%~1"=="--push-only" (
    set "PUSH_TO_GITHUB=1"
    set "PUSH_ONLY=1"
    shift /1
)
if not "%~1"=="" goto :usage

pushd "%~dp0"
if errorlevel 1 exit /b 1

REM These tool paths can be overridden in the caller's environment.
if not defined PYTHON_EXE set "PYTHON_EXE=C:\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" (
    echo Python not found. Set PYTHON_EXE to the Python executable.
    if "%PUSH_ONLY%"=="1" goto :publish_failed
    goto :build_failed
)
if "%PUSH_ONLY%"=="1" goto :publish

if not defined SEVENZIP_EXE set "SEVENZIP_EXE=C:\Program Files\7-Zip\7z.exe"
if not defined ISCC_EXE for %%I in (ISCC.exe) do set "ISCC_EXE=%%~$PATH:I"
if not defined ISCC_EXE (
    for %%I in (
        "%ProgramFiles%\Inno Setup 7\ISCC.exe"
        "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
        "%ProgramFiles%\Inno Setup 6\ISCC.exe"
        "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
        "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
        "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    ) do if not defined ISCC_EXE if exist "%%~I" set "ISCC_EXE=%%~I"
)
if not exist "%SEVENZIP_EXE%" (
    echo 7-Zip not found. Set SEVENZIP_EXE to 7z.exe.
    goto :build_failed
)
if not defined ISCC_EXE (
    echo Inno Setup not found. Install Inno Setup 6 or 7, or set ISCC_EXE to ISCC.exe.
    goto :build_failed
)
if not exist "%ISCC_EXE%" (
    echo Inno Setup compiler not found at "%ISCC_EXE%".
    goto :build_failed
)

if "%PUSH_TO_GITHUB%"=="1" (
    echo Checking GitHub publishing access...
    "%PYTHON_EXE%" upload_release.py --check
    if errorlevel 1 goto :build_failed
)

echo Building GremlinEx executable...
"%PYTHON_EXE%" -m PyInstaller -y --log-level INFO --clean gremlinEx.spec
if errorlevel 1 goto :build_failed

REM Robocopy exit codes below 8 indicate success, including copied files.
robocopy licenses dist\gremlinEx\licenses /E /XD .* /NFL /NDL /NJH /NJS
if errorlevel 8 goto :build_failed

echo Creating portable archive...
if exist "dist\gremlinEx.zip" del /q "dist\gremlinEx.zip"
if exist "dist\gremlinEx.zip" goto :build_failed
pushd "dist\gremlinEx"
if errorlevel 1 goto :build_failed
"%SEVENZIP_EXE%" a -r "..\gremlinEx.zip" *
if errorlevel 1 (
    popd
    goto :build_failed
)
popd

"%PYTHON_EXE%" rename_dist_zip.py
if errorlevel 1 goto :build_failed

echo Building bundled installer...
"%ISCC_EXE%" /DBundledBuild "installer\GremlinEx.iss"
if errorlevel 1 goto :build_failed

if "%PUSH_TO_GITHUB%"=="0" goto :build_complete

:publish
REM Select the version in gremlin\version.py, never an older unpacked EXE.
echo Uploading current source version's ZIP and installer to the M77 test release...
"%PYTHON_EXE%" upload_release.py
if errorlevel 1 goto :publish_failed
echo Upload complete.
if "%PUSH_ONLY%"=="1" goto :complete

:build_complete
echo Build complete. Portable ZIP: dist. Versioned installer: dist\installer.
:complete
popd
exit /b 0

:publish_failed
echo GitHub publishing failed.
echo Retry the upload with: %~nx0 --push-only
popd
exit /b 1

:build_failed
echo GremlinEx build failed.
popd
exit /b 1

:usage
echo Usage: %~nx0 [--push ^| --push-only]
echo   --push       Build and upload, overwriting assets with matching names.
echo   --push-only  Upload current source version's ZIP and installer without rebuilding.
exit /b 2
