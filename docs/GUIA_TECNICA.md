# Guía técnica — Visor Arquitectos / Normativa Urbanística 3D

**Estado al 18/09/2026** · Rama `feat/demo-silencioso` · Versión API `0.2.1`
Documento para revisión del experto y planificación de la siguiente fase.

---

## 1. Qué es el programa

Plataforma de análisis urbanístico para Galicia orientada a arquitectos (AC8 Arquitectura):
evalúa parcelas y edificios existentes —especialmente locales comerciales/oficinas para
conversión a vivienda— cruzando **fuentes oficiales en tiempo real** y generando un
**informe de viabilidad** auditable.

Principio rector: **ningún dato inventado**. Cada valor lleva etiqueta de calidad
(`official` / `measured` / `estimated` / `unavailable`) con fuente, fecha y, cuando
procede, página del documento oficial del que se extrajo.

## 2. Stack y arquitectura

| Capa | Tecnología | Ubicación |
|---|---|---|
| Frontend | MapLibre GL 3D (GeoLibre), HTML/JS vanilla | `web/geolibre/index.html` |
| Backend | FastAPI + Uvicorn, Python 3.14 | `app/main.py` (~4.100 líneas, ~60 endpoints) |
| Análisis | Shapely, pyproj, rasterio | `src/` (30 módulos) |
| Extracción PDF | pdfplumber + pypdf | `src/normativa_params.py`, `src/normativa_rag.py` |
| Informe | HTML → PDF (impresión navegador) | `src/report_service.py` |
| Persistencia | Ficheros locales (JSON/CSV/GeoTIFF) | `datos/` (gitignored salvo fixtures) |
| Tests | pytest — **336 pasan**, 1 skip | `tests/` (81 ficheros) |

Servidor de desarrollo: `venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002`

Diagrama interactivo de la arquitectura: `docs/diagrama.arquitectura.html`
(spec regenerable en `docs/diagrama.arquitectura.json`).

### Núcleo: `_build_official_context` (app/main.py)

Función central que reúne en **paralelo** (`ThreadPoolExecutor`, timeout 15 s/fuente):

1. **Catastro** — OVC por coordenadas + INSPIRE WFS + BU (edificios por parcela)
2. **SIOSE** — WFS IDEE por bbox (afecciones: masas de agua, matorral, espacios)
3. **Clasificación SIOTUGA** — WFS o copia vectorial local, punto-en-polígono
4. **WMS SIOTUGA** — capa `3CLAS` del plan vigente (descubierta por GetCapabilities)
5. **Edificio** — altura medida + huella

Produce: `catastro`, `clasificacion_siotuga`, `siotuga`, `siose`, `edificio_datos`,
`planeamiento`, `ordenanzas_pgom`, `official_links`, `data_points` (trazabilidad por
campo), `data_quality` (alta/media/baja), `provenance` (timestamp + fuentes).

## 3. Fuentes de datos — estado real de cada integración

| Fuente | Qué aporta | Método | Calidad | Estado |
|---|---|---|---|---|
| **Catastro OVC/INSPIRE** | refcat, dirección, superficie parcela, año, edificios BU | WFS/XML en vivo | `official` | ✅ Verificado |
| **SIOTUGA WFS 3CLAS** | clasificación del suelo (SUC/SUB/SUNC/SR…), recinto, área | WFS 1.1.0 UTM-29N o vectorial local cacheado | `official` | ✅ Verificado |
| **SIOTUGA WMS** | capa de clasificación renderizada al visor (proxy XYZ) | GetCapabilities → GetMap | oficial | ✅ |
| **SIOTUGA documental** | PDFs del planeamiento (normas, fichas) | sesión + token inventario → `datos/normativa/{ine}/` + manifiesto sha256 | oficial | ✅ Vigo descargado (5 PDFs) |
| **SIOTUGA inventario CSV** | instrumento vigente, fecha aprobación, estado (314 concellos) | auto-descarga `fPutCsvInv.php`, caché 7 días | `official` | ✅ Vivo (PXOM Vigo 2025-05-26) |
| **IDEE WCS MDSN** | **altura medida del edificio** (nDSM 2,5 m, P90 sobre huella) | WCS GetCoverage GeoTIFF, máscara polígono | `measured` | ✅ ~±1 m, LiDAR PNOA 1ª cobertura |
| **OSM/Overpass** | geometría edificio, altura/Plantas cuando existen | Overpass API, caché disco 7 días | `estimated` | ✅ |
| **Overture** | huellas alternativas | duckdb | `estimated` | ✅ |
| **LAZ CENDES** | altura de mayor precisión (~±25 cm) | tesela identificada automáticamente; descarga manual (captcha) | `measured` | ⚠️ Opcional, pendiente ficheros |
| **PGOM en PDF** | **parámetros por ordenanza**: ocupación, edificabilidad, recuados, altura, parcela mín. | extractor regex con trazabilidad de página | `official` | ✅ Vigo: U5-U10 + 9 SRP |
| **PBA (Plan Básico Autonómico)** | ordenanzas tipo supletorias | — | — | ❌ No implementado |
| **Precios de construcción** | costes de conversión | input del usuario | user-provided | ⚠️ Sin fuente pública; tablas Xunta pendientes |

## 4. Pipeline de parámetros normativos (P0 implementado)

```
PDFs oficiales (SIOTUGA documental, datos/normativa/{ine}/)
   → src/normativa_params.py
      · _segment_ordenanzas: corta por cabeceras "ART. N. ORDENANZA U.N"
      · _extract_params: regex por parámetro con traza {página, fragmento}
      · exclusiones por contexto (p.ej. "peto perimetral" no es altura del edificio)
      · prioridad "edificabilidade máxima" > "edificabilidade" de parcelación
   → caché _ordenanzas.json (30 días)
   → GET /normativa/parametros-subzona?municipio=X&ordenanza=Y
   → _build_official_context → data_points oficiales
   → Informe: sección "Parámetros por ordenanza (PGOM oficial)"
      · si la subzona del usuario coincide con una ordenanza → diagnóstico usa
        la norma oficial (etiqueta verde) en vez del piloto
```

**Verificado contra el PXOM 2025 de Vigo** — U6 pág. 179: edificabilidad 0,70 m²/m²,
ocupación 40 %, recuados frente 3 / lateral 2 / posterior 3 m, altura 7 m, parcela 250 m².

### Limitación clave — mapeo parcela→ordenanza

La capa detallada `PORD_02CL` de SIOTUGA es **raster** (planos escaneados), no vectorial:
GetFeatureInfo solo devuelve cajas de píxel. La clasificación WFS da `SUC` pero **no el
código de ordenanza** (U6, R-1…). Por tanto:

- Si el arquitecto indica la ordenanza → parámetros oficiales automáticos.
- Si solo hay clasificación → el informe lista las ordenanzas del plan con página
  para que el usuario localice la suya en el plano oficial. **No se inventa el mapeo.**

Posibles vías futuras: OCR sobre el plano raster, capa vectorial municipal (algunos
concellos la publican en ArcGIS/GeoServer), o entrada manual asistida.

## 5. Endpoints principales

| Endpoint | Función |
|---|---|
| `GET /geolibre/` | Visor GIS 3D |
| `GET /official/context` | Contexto oficial completo (paralelo) |
| `GET /official/building-data` | Altura medida + datos edificio (LAZ→MDSN→unavailable) |
| `GET /official/catastro/by-coords` `/by-ref` | Catastro |
| `GET /official/siotuga-clasificacion` | Clasificación vectorial por punto/bbox |
| `GET /official/siotuga-wms` `/proxy` `/tile/{z}/{x}/{y}` | WMS SIOTUGA + proxy |
| `GET /official/normativa-docs` | Lista/descarga PDFs normativos con manifiesto |
| `GET /normativa/parametros-subzona` | Parámetros de ordenanza con trazas |
| `POST /normativa/consulta` | RAG sobre PDFs normativos (BM25, citas por página) |
| `POST /qa/edificio` · `POST /qa/edificio/stream` (SSE) | Asistente agéntico con contexto de edificio |
| `GET /qa/health` | Estado del stack IA (LLM, índices, reranker) |
| `GET /planeamento/inventario` | Inventario municipal SIOTUGA auto-descargado |
| `GET /official/lidar-tile` `/lidar-preparar` · `POST /lidar-procesar` | Teselas LAZ |
| `POST /zoning/assess` · `GET/POST /zoning/assess-report` `…pdf` | Evaluación + informe |
| `POST /zoning/volume` · `/volume-export` | Envolvente edificable 3D |
| `GET /zoning/building-diagnostic` · `/shadow-analysis` | Diagnóstico y sombras |
| `POST /habitabilidad/verificar` | Reglas NHV (Decreto 128/2023) trazables |
| `POST /costes/estimar` | Estimación de costes (inputs usuario) |
| `POST /licencia/documentacion` | Plantillas de documentación de licencia |
| `GET /solar/exposicion` | Soleamiento por orientación |
| `GET /ordenanzas/{municipio}/{subzona}` | Ordenanzas estructuradas (datos AC8) |
| Admin/utilidad | `/admin/*`, `/debug/plan`, `/metrics`, `/health`, `/proxy/*` |

## 6. Informe de viabilidad — qué calcula hoy

| Sección | Contenido | Procedencia |
|---|---|---|
| Resumen ejecutivo | Veredicto orientativo, áreas | Evaluación + Catastro |
| Cuadro de superficies | Parcela geométrica (UTM), Catastro, **huella real**, libre, envolvente | Cálculo métrico + OSM + Catastro |
| Datos del edificio | Tipo, altura, huella OSM | OSM (`estimated`) |
| Altura medida | P90 sobre huella | IDEE WCS MDSN (`measured`) |
| Diagnóstico | altura/plantas/ocupación/edificabilidad/retranqueo vs norma | Medido/calculado vs piloto u ordenanza oficial |
| **Ordenanzas PGOM** | Tabla de ordenanzas con parámetros + página | PDF oficial (nuevo) |
| Habitabilidad | Reglas NHV verificables | Decreto 128/2023 (fuentes citadas) |
| Económica | Edificable, plantas, viviendas potenciales | Envolvente × plantas (hipótesis marcada) |
| Sombras / Soleamiento | Solsticio invierno, horas de sol por orientación | Modelo solar simplificado |
| Costes | "Pendiente" honesto si no hay inputs | Usuario |
| Datos oficiales | Catastro, SIOTUGA, SIOSE, enlaces | APIs oficiales |
| Proveniencia | Timestamp, versión, **trazabilidad por dato** | Sistema `DataPoint` |
| Viabilidad | Motivos + disclaimer "no sustituye verificación oficial" | — |

Cálculos métricos correctos: reproyección automática a EPSG:25829/25830 según
longitud; retranqueo medido como distancia real huella→lindero en UTM.

## 7. Modelo de calidad de datos (`src/data_quality.py`)

`DataPoint {value, unit, data_quality, source, source_ref, notes}`:

- `official` — API/documento oficial (Catastro, SIOTUGA, PDF PGOM, inventario)
- `measured` — medición instrumental (MDSN, LAZ)
- `estimated` — OSM, OCR, inferencias
- `unavailable` — no obtenible: **explícito, nunca rellenado**
- `user-provided` — inputs del arquitecto (costes, programa de estancias)

El informe muestra la tabla "Trazabilidad por dato" y el visor badges por campo.

## 7b. Asistente agéntico de normativa (`src/agent/`)

Chatbot experto que responde preguntas sobre el edificio seleccionado citando
fuentes oficiales — inspirado en la arquitectura de asistentes legales (RAG +
re-ranking + validación de citas + degradación honesta).

```
Visor (edificio seleccionado) → POST /qa/edificio → Orquestador
   ├─ Herramientas en paralelo: Catastro · SIOTUGA 3CLAS · altura medida
   │    · parámetros de ordenanza PGOM · inventario municipal
   ├─ RAG: corpus autonómico (Ley 2/2016, NHV v1.2, NTPU 2022 — chunks por
   │    artículo) + PDFs municipales → BM25 (+ cross-encoder ALIA si hay torch)
   ├─ Cálculo geométrico (piscina/pérgola: ocupación disponible vs máxima)
   ├─ Prompt anclado (reglas estrictas, citas [FUENTE n]) → gateway LLM
   └─ Validador: cada cita debe existir; números deben estar en fuentes
       → si falla, "Requiere revisión humana" explícito
```

- **Corpus** `datos/corpus/` — 3 documentos oficiales descargados de xunta.gal
  (LSG consolidada enero 2026, NHV comentada IGVS v1.2, NTPU abril 2022),
  561 chunks con `article_ref` y página. Manifiesto declara fuente+URL oficial.
- **Gateway multi-proveedor** — clave propia por proveedor
  (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`)
  con modelos gratuitos por defecto y `MODEL_FALLBACK_CHAIN`; sin LLM →
  **modo heurístico**: devuelve los artículos recuperados + el cálculo.
- **SSE** `POST /qa/edificio/stream` — eventos `contexto`/`fuentes`/`token`/`final`.
- **Chat en el visor** — botón "Asistente normativa"; toma el último edificio
  seleccionado (lon/lat, municipio, subzona, refcat) como contexto.
- **Limitación**: en Python 3.14 no hay torch → el reranker semántico ALIA y los
  embeddings están desactivados (BM25 como motor base); pgvector queda como
  opción si se despliega PostgreSQL. El índice por artículo ya da `article_ref`.

## 8. Verificación actual

- **348 tests** pasan (`pytest -q --ignore` los 2 de sentence-transformers, incompatibles
  con Python 3.14/torch)
- JS del visor: `node --check` OK
- Verificado en vivo: contexto Vigo (altura 32,2 m medida, SUC), ordenanzas U6/U9,
  inventario, informe PDF end-to-end, `/qa/edificio` con contexto real
  (refcat 3963033NG2736S, parcela 3584 m², U6 oficial, cálculo piscina viable)
- Reglas NHV verificadas contra DOG (128/2023 + corrección 77/2024)
- Extracción U6 validada contra el texto oficial pág. 179 (incluye test anti-regresión
  de la discrepancia 0,50/0,70)

## 9. Limitaciones honestas conocidas

1. **Parcela→ordenanza sin mapeo automático** (capa raster; ver §4).
2. **Altura MDSN** = LiDAR 1ª cobertura (2008-2015): edificios nuevos no aparecen
   (→ `unavailable`); precisión ±1 m, no topográfica.
3. **Subzonas piloto** (`subzonas_piloto.geojson`): geometrías inventadas, siempre
   marcadas como orientativas; solo se usan cuando no hay norma oficial.
4. **Plan CSV del usuario** (`plan_uploaded.csv`): parámetros parciales para R-1;
   ocupación/edificabilidad de subzona salen `—` si el CSV no los trae.
5. **Costes**: sin fuente pública estructurada; el informe pide inputs.
6. **Ordenanzas sin parámetros numéricos** (U1/U8 conservan existente; U4 en plantas)
   se listan con nota, no con valores fabricados.
7. Municipios sin plan adaptado (Ourense y otros) → `unavailable` honesto.
8. PDF escaneado (sin texto) → requeriría OCR (Tesseract) marcado `estimated`; no implementado.
9. **Reranker/embeddings del asistente desactivados** en este entorno (Python 3.14
   sin torch): el RAG funciona con BM25; con un Python ≤3.13 + torch el
   cross-encoder ALIA legal se activa solo (`RAG_RERANKER=1`).
10. **LLM externo necesario** para respuestas elaboradas: sin clave el asistente
    funciona en modo heurístico (artículos + cálculo), que es correcto pero menos
    narrativo. Configurar `OPENROUTER_API_KEY`/`GROQ_API_KEY`/… es gratis.

## 10. Propuestas para la siguiente fase (a decidir con el experto)

> ~~Asistente IA normativo~~ — **IMPLEMENTADO** (§7b). Pendiente dentro del
> mismo módulo: migración a MCP completo, reranker/embeddings en entorno con
> torch, pgvector si se despliega PostgreSQL, y evaluación con 20-30 preguntas
> reales de arquitectos.

**P0 — Cerrar el mapeo parcela→ordenanza**
- a) Capa vectorial municipal por concello (algunos ArcGIS/GeoServer propios)
- b) OCR/georreferenciación del plano PORD raster (alto esfuerzo)
- c) Selector manual asistido en el visor: el arquitecto pincha su ordenanza del listado
  oficial y queda fijada en el informe (bajo esfuerzo, ya soportado por `?subzona=U6`)

**P1 — Cobertura municipal**: pipeline de descarga masiva de normativa SIOTUGA por los
313 concellos (cliente ya existe) + verificación de extracción por formato de plan
(cada municipio redacta distinto; el extractor es regex — validar con otros planes).

**P1 — PBA supletorio**: ordenanzas tipo del Plan Básico Autonómico como respaldo
cuando el PGOM no fija parámetros (con etiqueta "supletorio").

**P2 — Costes**: tablas de precios unitarios de obra pública de la Xunta (PDF →
pdfplumber) como referencia, marcando que no son precios de mercado privado.

**P2 — OCR** para PDFs escaneados (`pytesseract` + `pdf2image`), calidad `estimated`.

**P2 — LAZ CENDES**: completar flujo captcha→descarga→`lidar-procesar` para ±25 cm.

## 11. Reproducibilidad y seguridad

- `datos/` gitignored (fixtures trackeados: `planes_*_sample.csv`, `subzonas_piloto.geojson`, `sample_*.geojson`)
- `plan_uploaded.csv` local del usuario: no se publica ni sobrescribe
- SSL verificado vía `truststore` (almacén del sistema); nunca desactivado
- HTML: todo dato externo escapado; enlaces validados http(s)
- Cachés: WCS/OSM 7-30 días en `datos/cache/`; ordenanzas 30 días; inventario 7 días
- Tests usan `monkeypatch` para servicios externos; nada de red en CI
