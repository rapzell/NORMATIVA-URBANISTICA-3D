# Guía técnica de funcionamiento de NORMATIVA GALICIA 3D

## 1. Propósito de esta guía

Esta guía describe el funcionamiento técnico del proyecto y, además, propone una evolución concreta en dos frentes:

1. una **operación 100% gratuita**, evitando dependencias de pago en la capa de IA;
2. una **integración progresiva con GeoLibre** como visor/cartografía avanzada y plataforma GIS de apoyo.

Importante: en este documento separo de forma explícita:

- **estado actual implementado en el código**;
- **arquitectura objetivo propuesta**.

Eso es necesario porque el repositorio actual todavía no integra GeoLibre dentro del frontend principal. En cambio, la parte de gateway IA ya puede orientarse a proveedores OpenAI-compatible configurables, manteniendo compatibilidad con OpenAI, Ollama y fallback local. La propuesta gratuita y la integración con GeoLibre siguen siendo viables, pero solo la parte del gateway ha empezado a acercarse a esa arquitectura objetivo.

---

## 2. Resumen ejecutivo

NORMATIVA GALICIA 3D es una plataforma orientada a:

- análisis urbanístico preliminar;
- visualización de parcelas y volúmenes edificables;
- consulta de normativa por municipio/subzona;
- exportación de resultados 3D;
- y asistencia normativa apoyada en recuperación semántica.

En su estado actual, el sistema combina:

- un backend HTTP en **FastAPI**;
- un visor web estático con **Three.js** y componentes de mapa;
- una capa de resolución de parámetros urbanísticos desde **CSV**;
- un motor geométrico con **Shapely**;
- extractores heurísticos desde texto normativo;
- un módulo de QA/RAG con embeddings, reranking y generación opcional.

La evolución más razonable, si el objetivo es mejorar la experiencia GIS sin perder el trabajo ya hecho, es **no reemplazar de golpe el sistema actual**, sino dividir el producto en dos capas:

- una capa **normativa y de cálculo** que seguiría residiendo en FastAPI;
- una capa **cartográfica y de exploración espacial** reforzada con GeoLibre.

---

## 3. Estado actual del sistema

## 3.1 Backend principal

El punto de entrada es `app/main.py`. Ahí se concentra gran parte de la lógica operativa del proyecto:

- inicialización de FastAPI;
- autodetección de plan CSV;
- servido de estáticos del visor;
- endpoints `/zoning/*`;
- endpoints `/admin/*`;
- proxies GIS (`/proxy/*`);
- inventario de planeamiento;
- métricas y diagnósticos.

### Observación de arquitectura

`app/main.py` está haciendo de:

- router HTTP,
- composition root,
- capa de servicios,
- capa de integración GIS,
- y parte de la capa de exportación.

Eso funciona para un MVP, pero ya es una señal clara de que el proyecto ha crecido lo suficiente como para beneficiarse de una refactorización por servicios.

## 3.2 Visor actual

El visor principal se sirve desde:

- `web/examples/threejs-viewer/index.html`

y se publica en la app mediante el montaje de estáticos. Su papel actual es:

- mostrar el mapa/escena;
- capturar geometrías o viewport;
- llamar a la API;
- visualizar GLTF/GLB;
- gestionar paneles de depuración y controles de operación.

Es un visor orientado sobre todo a:

- pruebas funcionales;
- volúmenes 3D;
- demostraciones técnicas;
- y validación rápida de parámetros urbanísticos.

## 3.3 Planeamiento municipal

La resolución normativa se apoya principalmente en el modelo `PlanParams`, que encapsula:

- altura máxima;
- retranqueo mínimo uniforme;
- setbacks direccionales;
- dirección de frente por defecto;
- ocupación máxima;
- edificabilidad máxima;
- metadatos de procedencia.

Este diseño es bueno porque desacopla la fuente del dato de la lógica de análisis. Hoy la fuente principal es CSV, pero el contrato es suficientemente neutro como para admitir mañana:

- capas GIS;
- resultados OCR estructurados;
- GeoPackage/GeoParquet;
- o incluso una base PostGIS.

## 3.4 QA / IA actual

El módulo de QA actual se compone de:

- embeddings con `SentenceTransformer`;
- reranking con `CrossEncoder`;
- un generador accesible a través de `src/model_gateway.py`;
- fallback robusto cuando faltan recursos o falla la generación.

### Punto importante

El código actual **ya ha empezado la transición** hacia un gateway más genérico, pero **todavía no puede darse por cerrada una edición 100% gratuita multi-proveedor completa**. En el estado actual:

- `src/model_gateway.py` ya admite una cadena configurable de proveedores OpenAI-compatible y conserva compatibilidad con **OpenAI**, **Ollama** y **modelo local**;
- `src/asistente_normativa.py` ya no se describe como un flujo rígido `OpenAI -> local`, aunque sigue conservando compatibilidad operativa con Ollama en modo avanzado si no hay proveedor externo configurado.

Por tanto, si la documentación habla de operación 100% gratuita, lo correcto es entenderla como:

- una **dirección ya iniciada en el código**;
- un **objetivo recomendado** para la configuración por defecto;
- y un **plan de consolidación** todavía pendiente.

---

## 4. Flujo funcional actual

El flujo real del sistema hoy es el siguiente:

1. el usuario abre el visor;
2. el visor toma una geometría activa o construye una a partir del viewport;
3. llama a endpoints FastAPI como:
   - `POST /zoning/analyze`
   - `POST /zoning/assess`
   - `POST /zoning/volume`
   - `POST /zoning/volume-export`
4. el backend resuelve parámetros urbanísticos:
   - desde request explícita,
   - desde CSV,
   - o mediante inferencia GIS en ciertos casos;
5. el backend ejecuta:
   - análisis normativo,
   - cálculo geométrico,
   - evaluación de viabilidad,
   - exportación 3D,
   - y, cuando se solicita, QA normativa;
6. devuelve resultado estructurado y diagnósticos para ser consumidos por la UI.

Este flujo está bien orientado para un producto de escritorio/local o demo técnica, pero todavía no explota del todo el potencial de una interfaz GIS moderna basada en capas, tablas, simbología y consultas espaciales avanzadas.

---

## 5. Componentes técnicos actuales

## 5.1 Backend FastAPI

Responsabilidades actuales:

- publicar la API;
- servir el visor;
- resolver el plan activo;
- exponer endpoints administrativos;
- integrar servicios WMS/ArcGIS/SIOSE;
- generar informes y exportaciones;
- exponer métricas.

## 5.2 Proveedor CSV

`src/planes/csv_provider.py` implementa el proveedor más importante hoy.

Hace:

- lectura del CSV;
- validación de columnas;
- normalización de municipio y subzona;
- coincidencia flexible;
- validaciones de rangos;
- y devolución en formato `PlanParams`.

### Ventaja

Para un proyecto en expansión normativa, CSV sigue siendo una buena elección como capa de transición porque:

- es sencillo de editar;
- fácil de auditar;
- fácil de versionar;
- y muy barato de operar.

### Limitación

CSV es bueno para los **atributos**, pero malo para la **cartografía asociada**. Por eso tiene sentido mantenerlo para reglas numéricas y añadir una capa geoespacial paralela para la representación espacial de subzonas.

## 5.3 Rules engine

`src/rules_engine.py` aporta una capa de análisis explicable y conservadora.

No intenta resolver toda la casuística jurídica real, sino:

- normalizar tipos de suelo;
- devolver observaciones;
- devolver restricciones base;
- incorporar parámetros del planeamiento municipal cuando existen.

Es, en esencia, una capa de decisión de tipo **MVP explicable**, adecuada para viabilidad preliminar.

## 5.4 Motor geométrico

`src/volume.py` calcula envolventes edificables con Shapely.

Características actuales:

- saneo geométrico básico;
- manejo de CRS geográfico en algunos casos;
- setbacks uniformes o direccionales;
- detección de frente por `front_direction` o `street_axis`;
- diagnósticos ricos para depuración.

### Fortalezas

- trazabilidad;
- comportamiento conservador;
- lógica razonablemente robusta para casos frecuentes;
- buen equilibrio entre simplicidad y utilidad.

### Limitaciones

- no es un motor urbanístico completo;
- la dirección del frente depende de heurísticas geométricas razonables, pero no infalibles;
- varias reglas todavía son simplificaciones del problema normativo real.

## 5.5 Extracción textual

El proyecto dispone de extracción heurística desde texto por dos vías:

- endpoints API de extracción básica;
- `src/text_extractor.py` como módulo reutilizable.

Esto sirve para:

- convertir normativa libre a estructura;
- apoyar la construcción de datasets;
- enriquecer respuestas cuando no hay datos perfectos;
- preparar futuras automatizaciones de OCR/ingesta.

## 5.6 Exportación 3D

`POST /zoning/volume-export` genera:

- `CityJSON`
- `GLTF`
- `GLB`

Esta parte ya da valor diferencial al proyecto porque conecta normativa y volumetría con formatos útiles para revisión, demo e interoperabilidad.

---

## 6. Operación 100% gratuita: qué significa realmente

Tu primera condición es correcta: si hay partes de pago, se ignoran. Pero técnicamente conviene distinguir dos cosas:

## 6.1 Lo que ya puede hacerse gratis hoy

El proyecto ya puede operar sin coste recurrente en gran parte del stack si se usa:

- FastAPI;
- Three.js / MapLibre;
- CSV;
- Shapely;
- datos abiertos o servicios públicos;
- embeddings/modelos locales cuando el hardware lo permita;
- y fallback heurístico sin LLM cuando no se quiera usar IA generativa.

Esto ya es, en gran medida, una operación de coste cero.

## 6.2 Lo que no está implementado todavía

Todavía no está completamente consolidado en el código actual:

- un conjunto de presets y documentación de uso suficientemente pulidos para todos los proveedores gratuitos recomendados;
- la configuración por defecto del proyecto orientada de fábrica a un proveedor gratuito concreto;
- ni la verificación completa de todos los caminos de fallback en entorno real.

Sí existe ya, sin embargo, una base para:

- `MODEL_PROVIDER` configurable;
- `MODEL_FALLBACK_CHAIN` multi-proveedor;
- y un cliente OpenAI-compatible genérico con compatibilidad heredada para OpenAI y Ollama.

### Conclusión honesta

La edición “100% gratuita con APIs gratuitas en la nube” ha dejado de ser solo una idea y ya tiene base técnica en el gateway, pero todavía no puede describirse como una migración completamente cerrada de extremo a extremo.

---

## 7. Cómo dejar la capa IA 100% gratuita sin romper el proyecto

La mejor forma no es reescribir todo el asistente, sino **generalizar `model_gateway.py`**.

## 7.1 Objetivo recomendado

Sustituir el gateway actual orientado a:

- OpenAI
- Ollama
- local GGUF

por un gateway por perfiles de proveedor compatibles con el protocolo OpenAI, por ejemplo:

- OpenRouter;
- Groq;
- Gemini OpenAI-compatible;
- Mistral;
- Cerebras;
- Hugging Face Inference;
- y opcionalmente un router autoalojado tipo FreeLLMAPI u Open-LLM Router.

## 7.2 Diseño recomendado

En lugar de codificar un método por proveedor, conviene introducir una capa así:

- `MODEL_PROVIDER`
- `MODEL_BASE_URL`
- `MODEL_API_KEY`
- `MODEL_NAME`
- `MODEL_FALLBACK_CHAIN`
- `MODEL_MAX_TOKENS`
- `MODEL_TEMPERATURE`

Con eso, el gateway solo necesita:

1. construir un cliente OpenAI-compatible;
2. enviar una petición de chat/completions;
3. si falla, recorrer la cadena de fallback;
4. si falla todo, caer al modo heurístico actual.

## 7.3 Qué debe mantenerse

Hay tres cosas del diseño actual que **sí conviene conservar**:

1. el fallback heurístico sin LLM;
2. la lógica RAG previa a la generación;
3. el control conservador de longitud y postprocesado de respuesta.

## 7.4 Estrategia práctica y gratuita

La ruta más realista es:

- primario: **OpenRouter free**;
- respaldo 1: **Groq**;
- respaldo 2: **Gemini**;
- respaldo 3: **Mistral** o **Cerebras**;
- fallback final: **modo heurístico actual**.

### Motivo

Eso mantiene:

- coste cero;
- rapidez razonable;
- variedad de modelos;
- y resiliencia frente a límites diarios o por minuto.

## 7.5 Qué no haría

No recomendaría depender exclusivamente de:

- un único proveedor gratuito en la nube;
- ni de un modelo local pesado obligatorio;
- ni de un flujo acoplado a Ollama si el objetivo es facilidad de despliegue.

---

## 8. GeoLibre: por qué encaja y por qué no debe reemplazar todo de golpe

GeoLibre tiene mucho sentido aquí, pero no como “sustitución total inmediata” del sistema actual.

Según su documentación pública, GeoLibre es una plataforma GIS libre, con:

- MapLibre como motor de mapa;
- React/TypeScript en frontend;
- DuckDB-WASM Spatial;
- deck.gl;
- soporte de múltiples formatos y servicios;
- herramientas vectoriales/raster/SQL;
- y despliegue web además de escritorio.

## 8.1 Encaje real con tu proyecto

Encaja especialmente bien en estos puntos:

### a) Visualización cartográfica avanzada

Tu proyecto actual está muy bien para volumen y demo 3D, pero GeoLibre aporta una experiencia mucho más madura para:

- capas vectoriales;
- WMS/WFS/WMTS/ArcGIS;
- tablas de atributos;
- estilos temáticos;
- filtros;
- consultas espaciales;
- y manejo de proyectos GIS.

### b) Consultas y análisis client-side

GeoLibre aporta valor para:

- buffers;
- intersecciones;
- overlays;
- estadísticas;
- SQL espacial con DuckDB-WASM;
- exploración sobre capas cargadas;
- análisis de apoyo a la decisión sin cargar todo al backend.

### c) Convivencia con tu backend

No necesitas mover tu lógica urbanística a GeoLibre. De hecho, lo recomendable es lo contrario:

- **FastAPI** sigue siendo el motor normativo y de cálculo oficial;
- **GeoLibre** se convierte en el visor GIS y entorno de análisis espacial de alto nivel.

## 8.2 Dónde no conviene usar GeoLibre como reemplazo directo

No lo usaría para sustituir de golpe:

- la lógica jurídica/normativa del backend;
- el cálculo oficial de viabilidad;
- la exportación de volúmenes ligada a tus reglas actuales;
- ni el contrato de API que ya consume el visor y los tests.

### Motivo

GeoLibre es fuerte como:

- plataforma cartográfica,
- GIS interactivo,
- contenedor de herramientas,
- explorador de datos,
- y entorno de trabajo visual.

Pero la “verdad normativa” de tu producto debe seguir viviendo en tu backend, donde puedes:

- versionar reglas;
- auditar cálculos;
- testear comportamiento;
- y controlar salidas reproducibles.

---

## 9. Arquitectura objetivo recomendada con GeoLibre

La mejor arquitectura no es “tirar Three.js y usar solo GeoLibre”, sino una arquitectura dual y gradual.

## 9.1 Capa 1: backend normativo oficial

Mantener en FastAPI:

- `/zoning/analyze`
- `/zoning/assess`
- `/zoning/volume`
- `/zoning/volume-export`
- `/planeamento/inventario`
- `/admin/*`
- proxies GIS cuando sigan siendo útiles

Esta capa seguiría siendo la fuente oficial de:

- reglas;
- decisiones;
- volumetría;
- exportaciones;
- informes;
- y trazabilidad.

## 9.2 Capa 2: frontend GIS reforzado con GeoLibre

GeoLibre debería asumir progresivamente:

- navegación cartográfica principal;
- gestión de capas y simbología;
- carga de subzonas y planeamiento espacial;
- edición/exploración de atributos;
- selección espacial de parcelas;
- SQL espacial exploratorio;
- composición visual de mapas para informes.

## 9.3 Capa 3: frontend 3D especializado

El visor 3D actual puede mantenerse para:

- visualización volumétrica especializada;
- revisión GLTF/GLB;
- demos 3D;
- exportación geométrica rápida.

### Conclusión técnica

GeoLibre no tiene por qué matar el visor actual. Puede convertirse en:

- la experiencia 2D/GIS principal;
- mientras Three.js queda como módulo especializado 3D.

Eso, de hecho, es más sólido que forzar a una sola herramienta a hacerlo todo.

---

## 10. Estrategia de integración con GeoLibre por fases

## Fase 1 — Integración ligera, sin romper nada

Objetivo:

- introducir GeoLibre como visor cartográfico paralelo, no sustitutivo.

Acciones:

- añadir un acceso desde la UI actual a una vista GeoLibre;
- publicar datasets del backend en formatos que GeoLibre consuma bien;
- usar GeoLibre para visualizar:
  - subzonas,
  - parcelas,
  - capas auxiliares,
  - inventario de planeamiento,
  - resultados GeoJSON.

Resultado:

- el producto gana un frontend GIS potente;
- no se rompe el contrato actual del backend.

## Fase 2 — Datos espaciales de planeamiento

Objetivo:

- dejar de depender solo de CSV para la parte espacial.

Acciones:

- mantener CSV para parámetros numéricos;
- añadir una capa geoespacial con polígonos de subzonas;
- idealmente en GeoJSON, GeoPackage o GeoParquet;
- exponerlas desde FastAPI o como ficheros estáticos consumibles por GeoLibre.

Resultado:

- el usuario ve directamente sobre el mapa qué subzona aplica;
- la inferencia GIS deja de ser un extra y pasa a ser una capacidad central.

## Fase 3 — Consultas espaciales híbridas

Objetivo:

- repartir mejor el trabajo entre cliente y servidor.

Acciones:

- dejar en FastAPI la decisión normativa oficial;
- dejar en GeoLibre el análisis exploratorio local:
  - buffers,
  - overlays,
  - joins espaciales,
  - SQL espacial,
  - inspección rápida de capas.

Resultado:

- menos carga en el backend;
- UX mucho más rica;
- mantenimiento más limpio de responsabilidades.

## Fase 4 — Informes cartográficos enriquecidos

Objetivo:

- mejorar la salida documental.

Acciones:

- usar GeoLibre para composición cartográfica;
- mantener FastAPI como generador de datos y resultados;
- unificar plantillas de informe que incluyan:
  - mapa,
  - subzona,
  - parcela,
  - volumen,
  - parámetros aplicados,
  - razones de viabilidad.

Resultado:

- informes visualmente mucho más potentes.

## Fase 5 — Consolidación

Objetivo:

- decidir si el visor actual queda como módulo experto o si parte de sus funciones pasan a otro frontend.

Resultado esperado:

- GeoLibre como interfaz GIS principal;
- visor Three.js como módulo 3D especializado;
- backend FastAPI como motor normativo oficial.

---

## 11. Qué parte de GeoLibre usaría realmente

Con criterio práctico, yo priorizaría estas capacidades de GeoLibre:

## 11.1 Imprescindibles

- visualización de capas vectoriales y ráster;
- soporte WMS/WFS/ArcGIS;
- tabla de atributos;
- simbología temática;
- selección y consulta espacial;
- carga de GeoJSON/GeoParquet/GeoPackage cuando sea viable.

## 11.2 Muy valiosas

- DuckDB-WASM Spatial para análisis local;
- herramientas vectoriales tipo buffer/intersect/clip;
- exportación de resultados;
- composición o impresión cartográfica.

## 11.3 Secundarias al principio

- marketplace/plugins avanzados;
- story maps;
- colaboración en tiempo real;
- sidecar Python de GeoLibre.

### Motivo

Tu proyecto tiene ya bastante backend propio. Si metes todo GeoLibre de golpe, introduces complejidad innecesaria. Lo correcto es explotar primero lo que más valor aporta a tu caso concreto.

---

## 12. Qué haría con los datos

La estrategia correcta no es “sustituir CSV”, sino **complementarlo**.

## 12.1 Mantener CSV para reglas alfanuméricas

CSV sigue siendo ideal para:

- alturas;
- retranqueos;
- ocupación;
- edificabilidad;
- precedencia;
- trazabilidad simple.

## 12.2 Añadir una capa espacial paralela

Añadiría un dataset espacial de subzonas con campos como:

- `municipio`
- `subzona`
- `fuente`
- `version`
- `geom`

Formatos recomendados por orden de adopción:

1. **GeoJSON** para empezar rápido;
2. **GeoPackage** para edición y distribución local;
3. **GeoParquet** para analítica y consumo moderno en GeoLibre/DuckDB.

## 12.3 Regla de diseño importante

La clave de unión entre ambos mundos debe seguir siendo:

- `municipio`
- `subzona`

De ese modo:

- el polígono espacial aporta contexto geográfico;
- el CSV aporta parámetros normativos.

---

## 13. Reparto recomendado de responsabilidades

## 13.1 Lo que debe quedarse en FastAPI

- resolución del plan oficial;
- cálculo de viabilidad;
- cálculo de volumen;
- exportación CityJSON/GLTF/GLB;
- generación de informes normativos;
- trazabilidad de reglas aplicadas;
- QA reproducible;
- tests de regresión.

## 13.2 Lo que debe pasar a GeoLibre o reforzarse con él

- navegación GIS principal;
- capas cartográficas;
- consulta espacial interactiva;
- edición ligera de atributos;
- exploración de datasets;
- composición cartográfica;
- análisis exploratorio local sin tocar el backend.

## 13.3 Lo que puede quedarse dual

- MapLibre básico dentro del visor actual;
- Three.js para visualización 3D de volúmenes;
- GeoLibre para operaciones GIS más amplias.

---

## 14. Riesgos reales de la integración

## 14.1 Riesgo de duplicación lógica

Si duplicas en GeoLibre lo mismo que ya calcula Shapely en backend, tendrás:

- incoherencias;
- resultados distintos;
- y dificultad de auditoría.

### Mitigación

Definir una regla clara:

- **GeoLibre explora**;
- **FastAPI decide oficialmente**.

## 14.2 Riesgo de complejidad frontend

GeoLibre no es una librería trivial. Es una plataforma amplia.

### Mitigación

Integración progresiva y limitada a:

- visor paralelo;
- datasets compatibles;
- flujos concretos de consulta.

## 14.3 Riesgo de documentación engañosa

El mayor riesgo documental ahora mismo sería afirmar que:

- ya existe integración GeoLibre plena;
- o que el gateway 100% gratuito ya está implementado.

Eso no sería fiel al código actual.

### Mitigación

Separar siempre:

- **estado actual**;
- **objetivo recomendado**;
- **plan de migración**.

---

## 15. Plan técnico recomendado de implementación

Si tuviera que priorizar trabajo real en el repositorio, haría esto:

## Prioridad 1 — Refactor de backend

Extraer desde `app/main.py`:

- `services/plan_service.py`
- `services/zoning_service.py`
- `services/export_service.py`
- `services/gis_service.py`
- `services/report_service.py`

### Motivo

Antes de integrar un frontend GIS mayor, conviene estabilizar responsabilidades internas.

## Prioridad 2 — Gateway de modelos gratuito y genérico

Rehacer `src/model_gateway.py` para soportar:

- cliente OpenAI-compatible genérico;
- proveedores por configuración;
- cadena de fallback cloud;
- fallback heurístico local ya existente.

### Motivo

Esto ataca directamente tu requisito de coste cero.

## Prioridad 3 — Dataset espacial de subzonas

Construir una primera capa geoespacial de subzonas por municipio.

### Motivo

Sin capa espacial bien estructurada, GeoLibre no aportará todo su valor.

## Prioridad 4 — Vista GeoLibre integrada

Añadir una nueva vista o ruta de frontend orientada a:

- inspección GIS;
- capas de subzona;
- consulta espacial;
- cruce con inventario de planeamiento.

## Prioridad 5 — Informes híbridos

Unificar salidas:

- datos desde FastAPI;
- composición cartográfica con GeoLibre o con un frontend derivado.

---

## 16. Recomendación final sobre la capa IA gratuita

De todas las opciones gratuitas, la mejor estrategia práctica suele ser:

- **OpenRouter free** como primario,
- **Groq** y **Gemini** como respaldo,
- **modo heurístico actual** como última red de seguridad.

Pero insisto en lo importante:

- eso es una **recomendación de implementación**,
- no una descripción exacta del código actual.

Si lo documentas así, la documentación será técnicamente correcta.

---

## 17. Recomendación final sobre GeoLibre

Sí: **tiene mucho sentido integrar GeoLibre**.

Pero la mejor manera no es “reemplazar el proyecto actual”, sino reorganizarlo así:

- **FastAPI** = motor normativo oficial y backend de cálculo;
- **GeoLibre** = visor GIS principal y exploración espacial avanzada;
- **Three.js actual** = módulo 3D especializado para volumetría y exportación.

Esa arquitectura:

- aprovecha lo ya construido;
- evita rehacer lo que funciona;
- mejora mucho la experiencia cartográfica;
- y mantiene una separación sana entre exploración visual y decisión normativa oficial.

---

## 18. Entregables documentales recomendados

A partir de esta guía, la documentación del proyecto debería quedar dividida en cuatro piezas:

1. **Guía técnica actual** — describe el repositorio tal como está.
2. **Propuesta GeoLibre** — describe la evolución arquitectónica recomendada.
3. **Plan IA 100% gratuita** — describe la migración del gateway de modelos.
4. **Mapa de endpoints** — contrato funcional backend.

En esta iteración, esta guía ya combina 1, 2 y 3 con separación explícita entre presente y futuro.

---

## 19. Conclusión

NORMATIVA GALICIA 3D tiene ya una base técnica útil y bastante bien enfocada:

- backend sólido para MVP;
- modelo urbanístico razonable;
- cálculo geométrico útil;
- exportación 3D con valor real;
- y una base de QA/RAG recuperable.

La mejor evolución posible, manteniendo el proyecto gratuito y útil, es:

1. **refactorizar el backend** para separar responsabilidades;
2. **migrar el gateway IA** a proveedores gratuitos OpenAI-compatible con fallback multi-proveedor;
3. **añadir una capa geoespacial real de subzonas**;
4. **integrar GeoLibre como frontend GIS principal**;
5. **mantener el visor Three.js como módulo 3D especializado**.

Esa hoja de ruta es, en mi opinión, la opción técnicamente más sólida, más honesta con el estado actual del código y con mejor relación entre esfuerzo y mejora funcional.
