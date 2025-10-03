@echo off
setlocal enableextensions enabledelayedexpansion

REM Ir a la raíz del proyecto (carpeta padre de este script)
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set ROOT=%%~fI
pushd "%ROOT%"

REM Crear y activar entorno virtual si no existe
if not exist .venv (
    py -3 -m venv .venv
)
call .venv\Scripts\activate

REM Actualizar pip y dependencias específicas del funko scanner
python -m pip install --upgrade pip
pip install -r funko_requirements.txt

REM Nota: pyzbar requiere la librería ZBar instalada en el sistema (DLL)
REM Consulta README_FUNKO.md para pasos de instalación en Windows.

REM Ejecutar el escáner como módulo
python -m src.funko_scanner

popd
endlocal
