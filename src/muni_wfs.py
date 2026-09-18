"""Capas vectoriales municipales propias (fuera de SIOTUGA).

Algunos concellos publican su planeamiento en GeoServer/ArcGIS
propios. Cuando existe una capa oficial de ordenanzas SUC, una
consulta punto-en-polígono resuelve la ordenanza de una parcela sin
intervención manual — el hueco de fiabilidad principal del asistente.

Configuración por INE en ``ORDSUC_LAYERS``; solo se usan capas
oficiales del propio concello y el resultado se etiqueta con el
instrumento y la URL del servicio.
"""
from __future__ import annotations

import requests

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


def consultar_ordenanza_punto(lon: float, lat: float,
                              ine: str | None) -> dict | None:
    """Ordenanza SUC oficial del punto vía WFS municipal.

    Devuelve ``{ordenanza, candidatas, data_quality, fuente,
    instrumento}`` o ``None`` si el municipio no tiene capa o el
    servicio falla — nunca inventa.
    """
    cfg = ORDSUC_LAYERS.get(str(ine or ''))
    if not cfg or lon is None or lat is None:
        return None
    eps = 0.0006  # ~50 m — las features se filtran por contención real
    try:
        r = requests.get(cfg['url'], params={
            'service': 'WFS', 'version': '2.0.0',
            'request': 'GetFeature', 'typeNames': cfg['layer'],
            'bbox': f'{lon-eps},{lat-eps},{lon+eps},{lat+eps},EPSG:4326',
            'srsName': 'EPSG:4326',  # reproyecta la salida a lon/lat
            'outputFormat': 'application/json', 'count': '50',
        }, timeout=15)
        feats = (r.json() or {}).get('features') or []
    except Exception:
        return {'data_quality': 'unavailable',
                'error': 'WFS municipal no responde',
                'fuente': cfg['fuente']}

    hits = [f for f in feats
            if f.get('geometry')
            and _point_in_poly(lon, lat, f['geometry'])]
    campo = cfg['campo']
    candidatas = sorted({
        str((f.get('properties') or {}).get(campo) or '').strip()
        for f in hits
    } - {''})
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
        'campo': campo,
        'nota': ('Cartografía oficial municipal publicada por el '
                 'concello; cotejar con la normativa vigente si el '
                 'plan se ha modificado tras la fecha de la capa.'),
    }
