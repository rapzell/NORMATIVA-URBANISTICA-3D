# Guía técnica — Visor Arquitectos (análisis urbanístico de Galicia)

Documento de referencia del estado actual del programa, escrito para planificar mejoras.
Fecha de análisis: rama `feat/demo-silencioso`, commit `aeb7d34`+ (con diagrama archify).

---

## 1. Qué es el programa

Aplicación web local (FastAPI + MapLibre/GeoLibre) para que AC8 Arquitectura evalúe
locales comerciales y oficinas como candidatos a conversión en vivienda en Galicia.
Combina visualización GIS 3D, consulta de fuentes oficiales (Catastro, SIOTUGA, SIOSE),
análisis normativo preliminar (NHV/Decreto 128/2023) y generación de documentos
(informe de viabilidad HTML, documentación de licencia).

**Principio rector:** distinguir siempre datos oficiales, datos piloto/orientativos,
supuestos del usuario y datos no verificables. Nunca presentar lo piloto como oficial.

---

## 2. Arquitectura por capas

```
Navegador (cliente)
├── web/geolibre/index.html   → visor 3D + panel + formularios (vanilla JS)
└── localStorage              → proyectos multi-estado (visoarq_projects_v1)

Servidor local :8002 (FastAPI, app/main.py ~3800 líneas)
├── Endpoints /proxy/*        → SIOSE WFS, WMS cap/info, OSM buildings
├── Endpoints /official/*     → contexto oficial (Catastro+SIOSE+SIOTUGA)
├── Endpoints /zoning/*       → assess, volume, diagnostics, sombras, informe
├── Endpoints /habitabilidad, /licencia, /solar, /costes, /ordenanzas
└── Motor de análisis (src/)  → módulos puros llamados desde los endpoints

Datos locales (datos/, mayoría gitignored)
├── subzonas_piloto.geojson   → subzonas con parámetros ORIENTATIVOS
├── inventario_planeamento.csv→ inventario municipal (no trackeado)
├── plan_uploaded.csv         → CSV de trabajo del usuario (ignorado)
├── ordenanzas/               → esquema + ordenanzas por municipio
└── cache/osm_buildings/      → caché GeoJSON en disco (TTL 7 días)

Servicios externos (HTTPS, truststore activado)
├── Overpass API (2 mirrors)  → edificios OSM
├── Catastro OVC + INSPIRE    → refcat, usos, parcela, superficies
├── SIOTUGA WMS + WFS         → capa plan vigente, clasificación del suelo
└── SIOSE / IDEE WFS          → ocupación del suelo
```

Diagrama interactivo: `docs/diagrama-arquitectura.html` (fuente:
`docs/diagrama.arquitectura.json`, regenerable con la skill archify).

---

## 3. Backend — app/main.py

### 3.1 Endpoints principales

| Endpoint | Método | Qué hace |
|---|---|---|
| `/proxy/osm-buildings` | GET | Devuelve edificios OSM del municipio en GeoJSON extruible (altura, niveles, cumplimiento vs subzona piloto). Caché memoria+disco. |
| `/official/context` | GET | **Núcleo**: reúne Catastro+SIOSE+SIOTUGA+inventario para un punto. Devuelve `data_quality`, `official_links`, `clasificacion_siotuga`. |
| `/official/catastro/by-coords` | GET | refcat + dirección desde coordenadas (OVC). |
| `/official/siotuga-wms*` | GET | Descubrimiento de capa del plan vigente, proxy GetMap y proxy de tiles XYZ→WMS. |
| `/zoning/assess` `/zoning/assess-report` | GET/POST | Evaluación volumétrica de parcela + informe HTML completo. |
| `/zoning/volume` `/zoning/volume-export` | POST | Envolvente edificable 3D (GeoJSON/IFC). |
| `/zoning/building-diagnostic` | GET | Compara edificio vs subzona (orientativo). |
| `/zoning/shadow-analysis` | GET/POST | Sombras multi-hora del solsticio de invierno. |
| `/habitabilidad/verificar` | POST | Preverificación NHV (Decreto 128/2023). |
| `/licencia/documentacion` | POST | Genera documentación de licencia HTML. |
| `/solar/exposicion` | GET | Soleamiento anual por orientación (astronómico). |
| `/costes/estimar` | POST | Estimación de costes con inputs del usuario. |
| `/ordenanzas/*` | GET | Ordenanzas locales por municipio/subzona (datos `datos/ordenanzas/`). |
| `/planeamento/*` | GET | Inventario municipal + subzonas piloto. |
| `/admin/*` | GET/POST | Recarga de CSV de planes (`plan_uploaded.csv`), resúmenes. |
| `/qa`, `/normativa/extract*` | POST | RAG/extracción normativa (requiere torch — excluido en Py3.14). |
| `/health` `/version` `/metrics` | GET | Operación. Prometheus opcional. |

### 3.2 `_build_official_context` — la función central

`app/main.py` (~línea 3040). Para un `(municipio, lon, lat)`:

1. Resuelve el INE del municipio (`_MUNICIPIO_INE`, 313 municipios).
2. En paralelo (`ThreadPoolExecutor`): Catastro por coordenadas + SIOSE por bbox.
3. Si hay refcat: `Consulta_DNPRC` (detalles por unidad: uso, sup., planta, puerta)
   + INSPIRE WFS `GetParcel` (geometría real + superficie oficial de parcela).
4. SIOTUGA: descubre capa `*_AD_3CLAS_*` del plan vigente vía WMS GetCapabilities,
   luego WFS GetFeature con punto transformado a **EPSG:25829** (UTM 29N),
   parsea GML2 (`coordinates`) y GML3 (`posList`), point-in-polygon real, y entre
   solapes prefiere la zona más específica (score: `edif_ficha`+3, `denom`+2, `uso`+1).
5. Inventario local CSV (referencia).
6. Construye `official_links` (Catastro, SIOTUGA WMS/WFS/inventario, SIOSE).
7. Calcula `data_quality` (alta/media/baja) **siempre**, aunque falten fuentes.
8. Caché `_OFFICIAL_CACHE` con TTL 5 min.

### 3.3 Módulos de análisis (src/)

| Módulo | Líneas | Función |
|---|---|---|
| `report_service.py` | 1160 | Informe de viabilidad HTML: resumen ejecutivo, datos edificio/OSM, diagnóstico, habitabilidad, sombras, solar, economía, costes, ficha técnica, datos oficiales, procedencia, fuentes. |
| `zoning_assess.py` | 266 | Resuelve parámetros efectivos (plan → subzona → defaults), orquesta assess. |
| `zoning_service.py` | 439 | Consultas ArcGIS/WMS auxiliares, config por municipio, centroides. |
| `volume.py` / `volume_service.py` | 391+63 | Envolvente edificable (retranqueos, altura, ocupación, edificabilidad). |
| `shadow_service.py` | 219 | Sombras solsticio de invierno multi-hora (modelo solar). |
| `solar_analysis.py` | 181 | Exposición solar anual por orientación (astronomía pura). |
| `habitabilidad_checker.py` | 248 | Reglas NHV trazables: altura libre ≥2,4m, acristalamiento 1/8, ventilación 1/3, superficies de estancias (tablas Anexo I). |
| `licencia_docs.py` | 283 | Plantillas de documentación de licencia con params urbanísticos + justificación Decreto. |
| `cost_estimator.py` | 107 | Cálculo económico con inputs del usuario (no inventa precios). |
| `subzones_service.py` | 944 | Subzonas piloto + `get_osm_buildings_geojson` (Overpass→GeoJSON 3D, caché doble). |
| `plans_service.py` | 100 | Carga `plan_uploaded.csv` y params por municipio/subzona. |
| `rules_engine.py` | 248 | `geometry_checks` (área, retranqueos direccionales, eje de calle). |
| `ordenanzas_service.py` | 148 | Sirve ordenanzas locales estructuradas. |
| `export_service.py` | 490 | Export IFC de la envolvente. |
| `model_gateway.py` | 259 | Gateway IA multi-provider (OpenAI/Ollama/…) — usado por `/qa`. |
| `qa_service.py`, `text_extractor.py`, `normativa_extract.py`, `procesar_normativa.py`, `crear_indice.py` | — | Pipeline RAG sobre PDFs normativos (torch no disponible en Py3.14 → tests excluidos). |
| `funko_api.py`, `funko_scanner.py` | — | Herencia del repo original (funkos); no relacionados con el visor. |
| `geo.py` | 57 | Utilidades geográficas. |

---

## 4. Frontend — web/geolibre/index.html (~2000 líneas)

Flujo: `loadMunicipios()` → `goToMunicipio(m)` → en paralelo:
`loadBuildings` (fetch lanzado **antes** de `waitForMap`), `loadOrdenanzas`,
`loadSiotugaWMS`, subzonas piloto.

Al hacer clic en un edificio → `selectBuilding(feature)`:
- Calcula huella con `turf.area`, muestra panel (tipo OSM, altura+procedencia,
  plantas, subzona piloto marcada como tal, enlace al way en OSM).
- En paralelo: `/zoning/building-diagnostic` + `fetchOfficialContext` →
  `renderOfficialContext` (Catastro, planeamiento SIOTUGA, SIOSE) y dibuja
  el lindero catastral en el mapa (capa `catastro-parcel`, naranja discontinua).

Acciones desde el panel:
- **Verificar habitabilidad** → formulario con auto-relleno (altura OSM, superficie
  Catastro/huella, selector de unidad no residencial catastral) → POST `/habitabilidad/verificar`.
- **Generar documentación de licencia** → recoge `params_urbanisticos`
  (subzona + edificio + Catastro + SIOTUGA) → POST `/licencia/documentacion`.
- **Analizar soleamiento** → GET `/solar/exposicion`.
- **Estimar costes** → formulario (sup. auto) → POST `/costes/estimar`;
  inputs guardados en `dataset.costInput` para incluirlos luego en el informe.
- **Generar informe de viabilidad** → formulario inline con vista previa de datos
  (reemplazó a `prompt()`) → POST `/zoning/assess-report` con geometría, altura,
  huella, municipio, habitabilidad preliminar, `edificio_osm`, `costes`,
  `official_context` completo. Abre el HTML en pestaña nueva (blob).
- **Guardar como proyecto** → localStorage con estado/plazo/navegación.

Capas extra: sombras con slider horario, afecciones SIOSE, WMS SIOTUGA
(tiles proxied), filtros de edificios por cumplimiento.

Seguridad: `escapeHtml()` en todo dato externo; `safeExternalUrl()` valida http(s).

---

## 5. Fuentes externas — detalle de integración

| Fuente | Uso | Notas |
|---|---|---|
| Overpass API | `way['building'](bbox); out geom` | 2 mirrors en paralelo, primer éxito gana; bbox = centro±delta×0.15 (reintento ×0.22); timeout 25s query / 30s urlopen; caché memoria+disco 7d. |
| Catastro OVC | `OVCBusqueda` por coords → refcat+dirección; `Consulta_DNPRC` → unidades (uso/sup/planta/puerta/año) | Endpoint DNPRC corregido: `OVCWcfCallejero/COVCCallejero.svc/rest/Consulta_DNPRC`. Parser sin namespaces. |
| Catastro INSPIRE WFS | `GetParcel` por refcat → polígono parcela + `areaValue` oficial + `label` | Geometría usada en mapa, mini-mapa del informe y cuadro de superficies. |
| SIOTUGA WMS | GetCapabilities → capa `*_AD_3CLAS_*` vigente; proxy de tiles | CRS EPSG:25829; capa cacheada 1h. GetFeatureInfo devuelve vacío (limitación del servicio). |
| SIOTUGA WFS | `GetFeature` en bbox UTM, `maxfeatures=10` | Extrae `cat_ley/cla_ley/cat_plan/...`, `uso`, `denom`, `sup_ficha`, `edif_ficha`, `id_recinto`. Solapes → más específico. |
| SIOSE IDEE WFS | `lcv:LandCoverUnit` por bbox | GML 3.2 → GeoJSON; coberturas + alertas preliminares. Caché 15min. |

---

## 6. Datos locales y proveniencia

- `subzonas_piloto.geojson`: geometrías rectangulares **inventadas** + parámetros
  orientativos (`altura_maxima_m`, `ocupacion_max`, `edificabilidad_max_m2_m2`,
  `retranqueo_min_m`, `normative_status: pilot`). Alimentan diagnóstico y
  cumplimiento de altura en el visor — siempre etiquetados "piloto/orientativo".
- `plan_uploaded.csv`: CSV del usuario (gitignored). Si tiene valores, pueden
  entrar como parámetros del "plan" — marcados como orientativos en el informe.
- `inventario_planeamento.csv`: inventario municipal (referencia, gitignored).
- `datos/ordenanzas/`: esquema JSON + ordenanzas por municipio (a rellenar por AC8).
- `datos/cache/osm_buildings/`: caché en disco del proxy Overpass.

Regla implementada: `data_quality` siempre presente; veredictos con parámetros
piloto se marcan "(orientativo)"; secciones sin datos muestran "Pendiente" con
instrucciones en vez de desaparecer.

---

## 7. Tests y verificación

- 269 tests (`pytest`), ~13s. Excluidos: `test_asistente_normativa_rules.py` y
  `test_evaluar_dataset_helpers.py` (requieren `sentence_transformers`/torch —
  no disponible en Python 3.14).
- Tests mockean servicios externos con `monkeypatch` (nunca red real).
- JS verificado extrayendo `<script>` y `node --check` por bloque.
- `conftest.py` usa `TestClient` de Starlette.

---

## 8. Limitaciones conocidas → candidatos a mejora

| Área | Estado | Posible mejora |
|---|---|---|
| Parámetros normativos reales | Solo `edif_ficha`/`sup_ficha`/`uso` de SIOTUGA donde existen (SUB/SUNC); SUC suele ir vacío | Parsear PDFs del planeamiento (RAG pendiente) o WFS con más capas (5.ORDEN…); descargar/cachear polígonos por municipio |
| Geometrías de subzona | Rectángulos inventados | Sustituir por geometrías WFS reales de SIOTUGA por municipio |
| `app/main.py` | ~3800 líneas monolíticas | Extraer routers: `official`, `zoning`, `proxy`, `admin` |
| Frontend | ~2000 líneas en un solo HTML | Modularizar (módulos ES) o al menos separar JS/CSS |
| Caché edificios | Por municipio completo (hasta 500) | Por bbox del viewport / tiles; precarga selectiva |
| Overpass | 2 mirrors paralelos | Añadir fallback `overpass.nchc.org.tw`; backoff en 429 |
| Habitabilidad | Pre-check NHV | Selector de unidad ya hecho; falta enlazar resultado al doc. de licencia automáticamente |
| RAG normativo | Pipeline existe pero sin torch en Py3.14 | Torch cuando soporte 3.14, o embeddings vía API/local llama.cpp |
| Persistencia | localStorage solo | SQLite local si se quieren proyectos servidor-side |
| Valor de mercado | Lo aporta el usuario | Idealista/fotocasa scraping no es fiable/legal; dejar como input |
| Errores de red | Overpass 429 frecuente | Ya mitigado con caché; añadir reintento con backoff |

---

## 9. Comandos

```bash
# Servidor
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002

# Tests
venv\Scripts\python.exe -m pytest -q --ignore=tests/test_asistente_normativa_rules.py --ignore=tests/test_evaluar_dataset_helpers.py

# Endpoints de diagnóstico
curl http://127.0.0.1:8002/health
curl "http://127.0.0.1:8002/official/context?municipio=Vigo&lon=-8.71&lat=42.19"

# Regenerar diagrama archify
node ~/.agents/skills/archify/bin/archify.mjs validate architecture docs/diagrama.arquitectura.json --quality showcase --json --repo-root .
node ~/.agents/skills/archify/bin/archify.mjs deliver architecture docs/diagrama.arquitectura.json docs/diagrama-arquitectura.html --quality showcase --json --repo-root .
```
