# Guía para continuar el desarrollo

## Comandos esenciales

```bash
# Arrancar servidor (puerto 8002)
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002

# Tests completos (217 tests, ~15s)
venv\Scripts\python.exe -m pytest -q

# Tests focalizados
venv\Scripts\python.exe -m pytest tests/test_geolibre_view.py -q
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
| Gateway IA | `src/model_gateway.py` |

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

### Enlaces oficiales (`official_links` en el contexto)

Se construyen en `_build_official_context` y se renderizan en:
- `web/geolibre/index.html` → `renderOfficialContext()`
- `src/report_service.py` → sección "Fuentes oficiales consultadas"

Formato de cada link: `{name, url, label}`

### Subzonas piloto

Las subzonas en `datos/subzonas_piloto.geojson` tienen:
- Parámetros normativos orientativos (altura, ocupación, edificabilidad, retranqueo)
- Geometrías rectangulares inventadas (no reales)

**No se muestran en el mapa** (se comentó `renderSubzones3D` en `goToMunicipio`).
Se usan solo para los cálculos del backend (diagnóstico, viabilidad).

### Tests

- Los tests usan `monkeypatch` para mockear servicios externos
- `_build_official_context` se mockea con `monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {...})`
- `find_subzone_by_name` se mockea en `src.subzones_service` (no en `app.main`)

## Lo que NO hay que hacer

- No subir API keys al repo (están en `.gitignore`: `docs/apikey*`)
- No inventar datos cuando los servicios externos no responden
- No usar dependencias de pago
- No modificar políticas de seguridad/compliance del repo
- No añadir comentarios innecesarios al código (el proyecto los minimiza)

## Próximos pasos recomendados

1. **Polígonos reales de subzonas** — el WMS de SIOTUGA devuelve la clasificación pero no es consultable por parcela (GetFeatureInfo devuelve vacío). Para tener parámetros normativos reales por zona, habría que:
   - Descargar los polígonos de clasificación del WFS de SIOTUGA (si está disponible)
   - O parsear los PDFs del planeamiento y asociar parámetros a cada polígono
   - O usar el WMS solo como referencia visual y mantener los parámetros piloto para cálculos

2. **Más municipios** — ampliar `_MUNICIPIO_INE` en `app/main.py` con los 313 municipios de Galicia

3. **RAG normativo** — indexar los PDFs en `datos/normativa/` y permitir consultas en lenguaje natural
