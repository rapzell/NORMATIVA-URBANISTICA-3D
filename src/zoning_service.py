import json
import logging
import os
import urllib.parse as _up
import urllib.request as _ur


def arcgis_feature_query(feature_url: str, lon: float, lat: float, *, sr_in: int = 4326, out_fields: str = "*") -> tuple[str | None, dict]:
    diag: dict = {"type": "feature_query", "url": feature_url}
    try:
        geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": sr_in}})
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
        data = json.loads(raw.decode("utf-8", "ignore")) if raw else {}
        diag["ok"] = True
        feats = data.get("features") or []
        if not feats:
            return None, diag
        attrs = feats[0].get("attributes") or {}
        diag["attrs_keys"] = list(attrs.keys())
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
        import re as _re
        m = _re.search(r"\b((?:U\s*\d+(?:\.\d+)?)|(?:NR\s*-?\s*\d+))\b", val, flags=_re.IGNORECASE)
        if m:
            return m.group(1).upper().replace(" ", "").replace("NR-", "NR-"), diag
        return val, diag
    except Exception as e:
        diag["error"] = str(e)
        return None, diag


def wms_config_for_municipio(muni: str):
    m = (muni or "").strip().lower()
    if m in ("a coruña", "a coruna", "coruna", "a corunha"):
        return {
            "base": os.getenv("ACORUNA_WMS_BASE", "https://geo.coruna.es/geoserver/wms"),
            "layers": os.getenv("ACORUNA_WMS_LAYERS", "pgom13:Ordenanzas"),
            "info_format": os.getenv("ACORUNA_WMS_INFO_FORMAT", "application/json"),
            "srs": os.getenv("ACORUNA_WMS_SRS", "EPSG:4326"),
        }
    if m in ("vigo",):
        return {
            "rest_identify": (os.getenv("VIGO_ARCGIS_IDENTIFY", "").strip() or None),
            "feature_url": (os.getenv("VIGO_ARCGIS_FEATURE_URL", "").strip() or None),
            "srs": "EPSG:4326",
        }
    return None


def lonlat_to_mercator(lon: float, lat: float):
    import math as _math
    r_major = 6378137.0
    x = r_major * _math.radians(lon)
    lat = max(min(lat, 89.9), -89.9)
    y = r_major * _math.log(_math.tan(_math.pi/4.0 + _math.radians(lat)/2.0))
    return x, y


def mercator_to_lonlat(x: float, y: float):
    import math as _math
    r_major = 6378137.0
    lon = (x / r_major) * (180.0 / _math.pi)
    lat = (2 * _math.atan(_math.exp(y / r_major)) - _math.pi / 2) * (180.0 / _math.pi)
    return lon, lat


def centroid_lonlat_from_geojson(geometry: dict | None, crs: str | None = None) -> tuple[float | None, float | None]:
    if not geometry or not isinstance(geometry, dict):
        return None, None
    try:
        gtype = (geometry.get('type') or '').lower()
        coords = geometry.get('coordinates')
        if gtype in ('polygon', 'multipolygon') and coords:
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
            crs_s = (crs or '').lower()
            if ('3857' in crs_s) or ('900913' in crs_s):
                lon, lat = mercator_to_lonlat(cx, cy)
            else:
                lon, lat = cx, cy
            return float(lon), float(lat)
    except Exception:
        return None, None
    return None, None


def build_wms_getfeatureinfo_url(base: str, layers: str, lon: float, lat: float, srs: str = "EPSG:4326", info_format: str = "application/json", version: str = "1.1.1") -> str:
    try:
        pad_m = float(os.getenv('WMS_GFI_PAD_M', '30'))
    except Exception:
        pad_m = 30.0
    if srs.upper() == "EPSG:4326":
        x, y = lonlat_to_mercator(lon, lat)
        bbox = f"{x-pad_m},{y-pad_m},{x+pad_m},{y+pad_m}"
    else:
        bbox = f"{lon-pad_m},{lat-pad_m},{lon+pad_m},{lat+pad_m}"
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
        **(({"X": "128", "Y": "128"} if version == "1.1.1" else {"I": "128", "J": "128"})),
        "INFO_FORMAT": info_format,
    }
    return f"{base}?{_up.urlencode(params)}"


def extract_subzone_from_wms_json(data: dict) -> str | None:
    try:
        feats = data.get("features") or data.get("FeatureCollection") or []
        if isinstance(feats, dict):
            feats = feats.get("features", [])
        if not feats and isinstance(data, dict) and ("results" in data or "identifyResults" in data):
            lst = data.get("results") or data.get("identifyResults") or []
            if isinstance(lst, list) and lst:
                first = lst[0] or {}
                attrs = first.get("attributes") or first.get("Attributes") or {}
                if isinstance(attrs, dict) and attrs:
                    props = attrs
                    norm = lambda s: ''.join(ch for ch in s.lower() if ch.isalnum())
                    by_norm = {norm(k): k for k in props.keys()}
                    candidates = [
                        "subzona", "ordenanza", "clave", "categoria", "codigo",
                        "claseordenanza", "claveordenanza", "clase", "zonificacion", "zona", "leyenda", "denominacion", "codordenanza", "codorden",
                        "ordenanzas", "claveorden", "claveordenanzas", "planeamiento", "clasesuelo",
                    ]
                    for c in candidates:
                        key_norm = norm(c)
                        if key_norm in by_norm:
                            k = by_norm[key_norm]
                            v = props.get(k)
                            if isinstance(v, str) and v.strip():
                                return v.strip()
                    for k, v in props.items():
                        if isinstance(v, str) and v.strip():
                            return v.strip()
        if not feats and isinstance(data, dict) and "raw" in data:
            import re as _re
            raw = data.get("raw") or ""
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
        f0 = feats[0] if feats else None
        props = (f0.get("properties") if isinstance(f0, dict) else None) or {}
        norm = lambda s: ''.join(ch for ch in s.lower() if ch.isalnum())
        by_norm = {norm(k): k for k in props.keys()}
        candidates = [
            "subzona", "ordenanza", "clave", "categoria", "codigo",
            "clasesuelo", "planeamiento", "clave_ordenanza",
            "ordenanzas", "leyenda", "zona", "zonificacion", "denominacion", "codordenanza", "codorden",
        ]
        for c in candidates:
            key_norm = norm(c)
            if key_norm in by_norm:
                k = by_norm[key_norm]
                v = props.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        for k, v in props.items():
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:
        return None
    return None


def arcgis_identify_extract(url: str, lon: float, lat: float, sr: int = 4326, tol: int = 12, layers_mode: str = "all") -> tuple[str | None, dict]:
    diag: dict = {}
    try:
        geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": sr}})
        pad = 0.001
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
            data = json.loads(raw.decode("utf-8", "ignore"))
        if isinstance(data, dict) and ("results" in data or "identifyResults" in data):
            lst = data.get("results") or data.get("identifyResults") or []
            diag["results_len"] = len(lst) if isinstance(lst, list) else 0
            if isinstance(lst, list) and lst:
                first = lst[0] or {}
                attrs = first.get("attributes") or first.get("Attributes") or {}
                if isinstance(attrs, dict) and attrs:
                    fake = {"features": [{"properties": attrs}]}
                    return extract_subzone_from_wms_json(fake), diag
        return None, diag
    except Exception as e:
        diag["error"] = str(e)
        return None, diag


def infer_subzone(municipio: str, lon: float, lat: float, srs: str | None = "EPSG:4326") -> dict:
    cfg = wms_config_for_municipio(municipio)
    if not cfg:
        return {"municipio": municipio, "subzona": None, "diagnostics": {"reason": "no_cfg_for_municipio"}}
    try:
        import urllib.error as _ue
        logger = logging.getLogger("zoning.infer_subzone")
        attempts_info: list[dict] = []

        def _attempt(base: str, layers: str, info_format: str, *, version: str = "1.1.1") -> tuple[str | None, str]:
            url = build_wms_getfeatureinfo_url(base, layers, lon, lat, srs or cfg.get("srs", "EPSG:4326"), info_format, version)
            try:
                logger.info("attempt muni='%s' layers='%s' fmt='%s' lon=%.6f lat=%.6f url=%s", municipio, layers, info_format, lon, lat, url)
            except Exception:
                pass
            try:
                resp = _ur.urlopen(_ur.Request(url, headers={"User-Agent": "NormativaGalicia/1.0"}), timeout=15)
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", info_format or "application/octet-stream")
                if "json" in ctype.lower():
                    try:
                        data = json.loads(raw.decode("utf-8", "ignore"))
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
                sz_local = extract_subzone_from_wms_json(data)
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

        rest_url_pref = cfg.get("rest_identify")
        if rest_url_pref:
            for mode in ("top", "visible", "all"):
                try:
                    sz_id, id_diag = arcgis_identify_extract(rest_url_pref, lon, lat, sr=4326, tol=16, layers_mode=mode)
                except Exception:
                    sz_id, id_diag = None, {"error": "identify exception"}
                try:
                    id_diag["layers_mode"] = mode
                    attempts_info.append({"identify": id_diag})
                except Exception:
                    pass
                if sz_id:
                    return {"municipio": municipio, "subzona": sz_id, "source": "identify"}

        feature_url = cfg.get("feature_url")
        if feature_url:
            sz_q, q_diag = arcgis_feature_query(feature_url, lon, lat, sr_in=4326, out_fields="*")
            try:
                attempts_info.append({"feature_query": q_diag})
            except Exception:
                pass
            if sz_q:
                return {"municipio": municipio, "subzona": sz_q, "source": "feature_query"}

        if "base" in cfg and "layers" in cfg:
            sz, _ = _attempt(cfg["base"], cfg["layers"], cfg.get("info_format", "application/json"), version="1.1.1")
            if sz:
                return {"municipio": municipio, "subzona": sz}

        sz_html = None
        if "base" in cfg and "layers" in cfg:
            try:
                sz_html, _ = _attempt(cfg["base"], cfg["layers"], "text/html", version="1.1.1")
            except Exception:
                sz_html = None
        if sz_html:
            return {"municipio": municipio, "subzona": sz_html}

        if "base" in cfg and "layers" in cfg:
            try:
                sz_130_json, _ = _attempt(cfg["base"], cfg["layers"], cfg.get("info_format", "application/json"), version="1.3.0")
            except Exception:
                sz_130_json = None
            if sz_130_json:
                return {"municipio": municipio, "subzona": sz_130_json}
            try:
                sz_130_html, _ = _attempt(cfg["base"], cfg["layers"], "text/html", version="1.3.0")
            except Exception:
                sz_130_html = None
            if sz_130_html:
                return {"municipio": municipio, "subzona": sz_130_html}

        m = (municipio or "").strip().lower()
        if m in ("a coruña", "a coruna", "coruna", "a corunha"):
            layer_candidates = [cfg.get("layers", "pgom13:Ordenanzas"), "Ordenanzas", "pgom13:Ordenanzas"]
            fmt_candidates = [cfg.get("info_format", "application/json"), "text/html", "application/json"]
            tried: set[tuple[str, str]] = set()
            for lyr in layer_candidates:
                for fmt in fmt_candidates:
                    key = (lyr, fmt)
                    if key in tried:
                        continue
                    tried.add(key)
                    sz2, _ctype = _attempt(cfg["base"], lyr, fmt, version="1.1.1")
                    if not sz2:
                        sz2, _ctype = _attempt(cfg["base"], lyr, fmt, version="1.3.0")
                    if sz2:
                        return {"municipio": municipio, "subzona": sz2}
            rest_url = cfg.get("rest_identify")
            if rest_url:
                try:
                    sz3, id_diag = arcgis_identify_extract(rest_url, lon, lat, sr=4326, tol=16)
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
                    return {"municipio": municipio, "subzona": sz3, "source": "identify"}

        rest_url_generic = cfg.get("rest_identify")
        if rest_url_generic:
            try:
                sz_ident, id_diag2 = arcgis_identify_extract(rest_url_generic, lon, lat, sr=4326, tol=16)
            except Exception:
                sz_ident, id_diag2 = None, {}
            try:
                attempts_info.append({"identify": id_diag2})
            except Exception:
                pass
            if sz_ident:
                return {"municipio": municipio, "subzona": sz_ident, "source": "identify"}

        if m in ("vigo",):
            layer_candidates = [cfg.get("layers", "CLASES_DE_SUELO"), "CLASES_DE_SUELO"]
            fmt_candidates = [cfg.get("info_format", "application/json"), "text/html", "application/json"]
            tried: set[tuple[str, str]] = set()
            for lyr in layer_candidates:
                for fmt in fmt_candidates:
                    key = (lyr, fmt)
                    if key in tried:
                        continue
                    tried.add(key)
                    sz2, _ctype = _attempt(cfg["base"], lyr, fmt)
                    if sz2:
                        return {"municipio": municipio, "subzona": sz2}

        return {"municipio": municipio, "subzona": None, "diagnostics": {"attempts": attempts_info}}
    except Exception as e:
        return {"municipio": municipio, "subzona": None, "diagnostics": {"error": str(e)}}
