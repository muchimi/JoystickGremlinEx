@echo off
REM Launch GremlinEx with experimental modules enabled (Overlay / AFCS / StreamDeck).
REM Usage: launch_gex.cmd [worktree-dir]
setlocal
set "GEX_ROOT=%~dp0.."
if not "%~1"=="" set "GEX_ROOT=%~1"
for %%I in ("%GEX_ROOT%") do set "GEX_ROOT=%%~fI"

set "GEX_OVERLAY_ENABLED=1"
set "GEX_AFCS_ENABLED=1"
set "GEX_STREAMDECK_ENABLED=1"

set "PY=%GEX_ROOT%\..\JoystickGremlinEx\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%GEX_ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python venv not found.
  echo Tried: %GEX_ROOT%\..\JoystickGremlinEx\.venv\Scripts\python.exe
  exit /b 1
)

cd /d "%GEX_ROOT%"
"%PY%" gremlinEx.py --nmh %*
