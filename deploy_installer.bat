@echo off
setlocal DisableDelayedExpansion

REM Build the bundled installer from the existing dist\gremlinEx package.
if not "%~1"=="" goto :usage

pushd "%~dp0"
if errorlevel 1 exit /b 1
set "BUILD_EXIT_CODE=1"

if not exist "dist\gremlinEx\gremlinEx.exe" (
    echo Packaged executable not found: dist\gremlinEx\gremlinEx.exe
    echo Run deploy.bat first to build the application package.
    goto :build_failed
)

REM Override ISCC_EXE in the caller's environment to select another compiler.
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
if not defined ISCC_EXE (
    echo Inno Setup not found. Install Inno Setup 6 or 7, or set ISCC_EXE to ISCC.exe.
    goto :build_failed
)
if not exist "%ISCC_EXE%" (
    echo Inno Setup compiler not found at "%ISCC_EXE%".
    goto :build_failed
)

echo Building bundled GremlinEx installer...
"%ISCC_EXE%" /DBundledBuild "installer\GremlinEx.iss"
set "BUILD_EXIT_CODE=%errorlevel%"
if not "%BUILD_EXIT_CODE%"=="0" goto :build_failed

echo Installer build complete. Versioned installer: dist\installer.
popd
exit /b 0

:build_failed
echo GremlinEx installer build failed.
popd
exit /b %BUILD_EXIT_CODE%

:usage
echo Usage: %~nx0
echo Builds the bundled installer from the existing dist\gremlinEx package.
exit /b 2
