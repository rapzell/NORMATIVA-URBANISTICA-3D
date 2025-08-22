# NORMATIVA GALICIA 3D
[![Smoke](https://github.com/rapzell/NORMATIVA-GALICIA-3D/actions/workflows/smoke.yml/badge.svg)](https://github.com/rapzell/NORMATIVA-GALICIA-3D/actions/workflows/smoke.yml)
[![Tests](https://github.com/rapzell/NORMATIVA-GALICIA-3D/actions/workflows/pytest.yml/badge.svg)](https://github.com/rapzell/NORMATIVA-GALICIA-3D/actions/workflows/pytest.yml)

## Troubleshooting

### PowerShell bloquea la ejecución de scripts (ExecutionPolicy)

Si ves un error tipo “la ejecución de scripts está deshabilitada”, ejecuta el script sólo para esta sesión en modo Bypass (no cambia la política del sistema):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_viewer_demo.ps1 -Format glb -Municipio Vigo -UsePlanFrontDefault -Altura 8 -Port 8010 -Echo -DiagFull
```

Opcionalmente, puedes iniciar una consola con `-ExecutionPolicy Bypass` y lanzar el script desde ahí.

### Puerto en uso / conflictos de socket

El script acepta `-Port` (por defecto 8000). Si el puerto solicitado está ocupado por otro proceso, `scripts/run_viewer_demo.ps1` detecta el conflicto y elige automáticamente el siguiente puerto libre en el rango `[max(Port,8000) .. +50]`. Se mostrará un mensaje del puerto alternativo elegido y la URL del visor usará ese puerto. Además, se añade `autop=1` a la URL del visor y éste mostrará un aviso en el panel de debug indicando que el puerto fue auto‑seleccionado.

Si prefieres forzar un puerto concreto, libera el puerto previamente o finaliza el proceso que lo usa.
 Alternativamente, ejecuta el script con `-NoAutoPort` para que falle si el puerto está ocupado (útil en CI o entornos controlados).

### Chequeo rápido (smoke test) sin abrir navegador

Para validar que el backend y el visor responden sin abrir el navegador:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_viewer_demo.ps1 -Format glb -Municipio Vigo -UsePlanFrontDefault -Altura 8 -Port 8010 -Smoke -Echo
```

El comando hace GET a `/viewer/` y POST al export; devuelve 0 si todo va bien, 3/4 si falla.

Nota de rendimiento: durante `-Smoke`, el script exporta `API_LOAD_RESOURCES=0` antes de lanzar Uvicorn para evitar cargar modelos pesados. Esto acelera CI y chequeos locales. Para una prueba completa con carga de modelos, omite `-Smoke`.

Tiempo de arranque y reintentos:

- Usa `-StartupTimeoutSec <seg>` para controlar cuánto esperar a que la API responda (por defecto 180s) antes de continuar con el smoke.
- El `POST /zoning/volume-export` reintenta automáticamente hasta 2 veces en errores 5xx o timeouts (3 intentos en total), con una pausa corta entre intentos.
 - El `GET /viewer/` también reintenta hasta 2 veces ante errores transitorios/timeout antes de fallar.

Parámetros de reintento configurables:

- `-RetryCount <n>`: número de reintentos para `GET /viewer/` y `POST /zoning/volume-export` (por defecto 2; total de intentos = `n+1`).
- `-RetryDelaySec <seg>`: espera entre intentos (por defecto 2s).
 - `-RetryBackoff fixed|exponential`: patrón de espera entre reintentos (por defecto `fixed`). Con `exponential`, el delay crece 2^intento.

### Arranque rápido interactivo (`-Fast`)

Si quieres abrir el visor (no smoke) pero acelerar el arranque, usa `-Fast` para desactivar la carga de modelos pesados igualmente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_viewer_demo.ps1 -Format glb -Municipio Vigo -UsePlanFrontDefault -Altura 8 -Port 8010 -Fast -Echo
```

Esto establece `API_LOAD_RESOURCES=0` sólo para esa ejecución.

### Registro de logs (`-LogDir`)

Puedes redirigir la salida de Uvicorn a un directorio para depuración:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_viewer_demo.ps1 -Format glb -Municipio Vigo -UsePlanFrontDefault -Altura 8 -Port 8010 -Smoke -LogDir .\logs-smoke -Echo
```

Esto creará `uvicorn_stdout.txt` y `uvicorn_stderr.txt` en la carpeta indicada. En CI, el workflow sube estos logs como artifacts para facilitar el diagnóstico.

Además, cuando se pasa `-LogDir`, el script intenta capturar también la consola del runner en `script_transcript.txt` (Start-Transcript) y la cierra correctamente al finalizar, incluso si el smoke falla.

### CI: Smoke automático en GitHub Actions

Se incluye un workflow en `.github/workflows/smoke.yml` que instala dependencias en Windows y ejecuta el smoke test del script con `-Smoke`. Esto valida `/viewer/` y `POST /zoning/volume-export` en cada push/PR.

Además, la matriz incluye variantes opcionales con `lib=local` (para ambos formatos) marcadas como `allow-failure` para comprobar el uso de librerías locales sin bloquear el pipeline si fallan.

#### Troubleshooting (CI)

- Si el smoke falla en CI, revisa el artifact de logs: además de `uvicorn_stdout.txt`/`uvicorn_stderr.txt`, consulta `script_transcript.txt` (captura de consola del runner) para ver mensajes y tiempos de reintento (`GET /viewer/` y `POST /zoning/volume-export`).
 - Cuando se ejecuta con `-Smoke` y `-LogDir`, se genera también `smoke_summary.json` con: política de reintentos efectiva, intentos y códigos de estado de GET/POST, marcas de tiempo y `exitCode`.

### Códigos de salida del script

- `0`: smoke OK (POST export correcto).
- `1`: no hay venv ni Python en PATH.
- `2`: puerto en uso y `-NoAutoPort` activo.
- `3`: fallo en `GET /viewer/` tras reintentos.
- `4`: fallo en `POST /zoning/volume-export` tras reintentos o error inesperado durante el smoke (ver `unhandledError` en `smoke_summary.json`).
- `5`: interrupción por `Ctrl+C` (cleanup realizado).

### Uso de CityJSON descargado (QGIS, cjio, val3dity)

CityJSON está pensado para interoperar con herramientas GIS/QA. Algunos flujos típicos:

- __QGIS (plugin CityJSON)__
  - Instala el plugin “CityJSON Loader” desde el Administrador de Complementos.
  - Abre `*.city.json` o `*.city.json.gz` para inspeccionar geometrías, atributos y hacer análisis.

- __cjio__ (CLI CityJSON)
  - Instalación (ejemplo):
    ```bash
    pip install cjio
    ```
  - Comandos útiles:
    ```bash
    # Información general del archivo
    cjio model.city.json info

    # Validación básica / resumen
    cjio model.city.json validate

    # Extraer bounding-box o recortar por bbox
    cjio model.city.json subset --bbox 0 0 4 4 save clipped.city.json

    # Convertir gzip <-> plano
    gzip -dk model.city.json.gz   # descomprimir a .json
    gzip -k model.city.json       # comprimir a .gz
    ```

- __val3dity__ (validación geométrica)
  - Instalación (consultar docs oficiales para plataforma): https://github.com/val3dity/val3dity
  - Ejemplo de uso:
    ```bash
    val3dity model.city.json --report report.html
    ```

- __Conversión / publicación__
  - Vía herramientas de terceros (p.ej., Cesium ion) para convertir CityJSON a 3D Tiles.
  - Integración en pipelines ETL (FME, Python) para almacenamiento en bases 3D o catálogos estáticos.

Notas:

- Los botones del visor generan CityJSON consistentes con `POST /zoning/volume-export` para casos: polígono simple, con agujeros, multipolígono y multipolígono con agujeros.
- Usa los archivos descargados para QA, auditoría y análisis sin depender del visor GLTF/GLB.

## Three.js Viewer integrado (visualización y descargas)

El proyecto incluye un visor Three.js servido por FastAPI en `http://127.0.0.1:8000/viewer/`.

Características clave:

- Visualiza GLB/GLTF devueltos por `POST /zoning/volume-export`.
- Descarga CityJSON (no se renderiza en el visor).
- Librerías locales (`/viewer/lib`) con fallback a CDN y `importmap` para `three`.
- Decodificador Draco local en `/viewer/lib/draco/`.
- Panel de logs en pantalla para depuración rápida.
- Panel de depuración adicional con última petición/respuesta (ver más abajo).
- Carga de eje de calle (GeoJSON) con persistencia en `localStorage` y aplicación automática al recargar.
- Controles de calidad del eje: toggle para activar/desactivar chequeos, umbrales de distancia (m) y ángulo (°) con persistencia en `localStorage`.
  - Feedback visual: toasts de aviso y parpadeo temporal de capas en el mapa cuando se exceden umbrales.

Controles del panel (barra superior del visor):

- `Limpiar log`: vacía el panel de logs.
- `Ocultar/Mostrar paneles`: alterna visibilidad de `Log` y `Métricas` (persistente: `viewer_panels_visible`).
- `Paneles: arriba/abajo/abajo-izq`: cambia la posición de los paneles de depuración para evitar solapes con la toolbar o métricas (persistente: `viewer_panels_pos`).
- `Compacto`/`Normal`: reduce/recupera tamaños de fuente y padding del panel y overlays (persistente: `viewer_compact`).
- `Diag full`: checkbox que fuerza `diagnostics_verbosity = "full"` en las peticiones cuando el body no lo especifica (persistente: `viewer_diag_full`).
- Estado rápido: muestra el origen de librerías seleccionado y la ruta DRACO aplicada.
- Métricas: FPS y estadísticas de escena (`renderer.info`: draw calls, triángulos, geometrías, texturas, programas) y últimas peticiones de red.
  - Control de umbral de triángulos: campo numérico y botón “Fijar” para ajustar `triWarn` (0 desactiva). También disponible por URL `?triWarn=<int>` y persistente en `localStorage`.
  - Badge ⚠ en la barra cuando los triángulos exceden el umbral.
  - Calidad del eje: checkbox “Calidad eje”, campos “Eje dist (m)” y “Eje ∠ (°)”, y botón “Aplicar”. Persisten en `localStorage`.
  - Body: botón que muestra/oculta el badge de resumen del último body enviado (persistente: `viewer_body_badge_visible`).
  - Copy: botón que copia al portapapeles el resumen actual del body.

Atajos de teclado en el visor:

- `C`: alterna modo Compacto/Normal (si no estás escribiendo en un input).
- `M`: alterna controles avanzados (Más/Menos).
- `P`: Ocultar/Mostrar paneles (log y métricas).
- `B`: Cicla posición de paneles: arriba → abajo → abajo-izquierda.
- `T`: enfoca el campo de umbral de triángulos; `Enter` aplica el valor.
- `H` o `?`: abre/cierra la ayuda rápida en pantalla.
- `F`: activa/desactiva el modo Presentación.

#### Accesibilidad (ARIA)

- La barra (`#toolbar`) expone `role="toolbar"` y `aria-label` descriptivo.
- Actualización de estados en toggles con `aria-pressed` y, cuando aplica, `aria-expanded`/`aria-controls`:
  - `toggle-advanced`, `toggle-panels`, `toggle-map`, `help-ui`.
  - Adicionales: `toggle-grid`, `toggle-parcela`, `toggle-eje`, `toggle-markers`.
- El panel `#debug` anuncia cambios con `aria-live="polite"`.
- Navegación por teclado: Tab para foco; Space/Enter activan los botones de la toolbar.
- Persistencia de estados clave en `localStorage` (p. ej., `viewer_panels_visible`, `viewer_adv_on`, `viewer_markers`, `viewer_parcela_visible`, `viewer_eje_visible`).

##### Checklist rápida A11y

- Navegación por teclado: Tab recorre los controles de la toolbar en orden lógico.
- Activación: Space/Enter sobre botones ejecuta la acción (equivalente a click).
- Estados anunciados: los toggles actualizan `aria-pressed` y, si aplica, `aria-expanded`/`aria-controls`.
- Feedback en vivo: el panel `#debug` y el badge `#body-badge` tienen `aria-live="polite"`.
- Contraste: texto de badges y toolbar legibles sobre el fondo (ver tema/estilos del navegador).
- Foco visible: estilo del foco es claro en botones e inputs.

Selector de librería:

- En la UI puedes elegir `Local`, `jsDelivr`, `unpkg` o `Auto`. También desde la URL con `?lib=auto|local|jsdelivr|unpkg`.
- El script de demo acepta `-Lib` y `-TriWarn` para propagarlos al visor, por ejemplo:
  - `scripts\run_viewer_demo.cmd -Format glb -Download -Lib local -TriWarn 750000`

Parámetros de URL del visor (inicialización de estado UI):

- `adv=1|0`: muestra controles avanzados.
- `panels=1|0`: visibilidad de paneles (log/metrics/debug).
- Preferencias persistidas (localStorage):

- Ahora el visor acepta un cuerpo POST personalizado a `POST /zoning/volume-export` usando el parámetro de URL `body_b64` (JSON UTF-8 en Base64 URL-safe). Esto permite cargar modelos 3D con parámetros dinámicos (municipio, subzona, retranqueos, eje de calle, etc.).
- El script de demo (`scripts/run_viewer_demo.ps1`) levanta el backend en `127.0.0.1:<Port>` si no está en marcha y abre el visor con la URL del export construida con el body embebido.
Flags relevantes: `-DiagFull` fuerza `diag=full` en la URL del visor para activar diagnósticos completos desde el inicio.
- `-Port`: especifica el puerto del backend (por defecto: 8000). Puedes cambiarlo con `-Port 8010` (útil si el 8000 está ocupado o con restricciones). El visor y los enlaces internos usarán ese puerto.
 - `-NoAutoPort`: si el puerto solicitado está en uso y la API no está levantada, el script falla con código 2 en lugar de buscar un puerto alternativo.
 - `-Smoke`: ejecuta un chequeo ligero de salud (GET `/viewer/` y POST al export construido) y termina sin abrir el navegador. Útil para CI.
 - `-StartupTimeoutSec`: segundos a esperar a que la API arranque antes de proceder con el smoke (por defecto 180).
 - `-RetryCount`: reintentos de GET/POST en el smoke (por defecto 2; total intentos = `n+1`).
 - `-RetryDelaySec`: segundos de espera entre reintentos (por defecto 2).
 - `-RetryBackoff`: `fixed` (por defecto) o `exponential`.

Ejemplos rápidos:

```powershell
# Caso básico: usa CSV del plan para Vigo y frente por defecto del plan
scripts\run_viewer_demo.cmd -Format glb -Municipio Vigo -UsePlanFrontDefault -Diagnostics min

# Con subzona y dirección explícita
scripts\run_viewer_demo.cmd -Format glb -Municipio Vigo -Subzona "RZ-2" -FrontDirection north

# Smoke local con backoff exponencial (más robusto en equipos lentos)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_viewer_demo.ps1 `
  -Format glb -Municipio Vigo -UsePlanFrontDefault -Altura 8 -Port 8010 `
  -Smoke -LogDir .\logs-smoke-glb -RetryCount 3 -RetryDelaySec 2 -RetryBackoff exponential

# Altura y retranqueos manuales (sin CSV)
scripts\run_viewer_demo.cmd -Format glb -Altura 18 -Retanqueo 0 -SetbackFront 2 -SetbackSide 1 -SetbackBack 2

# Geometría y eje de calle desde ficheros GeoJSON (Geometry, no Feature)
scripts\run_viewer_demo.cmd -Format glb -Municipio Boiro ^
  -GeometryPath datos\sample_parcela.geojson ^
  -StreetAxisPath datos\sample_street_axis.geojson

# CityJSON descargable y comprimido
scripts\run_viewer_demo.cmd -Format cityjson -Download

# Puerto personalizado (8010)
scripts\run_viewer_demo.cmd -Format glb -Municipio Vigo -UsePlanFrontDefault -Port 8010
- `source` (opcional): procedencia de los parámetros (`csv|mock|autonomica|municipal`). El proveedor CSV la establece automáticamente a `csv`.
- `source_refs` (opcional): referencias de trazabilidad (p.ej., páginas/capítulos de PDF).
- `precedence` (opcional): política de precedencia aplicada (p.ej., `municipal_over_autonomic`). No se lee del CSV.

### Validaciones y errores del CSV

El proveedor CSV valida estructura y rangos. Casos relevantes:

- Obligatorio: columna `municipio`. Si falta: 400 con detalle “CSV faltan columnas requeridas: municipio”.
- `altura_maxima_m` es obligatoria y debe ser > 0. Si falta o no es numérica: 400 (“altura_maxima_m requerida…”). Si ≤ 0: 400 (“altura_maxima_m debe ser > 0”).
- `retranqueo_min_m` si se proporciona, debe ser ≥ 0.
- `setback_front_m`, `setback_side_m`, `setback_back_m` si se proporcionan, deben ser ≥ 0.
- `front_direction_default` admite solo `north|east|south|west` (case-insensitive). Si está definido, debe existir al menos un `setback_*` no vacío; de lo contrario 400 por CSV inconsistente.
- `ocupacion_max` si se proporciona, debe estar en [0,1].
- `edificabilidad_max_m2_m2` si se proporciona, debe ser ≥ 0.

- Otras reglas de selección de filas:

- La coincidencia de `municipio`/`subzona` es case-insensitive y con recorte de espacios.
- Si no se indica `subzona` en la petición, se prefiere una fila con `subzona` vacía para ese municipio.
- Si no hay coincidencias, la API responde 400 (“No se pudieron obtener parámetros municipales …”).

Notas de uso:

- Los retranqueos direccionales del plan (`setback_*`) solo se aplican automáticamente cuando la petición activa el contexto direccional: indicando `front_direction` o aportando `street_axis`.
- Si no hay contexto direccional, se conserva el comportamiento uniforme por `retranqueo_min_m`.
- Los valores vacíos pueden dejarse en blanco (`,,,`).

Política de precedencia recomendada:

- Por defecto, se prioriza normativa municipal sobre autonómica si existe superposición. La API y el `rules engine` pueden utilizar `precedence='municipal_over_autonomic'` para dejar constancia de la regla aplicada.

Ejemplo de CSV (ver `datos/planes_municipales_sample.csv`):

```csv
municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2
Vigo,,16,3,,,,0.42,1.25
Vigo,RZ-2,12,3,2.0,1.0,0.5,north,0.35,0.90
A Coruña,,13.5,3,,,,0.45,1.10
```

Ejemplo mínimo de CSV (solo columnas imprescindibles para un caso sencillo):

```csv
municipio,subzona,altura_maxima_m
Vigo,,12
```

Ejemplo completo con direccionalidad y parámetros adicionales:

```csv
municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2
Vigo,RZ-2,12,3,2.0,1.0,0.5,north,0.35,0.90
```

Notas:

- Si el CSV contiene columnas desconocidas, el sistema emitirá un __warning__ (no fatal) en logs indicando los nombres de dichas columnas, pero continuará cargando el fichero.

Ejemplo de petición usando valores del CSV con modo direccional:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/zoning/volume -Method Post -ContentType 'application/json' -Body '{
  "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
  "municipio": "Vigo",
  "subzona": "RZ-2",
  "front_direction": "north"  # tomará setback_front/side/back del CSV
}'
```

### CSV de ejemplo Vigo/Boiro y script de extracción

- CSV listo para usar: `datos/planes_vigo_boiro.csv` (valores residenciales iniciales extraídos de los PDFs oficiales de Vigo y Boiro).
- Activación rápida (PowerShell):
  ```powershell
  $env:PLAN_PROVIDER = 'csv'
  $env:PLAN_CSV_PATH = 'datos/planes_vigo_boiro.csv'
  uvicorn app.main:app --reload
  ```
- Script de extracción (plantilla) para regenerar el CSV desde semillas confirmadas y verificar presencia de PDFs fuente:
  ```powershell
  .\venv\Scripts\python.exe -u scripts\extract_rules_vigo_boiro.py --out datos\planes_vigo_boiro.csv
  ```
  - El script escribe columnas compatibles con el proveedor (`municipio, subzona, altura_maxima_m, retranqueo_min_m, setback_front/side/back_m, front_direction_default, ocupacion_max, edificabilidad_max_m2_m2`) y añade `source` y `notes` para trazabilidad (estas dos son ignoradas por el proveedor, pero útiles para auditoría).
  - Comprueba que existan los PDFs en `datos/`:
    - `Normativa_Urbanistica-(Castelan) VIGO.pdf`
    - `Texto PXOM Boiro.pdf`
  - Nota: el script actualmente usa valores semilla (manuales) confirmados y sirve como base para extender reglas de parsing.

## Preparación
1. Crear/activar entorno virtual (opcional):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
2. Crear índice (si procede):
```powershell
.\venv\Scripts\python.exe -u src\crear_indice.py
```

## Consulta interactiva
```powershell
.\venv\Scripts\python.exe -u src\consultar_normativa.py
```

## Evaluación
- Dataset: `datos/dataset_ley_2_2016.json`
- Script: `scripts/evaluar_dataset.py`

Ejemplo (con CSV y JSONL):
```powershell
$env:PYTHONIOENCODING='utf-8'; chcp 65001 > $null;
.\venv\Scripts\python.exe -u scripts\evaluar_dataset.py --limit 1000 --debug `
  --csv .\resultados\eval_ley_2016_expanded.csv `
  --jsonl .\resultados\eval_ley_2016_expanded.jsonl
```

## API (FastAPI)

### Arranque del servidor

```powershell
uvicorn app.main:app --reload
```

- Documentación interactiva: `http://127.0.0.1:8000/docs`
- Salud: `GET /health`: estado del API.
- `GET /version`: versión del API.
- `GET /diagnostics/log-config`: devuelve configuración de logging (solo si `DIAGNOSTICS_ENABLED=1/true/yes`).
  Ejemplo de respuesta (recortado):
  ```json
  {
    "root": {
      "level": "INFO",
      "handlers": [
        { "type": "StreamHandler", "level": "INFO", "formatter": "%(asctime)s %(levelname)s %(name)s: %(message)s" },
        { "type": "RotatingFileHandler", "level": "INFO", "formatter": "%(asctime)s %(levelname)s %(name)s: %(message)s", "filename": "app.log", "maxBytes": 2097152, "backupCount": 5 }
      ]
    },
    "loggers": {
      "volume": { "effective_level": "DEBUG", "explicit_level": "DEBUG", "propagate": true }
    }
  }
  ```
- `GET /metrics`: expone métricas Prometheus (solo si `METRICS_ENABLED=1/true/yes`).
  - Incluye contadores `api_requests_total{method,route,status}` y latencias `api_request_latency_seconds{method,route}`.
  - Incluye contador de errores `api_errors_total{method,route,status,error_type}`:
    - `error_type` ∈ {`bad_request` (400), `not_found` (404), `server_error` (≥500), `client_error` (otros 4xx)}.
  - `api_response_size_bytes{method,route,status}`: histograma del tamaño de las respuestas (bytes) observado a partir del header `Content-Length`.
    - Uso: monitorizar el impacto de `DIAGNOSTICS_VERBOSITY`/`diagnostics_verbosity` en el tamaño de payload.
    - Si la respuesta no incluye `Content-Length` (streaming), no se observa tamaño.
    - Buckets configurables con `RESPONSE_SIZE_BUCKETS` (lista separada por comas en bytes, p.ej. `256,512,1024,2048,4096`).
  - `api_validate_csv_cache_hits_total`: contador global de aciertos de caché en `POST /zoning/validate-plan-csv` (modo `path`).
  - `api_validate_csv_cache_misses_total`: contador global de fallos de caché en `POST /zoning/validate-plan-csv` (modo `path`).
  - `api_volume_export_size_bytes{format,status}`: histograma del tamaño de los payloads de exportación 3D (CityJSON/GLTF).
    - `format` ∈ {`cityjson`,`gltf`}.
    - Buckets reutilizan `RESPONSE_SIZE_BUCKETS`.
  - `api_volume_export_requests_total{format,status}`: contador de peticiones de exportación 3D por formato y estado.
  - Ejemplo de activación (PowerShell):
    ```powershell
    $env:METRICS_ENABLED = '1'
    ```
  - Comportamiento:
    - Si `METRICS_ENABLED` está desactivado → `GET /metrics` devuelve 404.
    - Si `prometheus_client` no está disponible → se expone un fallback en texto plano con las métricas básicas para permitir el scrape.
    - Ejemplo de scrape con Prometheus:
      ```yaml
      scrape_configs:
        - job_name: 'asistente-normativa'
          static_configs:
            - targets: ['localhost:8000']
          metrics_path: /metrics
      ```

#### Alertas Prometheus recomendadas (exportación 3D)

```yaml
groups:
  - name: asistente-normativa-export
    rules:
      # p95 de tamaño de respuesta por formato por encima de umbral (15m)
      - alert: VolumeExportHighP95Size
        expr: |
          histogram_quantile(
            0.95,
            sum by (le, format) (rate(api_volume_export_size_bytes_bucket[15m]))
          ) > 524288  # 512 KiB
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "p95 de tamaño de exportación 3D alto (formato {{ $labels.format }})"
          description: |
            El p95 de tamaño de payload para exportación 3D en formato {{ $labels.format }} excede 512KiB
            en los últimos 15m. Revisa geometrías/diagnósticos y compresión.

      # Ratio de errores (>5%) en exportación 3D por formato (10m), con tráfico mínimo
      - alert: VolumeExportHighErrorRate
        expr: |
          sum by (format) (rate(api_volume_export_requests_total{status!~"2.."}[10m]))
          /
          clamp_min(sum by (format) (rate(api_volume_export_requests_total[10m])), 0.0001)
          > 0.05
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Alta tasa de errores en exportación 3D (formato {{ $labels.format }})"
          description: |
            La tasa de errores supera el 5% en los últimos 10m para exportaciones {{ $labels.format }}.
            Inspecciona logs y entradas recientes.

      # Caída de volumen de exportaciones (posible incidencia)
      - alert: VolumeExportTrafficDrop
        expr: |
          sum(rate(api_volume_export_requests_total[30m])) < 0.01
        for: 30m
        labels:
          severity: info
        annotations:
          summary: "Tráfico de exportación 3D muy bajo"
          description: |
            Menos de ~1 petición cada 100s en los últimos 30m. Confirmar si es esperado.
```

#### Paneles Grafana sugeridos (exportación 3D)

- __p95 tamaño por formato__ (bytes):
  ```promql
  histogram_quantile(
    0.95,
    sum by (le, format) (rate(api_volume_export_size_bytes_bucket[5m]))
  )
  ```

- __Tasa de errores por formato__:
  ```promql
  sum by (format) (rate(api_volume_export_requests_total{status!~"2.."}[5m]))
  /
  sum by (format) (rate(api_volume_export_requests_total[5m]))
  ```

- __Requests por formato/estado__ (stacked bar):
  ```promql
  sum by (format, status) (rate(api_volume_export_requests_total[5m]))
  ```

- `PLAN_CSV_PATH`: ruta del CSV si `PLAN_PROVIDER=csv`.
- `API_LOAD_RESOURCES`: Carga recursos pesados al arrancar (por defecto 1).
- `VOLUME_DEBUG`: si se establece a `1/true/yes`, emite logs `DEBUG` (logger `volume`) con decisiones de frente/retranqueos.
- `LOG_LEVEL`: nivel raíz de logging (`DEBUG`/`INFO`/`WARNING`/...). Por defecto `INFO`.
- `LOG_FILE`: si se establece, activa escritura a fichero con rotación.
- `LOG_MAX_BYTES`: tamaño máximo por fichero para rotación (por defecto `5 MiB`).
- `LOG_BACKUP_COUNT`: número de ficheros de backup retenidos (por defecto `3`).
- `DIAGNOSTICS_ENABLED`: si `1/true/yes`, habilita el endpoint de diagnóstico `/diagnostics/log-config`.
- `METRICS_ENABLED`: si `1/true/yes`, habilita middleware de métricas y el endpoint `/metrics` (Prometheus).
- `ADMIN_TOKEN`: si se define, protege los endpoints de administración (p.ej. `/admin/reload-plan`).
  - El token debe enviarse en `X-Admin-Token: <token>` o `Authorization: Bearer <token>`.
- `DIAGNOSTICS_VERBOSITY`: controla la verbosidad de campos diagnósticos en respuestas (por ejemplo en `POST /zoning/volume`). Valores:
  - `full` (por defecto): expone todos los diagnósticos (`front_detected_side`, `front_direction_source`, `street_axis_*`, `front_selection_rationale`, `polygon_type`, `directional_*`, etc.).
  - `min`: mantiene un subconjunto mínimo útil (`front_detected_side`, `front_direction_source`, `polygon_type`).
  - `none`: elimina todos los campos diagnósticos del `properties` devuelto.
- `VALIDATE_CACHE_MAX`: tamaño máximo del caché en memoria para `POST /zoning/validate-plan-csv` en modo `path` (por defecto `128`, mínimo `1`, máximo `4096`).
- `RESPONSE_SIZE_BUCKETS`: lista de buckets (en bytes) para `api_response_size_bytes` separada por comas. Por defecto: `512,1024,2048,4096,8192,16384,32768,65536,131072,262144`.
- `RECT_TOL_AREA_RATIO_MIN`: mínimo de la relación de áreas entre la parcela y su rectángulo mínimo rotado (por defecto `0.995`).
- `RECT_TOL_AREA_RATIO_MAX`: máximo de la relación de áreas entre la parcela y su rectángulo mínimo rotado (por defecto `1.005`).
- `RECT_TOL_SYMDIFF_PCT`: máximo de la diferencia simétrica entre la parcela y su rectángulo mínimo rotado como porcentaje del área de la parcela (por defecto `0.005` ≙ `0.5%`).

### Endpoints

- `POST /qa`
{{ ... }}
    - Propiedades adicionales de trazabilidad:
      - `street_axis_used` (bool): indica si el eje de calle se usó para detectar el frente.
      - `front_detected_side` (top|bottom|left|right|null): lado detectado como frente en el marco de cálculo.
      - `front_direction_source`: `street_axis` | `plan_default` | `request` | `none`.
- `street_axis_ignored_reason`: `too_far` | `geom_error` | `null`.
- `polygon_type`: tipo de polígono de la parcela detectado (`rectangle_axis_aligned`, `rectangle_rotated`, `general`).
- `directional_applicability`: estado de aplicación de retranqueos direccionales (`applied`, `not_applicable`, `not_requested`).
- `directional_not_applied_reason`: razón cuando no se aplican retranqueos direccionales (p.ej. `non_rectangular_parcel`).

Opciones de verbosidad de diagnósticos:
- En variables de entorno: `DIAGNOSTICS_VERBOSITY=full|min|none` (global).
- Por petición: añadir `diagnostics_verbosity` al body de `POST /zoning/volume` con valores `full|min|none` para sobrescribir el valor global en esa llamada.
- La respuesta incluye `diagnostics_level_applied` indicando el nivel aplicado efectivamente.
  - Reglas adicionales:
    - Detección de duplicados por clave `(municipio, subzona)`; se reportan como errores.
  - Ejemplos:
    - Vía texto CSV:
      ```powershell
      $csv = @"
      municipio,subzona,altura_maxima_m
        "errors": [
          { "municipio": "Foo", "subzona": null, "message": "Valor inválido en CSV para Foo: altura_maxima_m debe ser > 0" }
        ],
        "warnings": [
          "Columnas desconocidas: extra_col"
        ],
        "summary": { "errors": 1, "warnings": 1 },
        "cache_hit": false
      }
      ```

- `POST /zoning/volume-export`
  - Exporta la envolvente edificable como CityJSON (sólido extruido) reutilizando la lógica de `/zoning/volume`.
  - Request body: los mismos campos que `POST /zoning/volume` más `format` (opcional, `cityjson` o `gltf` o `glb`).
  - Soporte por formato:
    - CityJSON: soporta `Polygon` con huecos y `MultiPolygon` (cada polígono → un `Solid`).
    - GLTF: limitado a `Polygon` sin huecos.
    - GLB: binario, limitado a `Polygon` sin huecos.
  - Descarga directa: añadir query `?download=true` para recibir un adjunto con nombre y tipo adecuados.
    - CityJSON: `application/city+json`, filename `building.city.json`.
    - GLTF: `model/gltf+json`, filename `building.gltf`.
  - Compresión CityJSON: añade `gzip=true` junto a `download=true` para recibir contenido comprimido gzip.
    - Ejemplo (PowerShell):
      ```powershell
      $body = @{ geometry = @{ type = 'Polygon'; coordinates = @(@(@(0,0), @(10,0), @(10,10), @(0,10), @(0,0))) }; altura_maxima_m = 10; retranqueo_min_m = 0; format = 'cityjson' } | ConvertTo-Json -Depth 6
      Invoke-RestMethod -Method Post -Uri http://localhost:8000/zoning/volume-export?download=true&gzip=true -ContentType 'application/json' -Body $body -OutFile building.city.json.gz
      ```
  - Modo estricto (CityJSON): añade `strict=true` para desactivar el fallback que extruye la geometría original cuando la envolvente falla.
    - Ejemplo: `POST /zoning/volume-export?format=cityjson&strict=true` (devolverá 400 si la envolvente no puede calcularse).
  - Ejemplo (PowerShell):
    ```powershell
    $body = @{ 
      geometry = @{ type = 'Polygon'; coordinates = @(@(@(0,0), @(10,0), @(10,5), @(0,5), @(0,0))) };
      altura_maxima_m = 12; retranqueo_min_m = 2; format = 'cityjson'
    } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method Post -Uri http://localhost:8000/zoning/volume-export?download=true -ContentType 'application/json' -Body $body -OutFile building.city.json
    ```
  - Ejemplo GLTF (PowerShell):
    ```powershell
    $body = @{ 
      geometry = @{ type = 'Polygon'; coordinates = @(@(@(0,0), @(10,0), @(10,5), @(0,5), @(0,0))) };
      altura_maxima_m = 12; retranqueo_min_m = 2; format = 'gltf'
    } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method Post -Uri http://localhost:8000/zoning/volume-export?download=true -ContentType 'application/json' -Body $body -OutFile building.gltf
    ```
  - Ejemplo CityJSON con hueco (PowerShell):
    ```powershell
    $polyWithHole = @{ 
      type = 'Polygon'; 
      coordinates = @(
        @(@(0,0), @(10,0), @(10,10), @(0,10), @(0,0)),            # exterior
        @(@(3,3), @(7,3), @(7,7), @(3,7), @(3,3))                  # hueco
      )
    }
    $body = @{ geometry = $polyWithHole; altura_maxima_m = 10; retranqueo_min_m = 0; format = 'cityjson' } | ConvertTo-Json -Depth 8
    Invoke-RestMethod -Method Post -Uri http://localhost:8000/zoning/volume-export?download=true -ContentType 'application/json' -Body $body -OutFile building_hole.city.json
    ```

  - Ejemplo CityJSON MultiPolygon (PowerShell):
    ```powershell
    $multi = @{ 
      type = 'MultiPolygon'; 
      coordinates = @(
        @(@(@(0,0), @(2,0), @(2,2), @(0,2), @(0,0))),
        @(@(@(5,5), @(7,5), @(7,7), @(5,7), @(5,5)))
      )
    }
    $body = @{ geometry = $multi; altura_maxima_m = 5; retranqueo_min_m = 0; format = 'cityjson' } | ConvertTo-Json -Depth 8
    Invoke-RestMethod -Method Post -Uri http://localhost:8000/zoning/volume-export?download=true -ContentType 'application/json' -Body $body -OutFile building_multi.city.json
    ```
  - Respuesta CityJSON: objeto CityJSON v1.0 con `CityObjects.Building[0].geometry[0].type = Solid`, vertices 3D y superficies (`RoofSurface`, `GroundSurface`, `WallSurface`).
  - Respuesta GLTF: objeto GLTF 2.0 con un solo mesh y buffers embebidos vía data URI.

## Monitoring (Prometheus / Grafana)

- __Dashboard Grafana__
  - Archivo: `monitoring/grafana-dashboard-volume-export.json`
  - Importar en Grafana: Dashboards → New → Import → Upload JSON → seleccionar el archivo → elegir tu datasource Prometheus.
  - Paneles incluidos: RPS por formato/estado, error rate por formato, p95 de tamaño por formato, stats rápidas para CityJSON/GLTF.

- __Alertas Prometheus__
  - Archivo: `monitoring/prometheus-alerts-volume-export.yaml`
  - Añade a tu `prometheus.yml`:
    ```yaml
    rule_files:
      - monitoring/prometheus-alerts-volume-export.yaml
    ```
  - Reinicia o recarga Prometheus. Incluye reglas para:
    - Error rate > 5% por 10m (por formato)
    - p95 de tamaño > 5 MB por 10m (por formato)
    - Bajo tráfico (<0.001 rps) por 30m

Notas:
- Las métricas ya expuestas por el servicio incluyen `api_volume_export_requests_total{format,status}` y `api_volume_export_size_bytes{format,status}`.
- Cuando `gzip=true` (CityJSON en descarga), el tamaño observado corresponde al payload comprimido para reflejar el tamaño en la red.

- `POST /admin/reload-plan`
  - Recarga y valida el planeamiento municipal cuando `PLAN_PROVIDER=csv`.
  - Request body (opcional): `{ "path": "C:/ruta/planes.csv" }`.
    - Si se aporta `path` y es válido, actualiza `PLAN_CSV_PATH` en caliente.
    - Si no se aporta, usa el `PLAN_CSV_PATH` actual y lo valida.
  - Efectos: limpia el caché del validador CSV.
  - Respuesta típica:
    ```json
    { "ok": true, "provider": "csv", "applied_path": "C:/ruta/planes.csv", "rows": 123 }
    ```
  - Seguridad:
    - Si `ADMIN_TOKEN` está definido, es obligatorio incluirlo en cada llamada.
    - Ejemplos (PowerShell):
      - Con `X-Admin-Token`:
        ```powershell
        $env:ADMIN_TOKEN = 'mi_token_secreto'
        Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/reload-plan \
          -Headers @{ 'X-Admin-Token' = 'mi_token_secreto' } \
          -Body (@{ path = "C:/ruta/planes.csv" } | ConvertTo-Json) -ContentType 'application/json'
        ```
      - Con `Authorization: Bearer`:
        ```powershell
        $env:ADMIN_TOKEN = 'mi_token_secreto'
        Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/reload-plan \
          -Headers @{ 'Authorization' = 'Bearer mi_token_secreto' } \
          -Body (@{ path = "C:/ruta/planes.csv" } | ConvertTo-Json) -ContentType 'application/json'
        ```

### Detección de casi-rectángulos (tolerancia)

La API admite aplicar retranqueos direccionales a parcelas “casi rectangulares”, no solo a rectángulos exactos. Se compara la parcela con su `minimum_rotated_rectangle` de Shapely, y si ambas son suficientemente similares, se trata como `rectangle_rotated` y se aplican retranqueos direccionales.

Condiciones por defecto:

- __Ratio de áreas__: `area(min_rot_rect) / area(parcel)` en `[0.995, 1.005]`.
- __Diferencia simétrica__: `area(parcel △ min_rot_rect)` ≤ `0.5%` del área de la parcela.

Estas tolerancias son configurables vía variables de entorno:

- `RECT_TOL_AREA_RATIO_MIN` (por defecto `0.995`).
- `RECT_TOL_AREA_RATIO_MAX` (por defecto `1.005`).
- `RECT_TOL_SYMDIFF_PCT` (por defecto `0.005` ≙ `0.5%`).

Ejemplo de ejecución ajustando tolerancias:

```bash
# Windows PowerShell
$env:RECT_TOL_AREA_RATIO_MIN = "0.992"
$env:RECT_TOL_AREA_RATIO_MAX = "1.008"
$env:RECT_TOL_SYMDIFF_PCT    = "0.008"
uvicorn app.main:app --reload
```
      - `street_axis_ignored_reason` (too_far|geom_error|null): motivo por el que se ignoró `street_axis` si aplica.
  - Notas:
    - Si se proporcionan retranqueos diferenciados pero no es posible aplicar direccionalidad, se usa el __máximo__ como retranqueo uniforme (`setback_mode = "conservative_max_uniform"`).
    - Si la geometría es un rectángulo (alineado o rotado) y se indica `front_direction`, se aplican retranqueos por lado (`setback_mode = "rect_directional"` o `"rotated_rect_directional"`).
    - Alternativamente, si se aporta `street_axis` y no se indica `front_direction`, el frente se detecta automáticamente como el lado más cercano a la vía.
{{ ... }}
### Ejemplos rápidos (PowerShell)

```powershell
# QA
Invoke-RestMethod -Uri http://127.0.0.1:8000/qa -Method Post -ContentType 'application/json' -Body '{"pregunta":"¿Qué usos se permiten en suelo rústico?"}'

# Volumen con detección automática de frente (street_axis)
Invoke-RestMethod -Uri http://127.0.0.1:8000/zoning/volume -Method Post -ContentType 'application/json' -Body '{
  "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
  "altura_maxima_m": 9,
  "setback_front_m": 2.0,
  "setback_back_m": 1.0,
  "setback_side_m": 0.5,
  "street_axis": {"type":"LineString","coordinates":[[0,11],[10,11]]}
}'

# Análisis de zona
Invoke-RestMethod -Uri http://127.0.0.1:8000/zoning/analyze -Method Post -ContentType 'application/json' -Body '{
  "zona":"urbano","uso_previsto":"residencial","municipio":"Vigo","subzona":"RZ-2"
}'

# Chequeos geométricos
Invoke-RestMethod -Uri http://127.0.0.1:8000/zoning/geometry-checks -Method Post -ContentType 'application/json' -Body '{
  "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}
}'

# Chequeos geométricos con reproyección CRS
Invoke-RestMethod -Uri http://127.0.0.1:8000/zoning/geometry-checks -Method Post -ContentType 'application/json' -Body '{
  "geometry": {"type":"Polygon","coordinates":[[[-8.0,42.0],[-8.0,42.0001],[-8.0001,42.0001],[-8.0001,42.0],[-8.0,42.0]]]},
  "crs": "EPSG:4326", "target_crs": "EPSG:25829"
}'

# Volumen (usando plan municipal)
Invoke-RestMethod -Uri http://127.0.0.1:8000/zoning/volume -Method Post -ContentType 'application/json' -Body '{
  "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]] },
  "municipio":"Vigo","subzona":"RZ-2"
}'

# Volumen con retranqueos diferenciados
Invoke-RestMethod -Uri http://127.0.0.1:8000/zoning/volume -Method Post -ContentType 'application/json' -Body '{
  "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]] },
  "altura_maxima_m": 10.0,
  "retranqueo_min_m": 1.0,
  "setback_front_m": 2.0,
  "setback_side_m": 3.0,
  "setback_back_m": 1.5,
  "front_direction": "north"
}'
```

## Diseño y decisiones clave
- `src/asistente_normativa.py`
  - `buscar_fragmentos()`: multipaso, inyección previa de Ley+artículo inferido, reranking, y refuerzos por fuente/artículo.
  - `generar_respuesta()`: respuestas extractivas; early-returns canónicos para Art. 13/17/27/32/44 y caso comparativo urbanizable vs rústico.
  - Limpieza OCR e higiene Unicode.
- `scripts/evaluar_dataset.py`
  - Métrica: recall de solapamiento de tokens (umbral 0.5).
  - Desglose por artículo y exportación CSV/JSONL.

## Ampliación del dataset
Añadir variantes en `datos/dataset_ley_2_2016.json`:
- Art. 44: VPO/VPP/protección oficial + reservas de suelo.
- Art. 32: “usos permitidos/permitidas”, sinónimos.
- Art. 13: “núcleo tradicional”.
- Comparativas multiartículo (p.ej., urbanizable vs rústico).

## Notas
- Variables de entorno útiles:
  - `RETRIEVAL_DEBUG=1` para trazas de recuperación/reranking.
- Los ficheros de resultados se guardan en `resultados/`.
