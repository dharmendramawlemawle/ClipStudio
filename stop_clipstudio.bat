@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo [!] Failed to stop ClipStudio cleanly.
    pause
    exit /b %ERRORLEVEL%
)
exit /b 0
