"""Capas vectoriales municipales propias (fuera de SIOTUGA).

Algunos concellos publican su planeamiento en GeoServer/ArcGIS
propios. Cuando existe una capa oficial de ordenanzas SUC, una
consulta punto-en-polígono resuelve la ordenanza de una parcela sin
intervención manual — el hueco de fiabilidad principal del asistente.

Configuración por INE en ``ORDSUC_LAYERS``; solo se usan capas
oficiales del propio concello y el resultado se etiqueta con el
instrumento y la URL del servicio. La capa se descarga una vez y se
cachea en ``datos/cache/muni_wfs/`` 30 días para consultas masivas
(p. ej. etiquetar todos los edificios del visor).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

_CACHE_DIR = (Path(__file__).resolve().parent.parent / 'datos'
              / 'cache' / 'muni_wfs')
_CACHE_TTL_S = 30 * 24 * 3600
_FEATURES_MEM: dict[str, list[dict]] = {}

# Capas oficiales de ordenanzas SUC por municipio (INE).
# Vigo: GeoServer municipal mapas-ogc.vigo.org, capa oficial de
# ordenanzas de SUC publicada por el Concello (identificador con
# fecha 2021-07 — cotejar con el PXOM 2025 si difiere).
ORDSUC_LAYERS = {
    '36057': {
        'url': 'https://mapas-ogc.vigo.org/geoserver/ows',
        'layer': 'vigo:36057_pxom_202107_ai02_4ordsuc',
        'campo': 'ordenanza',
        'instrumento': 'Ordenanzas SUC — capa oficial Concello de '
                       'Vigo (36057_pxom_202107_ai02_4ordsuc)',
        'fuente': 'GeoServer municipal Concello de Vigo '
                  '(mapas-ogc.vigo.org)',
    },
}


def _point_in_poly(lon: float, lat: float, geom: dict) -> bool:
    try:
        from shapely.geometry import Point, shape
        from shapely import prepared
        return prepared.prep(shape(geom)).contains(Point(lon, lat))
    except Exception:
        return False


def _cache_path(ine: str) -> Path:
    return _CACHE_DIR / f'{ine}_ordsuc.geojson'


def capa_features(ine: str | None, *, fetch=requests.get) -> list[dict]:
    """Features de la capa oficial de ordenanzas del municipio.

    Usa la copia cacheada en disco (30 días); si no hay o está
    caducada, la descarga paginada del WFS. Devuelve ``[]`` si el
    municipio no tiene capa o el servicio falla.
    """
    cfg = ORDSUC_LAYERS.get(str(ine or ''))
    if not cfg:
        return []
    key = str(ine)
    if key in _FEATURES_MEM:
        return _FEATURES_MEM[key]
    path = _cache_path(key)
    if path.exists() and \
            (time.time() - path.stat().st_mtime) < _CACHE_TTL_S:
        try:
            feats = (json.loads(path.read_text(encoding='utf-8'))
                     .get('features') or [])
            _FEATURES_MEM[key] = feats
            return feats
        except Exception:
            pass
    features: list[dict] = []
    start = 0
    try:
        while True:
            r = fetch(cfg['url'], params={
                'service': 'WFS', 'version': '2.0.0',
                'request': 'GetFeature', 'typeNames': cfg['layer'],
                'srsName': 'EPSG:4326',
                'outputFormat': 'application/json',
                'count': '2000', 'startIndex': str(start),
            }, timeout=30)
            page = (r.json() or {}).get('features') or []
            features.extend(page)
            if len(page) < 2000:
                break
            start += len(page)
    except Exception:
        return []
    if features:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(
                {'type': 'FeatureCollection', 'features': features}),
                encoding='utf-8')
        except Exception:
            pass
    _FEATURES_MEM[key] = features
    return features


# Índice espacial por municipio: la capa cacheada se indexa una sola
# vez con STRtree — sin él, etiquetar 500 edificios exigiría preparar
# ~3.700 geometrías por edificio.
_TREE_CACHE: dict[str, tuple] = {}


def _tree(ine: str, features: list[dict]):
    key = str(ine)
    cached = _TREE_CACHE.get(key)
    if cached and cached[0] is features:
        return cached[1], cached[2], cached[3]
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    geoms, feats = [], []
    for f in features:
        if not f.get('geometry'):
            continue
        try:
            geoms.append(shape(f['geometry']))
            feats.append(f)
        except Exception:
            continue
    tree = STRtree(geoms)
    _TREE_CACHE[key] = (features, tree, geoms, feats)
    return tree, geoms, feats


def _ordenanza_desde_features(lon: float, lat: float,
                              features: list[dict],
                              campo: str,
                              ine: str | None = None) -> list[str]:
    if ine:
        from shapely.geometry import Point
        tree, geoms, feats = _tree(str(ine), features)
        pt = Point(lon, lat)
        hits = [feats[i] for i in tree.query(pt)
                if geoms[i].contains(pt)]
    else:
        hits = [f for f in features
                if f.get('geometry')
                and _point_in_poly(lon, lat, f['geometry'])]
    return sorted({
        str((f.get('properties') or {}).get(campo) or '').strip()
        for f in hits
    } - {''})


def _fetch_bbox_features(lon: float, lat: float, cfg: dict) -> list[dict]:
    eps = 0.0006  # ~50 m — las features se filtran por contención real
    r = requests.get(cfg['url'], params={
        'service': 'WFS', 'version': '2.0.0',
        'request': 'GetFeature', 'typeNames': cfg['layer'],
        'bbox': f'{lon-eps},{lat-eps},{lon+eps},{lat+eps},EPSG:4326',
        'srsName': 'EPSG:4326',  # reproyecta la salida a lon/lat
        'outputFormat': 'application/json', 'count': '50',
    }, timeout=15)
    return (r.json() or {}).get('features') or []


def consultar_ordenanza_punto(lon: float, lat: float,
                              ine: str | None) -> dict | None:
    """Ordenanza SUC oficial del punto vía WFS municipal.

    Primero la copia local cacheada de la capa; si no hay, consulta
    WFS puntual. Devuelve ``{ordenanza, candidatas, data_quality,
    fuente, instrumento}`` o ``None`` si el municipio no tiene capa —
    nunca inventa.
    """
    cfg = ORDSUC_LAYERS.get(str(ine or ''))
    if not cfg or lon is None or lat is None:
        return None
    feats = capa_features(ine)
    if not feats:
        try:
            feats = _fetch_bbox_features(lon, lat, cfg)
        except Exception:
            return {'data_quality': 'unavailable',
                    'error': 'WFS municipal no responde',
                    'fuente': cfg['fuente']}
    candidatas = _ordenanza_desde_features(
        lon, lat, feats, cfg['campo'], ine=ine)
    if not candidatas:
        return {'data_quality': 'unavailable',
                'error': 'Punto fuera de la capa de ordenanzas SUC',
                'fuente': cfg['fuente'],
                'instrumento': cfg['instrumento'],
                'candidatas': []}
    return {
        'ordenanza': candidatas[0] if len(candidatas) == 1 else None,
        'candidatas': candidatas,
        'ambigua': len(candidatas) > 1,
        'data_quality': 'official',
        'fuente': cfg['fuente'],
        'instrumento': cfg['instrumento'],
        'campo': cfg['campo'],
        'nota': ('Cartografía oficial municipal publicada por el '
                 'concello; cotejar con la normativa vigente si el '
                 'plan se ha modificado tras la fecha de la capa.'),
    }
