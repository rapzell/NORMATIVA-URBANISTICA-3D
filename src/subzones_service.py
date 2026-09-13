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
