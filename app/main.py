from __future__ import annotations

import os
from typing import Optional
import mimetypes
import logging
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
