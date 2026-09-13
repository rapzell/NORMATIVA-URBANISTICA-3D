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
    gltf_to_glb_bytes as _gltf_to_glb_bytes,
    is_exhausted_feature,
    normalize_volume_export_format,
)
from src.report_service import render_assess_report_html as _render_assess_report_html
from src.subzones_service import get_subzones, list_municipios_with_subzones, find_subzone_for_point

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
import json as _json
import csv

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
    return {"ok": True, "provider": provider, "applied_path": path, "rows": rows_count}

# --- Redirecciones de conveniencia ---
@app.get("/")
async def root_redirect():
    # Ir directo al visor principal
    return RedirectResponse(url="/viewer")

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

@app.get("/proxy/siose")
async def proxy_siose(bbox: str, typeNames: str = "elu:LandCoverUnit", srsName: str = "EPSG:4326", version: str = "2.0.0", max_age: int = 15):
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
            "outputFormat": "application/json",
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
                try:
                    import json as _json
                    data = _json.loads(raw.decode("utf-8", "ignore"))
                except Exception:
                    return Response(content=raw, media_type=resp.headers.get('Content-Type', 'application/json'))
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
    html = _render_assess_report_html(body, res, logo=logo, title=title, client=client, project=project, snapshot_data_url=snap, brand_color=brand_color, signature=bool(signature or False), sign_by=sign_by, sign_place=sign_place, notes=notes, source_ref=source_ref)
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
    html = _render_assess_report_html(body, res, logo=logo, title=title, client=client, project=project, snapshot_data_url=snap, brand_color=brand_color, signature=bool(signature or False), sign_by=sign_by, sign_place=sign_place)

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
    html = _render_assess_report_html(body, res, logo=req.logo, title=req.title, client=req.client, project=req.project, snapshot_data_url=req.snapshot_data_url, brand_color=req.brand_color, signature=bool(req.signature or False), sign_by=req.sign_by, sign_place=req.sign_place, notes=req.notes, source_ref=req.source_ref)
    return Response(content=html, media_type='text/html; charset=utf-8')


# ... (rest of the code remains the same)

@app.get("/zoning/volume-export")
async def zoning_volume_export_get(format: Optional[str] = 'cityjson', body_b64: Optional[str] = None, download: bool = False, strict: bool = False, gzip: bool = False):
    """GET variant that accepts a URL-safe base64 encoded JSON body via `body_b64`.
    This matches the viewer's usage pattern and forwards to the POST handler for processing.
    """
    # Validate format early to keep error symmetry
    fmt = (format or 'cityjson').strip().lower()
    if fmt not in ('cityjson', 'gltf', 'glb'):
        raise HTTPException(status_code=400, detail="Formato no soportado: use 'cityjson', 'gltf' o 'glb'")
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
