
@echo off
REM Lanzador backend NORMATIVA GALICIA (Windows)
REM Ajusta las rutas/variables si es necesario.

SETLOCAL ENABLEDELAYEDEXPANSION
set HOST=127.0.0.1
set PORT=8002

REM Proveedor de plan (csv/mock). Recomendado: csv si tienes un archivo.
set PLAN_PROVIDER=csv
REM Ruta al CSV (ajústala si usas otro fichero). Si no existe, se usará el CSV de ejemplo.
set PLAN_CSV_PATH=datos\plan_uploaded.csv
IF NOT EXIST "%PLAN_CSV_PATH%" (
  set PLAN_CSV_PATH=datos\planes_ejemplo_residencial.csv
)

REM (Opcional) Capa de ordenanzas Vigo para auto-inferir subzona
REM set VIGO_ARCGIS_FEATURE_URL=https://TU_SERVIDOR/arcgis/rest/services/Ordenanzas/FeatureServer/0

REM (Opcional) Nivel de log de uvicorn
set LOG_LEVEL=info

REM Perfil de modelo para el asistente IA (fast|balanced). balanced activa Mistral 7B Instruct (CPU)
set MODEL_PROFILE=balanced
REM Opcional: hilos y contexto del modelo GGUF (ajustables según CPU)
set GGUF_THREADS=4
set GGUF_CONTEXT=2048

REM Mostrar configuración
echo === Lanzando backend ===
echo HOST=%HOST% PORT=%PORT%
echo PLAN_PROVIDER=%PLAN_PROVIDER%
echo PLAN_CSV_PATH=%PLAN_CSV_PATH%
IF DEFINED VIGO_ARCGIS_FEATURE_URL echo VIGO_ARCGIS_FEATURE_URL=%VIGO_ARCGIS_FEATURE_URL%
echo MODEL_PROFILE=%MODEL_PROFILE%

REM Ejecutar uvicorn con autoreload
py -m uvicorn app.main:app --host %HOST% --port %PORT% --reload --log-level %LOG_LEVEL%

ENDLOCAL
