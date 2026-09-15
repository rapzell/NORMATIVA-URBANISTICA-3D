from __future__ import annotations
from pydantic import BaseModel

from src.normativa_extract import extract_normativa_fields
from src.plans_service import get_plan_params_dynamic, get_plan_provider_kind
from src.qa_service import build_qa_fallback_response, build_qa_verbose_fallback_response
from src.zoning_service import (
    arcgis_feature_query,
    arcgis_identify_extract,
    build_wms_getfeatureinfo_url,
    centroid_lonlat_from_geojson,
    extract_subzone_from_wms_json,
    infer_subzone,
    lonlat_to_mercator,
    mercator_to_lonlat,
    wms_config_for_municipio,
)
from src.zoning_assess import ZoningAssessmentError, evaluate_zoning_assessment
from src.volume_service import infer_limiting_factor
from src.export_service import (
    build_volume_export_feature,
    extrude_polygon_to_cityjson as _extrude_polygon_to_cityjson,
    extrude_polygon_to_gltf as _extrude_polygon_to_gltf,
    extrude_polygon_to_ifc as _extrude_polygon_to_ifc,
    gltf_to_glb_bytes as _gltf_to_glb_bytes,
    is_exhausted_feature,
    normalize_volume_export_format,
)
from src.report_service import render_assess_report_html as _render_assess_report_html
from src.shadow_service import shadow_analysis, shadow_analysis_multi_hour, solar_position
from src.subzones_service import (
    find_subzone_for_point,
    get_osm_buildings_geojson,
    get_subzones,
    list_municipios_with_subzones,
)

# ------------------------------
# Endpoint de depuración de planes
# ------------------------------
class DebugPlanResponse(BaseModel):
    municipio: str | None
    subzona: str | None
    provider: str
    params: dict

import os
from typing import Optional
import mimetypes
import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException, Response, Body
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import BaseModel
from collections import OrderedDict
import time
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
import json as _json
import csv

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

API_VERSION = "0.2.1"

# Lifespan para inicialización (autocarga de plan por defecto si existe datos/plan_uploaded.csv)
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # No alterar entorno en tests: dejar que pytest controle PLAN_PROVIDER
        if not os.getenv('PYTEST_CURRENT_TEST'):
            prov = os.getenv('PLAN_PROVIDER', '').strip().lower()
            if not prov:
                merged_path = os.path.join('datos', 'plan_merged.csv')
                uploaded_path = os.path.join('datos', 'plan_uploaded.csv')
                app_uploaded_path = os.path.join('app', 'data', 'plan_uploaded.csv')
                pick = None
                if os.path.isfile(merged_path):
                    pick = merged_path
                elif os.path.isfile(uploaded_path):
                    pick = uploaded_path
                elif os.path.isfile(app_uploaded_path):
                    pick = app_uploaded_path
                if pick:
                    os.environ['PLAN_PROVIDER'] = 'csv'
                    os.environ['PLAN_CSV_PATH'] = pick
    except Exception:
        # No interrumpir el arranque por esto
        pass
    yield

# Ensure correct MIME types for static assets (JS/WASM) on all platforms
try:
    mimetypes.add_type('text/javascript', '.js')
except Exception:
    pass
try:
    mimetypes.add_type('application/wasm', '.wasm')
except Exception:
    pass

app = FastAPI(title="Asistente Normativa Galicia API", version=API_VERSION, lifespan=lifespan)

# Servir visor Three.js como estático para evitar CORS (same-origin)
try:
    app.mount(
        "/viewer",
        StaticFiles(directory="web/examples/threejs-viewer", html=True),
        name="viewer",
    )
except Exception:
    # Si el directorio no existe en despliegues sin assets, ignora
    pass

# Vista GIS paralela con GeoLibre (MapLibre GL JS)
try:
    app.mount(
        "/geolibre",
        StaticFiles(directory="web/geolibre", html=True),
        name="geolibre",
    )
except Exception:
    pass

# Servir carpeta web completa para acceder a otros ejemplos/activos
try:
    app.mount(
        "/web",
        StaticFiles(directory="web", html=False),
        name="web",
    )
except Exception:
    pass

# Servir datos de ejemplo (GeoJSON/CSV) para el visor
try:
    app.mount(
        "/data",
        StaticFiles(directory="datos", html=False),
        name="data",
    )
except Exception:
    pass

# Endpoint de depuración para parámetros del plan
@app.get("/debug/plan", response_model=DebugPlanResponse)
def debug_plan(municipio: str | None = None, subzona: str | None = None):
    try:
        # Determinar proveedor actual y obtener params
        kind = get_plan_provider_kind()
        p = get_plan_params_dynamic(municipio or '', subzona or None)
        d = {
            'municipio': getattr(p, 'municipio', None),
            'subzona': getattr(p, 'subzona', None),
            'altura_maxima_m': getattr(p, 'altura_maxima_m', None),
            'retranqueo_min_m': getattr(p, 'retranqueo_min_m', None),
            'setback_front_m': getattr(p, 'setback_front_m', None),
            'setback_side_m': getattr(p, 'setback_side_m', None),
            'setback_back_m': getattr(p, 'setback_back_m', None),
            'front_direction_default': getattr(p, 'front_direction_default', None),
            'ocupacion_max': getattr(p, 'ocupacion_max', None),
            'edificabilidad_max_m2_m2': getattr(p, 'edificabilidad_max_m2_m2', None),
            'source': getattr(p, 'source', None),
        }
        return DebugPlanResponse(municipio=municipio, subzona=subzona, provider=kind, params=d)
    except Exception as e:
        logging.getLogger(__name__).exception("/debug/plan failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------
# Extracción básica de normativa desde texto (regex heurístico)
# ------------------------------
class NormExtractRequest(BaseModel):
    text: str
    municipio: Optional[str] = None

@app.post("/normativa/extract")
def normativa_extract(req: NormExtractRequest):
    """Extrae campos básicos de un texto libre. No lanza excepción: devuelve dict parcial."""
    try:
        return extract_normativa_fields(req.text, req.municipio)
    except Exception as e:
        return {
            "municipio": (req.municipio or None),
            "uso_suelo": None,
            "altura_maxima_m": None,
            "retranqueo_min_m": None,
            "referencias": [str(e)],
        }

# Lazy globals for retrieval resources
_RESOURCES = {
    'loaded': False,
    'chunks': None,
    'index': None,
    'bi_encoder': None,
    'cross_encoder': None,
    'llm': None,
}

# Basic logging configuration (idempotent)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

# Optional rotating file handler
log_file = os.getenv('LOG_FILE')
if log_file:
    try:
        max_bytes = int(os.getenv('LOG_MAX_BYTES', str(5 * 1024 * 1024)))
    except Exception:
        max_bytes = 5 * 1024 * 1024
    try:
        backup_count = int(os.getenv('LOG_BACKUP_COUNT', '3'))
    except Exception:
        backup_count = 3
    # Prevent duplicate file handler for same path
    root_logger = logging.getLogger()
    exists = any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == log_file for h in root_logger.handlers)
    if not exists:
        fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        root_logger.addHandler(fh)
    # Optional rotating file handler
    log_file = os.getenv('LOG_FILE')
    if log_file:
        try:
            max_bytes = int(os.getenv('LOG_MAX_BYTES', str(5 * 1024 * 1024)))
        except Exception:
            max_bytes = 5 * 1024 * 1024
        try:
            backup_count = int(os.getenv('LOG_BACKUP_COUNT', '3'))
        except Exception:
            backup_count = 3
        # Prevent duplicate file handler for same path
        root_logger = logging.getLogger()
        exists = any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == log_file for h in root_logger.handlers)
        if not exists:
            fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
            root_logger.addHandler(fh)

# Volume logger level can be overridden by VOLUME_DEBUG
_vol_debug = str(os.getenv('VOLUME_DEBUG', '0')).lower() in ('1', 'true', 'yes')
if _vol_debug:
    logging.getLogger('volume').setLevel(logging.DEBUG)

# Diagnostics verbosity for responses: 'full' | 'min' | 'none'
_diag_verbosity = os.getenv('DIAGNOSTICS_VERBOSITY', 'full').strip().lower()
if _diag_verbosity not in ('full', 'min', 'none'):
    _diag_verbosity = 'full'

def _resolve_diag_verbosity(override: Optional[str]) -> str:
    verb = (override or '').strip().lower() if isinstance(override, str) else None
    if verb not in ('full', 'min', 'none'):
        verb = _diag_verbosity
    return verb  # guaranteed valid

def _filter_volume_diagnostics(feature: dict, verbosity_override: Optional[str] = None) -> dict:
    if not feature or not isinstance(feature, dict):
        return feature
    verb = _resolve_diag_verbosity(verbosity_override)
    if verb == 'full':
        return feature
    props = feature.get('properties') or {}
    if not isinstance(props, dict):
        return feature
    diag_all = [
        'front_detected_side',
        'front_direction_source',
        'street_axis_used',
        'street_axis_min_distance_m',
        'street_axis_side_distances',
        'front_selection_rationale',
        'street_axis_ignored_reason',
        'polygon_type',
        'directional_applicability',
        'directional_not_applied_reason',
    ]

class ApplyPlanCSVTextRequest(BaseModel):
    csv_text: str


@app.post("/admin/apply-plan-csv-text")
async def apply_plan_csv_text(req: ApplyPlanCSVTextRequest):
    """Valida y aplica un CSV de plan municipal recibido como texto.
    - Escribe el CSV a datos/plan_uploaded.csv
    - Valida con CSVPlanProvider
    - Fija PLAN_PROVIDER=csv y PLAN_CSV_PATH
    - Limpia caché de validación
    """
    import os as _os
    import io as _io
    import csv as _csv
    if not req.csv_text or not isinstance(req.csv_text, str):
        raise HTTPException(status_code=400, detail="csv_text requerido")
    # Validación básica de cabeceras
    try:
        f = _io.StringIO(req.csv_text)
        reader = _csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        if 'municipio' not in headers:
            raise ValueError("CSV faltan columnas requeridas: municipio")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV inválido: {e}")
    # Guardar en datos/plan_uploaded.csv
    target_dir = 'datos'
    try:
        _os.makedirs(target_dir, exist_ok=True)
    except Exception:
        pass
    target_path = _os.path.join(target_dir, 'plan_uploaded.csv')
    try:
        with open(target_path, 'w', encoding='utf-8', newline='') as f2:
            f2.write(req.csv_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo escribir CSV: {e}")
    # Validar creando provider
    try:
        from src.planes.csv_provider import CSVPlanProvider
        prov = CSVPlanProvider(target_path)
        rows = len(prov.rows)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV no válido: {e}")
    # Aplicar
    try:
        _os.environ['PLAN_PROVIDER'] = 'csv'
        _os.environ['PLAN_CSV_PATH'] = target_path
        try:
            _validate_cache.clear()
        except Exception:
            pass
        # Limpiar cache del proveedor de planes para que recargue el nuevo CSV
        try:
            from src.plans_service import _PLAN_PROVIDER_CACHE
            _PLAN_PROVIDER_CACHE.update({"provider": None, "kind": None})
        except Exception:
            pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo aplicar configuración: {e}")
    return {"ok": True, "provider": "csv", "applied_path": target_path, "rows": rows}
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException, Header, Response, Body
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import BaseModel
from collections import OrderedDict

# Project imports
try:
    from src.asistente_normativa import cargar_recursos, buscar_fragmentos, generar_respuesta
except Exception:
    def cargar_recursos():
        raise RuntimeError('rag_unavailable')
    def buscar_fragmentos(*args, **kwargs):
        return []
    def generar_respuesta(pregunta, frags, llm=None):
        return (
            "Servicio en modo básico sin RAG. Indica municipio y subzona para una respuesta precisa, "
            "o usa el botón 'IA diag' en el visor."
        )
from src.rules_engine import (
    analizar_zonificacion,
    ZoneInput,
    geometry_checks,
    geometry_checks_with_crs,
    GeometryReport,
)
from src.volume import compute_building_envelope, VolumeParams
from src.text_extractor import extract_from_text
from urllib.request import urlopen
from urllib.parse import urlencode


API_VERSION = "0.2.1"

# Ensure correct MIME types for static assets (JS/WASM) on all platforms
try:
    mimetypes.add_type('text/javascript', '.js')
except Exception:
    pass
try:
    mimetypes.add_type('application/wasm', '.wasm')
except Exception:
    pass

# In-memory cache for /zoning/validate-plan-csv by file path/signature
def _read_validate_cache_max() -> int:
    try:
        v = int(os.getenv('VALIDATE_CACHE_MAX', '128'))
        if v < 1:
            return 1
        if v > 4096:
            return 4096
        return v
    except Exception:
        return 128

_VALIDATE_CACHE_MAX = _read_validate_cache_max()
_validate_cache: "OrderedDict[str, tuple[tuple[int, int], dict]]" = OrderedDict()

def _file_signature(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return (getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)), st.st_size)

def _validate_cache_get(path: str) -> Optional[dict]:
    try:
        sig = _file_signature(path)
    except FileNotFoundError:
        return None
    entry = _validate_cache.get(path)
    if entry and entry[0] == sig:
        # Move to end (LRU)
        _validate_cache.move_to_end(path)
        # Return a shallow copy and mark cache hit
        res = dict(entry[1])
        res["cache_hit"] = True
        return res
    return None


# ArcGIS REST Identify fallback (usar con moderación)

def _validate_cache_set(path: str, result: dict) -> None:
    try:
        sig = _file_signature(path)
    except FileNotFoundError:
        return
    # Ensure space
    if len(_validate_cache) >= _VALIDATE_CACHE_MAX:
        _validate_cache.popitem(last=False)
    # Store without cache flag
    to_store = dict(result)
    to_store.pop("cache_hit", None)
    _validate_cache[path] = (sig, to_store)
    _validate_cache.move_to_end(path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Allow disabling heavy loads for unit tests
    if os.getenv('API_LOAD_RESOURCES', '1') == '1':
        try:
            chunks, index, bi_encoder, cross_encoder, llm = cargar_recursos()
            _RESOURCES.update({
                'loaded': True,
                'chunks': chunks,
                'index': index,
                'bi_encoder': bi_encoder,
                'cross_encoder': cross_encoder,
                'llm': llm,
            })
        except Exception as e:
            print("[API] Error loading resources:", e)
    yield

    # (eliminado duplicado de app y mounts)

# Lazy globals for retrieval resources
_RESOURCES = {
    'loaded': False,
    'chunks': None,
    'index': None,
    'bi_encoder': None,
    'cross_encoder': None,
    'llm': None,
}

# Basic logging configuration (idempotent)
if not logging.getLogger().handlers:
    level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s'
    )
    # Optional rotating file handler
    log_file = os.getenv('LOG_FILE')
    if log_file:
        try:
            max_bytes = int(os.getenv('LOG_MAX_BYTES', str(5 * 1024 * 1024)))
        except Exception:
            max_bytes = 5 * 1024 * 1024
        try:
            backup_count = int(os.getenv('LOG_BACKUP_COUNT', '3'))
        except Exception:
            backup_count = 3
        # Prevent duplicate file handler for same path
        root_logger = logging.getLogger()
        exists = any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == log_file for h in root_logger.handlers)
        if not exists:
            fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
            root_logger.addHandler(fh)

# Volume logger level can be overridden by VOLUME_DEBUG
_vol_debug = str(os.getenv('VOLUME_DEBUG', '0')).lower() in ('1', 'true', 'yes')
if _vol_debug:
    logging.getLogger('volume').setLevel(logging.DEBUG)

# Diagnostics verbosity for responses: 'full' | 'min' | 'none'
_diag_verbosity = os.getenv('DIAGNOSTICS_VERBOSITY', 'full').strip().lower()
if _diag_verbosity not in ('full', 'min', 'none'):
    _diag_verbosity = 'full'

def _resolve_diag_verbosity(override: Optional[str]) -> str:
    verb = (override or '').strip().lower() if isinstance(override, str) else None
    if verb not in ('full', 'min', 'none'):
        verb = _diag_verbosity
    return verb  # guaranteed valid

def _filter_volume_diagnostics(feature: dict, verbosity_override: Optional[str] = None) -> dict:
    if not feature or not isinstance(feature, dict):
        return feature
    verb = _resolve_diag_verbosity(verbosity_override)
    if verb == 'full':
        return feature
    props = feature.get('properties') or {}
    if not isinstance(props, dict):
        return feature
    diag_all = [
        'front_detected_side',
        'front_direction_source',
        'street_axis_used',
        'street_axis_min_distance_m',
        'street_axis_side_distances',
        'front_selection_rationale',
        'street_axis_ignored_reason',
        'polygon_type',
        'directional_applicability',
        'directional_not_applied_reason',
    ]
    if verb == 'none':
        for k in diag_all:
            if k in props:
                props.pop(k, None)
    elif verb == 'min':
        keep = {'front_detected_side', 'front_direction_source', 'polygon_type'}
        for k in diag_all:
            if k not in keep and k in props:
                props.pop(k, None)
    feature['properties'] = props
    return feature

# Optional Prometheus metrics
_metrics_env_enabled = str(os.getenv('METRICS_ENABLED', '0')).lower() in ('1', 'true', 'yes')
_metrics_ready = False
_REGISTRY = None
_REQ_COUNT = None
_REQ_LATENCY = None
_ERR_COUNT = None
_RESP_SIZE = None
_RESP_SIZE_BUCKETS: list[float] | None = None
_CSV_CACHE_HITS = None
_CSV_CACHE_MISSES = None
_EXP_SIZE = None
_EXP_COUNT = None
def _parse_buckets_from_env(var_name: str, default: list[int]) -> list[float]:
    raw = os.getenv(var_name, '')
    if not raw:
        return [float(b) for b in default]
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    vals: list[float] = []
    for p in parts:
        try:
            v = float(p)
            if v > 0:
                vals.append(v)
        except Exception:
            continue
    if not vals:
        return [float(b) for b in default]
    vals = sorted(set(vals))
    return vals

def _ensure_metrics_initialized():
    global _metrics_ready, _REGISTRY, _REQ_COUNT, _REQ_LATENCY, _ERR_COUNT, _RESP_SIZE, _CSV_CACHE_HITS, _CSV_CACHE_MISSES, _RESP_SIZE_BUCKETS, _EXP_SIZE, _EXP_COUNT
    if _metrics_ready:
        return
    # Lazy import to avoid hard dependency during tests unless enabled
    from prometheus_client import Counter, Histogram, CollectorRegistry
    import time  # noqa: F401 (used in middleware)
    _REGISTRY = CollectorRegistry()
    _REQ_COUNT = Counter(
        'api_requests_total', 'Total API requests', ['method', 'route', 'status'], registry=_REGISTRY
    )
    _REQ_LATENCY = Histogram(
        'api_request_latency_seconds', 'Request latency in seconds', ['method', 'route'], registry=_REGISTRY
    )
    _ERR_COUNT = Counter(
        'api_errors_total', 'Total API errors', ['method', 'route', 'status', 'error_type'], registry=_REGISTRY
    )
    # Buckets por defecto (bytes): 0.5KB, 1KB, 2KB, 4KB, 8KB, 16KB, 32KB, 64KB, 128KB, 256KB
    _RESP_SIZE_BUCKETS = _parse_buckets_from_env('RESPONSE_SIZE_BUCKETS', [512,1024,2048,4096,8192,16384,32768,65536,131072,262144])
    _RESP_SIZE = Histogram(
        'api_response_size_bytes', 'Response payload size in bytes', ['method', 'route', 'status'],
        buckets=_RESP_SIZE_BUCKETS, registry=_REGISTRY
    )
    _CSV_CACHE_HITS = Counter(
        'api_validate_csv_cache_hits_total', 'Total cache hits in validate-plan-csv', registry=_REGISTRY
    )
    _CSV_CACHE_MISSES = Counter(
        'api_validate_csv_cache_misses_total', 'Total cache misses in validate-plan-csv', registry=_REGISTRY
    )
    # Métricas específicas de exportación 3D por formato
    _EXP_SIZE = Histogram(
        'api_volume_export_size_bytes', '3D export payload size in bytes', ['format', 'status'],
        buckets=_RESP_SIZE_BUCKETS, registry=_REGISTRY
    )
    _EXP_COUNT = Counter(
        'api_volume_export_requests_total', 'Total 3D export requests by format and status', ['format', 'status'],
        registry=_REGISTRY
    )
    _metrics_ready = True

if _metrics_env_enabled:
    try:
        # Initialize and add middleware at import time if enabled
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # type: ignore
        import time
        _ensure_metrics_initialized()

        @app.middleware("http")
        async def metrics_middleware(request, call_next):
            start = time.perf_counter()
            response = await call_next(request)
            # Prefer FastAPI route template (e.g., /items/{id}) to avoid cardinality explosion
            try:
                route_obj = request.scope.get('route') if isinstance(request.scope, dict) else None
                route = route_obj.path if route_obj and hasattr(route_obj, 'path') else request.url.path
            except Exception:
                route = request.url.path
            method = request.method
            status = response.status_code
            try:
                _REQ_COUNT.labels(method=method, route=route, status=str(status)).inc()
                _REQ_LATENCY.labels(method=method, route=route).observe(time.perf_counter() - start)
                # Observe response size if content-length header is present
                try:
                    cl = response.headers.get('content-length')
                    if cl is not None:
                        size = int(cl)
                        _RESP_SIZE.labels(method=method, route=route, status=str(status)).observe(size)
                except Exception:
                    pass
                if status >= 400:
                    if status >= 500:
                        etype = 'server_error'
                    elif status == 400:
                        etype = 'bad_request'
                    elif status == 404:
                        etype = 'not_found'
                    else:
                        etype = 'client_error'
                    _ERR_COUNT.labels(method=method, route=route, status=str(status), error_type=etype).inc()
            except Exception:
                pass
            return response
    except Exception:
        # Ignore import-time metrics errors; endpoint will handle
        pass


@app.get("/admin/plan-download")
async def plan_download():
    provider = os.getenv('PLAN_PROVIDER', 'mock').strip().lower()
    if provider != 'csv':
        raise HTTPException(status_code=400, detail="PLAN_PROVIDER no es 'csv'. Nada que descargar.")
    path = os.getenv('PLAN_CSV_PATH')
    if not path:
        raise HTTPException(status_code=400, detail="PLAN_CSV_PATH no definido.")
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"CSV no encontrado: {path}")
    # Sugerir nombre de archivo
    fname = os.path.basename(path) or 'plan.csv'
    headers = {"Content-Disposition": f"attachment; filename={fname}"}
    return Response(content=data, media_type='text/csv; charset=utf-8', headers=headers)


class AdminReloadPlanRequest(BaseModel):
    path: Optional[str] = None


@app.post("/admin/reload-plan")
async def admin_reload_plan(
    req: AdminReloadPlanRequest = Body(...),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """Recarga/valida el planeamiento CSV.
    - Requiere PLAN_PROVIDER=csv.
    - Si se aporta `path`, actualiza PLAN_CSV_PATH tras validarlo.
    - Limpia el caché de validación de CSV.
    """
    provider = os.getenv('PLAN_PROVIDER', 'mock').strip().lower()
    if provider != 'csv':
        raise HTTPException(status_code=400, detail="PLAN_PROVIDER no es 'csv'. Nada que recargar.")
    new_path = (req.path or '').strip()
    path = new_path or os.getenv('PLAN_CSV_PATH')
    if not path:
        raise HTTPException(status_code=400, detail="PLAN_CSV_PATH no definido y no se aportó 'path'.")
    try:
        from src.planes.csv_provider import CSVPlanProvider
        prov = CSVPlanProvider(path)
        rows_count = len(prov.rows)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Si se aportó path nuevo y es válido, actualizar env
    if new_path:
        os.environ['PLAN_CSV_PATH'] = path
    # Limpiar caché de validación
    try:
        _validate_cache.clear()
    except Exception:
        pass
    # Limpiar cache del proveedor de planes para que recargue el nuevo CSV
    try:
        from src.plans_service import _PLAN_PROVIDER_CACHE
        _PLAN_PROVIDER_CACHE.update({"provider": None, "kind": None})
    except Exception:
        pass
    return {"ok": True, "provider": provider, "applied_path": path, "rows": rows_count}

# --- Redirecciones de conveniencia ---
@app.get("/")
async def root_redirect():
    # Ir directo al visor principal (GeoLibre)
    return RedirectResponse(url="/geolibre")

@app.get("/web")
async def web_redirect():
    # Ir al ejemplo del visor dentro de /web
    return RedirectResponse(url="/web/examples/threejs-viewer/index.html")

@app.get("/metrics")
async def metrics_endpoint():
    # Serve metrics only if enabled
    if str(os.getenv('METRICS_ENABLED', '0')).lower() not in ('1', 'true', 'yes'):
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # type: ignore
    except Exception:
        # Fallback exposition to satisfy scraping even if dependency is missing
        fallback = (
            "# HELP api_requests_total Total API requests\n"
            "# TYPE api_requests_total counter\n"
            "# HELP api_request_latency_seconds Request latency in seconds\n"
            "# TYPE api_request_latency_seconds histogram\n"
        )
        return Response(content=fallback, media_type='text/plain; version=0.0.4; charset=utf-8')
    if not _metrics_ready:
        try:
            _ensure_metrics_initialized()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Metrics init failed: {e}")
    data = generate_latest(_REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/version")
async def version():
    return {"version": API_VERSION}


# --- Categorización explicable desde texto (versión inicial) ---
class CategorizeRequest(BaseModel):
    municipio: Optional[str] = None
    text: str


@app.post("/zoning/categorize")
async def zoning_categorize(req: CategorizeRequest):
    if not req.text or not isinstance(req.text, str):
        raise HTTPException(status_code=400, detail="text requerido")
    try:
        extracted = extract_from_text(req.text) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"error extrayendo: {e}")
    return {
        "ok": True,
        "municipio": (req.municipio or '').strip(),
        "extracted": extracted,
    }

@app.get("/health", operation_id="health_check")
async def health_check():
    try:
        now = int(time.time())
    except Exception:
        now = 0
    return {"ok": True, "status": "ok", "version": API_VERSION, "time": now}


@app.get("/admin/plan-summary")
async def plan_summary():
    provider = os.getenv('PLAN_PROVIDER', 'mock').strip().lower()
    if provider != 'csv':
        raise HTTPException(status_code=400, detail="PLAN_PROVIDER no es 'csv'. Nada que resumir.")
    path = os.getenv('PLAN_CSV_PATH')
    if not path:
        raise HTTPException(status_code=400, detail="PLAN_CSV_PATH no definido.")
    try:
        from src.planes.csv_provider import CSVPlanProvider
        prov = CSVPlanProvider(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error cargando CSV: {e}")
    # Construir resumen mínimo
    out = []
    for r in prov.rows:
        out.append({
            'municipio': (r.get('municipio') or '').strip(),
            'subzona': (r.get('subzona') or '').strip(),
            'altura_maxima_m': r.get('altura_maxima_m') or '',
            'retranqueo_min_m': r.get('retranqueo_min_m') or '',
        })
    return { 'provider': 'csv', 'path': path, 'rows': len(out), 'items': out }


# (Startup handler migrado a lifespan)


# --- Proxy SIOSE (WFS IDEE) con caché en memoria por BBOX ---
SIOSE_WFS_URL = "https://servicios.idee.es/wfs-inspire/ocupacion-suelo"
_SIOSE_CACHE = {}

def _siose_cache_get(key, max_age: int):
    try:
        ts, data = _SIOSE_CACHE.get(key) or (0.0, None)
        if data is None:
            return None
        import time as _t
        if (_t.time() - ts) <= max_age:
            return data
    except Exception:
        pass
    return None

def _siose_cache_set(key, data):
    try:
        import time as _t
        _SIOSE_CACHE[key] = (_t.time(), data)
    except Exception:
        pass

_SIOSE_CLASS_LABELS = {
    '110': 'Tejido urbano',
    '111': 'Centro urbano',
    '112': 'Área de expansión urbana',
    '113': 'Tejido urbano discontinuo',
    '114': 'Zonas verdes urbanas',
    '140': 'Servicios públicos',
    '161': 'Redes viarias y ferroviarias',
    '330': 'Matorral',
    '354': 'Suelo desnudo',
    '514': 'Masa de agua artificial',
}


def _parse_siose_gml(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    ns = {
        'wfs': 'http://www.opengis.net/wfs/2.0',
        'gml': 'http://www.opengis.net/gml/3.2',
        'lcv': 'http://inspire.ec.europa.eu/schemas/lcv/4.0',
        'xlink': 'http://www.w3.org/1999/xlink',
    }
    features = []
    for member in root.findall('.//wfs:member', ns):
        unit = member.find('lcv:LandCoverUnit', ns)
        if unit is None:
            continue
        class_el = unit.find('./lcv:landCoverObservation/lcv:LandCoverObservation/lcv:class', ns)
        href = class_el.get(f'{{{ns["xlink"]}}}href', '') if class_el is not None else ''
        code = href.rstrip('/').rsplit('/', 1)[-1] if href else ''
        polygons = []
        for patch in unit.findall('.//gml:PolygonPatch', ns):
            rings = []
            exterior = patch.find('./gml:exterior//gml:posList', ns)
            ring_nodes = ([exterior] if exterior is not None else []) + patch.findall('./gml:interior//gml:posList', ns)
            for pos_list in ring_nodes:
                values = [float(v) for v in (pos_list.text or '').split()]
                ring = [[values[i], values[i + 1]] for i in range(0, len(values) - 1, 2)]
                if len(ring) >= 4:
                    rings.append(ring)
            if rings:
                polygons.append(rings)
        if not polygons:
            continue
        geometry = {'type': 'Polygon', 'coordinates': polygons[0]} if len(polygons) == 1 else {'type': 'MultiPolygon', 'coordinates': polygons}
        features.append({
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'code': code,
                'label': _SIOSE_CLASS_LABELS.get(code, f'Clase CODIIGE {code}' if code else 'Sin clasificar'),
                'source': 'SIOSE Alta Resolución 2017 (IDEE)',
            },
        })
    return {'type': 'FeatureCollection', 'features': features}


@app.get("/proxy/siose")
async def proxy_siose(bbox: str, typeNames: str = "lcv:LandCoverUnit", srsName: str = "EPSG:4326", version: str = "2.0.0", max_age: int = 15):
    try:
        bb = bbox.strip()
        if bb.count(',') == 3 and srsName:
            bb = f"{bb},{srsName}"
        cache_key = (bb, typeNames, srsName, version)
        cached = _siose_cache_get(cache_key, max_age=max_age)
        if cached is not None:
            return cached
        params = {
            "service": "WFS",
            "request": "GetFeature",
            "version": version,
            "typeNames": typeNames,
            "srsName": srsName,
            "bbox": bb,
            "outputFormat": 'application/gml+xml; version=3.2',
            "count": 500,
        }
        from urllib.parse import urlencode as _urlencode
        from urllib.request import urlopen as _urlopen, Request as _Request
        from urllib.error import HTTPError as _HTTPError, URLError as _URLError
        url = f"{SIOSE_WFS_URL}?{_urlencode(params)}"
        req = _Request(url, headers={"User-Agent": "NormativaGalicia/1.0"})
        try:
            with _urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    # En teoría no llegamos aquí en 4xx (lanzan HTTPError), pero lo dejamos por robustez
                    if 400 <= int(getattr(resp, 'status', 0)) < 500:
                        empty = {"type": "FeatureCollection", "features": []}
                        _siose_cache_set(cache_key, empty)
                        return empty
                    raise HTTPException(status_code=resp.status, detail=f"SIOSE status {resp.status}")
                raw = resp.read()
                data = _parse_siose_gml(raw)
        except _HTTPError as e:
            # Amortiguar 4xx: devolver colección vacía y 200
            try:
                code = int(getattr(e, 'code', 0))
            except Exception:
                code = 0
            if 400 <= code < 500:
                empty = {"type": "FeatureCollection", "features": []}
                _siose_cache_set(cache_key, empty)
                return empty
            # Para 5xx u otros, propagar como 502
            raise HTTPException(status_code=502, detail=f"Proxy SIOSE upstream error: {code}")
        except _URLError as e:
            raise HTTPException(status_code=502, detail=f"Proxy SIOSE network error: {e}")
        _siose_cache_set(cache_key, data)
        return data
    except HTTPException as he:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy SIOSE error: {e}")


# --- Proxy genérico para WMS GetCapabilities (evitar CORS) ---
@app.get("/proxy/wmscap")
async def proxy_wms_cap(url: str):
    try:
        from urllib.request import urlopen as _urlopen, Request as _Request
        from urllib.error import HTTPError as _HTTPError, URLError as _URLError
        req = _Request(url, headers={"User-Agent": "NormativaGalicia/1.0"})
        try:
            with _urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    # En teoría 4xx lanza HTTPError, pero por robustez
                    if 400 <= int(getattr(resp, 'status', 0)) < 500:
                        empty_xml = b"<WMS_Capabilities version=\"1.3.0\"></WMS_Capabilities>"
                        return Response(content=empty_xml, media_type='application/xml')
                    raise HTTPException(status_code=resp.status, detail=f"WMS status {resp.status}")
                raw = resp.read()
                ctype = resp.headers.get('Content-Type', 'application/xml')
                return Response(content=raw, media_type=ctype)
        except _HTTPError as e:
            # Amortiguar 4xx devolviendo XML mínimo (200 OK)
            code = int(getattr(e, 'code', 0) or 0)
            if 400 <= code < 500:
                empty_xml = b"<WMS_Capabilities version=\"1.3.0\"></WMS_Capabilities>"
                return Response(content=empty_xml, media_type='application/xml')
            raise HTTPException(status_code=502, detail=f"Proxy WMS upstream error: {code}")
        except _URLError as e:
            raise HTTPException(status_code=502, detail=f"Proxy WMS network error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy WMS error: {e}")

# --- Proxy genérico para WMS GetFeatureInfo (evitar CORS) ---
@app.get("/proxy/wmsinfo")
async def proxy_wms_info(base: str, layers: str, bbox: str, width: int = 256, height: int = 256, x: int = 128, y: int = 128, version: str = "1.1.1", srs: str = "EPSG:3857", info_format: str = "application/json"):
    """Reenvía una petición WMS GetFeatureInfo.
    Parámetros claves (WMS 1.1.1): base (URL del WMS sin parámetros), layers, bbox (EPSG:3857), width/height, x/y, srs, version, info_format.
    """
    try:
        from urllib.parse import urlencode as _urlencode
        from urllib.request import urlopen as _urlopen, Request as _Request
        sep = '&' if ('?' in base) else '?'
        params = {
            'service': 'WMS',
            'request': 'GetFeatureInfo',
            'version': version,
            'layers': layers,
            'query_layers': layers,
            'bbox': bbox,
            'srs': srs,
            'width': str(int(width)),
            'height': str(int(height)),
            'x': str(int(x)),
            'y': str(int(y)),
            'info_format': info_format,
        }
        url = f"{base}{sep}{_urlencode(params)}"
        req = _Request(url, headers={"User-Agent": "NormativaGalicia/1.0"})
        with _urlopen(req, timeout=15) as resp:
            raw = resp.read()
            ctype = resp.headers.get('Content-Type', info_format or 'application/octet-stream')
            return Response(content=raw, media_type=ctype)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy WMS GetFeatureInfo error: {e}")

# ================================
#  IA NORMATIVA – EXTRACCIÓN FASE 1 (mock reglas)
# ================================
class ExtractRequest(BaseModel):
    text: str
    municipio: Optional[str] = None
    fuente: Optional[str] = None  # url o referencia


class ExtractResponse(BaseModel):
    uso_suelo: Optional[str] = None
    altura_maxima_m: Optional[float] = None
    retranqueo_min_m: Optional[float] = None
    referencias: list[str] = []


def _parse_float_like(s: str) -> Optional[float]:
    try:
        s2 = s.replace(',', '.')
        return float(s2)
    except Exception:
        return None


@app.post("/normativa/extract-lite", response_model=ExtractResponse)
async def normativa_extract_lite(req: ExtractRequest):
    """Extracción heurística básica de parámetros normativos desde texto.
    Esta es una fase 1 (mock de reglas) para iterar rápidamente en UI y validación.
    """
    if not req.text or not isinstance(req.text, str):
        raise HTTPException(status_code=400, detail="Campo 'text' requerido")
    txt = req.text.lower()

    # Heurísticas de uso del suelo
    uso = None
    if any(k in txt for k in ("residencial", "vivienda", "resid.")):
        uso = "residencial"
    elif any(k in txt for k in ("industrial",)):
        uso = "industrial"
    elif any(k in txt for k in ("terciario", "comercial")):
        uso = "terciario"

    # Altura máxima (m)
    import re
    altura = None
    # patrones explícitos en metros
    m1 = re.search(r"altura\s*(?:m[aá]xima|max)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", txt)
    if not m1:
        m1 = re.search(r"\bh\s*\.?\s*m[aá]x\.?\s*(\d+(?:[\.,]\d+)?)\s*m\b", txt)
    if m1:
        altura = _parse_float_like(m1.group(1))
    # heurística por número de plantas si no hay metros
    if altura is None:
        # ejemplos: PB+3, B+2, "planta baja + 3", "3 plantas", "hasta 4 alturas"
        per_floor = None
        try:
            per_floor = float(os.getenv('PLAN_FLOOR_HEIGHT_M', '3.0'))
        except Exception:
            per_floor = 3.0
        pisos = None
        # PB+N / B+N
        m_pbn = re.search(r"\b(?:pb|b)\s*\+\s*(\d{1,2})\b", txt)
        if m_pbn:
            pisos = 1 + int(m_pbn.group(1))  # PB cuenta como 1 altura constructiva
        # N plantas / N alturas
        if pisos is None:
            m_np = re.search(r"\b(\d{1,2})\s*(?:plantas|alturas)\b", txt)
            if m_np:
                pisos = int(m_np.group(1))
        # "planta baja + N"
        if pisos is None:
            m_pb = re.search(r"planta\s*baja\s*\+\s*(\d{1,2})", txt)
            if m_pb:
                pisos = 1 + int(m_pb.group(1))
        if pisos is not None and pisos > 0 and per_floor:
            altura = round(pisos * per_floor, 2)

    # Retranqueo mínimo (m)
    retranq = None
    r1 = re.search(r"retranqueo\s*(?:m[ií]nimo|min)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", txt)
    if not r1:
        r1 = re.search(r"\bsetback\b\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", txt)
    if r1:
        retranq = _parse_float_like(r1.group(1))
    # direccionales (frente/laterales/fondo), escoger el mínimo conservador si hay varios
    dir_vals = []
    try:
        for pat in [
            (r"(?:frente|a\s+vial|alineaci[oó]n\s+de\s+fachada)[^\d]*(\d+(?:[\.,]\d+)?)\s*m", 'front'),
            (r"(?:lateral(?:es)?|costados)[^\d]*(\d+(?:[\.,]\d+)?)\s*m", 'side'),
            (r"(?:fondo|posterior)[^\d]*(\d+(?:[\.,]\d+)?)\s*m", 'back'),
        ]:
            m = re.search(pat[0], txt)
            if m:
                v = _parse_float_like(m.group(1))
                if v is not None:
                    dir_vals.append(v)
        if dir_vals and retranq is None:
            retranq = min(dir_vals)
    except Exception:
        pass

    # Referencias rudimentarias (artículos)
    refs: list[str] = []
    for m in re.finditer(r"art[\.\s]*\d+[\.\d]*", txt):
        try:
            refs.append(m.group(0))
        except Exception:
            pass
    if req.fuente:
        refs.append(str(req.fuente))

    return ExtractResponse(
        uso_suelo=uso,
        altura_maxima_m=altura,
        retranqueo_min_m=retranq,
        referencias=refs,
    )


class QARequest(BaseModel):
    pregunta: str


class QAResponse(BaseModel):
    respuesta: str

class QAResponseVerbose(BaseModel):
    respuesta: str
    diag: dict


@app.post("/qa", response_model=QAResponse)
async def qa(req: QARequest):
    if not req.pregunta:
        raise HTTPException(status_code=400, detail="Campo 'pregunta' requerido")
    # Ensure resources
    try:
        if not _RESOURCES['loaded']:
            try:
                chunks, index, bi_encoder, cross_encoder, llm = cargar_recursos()
                _RESOURCES.update({
                    'loaded': True,
                    'chunks': chunks,
                    'index': index,
                    'bi_encoder': bi_encoder,
                    'cross_encoder': cross_encoder,
                    'llm': llm,
                })
            except Exception as e:
                # No tumbar la demo por esto: responder con modo básico
                logging.getLogger(__name__).warning("/qa: recursos no disponibles (%s), usando fallback básico", e)
                raise RuntimeError(str(e))

        try:
            frags = buscar_fragmentos(req.pregunta, _RESOURCES['chunks'], _RESOURCES['index'], _RESOURCES['bi_encoder'], _RESOURCES['cross_encoder'])
            resp = generar_respuesta(req.pregunta, frags, _RESOURCES['llm'])
            return QAResponse(respuesta=resp)
        except Exception as e:
            logging.getLogger(__name__).warning("/qa: fallo generando respuesta (%s), usando fallback básico", e)
            raise RuntimeError(str(e))
    except Exception:
        try:
            return QAResponse(respuesta=build_qa_fallback_response(req.pregunta or ""))
        except Exception:
            return QAResponse(respuesta="Servicio de preguntas operativo en modo básico. Indica municipio y subzona para más detalle.")


@app.post("/qa/verbose", response_model=QAResponseVerbose)
async def qa_verbose(req: QARequest):
    """Versión con diagnóstico: incluye fuente (rag|fallback), municipio/subzona detectados y origen de cada campo (csv|heuristica|none)."""
    # Manejo temprano de small talk y "donde estoy" para evitar caer en RAG genérico
    try:
        low = (req.pregunta or '').strip().lower()
        # Intentar leer breve contexto del visor si viene embebido en la pregunta
        ctx_muni = None; ctx_subz = None
        try:
            for ln in str(req.pregunta or '').splitlines():
                ln2 = ln.strip()
                if ln2.lower().startswith('[contexto visor]'):
                    parts = ln2.split(' ', 2)[-1].split(',')
                    for part in parts:
                        if '=' in part:
                            k,v = part.split('=',1)
                            k=k.strip().lower(); v=v.strip()
                            if k=='municipio': ctx_muni = v
                            if k=='subzona': ctx_subz = v
        except Exception:
            pass
        if any(x in low for x in ("hola", "buenas", "qué tal", "que tal", "hola?", "buenos días", "buenas tardes", "buenas noches")):
            return QAResponseVerbose(respuesta="¡Hola! Puedo ayudarte con normativa urbanística y el visor. Indícame municipio y, si procede, la subzona.", diag={'mode':'smalltalk'})
        if ("donde estoy" in low) or ("dónde estoy" in low):
            if ctx_muni:
                return QAResponseVerbose(respuesta=f"Parece que estás consultando {ctx_muni}{(' '+ctx_subz) if ctx_subz else ''}.", diag={'mode':'fallback','municipio':ctx_muni,'subzona':ctx_subz,'provider_used':'none','fields_source':{}})
            return QAResponseVerbose(respuesta="No puedo conocer tu posición sin contexto. Dime municipio/subzona (p. ej., Vigo RZ-2).", diag={'mode':'fallback','municipio':None,'subzona':None,'provider_used':'none','fields_source':{}})
    except Exception:
        pass
    # Intentar modo RAG si recursos disponibles; si falla, usar fallback con diag
    try:
        if not _RESOURCES['loaded']:
            try:
                chunks, index, bi_encoder, cross_encoder, llm = cargar_recursos()
                _RESOURCES.update({
                    'loaded': True,
                    'chunks': chunks,
                    'index': index,
                    'bi_encoder': bi_encoder,
                    'cross_encoder': cross_encoder,
                    'llm': llm,
                })
            except Exception:
                raise RuntimeError('rag_unavailable')
        frags = buscar_fragmentos(req.pregunta, _RESOURCES['chunks'], _RESOURCES['index'], _RESOURCES['bi_encoder'], _RESOURCES['cross_encoder'])
        resp = generar_respuesta(req.pregunta, frags, _RESOURCES['llm'])
        return QAResponseVerbose(respuesta=resp, diag={
            'mode': 'rag',
            'fragments': len(frags or []),
        })
    except Exception:
        payload = build_qa_verbose_fallback_response(req.pregunta or "")
        return QAResponseVerbose(respuesta=payload["respuesta"], diag=payload["diag"])


@app.post("/zoning/analyze")
async def zoning_analyze(inp: ZoneInput):
    try:
        # Auto-inferir subzona si estamos en Vigo y no se proporcionó
        try:
            if (not getattr(inp, 'subzona', None)) and getattr(inp, 'municipio', None):
                if str(inp.municipio).strip().lower().find('vigo') >= 0:
                    cfg = wms_config_for_municipio(inp.municipio)
                    feature_url = (cfg or {}).get('feature_url') if isinstance(cfg, dict) else None
                    if feature_url and getattr(inp, 'geometry', None):
                        lon, lat = centroid_lonlat_from_geojson(inp.geometry, getattr(inp, 'crs', None))
                        if (lon is not None) and (lat is not None):
                            subz, _diag = arcgis_feature_query(feature_url, float(lon), float(lat))
                            if subz:
                                inp.subzona = subz
        except Exception:
            pass
        res = analizar_zonificacion(inp)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Inferencia de subzona vía WMS (MVP) ---
from pydantic import BaseModel


class InferSubzoneRequest(BaseModel):
    lon: float
    lat: float
    municipio: str
    srs: str | None = "EPSG:4326"


class InferSubzoneResponse(BaseModel):
    municipio: str
    subzona: str | None = None
    source: str = "wms"
    diagnostics: dict | None = None


@app.post("/zoning/infer-subzone", response_model=InferSubzoneResponse)
async def zoning_infer_subzone(req: InferSubzoneRequest):
    result = infer_subzone(req.municipio, req.lon, req.lat, req.srs)
    return InferSubzoneResponse(**result)


@app.get("/diagnostics/log-config")
async def diagnostics_log_config():
    """Devuelve la configuración de logging actual (solo si DIAGNOSTICS_ENABLED está activo)."""
    if str(os.getenv('DIAGNOSTICS_ENABLED', '0')).lower() not in ('1', 'true', 'yes'):
        raise HTTPException(status_code=404, detail="Not Found")

    root = logging.getLogger()
    def _handler_info(h: logging.Handler):
        info = {
            'type': h.__class__.__name__,
            'level': logging.getLevelName(h.level),
            'formatter': getattr(h.formatter, '_fmt', None) if getattr(h, 'formatter', None) else None,
        }
        if isinstance(h, logging.FileHandler):
            info['filename'] = getattr(h, 'baseFilename', None)
        # Rotating specifics
        try:
            from logging.handlers import RotatingFileHandler
            if isinstance(h, RotatingFileHandler):
                info['maxBytes'] = getattr(h, 'maxBytes', None)
                info['backupCount'] = getattr(h, 'backupCount', None)
        except Exception:
            pass
        return info

    volume_logger = logging.getLogger('volume')
    payload = {
        'root': {
            'level': logging.getLevelName(root.level),
            'handlers': [_handler_info(h) for h in root.handlers],
        },
        'loggers': {
            'volume': {
                'effective_level': logging.getLevelName(volume_logger.getEffectiveLevel()),
                'explicit_level': logging.getLevelName(volume_logger.level) if volume_logger.level else None,
                'propagate': volume_logger.propagate,
            }
        }
    }
    return payload


class GeometryRequest(BaseModel):
    geometry: dict


class GeometryChecksRequest(BaseModel):
    geometry: dict
    crs: Optional[str] = None
    target_crs: Optional[str] = None


@app.post("/zoning/geometry-checks", response_model=GeometryReport)
async def endpoint_geometry_checks(req: GeometryChecksRequest):
    try:
        if req.crs or req.target_crs:
            return geometry_checks_with_crs(req.geometry, req.crs, req.target_crs)
        return geometry_checks(req.geometry)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Solicitud de volumen/params (hoisted antes de usar en /zoning/assess para evitar ForwardRef)
class VolumeRequest(BaseModel):
    geometry: dict | None = None
    altura_maxima_m: float | None = None
    retranqueo_min_m: float | None = None
    municipio: str | None = None
    subzona: str | None = None
    setback_front_m: float | None = None
    setback_side_m: float | None = None
    setback_back_m: float | None = None
    front_direction: str | None = None  # 'north'|'east'|'south'|'west'
    street_axis: dict | None = None  # GeoJSON LineString/MultiLineString para detección automática de frente
    use_plan_front_default: bool | None = None  # Opt-in para usar front_direction_default del plan
    diagnostics_verbosity: Optional[str] = None  # 'full'|'min'|'none' (override por petición)
    crs: Optional[str] = None  # CRS de la geometría; si 'EPSG:4326' se convertirá a espacio métrico local

try:
    # Resolver ForwardRefs por uso de `from __future__ import annotations`
    VolumeRequest.model_rebuild()
except Exception:
    pass


class AssessResponse(BaseModel):
    viability: str  # 'apto'|'condicionado'|'no_apto'
    reasons: list[str]
    params_effective: dict
    feature: dict | None = None
    geometry_summary: dict | None = None

try:
    AssessResponse.model_rebuild()
except Exception:
    pass


@app.post("/zoning/assess", response_model=AssessResponse)
async def zoning_assess(req: VolumeRequest = Body(...)):
    """Evalúa la viabilidad normativa de una parcela con parámetros de plan.
    Devuelve una etiqueta de viabilidad y razones, junto a los parámetros efectivos aplicados.
    """
    try:
        result = evaluate_zoning_assessment(req)
    except ZoningAssessmentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AssessResponse(**result)


@app.get("/zoning/assess-report")
async def zoning_assess_report_get(body_b64: Optional[str] = None, logo: Optional[str] = None, title: Optional[str] = None, client: Optional[str] = None, project: Optional[str] = None, snap: Optional[str] = None, brand_color: Optional[str] = None, signature: Optional[bool] = True, sign_by: Optional[str] = 'DVR', sign_place: Optional[str] = None, notes: Optional[str] = None, source_ref: Optional[str] = None):
    """GET que recibe `body_b64` (JSON VolumeRequest url-safe base64) y devuelve un informe HTML de viabilidad."""
    if not body_b64 or not isinstance(body_b64, str):
        raise HTTPException(status_code=400, detail="Parámetro 'body_b64' requerido en la query")
    try:
        import base64 as _b64, json as _json
        s = body_b64.replace('-', '+').replace('_', '/')
        pad = '=' * ((4 - (len(s) % 4)) % 4)
        raw = _b64.b64decode(s + pad)
        body = _json.loads(raw.decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('El cuerpo decodificado no es un objeto JSON')
        req = VolumeRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"body_b64 inválido: {e}")

    # Ejecutar evaluación reutilizando el endpoint
    res = await zoning_assess(req)  # AssessResponse
    official_ctx = _build_official_context(municipio=body.get('municipio'), subzona=body.get('subzona'), geometry=body.get('geometry'))
    html = _render_assess_report_html(body, res, logo=logo, title=title, client=client, project=project, snapshot_data_url=snap, brand_color=brand_color, signature=bool(signature or False), sign_by=sign_by, sign_place=sign_place, notes=notes, source_ref=source_ref, official_context=official_ctx)
    return Response(content=html, media_type='text/html; charset=utf-8')


@app.get("/zoning/assess-report.pdf")
async def zoning_assess_report_pdf_get(body_b64: Optional[str] = None, logo: Optional[str] = None, title: Optional[str] = None, client: Optional[str] = None, project: Optional[str] = None, snap: Optional[str] = None, brand_color: Optional[str] = None, signature: Optional[bool] = True, sign_by: Optional[str] = 'DVR', sign_place: Optional[str] = None, notes: Optional[str] = None, source_ref: Optional[str] = None):
    """Genera PDF del informe en servidor.
    Requiere la librería WeasyPrint instalada. Si no está disponible, devuelve 501.
    """
    # Reutilizar el flujo de GET HTML
    if not body_b64 or not isinstance(body_b64, str):
        raise HTTPException(status_code=400, detail="Parámetro 'body_b64' requerido en la query")
    try:
        import base64 as _b64, json as _json
        s = body_b64.replace('-', '+').replace('_', '/')
        pad = '=' * ((4 - (len(s) % 4)) % 4)
        raw = _b64.b64decode(s + pad)
        body = _json.loads(raw.decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('El cuerpo decodificado no es un objeto JSON')
        req = VolumeRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"body_b64 inválido: {e}")

    # Ejecutar evaluación y renderizar HTML
    res = await zoning_assess(req)
    official_ctx = _build_official_context(municipio=body.get('municipio'), subzona=body.get('subzona'), geometry=body.get('geometry'))
    html = _render_assess_report_html(body, res, logo=logo, title=title, client=client, project=project, snapshot_data_url=snap, brand_color=brand_color, signature=bool(signature or False), sign_by=sign_by, sign_place=sign_place, official_context=official_ctx)

    # Intentar generar PDF con WeasyPrint
    try:
        from weasyprint import HTML as _HTML
    except Exception as e:
        raise HTTPException(status_code=501, detail=f"PDF en servidor no disponible: instale 'WeasyPrint'. Detalle: {e}")
    try:
        pdf_bytes = _HTML(string=html).write_pdf()
        headers = {"Content-Disposition": "inline; filename=InformeViabilidad.pdf"}
        return Response(content=pdf_bytes, media_type='application/pdf', headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fallo generando PDF: {e}")


class AssessReportRequest(BaseModel):
    body: VolumeRequest
    logo: Optional[str] = None
    title: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    snapshot_data_url: Optional[str] = None
    brand_color: Optional[str] = None
    signature: Optional[bool] = True
    sign_by: Optional[str] = 'DVR'
    sign_place: Optional[str] = None
    notes: Optional[str] = None
    source_ref: Optional[str] = None


@app.post("/zoning/assess-report")
async def zoning_assess_report_post(req: AssessReportRequest):
    """POST que recibe JSON con VolumeRequest y metadatos opcionales, y devuelve el HTML del informe."""
    res = await zoning_assess(req.body)  # AssessResponse
    # Convertir VolumeRequest a dict limpio
    try:
        body = req.body.model_dump()
    except Exception:
        body = req.body.dict() if hasattr(req.body, 'dict') else dict(req.body)
    official_ctx = _build_official_context(municipio=body.get('municipio'), subzona=body.get('subzona'), geometry=body.get('geometry'))
    html = _render_assess_report_html(body, res, logo=req.logo, title=req.title, client=req.client, project=req.project, snapshot_data_url=req.snapshot_data_url, brand_color=req.brand_color, signature=bool(req.signature or False), sign_by=req.sign_by, sign_place=req.sign_place, notes=req.notes, source_ref=req.source_ref, official_context=official_ctx)
    return Response(content=html, media_type='text/html; charset=utf-8')


# ... (rest of the code remains the same)

@app.get("/zoning/volume-export")
async def zoning_volume_export_get(format: Optional[str] = 'cityjson', body_b64: Optional[str] = None, download: bool = False, strict: bool = False, gzip: bool = False):
    """GET variant that accepts a URL-safe base64 encoded JSON body via `body_b64`.
    This matches the viewer's usage pattern and forwards to the POST handler for processing.
    """
    # Validate format early to keep error symmetry
    fmt = (format or 'cityjson').strip().lower()
    if fmt not in ('cityjson', 'gltf', 'glb', 'ifc'):
        raise HTTPException(status_code=400, detail="Formato no soportado: use 'cityjson', 'gltf', 'glb' o 'ifc'")
    if not body_b64 or not isinstance(body_b64, str):
        raise HTTPException(status_code=400, detail="Parámetro 'body_b64' requerido en la query")
    # Decode URL-safe base64 with proper padding
    try:
        import base64 as _b64
        import json as _json
        s = body_b64.replace('-', '+').replace('_', '/')
        pad = '=' * ((4 - (len(s) % 4)) % 4)
        raw = _b64.b64decode(s + pad)
        body = _json.loads(raw.decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('El cuerpo decodificado no es un objeto JSON')
        # Ensure format consistency: query param prevails
        body['format'] = fmt
        req = VolumeExportRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"body_b64 inválido: {e}")
    # Delegate to the POST handler to keep a single implementation
    return await zoning_volume_export(req, download=download, strict=strict, gzip=gzip)

class ValidatePlanCSVRequest(BaseModel):
    path: Optional[str] = None
    csv_text: Optional[str] = None


@app.post("/zoning/validate-plan-csv")
async def validate_plan_csv(req: ValidatePlanCSVRequest):
    """Valida un CSV de planeamiento sin cargarlo en producción.
    Acepta `path` a fichero o `csv_text` en crudo. Devuelve errores y advertencias.
    """
    import io
    import csv as _csv
    from src.planes.csv_provider import CSVPlanProvider
    errors: list[dict] = []
    warnings: list[str] = []

    if not req.path and not req.csv_text:
        return {"valid": False, "errors": [{"message": "Se requiere 'path' o 'csv_text'"}], "warnings": [], "summary": {"errors": 1, "warnings": 0}, "cache_hit": False}

    try:
        if req.csv_text:
            f = io.StringIO(req.csv_text)
            reader = _csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            required = {'municipio'}
            missing = sorted(list(required - headers))
            if missing:
                errors.append({"message": f"CSV faltan columnas requeridas: {', '.join(missing)}"})
            allowed = {
                'municipio','subzona','altura_maxima_m','retranqueo_min_m',
                'setback_front_m','setback_side_m','setback_back_m',
                'front_direction_default','ocupacion_max','edificabilidad_max_m2_m2'
            }
            unknown = sorted(list(headers - allowed))
            if unknown:
                warnings.append(f"Columnas desconocidas: {', '.join(unknown)}")
            # Construir provider desde un buffer temporal para reutilizar validación fila a fila
            # Creamos un CSV en memoria con mismas filas
            rows = list(reader)
            # Duplicados por (municipio, subzona)
            seen: set[tuple[str, str]] = set()
            for rr in rows:
                km = (rr.get('municipio') or '').strip().lower()
                ks = (rr.get('subzona') or '').strip().lower() if (rr.get('subzona') is not None) else ''
                key = (km, ks)
                if key in seen:
                    errors.append({
                        "municipio": rr.get('municipio') or None,
                        "subzona": (rr.get('subzona') or '').strip() or None,
                        "message": f"Fila duplicada para municipio/subzona: {rr.get('municipio') or ''} / {(rr.get('subzona') or '').strip()}"
                    })
                else:
                    seen.add(key)
            # Para disparar validaciones, iteramos por filas y llamamos a la lógica de normalización/validación
            # Simulamos provider en memoria escribiendo a un NamedTemporaryFile
            import tempfile, os as _os
            with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8', newline='') as tmp:
                writer = _csv.DictWriter(tmp, fieldnames=list(headers))
                writer.writeheader()
                writer.writerows(rows)
                temp_path = tmp.name
            try:
                provider = CSVPlanProvider(temp_path)
                for r in provider.rows:
                    municipio = (r.get('municipio') or '').strip()
                    subzona = (r.get('subzona') or '').strip() or None
                    try:
                        # Dispara validaciones de rango y coherencia
                        provider.get(municipio, subzona)
                    except Exception as e:
                        errors.append({"municipio": municipio or None, "subzona": subzona, "message": str(e)})
            finally:
                try:
                    _os.unlink(temp_path)
                except Exception:
                    pass
        else:
            # Validar por ruta directa
            cached = _validate_cache_get(req.path)
            if cached is not None:
                try:
                    if _metrics_ready and _CSV_CACHE_HITS is not None:
                        _CSV_CACHE_HITS.inc()
                except Exception:
                    pass
                return cached
            provider = CSVPlanProvider(req.path)  # puede lanzar FileNotFoundError/ValueError
            # No conocemos directamente cabeceras desconocidas aquí, ya logueadas por el provider
            # Para cada fila, forzamos validación
            seen2: set[tuple[str, str]] = set()
            for r in provider.rows:
                municipio = (r.get('municipio') or '').strip()
                subzona = (r.get('subzona') or '').strip() or None
                km = municipio.lower()
                ks = (subzona or '').lower()
                key = (km, ks)
                if key in seen2:
                    errors.append({
                        "municipio": municipio or None,
                        "subzona": subzona,
                        "message": f"Fila duplicada para municipio/subzona: {municipio} / {(subzona or '')}"
                    })
                    continue
                else:
                    seen2.add(key)
                try:
                    provider.get(municipio, subzona)
                except Exception as e:
                    errors.append({"municipio": municipio or None, "subzona": subzona, "message": str(e)})
    except FileNotFoundError as e:
        return {"valid": False, "errors": [{"message": str(e)}], "warnings": [], "summary": {"errors": 1, "warnings": 0}, "cache_hit": False}
    except Exception as e:
        # No interrumpir: devolver como error de validación
        errors.append({"message": str(e)})

    response = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": {"errors": len(errors), "warnings": len(warnings)}
    }
    # cache only when path mode
    if req.path and not req.csv_text and len(errors) >= 0:
        response["cache_hit"] = False
        try:
            if _metrics_ready and _CSV_CACHE_MISSES is not None:
                _CSV_CACHE_MISSES.inc()
        except Exception:
            pass
        _validate_cache_set(req.path, response)
    return response



@app.post("/zoning/volume")
async def zoning_volume(req: VolumeRequest):
    # Derivar parámetros si no se aportan pero hay municipio
    altura = req.altura_maxima_m
    retranqueo = req.retranqueo_min_m or 0.0
    if altura is None:
        if req.municipio:
            try:
                from src.rules_engine import get_plan_params_dynamic
                plan = get_plan_params_dynamic(req.municipio, req.subzona)
                if plan.altura_maxima_m is None:
                    raise ValueError("El plan municipal no devuelve altura máxima")
                altura = plan.altura_maxima_m
                if req.retranqueo_min_m is None and plan.retranqueo_min_m is not None:
                    retranqueo = plan.retranqueo_min_m
                # Determinar dirección de frente efectiva
                effective_front_direction = req.front_direction
                # Si no hay front_direction ni street_axis, y el plan define una por defecto + setbacks, usarla
                pf = getattr(plan, 'setback_front_m', None)
                ps = getattr(plan, 'setback_side_m', None)
                pb = getattr(plan, 'setback_back_m', None)
                pfd = getattr(plan, 'front_direction_default', None)
                has_plan_dir_setbacks = (pf is not None) or (ps is not None) or (pb is not None)
                if (
                    effective_front_direction is None
                    and req.street_axis is None
                    and bool(req.use_plan_front_default)
                    and pfd
                    and has_plan_dir_setbacks
                ):
                    effective_front_direction = pfd

                # Rellenar retranqueos direccionales si procede (cuando hay contexto direccional efectivo)
                if effective_front_direction is not None or req.street_axis is not None:
                    setback_front = req.setback_front_m if req.setback_front_m is not None else pf
                    setback_side = req.setback_side_m if req.setback_side_m is not None else ps
                    setback_back = req.setback_back_m if req.setback_back_m is not None else pb
                else:
                    setback_front = req.setback_front_m
                    setback_side = req.setback_side_m
                    setback_back = req.setback_back_m
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"No se pudieron obtener parámetros municipales: {e}")
        else:
            raise HTTPException(status_code=400, detail="altura_maxima_m requerida si no se especifica municipio")

    try:
        # Usa valores de retranqueos: si no hubo municipio arriba, tomar los de request
        if req.municipio is None:
            setback_front = req.setback_front_m
            setback_side = req.setback_side_m
            setback_back = req.setback_back_m

        # Determinar front_direction a pasar y su origen
        front_dir_to_pass = req.front_direction
        front_dir_source = None
        if req.municipio is not None:
            # Si calculamos effective_front_direction arriba, úsala
            try:
                front_dir_to_pass = effective_front_direction
                if effective_front_direction is not None and req.front_direction is None and req.street_axis is None and bool(req.use_plan_front_default):
                    front_dir_source = 'plan_default'
            except NameError:
                front_dir_to_pass = req.front_direction
        if front_dir_source is None and front_dir_to_pass is not None and req.front_direction is not None:
            front_dir_source = 'request'

        feature = compute_building_envelope(
            req.geometry,
            VolumeParams(
                altura_maxima_m=altura,
                retranqueo_min_m=retranqueo,
                setback_front_m=setback_front,
                setback_side_m=setback_side,
                setback_back_m=setback_back,
                front_direction=front_dir_to_pass,
            ),
            street_axis=req.street_axis,
            front_direction_source=front_dir_source,
            crs=getattr(req, 'crs', None),
        )
        if feature is None:
            # Envolvente vacía: probablemente retranqueos agotan la parcela
            diag = {
                "reason": "parcel_exhausted_by_setbacks",
                "hint": "Reduzca retranqueos o use una parcela mayor",
            }
            return {
                "feature": None,
                "diagnostics": diag,
                "diagnostics_level_applied": _resolve_diag_verbosity(req.diagnostics_verbosity),
                "limiting_factor": "retranqueos",
                "limiting_details": {"reason": diag["reason"]},
            }
        limiting_factor, limiting_details = infer_limiting_factor(req.municipio, req.subzona, feature)
        _effective = _resolve_diag_verbosity(req.diagnostics_verbosity)
        return {
            "feature": _filter_volume_diagnostics(feature, _effective),
            "diagnostics_level_applied": _effective,
            "limiting_factor": limiting_factor,
            "limiting_details": limiting_details,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class VolumeExportRequest(VolumeRequest):
    format: Optional[str] = 'cityjson'  # 'cityjson' | 'gltf'


@app.post("/zoning/volume-export")
async def zoning_volume_export(req: VolumeExportRequest, download: bool = False, strict: bool = False, gzip: bool = False):
    try:
        fmt = normalize_volume_export_format(req.format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        feature = build_volume_export_feature(req, fmt, strict=strict)
        if is_exhausted_feature(feature):
            import json as _json
            if fmt == 'cityjson' and strict:
                # Sin envolvente y en modo estricto no hay fallback
                raise HTTPException(status_code=400, detail="Envolvente no computable en modo estricto")
            # Adjuntar diagnóstico coherente con /zoning/volume
            diagnostics = {
                "reason": "parcel_exhausted_by_setbacks",
                "hint": "Reduzca retranqueos o use una parcela mayor",
            }
            payload = ({"cityjson": None, "diagnostics": diagnostics} if fmt == 'cityjson' else {"gltf": None, "diagnostics": diagnostics})
            content = _json.dumps(payload, separators=(',', ':'))
            # métricas
            try:
                size_bytes = len(content.encode('utf-8'))
                if _metrics_env_enabled and _metrics_ready:
                    _EXP_COUNT.labels(format=fmt, status='200').inc()
                    _EXP_SIZE.labels(format=fmt, status='200').observe(size_bytes)
            except Exception:
                pass
            if download:
                media = 'application/city+json' if fmt == 'cityjson' else 'model/gltf+json'
                if fmt == 'cityjson' and gzip:
                    import gzip as _gzip
                    gz = _gzip.compress(content.encode('utf-8'))
                    # overwrite metrics with actual wire size
                    try:
                        if _metrics_env_enabled and _metrics_ready:
                            _EXP_SIZE.labels(format=fmt, status='200').observe(len(gz))
                    except Exception:
                        pass
                    return Response(content=gz, media_type=media, headers={
                        "Content-Disposition": "attachment; filename=\"building.city.json.gz\"",
                        "Content-Encoding": "gzip",
                    })
                fname = 'building.city.json' if fmt == 'cityjson' else 'building.gltf'
                return Response(content=content, media_type=media, headers={"Content-Disposition": f"attachment; filename=\"{fname}\""})
            return payload
        if fmt == 'cityjson':
            import json as _json
            payload = _extrude_polygon_to_cityjson(feature)
            content = _json.dumps(payload, separators=(',', ':'))
            try:
                size_bytes = len(content.encode('utf-8'))
                if _metrics_env_enabled and _metrics_ready:
                    _EXP_COUNT.labels(format=fmt, status='200').inc()
                    _EXP_SIZE.labels(format=fmt, status='200').observe(size_bytes)
            except Exception:
                pass
            if download:
                if gzip:
                    import gzip as _gzip
                    gz = _gzip.compress(content.encode('utf-8'))
                    try:
                        if _metrics_env_enabled and _metrics_ready:
                            _EXP_SIZE.labels(format=fmt, status='200').observe(len(gz))
                    except Exception:
                        pass
                    return Response(content=gz, media_type='application/city+json', headers={
                        "Content-Disposition": "attachment; filename=\"building.city.json.gz\"",
                        "Content-Encoding": "gzip",
                    })
                return Response(content=content, media_type='application/city+json', headers={"Content-Disposition": "attachment; filename=\"building.city.json\""})
            return payload
        else:
            if fmt == 'ifc':
                ifc_content = _extrude_polygon_to_ifc(feature)
                try:
                    size_bytes = len(ifc_content.encode('utf-8'))
                    if _metrics_env_enabled and _metrics_ready:
                        _EXP_COUNT.labels(format=fmt, status='200').inc()
                        _EXP_SIZE.labels(format=fmt, status='200').observe(size_bytes)
                except Exception:
                    pass
                media = 'application/ifc'
                fname = 'building.ifc'
                return Response(content=ifc_content, media_type=media, headers={"Content-Disposition": f"attachment; filename=\"{fname}\""} if download else {})
            import json as _json
            if fmt == 'gltf':
                payload = _extrude_polygon_to_gltf(feature)
                content = _json.dumps(payload, separators=(',', ':'))
            else:
                # glb: convertir desde GLTF embebido a binario GLB
                gltf_json = _extrude_polygon_to_gltf(feature)
                try:
                    glb_bytes = _gltf_to_glb_bytes(gltf_json)
                except Exception as _e:
                    raise HTTPException(status_code=400, detail=f"Error generando GLB: {_e}")
                # métricas
                try:
                    size_bytes = len(glb_bytes)
                    if _metrics_env_enabled and _metrics_ready:
                        _EXP_COUNT.labels(format=fmt, status='200').inc()
                        _EXP_SIZE.labels(format=fmt, status='200').observe(size_bytes)
                except Exception:
                    pass
                if download:
                    return Response(content=glb_bytes, media_type='model/gltf-binary', headers={"Content-Disposition": "attachment; filename=\"building.glb\""})
                else:
                    import base64 as _b64
                    b64 = _b64.b64encode(glb_bytes).decode('ascii')
                    return {"glb_b64": b64}
            try:
                size_bytes = len(content.encode('utf-8'))
                if _metrics_env_enabled and _metrics_ready:
                    _EXP_COUNT.labels(format=fmt, status='200').inc()
                    _EXP_SIZE.labels(format=fmt, status='200').observe(size_bytes)
            except Exception:
                pass
            # Para GLTF, devolver JSON envuelto cuando download=false (consistencia con diagnostics)
            if fmt == 'gltf' and not download:
                return {"gltf": payload}
            media = 'model/gltf+json'
            fname = 'building.gltf'
            return Response(content=content, media_type=media, headers={"Content-Disposition": f"attachment; filename=\"{fname}\""} if download else {})
    except HTTPException as he:
        try:
            if _metrics_env_enabled and _metrics_ready:
                _EXP_COUNT.labels(format=fmt, status=str(he.status_code)).inc()
                _EXP_SIZE.labels(format=fmt, status=str(he.status_code)).observe(0)
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            if _metrics_env_enabled and _metrics_ready:
                _EXP_COUNT.labels(format=fmt, status='400').inc()
                _EXP_SIZE.labels(format=fmt, status='400').observe(0)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))


# ------------------------------
# Inventario de planeamiento (CSV oficial Xunta)
# ------------------------------
_INV_CACHE = {
  'path': None,
  'mtime': None,
  'rows': None,
}

def _get_inventario_path() -> str:
  p = os.getenv('INVENTARIO_PLANEAMENTO_PATH')
  if p and os.path.isfile(p):
    return p
  for cand in (
    os.path.join('datos', 'inventario_planeamento.csv'),
    os.path.join('app', 'data', 'inventario_planeamento.csv'),
  ):
    if os.path.isfile(cand):
      return cand
  return os.path.join('datos', 'inventario_planeamento.csv')

def _load_inventario() -> list[dict]:
  path = _get_inventario_path()
  try:
    mtime = os.path.getmtime(path)
  except Exception:
    return []
  if _INV_CACHE['rows'] is not None and _INV_CACHE['path'] == path and _INV_CACHE['mtime'] == mtime:
    return _INV_CACHE['rows'] or []
  rows: list[dict] = []
  try:
    with open(path, 'r', encoding='utf-8-sig') as f:
      rdr = csv.DictReader(f)
      for r in rdr:
        rows.append(r)
    _INV_CACHE.update({'path': path, 'mtime': mtime, 'rows': rows})
    return rows
  except Exception:
    return []

@app.get('/planeamento/inventario')
def planeamento_inventario(municipio: Optional[str] = None):
  """Devuelve el inventario de planeamiento (CSV Xunta). Si se indica municipio, filtra por coincidencia case-insensitive.
  Respuesta: { count, rows }
  """
  rows = _load_inventario()
  if not rows:
    return {'count': 0, 'rows': []}
  if municipio:
    target = (municipio or '').strip()
    def _norm(s: str) -> str:
      try:
        import unicodedata as _ud
        return ''.join(ch for ch in _ud.normalize('NFD', s.lower()) if _ud.category(ch) != 'Mn')
      except Exception:
        return s.lower()
    out = [r for r in rows if _norm(str(r.get('CONCELLO') or r.get('Concello') or r.get('municipio') or '')) == _norm(target)]
    return {'count': len(out), 'rows': out}
  return {'count': len(rows), 'rows': rows[:5000]}


def _norm_text(s: str) -> str:
  try:
    import unicodedata as _ud
    return ''.join(ch for ch in _ud.normalize('NFD', (s or '').lower()) if _ud.category(ch) != 'Mn').strip()
  except Exception:
    return (s or '').lower().strip()


def _parse_catastro_rccoor_xml(raw: bytes) -> dict:
  """Parsea la respuesta XML de Consulta_RCCOOR del Catastro.
  Maneja diferentes esquemas y namespaces del OVC.
  """
  try:
    root = ET.fromstring(raw)
  except Exception:
    return {'found': False, 'error': 'XML inválido'}
  for elem in root.iter():
    if '}' in elem.tag:
      elem.tag = elem.tag.rsplit('}', 1)[-1]
  # Buscar el nodo coord en cualquier namespace
  coord = root.find('.//coord')
  if coord is None:
    # Intentar con namespace común del Catastro
    for elem in root.iter():
      if elem.tag.endswith('coord') and elem.find('.//pc') is not None:
        coord = elem
        break
  if coord is None:
    # Verificar si hay un mensaje de error
    err = root.findtext('.//error') or root.findtext('.//desError') or root.findtext('.//message')
    return {'found': False, 'error': err or 'No se encontró parcela'}
  # Referencia catastral: pc1 + pc2 (14 caracteres)
  pc1 = coord.findtext('./pc/pc1') or ''
  pc2 = coord.findtext('./pc/pc2') or ''
  pc = (pc1 + pc2).strip()
  # Validar formato: 14 caracteres alfanuméricos
  if pc and len(pc) != 14:
    # Intentar extraer de otros campos
    pc = coord.findtext('./rc') or coord.findtext('./refcat') or pc
  # Datos adicionales del nodo dt
  dt = coord.find('.//dt')
  municipio = None
  via = None
  npolicia = None
  if dt is not None:
    municipio = dt.findtext('./municipi/nm') or dt.findtext('./nm') or dt.findtext('.//nm')
    via_el = dt.find('.//via')
    if via_el is not None:
      via = via_el.findtext('./tv') or None
      npolicia = via_el.findtext('./pnp') or None
  # Coordenadas
  x = coord.findtext('./geo/xcen') or coord.findtext('./xcen') or coord.findtext('.//xcen')
  y = coord.findtext('./geo/ycen') or coord.findtext('./ycen') or coord.findtext('.//ycen')
  srs = coord.findtext('./geo/srs') or coord.findtext('./srs') or coord.findtext('.//srs')
  # Validar que el refcat tiene formato válido (7 dígitos + 7 alfanuméricos)
  refcat_valid = bool(pc) and len(pc) == 14 and pc[:7].isdigit()
  return {
    'found': refcat_valid,
    'refcat': pc if refcat_valid else None,
    'refcat_raw': pc or None,
    'direccion': coord.findtext('./ldt') or None,
    'srs': srs or 'EPSG:4326',
    'x': x,
    'y': y,
    'municipio_catastral': municipio,
    'via': via,
    'numero_policia': npolicia,
  }


# Bounding box aproximado de Galicia para validación
_GALICIA_BBOX = {
  'lon_min': -9.30, 'lon_max': -6.70,
  'lat_min': 41.80, 'lat_max': 44.10,
}

# Mapeo de municipios a códigos INE para SIOTUGA
# Fuente: INE - Relación de municipios y sus códigos (313 concellos de Galicia)
# Incluye alias comunes (sin artículo, formas cortas) para matching flexible
_MUNICIPIO_INE: dict[str, str] = {
  'a arnoia': '32003',
  'a bana': '15007',
  'a bola': '32014',
  'a caniza': '36009',
  'a capela': '15018',
  'a coruna': '15030',
  'a estrada': '36017',
  'a fonsagrada': '27018',
  'a guarda': '36023',
  'a gudina': '32034',
  'a illa de arousa': '36901',
  'a lama': '36025',
  'a laracha': '15041',
  'a merca': '32047',
  'a mezquita': '32048',
  'a pastoriza': '27044',
  'a peroxa': '32059',
  'a pobra de trives': '32063',
  'a pobra do brollon': '27047',
  'a pobra do caraminal': '15067',
  'a pontenova': '27048',
  'a rua': '32072',
  'a teixeira': '32080',
  'a veiga': '32083',
  'abadin': '27001',
  'abegondo': '15001',
  'agolada': '36020',
  'alfoz': '27002',
  'allariz': '32001',
  'ames': '15002',
  'amoeiro': '32002',
  'antas de ulla': '27003',
  'aranga': '15003',
  'arbo': '36001',
  'ares': '15004',
  'arnoia': '32003',
  'arnoia, a': '32003',
  'arteixo': '15005',
  'arzua': '15006',
  'as neves': '36034',
  'as nogais': '27037',
  'as pontes de garcia rodriguez': '15070',
  'as somozas': '15081',
  'avion': '32004',
  'baiona': '36003',
  'baleira': '27004',
  'baltar': '32005',
  'bana': '15007',
  'bana, a': '15007',
  'bande': '32006',
  'banos de molgas': '32007',
  'baralla': '27901',
  'barbadas': '32008',
  'barco de valdeorras': '32009',
  'barco de valdeorras, o': '32009',
  'barreiros': '27005',
  'barro': '36002',
  'beade': '32010',
  'beariz': '32011',
  'becerrea': '27006',
  'begonte': '27007',
  'bergondo': '15008',
  'bertamirans': '15002',
  'betanzos': '15009',
  'blancos': '32012',
  'blancos, os': '32012',
  'boboras': '32013',
  'boimorto': '15010',
  'boiro': '15011',
  'bola': '32014',
  'bola, a': '32014',
  'bolo': '32015',
  'bolo, o': '32015',
  'boqueixon': '15012',
  'boveda': '27008',
  'brion': '15013',
  'bueu': '36004',
  'burela': '27902',
  'cabana de bergantinos': '15014',
  'cabanas': '15015',
  'caldas de reis': '36005',
  'calvos de randin': '32016',
  'camarinas': '15016',
  'cambados': '36006',
  'cambre': '15017',
  'campo lameiro': '36007',
  'cangas': '36008',
  'caniza': '36009',
  'caniza, a': '36009',
  'capela': '15018',
  'capela, a': '15018',
  'carballeda de avia': '32018',
  'carballeda de valdeorras': '32017',
  'carballedo': '27009',
  'carballino': '32019',
  'carballino, o': '32019',
  'carballo': '15019',
  'carino': '15901',
  'carnota': '15020',
  'carral': '15021',
  'cartelle': '32020',
  'castrelo de mino': '32022',
  'castrelo do val': '32021',
  'castro caldelas': '32023',
  'castro de rei': '27010',
  'castroverde': '27011',
  'catoira': '36010',
  'cedeira': '15022',
  'cee': '15023',
  'celanova': '32024',
  'cenlle': '32025',
  'cerceda': '15024',
  'cerdedo-cotobade': '36902',
  'cerdido': '15025',
  'cervantes': '27012',
  'cervo': '27013',
  'chandrexa de queixa': '32029',
  'chantada': '27016',
  'coiros': '15027',
  'coles': '32026',
  'corcubion': '15028',
  'corgo': '27014',
  'corgo, o': '27014',
  'coristanco': '15029',
  'cortegada': '32027',
  'coruna': '15030',
  'coruna, a': '15030',
  'cospeito': '27015',
  'covelo': '36013',
  'crecente': '36014',
  'cualedro': '32028',
  'culleredo': '15031',
  'cuntis': '36015',
  'curtis': '15032',
  'dodro': '15033',
  'dozon': '36016',
  'dumbria': '15034',
  'entrimo': '32030',
  'esgos': '32031',
  'estrada': '36017',
  'estrada, a': '36017',
  'fene': '15035',
  'ferrol': '15036',
  'fisterra': '15037',
  'folgoso do courel': '27017',
  'fonsagrada': '27018',
  'fonsagrada, a': '27018',
  'forcarei': '36018',
  'fornelos de montes': '36019',
  'foz': '27019',
  'frades': '15038',
  'friol': '27020',
  'gomesende': '32033',
  'gondomar': '36021',
  'grove': '36022',
  'grove, o': '36022',
  'guarda': '36023',
  'guarda, a': '36023',
  'gudina': '32034',
  'gudina, a': '32034',
  'guitiriz': '27022',
  'guntin': '27023',
  'illa de arousa': '36901',
  'illa de arousa, a': '36901',
  'incio': '27024',
  'incio, o': '27024',
  'irixo': '32035',
  'irixo, o': '32035',
  'irixoa': '15039',
  'lalin': '36024',
  'lama': '36025',
  'lama, a': '36025',
  'lancara': '27026',
  'laracha': '15041',
  'laracha, a': '15041',
  'larouco': '32038',
  'laxe': '15040',
  'laza': '32039',
  'leiro': '32040',
  'lobeira': '32041',
  'lobios': '32042',
  'lourenza': '27027',
  'lousame': '15042',
  'lugo': '27028',
  'maceda': '32043',
  'malpica de bergantinos': '15043',
  'manon': '15044',
  'manzaneda': '32044',
  'marin': '36026',
  'maside': '32045',
  'mazaricos': '15045',
  'meano': '36027',
  'meira': '27029',
  'meis': '36028',
  'melide': '15046',
  'melon': '32046',
  'merca': '32047',
  'merca, a': '32047',
  'mesia': '15047',
  'mezquita': '32048',
  'mezquita, a': '32048',
  'mino': '15048',
  'moana': '36029',
  'moeche': '15049',
  'mondariz': '36030',
  'mondariz-balneario': '36031',
  'mondonedo': '27030',
  'monfero': '15050',
  'monforte de lemos': '27031',
  'montederramo': '32049',
  'monterrei': '32050',
  'monterroso': '27032',
  'morana': '36032',
  'mos': '36033',
  'mugardos': '15051',
  'muinos': '32051',
  'muras': '27033',
  'muros': '15053',
  'muxia': '15052',
  'naron': '15054',
  'navia de suarna': '27034',
  'neda': '15055',
  'negreira': '15056',
  'negueira de muniz': '27035',
  'neves': '36034',
  'neves, as': '36034',
  'nigran': '36035',
  'nogais': '27037',
  'nogais, as': '27037',
  'nogueira de ramuin': '32052',
  'noia': '15057',
  'o barco de valdeorras': '32009',
  'o bolo': '32015',
  'o carballino': '32019',
  'o corgo': '27014',
  'o grove': '36022',
  'o incio': '27024',
  'o paramo': '27043',
  'o pereiro de aguiar': '32058',
  'o pino': '15066',
  'o porrino': '36039',
  'o rosal': '36048',
  'o savinao': '27058',
  'o valadouro': '27063',
  'o vicedo': '27064',
  'oia': '36036',
  'oimbra': '32053',
  'oleiros': '15058',
  'ordes': '15059',
  'oroso': '15060',
  'ortigueira': '15061',
  'os blancos': '32012',
  'ourense': '32054',
  'ourol': '27038',
  'outeiro de rei': '27039',
  'outes': '15062',
  'oza-cesuras': '15902',
  'paderne': '15064',
  'paderne de allariz': '32055',
  'padrenda': '32056',
  'padron': '15065',
  'palas de rei': '27040',
  'panton': '27041',
  'parada de sil': '32057',
  'paradela': '27042',
  'paramo': '27043',
  'paramo, o': '27043',
  'pastoriza': '27044',
  'pastoriza, a': '27044',
  'pazos de borben': '36037',
  'pedrafita do cebreiro': '27045',
  'pereiro de aguiar': '32058',
  'pereiro de aguiar, o': '32058',
  'peroxa': '32059',
  'peroxa, a': '32059',
  'petin': '32060',
  'pino': '15066',
  'pino, o': '15066',
  'pinor': '32061',
  'pobra de trives': '32063',
  'pobra de trives, a': '32063',
  'pobra do brollon': '27047',
  'pobra do brollon, a': '27047',
  'pobra do caraminal': '15067',
  'pobra do caraminal, a': '15067',
  'poio': '36041',
  'pol': '27046',
  'ponte caldelas': '36043',
  'ponteareas': '36042',
  'ponteceso': '15068',
  'pontecesures': '36044',
  'pontedeume': '15069',
  'pontedeva': '32064',
  'pontenova': '27048',
  'pontenova, a': '27048',
  'pontes de garcia rodriguez': '15070',
  'pontes de garcia rodriguez, as': '15070',
  'pontevedra': '36038',
  'porqueira': '32062',
  'porrino': '36039',
  'porrino, o': '36039',
  'portas': '36040',
  'porto do son': '15071',
  'portodo son': '15071',
  'portomarin': '27049',
  'punxin': '32065',
  'quintela de leirado': '32066',
  'quiroga': '27050',
  'rabade': '27056',
  'rairiz de veiga': '32067',
  'ramiras': '32068',
  'redondela': '36045',
  'rianxo': '15072',
  'ribadavia': '32069',
  'ribadeo': '27051',
  'ribadumia': '36046',
  'ribas de sil': '27052',
  'ribeira': '15073',
  'ribeira de piquin': '27053',
  'rios': '32071',
  'riotorto': '27054',
  'rodeiro': '36047',
  'rois': '15074',
  'rosal': '36048',
  'rosal, o': '36048',
  'rua': '32072',
  'rua, a': '32072',
  'rubia': '32073',
  'sada': '15075',
  'salceda de caselas': '36049',
  'salvaterra de mino': '36050',
  'samos': '27055',
  'san amaro': '32074',
  'san cibrao das vinas': '32075',
  'san cristovo de cea': '32076',
  'san sadurnino': '15076',
  'san xoan de rio': '32070',
  'sandias': '32077',
  'santa comba': '15077',
  'santiago': '15078',
  'santiago de compostela': '15078',
  'santiso': '15079',
  'sanxenxo': '36051',
  'sarreaus': '32078',
  'sarria': '27057',
  'savinao': '27058',
  'savinao, o': '27058',
  'silleda': '36052',
  'sober': '27059',
  'sobrado': '15080',
  'somozas': '15081',
  'somozas, as': '15081',
  'soutomaior': '36053',
  'taboada': '27060',
  'taboadela': '32079',
  'teixeira': '32080',
  'teixeira, a': '32080',
  'teo': '15082',
  'toen': '32081',
  'tomino': '36054',
  'toques': '15083',
  'tordoia': '15084',
  'touro': '15085',
  'trabada': '27061',
  'trasmiras': '32082',
  'trazo': '15086',
  'triacastela': '27062',
  'tui': '36055',
  'val do dubra': '15088',
  'valadouro': '27063',
  'valadouro, o': '27063',
  'valdovino': '15087',
  'valga': '36056',
  'vedra': '15089',
  'veiga': '32083',
  'veiga, a': '32083',
  'verea': '32084',
  'verin': '32085',
  'viana do bolo': '32086',
  'vicedo': '27064',
  'vicedo, o': '27064',
  'vigo': '36057',
  'vila de cruces': '36059',
  'vilaboa': '36058',
  'vilagarcia': '36060',
  'vilagarcia de arousa': '36060',
  'vilalba': '27065',
  'vilamarin': '32087',
  'vilamartin de valdeorras': '32088',
  'vilanova': '36061',
  'vilanova de arousa': '36061',
  'vilar de barrio': '32089',
  'vilar de santos': '32090',
  'vilardevos': '32091',
  'vilarino de conso': '32092',
  'vilarmaior': '15091',
  'vilasantar': '15090',
  'vimianzo': '15092',
  'viveiro': '27066',
  'xermade': '27021',
  'xinzo de limia': '32032',
  'xove': '27025',
  'xunqueira de ambia': '32036',
  'xunqueira de espadanedo': '32037',
  'zas': '15093',
}


def _get_ine_for_municipio(municipio: str | None) -> str | None:
  if not municipio:
    return None
  key = _norm_text(municipio)
  return _MUNICIPIO_INE.get(key)


# Caché para la capa WMS actual del planeamiento de cada municipio
_SIOTUGA_WMS_CACHE: dict[str, dict] = {}


def _fetch_siotuga_wms_layer(ine_code: str) -> dict:
  """Obtiene la capa WMS del planeamiento vigente de un municipio desde SIOTUGA.
  Devuelve {layer_name, plan_title, approval_date, wms_url} o {error: ...}.
  """
  import time
  cache_key = ine_code
  cached = _SIOTUGA_WMS_CACHE.get(cache_key)
  if cached and (time.time() - cached.get('_ts', 0)) < 3600:
    return {k: v for k, v in cached.items() if k != '_ts'}
  wms_base = f'https://siotuga.xunta.gal/siotuga/ws?codine={ine_code}'
  try:
    import urllib.request
    url = f'{wms_base}&SERVICE=WMS&REQUEST=GetCapabilities&version=1.3.0'
    req = urllib.request.Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
      xml = resp.read().decode('utf-8', errors='replace')
    # Buscar capas de clasificación (3CLAS) del plan vigente (no Histórico, no MP)
    # Las capas tienen formato: _{INE}_{TIPO}_{FECHA}_AD_3CLAS_{IDDOC}
    import re
    # Buscar todos los Name> de capas que contienen _AD_3CLAS_
    layer_matches = re.findall(
      r'<Name>([^<]*_AD_3CLAS_\d+)</Name>', xml
    )
    # Buscar títulos para identificar el plan vigente (no Hco:, no MP)
    title_matches = re.findall(
      r'<Title>([^<]*Clasificaci[oó]n[^<]*)</Title>', xml
    )
    # Encontrar la capa del plan vigente: la que tiene "PXOM" o "Plan Xeral" en el título
    # y NO tiene "Hco:" ni "Modificación Puntual"
    best_layer = None
    best_title = None
    best_date = None
    # Buscar bloques Name+Title juntos
    blocks = re.findall(
      r'<Name>([^<]*_AD_3CLAS_\d+)</Name>\s*<Title>([^<]*)</Title>', xml
    )
    for layer_name, title in blocks:
      # Saltar históricos y modificaciones puntuales
      if 'Hco:' in title or 'Hco.' in title:
        continue
      if 'Modificación Puntual' in title:
        continue
      # Preferir PXOM (plan vigente)
      if 'PXOM' in layer_name or 'Plan Xeral' in title or 'PLAN XERAL' in title:
        best_layer = layer_name
        best_title = title
        # Extraer fecha del nombre: _36057_PXOM_202505_AD_3CLAS_28719
        date_match = re.search(r'_(\d{6})_AD_', layer_name)
        if date_match:
          ym = date_match.group(1)
          best_date = f'{ym[:4]}-{ym[4:6]}'
        break
    # Si no encontramos PXOM, usar la primera capa no histórica
    if not best_layer and layer_matches:
      best_layer = layer_matches[0]
      if title_matches:
        best_title = title_matches[0]
    if best_layer:
      result = {
        'layer_name': best_layer,
        'plan_title': best_title or 'Plan vigente',
        'approval_date': best_date,
        'wms_base': wms_base,
      }
      _SIOTUGA_WMS_CACHE[cache_key] = {**result, '_ts': time.time()}
      return result
    return {'error': 'No se encontró capa de clasificación vigente'}
  except Exception as e:
    return {'error': str(e)}


def _build_siotuga_wms_getmap_url(ine_code: str, lon: float, lat: float, layer_name: str, wms_base: str) -> str:
  """Construye una URL GetMap del WMS de SIOTUGA centrada en unas coordenadas."""
  delta = 0.005  # ~500m
  bbox = f'{lon-delta},{lat-delta},{lon+delta},{lat+delta}'
  return (
    f'{wms_base}&SERVICE=WMS&REQUEST=GetMap&version=1.3.0'
    f'&layers={layer_name}&styles=&crs=EPSG:4326'
    f'&bbox={bbox}&width=400&height=400&format=image/png&transparent=true'
  )


def _is_in_galicia(lon: float, lat: float) -> bool:
  """Valida si unas coordenadas están dentro del bounding box de Galicia."""
  return (
    _GALICIA_BBOX['lon_min'] <= lon <= _GALICIA_BBOX['lon_max'] and
    _GALICIA_BBOX['lat_min'] <= lat <= _GALICIA_BBOX['lat_max']
  )


# Caché con TTL para datos oficiales
_OFFICIAL_CACHE: dict[tuple, tuple[float, Any]] = {}
_OFFICIAL_CACHE_TTL = 300  # 5 minutos


def _official_cache_get(key: tuple) -> Any | None:
  import time as _t
  entry = _OFFICIAL_CACHE.get(key)
  if entry is None:
    return None
  ts, val = entry
  if _t.time() - ts > _OFFICIAL_CACHE_TTL:
    _OFFICIAL_CACHE.pop(key, None)
    return None
  return val


def _official_cache_set(key: tuple, val: Any) -> None:
  import time as _t
  _OFFICIAL_CACHE[key] = (_t.time(), val)


def _fetch_catastro_by_coords(lon: float, lat: float, srs: str = 'EPSG:4326') -> dict:
  # Validar que las coordenadas están en Galicia
  if srs == 'EPSG:4326' and not _is_in_galicia(lon, lat):
    return {'found': False, 'error': 'Coordenadas fuera de Galicia', 'available': False}
  cache_key = ('catastro', 'coords', round(lon, 6), round(lat, 6), srs)
  cached = _official_cache_get(cache_key)
  if cached is not None:
    return cached
  base = 'https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/ovccoordenadas.asmx/Consulta_RCCOOR'
  url = f"{base}?{urlencode({'SRS': srs, 'Coordenada_X': lon, 'Coordenada_Y': lat})}"
  req = Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
  with urlopen(req, timeout=10) as resp:
    result = _parse_catastro_rccoor_xml(resp.read())
  _official_cache_set(cache_key, result)
  return result


def _fetch_catastro_by_ref(refcat: str) -> dict:
  rc = ''.join(ch for ch in (refcat or '') if ch.isalnum()).upper()
  if len(rc) < 14:
    return {'found': False, 'refcat': rc or None}
  base = 'https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/ovccoordenadas.asmx/Consulta_CPMRC'
  url = f"{base}?{urlencode({'Provincia': '', 'Municipio': '', 'SRS': 'EPSG:4326', 'RC': rc[:14]})}"
  req = Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
  with urlopen(req, timeout=20) as resp:
    raw = resp.read()
  root = ET.fromstring(raw)
  for elem in root.iter():
    if '}' in elem.tag:
      elem.tag = elem.tag.rsplit('}', 1)[-1]
  coord = root.find('.//coord')
  if coord is None:
    return {'found': False, 'refcat': rc}
  x = coord.findtext('./geo/xcen') or coord.findtext('./xcen')
  y = coord.findtext('./geo/ycen') or coord.findtext('./ycen')
  return {
    'found': True,
    'refcat': coord.findtext('./pc/pc1') and ((coord.findtext('./pc/pc1') or '') + (coord.findtext('./pc/pc2') or '')) or rc,
    'direccion': coord.findtext('./ldt') or None,
    'srs': coord.findtext('./geo/srs') or coord.findtext('./srs') or 'EPSG:4326',
    'x': x,
    'y': y,
  }


def _fetch_siose_precheck(lon: float, lat: float, delta: float = 0.0015) -> dict:
  bb = f"{lon-delta},{lat-delta},{lon+delta},{lat+delta},EPSG:4326"
  cache_key = ('siose', bb)
  cached = _official_cache_get(cache_key)
  if cached is not None:
    return cached
  wfs_cache_key = (bb, 'lcv:LandCoverUnit', 'EPSG:4326', '2.0.0')
  data = _siose_cache_get(wfs_cache_key, max_age=120)
  if data is None:
    params = {
      'service': 'WFS',
      'request': 'GetFeature',
      'version': '2.0.0',
      'typeNames': 'lcv:LandCoverUnit',
      'srsName': 'EPSG:4326',
      'bbox': bb,
      'outputFormat': 'application/gml+xml; version=3.2',
      'count': 50,
    }
    url = f"{SIOSE_WFS_URL}?{urlencode(params)}"
    req = Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
    with urlopen(req, timeout=15) as resp:
      data = _parse_siose_gml(resp.read())
    _siose_cache_set(wfs_cache_key, data)
  feats = data.get('features') or []
  labels: list[str] = []
  alerts: list[str] = []
  for feat in feats[:8]:
    props = feat.get('properties') or {}
    label = None
    for k in ('label', 'legend', 'clasificacion', 'desc_', 'descripcion', 'cover', 'LC_Value', 'LU_Value', 'landcover', 'land_cover'):
      v = props.get(k)
      if isinstance(v, str) and v.strip():
        label = v.strip()
        break
    if not label:
      for v in props.values():
        if isinstance(v, str) and v.strip() and len(v.strip()) > 2:
          label = v.strip()
          break
    if label:
      labels.append(label)
      low = _norm_text(label)
      # Agua y zonas húmedas
      if any(t in low for t in ('agua', 'wetland', 'humedal', 'marisma', 'costa', 'playa', 'rivera', 'rio', 'cauce', 'lago', 'embalse', 'canal')):
        alerts.append(f'Entorno potencialmente sensible por presencia de {label} — revisar afección a dominio público hidráulico, costas o zonas húmedas')
      # Espacios naturales y forestales
      elif any(t in low for t in ('forest', 'bosque', 'arbolado', 'natural', 'vegetacion', 'matorral', 'pasto', 'pradera')):
        alerts.append(f'Revisar afección ambiental/paisajística por cobertura natural: {label}')
      # Zonas protegidas
      elif any(t in low for t in ('protegido', 'proteccion', 'red natura', 'zepa', 'lic', 'reserva', 'parque')):
        alerts.append(f'Posible espacio protegido detectado: {label} — verificar figura de protección')
      # Agrícola
      elif any(t in low for t in ('agricol', 'cultivo', 'regadio', 'secano', 'viña', 'viñedo', 'huerta')):
        alerts.append(f'Uso agrícola detectado: {label} — verificar compatibilidad con uso urbanístico propuesto')
      # Industrial
      elif any(t in low for t in ('industrial', 'almacen', 'taller', 'fabrica', 'cantera', 'mineria')):
        alerts.append(f'Uso industrial detectado: {label} — verificar compatibilidad y posibles afecciones')
  result = {
    'available': True,
    'bbox': bb,
    'sample_count': len(feats),
    'land_cover_labels': list(dict.fromkeys(labels))[:5],
    'alerts': list(dict.fromkeys(alerts))[:6],
    'disclaimer': 'Prechequeo preliminar basado en SIOSE; no sustituye verificación sectorial oficial.',
  }
  _official_cache_set(cache_key, result)
  return result


def _safe_fetch_catastro(lon: float, lat: float) -> dict:
  try:
    result = _fetch_catastro_by_coords(lon, lat)
    # Si encontramos refcat, intentar obtener datos ampliados
    refcat = result.get('refcat')
    if refcat and len(refcat) >= 14:
      try:
        details = _fetch_catastro_details_by_ref(refcat)
        if details:
          result.update(details)
      except Exception:
        pass
    return result
  except Exception as e:
    return {'available': False, 'error': str(e)}


def _safe_fetch_siose(lon: float, lat: float) -> dict:
  try:
    return _fetch_siose_precheck(lon, lat)
  except Exception as e:
    return {'available': False, 'alerts': [], 'error': str(e)}


def _fetch_catastro_details_by_ref(refcat: str) -> dict:
  """Obtiene datos ampliados de una parcela por referencia catastral.
  Usa Consulta_DNPRC del OVC que devuelve datos no protegidos.
  Maneja diferentes esquemas XML del Catastro.
  """
  cache_key = ('catastro', 'details', refcat[:14])
  cached = _official_cache_get(cache_key)
  if cached is not None:
    return cached
  rc = ''.join(ch for ch in (refcat or '') if ch.isalnum()).upper()[:14]
  if len(rc) < 14:
    return {}
  base = 'https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCSoporteWS.asmx/Consulta_DNPRC'
  url = f"{base}?{urlencode({'Provincia': '', 'Municipio': '', 'RC': rc, 'Localizador': ''})}"
  req = Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
  with urlopen(req, timeout=10) as resp:
    raw = resp.read()
  try:
    root = ET.fromstring(raw)
  except Exception:
    return {}
  for elem in root.iter():
    if '}' in elem.tag:
      elem.tag = elem.tag.rsplit('}', 1)[-1]
  result: dict = {}
  # Buscar el nodo bi (bien inmueble) en cualquier posición
  bi = root.find('.//bico/bi')
  if bi is None:
    # Intentar buscar directamente bi
    for elem in root.iter():
      if elem.tag.endswith('bi'):
        bi = elem
        break
  if bi is not None:
    # Superficie construida — buscar en múltiples ubicaciones posibles
    for path in ['.//lscons/dcons/scon', './/dcons/scon', './/scon', './/cons/scon']:
      scon = bi.findtext(path)
      if scon:
        val = _try_float(scon)
        if val and val > 0:
          result['superficie_construida_m2'] = val
          break
    # Superficie del terreno — buscar en múltiples ubicaciones
    for path in ['.//sfterreno', './/stf', './/dt/sfterreno', './/dt/stf', './/superficie']:
      sf = bi.findtext(path)
      if sf:
        val = _try_float(sf)
        if val and val > 0:
          result['superficie_terreno_m2'] = val
          break
    # Uso principal — buscar en múltiples ubicaciones
    for path in ['.//luso/fpu', './/luso/cuo', './/luso', './/fpu', './/uso']:
      uso = bi.findtext(path)
      if uso and uso.strip():
        result['uso_principal'] = uso.strip()
        break
    # Año de construcción
    for path in ['.//ant/e1', './/ant', './/e1', './/anio', './/ano']:
      año = bi.findtext(path)
      if año:
        val = _try_int(año)
        if val and 1800 < val < 2100:
          result['anio_construccion'] = val
          break
  # También buscar en el nodo ctrl para datos del control
  ctrl = root.find('.//ctrl')
  if ctrl is not None:
    val = ctrl.findtext('.//val')
    if val:
      result.setdefault('valor_catastral', _try_float(val))
  _official_cache_set(cache_key, result)
  return result


def _try_float(s: str):
  try:
    return float(s)
  except Exception:
    return None


def _try_int(s: str):
  try:
    return int(s)
  except Exception:
    return None


def _build_official_context(municipio: str | None = None, subzona: str | None = None, geometry: dict | None = None, lon: float | None = None, lat: float | None = None) -> dict:
  import datetime as _pdt
  query_ts = _pdt.datetime.now(_pdt.timezone.utc).isoformat()
  ctx: dict = {
    'municipio': municipio,
    'subzona': subzona,
    'catastro': {'available': False},
    'planeamiento': {'available': False},
    'siotuga': {'available': True, 'note': 'Contexto apoyado en inventario municipal y servicios WMS/WFS/proxy ya integrados'},
    'afecciones_preliminares': {'available': False, 'alerts': []},
    'provenance': {
      'query_timestamp': query_ts,
      'api_version': API_VERSION,
      'sources': [
        {'name': 'Catastro (OVC)', 'url': 'https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCBusqueda.aspx', 'type': 'coordenadas/referencia'},
        {'name': 'SIOTUGA', 'url': 'https://siotuga.xunta.gal/siotuga/inventario', 'type': 'planeamiento territorial'},
        {'name': 'SIOSE (IDEE)', 'url': 'https://servicios.idee.es/wfs-inspire/ocupacion-suelo', 'type': 'ocupación del suelo'},
        {'name': 'Inventario municipal', 'url': '', 'type': 'planeamiento vigente'},
      ],
    },
  }
  # Construir enlaces específicos a fuentes oficiales con datos de la parcela
  cat_refcat = None
  cat_lon = None
  cat_lat = None
  if municipio:
    inv = planeamento_inventario(municipio)
    rows = inv.get('rows') or []
    ctx['planeamiento'] = {
      'available': bool(rows),
      'count': len(rows),
      'rows': rows[:5],
    }
  if lon is None or lat is None:
    if geometry:
      try:
        lon, lat = centroid_lonlat_from_geojson(geometry)
      except Exception as e:
        ctx['catastro'] = {'available': False, 'error': str(e)}
        return ctx
  if lon is not None and lat is not None:
    # Paralelizar consultas a Catastro y SIOSE para reducir tiempo total
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
      futures = {
        'catastro': pool.submit(_safe_fetch_catastro, lon, lat),
        'siose': pool.submit(_safe_fetch_siose, lon, lat),
      }
      for name, fut in futures.items():
        try:
          results[name] = fut.result(timeout=15)
        except Exception as e:
          results[name] = {'available': False, 'error': str(e)}
    cat = results.get('catastro') or {}
    if cat.get('found') or cat.get('available'):
      cat.update({'available': True, 'query_lon': lon, 'query_lat': lat})
      # Validación de consistencia: coordenadas del catastro vs consulta
      cat_x = _try_float(cat.get('x') or '')
      cat_y = _try_float(cat.get('y') or '')
      if cat_x is not None and cat_y is not None:
        dist = ((cat_x - lon) ** 2 + (cat_y - lat) ** 2) ** 0.5
        cat['coord_consistency'] = 'ok' if dist < 0.01 else 'mismatch'
      # Validación de municipio
      cat_muni = _norm_text(cat.get('municipio_catastral') or '')
      query_muni = _norm_text(municipio or '')
      if cat_muni and query_muni:
        cat['municipio_consistency'] = 'ok' if cat_muni == query_muni else 'mismatch'
      ctx['catastro'] = cat
    else:
      ctx['catastro'] = cat
    siose = results.get('siose') or {}
    ctx['afecciones_preliminares'] = siose
    # Indicador de calidad de datos
    sources_ok = sum([
      1 if cat.get('found') else 0,
      1 if siose.get('available') else 0,
      1 if ctx.get('planeamiento', {}).get('available') else 0,
    ])
    ctx['data_quality'] = 'alta' if sources_ok >= 2 else ('media' if sources_ok == 1 else 'baja')
    # Construir enlaces específicos a fuentes oficiales con datos de la parcela
    links: list[dict] = []
    # Catastro: URL directa a la ficha de la parcela por coordenadas
    cat_qlon = cat.get('query_lon') or lon
    cat_qlat = cat.get('query_lat') or lat
    if cat_qlon is not None and cat_qlat is not None:
      # URL que busca automáticamente por coordenadas y muestra la parcela
      cat_url = (
        f"https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCListaBienes.aspx"
        f"?pest=coordenadas&latitud={cat_qlat}&longitud={cat_qlon}"
        f"&tipoCoordenadas=2&TipUR=Coor&from=OVCBusqueda&final="
      )
      cat_label = f'Ver parcela en Catastro ({cat_qlon:.4f}, {cat_qlat:.4f})'
      links.append({
        'name': 'Catastro',
        'url': cat_url,
        'label': cat_label,
      })
    # SIOTUGA: enlace al WMS GetMap centrado en la parcela + inventario
    ine = _get_ine_for_municipio(municipio)
    if ine:
      # Obtener capa WMS del planeamiento vigente
      wms_info = _fetch_siotuga_wms_layer(ine)
      if wms_info.get('layer_name') and cat_qlon is not None and cat_qlat is not None:
        getmap_url = _build_siotuga_wms_getmap_url(
          ine, cat_qlon, cat_qlat,
          wms_info['layer_name'], wms_info['wms_base']
        )
        links.append({
          'name': 'SIOTUGA',
          'url': getmap_url,
          'label': f'Ver zonificación del planeamiento de {municipio} (mapa)',
        })
        # También añadir el plan vigente al contexto
        ctx.setdefault('siotuga', {}).update({
          'plan_title': wms_info.get('plan_title'),
          'approval_date': wms_info.get('approval_date'),
          'wms_layer': wms_info.get('layer_name'),
        })
      # Enlace al inventario para descargar documentos
      links.append({
        'name': 'SIOTUGA (documentos)',
        'url': f'https://siotuga.xunta.gal/siotuga/inventario?concello={ine}&lang=es_ES',
        'label': f'Documentos del planeamiento de {municipio}',
      })
    else:
      links.append({
        'name': 'SIOTUGA',
        'url': 'https://siotuga.xunta.gal/siotuga/inventario?lang=es_ES',
        'label': 'Inventario de planeamiento',
      })
    # SIOSE: enlace GetFeatureInfo del WMS que devuelve los datos de la parcela
    if cat_qlon is not None and cat_qlat is not None:
      siose_bbox = f"{cat_qlon-0.001},{cat_qlat-0.001},{cat_qlon+0.001},{cat_qlat+0.001}"
      siose_url = (
        f"https://servicios.idee.es/wms-inspire/ocupacion-suelo"
        f"?service=WMS&request=GetFeatureInfo&version=1.3.0"
        f"&layers=LC.LandCoverSurfaces&query_layers=LC.LandCoverSurfaces"
        f"&crs=CRS:84&bbox={siose_bbox}&width=101&height=101&i=50&j=50"
        f"&info_format=text/html"
      )
      links.append({
        'name': 'SIOSE',
        'url': siose_url,
        'label': 'Ver ocupación del suelo en esta parcela',
      })
    ctx['official_links'] = links
  return ctx


@app.get('/zoning/building-diagnostic')
def zoning_building_diagnostic(
  height_m: float | None = None,
  levels: int | None = None,
  footprint_m2: float | None = None,
  subzona: str | None = None,
  municipio: str | None = None,
  lon: float | None = None,
  lat: float | None = None,
):
  """Diagnóstico comparativo entre un edificio y los parámetros normativos de su subzona.
  Devuelve una tabla comparativa detallada con veredicto y margen/exceso.
  """
  # Buscar subzona por nombre o por coordenadas
  subzone_props = None
  if subzona and municipio:
    try:
      from src.subzones_service import find_subzone_by_name
      subzone_props = find_subzone_by_name(municipio, subzona)
    except Exception:
      pass
  if subzone_props is None and lon is not None and lat is not None:
    try:
      from src.subzones_service import find_subzone_for_point
      subzone_props = find_subzone_for_point(lon, lat)
    except Exception:
      pass

  if not subzone_props:
    return {
      'available': False,
      'error': 'No se encontró subzona normativa para los parámetros proporcionados',
      'comparisons': [],
      'verdict': 'sin_dato',
    }

  altura_max = subzone_props.get('altura_maxima_m')
  ocupacion_max = subzone_props.get('ocupacion_max')
  edificabilidad_max = subzone_props.get('edificabilidad_max_m2_m2')
  retranqueo_min = subzone_props.get('retranqueo_min_m')

  comparisons: list[dict] = []
  verdict = 'compatible'
  issues: list[str] = []

  # Comparación de altura
  if height_m is not None and altura_max is not None:
    try:
      h = float(height_m)
      lim = float(altura_max)
      diff = round(h - lim, 2)
      if diff <= 0:
        comparisons.append({
          'parametro': 'Altura',
          'valor_edificio': f'{h} m',
          'valor_normativo': f'{lim} m',
          'diferencia': f'{abs(diff)} m margen',
          'cumple': True,
          'detalle': f'El edificio está {abs(diff)} m por debajo del máximo permitido',
        })
      else:
        comparisons.append({
          'parametro': 'Altura',
          'valor_edificio': f'{h} m',
          'valor_normativo': f'{lim} m',
          'diferencia': f'{diff} m exceso',
          'cumple': False,
          'detalle': f'El edificio supera el máximo en {diff} m',
        })
        verdict = 'supera_altura'
        issues.append(f'Altura: exceso de {diff} m')
    except (ValueError, TypeError):
      comparisons.append({
        'parametro': 'Altura',
        'valor_edificio': '—',
        'valor_normativo': f'{altura_max} m',
        'diferencia': '—',
        'cumple': None,
        'detalle': 'No se pudo comparar la altura',
      })
  elif altura_max is not None:
    comparisons.append({
      'parametro': 'Altura',
      'valor_edificio': '—',
      'valor_normativo': f'{altura_max} m',
      'diferencia': '—',
      'cumple': None,
      'detalle': 'Altura del edificio no proporcionada',
    })

  # Comparación de plantas
  if levels is not None and altura_max is not None:
    try:
      allowed_floors = max(1, int(float(altura_max) / 3.0))
      actual_floors = int(levels)
      if actual_floors <= allowed_floors:
        comparisons.append({
          'parametro': 'Plantas',
          'valor_edificio': f'{actual_floors}',
          'valor_normativo': f'≤ {allowed_floors}',
          'diferencia': f'{allowed_floors - actual_floors} margen',
          'cumple': True,
          'detalle': f'{actual_floors} plantas dentro del máximo de {allowed_floors}',
        })
      else:
        comparisons.append({
          'parametro': 'Plantas',
          'valor_edificio': f'{actual_floors}',
          'valor_normativo': f'≤ {allowed_floors}',
          'diferencia': f'{actual_floors - allowed_floors} exceso',
          'cumple': False,
          'detalle': f'{actual_floors} plantas superan el máximo de {allowed_floors}',
        })
        if verdict == 'compatible':
          verdict = 'supera_altura'
        issues.append(f'Plantas: {actual_floors - allowed_floors} de exceso')
    except (ValueError, TypeError):
      pass

  # Comparación de ocupación (si tenemos footprint)
  if footprint_m2 is not None and ocupacion_max is not None:
    try:
      occ_limit = float(ocupacion_max)
      # Necesitaríamos el área de la parcela para comparar
      comparisons.append({
        'parametro': 'Ocupación',
        'valor_edificio': f'{footprint_m2} m² (huella)',
        'valor_normativo': f'{occ_limit * 100}% máx.',
        'diferencia': '—',
        'cumple': None,
        'detalle': 'Se necesita el área de la parcela para verificar la ocupación',
      })
    except (ValueError, TypeError):
      pass

  # Parámetros normativos sin comparación (informativos)
  if edificabilidad_max is not None:
    comparisons.append({
      'parametro': 'Edificabilidad',
      'valor_edificio': '—',
      'valor_normativo': f'{edificabilidad_max} m²/m²',
      'diferencia': '—',
      'cumple': None,
      'detalle': 'Edificabilidad máxima de la subzona',
    })
  if retranqueo_min is not None:
    comparisons.append({
      'parametro': 'Retranqueo mín.',
      'valor_edificio': '—',
      'valor_normativo': f'{retranqueo_min} m',
      'diferencia': '—',
      'cumple': None,
      'detalle': 'Retranqueo mínimo a linderos',
    })

  is_pilot = str(subzone_props.get('normative_status') or '').lower() == 'pilot'
  if is_pilot:
    for comparison in comparisons:
      comparison['detalle'] = f"Dato piloto: {comparison.get('detalle') or ''}".strip()
      if comparison.get('cumple') is not None:
        comparison['resultado_orientativo'] = 'dentro' if comparison['cumple'] else 'supera'
        comparison['cumple'] = None
    pilot_verdict = 'orientativo_dentro' if verdict == 'compatible' else 'orientativo_supera'
    return {
      'available': True,
      'subzona': subzone_props.get('subzona'),
      'municipio': subzone_props.get('municipio') or municipio,
      'comparisons': comparisons,
      'verdict': pilot_verdict,
      'issues': [],
      'observations': issues,
      'normative_status': 'pilot',
      'source': subzone_props.get('fuente'),
      'warning': 'Diagnóstico orientativo basado en una subzona piloto no oficial.',
      'summary': 'Comparación orientativa; requiere verificación en el planeamiento oficial',
    }
  return {
    'available': True,
    'subzona': subzone_props.get('subzona'),
    'municipio': subzone_props.get('municipio') or municipio,
    'comparisons': comparisons,
    'verdict': verdict,
    'issues': issues,
    'normative_status': 'verified',
    'source': subzone_props.get('fuente'),
    'summary': 'Todos los parámetros cumplen' if verdict == 'compatible' else f'{len(issues)} parámetro(s) no cumplen',
  }


@app.get('/official/catastro/by-coords')
def official_catastro_by_coords(lon: float, lat: float, srs: str = 'EPSG:4326'):
  try:
    return _fetch_catastro_by_coords(lon, lat, srs=srs)
  except HTTPError as e:
    raise HTTPException(status_code=502, detail=f'Catastro upstream error: {getattr(e, "code", 0)}')
  except URLError as e:
    raise HTTPException(status_code=502, detail=f'Catastro network error: {e}')
  except Exception as e:
    raise HTTPException(status_code=502, detail=f'Catastro error: {e}')


@app.get('/official/catastro/by-ref')
def official_catastro_by_ref(refcat: str):
  try:
    return _fetch_catastro_by_ref(refcat)
  except HTTPError as e:
    raise HTTPException(status_code=502, detail=f'Catastro upstream error: {getattr(e, "code", 0)}')
  except URLError as e:
    raise HTTPException(status_code=502, detail=f'Catastro network error: {e}')
  except Exception as e:
    raise HTTPException(status_code=502, detail=f'Catastro error: {e}')


@app.get('/official/context')
def official_context(municipio: Optional[str] = None, subzona: Optional[str] = None, lon: Optional[float] = None, lat: Optional[float] = None):
  return _build_official_context(municipio=municipio, subzona=subzona, lon=lon, lat=lat)


def _classify_land_cover(label: str) -> str:
  low = _norm_text(label)
  if any(t in low for t in ('agua', 'wetland', 'humedal', 'marisma', 'costa', 'playa', 'rivera', 'rio', 'cauce', 'lago')):
    return 'sensible_agua'
  if any(t in low for t in ('forest', 'bosque', 'arbolado', 'natural', 'vegetacion', 'matorral', 'pasto')):
    return 'sensible_natural'
  if any(t in low for t in ('artificial', 'constru', 'urban', 'industrial', 'via', 'carretera', 'infraestructura')):
    return 'artificial'
  return 'otros'


def _fetch_siose_afecciones_geojson(bbox: str) -> dict:
  bb = bbox.strip()
  if bb.count(',') == 3:
    bb = f"{bb},EPSG:4326"
  cache_key = (bb, 'lcv:LandCoverUnit', 'EPSG:4326', '2.0.0')
  data = _siose_cache_get(cache_key, max_age=120)
  if data is None:
    params = {
      'service': 'WFS',
      'request': 'GetFeature',
      'version': '2.0.0',
      'typeNames': 'lcv:LandCoverUnit',
      'srsName': 'EPSG:4326',
      'bbox': bb,
      'outputFormat': 'application/gml+xml; version=3.2',
      'count': 500,
    }
    url = f"{SIOSE_WFS_URL}?{urlencode(params)}"
    req = Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
    with urlopen(req, timeout=20) as resp:
      data = _parse_siose_gml(resp.read())
    _siose_cache_set(cache_key, data)
  out_features = []
  for feat in data.get('features') or []:
    props = feat.get('properties') or {}
    label = None
    for k in ('label', 'legend', 'clasificacion', 'desc_', 'descripcion', 'cover', 'LC_Value', 'LU_Value'):
      v = props.get(k)
      if isinstance(v, str) and v.strip():
        label = v.strip()
        break
    if not label:
      for v in props.values():
        if isinstance(v, str) and v.strip():
          label = v.strip()
          break
    if not label:
      label = 'Sin clasificar'
    clase = _classify_land_cover(label)
    alerta = None
    if clase == 'sensible_agua':
      alerta = f'Entorno potencialmente sensible por presencia de {label}'
    elif clase == 'sensible_natural':
      alerta = f'Revisar afección ambiental/paisajística por cobertura {label}'
    out_features.append({
      'type': 'Feature',
      'geometry': feat.get('geometry'),
      'properties': {
        'label': label,
        'clase': clase,
        'alerta': alerta,
        'source': 'SIOSE (IDEE)',
      },
    })
  return {'type': 'FeatureCollection', 'features': out_features}


@app.get('/official/afecciones')
def official_afecciones(bbox: str):
  """Devuelve GeoJSON de coberturas SIOSE clasificadas por tipo de afección preliminar.
  Parámetros:
    bbox: minx,miny,maxx,maxy en EPSG:4326
  """
  try:
    return _fetch_siose_afecciones_geojson(bbox)
  except HTTPError as e:
    raise HTTPException(status_code=502, detail=f'SIOSE upstream error: {getattr(e, "code", 0)}')
  except URLError as e:
    raise HTTPException(status_code=502, detail=f'SIOSE network error: {e}')
  except Exception as e:
    raise HTTPException(status_code=502, detail=f'Afecciones error: {e}')


@app.get('/official/siotuga-wms')
def official_siotuga_wms(municipio: Optional[str] = None):
  """Devuelve la URL del WMS de SIOTUGA para el planeamiento vigente del municipio.
  Usado por el visor para mostrar la zonificación oficial como capa de fondo.
  """
  ine = _get_ine_for_municipio(municipio) if municipio else None
  if not ine:
    return {'available': False, 'error': 'Municipio no encontrado en el mapeo INE'}
  wms_info = _fetch_siotuga_wms_layer(ine)
  if wms_info.get('layer_name'):
    return {
      'available': True,
      'ine': ine,
      'layer_name': wms_info['layer_name'],
      'plan_title': wms_info.get('plan_title'),
      'approval_date': wms_info.get('approval_date'),
      'wms_base': wms_info['wms_base'],
      'proxy_url': f'/official/siotuga-wms/proxy?ine={ine}&layer={wms_info["layer_name"]}&bbox={{bbox}}',
    }
  return {'available': False, 'error': wms_info.get('error', 'No se pudo obtener el WMS')}


@app.get('/official/siotuga-wms/proxy')
def official_siotuga_wms_proxy(
  ine: str,
  layer: str,
  bbox: str,
  width: int = 512,
  height: int = 512,
):
  """Proxy WMS para SIOTUGA. Evita problemas de CORS y arregla el orden de coordenadas.
  MapLibre envía bbox como lon,min,lat,min,lon,max,lat,max (EPSG:4326).
  WMS 1.3.0 con CRS:EPSG:4326 espera lat,min,lon,min,lat,max,lon,max.
  Usamos WMS 1.1.0 con SRS=EPSG:4326 que usa lon,lat order.
  """
  from fastapi.responses import Response
  parts = bbox.split(',')
  if len(parts) != 4:
    raise HTTPException(status_code=400, detail='bbox debe tener 4 valores')
  wms_base = f'https://siotuga.xunta.gal/siotuga/ws?codine={ine}'
  # WMS 1.1.0 usa SRS y bbox en lon,lat order (igual que MapLibre)
  url = (
    f'{wms_base}&SERVICE=WMS&REQUEST=GetMap&version=1.1.0'
    f'&layers={layer}&styles=&SRS=EPSG:4326'
    f'&bbox={bbox}&width={width}&height={height}'
    f'&format=image/png&transparent=true'
  )
  try:
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
      img_data = resp.read()
    return Response(content=img_data, media_type='image/png')
  except Exception as e:
    raise HTTPException(status_code=502, detail=f'Error proxy WMS SIOTUGA: {e}')


@app.get('/official/siotuga-wms/tile/{z}/{x}/{y}')
def official_siotuga_wms_tile(z: int, x: int, y: int, ine: str, layer: str):
  """Proxy XYZ→WMS para SIOTUGA. Convierte tiles XYZ (estilo Google/OSM)
  a peticiones WMS GetMap con el bbox correspondiente en EPSG:4326.
  Esto permite usar la capa WMS como source raster en MapLibre.
  """
  from fastapi.responses import Response
  import math
  # Convertir tile XYZ a bbox en EPSG:4326 (lon,lat)
  n = 2 ** z
  lon_min = x / n * 360.0 - 180.0
  lon_max = (x + 1) / n * 360.0 - 180.0
  # Latitud en proyección Web Mercator
  lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
  lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
  bbox = f'{lon_min},{lat_min},{lon_max},{lat_max}'
  wms_base = f'https://siotuga.xunta.gal/siotuga/ws?codine={ine}'
  url = (
    f'{wms_base}&SERVICE=WMS&REQUEST=GetMap&version=1.1.0'
    f'&layers={layer}&styles=&SRS=EPSG:4326'
    f'&bbox={bbox}&width=512&height=512'
    f'&format=image/png&transparent=true'
  )
  try:
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'NormativaGalicia/1.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
      img_data = resp.read()
    return Response(content=img_data, media_type='image/png')
  except Exception as e:
    raise HTTPException(status_code=502, detail=f'Error proxy WMS SIOTUGA: {e}')


# ------------------------------
# Análisis de sombras
# ------------------------------
class ShadowAnalysisRequest(BaseModel):
  geometry: dict
  height_m: float
  lat: float
  lon: float
  date: Optional[str] = None
  hour_utc: Optional[int] = None


@app.post('/zoning/shadow-analysis')
def zoning_shadow_analysis(req: ShadowAnalysisRequest):
  """Analiza la sombra proyectada por un edificio en un momento dado.

  Si no se especifica fecha/hora, usa el solsticio de invierno (21 dic) al mediodía solar.
  """
  import datetime as _dt
  if req.date:
    try:
      parts = req.date.split('-')
      date = _dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
      date = _dt.date(2025, 12, 21)
  else:
    date = _dt.date(2025, 12, 21)
  if req.hour_utc is not None:
    hours = [req.hour_utc]
  else:
    hours = [8, 10, 12, 14, 16, 18]
  return shadow_analysis_multi_hour(req.geometry, req.height_m, req.lat, req.lon, date, hours=hours)


@app.get('/zoning/shadow-analysis')
def zoning_shadow_analysis_get(
  lon: float,
  lat: float,
  height_m: float = 12.0,
  geometry: Optional[str] = None,
  date: Optional[str] = None,
  hour_utc: Optional[int] = None,
):
  """GET simplificado: analiza sombras para un punto y altura dados.

  Si no se pasa geometry, usa un cuadrado de 10x10 m centrado en (lon, lat).
  """
  import datetime as _dt
  import json as _json
  if geometry:
    try:
      geom = _json.loads(geometry)
    except Exception:
      geom = None
  else:
    d = 0.00005
    geom = {
      'type': 'Polygon',
      'coordinates': [[
        [lon - d, lat - d], [lon + d, lat - d],
        [lon + d, lat + d], [lon - d, lat + d],
        [lon - d, lat - d],
      ]],
    }
  if date:
    try:
      parts = date.split('-')
      dt_date = _dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
      dt_date = _dt.date(2025, 12, 21)
  else:
    dt_date = _dt.date(2025, 12, 21)
  if hour_utc is not None:
    hours = [hour_utc]
  else:
    hours = [8, 10, 12, 14, 16, 18]
  return shadow_analysis_multi_hour(geom, height_m, lat, lon, dt_date, hours=hours)


# ------------------------------
# Subzonas espaciales (Fase 2 GeoLibre)
# ------------------------------
@app.get("/planeamiento/subzonas")
def planeamento_subzonas(municipio: Optional[str] = None):
  """Devuelve el GeoJSON de subzonas espaciales piloto.

  Si se indica municipio, filtra por coincidencia case-insensitive sin acentos.
  """
  return get_subzones(municipio)


@app.get("/planeamiento/subzonas/municipios")
def planeamento_subzonas_municipios():
  """Devuelve la lista de municipios que tienen subzonas espaciales."""
  return {"municipios": list_municipios_with_subzones()}


@app.get("/planeamiento/subzonas/lookup")
def planeamento_subzonas_lookup(lon: float, lat: float):
  """Busca la subzona espacial que contiene el punto (lon, lat) en EPSG:4326."""
  props = find_subzone_for_point(lon, lat)
  if props is None:
    return {"found": False, "subzona": None}
  return {"found": True, "subzona": props}


@app.get("/proxy/osm-buildings")
def proxy_osm_buildings(municipio: str, limit: int = 800):
  """Devuelve edificios OSM en GeoJSON listos para extrusión 3D."""
  try:
    return get_osm_buildings_geojson(municipio, limit=limit)
  except Exception:
    return {"type": "FeatureCollection", "features": []}
