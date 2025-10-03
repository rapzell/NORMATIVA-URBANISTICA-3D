# Funko Scanner (UPC) - Uso desde esta carpeta

Este módulo permite escanear códigos de barras (UPC) de Funko Pops usando la webcam y consultar detalles del producto mediante APIs públicas.

## Requisitos

- Python 3.8+
- Webcam
- Dependencias Python (se instalan automáticamente con el script):
  - opencv-python
  - pyzbar
  - requests
  - Pillow
- En Windows: pyzbar requiere la librería nativa ZBar instalada (DLL)

## Instalación y ejecución rápida (Windows)

1) Abre una terminal en esta carpeta (raíz de `NORMATIVA GALICIA`).
2) Ejecuta:

```
scripts\run_funko_scanner.cmd
```

El script creará un entorno virtual `.venv`, instalará `funko_requirements.txt` y ejecutará el escáner con `python -m src.funko_scanner`.

### Instalar ZBar en Windows

- Con Chocolatey (recomendado si lo tienes):
  - Instala Chocolatey: https://chocolatey.org/install
  - Luego: `choco install zbar` (PowerShell/Command Prompt como Administrador)

- Alternativa: binarios precompilados de ZBar:
  - Descarga un paquete compatible con tu Windows (x64).
  - Asegura que `libzbar-64.dll` esté en el PATH de Windows o junto al ejecutable de Python.

Sin ZBar, `pyzbar` no podrá leer los códigos de barras.

## Uso

1) Coloca el código de barras frente a la cámara. Cuando detecte un UPC válido (12 dígitos), consultará la API.
2) Si no se detecta automáticamente, puedes introducir el UPC manualmente.
3) Si el producto tiene imagen, puedes abrirla en el navegador por defecto.

## APIs soportadas

- UPCitemdb (trial, 100 requests/día):
  - `https://api.upcitemdb.com/prod/trial/lookup?upc={UPC}`
- UPCDatabase (requiere API key). Configura `UPCDATABASE_API_KEY` en el entorno para usarla como alternativa.

## Problemas comunes

- Cámara no abre: edita `src/funko_scanner.py` y cambia `cv2.VideoCapture(0)` a `1` o `2`.
- Límite de API o respuesta vacía: prueba otro UPC o configura `UPCDATABASE_API_KEY`.
- Error de ZBar (DLL no encontrada): instala ZBar y reinicia la terminal.
