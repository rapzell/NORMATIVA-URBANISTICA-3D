# Flujo offline: ODT/PDF → CSV → Backend → Visor

Este documento describe cómo trabajar sin servicios municipales (WMS/ArcGIS), usando CSV como fuente de normativa para el backend y el visor 3D.

## Esquema soportado por el backend (`src/planes/csv_provider.py`)

Columnas esperadas (cabeceras):

- municipio
- subzona
- altura_maxima_m
- retranqueo_min_m
- setback_front_m
- setback_side_m
- setback_back_m
- front_direction_default
- ocupacion_max
- edificabilidad_max_m2_m2

Notas:
- Valores numéricos en metros. `ocupacion_max` es fracción (0.40 == 40%).
- Se recomienda incluir una fila por defecto del municipio (subzona vacía) para evitar paneles en blanco.

## Extracción desde documentos

Opciones disponibles en `scripts/`:

- `odt_to_plan_csv.py`: Convierte un `.odt` con texto a CSV (heurístico por expresiones regulares).
  
  Ejemplo:
  
  ```bash
  py scripts/odt_to_plan_csv.py "datos/Parametros Vigo A Coruña.odt" "datos/plan_from_odt.csv"
  ```

- `extract_tables_pdfplumber.py`: Extrae tablas desde PDF con `pdfplumber` (más robusto que texto plano), filtra páginas por palabras clave y aplica umbrales de plausibilidad.
  
  Ejemplo:
  
  ```bash
  py scripts/extract_tables_pdfplumber.py "datos/Normativa_Urbanistica-(Castelan) VIGO.pdf" "datos/extracted_vigo_suelo_urbano_filtered.csv" "suelo urbano,residencial,ordenanza,uso residencial,condiciones de edificación,parámetros,ordenanzas"
  ```

## Aplicar un CSV al backend (puerto 8002)

- Endpoint de administración (acepta CSV como texto):
  
  POST `http://127.0.0.1:8002/admin/apply-plan-csv-text`
  
  Body JSON: `{ "csv_text": "<contenido CSV>" }`

- Script helper (ver siguiente sección) para enviar un CSV local.

- Verificar plan activo:
  
  GET `http://127.0.0.1:8002/admin/plan-summary`

## Script helper: aplicar CSV en 8002

En `scripts/apply_csv_text_8002.py` (incluido en el repo):

```bash
py scripts/apply_csv_text_8002.py datos/plan_municipal.csv
```

Devuelve la respuesta del backend y permite confirmar la carga del plan.

## Visor 3D (same-origin)

- URL: `http://127.0.0.1:8002/viewer`
- Para centrar pruebas en normativa municipal, se recomienda desactivar fuentes no esenciales:

```js
localStorage.setItem('viewer_siose_enable','off');
localStorage.setItem('viewer_buildings_prefetch','off');
localStorage.setItem('viewer_buildings_enable','off');
localStorage.setItem('viewer_terrain_enable','off');
location.reload();
```

- Selector manual de subzona (ordenanza): disponible en el panel `Normativa (beta)`. Permite forzar U3, U6.x, NR-x, etc.
- Conflicto de fuentes: si la zona es rústico y la subzona no parece una ordenanza municipal, el visor muestra `Subzona: —` y un aviso de conflicto SIOSE vs SIU.

## Endpoints útiles

- Salud/versión: `GET /health`, `GET /version`
- Plan activo: `GET /admin/plan-summary`
- Analizar normativa: `POST /zoning/analyze`
- Volúmenes/viabilidad: `POST /zoning/volume`, `POST /zoning/assess`

## Tests offline

Se han añadido tests que validan lectura desde CSV sin APIs externas:

- `tests/test_csv_offline_min.py`: Vigo U3 y A Coruña NR-1.
- `tests/test_csv_offline_boiro.py`: Boiro Ordenanza 1 y 3.

Ejecutar (si tienes pytest):

```bash
pip install -r requirements.txt
pip install pytest
pytest -q tests/test_csv_offline_min.py
pytest -q tests/test_csv_offline_boiro.py
```

## Futuro: Integración ArcGIS (Vigo)

Cuando dispongas de la URL del Feature Layer público de zonificación del PXOM 2025:

- Configurar variable de entorno `VIGO_ARCGIS_FEATURE_URL` con la URL del layer (termina en `/FeatureServer/<layer>` o `/MapServer/<layer>`).
- El endpoint `POST /zoning/infer-subzone` devolverá U3/U6.x automáticamente por coordenadas.
- El visor ya no requerirá el selector manual para Vigo.
