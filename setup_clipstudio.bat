@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo [!] Setup failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)
exit /b 0
