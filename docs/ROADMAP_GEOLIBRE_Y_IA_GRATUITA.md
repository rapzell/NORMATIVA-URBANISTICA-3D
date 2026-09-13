# Roadmap técnico: GeoLibre + IA gratuita

## 1. Objetivo

Este roadmap traduce la propuesta funcional a trabajo implementable sobre el repositorio actual.

Metas:

1. mantener **FastAPI** como motor normativo oficial;
2. integrar **GeoLibre** como experiencia GIS principal por fases;
3. migrar la capa IA a una arquitectura **100% gratuita**;
4. no romper los endpoints ni el visor 3D ya existentes.

Base verificada del repositorio: commit `2f9775c06f3798c992ba0002f887e206d01f9db0`.

---

## 2. Principios de implementación

- separar **estado actual** y **objetivo futuro**;
- no duplicar la lógica oficial de viabilidad en el cliente;
- conservar el fallback heurístico actual;
- introducir cambios incrementales y testeables;
- mantener compatibilidad con el visor Three.js mientras GeoLibre entra en paralelo.

---

## 3. Fase 0 — saneamiento previo del backend

## 3.1 Objetivo

Reducir el acoplamiento actual antes de añadir nuevas piezas.

## 3.2 Trabajo técnico

### A. Extraer servicios desde `app/main.py`

Crear módulos internos como:

- `app/services/plan_service.py`
- `app/services/zoning_service.py`
- `app/services/export_service.py`
- `app/services/gis_service.py`
- `app/services/report_service.py`

### B. Consolidar la resolución de parámetros efectivos

Actualmente la lógica de resolución aparece repartida alrededor de:

- `POST /zoning/volume`
- `POST /zoning/assess`
- `POST /zoning/volume-export`

El objetivo es tener una sola función reutilizable.

### C. Extraer contratos tipados comunes

Conviene centralizar:

- parámetros efectivos;
- diagnósticos geométricos;
- resultado normativo;
- errores controlados.

## 3.3 Criterio de terminado

- menos lógica repetida en `app/main.py`;
- tests actuales en verde;
- endpoints existentes sin cambios funcionales visibles.

---

## 4. Fase 1 — gateway IA gratuito y genérico

## 4.1 Objetivo

Sustituir la dependencia explícita de OpenAI/Ollama/local por un gateway OpenAI-compatible configurable.

## 4.2 Estado actual verificado

Hoy el proyecto implementa en `src/model_gateway.py`:

- `_call_openai()`
- `_call_ollama()`
- `_call_local()`
- `generate_with_fallback()`

Y `src/asistente_normativa.py` sigue refiriéndose a flujos como `OpenAI -> local` y a un modo avanzado ligado a Ollama.

## 4.3 Diseño objetivo

Variables recomendadas:

- `MODEL_PROVIDER`
- `MODEL_BASE_URL`
- `MODEL_API_KEY`
- `MODEL_NAME`
- `MODEL_FALLBACK_CHAIN`
- `MODEL_MAX_TOKENS`
- `MODEL_TEMPERATURE`

### Política de fallback

1. intentar proveedor primario;
2. recorrer cadena de fallback;
3. si todo falla, activar fallback heurístico actual.

## 4.4 Proveedores sugeridos

- OpenRouter free
- Groq
- Gemini compatible
- Mistral
- Cerebras

## 4.5 Tareas concretas

- refactorizar `src/model_gateway.py` para desacoplar proveedor de implementación;
- adaptar `src/asistente_normativa.py` para no acoplarse a Ollama/OpenAI en el texto y la CLI;
- añadir tests unitarios de fallback;
- documentar variables en `scripts/launch_server.cmd` y/o docs.

## 4.6 Criterio de terminado

- el asistente funciona con proveedor cloud gratuito configurable;
- si el proveedor falla, cae a otro o al modo heurístico;
- no se requiere OpenAI ni Ollama para uso básico.

---

## 5. Fase 2 — capa espacial de subzonas

## 5.1 Objetivo

Complementar el CSV con una capa espacial consultable.

## 5.2 Diseño de datos

Conservar CSV para atributos normativos y añadir una capa con:

- `municipio`
- `subzona`
- `fuente`
- `version`
- `geometry`

## 5.3 Formatos recomendados

Orden práctico de adopción:

1. GeoJSON
2. GeoPackage
3. GeoParquet

## 5.4 Tareas concretas

- definir esquema mínimo de subzonas;
- crear un primer dataset piloto para uno o dos municipios;
- exponerlo por FastAPI o servirlo como estático;
- enlazarlo con `municipio` + `subzona`.

## 5.5 Criterio de terminado

- se puede visualizar la subzona en mapa;
- la unión entre geometría y parámetros numéricos es estable.

---

## 6. Fase 3 — integración ligera con GeoLibre

## 6.1 Objetivo

Introducir GeoLibre sin romper el frontend actual.

## 6.2 Estrategia

- mantener el visor actual;
- añadir una vista GeoLibre paralela;
- cargar subzonas, inventario y resultados GeoJSON;
- usar GeoLibre para inspección GIS, no para la decisión oficial.

## 6.3 Tareas concretas

- preparar una ruta o acceso específico hacia la experiencia GeoLibre;
- publicar datasets que GeoLibre consuma bien;
- validar flujo de selección de capa y consulta de atributos;
- superponer resultados de `/zoning/assess` y `/zoning/volume`.

## 6.4 Criterio de terminado

- el usuario puede explorar cartografía legal en GeoLibre;
- la decisión normativa sigue llegando desde FastAPI.

---

## 7. Fase 4 — flujo híbrido GIS + backend

## 7.1 Objetivo

Hacer que la experiencia cartográfica y la evaluación se conecten de forma natural.

## 7.2 Flujo esperado

1. el usuario selecciona parcela o subzona en GeoLibre;
2. GeoLibre envía geometría/contexto al backend;
3. FastAPI devuelve viabilidad, parámetros y volumen;
4. GeoLibre pinta resultado y diagnósticos;
5. el visor 3D puede abrirse para revisión específica.

## 7.3 Tareas concretas

- definir payload mínimo entre GeoLibre y backend;
- normalizar salida GeoJSON + diagnósticos;
- preparar una capa de estilo para resultado apto/condicionado/no apto;
- enlazar con exportaciones e informes.

## 7.4 Criterio de terminado

- existe un flujo continuo mapa → análisis → resultado → revisión.

---

## 8. Fase 5 — informes y composición cartográfica

## 8.1 Objetivo

Mejorar la salida documental del sistema.

## 8.2 Tareas concretas

- definir plantilla de informe unificada;
- combinar mapa, parcela, subzona y resultado;
- mantener trazabilidad de parámetros aplicados;
- incorporar exportación HTML/PDF con mejor composición.

## 8.3 Criterio de terminado

- el informe sirve tanto como entrega técnica como para revisión visual.

---

## 9. Testing recomendado por fase

## Backend / dominio

- tests de proveedor CSV;
- tests de resolución de parámetros efectivos;
- tests de fallback IA;
- tests de volumen y viabilidad.

## Integración GIS

- smoke tests de endpoints de capas;
- pruebas de consistencia entre subzona espacial y subzona alfanumérica;
- pruebas de render básico del visor y estáticos.

## Regresión funcional

- mantener green los tests ya existentes del visor;
- añadir casos piloto de uno o dos municipios.

---

## 10. Orden recomendado real de ejecución

1. refactor de `app/main.py`
2. gateway IA gratuito genérico
3. dataset espacial piloto de subzonas
4. vista GeoLibre paralela
5. flujo híbrido completo
6. informes reforzados

Ese orden minimiza riesgo y maximiza reutilización del código existente.

---

## 11. Resultado esperado

Si se sigue este roadmap, el sistema quedaría con esta forma:

- **FastAPI**: reglas, viabilidad, volumen, exportación, QA y trazabilidad;
- **GeoLibre**: navegación GIS, capas legales, análisis espacial exploratorio y mapa principal;
- **Three.js**: revisión 3D especializada;
- **IA gratuita**: proveedor cloud configurable con fallback multi-proveedor y red de seguridad heurística.

Ese es, a día de hoy, el camino técnicamente más sólido para mejorar el producto sin rehacerlo desde cero.
