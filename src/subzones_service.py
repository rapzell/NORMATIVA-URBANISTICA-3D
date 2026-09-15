"""Servicio de subzonas espaciales para integracion GIS con GeoLibre.

Carga el dataset piloto de subzonas en GeoJSON y permite consultarlo
por municipio o devolverlo completo. Esto es la base de la Fase 2 del
roadmap de integracion con GeoLibre.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_OVERPASS_CACHE: dict[tuple[str, int], dict[str, Any]] = {}
_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
] 

MUNICIPIO_CENTERS = {
    "vigo": {"center": [-8.722, 42.232], "delta": 0.02},
    "a coruna": {"center": [-8.400, 43.370], "delta": 0.02},
    "coruna": {"center": [-8.400, 43.370], "delta": 0.02},
    "santiago": {"center": [-8.540, 42.880], "delta": 0.02},
    "santiago de compostela": {"center": [-8.540, 42.880], "delta": 0.02},
}

# Ruta del dataset piloto
_DATOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
_SUBZONAS_PATH = os.path.join(_DATOS_DIR, "subzonas_piloto.geojson")


@lru_cache(maxsize=1)
def _load_subzones_raw() -> dict[str, Any]:
    """Carga y cachea el GeoJSON de subzonas piloto."""
    if not os.path.exists(_SUBZONAS_PATH):
        return {"type": "FeatureCollection", "features": []}
    with open(_SUBZONAS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_subzones(municipio: str | None = None) -> dict[str, Any]:
    """Devuelve el GeoJSON de subzonas, opcionalmente filtrado por municipio.

    Args:
        municipio: si se proporciona, filtra features cuyo municipio coincide
                   (case-insensitive, sin acentos en la comparacion).

    Returns:
        GeoJSON FeatureCollection con las subzonas que coincidan.
    """
    data = _load_subzones_raw()
    if not municipio:
        return data

    target = _normalize(municipio)
    filtered = [
        feat for feat in data.get("features", [])
        if _normalize(feat.get("properties", {}).get("municipio", "")) == target
    ]
    return {"type": "FeatureCollection", "features": filtered}


def list_municipios_with_subzones() -> list[str]:
    """Devuelve la lista de municipios que tienen subzonas espaciales."""
    data = _load_subzones_raw()
    seen: list[str] = []
    for feat in data.get("features", []):
        m = feat.get("properties", {}).get("municipio")
        if m and m not in seen:
            seen.append(m)
    return seen


def find_subzone_for_point(lon: float, lat: float) -> dict[str, Any] | None:
    """Busca la subzona que contiene el punto (lon, lat) en EPSG:4326.

    Usa shapely si esta disponible; si no, hace un bounding-box match simple.
    Devuelve las propiedades de la subzona o None.
    """
    data = _load_subzones_raw()
    try:
        from shapely.geometry import Point, shape
        pt = Point(lon, lat)
        for feat in data.get("features", []):
            geom = feat.get("geometry")
            if geom and shape(geom).contains(pt):
                return feat.get("properties")
    except Exception:
        # Fallback: bounding-box simple
        for feat in data.get("features", []):
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [[]])
            if not coords or not coords[0]:
                continue
            ring = coords[0]
            xs = [c[0] for c in ring]
            ys = [c[1] for c in ring]
            if min(xs) <= lon <= max(xs) and min(ys) <= lat <= max(ys):
                return feat.get("properties")
    return None


def find_subzone_by_name(municipio: str, subzona: str) -> dict[str, Any] | None:
    """Busca una subzona por municipio y nombre de subzona."""
    data = _load_subzones_raw()
    muni_norm = _normalize(municipio)
    sz_norm = _normalize(subzona)
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        if _normalize(props.get("municipio") or "") == muni_norm and _normalize(props.get("subzona") or "") == sz_norm:
            return props
    return None


def get_osm_buildings_geojson(municipio: str | None = None, *, limit: int = 800) -> dict[str, Any]:
    """Devuelve edificios OSM en GeoJSON listos para extrusión 3D.

    Usa Overpass desde backend para evitar CORS del navegador.
    Si no hay municipio o no existe centro conocido, devuelve FeatureCollection vacía.
    """
    muni_key = _normalize(municipio or "")
    cfg = MUNICIPIO_CENTERS.get(muni_key)
    if not cfg:
        return {"type": "FeatureCollection", "features": []}

    cache_key = (muni_key, int(limit))
    cached = _OVERPASS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    lon, lat = cfg["center"]
    delta = float(cfg.get("delta") or 0.01)
    raw = None
    last_error = None
    for factor in (0.22, 0.15):
        qd = delta * factor
        south, west, north, east = lat - qd, lon - qd, lat + qd, lon + qd
        query = (
            "[out:json][timeout:8];"
            f"way['building']({south},{west},{north},{east});"
            "out geom;"
        )

        def _fetch_overpass(overpass_url: str):
            req = Request(
                overpass_url,
                data=urlencode({"data": query}).encode("utf-8"),
                headers={"User-Agent": "NormativaGalicia/1.0", "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        from concurrent.futures import ThreadPoolExecutor, as_completed
        pool = ThreadPoolExecutor(max_workers=len(_OVERPASS_URLS))
        futures = [pool.submit(_fetch_overpass, url) for url in _OVERPASS_URLS]
        try:
            for future in as_completed(futures):
                try:
                    raw = future.result()
                    break
                except (HTTPError, URLError, TimeoutError, ValueError) as e:
                    last_error = e
        finally:
            for future in futures:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
        if raw is not None:
            break
    if raw is None:
        raise last_error or RuntimeError("No se pudieron cargar edificios OSM")

    features: list[dict[str, Any]] = []
    for el in (raw.get("elements") or []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 4:
            continue
        coords = [[float(p["lon"]), float(p["lat"])] for p in geom if "lon" in p and "lat" in p]
        if len(coords) < 4:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        tags = el.get("tags") or {}
        height_info = _building_height_details(tags)
        height = round(float(height_info["height"]), 2)
        subzone_props = _find_subzone_for_ring(coords, municipio)
        compliance = _classify_building_compliance(height, subzone_props)
        features.append({
            "type": "Feature",
            "properties": {
                "osm_id": el.get("id"),
                "name": tags.get("name") or "",
                "building": tags.get("building") or "yes",
                "height": height,
                "height_source": height_info["source"],
                "height_estimated": height_info["estimated"],
                "levels": tags.get("building:levels") or None,
                "_altura_visual": round(float(height), 2),
                "municipio": (subzone_props or {}).get("municipio") or municipio,
                "subzona": (subzone_props or {}).get("subzona"),
                "altura_maxima_subzona_m": (subzone_props or {}).get("altura_maxima_m"),
                "normative_status": (subzone_props or {}).get("normative_status"),
                "normative_source": (subzone_props or {}).get("fuente"),
                "cumplimiento_altura": compliance["status"],
                "cumplimiento_detalle": compliance["detail"],
                "color_semantica": compliance["color_semantics"],
            },
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        })
        if len(features) >= max(1, int(limit)):
            break
    result = {"type": "FeatureCollection", "features": features}
    _OVERPASS_CACHE[cache_key] = result
    return result


def _find_subzone_for_ring(coords: list[list[float]], municipio: str | None) -> dict[str, Any] | None:
    try:
        from shapely.geometry import Polygon
        poly = Polygon(coords)
        pt = poly.representative_point()
        return find_subzone_for_point(float(pt.x), float(pt.y))
    except Exception:
        try:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            lon = (min(xs) + max(xs)) / 2.0
            lat = (min(ys) + max(ys)) / 2.0
            return find_subzone_for_point(float(lon), float(lat))
        except Exception:
            return None


def _classify_building_compliance(height: float, subzone_props: dict[str, Any] | None) -> dict[str, str]:
    limit = None if not subzone_props else subzone_props.get("altura_maxima_m")
    if limit is None:
        return {
            "status": "sin_dato",
            "detail": "Sin subzona asociada o sin altura máxima conocida",
            "color_semantics": "gris = sin dato normativo",
        }
    try:
        limit_f = float(limit)
        h = float(height)
    except Exception:
        return {
            "status": "sin_dato",
            "detail": "No se pudo comparar la altura del edificio con el límite disponible",
            "color_semantics": "gris = sin dato normativo",
        }
    is_pilot = str((subzone_props or {}).get("normative_status") or "").lower() == "pilot"
    if h <= limit_f:
        margin = round(limit_f - h, 2)
        if is_pilot:
            return {
                "status": "orientativo_dentro",
                "detail": f"Comparación orientativa: {h} m <= {limit_f} m (margen {margin} m). La subzona y su límite son piloto, no acreditan cumplimiento urbanístico.",
                "color_semantics": "amarillo = comparación con datos piloto",
            }
        return {
            "status": "compatible",
            "detail": f"Altura dentro del máximo de subzona ({h} m <= {limit_f} m, margen {margin} m)",
            "color_semantics": "verde = compatible con la altura máxima",
        }
    excess = round(h - limit_f, 2)
    if is_pilot:
        return {
            "status": "orientativo_supera",
            "detail": f"Comparación orientativa: {h} m > {limit_f} m (exceso {excess} m). La subzona y su límite son piloto, no acreditan incumplimiento urbanístico.",
            "color_semantics": "naranja = posible exceso según datos piloto",
        }
    return {
        "status": "supera_altura",
        "detail": f"Altura por encima del máximo de subzona ({h} m > {limit_f} m, exceso {excess} m)",
        "color_semantics": "rojo = supera la altura máxima",
    }


def _building_height_details(tags: dict[str, Any]) -> dict[str, Any]:
    raw_h = tags.get("height")
    if isinstance(raw_h, str):
        try:
            return {"height": max(2.5, float(raw_h.lower().replace("m", "").strip())), "source": "osm_height", "estimated": False}
        except Exception:
            pass
    raw_levels = tags.get("building:levels")
    if isinstance(raw_levels, str):
        try:
            return {"height": max(3.0, float(raw_levels.strip()) * 3.2), "source": "osm_levels", "estimated": True}
        except Exception:
            pass
    btype = str(tags.get("building") or "").strip().lower()
    if btype in {"apartments", "office", "hospital", "hotel"}:
        return {"height": 18.0, "source": "building_type", "estimated": True}
    if btype in {"commercial", "retail", "school", "church"}:
        return {"height": 12.0, "source": "building_type", "estimated": True}
    if btype in {"industrial", "warehouse"}:
        return {"height": 8.0, "source": "building_type", "estimated": True}
    return {"height": 9.0, "source": "default", "estimated": True}


def _estimate_building_height(tags: dict[str, Any]) -> float:
    return float(_building_height_details(tags)["height"])


def _normalize(s: str) -> str:
    """Normaliza un string para comparacion: minusculas, sin acentos."""
    out = s.strip().lower()
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "ü": "u",
    }
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out
