# Funcionamiento del sistema — NORMATIVA GALICIA 3D

> Documento de referencia del estado **real y desplegado** de la plataforma
> (rama `feat/demo-silencioso`, servicio beta en Render). Para la historia del
> diseño y la propuesta original de integración GeoLibre, véase
> `docs/GUIA_TECNICA_FUNCIONAMIENTO.md`. Diagrama visual de la arquitectura:
> `docs/diagrama_funcionamiento.html`.

## 1. Qué es

Plataforma web gratuita/open de **pre-viabilidad urbanística** para Galicia,
pensada para arquitectos en fase de anteproyecto. Responde, para cualquier
edificio o parcela de los municipios cubiertos:

- ¿Qué ordenanza / calificación urbanística aplica?
- ¿Qué parámetros regulan (altura, edificabilidad, ocupación, retranqueos, usos)?
- ¿El edificio existente encaja dentro de esos parámetros?
- ¿Qué fuentes oficiales respaldan cada dato?

Cobertura actual:

| Municipio | Planeamiento usado | Estado |
|---|---|---|
| Vigo | PXOM 2025 (ordenanzas definitivas + ámbitos API/SUB/SUNC/PE) | Completo |
| A Coruña | PGM 2013 (normas zonales NZ_x) | Completo |
| Santiago de Compostela | PGOM (14 ordenanzas) + **PE-1 casco histórico** | Completo |

## 2. Arquitectura en una página

```
Navegador ──► Visor web (web/geolibre/index.html)
              MapLibre GL + extrusión 3D + panel de datos
                    │ HTTPS (cookie beta_auth)
                    ▼
            FastAPI (app/main.py)  ──► Datos locales `datos/`
                    │                  (normativa, cachés, geojson)
                    ├──► Fuentes oficiales en vivo (solo si falta caché):
                    │    Catastro OVC/INSPIRE · ArcGIS municipales ·
                    │    SIOTUGA WMS/WFS · WCS MDS/MDSN · Overpass/Overture
                    ├──► Agente IA (src/agent): orquestador → herramientas
                    │    → contradicciones → prompt → OpenRouter (LLM)
                    └──► RAG normativo (src/rag, src/normativa_rag):
                         BM25 sobre corpus autonómico + PDFs municipales
```

Despliegue: **Render free** (Docker) + dataset público Hugging Face
`DavidVRM/normativa-galicia-data` descargado al arrancar por
`scripts/fetch_beta_data.py`. Acceso protegido por `BETA_PASSWORD`
(middleware en `app/main.py`).

## 3. Flujo de usuario (lo que se ve en la demo)

### 3.1 Mapa 3D

- `GET /proxy/osm-buildings?municipio=…&limit=500` devuelve las huellas de
  edificios con altura extrusible y propiedades normativas precalculadas.
- Origen de alturas (en orden de preferencia, etiquetado en `height_source`):
  LiDAR/MDSN oficial (WCS IDEE, nDSM 2,5 m) → Overture Maps → tag OSM
  `building:levels` → estimación.
- Cada edificio lleva `cumplimiento_altura` ∈ {`compatible`, `supera_altura`,
  `supera_cornisa`, `altura_tabla`, `altura_alzados`, `sin_limite`,
  `sin_dato`, `orientativo_*`} — el visor colorea y filtra por estado.

### 3.2 Contexto oficial de una parcela

`GET /official/context?lon=…&lat=…&municipio=…` reúne en una sola llamada
(paralelizada con `ThreadPoolExecutor`):

1. **Catastro**: referencia, superficie de parcela y construida, uso
   (OVC RCCOOR/DNPRC) + **plantas y sótanos oficiales**
   (`BuildingPart` INSPIRE → `plantas_oficiales`/`sotanos_oficiales`).
2. **Planeamiento**: ordenanza/subzona por punto-en-polígono sobre la capa
   oficial municipal (GeoServer Vigo / IDE Coruña / Xeoportal Santiago).
3. **Ámbitos singulares**: API/SUB/SUNC/PE/PEP/PERI si la parcela cae en uno.
4. **PE-1** (solo casco de Santiago): calificación RI/AU/LH/R/THR/EQ…
5. **Afecciones**: dotaciones PXOM, contorno arqueológico.
6. **`data_quality`** global (alta/media/baja) y `official_links` con URLs
   directas a cada fuente oficial.
7. **`advertencias`**: detector de contradicciones (§6).

### 3.3 Asistente normativo (`/qa/edificio`)

Pipeline del agente (`src/agent/`):

```
pregunta → clasificador de intención (LLM few-shot, fallback regex)
        → orquestador elige herramientas:
          get_catastro_data · get_subzone · get_ambito_punto ·
          get_pe1_punto · get_ambito_punto · search_normativa (RAG) …
        → respuesta determinista (datos tabulados) o prompt al LLM
        → validador de respuesta (¿inventa números? ¿cita fuentes?)
        → memoria conversacional por chat_id (TTL 30 min)
```

Reglas duras:

- El LLM solo recibe contexto con **datos verificados** + fragmentos del
  corpus; las cifras llevan `data_quality`.
- Si una fuente falla, la respuesta lo dice ("dato no disponible"), nunca
  rellena con valores inventados.
- Respuestas deterministas instantáneas para preguntas tabuladas
  ("¿qué ordenanza aplica aquí?"); ~25-45 s cuando interviene el LLM.

### 3.4 Informe de viabilidad

`POST /zoning/assess` (huella + parámetros) → envolvente edificable con
Shapely → `apto/condicionado/no_apto` + razones.
`GET /zoning/assess-report?body_b64=…` → informe HTML/PDF con fuentes
oficiales citadas y proveniencia.

## 4. Semántica de calidad de datos

Todo dato lleva etiqueta explícita — es la garantía de honestidad del sistema:

| Etiqueta | Significado | Ejemplo |
|---|---|---|
| `official` | Servicio oficial consultado y respondido | Calificación PE-1, refcat, ordenanza NZ |
| `measured` | Medición sobre datos oficiales brutos | Altura MDSN LiDAR sobre huella |
| `estimated` | Cálculo transparente marcado como tal | Plantas ≈ altura/3,2 m; ancho de rúa OSM |
| `unavailable` | La fuente no cubre el punto o falló | Parcela fuera de capa; timeout de Catastro |

Los huecos de capas oficiales **nunca** se rellenan con el polígono más
próximo: quedan `unavailable`.

## 5. Caso especial: PE-1 de Santiago (casco histórico)

El Plan Especial no tabula alturas: **la altura máxima la fija el alzado de
ordenación de cada manzana** (arts. 95-98). Auditado el Xeoportal
(131 servicios ArcGIS): no existe capa vectorial de cotas ni plantas —
solo planos raster por manzana.

Lo que el sistema hace entonces:

- `pe1_altura_regimen='alzados_ordenacion'`, estado `altura_alzados`
  (color morado propio, filtro y etiqueta "según alzados de ordenación").
- `pe1_en_punto`: calificación oficial por parcela
  (`ModifPE1_NoEquip/FeatureServer/0`, campo `CALIFICA` + URL del PDF de la
  ordenanza oficial de la manzana).
- `pe1_alzados_en_punto`: enlace al **plano de fachada oficial** de la
  manzana (capa "Localizador fachadas PE1" — geometría deshabilitada en
  REST, resuelta con `identify` tolerancia ~25 m).
- `pe1_ordenanzas.json`: parámetros curados de los PDFs oficiales
  (arts. 150-154, 172: conservación de volumen, sotos, drenaje…).
- Plantas reales vía Catastro `BuildingPart`; altura medida via LiDAR.
- RAG indexa los PDFs PE-1 + el **BOP texto refundido** (arts. 150-155 +
  remisión a 95-98). El Tomo I completo no está publicado en URL directa.
- La "regla B+4 / máx. 5 plantas" **no consta en el texto oficial** y no se
  usa ni siquiera como estimado.

## 6. Detector de contradicciones (`src/agent/contradictions.py`)

Antes de responder, cruza los datos y añade `advertencias`:

- Altura medida LiDAR vs. altura máxima de la ordenanza → posible
  sobreedificación.
- Altura medida vs. plantas oficiales de Catastro → incoherencia (>1,5
  plantas de diferencia).
- En PE-1: recordatorio de contrastar la altura medida con el alzado
  oficial de la manzana (enlazado).
- Ordenanza asignada vs. ámbito singular solapado; parcela < mínima;
  edificabilidad existente > permitida; usos incompatibles.

Las advertencias se muestran en el panel del visor, en el contexto oficial
y en las respuestas del asistente.

## 7. Caché y rendimiento (crítico en Render free, 512 MB)

| Caché | Ubicación | TTL | Comentario |
|---|---|---|---|
| Edificios mapa | `datos/cache/osm_buildings/{muni}_{n}_v{schema}.json` | 7 días disco / RAM | Precargada en el dataset HF; nombre canónico (`santiago_de_compostela`, `a_coruna`, `vigo`) |
| Capas ArcGIS | `datos/cache/arcgis_ambitos/` | — | PE-1, ámbitos PXOM |
| WFS municipal | `datos/cache/muni_wfs/` | 30 días | Ordenanzas por punto |
| Contexto oficial | `_OFFICIAL_CACHE` RAM | 5 min | |
| Índice RAG | `datos/normativa/{ine}/_index.json` | se invalida por `_manifest_key` | Rebuild automático al cambiar PDFs |
| GeoJSON mapas | `datos/mapas/` | — | Precomputados (clasificación + ordenanzas); servidos con `FileResponse` para no agotar RAM |

Tiempos medidos en producción (instancia caliente): mapa 0,6-1,5 s por
ciudad; contexto oficial 3-8 s; respuesta LLM 25-45 s.

**Convención del dataset**: `snapshot_download(local_dir='datos')` → los
ficheros se suben a la **raíz** del dataset sin prefijo `datos/`. Nunca
`upload_folder` de `datos/` entero (~4 GB de cartografía bruta).

## 8. Limitaciones conocidas (declaradas)

- **Render free**: la instancia duerme tras ~15 min sin tráfico
  (despertar 60-90 s); hay workflow keepalive, pero conviene calentar
  antes de una demo.
- **RAG sin reranker en producción**: `RAG_RERANKER=0` obligatorio
  (el cross-encoder importa torch → OOM). Búsqueda = BM25 + sinónimos;
  suficiente para citar artículos, menos preciso en consultas vagas.
- **`/qa` básico** devuelve "sin fragmentos" en modo light — el flujo real
  es `/qa/edificio` (agente + `src/rag`, sin torch).
- **Alturas MDSN desactivadas en vivo** en beta (`beta_light()`: rasterio
  ~200 MB RSS); las del mapa vienen precalculadas.
- **PE-1**: las cotas exactas solo están en los planos de fachada (raster
  por manzana); el sistema enlaza el plano pero no extrae la cifra.
- ~33 edificios `unavailable` en A Coruña: puerto/vías reales, no un bug.
- Servicios externos (Catastro, ArcGIS, Overpass) pueden fallar — el
  sistema degrada a `unavailable` con timeout, nunca bloquea ni inventa.

## 9. Verificación

- **453 tests** verdes en local (`pytest -q`, ~2,5 min).
- Producción verificada (post-deploy `e19e029`): 3 ciudades <1,5 s,
  contexto PE-1 con `plantas_oficiales` + advertencias + enlaces,
  `/qa/edificio` modo LLM con citas a fuentes oficiales.
- Suite PE-1: regresiones de `pe1_en_punto`, `pe1_alzados_en_punto`,
  `altura_alzados`, contradicciones y manifest/RAG con el BOP.

## 10. Mapa de archivos

| Pieza | Archivo |
|---|---|
| Visor web | `web/geolibre/index.html` |
| API | `app/main.py` |
| Edificios + cumplimiento | `src/subzones_service.py` |
| Contexto oficial | `app/main.py` → `_build_official_context` |
| Catastro | `src/catastro/client.py` |
| Ordenanzas municipales | `src/muni_wfs.py`, `src/ambitos_service.py` |
| PE-1 | `src/ambitos_service.py`, `datos/normativa/15078/` |
| Agente IA | `src/agent/` (orchestrator, tools, contradictions, memory, intent_classifier) |
| RAG | `src/rag/`, `src/normativa_rag.py` |
| Viabilidad/informe | `src/zoning_assess.py`, `src/report_service.py` |
| Deploy | `Dockerfile`, `render.yaml`, `scripts/fetch_beta_data.py` |
