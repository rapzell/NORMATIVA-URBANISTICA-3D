# Informe técnico — Asistente IA de normativa urbanística

**Fecha:** 2026-09-18 · **Estado:** operativo en producción local · **Ámbito:** `/qa/edificio*` + panel de chat del visor

Documento de trabajo para revisar con el experto cómo funciona el bot, qué decisiones se tomaron y dónde conviene invertir la siguiente fase. Complementa a `GUIA_TECNICA.md` (estado general de la plataforma).

---

## 1. Qué hace hoy el asistente

El arquitecto selecciona un edificio o parcela en el visor GeoLibre y pregunta en lenguaje natural. El sistema responde con tres comportamientos según la intención detectada:

| Intención | Ejemplo | Camino | Latencia real medida |
|---|---|---|---|
| `edificio` (contexto) | "qué tipo de suelo he seleccionado" | Respuesta determinista desde herramientas, **sin RAG ni LLM** | < 1 s |
| `saludo` | "hola" | Respuesta fija + contexto actual | < 1 s |
| `normativa` | "¿puedo hacer una piscina?" | Contexto + RAG + cálculo + LLM + validación | ~14-30 s (LLM gratuito) |

Modos de respuesta expuestos en la API: `contexto`, `llm`, `heuristico` (fallback cuando el LLM falla — devuelve los fragmentos recuperados con mensaje honesto, nunca inventa).

## 2. Arquitectura real

```
Visor GeoLibre (chat)
  → POST /qa/edificio          (JSON completo)
  → POST /qa/edificio/stream   (SSE: contexto → fuentes → token* → final)
  → GET  /qa/health            (estado LLM + corpus)

        orchestrator.py
          1. _detectar_intencion (regex: edificio|saludo|normativa)
          2. _contexto_edificio — 5 herramientas en paralelo (ThreadPoolExecutor)
          3. search_normativa (solo si intencion=normativa)
          4. check_piscina_viability (si la pregunta menciona elementos)
          5. _prompt anclado → model_gateway
          6. validar_respuesta → anotar_respuesta
          7. finalizar_respuesta → modo + fuentes + calculo + validacion
```

## 3. Herramientas del agente (`src/agent/tools.py`)

Funciones Python directas (no MCP aún). Cada una devuelve `data_quality` explícita:

| Herramienta | Fuente | Devuelve |
|---|---|---|
| `get_catastro_data` | Catastro OVC/INSPIRE | refcat, dirección, uso principal, usos por superficie, año, superficie construida |
| `get_siotuga_clasificacion` | SIOTUGA WFS / copia vectorial local | clase_ley (SUC…), uso_zona, denominación, categoría |
| `get_building_data` | MDS IDEE WCS / LAZ / Overture | altura medida (P90), huella |
| `get_ordenanzas_params` | `normativa_params` sobre PDFs PGOM descargados | ocupación máx, edificabilidad, retranqueos, altura máx, parcela mín — con página oficial |
| `get_inventario_planeamiento` | CSV SIOTUGA | instrumento vigente y fecha de aprobación |
| `search_normativa` | `src/rag/search.py` | fragmentos citables |
| `check_piscina_viability` | cálculo propio | ocupación disponible/resultante, viabilidad, notas de datos faltantes |

Las llamadas externas van envueltas en `_safe`: cualquier fallo se degrada a `unavailable`, nunca tumba la consulta.

## 4. RAG normativo

Dos índices BM25 unificados en `src/rag/search.py`:

| Índice | Contenido | Chunking | Volumen |
|---|---|---|---|
| Corpus autonómico (`src/rag/corpus.py`) | Ley 2/2016 consolidada ene-2026, NHV comentada IGVS v1.2, NTPU abr-2022 | **por artículo/disposición** con `article_ref` + página | **561 chunks** (403+57+101) |
| Municipal (`src/normativa_rag.py`) | PDFs del PGOM descargados vía `/official/normativa-docs` | por página | depende del municipio (Vigo: nu002/nu003 indexados) |

Detalles relevantes:

- **Dedup por contenido**: el mismo texto repetido en varios PDFs no ocupa dos citas.
- **Prioridad municipal**: +0.5 al score de fragmentos locales.
- **Reranker semántico opcional**: `SINAI/ALIA-MrBERT-es-legal-administrative-reranker` si `sentence_transformers` está instalado (`RAG_RERANKER=1`). En Python 3.14 no hay torch → desactivado automáticamente, BM25 puro.
- **Filtro de relevancia en modo heurístico**: si el mejor score es < 3.0 solo se muestran los 3 mejores fragmentos; si nada es claramente relevante, el sistema lo dice en vez de volcar texto.
- **Caché**: índice en disco invalidado por sha256 del manifiesto (`_manifest_key`).

## 5. Gateway LLM (`src/model_gateway.py`)

- Proveedores OpenAI-compatibles: openrouter, groq, gemini, mistral, cerebras, huggingface, freellm, ollama, local (GGUF).
- **Claves**: variable de entorno por proveedor → respaldo `api.txt`/`api.env`/`.env` en la raíz del repo (gitignored). Si existe clave de OpenRouter en archivo, **openrouter se activa solo** como proveedor. Bajo pytest el archivo se ignora (tests herméticos).
- **Cadena de modelos**: `default_model`/`OPENROUTER_MODEL` acepta lista separada por comas; se intenta cada modelo hasta obtener contenido no vacío:

  ```
  dots-studio/dots-3-note-preview:free (~26 s)
    → cohere/north-mini-code:free (~29 s)
    → deepseek/deepseek-v4-flash-0731:free (~130 s, último respaldo)
  ```

- `MODEL_FALLBACK_CHAIN` = `openrouter,local` (launch_server.cmd).
- `MODEL_MAX_TOKENS` = 8000 y `TIMEOUT_S` = 300: los modelos gratuitos con razonamiento queman tokens pensando y tardaban ~2 min; con 600/45 llegaban respuestas vacías.
- Streaming real por SSE (`stream_with_fallback`) cuando el proveedor lo soporta.

## 6. Prompt y validación

**Prompt anclado** (`_prompt`): system prompt con 8 reglas estrictas (solo afirmar lo respaldado, citar `[FUENTE n]`, distinguir autonómico/municipal, advertir datos `estimated`, no inventar, mostrar cálculos paso a paso, cerrar con condiciones a verificar) + contexto del edificio con `data_quality` por campo + cálculo previo + fragmentos numerados con documento/referencia/página.

**Validador** (`src/agent/validator.py`):

- Cada `[FUENTE n]` debe existir en los fragmentos recuperados → `verificada`/`no_encontrada`.
- Números citados deben aparecer en contexto o fragmentos (ignora 0-31 triviales).
- Si falla → `requiere_revision` + advertencia visible "Requiere revisión humana" con las citas problemáticas. Nunca se oculta.

## 7. Frontend (visor)

Panel de chat con: contexto del último edificio seleccionado (municipio/subzona/refcat), consumo SSE en vivo (tokens progresivos), badge de modo (`IA`/`contexto`/`extractivo`), fuentes con enlaces, bloque de cálculo, renderizado `mdLite` (negritas/citas), fallback a POST JSON si el stream falla.

## 8. Datos y trazabilidad

- Cada dato del contexto viaja con `data_quality`: `official` | `measured` | `estimated` | `unavailable`.
- Cada fuente citable expone: documento, referencia/fichero, página, extracto, URL oficial, ámbito (`autonomico`/`municipal`).
- La ordenanza muestra el PDF y la página oficial de donde se extrajo cada parámetro (`trazas`).

## 9. Limitaciones conocidas (honestas)

> **Actualización**: los puntos 1-5 y 8 quedaron cubiertos por la
> implementación de la guía del experto (sección 12). Se conservan
> aquí como estado residual.

1. **Parcela → ordenanza**: resuelta parcialmente — `ordinance_resolver` intenta código oficial en atributos de zona (`oficial`), coincidencia por título (`inferida`, siempre etiquetada "verificar"), y marca `ambigua`/`no_resuelta` sin elegir. Lo que no se puede resolver oficialmente sigue pidiendo selección manual. Residual: depende de que la zona SIOTUGA lleve código/denominación compatible.
2. **RAG híbrido activo**: BM25 + sinónimos ES/GL + embeddings ALIA (561 chunks precalculados en `datos/rag/`) + RRF k=60 + reranker legal remoto. Si el microservicio :8003 está caído degrada a BM25+sinónimos sin fallar.
3. **Memoria multi-turno**: `chat_id` (frontend lo persiste en localStorage), ventana de 3 turnos, TTL 30 min, correferencias ("ahí", "y si…") que reutilizan el edificio anterior. RAM; producción → Redis.
4. **Intención**: regex para casos fiables + LLM few-shot que refina el bucket ambiguo "normativa" con timeout de 5 s.
5. **Validación**: heurística de citas/números + validación semántica opcional con LLM (`SEMANTIC_VALIDATION=1`, solo si la heurística pasa; fallos → queda la heurística).
6. **Tier gratuito LLM.** Rate limits variables (429), latencias ocasionales altas; la cadena de modelos lo absorbe pero el último respaldo es lento.
7. **Corpus autonómico = 3 documentos.** Falta Reglamento LSG, CTE relevante, y el PGOM solo cubre municipios con PDFs descargados.
8. **Calculadores**: piscina (ocupación) + cambio de uso NHV vía `habitabilidad_checker` (sin medidas → `no_verificable`, lista requisitos oficiales). Residual: ocupación/edificabilidad/retranqueos genéricos pendientes.
9. **Sin MCP.** Herramientas son funciones Python; interoperabilidad futura pendiente.
10. **`data_quality` de respuesta agregada** se reduce a `official/unavailable` según haya fragmentos — no refleja la mezcla real de calidades.

## 10. Propuestas de mejora para decidir con el experto

### P0 — Calidad de la información (lo que más importa)

| # | Propuesta | Esfuerzo | Impacto |
|---|---|---|---|
| P0.1 | **Resolver parcela → ordenanza**: capas vectoriales municipales (ArcGIS/GeoServer propios de cada concello), OCR del plano raster, o confirmación asistida del selector actual | Alto | Elimina la principal brecha de fiabilidad |
| P0.2 | **Detector de contradicciones**: si altura medida > altura máx de la ordenanza asignada (caso 23 m vs U6=7 m) → aviso explícito de posible ordenanza mal asignada | Bajo | Evita presentar datos incompatibles como válidos |
| P0.3 | **Ampliar corpus**: Reglamento LSG (Decreto 143/2016), CTE-DB-SI/HE pertinentes, y descarga masiva de PGOM de los municipios de trabajo de AC8 | Medio | Respuestas más completas y locales |
| P0.4 | **Batería de evaluación**: 20-30 preguntas reales de arquitectos con respuesta esperada → script de regresión que mida precisión de citas | Medio | Permite medir mejoras objetivamente |

### P1 — Precisión y experiencia

| # | Propuesta | Esfuerzo | Impacto |
|---|---|---|---|
| P1.1 | **Entorno Python ≤3.13 secundario** con `sentence_transformers` → embeddings + reranker ALIA legal (Apache-2.0, CPU) | Medio | Recuperación mucho más precisa |
| P1.2 | **Expansión de consulta** léxica (sinónimos urbanísticos ES/GL) + filtro por tipo de artículo según la pregunta | Bajo | Mejora BM25 sin dependencias |
| P1.3 | **Memoria de sesión** corta (último edificio + últimas 3 preguntas) para correferencias | Bajo-Medio | Conversación natural |
| P1.4 | **Más calculadores**: cambio de uso a vivienda (NHV), ocupación/edificabilidad genérica, retranqueos, número de viviendas por superficie | Medio | Respuestas operativas, no solo texto |
| P1.5 | **Clasificador de intención por LLM** (o regex ampliado con tests) para rutar contexto/normativa/cálculo | Bajo | Menos falsos positivos/negativos |

### P2 — Arquitectura y escala

| # | Propuesta | Esfuerzo | Impacto |
|---|---|---|---|
| P2.1 | **pgvector/PostGIS** para índice vectorial real cuando haya PostgreSQL | Alto | Escala a cientos de documentos |
| P2.2 | **Servidor MCP** formalizando las herramientas actuales | Alto | Interoperabilidad con otros agentes |
| P2.3 | **Proveedores adicionales** (Groq/Gemini gratuitos) en la cadena — reducen latencia y dependencia de OpenRouter | Bajo | Robustez y velocidad |
| P2.4 | **Caché de respuestas** por (refcat, subzona, pregunta normalizada) | Bajo | Respuestas instantáneas repetidas |
| P2.5 | **Generación de informe desde el chat**: "expórtame esta consulta" → sección del informe de viabilidad | Medio | Cierra el flujo arquitecto→cliente |

## 11. Estado verificado

- 386 tests pasan (49 del asistente: orquestador + mejoras). Herméticos: sin red, sin :8003.
- `/qa/health`: provider `openrouter`, `servicio_embeddings: true`, `embeddings_disponibles: true`, `memoria` activa.
- Microservicio :8003 (`venv_rag`, Python 3.13): embedder + reranker ALIA legal ES cargados y respondiendo.
- En vivo verificado: contexto <1 s · multi-turno con correferencia ("y ahí puedo hacer una piscina" sin coordenadas → resolvió la parcela previa) · cambio de uso → `check_cambio_uso` NHV con `no_verificable` · SSE `contexto→fuentes→final` sin tokens en preguntas de contexto.
- Commits: `ff2dfe0` (asistente completo) → `1c11ee5`, `3adcd4c`, `84bde50`, `ed2a6c1` → implementación guía del experto (este cambio).

## 12. Guía del experto implementada — módulos nuevos

La guía del experto quedó implementada al completo con arquitectura degradable por capas:

```
chat_id → memoria de sesión (3 turnos, TTL 30 min)
    ↓
clasificar_intencion (regex fiable → LLM few-shot solo si ambiguo, 5 s)
    ↓
herramientas en paralelo (Catastro, SIOTUGA, altura, ordenanzas, inventario)
    ↓
resolver_ordenanza (oficial > inferida > ambigua > no_resuelta)
    ↓
detectar_contradicciones (⚠ altura medida vs ordenanza, parcela mínima…)
    ↓
RAG híbrido: sinónimos → BM25 + embeddings :8003 → RRF k=60 → reranker ALIA
    ↓
calculador (piscina | cambio de uso NHV → no_verificable sin medidas)
    ↓
prompt (contexto + fuentes + historial + advertencias) → LLM
    ↓
validar_respuesta (citas+números) → validacion_semantica (opt., env-gated)
```

| Módulo | Fichero | Degradación |
|---|---|---|
| Intención | `src/agent/intent_classifier.py` | LLM lento/falla → regex, 0 coste extra |
| Memoria | `src/agent/memory.py` | sin `chat_id` → comportamiento anterior |
| Sinónimos | `src/rag/synonyms.py` | falla → query original |
| Híbrido | `src/rag/hybrid_search.py` + `embedding_service.py` (:8003, `venv_rag` Py3.13) | servicio caído → BM25+sinónimos |
| Ordenanza | `src/agent/ordinance_resolver.py` | sin resolución → lista oficial + petición manual |
| Contradicciones | `src/agent/contradictions.py` | siempre activo, solo avisa |
| Cambio de uso | `tools.check_cambio_uso` → `habitabilidad_checker` | sin medidas → `no_verificable` + requisitos |
| Validación semántica | `validator.validacion_semantica` | `SEMANTIC_VALIDATION=1`; fallos → heurística |
| Citas clicables | `#page=N` en `url` de cada fuente (corpus y municipales) | sin URL → cita sin enlace |

**Operación del servicio de embeddings**: `scripts\launch_embedding_service.cmd` (puerto 8003). Tras cambiar `datos/corpus/`: `venv\Scripts\python.exe scripts\precompute_embeddings.py` — la invalidación es por sha256 del manifiesto.

**Nota honesta sobre la intención LLM**: el few-shot solo se invoca cuando el regex cae en el bucket ambiguo "normativa" — los casos fiables (saludo, contexto, cálculo) no pagan la latencia de una llamada al tier gratuito.

## 13. Preguntas abiertas para el experto

1. ¿La asociación parcela→ordenanza debe resolverse con datos vectoriales oficiales (esfuerzo alto) o basta el selector asistido + verificación profesional?
2. ¿Qué 20-30 preguntas reales haría un arquitecto de AC8? (para la batería de evaluación P0.4)
3. ¿Prioridad: más calculadores normativos (cambio de uso NHV) o mejor recuperación (embeddings)?
4. ¿Vale un segundo entorno Python ≤3.13 solo para el reranker, o preferimos cero dependencias pesadas?
5. ¿El chat debe quedar registrado/trazable por proyecto (multi-proyecto del visor)?
