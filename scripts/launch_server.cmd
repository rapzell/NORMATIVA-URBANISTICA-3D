
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

REM Perfil de modelo local para el asistente IA (fast|balanced). Se usa como fallback o modo local.
set MODEL_PROFILE=balanced
REM Gateway IA multi-proveedor del asistente agéntico (/qa/edificio).
REM Si existe api.txt en la raiz del repo con la clave de OpenRouter,
REM el gateway la detecta solo y usa una cadena de modelos gratuitos
REM (rapidos primero, con respaldo). api.txt esta gitignored.
REM Para forzar otro proveedor o cadena de respaldo:
REM set MODEL_PROVIDER=openrouter
REM set OPENROUTER_API_KEY=tu_clave_openrouter
REM set GROQ_API_KEY=tu_clave_groq
REM set GEMINI_API_KEY=tu_clave_gemini
REM set MISTRAL_API_KEY=tu_clave_mistral
set MODEL_FALLBACK_CHAIN=openrouter,local
REM (Alternativa compartida: MODEL_API_KEY + MODEL_NAME aplican a todos)
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
IF DEFINED MODEL_PROVIDER echo MODEL_PROVIDER=%MODEL_PROVIDER%
IF DEFINED MODEL_NAME echo MODEL_NAME=%MODEL_NAME%

REM Ejecutar uvicorn con el venv del proyecto (lleva rasterio/numpy
REM para la altura medida MDSN; el Python de sistema no los tiene).
IF EXIST "venv\Scripts\python.exe" (
  venv\Scripts\python.exe -m uvicorn app.main:app --host %HOST% --port %PORT% --reload --log-level %LOG_LEVEL%
) ELSE (
  py -m uvicorn app.main:app --host %HOST% --port %PORT% --reload --log-level %LOG_LEVEL%
)

ENDLOCAL
