from __future__ import annotations
from pydantic import BaseModel

# ------------------------------
# Proveedor de planes (factory + caché)
# ------------------------------
_PLAN_PROVIDER_CACHE = {
    'provider': None,
    'kind': None,
}

def _get_plan_provider():
    """Devuelve una instancia de proveedor de planes según variables de entorno.
    Soporta PLAN_PROVIDER=csv (usar PLAN_CSV_PATH) o mock por defecto.
    Instancia una vez y la reutiliza (caché en memoria).
    """
    kind = (os.getenv('PLAN_PROVIDER', '') or '').strip().lower() or 'csv'
    cached = _PLAN_PROVIDER_CACHE.get('provider')
    if cached is not None and _PLAN_PROVIDER_CACHE.get('kind') == kind:
        return cached
    if kind == 'csv':
        try:
            from src.planes.csv_provider import CSVPlanProvider
            csv_path = os.getenv('PLAN_CSV_PATH') or os.path.join('datos', 'plan_uploaded.csv')
            prov = CSVPlanProvider(csv_path)
            _PLAN_PROVIDER_CACHE.update({'provider': prov, 'kind': kind})
            logging.getLogger(__name__).info("PLAN_PROVIDER=csv usando %s", csv_path)
            return prov
        except Exception as e:
            logging.getLogger(__name__).warning("Fallo iniciando CSVPlanProvider: %s. Cayendo a mock.", e)
            kind = 'mock'
    # fallback mock: adaptar al módulo existente (no hay clase MockPlanProvider, solo función get_plan_params)
    try:
        from src.planes import mock_provider as _mp
        class _MockProvider:
            def get(self, municipio: str, subzona: str | None = None):
                return _mp.get_plan_params(municipio, subzona)
        prov = _MockProvider()
    except Exception:
        # Último recurso: proveedor vacío
        class _EmptyProvider:
            def get(self, municipio: str, subzona: str | None = None):
                from src.planes.base import PlanParams
                return PlanParams(municipio=municipio, subzona=subzona)
        prov = _EmptyProvider()
    _PLAN_PROVIDER_CACHE.update({'provider': prov, 'kind': 'mock'})
    logging.getLogger(__name__).info("PLAN_PROVIDER=mock (fallback)")
    return prov

def get_plan_params_dynamic(municipio: str | None, subzona: str | None):
    """Obtiene parámetros del plan de manera dinámica usando el proveedor activo."""
    from src.planes.base import PlanParams
    muni = (municipio or '').strip()
    subz = (subzona or None)
    prov = _get_plan_provider()
    try:
        params = prov.get(muni, subz)
        if not isinstance(params, PlanParams):
            # Normalizar si el proveedor devolviese dict
            params = PlanParams(**(params or {}))
        # Si no hay datos y estamos en Vigo, intentar CSVs municipales conocidos como fallback
        def _has_core_values(p: PlanParams) -> bool:
            return (getattr(p, 'altura_maxima_m', None) is not None) or (getattr(p, 'retranqueo_min_m', None) is not None)
        mlow = muni.lower()
        if not _has_core_values(params) and ('vigo' in mlow):
            try:
                from src.planes.csv_provider import CSVPlanProvider
                for alt_csv in (
                    os.path.join('datos', 'planes_Vigo_residencial_clean.csv'),
                    os.path.join('datos', 'planes_Vigo_residencial.csv'),
                    os.path.join('datos', 'planes_vigo_boiro.csv'),
                ):
                    try:
                        if os.path.isfile(alt_csv):
                            altp = CSVPlanProvider(alt_csv).get(muni, subz)
                            if not isinstance(altp, PlanParams):
                                altp = PlanParams(**(altp or {}))
                            if _has_core_values(altp):
                                logging.getLogger(__name__).info("Proveedor CSV alternativo aplicado: %s", alt_csv)
                                return altp
                    except Exception:
                        continue
            except Exception:
                pass
        return params
    except Exception as e:
        logging.getLogger(__name__).warning("get_plan_params_dynamic error: %s", e)
        return PlanParams(municipio=muni, subzona=subz)

# ------------------------------
# Endpoint de depuración de planes
# ------------------------------
class DebugPlanResponse(BaseModel):
    municipio: str | None
    subzona: str | None
    provider: str
    params: dict

def _arcgis_feature_query(feature_url: str, lon: float, lat: float, *, sr_in: int = 4326, out_fields: str = "*") -> tuple[str | None, dict]:
    """Consulta un Feature Layer (FeatureServer/MapServer layer) con /query devolviendo una subzona si existe.
    Devuelve (subzona, diag). No lanza excepción: diag incluirá 'error' si falla.
    """
    diag: dict = {"type": "feature_query", "url": feature_url}
    try:
        import urllib.parse as _up
        import urllib.request as _ur
        import json as _json
        # ArcGIS /query requiere geometry como JSON y parámetros estándar
        geom = _json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": sr_in}})
        params = {
            "f": "json",
            "where": "1=1",
            "geometry": geom,
            "geometryType": "esriGeometryPoint",
            "inSR": str(sr_in),
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields or "*",
            "returnGeometry": "false",
        }
        url = feature_url.rstrip('/') + "/query?" + _up.urlencode(params)
        diag["query_url"] = url
        req = _ur.Request(url, headers={"User-Agent": "NormativaGalicia/1.0"})
        with _ur.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        data = _json.loads(raw.decode("utf-8", "ignore")) if raw else {}
        diag["ok"] = True
        feats = data.get("features") or []
        if not feats:
            return None, diag
        attrs = feats[0].get("attributes") or {}
        diag["attrs_keys"] = list(attrs.keys())
        # Intentar campos comunes para ordenanza/subzona
        candidates = [
            "subzona", "ordenanza", "ORDENANZA", "U", "u", "codigo", "Código", "CODIGO", "clase", "Clase",
        ]
        val: str | None = None
        for k in candidates:
            if k in attrs and isinstance(attrs[k], (str, int, float)):
                v = str(attrs[k]).strip()
                if v:
                    val = v
                    break
        if not val:
            return None, diag
        # Normalizar: quedarnos con códigos tipo U3, U6.1, NR-1
        import re as _re
        m = _re.search(r"\b((?:U\s*\d+(?:\.\d+)?)|(?:NR\s*-?\s*\d+))\b", val, flags=_re.IGNORECASE)
        if m:
            return m.group(1).upper().replace(" ", "").replace("NR-", "NR-") , diag
        # Si no encaja, devolver valor bruto
        return val, diag
    except Exception as e:
        try:
            diag["error"] = str(e)
        except Exception:
            pass
        return None, diag
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
                pick = merged_path if os.path.isfile(merged_path) else (uploaded_path if os.path.isfile(uploaded_path) else None)
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
        prov = _get_plan_provider()
        kind = (_PLAN_PROVIDER_CACHE.get('kind') or 'unknown')
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
    """Extrae campos básicos (uso_suelo, altura_maxima_m, retranqueo_min_m) de un texto libre.
    Heurística con regex pensada para español. No lanza excepción: siempre devuelve dict parcial.
    """
    try:
        import re
        t = (req.text or "").strip()
        res: dict = {
            "municipio": (req.municipio or None),
            "uso_suelo": None,
            "altura_maxima_m": None,
            "retranqueo_min_m": None,
            "setback_front_m": None,
            "setback_side_m": None,
            "setback_back_m": None,
            "ocupacion_max": None,
            "edificabilidad_max_m2_m2": None,
            "subzona": None,
            "referencias": [],
        }
        if not t:
            return res
        # Uso del suelo (ampliado)
        if re.search(r"\bresidencial\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "residencial"
        elif re.search(r"\bindustrial\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "industrial"
        elif re.search(r"\bcomercial\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "comercial"
        elif re.search(r"\br[úu]stic[oa]\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "rustico"
        elif re.search(r"\burbano\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "urbano"
        elif re.search(r"\burbanizable\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "urbanizable"
        elif re.search(r"\b(dotacional|equipamientos?)\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "dotacional"
        elif re.search(r"\bterciari[oa]\b", t, flags=re.IGNORECASE):
            res["uso_suelo"] = "terciario"
        # Altura máxima (metros)
        m = re.search(r"altura\s*m[aá]x\.?\s*(?:permitida|m[ií]nima|\w+)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if not m:
            m = re.search(r"\b(?:altura|alzada)\b[^\d]*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if m:
            try:
                res["altura_maxima_m"] = float(str(m.group(1)).replace(",", "."))
            except Exception:
                pass
        # Retranqueos (metros) — frente/lateral/fondo y genérico
        def _to_float(s: str) -> float | None:
            try:
                return float(s.replace(',', '.'))
            except Exception:
                return None
        # Frente
        rf = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*(?:al\s*frente|frontal)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if rf:
            v = _to_float(rf.group(1))
            if v is not None:
                res["setback_front_m"] = v
        # Laterales (permitir expresión sin la palabra 'retranqueo')
        rl = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*(?:lateral(?:es)?)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if not rl:
            rl = re.search(r"\blateral(?:es)?\b[^\d]*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if rl:
            v = _to_float(rl.group(1))
            if v is not None:
                res["setback_side_m"] = v
        # Fondo/trasero (permitir expresión sin la palabra 'retranqueo')
        rb = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*(?:de\s*fondo|posterior|trasero)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if not rb:
            rb = re.search(r"\b(?:de\s*fondo|posterior|trasero)\b[^\d]*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if rb:
            v = _to_float(rb.group(1))
            if v is not None:
                res["setback_back_m"] = v
        # Genérico (si no hay frente explícito)
        if res["setback_front_m"] is None and res["retranqueo_min_m"] is None:
            r = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
            if r:
                v = _to_float(r.group(1))
                if v is not None:
                    res["retranqueo_min_m"] = v
        # Ocupación máxima: robusto ante codificaciones y con/sin símbolo %
        occ = re.search(r"ocupaci[^\d%]*\s*(?:m[aá]x\.?|m[aá]xima)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*%?\b", t, flags=re.IGNORECASE)
        if occ:
            v = _to_float(occ.group(1))
            if v is not None:
                # Si el valor parece porcentaje (>= 1.5), normalizar a 0..1
                res["ocupacion_max"] = v/100.0 if v > 1.0 else v
        # Edificabilidad (m2/m2) — tolerar espacios y variantes m²
        edi = re.search(r"edificabilidad\s*(?:m[aá]x\.?|m[aá]xima)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*(?:m2|m²)?\s*/\s*(?:m2|m²)\b", t, flags=re.IGNORECASE)
        if not edi:
            edi = re.search(r"edificabilidad\b[^\d]*(\d+(?:[\.,]\d+)?)\b", t, flags=re.IGNORECASE)
        if edi:
            v = _to_float(edi.group(1))
            if v is not None:
                res["edificabilidad_max_m2_m2"] = v
        # Subzona/código básico (U3, U6.1, NR-1, etc.)
        cz = re.search(r"\b((?:U\s*\d+(?:\.\d+)?)|(?:NR\s*-?\s*\d+))\b", t, flags=re.IGNORECASE)
        if cz:
            res["subzona"] = cz.group(1).upper().replace(" ", "").replace("NR-", "NR-")
        # Referencias (muy básico: Art. X, o URLs)
        refs: list[str] = []
        for mref in re.findall(r"\bArt\.?\s*\d+(?:\.\d+)?\b", t, flags=re.IGNORECASE):
            refs.append(mref)
        for url in re.findall(r"https?://\S+", t, flags=re.IGNORECASE):
            refs.append(url.rstrip(').,;'))
        if refs:
            res["referencias"] = refs
        return res
    except Exception as e:
        # No bloquear por errores de parsing; devolver parcial
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
from src.asistente_normativa import cargar_recursos, buscar_fragmentos, generar_respuesta
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
def _arcgis_identify_extract(url: str, lon: float, lat: float, sr: int = 4326, tol: int = 12, layers_mode: str = "all") -> tuple[str | None, dict]:
    diag: dict = {}
    try:
        import urllib.parse as _up
        import urllib.request as _ur
        # Geometry payload como punto (no pre-quote, urlencode se encarga)
        geom = _json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": sr}})
        # Map extent pequeño alrededor del punto (en grados si sr=4326)
        pad = 0.001  # ~100 m aprox
        ext = f"{lon - pad},{lat - pad},{lon + pad},{lat + pad}"
        params = {
            "f": "json",
            "geometry": geom,
            "geometryType": "esriGeometryPoint",
            "sr": str(sr),
            "tolerance": str(tol),
            "mapExtent": ext,
            "imageDisplay": "400,400,96",
            "layers": layers_mode,
            "returnGeometry": "false",
        }
        full = f"{url}?{_up.urlencode(params)}"
        diag["url"] = full
        diag["type"] = "identify"
        req = _ur.Request(full, headers={"User-Agent": "NormativaGalicia/1.0"})
        with _ur.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            data = _json.loads(raw.decode("utf-8", "ignore"))
        # Normalizar a estructura similar a _extract_subzone... (usar 'results' con 'attributes')
        if isinstance(data, dict) and ("results" in data or "identifyResults" in data):
            lst = data.get("results") or data.get("identifyResults") or []
            diag["results_len"] = len(lst) if isinstance(lst, list) else 0
            if isinstance(lst, list) and lst:
                first = lst[0] or {}
                attrs = first.get("attributes") or first.get("Attributes") or {}
                if isinstance(attrs, dict):
                    try:
                        diag["attrs_keys"] = list(attrs.keys())
                    except Exception:
                        pass
                if isinstance(attrs, dict) and attrs:
                    # Reutilizar extractor pasando como si fuera props de una feature
                    fake = {"features": [{"properties": attrs}]}
                    return _extract_subzone_from_wms_json(fake), diag
        return None, diag
    except Exception as e:
        try:
            diag["error"] = str(e)
        except Exception:
            pass
        return None, diag

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
async def health():
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
        # Fallback muy robusto: extraer municipio/subzona + parámetros desde provider CSV y heurística de texto
        try:
            import re as _re
            raw = (req.pregunta or '')
            # No contaminar con el prefijo del visor
            txt = "\n".join([ln for ln in raw.splitlines() if not ln.strip().startswith('[Contexto visor]')]).strip()
            # Señales de intención local: sólo si pide parámetros o menciona muni/subzona
            wants_local = False
            if _re.search(r"\b(altura|maxim|retranqueo|setback|ocupaci[oó]n|edificabilidad|m2\s*/\s*m2)\b", txt, flags=_re.IGNORECASE):
                wants_local = True
            # 1) Extraer municipio y subzona del texto
            muni = None
            if wants_local:
                if _re.search(r"\bVigo\b", txt, flags=_re.IGNORECASE):
                    muni = "Vigo"
                elif _re.search(r"\bA\s*Coru(?:n|ñ)a\b", txt, flags=_re.IGNORECASE):
                    muni = "A Coruna"
                elif _re.search(r"\bBoiro\b", txt, flags=_re.IGNORECASE):
                    muni = "Boiro"
            m_sub = _re.search(r"\b((?:U\s*\d+(?:\.\d+)?)|(?:NR\s*-?\s*\d+))\b", txt, flags=_re.IGNORECASE)
            subz = m_sub.group(1).upper().replace(" ", "") if (wants_local and m_sub) else None
            # 2) Obtener parámetros del plan (si hay muni/subz)
            p = None
            if wants_local and muni:
                try:
                    p = get_plan_params_dynamic(muni, subz)
                except Exception:
                    p = None
            # 3) Heurística de extracción adicional desde el texto
            basic = normativa_extract(NormExtractRequest(text=txt))
            # 4) Construir respuesta fusionando provider + heurística
            def _fmt(n):
                return None if n is None else (int(n) if isinstance(n, (int,)) or (isinstance(n, float) and n.is_integer()) else float(n))
            resumen = []
            if wants_local and muni:
                resumen.append(f"Municipio: {muni}")
            if subz:
                resumen.append(f"Subzona: {subz}")
            # Provider primero si existe
            if wants_local and p is not None:
                am = _fmt(getattr(p, 'altura_maxima_m', None))
                rm = _fmt(getattr(p, 'retranqueo_min_m', None))
                sf = _fmt(getattr(p, 'setback_front_m', None))
                ss = _fmt(getattr(p, 'setback_side_m', None))
                sb = _fmt(getattr(p, 'setback_back_m', None))
                oc = getattr(p, 'ocupacion_max', None)
                ed = _fmt(getattr(p, 'edificabilidad_max_m2_m2', None))
                if am is not None: resumen.append(f"Altura máxima (m): {am}")
                if rm is not None: resumen.append(f"Retanqueo mínimo (m): {rm}")
                if sf is not None: resumen.append(f"Frente (m): {sf}")
                if ss is not None: resumen.append(f"Laterales (m): {ss}")
                if sb is not None: resumen.append(f"Fondo (m): {sb}")
                if oc is not None: resumen.append(f"Ocupación máx.: {oc}")
                if ed is not None: resumen.append(f"Edificabilidad (m2/m2): {ed}")
            # Rellenar con heurística si faltan campos
            if basic.get("uso_suelo") and all("Uso del suelo:" not in x for x in resumen):
                resumen.append(f"Uso del suelo: {basic['uso_suelo']}")
            if basic.get("altura_maxima_m") is not None and all("Altura máxima" not in x for x in resumen):
                resumen.append(f"Altura máxima (m): {basic['altura_maxima_m']}")
            if basic.get("retranqueo_min_m") is not None and all("Retanqueo mínimo" not in x for x in resumen):
                resumen.append(f"Retanqueo mínimo (m): {basic['retranqueo_min_m']}")
            if basic.get("setback_front_m") is not None and all("Frente (m):" not in x for x in resumen):
                resumen.append(f"Frente (m): {basic['setback_front_m']}")
            if basic.get("setback_side_m") is not None and all("Laterales (m):" not in x for x in resumen):
                resumen.append(f"Laterales (m): {basic['setback_side_m']}")
            if basic.get("setback_back_m") is not None and all("Fondo (m):" not in x for x in resumen):
                resumen.append(f"Fondo (m): {basic['setback_back_m']}")
            if basic.get("edificabilidad_max_m2_m2") is not None and all("Edificabilidad" not in x for x in resumen):
                resumen.append(f"Edificabilidad (m2/m2): {basic['edificabilidad_max_m2_m2']}")
            # Si la consulta es general (sin intención local), priorizar extracto legal según uso_suelo detectado
            if not wants_local:
                uso_det = str(basic.get("uso_suelo") or '').lower()
                if uso_det in ("rustico", "rústico"):
                    resumen = [
                        "Suelo rústico: usos compatibles con su naturaleza (agrícolas, ganaderos, forestales, de protección ambiental e infraestructuras), evitando transformaciones urbanísticas.",
                        "Referencia: Ley 2/2016 del Suelo de Galicia, Artículos 31–32."
                    ]
                elif uso_det.startswith("urbano") or uso_det == "urbana":
                    resumen = [
                        "Suelo urbano consolidado: integrado en la malla urbana, con servicios urbanísticos completos; reúne la condición de solar o puede adquirirla con obras accesorias menores.",
                        "Referencia: Ley 2/2016 del Suelo de Galicia, Artículo 17."
                    ]
                else:
                    # Respaldo: detección acento-insensible por texto
                    import unicodedata as _ud
                    def _strip(s: str) -> str:
                        try:
                            return ''.join(ch for ch in _ud.normalize('NFD', s.lower()) if _ud.category(ch) != 'Mn')
                        except Exception:
                            return s.lower()
                    base = _strip(txt)
                    if ('rustico' in base) and ('urbano' not in base):
                        resumen = [
                            "Suelo rústico: usos compatibles con su naturaleza (agrícolas, ganaderos, forestales, de protección ambiental e infraestructuras), evitando transformaciones urbanísticas.",
                            "Referencia: Ley 2/2016 del Suelo de Galicia, Artículos 31–32."
                        ]
                    elif ('urbano' in base) and ('rustico' not in base):
                        resumen = [
                            "Suelo urbano consolidado: integrado en la malla urbana, con servicios urbanísticos completos; reúne la condición de solar o puede adquirirla con obras accesorias menores.",
                            "Referencia: Ley 2/2016 del Suelo de Galicia, Artículo 17."
                        ]
            # Si hay intención local pero no hay datos CSV, informar y aportar extracto legal si procede
            if wants_local and (p is None):
                import unicodedata as _ud
                def _strip2(s: str) -> str:
                    try:
                        return ''.join(ch for ch in _ud.normalize('NFD', s.lower()) if _ud.category(ch) != 'Mn')
                    except Exception:
                        return s.lower()
                base2 = _strip2(txt)
                resumen.append("No se encontraron parámetros en el CSV para el municipio/subzona indicados.")
                if ('rustico' in base2) and ('urbano' not in base2):
                    resumen.append("Referencia: Ley 2/2016 del Suelo de Galicia, Artículos 31–32 (suelo rústico).")
                elif ('urbano' in base2) and ('rustico' not in base2):
                    resumen.append("Referencia: Ley 2/2016 del Suelo de Galicia, Artículo 17 (suelo urbano).")
            if not resumen:
                resumen = ["Servicio operativo. Aporta municipio y, si lo conoces, la subzona (p. ej., Vigo RZ-2 o A Coruña NR-1)."]
            msg = "\n".join(resumen) + "\n\nNota: respuesta generada en modo básico (sin modelo)."
            return QAResponse(respuesta=msg)
        except Exception:
            # Último recurso
            return QAResponse(respuesta="Servicio de preguntas operativo en modo básico. Indica municipio y subzona para más detalle.")


@app.post("/zoning/analyze")
async def zoning_analyze(inp: ZoneInput):
    try:
        # Auto-inferir subzona si estamos en Vigo y no se proporcionó
        try:
            if (not getattr(inp, 'subzona', None)) and getattr(inp, 'municipio', None):
                if str(inp.municipio).strip().lower().find('vigo') >= 0:
                    cfg = _wms_config_for_municipio(inp.municipio)
                    feature_url = (cfg or {}).get('feature_url') if isinstance(cfg, dict) else None
                    if feature_url and getattr(inp, 'geometry', None):
                        lon, lat = _centroid_lonlat_from_geojson(inp.geometry, getattr(inp, 'crs', None))
                        if (lon is not None) and (lat is not None):
                            subz, _diag = _arcgis_feature_query(feature_url, float(lon), float(lat))
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


def _wms_config_for_municipio(muni: str):
    m = (muni or "").strip().lower()
    # MVP: A Coruña PGOM13 Ordenanzas. Se pueden añadir más municipios aquí.
    if m in ("a coruña", "a coruna", "coruna", "a corunha"):
        return {
            "base": os.getenv("ACORUNA_WMS_BASE", "https://geo.coruna.es/geoserver/wms"),
            "layers": os.getenv("ACORUNA_WMS_LAYERS", "pgom13:Ordenanzas"),
            "info_format": os.getenv("ACORUNA_WMS_INFO_FORMAT", "application/json"),
            "srs": os.getenv("ACORUNA_WMS_SRS", "EPSG:4326"),
        }
    # Vigo: desde 2025 migrado a ArcGIS Online. Configurable via variables de entorno.
    if m in ("vigo",):
        cfg: dict = {
            # Endpoint Identify (opcional) hacia MapServer/identify del servicio municipal
            "rest_identify": (os.getenv("VIGO_ARCGIS_IDENTIFY", "").strip() or None),
            # URL de Feature Layer (FeatureServer/N o MapServer/N) para /query (recomendado)
            "feature_url": (os.getenv("VIGO_ARCGIS_FEATURE_URL", "").strip() or None),
            "srs": "EPSG:4326",
        }
        return cfg
    return None


def _lonlat_to_mercator(lon: float, lat: float):
    import math as _math
    r_major = 6378137.0
    x = r_major * _math.radians(lon)
    lat = max(min(lat, 89.9), -89.9)
    y = r_major * _math.log(_math.tan(_math.pi/4.0 + _math.radians(lat)/2.0))
    return x, y


def _mercator_to_lonlat(x: float, y: float):
    import math as _math
    r_major = 6378137.0
    lon = (x / r_major) * (180.0 / _math.pi)
    lat = (2 * _math.atan(_math.exp(y / r_major)) - _math.pi / 2) * (180.0 / _math.pi)
    return lon, lat


def _centroid_lonlat_from_geojson(geometry: dict | None, crs: str | None = None) -> tuple[float | None, float | None]:
    """Obtiene el centroide en lon/lat a partir de un GeoJSON simple.
    Soporta geometrías en EPSG:4326. Si el CRS parece métrico WebMercator (3857/900913), se hace la inversa.
    """
    if not geometry or not isinstance(geometry, dict):
        return None, None
    try:
        gtype = (geometry.get('type') or '').lower()
        coords = geometry.get('coordinates')
        if gtype in ('polygon', 'multipolygon') and coords:
            # Bounding box aproximado para centroide rápido
            def _iter_pts(c):
                if gtype == 'polygon':
                    for ring in c or []:
                        for pt in ring or []:
                            yield pt
                else:
                    for poly in c or []:
                        for ring in poly or []:
                            for pt in ring or []:
                                yield pt
            xs = []
            ys = []
            for pt in _iter_pts(coords):
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    xs.append(float(pt[0]))
                    ys.append(float(pt[1]))
            if not xs or not ys:
                return None, None
            cx = (min(xs) + max(xs)) / 2.0
            cy = (min(ys) + max(ys)) / 2.0
            # Interpretar CRS
            crs_s = (crs or '').lower()
            if ('3857' in crs_s) or ('900913' in crs_s):
                lon, lat = _mercator_to_lonlat(cx, cy)
            else:
                # Asumir lon/lat por defecto
                lon, lat = cx, cy
            return float(lon), float(lat)
    except Exception:
        return None, None
    return None, None


def _build_wms_getfeatureinfo_url(base: str, layers: str, lon: float, lat: float, srs: str = "EPSG:4326", info_format: str = "application/json", version: str = "1.1.1") -> str:
    import urllib.parse as _up
    # Padding de selección en metros para el BBOX (configurable)
    try:
        pad_m = float(os.getenv('WMS_GFI_PAD_M', '30'))
    except Exception:
        pad_m = 30.0
    if srs.upper() == "EPSG:4326":
        x, y = _lonlat_to_mercator(lon, lat)
        bbox = f"{x-pad_m},{y-pad_m},{x+pad_m},{y+pad_m}"
        req_srs = "EPSG:3857"
    else:
        # Suponemos coords ya en el SRS solicitado
        bbox = f"{lon-pad_m},{lat-pad_m},{lon+pad_m},{lat+pad_m}"
        req_srs = srs
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetFeatureInfo",
        "VERSION": version,
        "LAYERS": layers,
        "QUERY_LAYERS": layers,
        **({"SRS": srs} if version == "1.1.1" else {"CRS": srs}),
        "BBOX": bbox,
        "WIDTH": "256",
        "HEIGHT": "256",
        # Nota: X/Y para 1.1.1; I/J para 1.3.0
        **(({"X": "128", "Y": "128"} if version == "1.1.1" else {"I": "128", "J": "128"})),
        "INFO_FORMAT": info_format,
    }
    qs = _up.urlencode(params)
    return f"{base}?{qs}"


def _extract_subzone_from_wms_json(data: dict) -> str | None:
    try:
        feats = data.get("features") or data.get("FeatureCollection") or []
        if isinstance(feats, dict):
            feats = feats.get("features", [])
        # ArcGIS Identify JSON fallback: results / identifyResults with attributes
        if not feats and isinstance(data, dict) and ("results" in data or "identifyResults" in data):
            try:
                lst = data.get("results") or data.get("identifyResults") or []
                if isinstance(lst, list) and lst:
                    first = lst[0] or {}
                    attrs = first.get("attributes") or first.get("Attributes") or {}
                    if isinstance(attrs, dict) and attrs:
                        # Try to extract from attributes directly with robust matching
                        props = attrs
                        # Build normalized key map
                        norm = lambda s: ''.join(ch for ch in s.lower() if ch.isalnum())
                        by_norm = {norm(k): k for k in props.keys()}
                        candidates = [
                            # very common
                            "subzona","ordenanza","clave","categoria","codigo",
                            # variations and Spanish diacritics removed
                            "claseordenanza","claveordenanza","clase","zonificacion","zonificacion",
                            "zona","leyenda","denominacion","denominacion","codordenanza","codorden",
                            # other possible naming
                            "ordenanzas","claveorden","claveordenanzas","planeamiento","clasesuelo",
                        ]
                        for c in candidates:
                            key_norm = norm(c)
                            if key_norm in by_norm:
                                k = by_norm[key_norm]
                                v = props.get(k)
                                if isinstance(v, str) and v.strip():
                                    return v.strip()
                        # Fallback: first non-empty string
                        for k, v in props.items():
                            if isinstance(v, str) and v.strip():
                                return v.strip()
            except Exception:
                pass
        if not feats and isinstance(data, dict) and "raw" in data:
            # Fallback: parse simple HTML table from ArcGIS WMS GetFeatureInfo
            try:
                import re as _re
                raw = data.get("raw") or ""
                # Buscar pares clave-valor en celdas de tabla
                patterns = [
                    r"(?i)ORDENANZA\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                    r"(?i)SUBZONA\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                    r"(?i)CLAVE[_ ]?ORDENANZA\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                    r"(?i)CLAVE\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                    r"(?i)ClaseSuelo\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                    r"(?i)PLANEAMIENTO\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                    r"(?i)LEYENDA\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                    r"(?i)ZONA\s*</t[dh]>\s*<t[dh][^>]*>\s*([^<\n]+)",
                ]
                for pat in patterns:
                    m = _re.search(pat, raw)
                    if m:
                        val = (m.group(1) or '').strip()
                        if val:
                            return val
            except Exception:
                pass
            return None
        # Tomar primera feature
        f0 = feats[0] if feats else None
        props = (f0.get("properties") if isinstance(f0, dict) else None) or {}
        # Buscar campos típicos de subzona/ordenanza/clave (case-insensitive, normalizados)
        norm = lambda s: ''.join(ch for ch in s.lower() if ch.isalnum())
        by_norm = {norm(k): k for k in props.keys()}
        candidates = [
            # genéricos
            "subzona","ordenanza","clave","categoria","codigo",
            # SIU / Vigo propuestos por el usuario
            "clasesuelo","planeamiento","clave_ordenanza",
            # variaciones frecuentes en WMS municipales
            "ordenanzas","leyenda","zona","zonificacion","denominacion","codordenanza","codorden",
        ]
        for c in candidates:
            key_norm = norm(c)
            if key_norm in by_norm:
                k = by_norm[key_norm]
                v = props.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        # Fallback: primera cadena no vacía en props
        for k, v in props.items():
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:
        return None
    return None


@app.post("/zoning/infer-subzone", response_model=InferSubzoneResponse)
async def zoning_infer_subzone(req: InferSubzoneRequest):
    cfg = _wms_config_for_municipio(req.municipio)
    if not cfg:
        return InferSubzoneResponse(municipio=req.municipio, subzona=None, diagnostics={"reason":"no_cfg_for_municipio"})
    try:
        import urllib.request as _ur
        logger = logging.getLogger("zoning.infer_subzone")
        attempts_info: list[dict] = []
        def _attempt(base: str, layers: str, info_format: str, *, version: str = "1.1.1") -> tuple[str | None, str]:
            url = _build_wms_getfeatureinfo_url(base, layers, req.lon, req.lat, req.srs or cfg.get("srs", "EPSG:4326"), info_format, version)
            try:
                logger.info("attempt muni='%s' layers='%s' fmt='%s' lon=%.6f lat=%.6f url=%s", req.municipio, layers, info_format, req.lon, req.lat, url)
            except Exception:
                pass
            import urllib.error as _ue
            try:
                resp = _ur.urlopen(_ur.Request(url, headers={"User-Agent":"NormativaGalicia/1.0"}), timeout=15)
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", info_format or "application/octet-stream")
                import json as _json
                if "json" in ctype.lower():
                    try:
                        data = _json.loads(raw.decode("utf-8", "ignore"))
                    except Exception:
                        data = {}
                    try:
                        feats = data.get("features") or []
                        props_keys = list((feats[0].get("properties") or {}).keys()) if feats else []
                        logger.info("props(keys)=%s", props_keys)
                        attempts_info.append({"url": url, "ctype": ctype, "props_keys": props_keys})
                    except Exception:
                        attempts_info.append({"url": url, "ctype": ctype, "props_keys": []})
                else:
                    data = {"raw": raw.decode("utf-8", "ignore")}
                    try:
                        html_len = len(data.get("raw") or "")
                        logger.info("html_len=%d ctype=%s", html_len, ctype)
                        attempts_info.append({"url": url, "ctype": ctype, "html_len": html_len})
                    except Exception:
                        attempts_info.append({"url": url, "ctype": ctype})
                sz_local = _extract_subzone_from_wms_json(data)
                try:
                    logger.info("extracted subzona=%s", sz_local)
                except Exception:
                    pass
                return sz_local, ctype
            except _ue.HTTPError as e:
                try:
                    attempts_info.append({"url": url, "error": f"HTTP {int(getattr(e, 'code', 0))}", "ctype": getattr(e, 'headers', {}).get('Content-Type', '')})
                except Exception:
                    attempts_info.append({"url": url, "error": "HTTP error"})
                return None, "error"
            except _ue.URLError as e:
                try:
                    attempts_info.append({"url": url, "error": f"URL error: {e.reason}"})
                except Exception:
                    attempts_info.append({"url": url, "error": "URL error"})
                return None, "error"

        # 0) ArcGIS Identify (si está configurado para el municipio)
        rest_url_pref = cfg.get("rest_identify")
        if rest_url_pref:
            for mode in ("top", "visible", "all"):
                try:
                    sz_id, id_diag = _arcgis_identify_extract(rest_url_pref, req.lon, req.lat, sr=4326, tol=16, layers_mode=mode)
                except Exception:
                    sz_id, id_diag = None, {"error": "identify exception"}
                try:
                    id_diag["layers_mode"] = mode
                    attempts_info.append({"identify": id_diag})
                except Exception:
                    pass
                if sz_id:
                    return InferSubzoneResponse(municipio=req.municipio, subzona=sz_id, source="identify")

        # 1) ArcGIS Feature Layer /query (si está configurado)
        feature_url = cfg.get("feature_url")
        if feature_url:
            sz_q, q_diag = _arcgis_feature_query(feature_url, req.lon, req.lat, sr_in=4326, out_fields="*")
            try: attempts_info.append({"feature_query": q_diag})
            except Exception: pass
            if sz_q:
                return InferSubzoneResponse(municipio=req.municipio, subzona=sz_q, source="feature_query")

        # 2) WMS clásico (si hay configuración base/layers)
        if "base" in cfg and "layers" in cfg:
            sz, _ = _attempt(cfg["base"], cfg["layers"], cfg.get("info_format", "application/json"), version="1.1.1")
            if sz:
                return InferSubzoneResponse(municipio=req.municipio, subzona=sz)

        # Fallback genérico: probar con text/html si el primer intento no devolvió subzona
        sz_html = None
        if "base" in cfg and "layers" in cfg:
            try:
                sz_html, _ = _attempt(cfg["base"], cfg["layers"], "text/html", version="1.1.1")
            except Exception:
                sz_html = None
        if sz_html:
            return InferSubzoneResponse(municipio=req.municipio, subzona=sz_html)

        # Fallback adicional: reintentar con WMS 1.3.0 (CRS + I/J)
        if "base" in cfg and "layers" in cfg:
            try:
                sz_130_json, _ = _attempt(cfg["base"], cfg["layers"], cfg.get("info_format", "application/json"), version="1.3.0")
            except Exception:
                sz_130_json = None
            if sz_130_json:
                return InferSubzoneResponse(municipio=req.municipio, subzona=sz_130_json)
            try:
                sz_130_html, _ = _attempt(cfg["base"], cfg["layers"], "text/html", version="1.3.0")
            except Exception:
                sz_130_html = None
            if sz_130_html:
                return InferSubzoneResponse(municipio=req.municipio, subzona=sz_130_html)

        # Reintentos específicos para A Coruña: variaciones de capa y formato
        m = (req.municipio or "").strip().lower()
        if m in ("a coruña", "a coruna", "coruna", "a corunha"):
            layer_candidates = [cfg.get("layers", "pgom13:Ordenanzas"), "Ordenanzas", "pgom13:Ordenanzas"]
            fmt_candidates = [cfg.get("info_format", "application/json"), "text/html", "application/json"]
            tried: set[tuple[str,str]] = set()
            for lyr in layer_candidates:
                for fmt in fmt_candidates:
                    key = (lyr, fmt)
                    if key in tried:
                        continue
                    tried.add(key)
                    # Probar 1.1.1 y 1.3.0 por cada combinación
                    sz2, _ctype = _attempt(cfg["base"], lyr, fmt, version="1.1.1")
                    if not sz2:
                        sz2, _ctype = _attempt(cfg["base"], lyr, fmt, version="1.3.0")
                    if sz2:
                        return InferSubzoneResponse(municipio=req.municipio, subzona=sz2)
            # Fallback adicional: ArcGIS REST Identify
            rest_url = cfg.get("rest_identify")
            if rest_url:
                try:
                    sz3, id_diag = _arcgis_identify_extract(rest_url, req.lon, req.lat, sr=4326, tol=16)
                except Exception:
                    sz3, id_diag = None, {}
                try:
                    attempts_info.append({"identify": id_diag})
                except Exception:
                    pass
                if sz3:
                    try:
                        logging.getLogger("zoning.infer_subzone").info("identify extracted subzona=%s", sz3)
                    except Exception:
                        pass
                    return InferSubzoneResponse(municipio=req.municipio, subzona=sz3, source="identify")

        # Intento Identify genérico si hay configuración para el municipio
        rest_url_generic = cfg.get("rest_identify")
        if rest_url_generic:
            try:
                sz_ident, id_diag2 = _arcgis_identify_extract(rest_url_generic, req.lon, req.lat, sr=4326, tol=16)
            except Exception:
                sz_ident, id_diag2 = None, {}
            try:
                attempts_info.append({"identify": id_diag2})
            except Exception:
                pass
            if sz_ident:
                return InferSubzoneResponse(municipio=req.municipio, subzona=sz_ident, source="identify")

        # Reintentos específicos para Vigo: variaciones de formato (algunos servidores devuelven HTML)
        if m in ("vigo",):
            layer_candidates = [cfg.get("layers", "CLASES_DE_SUELO"), "CLASES_DE_SUELO"]
            fmt_candidates = [cfg.get("info_format", "application/json"), "text/html", "application/json"]
            tried: set[tuple[str,str]] = set()
            for lyr in layer_candidates:
                for fmt in fmt_candidates:
                    key = (lyr, fmt)
                    if key in tried:
                        continue
                    tried.add(key)
                    sz2, _ctype = _attempt(cfg["base"], lyr, fmt)
                    if sz2:
                        return InferSubzoneResponse(municipio=req.municipio, subzona=sz2)

        # Si nada funcionó, devolvemos sin subzona
        return InferSubzoneResponse(municipio=req.municipio, subzona=None, diagnostics={"attempts": attempts_info})
    except Exception as e:
        # No bloquear: devolver sin subzona
        return InferSubzoneResponse(municipio=req.municipio, subzona=None, diagnostics={"error": str(e)})


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
                # Auto-inferir subzona si estamos en Vigo y no se proporcionó, usando el centro de la geometría
                try:
                    if (not getattr(req, 'subzona', None)) and getattr(req, 'municipio', None):
                        if str(req.municipio).strip().lower().find('vigo') >= 0:
                            cfg = _wms_config_for_municipio(req.municipio)
                            feature_url = (cfg or {}).get('feature_url') if isinstance(cfg, dict) else None
                            if feature_url and getattr(req, 'geometry', None):
                                lon, lat = _centroid_lonlat_from_geojson(req.geometry, getattr(req, 'crs', None))
                                if (lon is not None) and (lat is not None):
                                    subz, _diag = _arcgis_feature_query(feature_url, float(lon), float(lat))
                                    if subz:
                                        req.subzona = subz
                except Exception:
                    pass
                # Usar el proveedor activo (CSV/mock) para obtener parámetros del plan
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
        # Fallback: continuar con valores por defecto si el proveedor falla
        reasons.append(f"Fallback de plan: {e}")

    # Fallback definitivo si seguimos sin altura
    if altura is None:
        altura = 12.0
        if retranqueo is None:
            retranqueo = 3.0
        reasons.append("Parámetros por defecto aplicados (altura=12m, retranqueo_min=3m)")

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
        feat = compute_building_envelope(req.geometry, params, street_axis=req.street_axis, front_direction_source=front_dir_source, crs=getattr(req, 'crs', None))
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
                'municipio': (req.municipio or '').strip() if isinstance(req.municipio, str) else req.municipio,
                'subzona': (req.subzona or '').strip() if isinstance(req.subzona, str) else req.subzona,
            },
            feature=None,
            geometry_summary=geometry_summary,
        )

    props = feat.get('properties') or {}
    # Exponer municipio/subzona en las properties para consumo del visor
    try:
        muni_norm = (req.municipio or '').strip() if isinstance(req.municipio, str) else req.municipio
        subz_norm = (req.subzona or '').strip() if isinstance(req.subzona, str) else req.subzona
        if isinstance(props, dict):
            if muni_norm and 'municipio' not in props:
                props['municipio'] = muni_norm
            if subz_norm and 'subzona' not in props:
                props['subzona'] = subz_norm
            feat['properties'] = props
    except Exception:
        pass
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
            'municipio': (req.municipio or '').strip() if isinstance(req.municipio, str) else req.municipio,
            'subzona': (req.subzona or '').strip() if isinstance(req.subzona, str) else req.subzona,
        },
        feature=feat,
        geometry_summary=geometry_summary,
    )


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


def _render_assess_report_html(body: dict, res: "AssessResponse", *, logo: Optional[str] = None, title: Optional[str] = None, client: Optional[str] = None, project: Optional[str] = None, snapshot_data_url: Optional[str] = None, brand_color: Optional[str] = None, signature: bool = False, sign_by: Optional[str] = None, sign_place: Optional[str] = None, notes: Optional[str] = None, source_ref: Optional[str] = None) -> str:
    import html as _html
    def esc(x: str) -> str:
        try:
            return _html.escape(x if isinstance(x, str) else str(x))
        except Exception:
            return str(x)
    v = (res.viability or '').upper()
    color = {'APTO':'#2e7d32','CONDICIONADO':'#f57f17','NO APTO':'#c62828'}.get(v, (brand_color or '#37474f'))
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
    # Bloque de firma pre-renderizado para evitar expresiones complejas en la f-string principal
    sig_html = ''
    if signature:
        try:
            _sb = esc(sign_by) if sign_by else ''
            _sp = esc(sign_place) if sign_place else 'Lugar y fecha'
            _sb_txt = (f" · {_sb}") if _sb else ''
            sig_html = (
                "<h2>Firma</h2>"
                "<div style=\"display:flex;gap:24px;flex-wrap:wrap;margin-top:8px\">"
                "<div style=\"flex:1 1 280px;border:1px dashed var(--line);border-radius:6px;padding:12px;\">"
                "<div style=\"height:70px\"></div>"
                f"<div class=\"muted\" style=\"margin-top:6px\">Firma{_sb_txt}</div>"
                "</div>"
                "<div style=\"flex:1 1 240px;border:1px dashed var(--line);border-radius:6px;padding:12px;\">"
                "<div style=\"height:70px\"></div>"
                "<div class=\"muted\" style=\"margin-top:6px\">Sello</div>"
                "</div>"
                "<div style=\"flex:1 1 240px;border:1px dashed var(--line);border-radius:6px;padding:12px;\">"
                "<div style=\"height:70px\"></div>"
                f"<div class=\"muted\" style=\"margin-top:6px\">{_sp}</div>"
                "</div>"
                "</div>"
            )
        except Exception:
            sig_html = ''
    # Resumen ejecutivo
    try:
        muni = esc((res.context or {}).get('municipio') or (body.get('municipio') if isinstance(body, dict) else '') or '')
    except Exception:
        muni = ''
    try:
        subz = esc((res.context or {}).get('subzona') or (body.get('subzona') if isinstance(body, dict) else '') or '')
    except Exception:
        subz = ''
    prov_kind = esc((_PLAN_PROVIDER_CACHE.get('kind') or 'desconocido'))
    alt = pe.get('altura_maxima_m')
    ret = pe.get('retranqueo_min_m')
    ocu = pe.get('ocupacion_max') or pe.get('ocupacion')
    edi = pe.get('edificabilidad_max_m2_m2') or pe.get('edificabilidad')
    def _fmt(x):
        try:
            if x is None:
                return '—'
            if isinstance(x, (int, float)):
                return str(round(float(x), 2))
            return esc(str(x))
        except Exception:
            return esc(str(x))
    resumen_html = (
        f"<p class=muted>Zona: {muni or '—'}{(' · ' + subz) if subz else ''} · Proveedor: {prov_kind}. "
        f"Viabilidad: <b>{esc(v or '—')}</b>. Altura máx: {_fmt(alt)} m; Retranqueo: {_fmt(ret)} m; "
        f"Ocupación: {_fmt(ocu)}; Edificabilidad: {_fmt(edi)}.</p>"
    )
    ficha_rows = ''.join([
        f"<tr><td>Municipio</td><td>{muni or '—'}</td></tr>",
        f"<tr><td>Subzona</td><td>{subz or '—'}</td></tr>",
        f"<tr><td>Proveedor</td><td>{prov_kind}</td></tr>",
        f"<tr><td>Altura máxima (m)</td><td>{_fmt(alt)}</td></tr>",
        f"<tr><td>Retranqueo mínimo (m)</td><td>{_fmt(ret)}</td></tr>",
        f"<tr><td>Ocupación máx</td><td>{_fmt(ocu)}</td></tr>",
        f"<tr><td>Edificabilidad máx</td><td>{_fmt(edi)}</td></tr>",
    ])
    src_row = ''
    if source_ref:
        try:
            _s = esc(source_ref)
            # Detectar si parece URL
            if isinstance(source_ref, str) and (source_ref.startswith('http://') or source_ref.startswith('https://')):
                _s = f"<a href=\"{_s}\" target=\"_blank\" rel=\"noopener\">{_s}</a>"
            src_row = f"<tr><td>Fuente normativa</td><td>{_s}</td></tr>"
        except Exception:
            src_row = ''
    notes_html = ''
    if notes:
        try:
            notes_html = f"<section>\n      <h2>Observaciones</h2>\n      <p>{esc(notes)}</p>\n    </section>"
        except Exception:
            notes_html = ''
    html = f"""
<!doctype html>
<html lang=es>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{ttl}</title>
  <style>
    :root{{
      --fg:#eaeaea; --bg:#111; --card:#1a1a1a; --line:#2e2e2e; --muted:#b0b0b0; --accent:{esc(brand_color) if brand_color else '#607d8b'};
    }}
    /* Pantalla (oscuro sobrio) */
    body{{font-family:"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);margin:24px;line-height:1.45;}}
    .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 24px;max-width:980px;margin:0 auto;}}
    h1{{margin:0 0 8px 0;font-size:24px;font-weight:650;letter-spacing:.2px;}}
    h2{{margin:18px 0 8px 0;font-size:18px;font-weight:600;}}
    h3{{margin:16px 0 8px 0;font-size:16px;font-weight:600;}}
    .badge{{display:inline-block;padding:4px 12px;border-radius:18px;border:1px solid {color};color:{color};font-weight:600;}}
    h2, h3{{ border-left:4px solid var(--accent); padding-left:8px; }}
    .meta{{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-top:2px}}
    table{{width:100%;border-collapse:collapse;margin-top:10px;}}
    th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;font-size:14px;vertical-align:top;}}
    th{{color:var(--muted);font-weight:600;}}
    ul{{margin:6px 0 0 20px;}}
    .muted{{opacity:0.85;font-size:13px;}}
    .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}
    .toolbar{{position:sticky;top:0;display:flex;gap:8px;margin-bottom:14px}}
    .toolbar button{{padding:6px 10px;border:1px solid #4a4a4a;background:#1f1f1f;color:#eee;border-radius:6px;cursor:pointer}}
    .toolbar button:hover{{background:#2a2a2a}}
    footer{{margin-top:18px;color:var(--muted);font-size:12px}}
    /* Impresión (claro, márgenes y tipografía más formal) */
    @media print{{
      body{{background:#fff;color:#000;margin:0;font-family:"Georgia", "Times New Roman", Times, serif;}}
      .card{{border:none;border-radius:0;padding:0 2mm;}}
      .toolbar{{display:none}}
      a[href]::after{{content:"";}}
      h1{{font-size:22px}}
      h2{{font-size:16px}}
      h3{{font-size:14px}}
      @page{{margin:14mm}}
    }}
  </style>
  <meta name="format-detection" content="telephone=no"/>
  <meta name="color-scheme" content="dark light"/>
</head>
<body>
  <div class="toolbar">
    <button onclick="window.print()">Descargar PDF</button>
    <button onclick="window.close()">Cerrar</button>
  </div>
  <div class="card">
    <header style="display:flex;align-items:flex-start;gap:12px;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:12px">{logo_html}<h1 style="margin:0">{ttl}</h1></div>
      <div class="muted">Generado: {esc(gen_date)}</div>
    </header>
    <div class="meta">
      <span class="badge">{v}</span>
      {loc_txt}
      {client_proj}
      {area_txt}
    </div>
    {resumen_html}
    {snap_html}
    <section>
      <h2>Parámetros efectivos</h2>
      <table>
        <thead><tr><th>Parámetro</th><th>Valor</th></tr></thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>
    <section>
      <h2>Ficha técnica</h2>
      <table>
        <tbody>
          {ficha_rows}
          {src_row}
        </tbody>
      </table>
    </section>
    <section class="grid2">
      <div>
        <h2>Viabilidad</h2>
        <div class="muted">Resultado: {v or '—'}</div>
      </div>
      <div>
        <h2>Motivos</h2>
        <ul>{reasons or '<li>—</li>'}</ul>
      </div>
    </section>
    {notes_html}
    <section style="margin-top:14px;">
      {sig_html}
    </section>
    <footer style="margin-top:14px;">
      Este informe es orientativo y no sustituye a la verificación oficial del planeamiento vigente. Revise siempre la normativa y planos urbanísticos aplicables.
    </footer>
  </div>
  
</body>
</html>
"""
    return html

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
        # Calcular diagnóstico de qué limita el volumen (prioridad: ocupación > edificabilidad > retranqueos > altura)
        limiting_factor = "altura"
        limiting_details = {}
        try:
            from src.rules_engine import geometry_checks
            parcel_area = None
            try:
                parcel_area = float(geometry_checks(req.geometry).area)
            except Exception:
                parcel_area = None
            props = (feature.get('properties') or {})
            build_area = props.get('area_m2')
            setback_applied = float(props.get('setback_applied_m') or 0.0)
            dir_applied = (props.get('directional_applicability') == 'applied')
            # Considerar ocupación del plan si existe
            occ_used = None
            occ_cap = None
            # Considerar edificabilidad del plan si existe: si el cap (m2 techo) es menor que el área de una planta edificable, entonces limita edificabilidad inmediatamente
            edi_used = None
            edi_cap = None
            try:
                if req.municipio and (parcel_area is not None) and (build_area is not None):
                    from src.rules_engine import get_plan_params_dynamic
                    _plan = get_plan_params_dynamic(req.municipio, req.subzona)
                    occ_used = getattr(_plan, 'ocupacion_max', None)
                    if occ_used is not None:
                        occ_cap = float(parcel_area) * float(occ_used)
                        try:
                            ba = float(build_area)
                        except Exception:
                            ba = None
                        # Prioridad 1: ocupación limita si el tope de m2 en planta es menor que el área edificable calculada
                        if ba is not None and occ_cap is not None and occ_cap < (ba * 0.99):
                            limiting_factor = 'ocupacion'
                    edi_used = getattr(_plan, 'edificabilidad_max_m2_m2', None)
                    if edi_used is not None:
                        edi_cap = float(parcel_area) * float(edi_used)  # m2 techo total permitidos
                        try:
                            ba = float(build_area)  # m2 de una planta
                        except Exception:
                            ba = None
                        # Prioridad 2: edificabilidad limita si incluso una planta excede el tope total de m2/m2
                        if ba is not None and edi_cap is not None and edi_cap < (ba * 0.99) and limiting_factor == 'altura':
                            limiting_factor = 'edificabilidad'
            except Exception:
                pass
            # Prioridad 3: retranqueos si reducen el área edificable frente a la parcela y no limitaron ocupación/edificabilidad
            if limiting_factor == 'altura' and (dir_applied or (setback_applied > 0.0)):
                if (parcel_area is not None and build_area is not None):
                    try:
                        ba = float(build_area)
                    except Exception:
                        ba = None
                    if ba is not None and ba <= parcel_area * 0.99:
                        limiting_factor = 'retranqueos'
            limiting_details = {
                'parcel_area_m2': parcel_area,
                'buildable_area_m2': build_area,
                'setback_applied_m': props.get('setback_applied_m'),
                'directional_applicability': props.get('directional_applicability'),
                'ocupacion_max': occ_used,
                'ocupacion_cap_area_m2': occ_cap,
                'edificabilidad_max_m2_m2': edi_used,
                'edificabilidad_cap_m2': edi_cap,
            }
        except Exception:
            pass
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
            # Ruta rápida para GLTF/GLB: si no es estricto y la geometría es Polygon simple sin huecos,
            # evitamos cálculos complejos y usamos directamente la geometría aportada.
            if (not strict) and fmt in ('gltf', 'glb') and isinstance(req.geometry, dict):
                g = req.geometry
                if (g.get('type') == 'Polygon') and isinstance(g.get('coordinates'), list):
                    coords = g.get('coordinates')
                    if len(coords) == 1 and len(coords[0]) >= 4:  # un único anillo, al menos 4 puntos (cerrado)
                        feature = {
                            'type': 'Feature',
                            'geometry': g,
                            'properties': {
                                'height_m': float(altura or 0.0),
                                'area_m2': None,
                            }
                        }
            # Si no se aplicó la ruta rápida, usar el cómputo completo de la envolvente
            if feature is None:
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
                    crs=getattr(req, 'crs', None),
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
        # Considerar "agotado" si no hay feature o si el área es prácticamente nula
        def _is_exhausted(feat: dict | None) -> bool:
            try:
                if not feat:
                    return True
                props = feat.get('properties') or {}
                area = props.get('area_m2')
                if area is None:
                    return False
                return float(area) <= 1e-8
            except Exception:
                return False

        if _is_exhausted(feature):
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
            # Para GLTF, devolver siempre Response con el JSON serializado
            media = 'model/gltf+json'
            fname = 'building.gltf'
            return Response(content=content, media_type=media, headers=({"Content-Disposition": f"attachment; filename=\"{fname}\""} if download else {}))
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
