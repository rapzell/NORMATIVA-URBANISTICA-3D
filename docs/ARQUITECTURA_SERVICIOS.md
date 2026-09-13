# Arquitectura de servicios — NORMATIVA GALICIA 3D

## 1. Visión general

El sistema sigue una arquitectura por capas:

```
┌─────────────────────────────────────────────────────┐
│  Frontend                                           │
│  ├─ /viewer  (Three.js — visor 3D especializado)    │
│  └─ /geolibre (MapLibre GL JS — vista GIS)          │
├─────────────────────────────────────────────────────┤
│  FastAPI — app/main.py (capa HTTP delgada)          │
│  ├─ routes, request/response models, metrics       │
│  └─ HTTP errors, headers, gzip, download           │
├─────────────────────────────────────────────────────┤
│  Servicios de dominio — src/*_service.py            │
│  ├─ normativa_extract.py  (extracción de campos)   │
│  ├─ plans_service.py      (proveedor de planes)    │
│  ├─ qa_service.py         (fallback QA)            │
│  ├─ zoning_service.py      (helpers GIS + subzonas) │
│  ├─ zoning_assess.py       (evaluación urbanística) │
│  ├─ volume_service.py     (diagnóstico de volumen)  │
│  ├─ export_service.py     (CityJSON/GLTF/GLB)       │
│  ├─ report_service.py     (informe HTML + SVG)      │
│  └─ subzones_service.py   (capa espacial subzonas)  │
├─────────────────────────────────────────────────────┤
│  Motor geométrico — src/volume.py                   │
│  ├─ compute_building_envelope                      │
│  └─ VolumeParams                                   │
├─────────────────────────────────────────────────────┤
│  Proveedores de planes — src/planes/               │
│  ├─ base.py        (PlanParams, interfaz)           │
│  ├─ csv_provider.py (CSV municipal)                 │
│  └─ mock_provider.py (mock para tests)              │
├─────────────────────────────────────────────────────┤
│  IA / RAG                                           │
│  ├─ model_gateway.py   (multi-proveedor con fallback)│
│  └─ asistente_normativa.py (RAG + FAISS)           │
├─────────────────────────────────────────────────────┤
│  Datos                                              │
│  ├─ plan_activo.csv          (parámetros normativos)│
│  ├─ datos/subzonas_piloto.geojson (capa espacial)   │
│  └─ datos/             (served via /data)           │
└─────────────────────────────────────────────────────┘
```

## 2. Principios de diseño

1. **FastAPI es la autoridad normativa**: la decisión oficial de viabilidad siempre viene del backend.
2. **Servicios desacoplados**: cada servicio tiene una responsabilidad clara y es testeable de forma aislada.
3. **API estable**: los endpoints públicos no cambian; la refactorización es interna.
4. **100% gratuito**: sin dependencias de pago; IA multi-proveedor con fallback.
5. **GeoLibre complementa, no reemplaza**: el visor 3D se conserva; GeoLibre añade capacidades GIS.

## 3. Servicios de dominio

### normativa_extract.py
- `extract_normativa_fields()`: heurística de extracción de campos normativos desde texto.
- Usado por: `POST /normativa/extract`.

### plans_service.py
- `get_plan_provider()`: proveedor de planes por entorno (CSV/mock).
- `get_plan_params_dynamic()`: resolución dinámica de parámetros municipales.
- `get_plan_provider_kind()`: tipo de proveedor activo.
- Conversión segura entre modelos Pydantic de distintos proveedores.
- Usado por: assess, volume, export, QA, debug.

### qa_service.py
- `build_qa_fallback_response()`: respuesta heurística de fallback para `/qa`.
- `build_qa_verbose_fallback_response()`: respuesta con diagnóstico para `/qa/verbose`.
- Usado por: `POST /qa`, `POST /qa/verbose`.

### zoning_service.py
- Helpers GIS: `arcgis_feature_query`, `arcgis_identify_extract`, `wms_config_for_municipio`, `lonlat_to_mercator`, `mercator_to_lonlat`, `centroid_lonlat_from_geojson`, `build_wms_getfeatureinfo_url`, `extract_subzone_from_wms_json`.
- `infer_subzone()`: orquestación completa de inferencia de subzona (ArcGIS Identify, Feature/query, WMS GetFeatureInfo).
- Usado por: `POST /zoning/infer-subzone`, `POST /zoning/analyze`.

### zoning_assess.py
- `resolve_assess_effective_params()`: resuelve altura, retranqueos, dirección de frente, plan y motivos.
- `evaluate_zoning_assessment()`: evaluación completa de viabilidad (sin geometría, geometry checks, envolvente, heurística de viabilidad, diagnósticos direccionales).
- `ZoningAssessmentError`: excepción controlada.
- Usado por: `POST /zoning/assess`, endpoints de informe.

### volume_service.py
- `infer_limiting_factor()`: diagnostica qué limita el volumen (altura, ocupación, edificabilidad, retranqueos).
- Usado por: `POST /zoning/volume`.

### export_service.py
- `normalize_export_format()`: validación de formatos (cityjson, gltf, glb).
- `build_volume_export_feature()`: construcción del feature exportable.
- Serializadores: CityJSON, GLTF embebido, GLB binario.
- Detección de parcela agotada.
- Usado por: `POST /zoning/volume-export`, `GET /zoning/volume-export`.

### report_service.py
- `render_assess_report_html()`: informe HTML con branding, firma, observaciones, fuente normativa.
- `render_svg_minimap()`: composición cartográfica SVG (parcela + envolvente).
- Usado por: `GET /zoning/assess-report`, `POST /zoning/assess-report`, `GET /zoning/assess-report.pdf`.

### subzones_service.py
- `get_subzones(municipio)`: GeoJSON de subzonas, filtrado opcional por municipio.
- `list_municipios_with_subzones()`: lista de municipios con capa espacial.
- `find_subzone_for_point(lon, lat)`: busca subzona por punto (shapely o bbox).
- Usado por: `GET /planeamiento/subzonas`, `GET /planeamiento/subzonas/municipios`, `GET /planeamiento/subzonas/lookup`.

## 4. Endpoints API

### Normativa
- `POST /normativa/extract` — extracción de campos normativos.

### QA / IA
- `POST /qa` — pregunta al asistente RAG.
- `POST /qa/verbose` — pregunta con diagnóstico.

### Zoning
- `POST /zoning/assess` — evaluación de viabilidad.
- `POST /zoning/volume` — cálculo de volumen edificable.
- `POST /zoning/volume-export` — exportación CityJSON/GLTF/GLB.
- `GET /zoning/volume-export` — exportación vía GET.
- `POST /zoning/infer-subzone` — inferencia de subzona GIS.
- `POST /zoning/geometry-checks` — checks geométricos.
- `GET /zoning/assess-report` — informe HTML.
- `POST /zoning/assess-report` — informe HTML vía POST.
- `GET /zoning/assess-report.pdf` — informe PDF.

### Planeamiento
- `GET /planeamento/inventario` — inventario CSV Xunta.
- `GET /planeamiento/subzonas` — GeoJSON de subzonas espaciales.
- `GET /planeamiento/subzonas/municipios` — municipios con subzonas.
- `GET /planeamiento/subzonas/lookup` — busca subzona por punto.

### Debug
- `GET /debug/plan` — depuración de parámetros del plan.

### Admin
- `POST /admin/apply-plan-csv-text` — aplicar plan CSV.
- `GET /admin/plan-download` — descargar plan activo.
- `POST /admin/reload-plan` — recargar plan.
- `GET /admin/plan-summary` — resumen del plan.

### GIS / Proxies
- `GET /proxy/siose` — proxy SIOSE.
- `GET /proxy/wmscap` — proxy WMS capabilities.

### Health
- `GET /health` — estado del servicio.

### Frontend
- `/viewer` — visor Three.js.
- `/geolibre` — vista GIS GeoLibre.
- `/web` — assets estáticos.
- `/data` — datos de ejemplo.

## 5. IA / RAG

### model_gateway.py
- Multi-proveedor OpenAI-compatible: OpenRouter, Groq, Gemini, local.
- Fallback chain configurable vía `MODEL_FALLBACK_CHAIN`.
- Variables: `MODEL_PROVIDER`, `MODEL_NAME`, `MODEL_API_KEY`, `MODEL_BASE_URL`, `MODEL_MIN_RESPONSE_CHARS`.
- `generate_with_fallback()`: recorre la cadena de proveedores.

### asistente_normativa.py
- RAG con FAISS + Sentence Transformers + CrossEncoder.
- `cargar_recursos()`: carga índice FAISS y modelos.
- `buscar_fragmentos()`: búsqueda semántica con fallback seguro.
- `faiss` es opcional: si no está disponible, cae a modo básico.

## 6. Datos

### plan_activo.csv
Parámetros normativos por municipio/subzona:
- `altura_maxima_m`, `retranqueo_min_m`, `setback_front_m`, `setback_side_m`, `setback_back_m`, `front_direction_default`, `ocupacion_max`, `edificabilidad_max_m2_m2`.

### datos/subzonas_piloto.geojson
Capa espacial piloto con 4 subzonas en 3 municipios (Vigo, A Coruña, Santiago).
Incluye geometría + propiedades normativas completas.

## 7. Testing

### Tests actuales (42 passed)
- `test_api_endpoints.py` — endpoints API + infer-subzone.
- `test_health_and_proxies.py` — health + proxies.
- `test_wmscap_proxy.py` — proxy WMS.
- `test_assess_endpoints.py` — /zoning/assess.
- `test_assess_regression.py` — regresión de assess.
- `test_zoning_assess_unit.py` — tests unitarios del evaluador.
- `test_volume.py` — /zoning/volume.
- `test_volume_regression.py` — regresión de volumen.
- `test_volume_export.py` — exportación.
- `test_export_diagnostics.py` — diagnósticos de export.
- `test_assess_report_branding.py` — informe + composición cartográfica.
- `test_subzones_endpoints.py` — subzonas espaciales.
- `test_geolibre_view.py` — vista GeoLibre.
- `test_model_gateway.py` — gateway IA.
- `test_asistente_normativa_rules.py` — RAG.

### Comando
```bash
python -m pytest tests/ -q
```

## 8. Roadmap completado

| Fase | Estado |
|------|--------|
| Fase 0 — refactor backend | ✅ |
| Fase 1 — gateway IA gratuito | ✅ |
| Fase 2 — dataset espacial subzonas | ✅ |
| Fase 3 — vista GeoLibre paralela | ✅ |
| Fase 4 — flujo híbrido GIS+backend | ✅ |
| Fase 5 — informes reforzados | ✅ |

## 9. Configuración

### .env
```dotenv
MODEL_PROVIDER=openrouter
MODEL_NAME=openrouter/free
MODEL_API_KEY=<tu_key>
MODEL_FALLBACK_CHAIN=groq,gemini,local
MODEL_PROFILE=balanced
MODEL_MIN_RESPONSE_CHARS=4
```

### Arranque
```bash
python -m uvicorn app.main:app --reload
```

### Vistas
- Visor 3D: `http://localhost:8000/viewer/`
- Vista GIS: `http://localhost:8000/geolibre/`
- API docs: `http://localhost:8000/docs`
