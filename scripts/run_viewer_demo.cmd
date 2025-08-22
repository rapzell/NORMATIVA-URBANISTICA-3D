@echo off
setlocal
set SCRIPT_DIR=%~dp0
set PS1=%SCRIPT_DIR%run_viewer_demo.ps1

REM Forward all args to the PowerShell script
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*

endlocal
