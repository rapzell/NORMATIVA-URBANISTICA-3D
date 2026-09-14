# NORMATIVA GALICIA 3D

Plataforma libre/open de análisis urbanístico para Galicia, orientada a arquitectos y estudios preliminares de viabilidad.

## Qué hace

- **Visor GIS** (GeoLibre/MapLibre) con zonificación oficial del planeamiento vigente (SIOTUGA) y edificios 3D de OpenStreetMap.
- **Cálculos normativos**: altura, ocupación, edificabilidad, retranqueos, viabilidad.
- **Diagnóstico comparativo** entre un edificio existente y los parámetros de su subzona.
- **Datos oficiales** extraídos directamente: Catastro (referencia, superficies, uso, año), SIOSE (ocupación del suelo), SIOTUGA (planeamiento vigente).
- **Enlaces a fuentes oficiales** que abren la página concreta de la parcela (no la homepage).
- **Análisis de sombras** dinámico con slider de hora (solsticio de invierno).
- **Informes profesionales** en HTML/PDF con portada, índice, diagnóstico, sombras, datos oficiales y proveniencia.
- **Exportación IFC/BIM** y GLTF/GLB.
- **Asistente IA** con proveedores gratuitos configurables (OpenRouter, Groq, Gemini, local).

## Instalación rápida

### Requisitos

- Python 3.11+
- Windows (los scripts `.cmd` son para Windows; el backend funciona en cualquier OS)

### Pasos

```bash
# 1. Clonar
git clone https://github.com/rapzell/NORMATIVA-GALICIA-3D
cd NORMATIVA-GALICIA-3D
git checkout feat/demo-silencioso

# 2. Crear entorno virtual
python -m venv venv
venv\Scripts\activate    # Windows
# source venv/bin/activate  # Linux/Mac

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Arrancar el servidor
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002

# 5. Abrir el visor
#    http://127.0.0.1:8002/geolibre/
```

### Script de arranque (Windows)

```powershell
scripts\launch_server.cmd
```

### Configuración IA (opcional)

Crear un archivo `.env` o configurar variables de entorno:

```dotenv
MODEL_PROVIDER=openrouter
MODEL_NAME=meta-llama/llama-3.3-70b-instruct:free
MODEL_API_KEY=tu_clave_de_openrouter
MODEL_FALLBACK_CHAIN=groq,gemini,local
MODEL_PROFILE=balanced
```

Si no se configura, el sistema usa fallback local/heurístico.

## Arquitectura

```
NORMATIVA GALICIA 3D/
├── app/
│   └── main.py                 # Backend FastAPI (endpoints, contexto oficial, WMS proxy)
├── src/
│   ├── zoning_service.py        # Evaluación de viabilidad
│   ├── zoning_assess.py         # Motor de assessment
│   ├── volume_service.py        # Cálculo de envolvente edificable
│   ├── shadow_service.py        # Análisis de sombras multi-hora
│   ├── report_service.py        # Generación de informes HTML/PDF
│   ├── export_service.py        # Exportación IFC/BIM, GLTF/GLB, CityJSON
│   ├── subzones_service.py      # Subzonas espaciales (GeoJSON)
│   ├── plans_service.py         # Proveedor de planes normativos (CSV)
│   ├── model_gateway.py         # Gateway IA multi-proveedor
│   ├── qa_service.py            # Calidad de datos y validaciones
│   └── normativa_extract.py     # Extracción heurística de normativa
├── web/
│   ├── geolibre/
│   │   └── index.html           # Visor GIS principal (MapLibre + Three.js)
│   └── viewer/                  # Visor Three.js (GLB/GLTF)
├── datos/
│   ├── subzonas_piloto.geojson  # Subzonas piloto (parámetros orientativos)
│   ├── inventario_planeamento.csv  # Inventario de planeamiento de Galicia
│   ├── planes_ejemplo_residencial.csv  # Planes de ejemplo
│   └── ...                      # PDFs normativos, anotaciones, etc.
├── tests/                       # 217 tests (pytest)
├── docs/                        # Documentación técnica
└── scripts/                     # Scripts de arranque y utilidades
```

### Flujo de datos

1. **Visor GeoLibre** → selecciona municipio → carga WMS SIOTUGA + edificios OSM
2. **Click en edificio** → backend consulta Catastro + SIOSE + planeamiento en paralelo
3. **Panel** muestra datos catastrales, planeamiento vigente, afecciones, diagnóstico
4. **Enlaces oficiales** abren la parcela concreta en Catastro/SIOTUGA/SIOSE
5. **Informe** genera PDF con portada, índice, diagnóstico, sombras, datos oficiales

## Endpoints principales

| Endpoint | Descripción |
|---|---|
| `GET /geolibre/` | Visor GIS principal |
| `GET /viewer/` | Visor Three.js |
| `GET /official/context` | Contexto oficial (Catastro + SIOSE + planeamiento) |
| `GET /official/siotuga-wms` | URL del WMS del planeamiento vigente |
| `GET /official/siotuga-wms/tile/{z}/{x}/{y}` | Proxy XYZ→WMS de SIOTUGA |
| `GET /zoning/building-diagnostic` | Diagnóstico edificio vs subzona |
| `POST /zoning/assess` | Evaluación de viabilidad |
| `GET /zoning/assess-report` | Informe HTML/PDF |
| `POST /zoning/volume-export` | Exportación 3D (IFC/GLB/CityJSON) |
| `POST /zoning/shadow-analysis` | Análisis de sombras |
| `GET /planeamento/subzonas` | Subzonas espaciales (GeoJSON) |
| `GET /planeamento/inventario` | Inventario de planeamiento municipal |

## Tests

```bash
# Suite completa (217 tests)
pytest -q

# Tests focalizados por área
pytest tests/test_geolibre_view.py -q          # Visor GIS
pytest tests/test_assess_report_branding.py -q  # Informes
pytest tests/test_health_and_proxies.py -q     # Endpoints y proxies
```

## Estado actual y contexto para continuar

### Funcionalidad implementada

- ✅ Zonificación oficial SIOTUGA vía WMS (proxy XYZ→WMS, automático al seleccionar municipio)
- ✅ Edificios 3D de OpenStreetMap (Overpass optimizado, carga rápida)
- ✅ Datos catastrales ampliados (refcat, dirección, superficies, uso, año, valor)
- ✅ Planeamiento vigente destacado (tipo, fecha, estado)
- ✅ Afecciones preliminares SIOSE (6 categorías)
- ✅ Enlaces oficiales directos a la parcela (Catastro coordenadas, SIOTUGA municipio, SIOSE GetFeatureInfo)
- ✅ Diagnóstico comparativo edificio vs subzona (visor + informe)
- ✅ Análisis de sombras con slider de hora (visor + informe)
- ✅ Informe profesional (portada, índice, secciones numeradas, proveniencia)
- ✅ Exportación IFC/BIM, GLTF/GLB, CityJSON
- ✅ Indicador de calidad de datos (alta/media/baja)
- ✅ Validación de coordenadas (bbox Galicia)
- ✅ Caché con TTL (5 min Catastro, 1h WMS SIOTUGA)
- ✅ Consultas paralelas (Catastro + SIOSE)
- ✅ Asistente IA multi-proveedor con fallback local

### Subzonas piloto — importante

Las subzonas en `datos/subzonas_piloto.geojson` son **áreas de demostración** con:
- Parámetros normativos orientativos (inspirados en valores típicos)
- Geometrías rectangulares simples que **no coinciden con las zonas reales**

Se usan para los cálculos normativos del backend, pero **ya no se muestran en el mapa**. La zonificación visible en el visor viene del WMS oficial de SIOTUGA.

### Lo que queda por hacer (roadmap)

1. **Datos de mercado/valoración** — TAKSON o valores de referencia catastral
2. **Comparativa de sombras antes/después** — sombra del edificio existente vs envolvente propuesta
3. **Polígonos reales de subzonas** — extraer del WMS/WFS de SIOTUGA y asociar parámetros normativos reales
4. **Más municipios en el mapeo INE** — ampliar `_MUNICIPIO_INE` en `app/main.py`
5. **RAG sobre normativa** — indexar PDFs normativos y permitir consultas en lenguaje natural
6. **Integración GeoLibre.app** — embeber el visor de GeoLibre como alternativa a MapLibre

### Decisiones técnicas clave

- **FastAPI** es el backend autoritativo para todos los cálculos normativos y de viabilidad.
- **GeoLibre/MapLibre** es la interfaz GIS principal.
- **Three.js** se usa para visualización 3D especializada y GLTF/GLB.
- **Todo es gratuito/open** — no hay dependencias de pago.
- **Fallbacks** — si un servicio externo no responde, se usa heurística local y se reporta honestamente.
- **No se inventan datos** — si Catastro/SIOSE/SIOTUGA no responden, se indica calidad "baja".

### Servicios externos utilizados

| Servicio | Uso | URL |
|---|---|---|
| Catastro (OVC) | Datos catastrales por coordenadas | `sedecatastro.gob.es` |
| SIOTUGA | Planeamiento vigente + WMS zonificación | `siotuga.xunta.gal` |
| SIOSE (IDEE) | Ocupación del suelo | `servicios.idee.es` |
| OpenStreetMap | Edificios 3D (Overpass API) | `overpass-api.org` |
| OpenRouter/Groq/Gemini | IA gratuita (opcional) | configurable |

## Documentación adicional

- `docs/ARQUITECTURA_SERVICIOS.md` — arquitectura detallada
- `docs/GUIA_TECNICA_FUNCIONAMIENTO.md` — guía técnica
- `docs/PROPUESTA_INTEGRACION_GEOLIBRE.md` — propuesta GeoLibre
- `docs/ROADMAP_GEOLIBRE_Y_IA_GRATUITA.md` — roadmap

## Licencia

Proyecto libre/open para análisis urbanístico de Galicia.
