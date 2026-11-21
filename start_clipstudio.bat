@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo [!] Failed to start ClipStudio. Check error logs in logs\ directory.
    pause
    exit /b %ERRORLEVEL%
)
exit /b 0
