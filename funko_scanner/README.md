# Funko Scanner (UPC)

Programa sencillo en Python para escanear códigos de barras (UPC) de Funko Pops usando una cámara web y consultar detalles del producto mediante APIs públicas.

## Requisitos

- Python 3.8+
- Webcam
- Dependencias Python:
  - opencv-python
  - pyzbar
  - requests
  - Pillow
- Importante en Windows: pyzbar requiere la librería nativa ZBar instalada (DLL).

## Instalación rápida (Windows)

1) Clona o copia este proyecto en tu equipo.
2) Abre una terminal en la carpeta `funko_scanner/`.
3) Ejecuta el script:

```
scripts\run_scanner.cmd
```

Esto creará un entorno virtual `.venv`, instalará dependencias y ejecutará el escáner.

### Instalar ZBar en Windows

pyzbar necesita la DLL de ZBar. Opciones:

- Con Chocolatey (recomendado si lo tienes):
  - Instala Chocolatey si no lo tienes: https://chocolatey.org/install
  - Luego: `choco install zbar` (requiere terminal con privilegios de administrador)

- Binarios precompilados:
  - Descarga desde el repositorio oficial o mirrors (por ejemplo, "ZBar windows binaries").
  - Asegura que `libzbar-64.dll` (o equivalente) esté en el `PATH` de Windows o junto al ejecutable de Python.

Si no instalas ZBar, `pyzbar` no podrá decodificar códigos de barras y el escaneo fallará.

## Uso

1) Ejecuta el script de Windows o manualmente:

```
# Activar entorno y ejecutar manualmente (alternativa)
py -3 -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
python src\scanner.py
```

2) Coloca el código de barras frente a la cámara. Cuando detecte un UPC válido, consultará la API.

3) Opcionalmente, puedes introducir un UPC manual si la cámara no lo detecta.

## APIs Soportadas

- UPCitemdb (trial, 100 requests/día, sin API key):
  - `https://api.upcitemdb.com/prod/trial/lookup?upc={UPC}`

- UPCDatabase (requiere API key). Puedes definir la variable de entorno `UPCDATABASE_API_KEY` y el programa la usará como alternativa si la primera falla:
  - `https://api.upcdatabase.org/product/{UPC}?apikey=TU_API_KEY`

## Problemas comunes

- La cámara no abre: prueba cambiando `cv2.VideoCapture(0)` por `1` o `2` en `src/scanner.py`.
- Imagen oscura o mala lectura: mejora la iluminación; evita reflejos sobre el código de barras.
- ZBar no instalado: instala la DLL (ver sección ZBar) y reinicia la terminal.
- Límite de API: si superas el límite de UPCitemdb, configura `UPCDATABASE_API_KEY` o espera al día siguiente.

## Próximos pasos y mejoras

- Modo multi-escaneo y exportar a CSV.
- Validación con checksum UPC-A.
- UI con Tkinter o PyQt.
- Cache local (SQLite) para evitar consultas repetidas.
- Empaquetado con PyInstaller.
