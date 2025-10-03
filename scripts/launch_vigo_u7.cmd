@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_viewer_demo.ps1" -Demo -Fast -PlanProvider csv -PlanCSVPath "..\datos\plan_uploaded.csv" -Preset vigo_u7 -UsePlanFrontDefault
endlocal
