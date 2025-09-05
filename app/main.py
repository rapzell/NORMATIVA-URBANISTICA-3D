from __future__ import annotations
import os
from typing import Optional
import mimetypes
import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException, Response, Body
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import BaseModel
from collections import OrderedDict
import time
from urllib.parse import urlencode
from urllib.request import urlopen, Request
import json as _json

API_VERSION = "0.2.0"

# Ensure correct MIME types for static assets (JS/WASM) on all platforms
try:
    mimetypes.add_type('text/javascript', '.js')
except Exception:
    pass
try:
    mimetypes.add_type('application/wasm', '.wasm')
except Exception:
    pass

app = FastAPI(title="Asistente Normativa Galicia API", version=API_VERSION)

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

# Servir datos de ejemplo (GeoJSON/CSV) para el visor
try:
    app.mount(
        "/data",
        StaticFiles(directory="datos", html=False),
        name="data",
    )
except Exception:
    pass

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
from src.asistente_normativa import cargar_recursos, buscar_fragmentos, generar_respuesta
from src.rules_engine import (
    analizar_zonificacion,
    ZoneInput,
    geometry_checks,
    geometry_checks_with_crs,
    GeometryReport,
)
from src.volume import compute_building_envelope, VolumeParams


API_VERSION = "0.2.0"

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

# Servir datos de ejemplo (GeoJSON/CSV) para el visor
try:
    app.mount(
        "/data",
        StaticFiles(directory="datos", html=False),
        name="data",
    )
except Exception:
    pass

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

# Endpoint para aplicar CSV de plan municipal recibido como texto (reubicado tras imports/app)
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

@app.get("/health", operation_id="health_check")
async def health():
    try:
        now = int(time.time())
    except Exception:
        now = 0
    return {"ok": True, "status": "ok", "version": API_VERSION, "time": now}


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


@app.post("/normativa/extract", response_model=ExtractResponse)
async def normativa_extract(req: ExtractRequest):
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


@app.post("/qa", response_model=QAResponse)
async def qa(req: QARequest):
    if not req.pregunta:
        raise HTTPException(status_code=400, detail="Campo 'pregunta' requerido")
    # Ensure resources
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
            raise HTTPException(status_code=500, detail=f"No se pudieron cargar recursos: {e}")

    frags = buscar_fragmentos(req.pregunta, _RESOURCES['chunks'], _RESOURCES['index'], _RESOURCES['bi_encoder'], _RESOURCES['cross_encoder'])
    resp = generar_respuesta(req.pregunta, frags, _RESOURCES['llm'])
    return QAResponse(respuesta=resp)


@app.post("/zoning/analyze")
async def zoning_analyze(inp: ZoneInput):
    try:
        res = analizar_zonificacion(inp)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Alias semántico: /normativa/consulta (misma lógica que /zoning/analyze)
@app.post("/normativa/consulta")
async def normativa_consulta(inp: ZoneInput):
    try:
        res = analizar_zonificacion(inp)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "resources_loaded": bool(_RESOURCES['loaded'])}


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
    geometry: dict
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
    # Resolver parámetros como en /zoning/volume
    altura = req.altura_maxima_m
    retranqueo = req.retranqueo_min_m or 0.0
    reasons: list[str] = []
    effective_front_direction = req.front_direction
    front_dir_source = None
    setback_front = req.setback_front_m
    setback_side = req.setback_side_m
    setback_back = req.setback_back_m

    try:
        if altura is None:
            if req.municipio:
                from src.rules_engine import get_plan_params_dynamic
                plan = get_plan_params_dynamic(req.municipio, req.subzona)
                if plan.altura_maxima_m is None:
                    raise ValueError("El plan municipal no devuelve altura máxima")
                altura = plan.altura_maxima_m
                if req.retranqueo_min_m is None and plan.retranqueo_min_m is not None:
                    retranqueo = plan.retranqueo_min_m
                # Determinar dirección de frente efectiva
                pfd = getattr(plan, 'front_direction_default', None)
                pf = getattr(plan, 'setback_front_m', None)
                ps = getattr(plan, 'setback_side_m', None)
                pb = getattr(plan, 'setback_back_m', None)
                has_plan_dir_setbacks = (pf is not None) or (ps is not None) or (pb is not None)
                if (
                    effective_front_direction is None
                    and req.street_axis is None
                    and bool(req.use_plan_front_default)
                    and pfd
                    and has_plan_dir_setbacks
                ):
                    effective_front_direction = pfd
                    front_dir_source = 'plan_default'
                    reasons.append("front_direction por defecto del plan aplicado")
                # Rellenar retranqueos direccionales si hay contexto direccional
                if effective_front_direction is not None or req.street_axis is not None:
                    setback_front = req.setback_front_m if req.setback_front_m is not None else pf
                    setback_side = req.setback_side_m if req.setback_side_m is not None else ps
                    setback_back = req.setback_back_m if req.setback_back_m is not None else pb
            else:
                raise HTTPException(status_code=400, detail="altura_maxima_m requerida si no se especifica municipio")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudieron obtener parámetros municipales: {e}")

    # Construir parámetros y calcular envolvente (en seco)
    try:
        params = VolumeParams(
            altura_maxima_m=float(altura),
            retranqueo_min_m=float(retranqueo or 0.0),
            setback_front_m=setback_front,
            setback_side_m=setback_side,
            setback_back_m=setback_back,
            front_direction=effective_front_direction,
        )
        feat = compute_building_envelope(req.geometry, params, street_axis=req.street_axis, front_direction_source=front_dir_source)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error en evaluación volumétrica: {e}")

    # Resumen geométrico opcional
    geometry_summary = None
    try:
        _gs = geometry_checks(req.geometry)
        # Normalizar a dict para la respuesta
        try:
            geometry_summary = _gs.model_dump()  # Pydantic v2
        except Exception:
            try:
                # Compatibilidad u otros tipos
                geometry_summary = dict(_gs) if isinstance(_gs, dict) else (
                    _gs.__dict__ if hasattr(_gs, '__dict__') else None
                )
            except Exception:
                geometry_summary = None
    except Exception:
        geometry_summary = None

    # Determinar viabilidad
    if feat is None:
        reasons.append("La envolvente edificable no existe (retranqueos agotan la parcela)")
        return AssessResponse(
            viability='no_apto',
            reasons=reasons,
            params_effective={
                'altura_maxima_m': altura,
                'retranqueo_min_m': retranqueo,
                'setback_front_m': setback_front,
                'setback_side_m': setback_side,
                'setback_back_m': setback_back,
                'front_direction': effective_front_direction,
                'front_direction_source': front_dir_source or ('request' if effective_front_direction else 'none'),
            },
            feature=None,
            geometry_summary=geometry_summary,
        )

    props = feat.get('properties') or {}
    # Heurísticas de condición
    condicionado = False
    if props.get('directional_not_applied_reason'):
        condicionado = True
        reasons.append(f"No se aplicó retranqueo direccional: {props.get('directional_not_applied_reason')}")
    if props.get('street_axis_ignored_reason'):
        condicionado = True
        reasons.append(f"Eje de calle ignorado: {props.get('street_axis_ignored_reason')}")
    if (front_dir_source == 'plan_default') and not req.front_direction and not req.street_axis:
        condicionado = True
        reasons.append("Dirección de frente por defecto del plan (sin eje de calle ni petición explícita)")

    viability = 'condicionado' if condicionado else 'apto'
    return AssessResponse(
        viability=viability,
        reasons=reasons,
        params_effective={
            'altura_maxima_m': altura,
            'retranqueo_min_m': retranqueo,
            'setback_front_m': setback_front,
            'setback_side_m': setback_side,
            'setback_back_m': setback_back,
            'front_direction': effective_front_direction,
            'front_direction_source': props.get('front_direction_source') or front_dir_source or ('request' if effective_front_direction else 'none'),
        },
        feature=feat,
        geometry_summary=geometry_summary,
    )


@app.get("/zoning/assess-report")
async def zoning_assess_report_get(body_b64: Optional[str] = None, logo: Optional[str] = None, title: Optional[str] = None, client: Optional[str] = None, project: Optional[str] = None, snap: Optional[str] = None):
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
    html = _render_assess_report_html(body, res, logo=logo, title=title, client=client, project=project, snapshot_data_url=snap)
    return Response(content=html, media_type='text/html; charset=utf-8')


class AssessReportRequest(BaseModel):
    body: VolumeRequest
    logo: Optional[str] = None
    title: Optional[str] = None
    client: Optional[str] = None
    project: Optional[str] = None
    snapshot_data_url: Optional[str] = None


@app.post("/zoning/assess-report")
async def zoning_assess_report_post(req: AssessReportRequest):
    """POST que recibe JSON con VolumeRequest y metadatos opcionales, y devuelve el HTML del informe."""
    res = await zoning_assess(req.body)  # AssessResponse
    # Convertir VolumeRequest a dict limpio
    try:
        body = req.body.model_dump()
    except Exception:
        body = req.body.dict() if hasattr(req.body, 'dict') else dict(req.body)
    html = _render_assess_report_html(body, res, logo=req.logo, title=req.title, client=req.client, project=req.project, snapshot_data_url=req.snapshot_data_url)
    return Response(content=html, media_type='text/html; charset=utf-8')


def _render_assess_report_html(body: dict, res: "AssessResponse", *, logo: Optional[str] = None, title: Optional[str] = None, client: Optional[str] = None, project: Optional[str] = None, snapshot_data_url: Optional[str] = None) -> str:
    import html as _html
    def esc(x: str) -> str:
        try:
            return _html.escape(x if isinstance(x, str) else str(x))
        except Exception:
            return str(x)
    v = (res.viability or '').upper()
    color = {'APTO':'#2e7d32','CONDICIONADO':'#f57f17','NO APTO':'#c62828'}.get(v, '#37474f')
    reasons = ''.join(f"<li>{esc(r)}</li>" for r in (res.reasons or []))
    pe = res.params_effective or {}
    rows = ''
    for k in ['altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','front_direction','front_direction_source']:
        rows += f"<tr><td>{esc(k)}</td><td>{esc(pe.get(k))}</td></tr>"
    area_txt = ''
    try:
        a = (res.geometry_summary or {}).get('area') or (res.geometry_summary or {}).get('area_m2')
        if a is not None:
            area_txt = f"<div class=muted>Área de parcela: {esc(round(float(a), 2))} m²</div>"
    except Exception:
        pass
    muni = (body.get('municipio') or '').strip() if isinstance(body, dict) else ''
    subz = (body.get('subzona') or '').strip() if isinstance(body, dict) else ''
    loc_txt = ''
    if muni or subz:
        loc_txt = f"<div class=muted>Municipio: {esc(muni) or '—'}{(' · Subzona: ' + esc(subz)) if subz else ''}</div>"
    import datetime as _dt
    gen_date = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    ttl = esc(title) if title else 'Informe de Viabilidad'
    cl = esc(client) if client else ''
    pj = esc(project) if project else ''
    logo_html = f"<img src='{esc(logo)}' alt='logo' style='height:40px'/>" if logo else ''
    client_proj = ''
    if cl or pj:
        client_proj = f"<div class=muted>{('Cliente: ' + cl) if cl else ''}{(' · Proyecto: ' + pj) if pj else ''}</div>"
    snap_html = ''
    if snapshot_data_url:
        try:
            snap_html = f"<div style='margin-top:10px'><img alt='snapshot' src='{esc(snapshot_data_url)}' style='max-width:100%;border:1px solid #333;border-radius:6px'/></div>"
        except Exception:
            snap_html = ''
    html = f"""
<!doctype html>
<html lang=es>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{ttl}</title>
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif;background:#111;color:#eaeaea;margin:20px;}}
    .card{{background:#1c1c1c;border:1px solid #333;border-radius:10px;padding:18px;max-width:900px;}}
    h1{{margin:0 0 10px 0;font-size:22px;}}
    .badge{{display:inline-block;padding:4px 10px;border-radius:20px;border:1px solid {color};color:{color};font-weight:600;}}
    table{{width:100%;border-collapse:collapse;margin-top:12px;}}
    td,th{{border-bottom:1px solid #333;padding:6px 8px;text-align:left;font-size:14px;}}
    ul{{margin:6px 0 0 20px;}}
    .muted{{opacity:0.8;font-size:13px;}}
    .toolbar{{position:sticky;top:0;display:flex;gap:8px;margin-bottom:12px}}
    .toolbar button{{padding:6px 10px;border:1px solid #555;background:#222;color:#eee;border-radius:6px;cursor:pointer}}
    .toolbar button:hover{{background:#2a2a2a}}
    @media print{{
      body{{background:#fff;color:#000;margin:0;}}
      .card{{border:none;border-radius:0;}}
      .toolbar{{display:none}}
      a[href]::after{{content:"";}}
      @page{{margin:12mm}}
    }}
  </style>
</head>
<body>
  <div class="toolbar">
    <button onclick="window.print()">Descargar PDF</button>
    <button onclick="window.close()">Cerrar</button>
  </div>
  <div class="card">
    <div style="display:flex;align-items:center;gap:12px;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:12px">{logo_html}<h1 style="margin:0">{ttl}</h1></div>
      <div class="muted">Generado: {esc(gen_date)}</div>
    </div>
    <div class="badge">{v}</div>
    {loc_txt}
    {client_proj}
    {area_txt}
    {snap_html}
    <h3>Parámetros efectivos</h3>
    <table>
      <tbody>
        {rows}
      </tbody>
    </table>
    <h3>Motivos</h3>
    <ul>{reasons or '<li>—</li>'}</ul>
    <p class="muted">Generado por Asistente Normativa Galicia</p>
  </div>
</body>
</html>
"""
    return html


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
            }
        _effective = _resolve_diag_verbosity(req.diagnostics_verbosity)
        return {"feature": _filter_volume_diagnostics(feature, _effective), "diagnostics_level_applied": _effective}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class VolumeExportRequest(VolumeRequest):
    format: Optional[str] = 'cityjson'  # 'cityjson' | 'gltf'


def _extrude_polygon_to_cityjson(feature: dict) -> dict:
    """Convierte un Feature 2D (Polygon/MultiPolygon, con o sin huecos) a CityJSON.
    - Cada polígono se extruye como un Solid independiente.
    - Top/Bottom incluyen huecos si existen; paredes para anillos exteriores e interiores.
    """
    if not feature or not isinstance(feature, dict):
        raise ValueError("feature inválido")
    geom = feature.get('geometry') or {}
    gtype = geom.get('type')
    h = float((feature.get('properties') or {}).get('height_m') or 0.0)
    if h <= 0:
        raise ValueError("height_m debe ser > 0")

    # Acumuladores globales de vértices
    vert_index: dict[tuple[float, float, float], int] = {}
    vertices: list[list[float]] = []

    def _vid(x: float, y: float, z: float) -> int:
        key = (float(x), float(y), float(z))
        idx = vert_index.get(key)
        if idx is not None:
            return idx
        vertices.append([float(x), float(y), float(z)])
        idx = len(vertices) - 1
        vert_index[key] = idx
        return idx

    def _ensure_closed(ring) -> list[list[float]]:
        # Acepta lista o tupla de puntos; fuerza a lista de listas
        ring = [list(pt) for pt in ring]
        if len(ring) < 4:
            raise ValueError("Anillo inválido")
        if ring[0] != ring[-1]:
            return ring + [ring[0]]
        return ring

    def _process_polygon(poly_coords) -> dict:
        # poly_coords: [outer, hole1, hole2, ...]
        if not poly_coords or not isinstance(poly_coords, (list, tuple)):
            raise ValueError("Coordenadas de polígono inválidas")
        rings = [
            _ensure_closed(r) for r in poly_coords
        ]
        # Construir loops de índices top/bottom por anillo
        top_loops: list[list[int]] = []
        bottom_loops: list[list[int]] = []
        for ring in rings:
            top_loop: list[int] = []
            bottom_loop: list[int] = []
            for (x, y) in ring[:-1]:  # omite cierre duplicado
                bottom_loop.append(_vid(x, y, 0.0))
                top_loop.append(_vid(x, y, h))
            top_loops.append(top_loop)
            bottom_loops.append(bottom_loop)
        # Superficies: top con huecos, bottom con huecos invertidos, paredes por anillo
        surfaces: list[list[list[int]]] = []
        # Top: el primer bucle es exterior, el resto son huecos
        surfaces.append(top_loops)
        # Bottom: mismo conjunto de anillos pero invertidos
        surfaces.append([list(reversed(loop)) for loop in bottom_loops])
        # Walls: por cada anillo, por cada arista, un quad
        for loop_idx, (b_loop, t_loop) in enumerate(zip(bottom_loops, top_loops)):
            n = len(t_loop)
            for i in range(n):
                i2 = (i + 1) % n
                v0 = b_loop[i]
                v1 = b_loop[i2]
                v2 = t_loop[i2]
                v3 = t_loop[i]
                surfaces.append([[v0, v1, v2, v3]])
        # Semánticas: 2 superficies base + tantas paredes como quads
        wall_count = sum(len(tl) for tl in top_loops)  # paredes por segmento; ajustaremos usando recuento real
        # Nota: para consistencia, calculamos wall_count real:
        wall_count = 0
        for t_loop in top_loops:
            wall_count += len(t_loop)
        semantics = {
            "surfaces": (
                [{"type": "RoofSurface"}, {"type": "GroundSurface"}] +
                ([{"type": "WallSurface"}] * wall_count)
            )
        }
        return {
            "type": "Solid",
            "lod": 2,
            "boundaries": [[s for s in surfaces]],
            "semantics": semantics,
        }

    geometries: list[dict] = []
    if gtype == 'Polygon':
        coords = geom.get('coordinates')
        geometries.append(_process_polygon(coords))
    elif gtype == 'MultiPolygon':
        for poly in (geom.get('coordinates') or []):
            geometries.append(_process_polygon(poly))
    else:
        raise ValueError("Tipo de geometría no soportado para CityJSON (use Polygon o MultiPolygon)")

    cityjson = {
        "type": "CityJSON",
        "version": "1.0",
        "vertices": vertices,
        "CityObjects": {
            "building-1": {
                "type": "Building",
                "geometry": geometries,
                "attributes": {
                    "height_m": h,
                    "area_m2": (feature.get('properties') or {}).get('area_m2')
                }
            }
        }
    }
    return cityjson


@app.post("/zoning/volume-export")
async def zoning_volume_export(req: VolumeExportRequest, download: bool = False, strict: bool = False, gzip: bool = False):
    fmt = (req.format or 'cityjson').strip().lower()
    if fmt not in ('cityjson', 'gltf', 'glb'):
        raise HTTPException(status_code=400, detail="Formato no soportado: use 'cityjson', 'gltf' o 'glb'")
    # Reutilizar la lógica de /zoning/volume para construir el feature 2D con height
    try:
        # Construye el feature usando la misma ruta que zoning_volume pero sin filtrar diagnósticos
        altura = req.altura_maxima_m
        retranqueo = req.retranqueo_min_m or 0.0
        if altura is None:
            if req.municipio:
                from src.rules_engine import get_plan_params_dynamic
                plan = get_plan_params_dynamic(req.municipio, req.subzona)
                if plan.altura_maxima_m is None:
                    raise ValueError("El plan municipal no devuelve altura máxima")
                altura = plan.altura_maxima_m
                if req.retranqueo_min_m is None and plan.retranqueo_min_m is not None:
                    retranqueo = plan.retranqueo_min_m
                pf = getattr(plan, 'setback_front_m', None)
                ps = getattr(plan, 'setback_side_m', None)
                pb = getattr(plan, 'setback_back_m', None)
                pfd = getattr(plan, 'front_direction_default', None)
                effective_front_direction = req.front_direction
                has_plan_dir_setbacks = (pf is not None) or (ps is not None) or (pb is not None)
                if (effective_front_direction is None and req.street_axis is None and bool(req.use_plan_front_default) and pfd and has_plan_dir_setbacks):
                    effective_front_direction = pfd
                if effective_front_direction is not None or req.street_axis is not None:
                    setback_front = req.setback_front_m if req.setback_front_m is not None else pf
                    setback_side = req.setback_side_m if req.setback_side_m is not None else ps
                    setback_back = req.setback_back_m if req.setback_back_m is not None else pb
                else:
                    setback_front = req.setback_front_m
                    setback_side = req.setback_side_m
                    setback_back = req.setback_back_m
            else:
                raise HTTPException(status_code=400, detail="altura_maxima_m requerida si no se especifica municipio")
        else:
            setback_front = req.setback_front_m
            setback_side = req.setback_side_m
            setback_back = req.setback_back_m

        feature = None
        try:
            feature = compute_building_envelope(
                req.geometry,
                VolumeParams(
                    altura_maxima_m=altura,
                    retranqueo_min_m=retranqueo,
                    setback_front_m=setback_front,
                    setback_side_m=setback_side,
                    setback_back_m=setback_back,
                    front_direction=req.front_direction,
                ),
                street_axis=req.street_axis,
                front_direction_source=None,
            )
        except Exception:
            # Fallback: para CityJSON, si la extrusión de la envolvente falla (p.ej. por huecos/MultiPolygon),
            # intentamos extruir la geometría original cuando hay altura y sin aplicar retranqueos complejos.
            if (not strict) and fmt == 'cityjson' and isinstance(req.geometry, dict) and req.geometry.get('type') in ('Polygon', 'MultiPolygon'):
                feature = {
                    'type': 'Feature',
                    'geometry': req.geometry,
                    'properties': {
                        'height_m': float(altura or 0.0),
                        'area_m2': None,
                    }
                }
            else:
                raise
        if feature is None:
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
            if download:
                media = 'model/gltf+json'
                fname = 'building.gltf'
                return Response(content=content, media_type=media, headers={"Content-Disposition": f"attachment; filename=\"{fname}\""})
            return payload
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


def _extrude_polygon_to_gltf(feature: dict) -> dict:
    """Convierte el Feature 2D en un GLTF 2.0 embebido (data URI) sin dependencias externas.
    Limitaciones: Polygon sin huecos.
    """
    geom = feature.get('geometry') or {}
    if geom.get('type') != 'Polygon':
        raise ValueError("Solo se soporta Polygon sin huecos para exportación GLTF")
    coords = geom.get('coordinates') or []
    if len(coords) == 0 or len(coords) > 1:
        raise ValueError("No se soportan huecos ni geometrías vacías en GLTF")
    ring = coords[0]
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("Anillo inválido")
    h = float((feature.get('properties') or {}).get('height_m') or 0.0)
    if h <= 0:
        raise ValueError("height_m debe ser > 0")
    # Construir vértices: bottom seguido de top
    bottom = [(float(x), float(y), 0.0) for (x, y) in ring]
    top = [(float(x), float(y), h) for (x, y) in ring]
    vertices = bottom + top
    n = len(ring)
    # Triangulación tipo fan para top (sentido CCW) y bottom (CW)
    indices: list[int] = []
    # top fan: índices desplazados por n (top start)
    top_off = n
    for i in range(1, n - 1):
        indices.extend([top_off, top_off + i, top_off + i + 1])
    # bottom fan invertido
    for i in range(1, n - 1):
        indices += [0, i + 1, i]
    # lados como dos triángulos por arista
    for i in range(n):
        i2 = (i + 1) % n
        b0 = i
        b1 = i2
        t1 = top_off + i2
        t0 = top_off + i
        # (b0, b1, t1) y (b0, t1, t0)
        indices += [b0, b1, t1, b0, t1, t0]
    # Empaquetar binarios
    import struct, base64
    # Positions float32
    pos_bytes = struct.pack('<' + 'f' * (len(vertices) * 3), *[c for v in vertices for c in v])
    # Padding a múltiplo de 4
    def _pad4(b: bytes) -> bytes:
        pad = (4 - (len(b) % 4)) % 4
        return b + (b'\x00' * pad)
    pos_bytes = _pad4(pos_bytes)
    # Indices uint32
    idx_bytes = struct.pack('<' + 'I' * len(indices), *indices)
    idx_bytes = _pad4(idx_bytes)
    # Concatenar y crear bufferViews
    buf = pos_bytes + idx_bytes
    uri = 'data:application/octet-stream;base64,' + base64.b64encode(buf).decode('ascii')
    # bufferViews
    pos_view = {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962}
    idx_view = {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(idx_bytes), "target": 34963}
    # accessors
    # Positions accessor
    xs = [v[0] for v in vertices]; ys = [v[1] for v in vertices]; zs = [v[2] for v in vertices]
    minv = [min(xs), min(ys), min(zs)]
    maxv = [max(xs), max(ys), max(zs)]
    pos_acc = {"bufferView": 0, "componentType": 5126, "count": len(vertices), "type": "VEC3", "min": minv, "max": maxv}
    idx_acc = {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"}
    gltf = {
        "asset": {"version": "2.0", "generator": "Asistente Normativa Galicia"},
        "buffers": [{"byteLength": len(buf), "uri": uri}],
        "bufferViews": [pos_view, idx_view],
        "accessors": [pos_acc, idx_acc],
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0},
                "indices": 1
            }]
        }],
        "nodes": [{"mesh": 0, "name": "building"}],
        "scenes": [{"nodes": [0]}],
        "scene": 0
    }
    return gltf


def _gltf_to_glb_bytes(gltf: dict) -> bytes:
    """Convierte un GLTF 2.0 (JSON) con buffer embebido (data URI base64) a GLB binario.
    Requisitos: un único buffer con "uri" data: y sin recursos externos.
    """
    import base64 as _b64
    import json as _json
    import struct as _struct

    buffers = gltf.get('buffers') or []
    if len(buffers) != 1:
        raise ValueError("Se requiere un único buffer embebido")
    uri = buffers[0].get('uri')
    if not uri or not uri.startswith('data:'):
        raise ValueError("Buffer debe estar embebido como data URI")
    # extrae base64 después de ','
    try:
        b64 = uri.split(',', 1)[1]
        bin_data = _b64.b64decode(b64)
    except Exception as e:
        raise ValueError(f"URI embebido inválido: {e}")
    # Actualiza buffers: GLB no usa uri, solo byteLength
    buffers[0].pop('uri', None)
    buffers[0]['byteLength'] = len(bin_data)

    # JSON chunk
    json_bytes = _json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    def _pad4(b: bytes) -> bytes:
        rem = (4 - (len(b) % 4)) % 4
        return b + (b' ' * rem)
    json_chunk = _pad4(json_bytes)
    bin_chunk = _pad4(bin_data)

    # GLB header
    magic = 0x46546C67  # 'glTF'
    version = 2
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    header = _struct.pack('<III', magic, version, total_length)

    # Chunks: JSON (type 0x4E4F534A 'JSON'), BIN (type 0x004E4942 'BIN\0')
    JSON_TYPE = 0x4E4F534A
    BIN_TYPE = 0x004E4942
    json_header = _struct.pack('<II', len(json_chunk), JSON_TYPE)
    bin_header = _struct.pack('<II', len(bin_chunk), BIN_TYPE)

    return header + json_header + json_chunk + bin_header + bin_chunk
