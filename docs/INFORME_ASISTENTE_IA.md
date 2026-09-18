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

1. **Parcela → ordenanza sin mapeo automático.** `3CLAS` da SUC pero no la subzona; los parámetros están en PDFs. Hoy el bot lista las ordenanzas extraídas y pide indicarla — es selector asistido, no resolución. *Caso observado: edificio de 23 m/380 viviendas asociado a U6 "vivienda unifamiliar" (máx 7 m) — posible desajuste a verificar.*
2. **RAG lexical, no semántico.** BM25 funciona pero sin embeddings ni reranker en Python 3.14; preguntas con sinónimos ("azotea" vs "cubierta") pueden recuperar poco.
3. **Sin memoria multi-turno.** Cada pregunta es independiente; no hay historial conversacional ni correferencias ("y en la de al lado").
4. **Intención por regex.** Cubre los patrones habituales pero es frágil ante formulaciones nuevas; un clasificador ligero o el propio LLM decidiría mejor.
5. **Validador heurístico.** Verifica citas y números, pero no la corrección semántica de las afirmaciones.
6. **Tier gratuito LLM.** Rate limits variables (429), latencias ocasionales altas; la cadena de modelos lo absorbe pero el último respaldo es lento.
7. **Corpus autonómico = 3 documentos.** Falta Reglamento LSG, CTE relevante, y el PGOM solo cubre municipios con PDFs descargados.
8. **Cálculo limitado.** Solo piscina/elementos auxiliares; no hay evaluación de cambio de uso, subdivisiones, núcleos, etc.
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

## 11. Estado verificado (2026-09-18)

- 351 tests pasan, 1 skip. 15 tests específicos del asistente.
- `/qa/health`: provider `openrouter`, modelo cadena rápida, corpus 561 chunks, rerank `false`.
- En vivo: contexto < 1 s · normativa LLM ~14-30 s con citas validadas · streaming SSE con tokens reales.
- Commits: `ff2dfe0` (asistente completo) → `1c11ee5`, `3adcd4c`, `84bde50`, `ed2a6c1` (iteraciones de intención, streaming, velocidad y clave).

## 12. Preguntas abiertas para el experto

1. ¿La asociación parcela→ordenanza debe resolverse con datos vectoriales oficiales (esfuerzo alto) o basta el selector asistido + verificación profesional?
2. ¿Qué 20-30 preguntas reales haría un arquitecto de AC8? (para la batería de evaluación P0.4)
3. ¿Prioridad: más calculadores normativos (cambio de uso NHV) o mejor recuperación (embeddings)?
4. ¿Vale un segundo entorno Python ≤3.13 solo para el reranker, o preferimos cero dependencias pesadas?
5. ¿El chat debe quedar registrado/trazable por proyecto (multi-proyecto del visor)?
