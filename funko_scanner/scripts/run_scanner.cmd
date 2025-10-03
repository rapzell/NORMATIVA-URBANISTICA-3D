@echo off
setlocal enableextensions enabledelayedexpansion

REM Determinar ruta del proyecto (carpeta padre de este script)
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set ROOT=%%~fI

pushd "%ROOT%"

REM Crear y activar entorno virtual si no existe
if not exist .venv (
    py -3 -m venv .venv
)

call .venv\Scripts\activate

REM Actualizar pip y dependencias
python -m pip install --upgrade pip
pip install -r requirements.txt

REM Nota: pyzbar requiere la librería ZBar instalada en el sistema (DLL)
REM Consulta README.md para pasos de instalación en Windows.

python -m pip show pyzbar >nul 2>&1
if errorlevel 1 (
    echo pyzbar no se instaló correctamente.
)

REM Ejecutar como módulo para que los imports relativos funcionen
python -m src.scanner

popd

endlocal
