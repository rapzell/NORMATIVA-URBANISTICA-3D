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
#
# Dos protocolos:
#   - 'wfs' (por defecto): GeoServer WFS 2.0 paginado por startIndex.
#   - 'arcgis': ArcGIS REST `.../query?f=geojson` paginado por
#     resultOffset (maxRecordCount 2000 en ambos servidores).
# Al descargar, el valor de ``campo`` se copia siempre a la prop
# normalizada ``ordenanza`` — el resto del pipeline (STRtree, mapa
# vectorial, lookup) trabaja solo con ``ordenanza``.
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
    # A Coruña: IDE municipal (ide.coruna.gal) — capa oficial
    # "CALIFICACIÓN. ZONIFICACIÓN" del Mapa de Gestión del PGM 2013.
    # Códigos SUBZONA tipo NZ_4_1 (Normas Zonales), uso característico
    # y enlace a la ficha oficial de la subzona. Filtrada a VIGENTE.
    '15030': {
        'tipo': 'arcgis',
        'url': ('https://ide.coruna.gal/server/rest/services/Publica/'
                'PGM13_FICHAS_INFORMACION/MapServer/2/query'),
        'where': "ESTADO='VIGENTE'",
        'campo': 'SUBZONA',
        'extras': {'uso': 'USOCARACT', 'denominacion': 'DENOMINAC',
                   'cualificacion': 'CUALIFICACIÓN', 'doc': 'ENLACE_02'},
        'instrumento': 'Calificación. Zonificación — PGM 2013 '
                       'Concello da Coruña (Mapa de Gestión)',
        'fuente': 'IDE municipal Concello da Coruña (ide.coruna.gal)',
    },
    # Santiago: Xeoportal municipal (ArcGIS Enterprise) — capa oficial
    # "Ordenanzas" del servicio RegulacionUsos2025. El campo
    # DOCUMENTO enlaza al PDF oficial de cada ordenanza.
    '15078': {
        'tipo': 'arcgis',
        'url': ('https://xeoportal.santiagodecompostela.gal/ags/rest/'
                'services/RegulacionUsos2025/FeatureServer/9/query'),
        'campo': 'ORDENANZA',
        'prefijo_ordenanza': 'Ordenanza ',
        'extras': {'uso': 'USO', 'zona': 'ZONA', 'doc': 'DOCUMENTO'},
        'instrumento': 'Ordenanzas — Regulación dos Usos 2025 '
                       'Concello de Santiago',
        'fuente': 'Xeoportal Concello de Santiago '
                  '(xeoportal.santiagodecompostela.gal)',
    },
}


# Capas oficiales de alineaciones del plan vigente (sirven para medir
# el «ancho de rúa» de las tablas de altura, p.ej. ordenanza U2 de
# Vigo). Vigo publica la del PXOM 2025 definitivo.
ALIN_LAYERS = {
    '36057': {
        'url': 'https://mapas-ogc.vigo.org/geoserver/ows',
        'layer': 'vigo:36057_PXOM_202502_AD01_O_ALIN',
        'fuente': 'GeoServer municipal Concello de Vigo '
                  '(mapas-ogc.vigo.org)',
        'instrumento': 'Alineaciones oficiales PXOM 2025 '
                       '(36057_PXOM_202502_AD01_O_ALIN)',
    },
    '15078': {
        'tipo': 'arcgis',
        'url': 'https://xeoportal.santiagodecompostela.gal/ags/rest/'
               'services/Planeamento_urbanistico/MapServer/15/query',
        'fuente': 'XeoPortal Concello de Santiago '
                  '(xeoportal.santiagodecompostela.gal)',
        'instrumento': 'Aliñacións oficiais — Planeamento urbanístico '
                       'municipal de Santiago',
    },
}

_ALIN_MEM: dict[str, list] = {}


def alineaciones_features(ine: str | None,
                          *, fetch=requests.get) -> list[dict]:
    """Features de la capa oficial de alineaciones del municipio.

    Mismo patrón que ``capa_features``: copia cacheada en disco 30 días
    (``{ine}_alin.geojson``) y descarga paginada WFS si caduca. ``[]``
    si el municipio no publica la capa.
    """
    cfg = ALIN_LAYERS.get(str(ine or ''))
    if not cfg:
        return []
    key = str(ine)
    if key in _ALIN_MEM:
        return _ALIN_MEM[key]
    path = _CACHE_DIR / f'{key}_alin.geojson'
    if path.exists() and \
            (time.time() - path.stat().st_mtime) < _CACHE_TTL_S:
        try:
            feats = (json.loads(path.read_text(encoding='utf-8'))
                     .get('features') or [])
            _ALIN_MEM[key] = feats
            return feats
        except Exception:
            pass
    try:
        if cfg.get('tipo') == 'arcgis':
            features = _fetch_arcgis_features(cfg, fetch)
        else:
            features = []
            start = 0
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
    _ALIN_MEM[key] = features
    return features


def alineaciones_cfg(ine: str | None) -> dict | None:
    return ALIN_LAYERS.get(str(ine or ''))


def _point_in_poly(lon: float, lat: float, geom: dict) -> bool:
    try:
        from shapely.geometry import Point, shape
        from shapely import prepared
        return prepared.prep(shape(geom)).contains(Point(lon, lat))
    except Exception:
        return False


def _cache_path(ine: str) -> Path:
    return _CACHE_DIR / f'{ine}_ordsuc.geojson'


def _fetch_wfs_features(cfg: dict, fetch) -> list[dict]:
    """Descarga paginada GeoServer WFS 2.0 (startIndex)."""
    features: list[dict] = []
    start = 0
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
    return features


def _fetch_arcgis_features(cfg: dict, fetch) -> list[dict]:
    """Descarga paginada ArcGIS REST ``query?f=geojson`` (resultOffset;
    los servidores de Coruña y Santiago limitan a 2000 registros)."""
    features: list[dict] = []
    offset = 0
    while True:
        r = fetch(cfg['url'], params={
            'where': cfg.get('where') or '1=1',
            'outFields': '*', 'f': 'geojson', 'outSR': '4326',
            'resultRecordCount': '2000', 'resultOffset': str(offset),
        }, timeout=60)
        page = (r.json() or {}).get('features') or []
        features.extend(page)
        if len(page) < 2000:
            break
        offset += len(page)
        if offset > 200000:
            break
    return features


def _doc_url(valor) -> str | None:
    """Extrae la URL de un campo documental: ArcGIS la sirve como
    ancla HTML (``<a href='...'>texto</a>``) o como URL/ruta suelta."""
    if not valor:
        return None
    import re
    m = re.search(r"href=['\"]([^'\"]+)['\"]", str(valor))
    if m:
        return m.group(1)
    v = str(valor).strip()
    return v if v.startswith('http') else None


def _normalizar_props(features: list[dict], cfg: dict) -> None:
    """Copia el campo de ordenanza del servicio a la prop normalizada
    ``ordenanza`` y prepara el detalle auxiliar (uso, denominación,
    documento) que consume el contexto oficial."""
    campo = cfg.get('campo') or 'ordenanza'
    extras = cfg.get('extras') or {}
    for f in features:
        p = f.setdefault('properties', {})
        code = str(p.get(campo) or '').strip()
        if code and not p.get('ordenanza'):
            p['ordenanza'] = code
        det: dict = {}
        for nombre, src in extras.items():
            v = p.get(src)
            if v is None or str(v).strip() in ('', ' '):
                continue
            det[nombre] = (_doc_url(v) if nombre == 'doc'
                           else str(v).strip())
        if det:
            p['_detalle'] = det


def capa_features(ine: str | None, *, fetch=requests.get) -> list[dict]:
    """Features de la capa oficial de ordenanzas del municipio.

    Usa la copia cacheada en disco (30 días); si no hay o está
    caducada, la descarga paginada (WFS GeoServer o ArcGIS REST según
    ``cfg['tipo']``). Devuelve ``[]`` si el municipio no tiene capa o
    el servicio falla.
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
    try:
        if cfg.get('tipo') == 'arcgis':
            features = _fetch_arcgis_features(cfg, fetch)
        else:
            features = _fetch_wfs_features(cfg, fetch)
    except Exception:
        return []
    _normalizar_props(features, cfg)
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


def _hits_en_punto(lon: float, lat: float, features: list[dict],
                   ine: str | None = None) -> list[dict]:
    """Features de la capa cuyo polígono contiene el punto."""
    if ine:
        from shapely.geometry import Point
        tree, geoms, feats = _tree(str(ine), features)
        pt = Point(lon, lat)
        return [feats[i] for i in tree.query(pt)
                if geoms[i].contains(pt)]
    return [f for f in features
            if f.get('geometry')
            and _point_in_poly(lon, lat, f['geometry'])]


def _ordenanza_desde_features(lon: float, lat: float,
                              features: list[dict],
                              campo: str,
                              ine: str | None = None) -> list[str]:
    hits = _hits_en_punto(lon, lat, features, ine)
    return sorted({
        str((f.get('properties') or {}).get(campo) or '').strip()
        for f in hits
    } - {''})


def _ordenanzas_proximas(lon: float, lat: float, features: list[dict],
                         campo: str, ine: str | None,
                         radio_m: float = 250.0) -> list[dict]:
    """Ordenanzas de los polígonos más cercanos al punto cuando éste
    cae en un hueco de la capa (parcela sin polígono de ordenanza).
    Son candidatas *por proximidad* — nunca se asignan: pueden ser de
    la parcela colindante y no aplicar. Radio amplio (250 m) porque los
    huecos de la capa suelen ser corredores viarios o manzanas enteras
    — la distancia se muestra al usuario para juzgar la fiabilidad."""
    from shapely.geometry import Point
    pt = Point(lon, lat)
    radio_deg = radio_m / 111320.0
    if ine:
        tree, geoms, feats = _tree(str(ine), features)
        idx = tree.query(pt.buffer(radio_deg))
        cand = [(geoms[i].distance(pt) * 111320.0, feats[i])
                for i in idx]
    else:
        from shapely.geometry import shape
        cand = []
        for f in features:
            if not f.get('geometry'):
                continue
            try:
                cand.append((shape(f['geometry']).distance(pt)
                             * 111320.0, f))
            except Exception:
                continue
    cand.sort(key=lambda x: x[0])
    out: list[dict] = []
    for d, f in cand:
        if d > radio_m:
            break
        code = str((f.get('properties') or {}).get(campo) or '').strip()
        if code and all(c['ordenanza'] != code for c in out):
            out.append({'ordenanza': code, 'distancia_m': round(d)})
        if len(out) >= 6:
            break
    return out


def _fetch_bbox_features(lon: float, lat: float, cfg: dict) -> list[dict]:
    if cfg.get('tipo') == 'arcgis':
        r = requests.get(cfg['url'], params={
            'geometry': f'{lon},{lat}',
            'geometryType': 'esriGeometryPoint',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': '4326', 'outSR': '4326', 'f': 'geojson',
            'outFields': '*', 'where': cfg.get('where') or '1=1',
        }, timeout=15)
        feats = (r.json() or {}).get('features') or []
        _normalizar_props(feats, cfg)
        return feats
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
    """Ordenanza SUC oficial del punto.

    Primero la capa definitiva del PXOM 2025 (ArcGIS Concello, cuando
    existe — Vigo); si no cubre el punto, la capa WFS municipal de la
    aprobación inicial 2021. Devuelve ``{ordenanza, candidatas,
    data_quality, fuente, instrumento}`` o ``None`` si el municipio no
    tiene capa — nunca inventa.
    """
    cfg = ORDSUC_LAYERS.get(str(ine or ''))
    if not cfg or lon is None or lat is None:
        return None
    # Capa definitiva 4ORDSUC del PXOM 2025 (ArcGIS Concello) —
    # prevalece sobre la de aprobación inicial 2021.
    try:
        from src.ambitos_service import (ordenanza_2025_en_punto,
                                         ordenanzas_2025_proximas)
        hit = ordenanza_2025_en_punto(lon, lat, ine)
    except Exception:
        hit = None
    if hit:
        return {
            'ordenanza': None if hit.get('ambigua') else
                         hit.get('ordenanza'),
            'candidatas': hit.get('candidatas') or [],
            'ambigua': bool(hit.get('ambigua')),
            'data_quality': 'official',
            'fuente': hit.get('fuente'),
            'instrumento': ('Ordenanzas SUC — PXOM 2025 aprobación '
                            'definitiva (36057_PXOM_202502_AD01_'
                            '4ORDSUC)'),
            'campo': 'ordenanza',
            'nota': ('Cartografía oficial de la aprobación definitiva '
                     'del PXOM 2025 publicada por el Concello.'),
        }
    feats = capa_features(ine)
    if not feats:
        try:
            feats = _fetch_bbox_features(lon, lat, cfg)
        except Exception:
            return {'data_quality': 'unavailable',
                    'error': 'Servicio municipal no responde',
                    'fuente': cfg['fuente']}
    hits = _hits_en_punto(lon, lat, feats, ine)
    candidatas = sorted({
        str((f.get('properties') or {}).get('ordenanza')
            or (f.get('properties') or {}).get(cfg['campo']) or ''
            ).strip() for f in hits} - {''})
    detalle = None
    for f in hits:
        det = (f.get('properties') or {}).get('_detalle')
        if det:
            detalle = det
            break
    if not candidatas:
        # Colindantes desde la capa definitiva 2025 (más autoritativa);
        # si no está disponible, desde la capa 2021.
        proximas: list[dict] = []
        try:
            proximas = ordenanzas_2025_proximas(lon, lat, ine)
        except Exception:
            proximas = []
        if not proximas:
            proximas = _ordenanzas_proximas(
                lon, lat, feats, cfg['campo'], ine)
        return {'data_quality': 'unavailable',
                'error': 'Punto fuera de la capa de ordenanzas SUC',
                'fuente': cfg['fuente'],
                'instrumento': cfg['instrumento'],
                'candidatas': [],
                'candidatas_proximas': proximas}
    out = {
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
    if detalle:
        out['detalle'] = detalle
    if cfg.get('prefijo_ordenanza'):
        out['prefijo_ordenanza'] = cfg['prefijo_ordenanza']
    return out
