# Guía para continuar el desarrollo

## Comandos esenciales

```bash
# Arrancar servidor (puerto 8002)
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002

# Tests completos (269 tests, ~8s)
venv\Scripts\python.exe -m pytest -q --ignore=tests/test_asistente_normativa_rules.py --ignore=tests/test_evaluar_dataset_helpers.py

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

1. **Polígonos reales de subzonas** — HECHO: el WFS de SIOTUGA devuelve la clasificación real por coordenadas (`_fetch_siotuga_classification`). Extrae `edif_ficha`, `sup_ficha`, `uso`, `denom` para zonas SUB/SUNC. Para parámetros normativos detallados (altura, retranqueos, ocupación) habría que:
   - Parsear los PDFs del planeamiento municipal y asociar parámetros a cada polígono
   - O usar el WFS como referencia oficial de clasificación + ordenanzas aportadas por AC8

2. ~~**Más municipios**~~ — HECHO: `_MUNICIPIO_INE` ahora tiene los 313 municipios de Galicia (fuente: INE) con alias. Se corrigieron errores graves: Pontevedra era 36042 (en realidad Ponteareas, correcto 36038), Santiago era 27059 (en realidad Sober, correcto 15078), Porriño era 36041 (en realidad Poio, correcto 36039), y muchos municipios de A Coruña tenían códigos de Pontevedra.

3. **RAG normativo** — indexar los PDFs en `datos/normativa/` y permitir consultas en lenguaje natural

4. ~~**Ampliar `MUNICIPIO_CENTERS`**~~ — HECHO: 337 municipios (principales + aliases). Cubre las 4 provincias.

5. **Panel multi-proyecto** — HECHO: `localStorage` para guardar proyectos con estado (viabilidad/licencia/obra), plazo y navegación.

6. **Módulos completados en esta fase**:
   - `src/habitabilidad_checker.py` — NHV/Decreto 128/2023 (reglas verificadas contra DOG)
   - `src/licencia_docs.py` — plantillas de documentación de licencia
   - `src/solar_analysis.py` — soleamiento por orientación (preliminar)
   - `src/cost_estimator.py` — estimación de costes (inputs del usuario, no inventa precios)
   - `src/ordenanzas_service.py` — estructura para ordenanzas municipales (pendiente datos de AC8)
   - `src/report_service.py` — integra habitabilidad, soleamiento y costes
   - Performance: Overpass timeout 8s→25s, eliminado Shapely por edificio, límite 3000→500

7. **Auto-rellenado de formularios e informes**:
   - Botón "Generar informe de viabilidad" con formulario inline y vista previa de datos
   - Auto-rellena: geometría, altura, huella (turf), municipio, habitabilidad preliminar, datos OSM
   - El servidor rellena desde fuentes oficiales: Catastro, SIOTUGA, SIOSE, soleamiento, sombras
   - Resumen ejecutivo con datos del edificio, Catastro e indicador de disponibilidad por sección
   - Diagnóstico del edificio funciona sin subzona (muestra datos disponibles)
   - Sección de costes muestra "Pendiente" cuando no hay datos (no se omite)
   - Habitabilidad: pre-rellena altura (OSM) y superficie (Catastro o huella)
   - Costes: pre-rellena superficie (huella del edificio) y guarda inputs para el informe
   - Licencia: pre-rellena huella (turf) para el cuadro de superficies

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
