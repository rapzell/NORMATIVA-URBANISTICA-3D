@echo off
REM Lanzador backend con comprobación de WeasyPrint (Windows)
REM Ajusta rutas/variables si es necesario.

SETLOCAL ENABLEDELAYEDEXPANSION
set HOST=127.0.0.1
set PORT=8002

REM Proveedor de plan (csv/mock)
set PLAN_PROVIDER=csv
set PLAN_CSV_PATH=datos\plan_uploaded.csv

REM (Opcional) URL de ordenanzas Vigo
REM set VIGO_ARCGIS_FEATURE_URL=https://TU_SERVIDOR/arcgis/rest/services/Ordenanzas/FeatureServer/0

set LOG_LEVEL=info

echo === Comprobando WeasyPrint ===
py -c "import importlib,sys;print('weasyprint ok' if importlib.util.find_spec('weasyprint') else 'weasyprint NOT FOUND');" 1>__weasy.txt 2>&1
set /p WEASY=<__weasy.txt
if exist __weasy.txt del /f /q __weasy.txt >nul 2>&1

echo Resultado: %WEASY%
if "%WEASY%"=="weasyprint NOT FOUND" (
  echo [AVISO] WeasyPrint no esta instalado. El endpoint /zoning/assess-report.pdf devolvera 501.
  echo         Puedes seguir usando Informe (HTML) y Guardar como PDF desde el navegador.
)

echo === Lanzando backend ===
echo HOST=%HOST% PORT=%PORT%
echo PLAN_PROVIDER=%PLAN_PROVIDER%
echo PLAN_CSV_PATH=%PLAN_CSV_PATH%
IF DEFINED VIGO_ARCGIS_FEATURE_URL echo VIGO_ARCGIS_FEATURE_URL=%VIGO_ARCGIS_FEATURE_URL%

py -m uvicorn app.main:app --host %HOST% --port %PORT% --reload --log-level %LOG_LEVEL%

ENDLOCAL
