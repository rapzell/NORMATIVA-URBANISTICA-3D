# Guía para continuar el desarrollo

## Setup en una máquina nueva

```bash
git clone https://github.com/rapzell/NORMATIVA-URBANISTICA-3D.git
cd NORMATIVA-URBANISTICA-3D
git checkout feat/demo-silencioso

# Entorno principal
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt

# Entorno RAG/embeddings (Python 3.13)
py -3.13 -m venv venv_rag          # o: python3.13 -m venv venv_rag
venv_rag\Scripts\python.exe -m pip install -r requirements_rag.txt
```

Los PDFs oficiales (corpus RAG + normativa Vigo PXOM 2025 + fichas de
ámbitos) y los embeddings precalculados **van en el repo** — no hay que
descargar nada. Lo que se regenera solo: `datos/cache/` (capas SIOTUGA
y WFS municipal al primer uso) y `_index.json` (BM25, automático).
Las API keys (`api.txt`, `docs/apikey*`) NO están en el repo —
copiarlas a mano o crear el fichero en la máquina nueva.

## Comandos esenciales

```bash
# Arrancar servidor (puerto 8002)
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002

# Tests completos (~404 tests, ~30s)
venv\Scripts\python.exe -m pytest -q --ignore=tests/test_asistente_normativa_rules.py --ignore=tests/test_evaluar_dataset_helpers.py

# Microservicio de embeddings/reranker RAG (puerto 8003, entorno Python 3.13)
venv_rag\Scripts\python.exe -m uvicorn src.rag.embedding_service:app --host 127.0.0.1 --port 8003
# o: scripts\launch_embedding_service.cmd

# Regenerar embeddings del corpus (tras cambiar datos/corpus/, requiere :8003 activo)
venv\Scripts\python.exe scripts\precompute_embeddings.py

# Regenerar el índice de ámbitos de Vigo (API + fichas SUB/SUNC/PE)
# Requiere los PDFs NU en datos/normativa/36057/ (28719nu003/004)
venv\Scripts\python.exe scripts\extract_vigo_ambitos.py

# Tests focalizados
venv\Scripts\python.exe -m pytest tests/test_geolibre_view.py -q
venv\Scripts\python.exe -m pytest tests/test_habitabilidad_checker.py -q
venv\Scripts\python.exe -m pytest tests/test_assess_report_branding.py -q
venv\Scripts\python.exe -m pytest tests/test_health_and_proxies.py -q

# Verificar un endpoint concreto
curl -s http://127.0.0.1:8002/official/siotuga-wms?municipio=Vigo
curl -s -o tile.png http://127.0.0.1:8002/official/siotuga-wms/tile/14/7795/6067?ine=36057&layer=_36057_PXOM_202505_AD_3CLAS_28719
```

## Dónde está cada cosa

| Quiero cambiar... | Archivo |
|---|---|
| Endpoints del backend | `app/main.py` |
| Visor GIS (mapa, panel, botones) | `web/geolibre/index.html` |
| Generación de informes | `src/report_service.py` |
| Cálculo de viabilidad | `src/zoning_service.py`, `src/zoning_assess.py` |
| Volumen edificable | `src/volume_service.py` |
| Análisis de sombras | `src/shadow_service.py` |
| Subzonas espaciales | `src/subzones_service.py` |
| Datos piloto de subzonas | `datos/subzonas_piloto.geojson` |
| Inventario de planeamiento | `datos/inventario_planeamento.csv` |
| Mapeo municipio→INE | `app/main.py` → `_MUNICIPIO_INE` |
| Exportación 3D | `src/export_service.py` |
| Preverificación de habitabilidad (NHV/Decreto 128/2023) | `src/habitabilidad_checker.py` |
| Plantillas de documentación de licencia | `src/licencia_docs.py` |
| Análisis de soleamiento por orientación | `src/solar_analysis.py` |
| Estimación de costes de conversión | `src/cost_estimator.py` |
| Ordenanzas municipales (cambio de uso) | `src/ordenanzas_service.py`, `datos/ordenanzas/` |
| Panel multi-proyecto | `web/geolibre/index.html` (localStorage) |
| Gateway IA | `src/model_gateway.py` |
| Asistente agéntico normativa (orquestador/herramientas/validador) | `src/agent/` |
| Corpus normativo autonómico (Ley 2/2016, NHV, NTPU, PBA — índice por artículo) | `src/rag/corpus.py`, `datos/corpus/` |
| Búsqueda normativa unificada (corpus + PDFs municipales, rerank opcional) | `src/rag/search.py` |
| Sinónimos urbanísticos ES/GL + boost por tipo de pregunta | `src/rag/synonyms.py` |
| RAG híbrido (embeddings + RRF k=60 + rerank remoto, degradable) | `src/rag/hybrid_search.py` |
| Microservicio embeddings/reranker :8003 (Python 3.13, ALIA legal ES) | `src/rag/embedding_service.py`, `scripts/launch_embedding_service.cmd` |
| Clasificador de intención (LLM few-shot + fallback regex) | `src/agent/intent_classifier.py` |
| Memoria conversacional multi-turno (chat_id, TTL 30 min, RAM) | `src/agent/memory.py` |
| Detector de contradicciones (altura medida vs ordenanza, etc.) | `src/agent/contradictions.py` |
| Resolución parcela → ordenanza (oficial/inferida/ambigua) | `src/agent/ordinance_resolver.py` |
| Ámbitos de planeamento singular (API/SUB/SUNC/PE): índice, detección por atributos y punto-en-polígono | `src/ambitos_service.py`, `datos/normativa/{ine}/ambitos.json`, `scripts/extract_vigo_ambitos.py` |
| Etiquetado de calidad de datos | `src/data_quality.py` |
| Caché unificada en disco + HTTP con reintentos | `src/cache.py` |
| Clasificación vectorial SIOTUGA (descarga + punto-en-polígono) | `src/siotuga/vector_downloader.py` |
| Documentos oficiales SIOTUGA (PDFs normativa, sesión+token) | `src/siotuga/document_client.py` |
| Ordenanza SUC por punto vía capa municipal oficial (Vigo GeoServer, caché local + STRtree) | `src/muni_wfs.py` |
| Ámbitos oficiales PXOM 2025 (PEP/PERI/PP/API) vía FeatureServer ArcGIS público del Concello — cubren los huecos de `4ordsuc` donde la zona rige por instrumento propio | `src/ambitos_service.py` → `ambito_oficial_en_punto` |
| PXOM 2025 aprobación definitiva (NU + fichas de ámbitos; descarga selectiva del ZIP de 12,8 GB por HTTP Range) | `datos/normativa/36057/pxom2025/`, `scripts/download_pxom2025_nu.py` |
| Ancho de rúa estimado desde OSM (fachadas opuestas ⊥ al vial más próximo; resuelve la tabla de altura U2 → `ancho_rua_estimado_m`/`altura_aplicable_m`, siempre `estimated`) | `src/subzones_service.py` → `_estimate_street_widths` |
| RAG normativo sobre PDFs oficiales (índice BM25 + citas) | `src/normativa_rag.py` |
| Cliente Catastro (OVC/INSPIRE/BU/ATOM) | `src/catastro/client.py` |
| Alturas LiDAR + huellas Overture | `src/building_data/height_extractor.py` |
| Alturas vía WCS MDS del IDEE (nDSM 2.5m, sin captcha) | `src/building_data/mds_wcs.py` |
| Preparación/procesado teselas LAZ CENDES | `src/building_data/lidar_prep.py` |

## Patrones del código

### Contexto oficial (`_build_official_context` en `app/main.py`)

Es la función central que reúne todos los datos oficiales de una parcela:
1. Consulta Catastro por coordenadas (en paralelo con SIOSE)
2. Consulta SIOSE por bbox
3. Consulta inventario de planeamiento (CSV local)
4. Construye `official_links` con URLs directas a la parcela
5. Calcula `data_quality` (alta/media/baja)
6. Valida consistencia de coordenadas y municipio

Usa `ThreadPoolExecutor` para paralelizar Catastro + SIOSE.
Caché en `_OFFICIAL_CACHE` (TTL 5 min).

### WMS SIOTUGA (`_fetch_siotuga_wms_layer` en `app/main.py`)

1. Obtiene GetCapabilities del WMS del municipio
2. Busca la capa `_AD_3CLAS_` del plan vigente (no histórico, no MP)
3. Cachea el resultado (TTL 1h)
4. El visor usa el proxy XYZ→WMS (`/official/siotuga-wms/tile/{z}/{x}/{y}`)

### WFS SIOTUGA clasificación (`_fetch_siotuga_classification` en `app/main.py`)

1. Obtiene la capa 3CLAS del plan vigente vía `_fetch_siotuga_wms_layer`
2. Convierte lon/lat a UTM 29N (EPSG:25829) — la capa usa ese CRS, no 4326
3. WFS 1.1.0 con `TYPENAME` (MapServer requiere este parámetro, no `typeNames`)
4. `maxfeatures=10` — el punto puede estar en varias zonas superpuestas
5. Point-in-polygon sobre GML (ray casting sobre `coordinates`/`posList`)
6. Prefiere la feature con más datos específicos (`edif_ficha` > `denom` > `uso`)

Devuelve: `clasificacion_ley`, `clasificacion_homo`, `clasificacion_plan`,
`clase_ley`, `clase_homo`, `uso_zona`, `denominacion_zona`,
`edificabilidad_ficha`, `sup_ficha_m2`, `area_zona_m2`, `id_recinto`,
`observaciones_zona`, `estado_zona`, `categoria_wiug` + etiquetas legibles.

**Limitación**: solo las zonas SUB/SUNC tienen `edif_ficha` y `sup_ficha`
rellenos. Las zonas SUC no los tienen — esos parámetros están en los PDFs
del planeamiento municipal, no en el WFS.

### Enlaces oficiales (`official_links` en el contexto)

Se construyen en `_build_official_context` y se renderizan en:
- `web/geolibre/index.html` → `renderOfficialContext()`
- `src/report_service.py` → sección "Fuentes oficiales consultadas"

Formato de cada link: `{name, url, label}`

### Subzonas piloto y jerarquía oficial

`find_subzone_for_point(lon, lat, municipio)` resuelve la ordenanza del
punto con esta jerarquía (datos reales primero, nunca se rellena con
piloto un hueco de la capa oficial):

1. **Capa oficial municipal** (`src.muni_wfs`): GeoServer del concello
   copiado en `datos/cache/muni_wfs/{ine}.json` (TTL 30 días) +
   `STRtree` en memoria (~1 ms/punto; sin él sería inusable para 500
   edificios). Devuelve `normative_status='official'` + `subzona`
   (código de zona, p.ej. `U6.6`) + `ordenanza` (normalizada al PDF,
   p.ej. `U6`) + parámetros extraídos del PDF del plan.
2. **Hueco de cobertura**: si el municipio tiene capa pero el punto cae
   fuera de todo polígono → `normative_status='unavailable'` + `nota`.
   El polígono más cercano NO se usa: puede ser un ámbito de
   planeamiento singular (p.ej. `observ: API-106` en RU COUTO 2).
3. **Piloto**: solo si el municipio no tiene capa configurada →
   `normative_status='pilot'` y el código viaja como `subzona_piloto`,
   nunca como `subzona`.

Contrato en las props de edificio (`/proxy/osm-buildings`):
`subzona` = solo códigos oficiales · `subzona_piloto` = piloto
orientativo · `normative_status` = official|pilot|unavailable|ambiguous.
La caché de Overpass en disco lleva `_PROPS_SCHEMA` en el nombre del
fichero para invalidarse cuando cambia este contrato.

Alturas: `_attach_mdsn_heights` descarga un único GeoTIFF `mdsn_e025`
(nDSM edificación 2,5 m, WCS IDEE) cubriendo el bbox de todos los
features y toma el P90 por huella — la altura pasa de estimada OSM a
medida real (`height_source='mdsn_lidar'`, `altura_medida_m`,
`altura_osm_m` conserva la estimación). Estados de cumplimiento:
`compatible|supera_altura|orientativo_*|altura_tabla|sin_limite`
(ordenanza oficial que no fija altura, p.ej. U1.x conservación) |
`sin_dato` (hueco real de capa). `ancho_rua_estimado_m` se estima por
sección perpendicular al vial OSM entre fachadas opuestas y resuelve
la fila aplicable de las tablas de altura por ancho (U2).

Los polígonos piloto (`datos/subzonas_piloto.geojson`) tienen parámetros
orientativos y geometrías inventadas: se sirven con `subzona_piloto` +
`normative_status='pilot'` (`_pilot_public_feature`) y **no se muestran
en el mapa** (se comentó `renderSubzones3D`). `/planeamiento/subzonas`
adjunta `ordenanzas_reales` (extraídas del PDF oficial) y
`capa_ordenanzas_oficial`.

### Ámbitos de planeamento singular (`src/ambitos_service.py`)

Los ámbitos API (planeamento incorporado) y SUB/SUNC/PE (ordenación
detallada) se rigen por su propio instrumento — el Plan Xeral se remite
a él — por encima de las ordenanzas xerais del SUC.

- **Índice**: `datos/normativa/{ine}/ambitos.json`, generado por
  `scripts/extract_vigo_ambitos.py` desde los PDFs oficiales (Vigo:
  tabla API→instrumento de la DF Quinta de `28719nu003.pdf`, pág. 347,
  + 158 fichas de `28719nu004.pdf` con parámetros estructurados).
  No se versiona (`datos/` está en `.gitignore`): se regenera con el
  script tras descargar la normativa.
- **Detección**: `detectar_ambito_en_clasificacion` lee los atributos
  oficiales del polígono (`obsv` lleva «API-106»; `denom` lleva el
  número de ámbito en SUB/SUNC, p.ej. «201 Guixar-Santa Tegra» →
  SUNC-201). `ambito_en_punto` hace lo propio espacialmente con un
  STRtree sobre la copia local 3CLAS (solo polígonos con código).
- **Lookup**: `get_ambito(ine, codigo)` normaliza variantes
  («api 106», «sunc201», «API-201_P-8») y devuelve la entrada oficial
  con `data_quality='official'`, página y fuente; lo no indexado queda
  `unavailable`.
- **Integración**: `ordinance_resolver` lo resuelve antes que la
  ordenanza xeral (incl. si el usuario seleccionó otra — se informa);
  `_build_official_context` lo expone como `ctx.ambito`; los edificios
  llevan `props.ambito`/`props.ambito_nombre`; `GET
  /ambitos/{municipio}[/{codigo}]` expone el índice; la herramienta del
  agente es `get_ambito_ficha`.
- **API sin ficha de parámetros** (p.ej. API-106): se informa del
  instrumento (ED UE I-06 Rosalía Castro 2, AD 1995) y se declara que
  los parámetros requieren el documento del instrumento — nunca se
  inventan.

### Tests

- Los tests usan `monkeypatch` para mockear servicios externos
- `_build_official_context` se mockea con `monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {...})`
- `find_subzone_by_name` se mockea en `src.subzones_service` (no en `app.main`)

### Asistente agéntico de normativa (`src/agent/`)

Chatbot experto que responde preguntas sobre el edificio/parcela
seleccionado en el visor con respuestas citadas a fuentes oficiales.

- **Endpoints:** `POST /qa/edificio` (JSON completo),
  `POST /qa/edificio/stream` (SSE: eventos `contexto` → `fuentes` →
  `token` → `final`), `GET /qa/health` (estado LLM/índices/reranker).
- **UI:** panel de chat en `web/geolibre/index.html` (botón "Asistente
  normativa"); usa el último edificio seleccionado como contexto.
- **Flujo** (`orchestrator.preparar_consulta` → `finalizar_respuesta`):
  0. Memoria de sesión (`memory.get_session(chat_id)`): referencias
     ("ahí", "y si…") resuelven el último edificio; historial de 3
     turnos se inyecta en el prompt. RAM con TTL 30 min.
  1. Intención (`intent_classifier.clasificar_intencion`): regex primero
     (saludo/edificio/calculo fiables); el LLM few-shot solo refina el
     bucket ambiguo "normativa" con timeout de 5 s — nunca bloquea.
  2. Herramientas en paralelo (`src/agent/tools.py`): Catastro,
     clasificación SIOTUGA, altura medida, parámetros de ordenanza del
     PGOM, inventario municipal, ordenanza por punto vía WFS municipal
     (`muni_wfs` — Vigo: GeoServer `mapas-ogc.vigo.org`, capa
     `4ordsuc`; `srsName=EPSG:4326` imprescindible o la geometría
     vuelve en UTM 29N).
  3. Resolución parcela→ordenanza (`ordinance_resolver`): **ámbito de
     planeamento singular primero** (`ambitos_service` — `obsv`
     «API-106» o `denom` numerado en SUB/SUNC → ficha oficial del
     `ambitos.json`); el instrumento incorporado (ED/PERI/PP) rige el
     ámbito y prevalece sobre la ordenanza xeral del SUC y sobre una
     selección manual. Después: WFS municipal oficial → código en
     atributos de zona → `oficial`; título coincidente → `inferida`;
     varios → `ambigua`; nada → `no_resuelta` + lista de ordenanzas.
     Nunca se inventa ni se elige entre candidatas. Códigos de subzona
     (`U6.5`) resuelven por prefijo a la ordenanza del PDF (`U6`).
  4. Contradicciones (`contradictions.detectar_contradicciones`):
     altura medida vs altura máx. de la ordenanza, parcela vs parcela
     mínima, edificabilidad real vs máxima → avisos `⚠` visibles.
  5. RAG (`src/rag/search.buscar_normativa`): sinónimos ES/GL → BM25
     (corpus + PDFs municipales) + embeddings del microservicio :8003
     fusionados con RRF k=60 + reranker legal ALIA remoto; sin servicio
     queda BM25+sinónimos — nunca falla.
     Si la pregunta cita una ordenanza concreta («U6»), sus parámetros
     extraídos del PDF oficial entran como `[FUENTE 1]` con
     `url#page=N` — determinista, sin depender del ranking.
  6. Cálculo: `check_piscina_viability` (ocupación) o
     `check_cambio_uso` (NHV Decreto 128/2023 vía
     `habitabilidad_checker` — sin medidas devuelve `no_verificable`,
     nunca inventa).
  7. Prompt anclado (system prompt con reglas estrictas de citación
     `[FUENTE n]`, historial y advertencias) →
     `model_gateway.generate_with_fallback`.
  8. Validación (`src/agent/validator.py`): heurística de citas/números
     + `validacion_semantica` opcional con LLM (`SEMANTIC_VALIDATION=1`,
     solo si la heurística pasa; JSON inválido → queda la heurística).
  9. Sin LLM → modo heurístico: devuelve los artículos recuperados con
     el cálculo — nunca calla ni inventa.
- **Corpus** (`src/rag/corpus.py`): documentos en `datos/corpus/`
  declarados en `_manifest.json` (LSG consolidada enero 2026, NHV
  comentada v1.2 IGVS, NTPU abril 2022, PBA Decreto 83/2018 marcado
  «supletorio» — solo aplica donde el planeamiento municipal no fija
  el parámetro — descargados de xunta.gal).
  Chunking por artículo/disposición/anexo con `article_ref`; índice
  cacheado `_corpus_index.json` invalidado por manifiesto+tamaños.
- **Gateway** (`src/model_gateway.py`): cada proveedor acepta su clave
  propia (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
  `MISTRAL_API_KEY`, `CEREBRAS_API_KEY`) o la compartida
  `MODEL_API_KEY`; modelos gratuitos por defecto por proveedor;
  `MODEL_FALLBACK_CHAIN` ordena el failover; `stream_with_fallback`
  da streaming OpenAI-compatible para el SSE.
- **Tests:** `tests/test_agent_orchestrator.py` (orquestador, validador,
  endpoints, SSE) + `tests/test_agent_mejoras.py` (intención, memoria,
  sinónimos, RRF, contradicciones, cambio de uso, resolutor de
  ordenanza, validación semántica). Herméticos: sin red ni :8003.

### Preverificación de habitabilidad (`src/habitabilidad_checker.py`)

Motor de reglas trazable de las NHV (Decreto 29/2010, redacción dada por el Decreto 128/2023).

- **Endpoint:** `POST /habitabilidad/verificar` (en `app/main.py`)
- **Tests:** `tests/test_habitabilidad_checker.py`
- **UI:** panel en `web/geolibre/index.html` (`showHabitabilityForm`, `submitHabitabilityCheck`)
- **Informe:** sección 3.2 en `src/report_service.py` (recibe `body['habitabilidad']`)

Estados por comprobación: `cumple`, `no_cumple`, `no_verificable` (los datos faltantes nunca fallan).

Fuentes oficiales (siempre se devuelven en `fuentes`):
- DOG 176, 15/09/2023 (Decreto 128/2023)
- Corrección de errores, DOG 77, 18/04/2024
- Texto consolidado comentado NHV v1.2 (IGVS)

Valores verificados (no hardcodear sin fuente):
- Altura libre mínima cambio de uso: **2,4 m** (Anexo I, A.3.1.1.d)
- Acristalamiento mínimo: **1/8** de la superficie útil de la pieza (Anexo I, A.1.2.a)
- Ventilación real mínima: **1/3** del acristalamiento mínimo (Anexo I, A.1.2.i)
- Superficies de estancias: tablas 1 y 2 del Anexo I, A.3.2.1/A.3.2.2 (varían con el nº de estancias)

**No cubre** (módulos normativos separados, no mezclar con NHV):
- Accesibilidad, evacuación, seguridad contra incendios, CTE
- Planeamiento municipal (ordenanzas de cada municipio)
- Certificación legal o sustitución del proyecto técnico

`programa_declarado_completo=True` convierte las piezas ausentes en `no_cumple`; `False` las deja en `no_verificable`.

## Lo que NO hay que hacer

- No subir API keys al repo (están en `.gitignore`: `docs/apikey*`)
- No inventar datos cuando los servicios externos no responden
- No usar dependencias de pago
- No modificar políticas de seguridad/compliance del repo
- No añadir comentarios innecesarios al código (el proyecto los minimiza)

## Próximos pasos recomendados

1. **Polígonos reales de subzonas** — HECHO (doble vía):
   - `_fetch_siotuga_classification` → `src/siotuga/vector_downloader.consultar_clasificacion_punto`: usa la copia vectorial local si está cacheada, si no consulta WFS puntual (bbox UTM 25829).
   - `descargar_clasificacion_municipio(ine, layer)` baja la capa `*_AD_3CLAS_*` completa paginando (`maxfeatures=2000`+`startindex`), parsea GML→GeoJSON (invierte lat,lon→lon,lat cuando srsName es 4326) y cachea en `datos/cache/siotuga/` 30 días.
   - `GET /official/siotuga-clasificacion?municipio=X[&bbox=]` sirve la capa al visor (botón "Clasificación", colores por `clase_ley`, click → clase/categoría/uso/edificabilidad). Sin datos → `data_quality: unavailable`, nunca rellena con piloto.
   - `consultar_clasificacion_punto` sin `layer_name` resuelve desde cualquier capa cacheada del municipio (`capa_cacheada`), sin red — funciona con SIOTUGA caído y sin GetCapabilities.
   - **Planes sin vectorizar (Ourense, Ferrol, antiguos)**: `3CLAS`/`1DEL` vacíos en el servidor; la clasificación solo existe como plano escaneado (`*_AD_PORD_02CL_{iddoc}`). `_fetch_siotuga_wms_layer` devuelve `raster_layer` + `alt_layers` (otras 3CLAS no históricas, p.ej. MP). El endpoint prueba las alternativas (features etiquetadas `plan_modificacion`), y cuando no hay vectorial devuelve `raster_layer` en metadata: el visor superpone el plano oficial como capa raster ("Clasificación: raster"). La consulta por punto sigue `unavailable` — correcto.
   - Pendiente: parámetros finos (altura máx, retranqueos) solo existen en SIOTUGA para zonas SUB/SUNC (`edif_ficha`, `sup_ficha`, `uso`); el resto sigue siendo piloto u ordenanzas aportadas por AC8.

2. **Capa de calidad de datos** — HECHO: `src/data_quality.py` (`DataPoint`/`DataQuality`: official|measured|estimated|unavailable). El contexto expone `data_points` por campo; la UI muestra badges y el informe una tabla "Trazabilidad por dato".

3. **Datos reales de edificios** — HECHO parcial: `src/building_data/height_extractor.py` (PNOA LiDAR LAZ en `datos/cache/lidar/` → altura P90 − terreno; MDT 5m vía WCS IDEE como cota de terreno; Overture vía duckdb) + `src/catastro/client.py` (BU WFS: edificios oficiales por parcela con uso/año/plantas). `GET /official/building-data` devuelve todo con DataPoint. Sin LAZ → `unavailable` (sin fallback silencioso a OSM).

4. ~~**Más municipios**~~ — HECHO: `_MUNICIPIO_INE` ahora tiene los 313 municipios de Galicia (fuente: INE) con alias. Se corrigieron errores graves: Pontevedra era 36042 (en realidad Ponteareas, correcto 36038), Santiago era 27059 (en realidad Sober, correcto 15078), Porriño era 36041 (en realidad Poio, correcto 36039), y muchos municipios de A Coruña tenían códigos de Pontevedra.

5. **RAG normativo** — HECHO: `src/normativa_rag.py` indexa los PDFs descargados en `datos/normativa/{ine}/` (chunks por página, BM25, caché `_index.json` invalidado por sha256 del manifiesto) y `POST /normativa/consulta` devuelve respuesta + citas `{fichero, seccion, pagina, extracto}`. Si hay proveedor LLM configurado (`MODEL_PROVIDER`) sintetiza; si no, respuesta extractiva. Documentos SIOTUGA: `src/siotuga/document_client.py` abre sesión (PHPSESSID+token CSRF del HTML de `/siotuga/inventario`), `query_document.php` lista instrumentos (idclase 14=xeral, 13=desenvolvemento, 16=HCO, 18=núcleos), `getIOTPU.php` da `elementos[].componentes[].pathesperado`; URL real: `https://siotuga.xunta.gal/siotuga/{filesroot}{folder}/documents/{pathesperado}`. `GET /official/normativa-docs?municipio=X[&secciones=NU,PORD]` descarga a `datos/normativa/{ine}/` con manifiesto sha256. LiDAR: `hoja_lidar_para_punto(lon,lat)` consulta la malla CENDES (`ideg.xunta.gal/servizos/rest/services/Cendes/Mallas/MapServer`, capa 69=LIDAR_2015_2016 clasificado) y devuelve hoja+fichero+permalink `descargas.xunta.es/{id}`; la descarga exige captcha → depositar el ZIP manualmente en `datos/cache/lidar/` y `obtener_altura_lidar` lo usa automáticamente. `GET /official/lidar-tile?lon=&lat=` expone esto al visor. **Alturas sin captcha**: `src/building_data/mds_wcs.py` consulta el WCS MDS del IDEE (`wcs-mds.idee.es/mds`, cobertura `mdsn_e025` = nDSM edificación 2,5 m, CRS EPSG:3042, GeoTIFF cacheado 30 días) y devuelve P90 sobre la huella como `measured` — es el fallback automático cuando no hay LAZ local; el flujo CENDES queda solo como mejora de precisión opcional (`GET /official/lidar-preparar`, `POST /official/lidar-procesar`).

6. ~~**Ampliar `MUNICIPIO_CENTERS`**~~ — HECHO: 337 municipios (principales + aliases). Cubre las 4 provincias.

7. **Panel multi-proyecto** — HECHO: `localStorage` para guardar proyectos con estado (viabilidad/licencia/obra), plazo y navegación.

8. **Módulos completados en esta fase**:
   - `src/habitabilidad_checker.py` — NHV/Decreto 128/2023 (reglas verificadas contra DOG)
   - `src/licencia_docs.py` — plantillas de documentación de licencia
   - `src/solar_analysis.py` — soleamiento por orientación (preliminar)
   - `src/cost_estimator.py` — estimación de costes (inputs del usuario, no inventa precios)
   - `src/ordenanzas_service.py` — estructura para ordenanzas municipales (pendiente datos de AC8)
   - `src/report_service.py` — integra habitabilidad, soleamiento y costes
   - Performance: Overpass timeout 8s→25s, eliminado Shapely por edificio, límite 3000→500
   - **Caché de edificios OSM**: doble nivel — memoria (`_OVERPASS_CACHE`) + disco (`datos/cache/osm_buildings/{muni}_{limit}.json`, TTL 7 días, gitignored). Un municipio cacheado carga en ~0.04s en vez de 5-50s. Las 7 capitales + Ferrol están precalentadas.
   - **GZipMiddleware** activo (`minimum_size=4096`): GeoJSON 356KB → ~26KB comprimido.
   - El frontend lanza el fetch de edificios en paralelo con la carga del mapa (no espera a `waitForMap`).

9. **Auto-rellenado de formularios e informes**:
   - Botón "Generar informe de viabilidad" con formulario inline y vista previa de datos
   - Auto-rellena: geometría, altura, huella (turf), municipio, habitabilidad preliminar, datos OSM
   - El servidor rellena desde fuentes oficiales: Catastro, SIOTUGA, SIOSE, soleamiento, sombras
   - Resumen ejecutivo con datos del edificio, Catastro e indicador de disponibilidad por sección
   - Diagnóstico del edificio funciona sin subzona (muestra datos disponibles)
   - Sección de costes muestra "Pendiente" cuando no hay datos (no se omite)
   - Habitabilidad: pre-rellena altura (OSM) y superficie (Catastro o huella)
   - Costes: pre-rellena superficie (huella del edificio) y guarda inputs para el informe
   - Licencia: pre-rellena huella (turf) para el cuadro de superficies
   - **Popup del informe**: `submitGenerateReport` abre la pestaña de forma síncrona (gesto de usuario) con placeholder y escribe el HTML al llegar — abrirla tras el `await` la bloquea el navegador. Fallback: enlace de descarga del HTML.

## Notas sobre datos y reproducibilidad

- `datos/` está gitignored salvo archivos de test. Los archivos trackeados son: `planes_municipales_sample.csv`, `planes_vigo_boiro.csv`, `subzonas_piloto.geojson`, `planes_ejemplo_residencial.csv`, `sample_parcela.geojson`, `sample_street_axis.geojson`.
- `plan_uploaded.csv` es el CSV local de trabajo del usuario (se edita vía admin/reload-plan), permanece ignorado y no debe publicarse ni sobrescribirse.
- `planes_municipales_sample.csv` es el fixture de tests (Vigo RZ-2 con setbacks 2/1/0.5 north → área 60).
- `subzonas_piloto.geojson` tiene geometrías inventadas (no reales) con parámetros orientativos.
- En Python 3.14, `torch==2.8.0` no está disponible. Los tests `test_asistente_normativa_rules.py` y `test_evaluar_dataset_helpers.py` requieren `sentence_transformers` (depende de torch) y se excluyen con `--ignore`.
- `prometheus-client` >= 0.26 usa `version=1.0.0` en el content-type (antes `0.0.4`). El test `test_metrics_enabled_content_type` acepta cualquier versión.

## Estado del bloque GeoLibre (auditoría 2026-09-15)

- Catastro y SIOSE usan el almacén de certificados del sistema mediante `truststore`; no desactivar la verificación SSL.
- El parser de Catastro elimina namespaces XML antes de extraer referencia y dirección.
- SIOSE usa el tipo correcto `lcv:LandCoverUnit`, recibe GML 3.2 y lo convierte a GeoJSON.
- La altura 3D coincide con la altura indicada; se eliminó la exageración visual del 35 %.
- Cada edificio expone `height_source` y `height_estimated` para distinguir altura OSM, estimación por plantas, tipo o valor genérico.
- Las comparaciones con `subzonas_piloto.geojson` usan estados `orientativo_dentro`/`orientativo_supera`; nunca deben mostrarse como cumplimiento o incumplimiento oficial.
- El visor escapa datos externos antes de insertarlos en HTML y valida enlaces HTTP(S).
- Verificación del bloque: 214 tests pasan (excluyendo los 2 de `sentence_transformers` incompatibles con Python 3.14), JavaScript válido con `node --check`, y prueba real positiva de Catastro, SIOSE, SIOTUGA y OSM.
