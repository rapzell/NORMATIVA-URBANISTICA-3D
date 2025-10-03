@echo off
REM Lanzar demo rápida del visor 3D con Vigo y eje de calle (valida retranqueos)
setlocal
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..

rem Usar PowerShell para invocar el script principal con parámetros de demo
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\run_viewer_demo.ps1" ^
  -Demo -Fast ^
  -PlanProvider mock ^
  -Preset axis_used ^
  -Municipio "Vigo" ^
  -UsePlanFrontDefault -DiagFull

endlocal
