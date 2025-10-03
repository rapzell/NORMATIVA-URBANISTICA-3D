@echo off
REM Lanzar demo rápida del visor 3D con A Coruña (plan CSV aplicado)
setlocal
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..

rem Usar PowerShell para invocar el script principal con parámetros de demo
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\run_viewer_demo.ps1" ^
  -Demo -Fast ^
  -PlanProvider csv -PlanCSVPath "datos\plan_uploaded.csv" ^
  -Municipio "A Coruña" ^
  -UsePlanFrontDefault -DiagFull

endlocal
