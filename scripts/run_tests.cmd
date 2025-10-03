@echo off
REM Ejecuta tests de la API en un entorno virtual local (Windows)
SETLOCAL ENABLEDELAYEDEXPANSION

set VENV_DIR=.venv
if not exist %VENV_DIR% (
  echo [tests] Creando entorno virtual en %VENV_DIR% ...
  py -3 -m venv %VENV_DIR%
)

call %VENV_DIR%\Scripts\activate.bat

REM Instalar dependencias minimas para tests
python -m pip install --upgrade pip >NUL 2>&1
python -m pip install pytest fastapi starlette httpx >NUL 2>&1

if "%1"=="" (
  set TEST_PATH=tests
) else (
  set TEST_PATH=%*
)

echo [tests] Ejecutando pytest en %TEST_PATH%
pytest -q %TEST_PATH%

ENDLOCAL
