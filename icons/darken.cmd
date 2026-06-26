@echo off
setlocal enabledelayedexpansion

:: Check if a file was provided
if "%~1"=="" (
    echo Error: Please drag and drop an image onto this script or provide a file path.
    pause
    exit /b
)

:: Run ImageMagick v7 command
magick "%~1" -modulate 60,100,100 "%~dpn1_disabled%~x1"

echo Done Dimming: "%~dpn1_disabled%~x1"