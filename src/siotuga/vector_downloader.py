"""Descarga y consulta local de la clasificación urbanística SIOTUGA.

SIOTUGA expone la capa ``_{INE}_{TIPO}_{FECHA}_AD_3CLAS_{IDDOC}`` de cada plan
vigente mediante WFS 1.1.0 (MapServer). Este módulo:

1. Descarga la capa completa del municipio paginando con
   ``maxfeatures`` + ``startindex`` y la guarda como GeoJSON EPSG:4326 en
   ``datos/cache/siotuga/`` (TTL 30 días).
2. Resuelve consultas punto-en-polígono sobre la copia local; si no hay copia,
   recurre a una consulta WFS acotada al punto (comportamiento anterior).
3. Sirve recortes GeoJSON al visor para la capa
   "Clasificación SIOTUGA (oficial)".

Trazabilidad: cada resultado lleva ``fuente`` y, cuando procede de la copia
local, ``vectorial_local: true``.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Callable
from urllib.parse import urlencode

from shapely.geometry import Point, shape
from shapely.prepared import prep

from src.cache import disk_get, disk_set, http_get

SIOTUGA_WFS = "https://siotuga.xunta.gal/siotuga/ws"
LAYER_TTL_S = 30 * 24 * 3600  # el plan vigente cambia muy poco
PAGE_SIZE = 2000
MAX_PAGES = 15  # hasta 30 000 polígonos por municipio

GML_NS = "http://www.opengis.net/gml"

# Códigos de clasificación/categoría → etiqueta legible
CODE_LABELS = {
    'SUC': 'Suelo Urbano Consolidado',
    'SUNC': 'Suelo Urbano No Consolidado',
    'SNU': 'Suelo No Urbanizable',
    'SUN': 'Suelo Urbanizable',
    'SUR': 'Suelo Urbano Residencial',
    'SUT': 'Suelo Urbano Terciario',
    'SUI': 'Suelo Urbano Industrial',
    'SUB': 'Suelo Urbanizable',
    'SU': 'Suelo Urbano',
    'SNUC': 'Suelo No Urbanizable Común',
    'SNUP': 'Suelo No Urbanizable Protegido',
    'SNR': 'Suelo de Núcleo Rural',
    'SR': 'Suelo Rústico',
    'SRP': 'Suelo Rústico Protegido',
    'SRPA': 'Suelo Rústico de Protección Agraria',
    'SRPP': 'Suelo Rústico de Protección Paisajística',
    'SRPEN': 'Suelo Rústico de Protección de Espacios Naturales',
    'SRPAU': 'Suelo Rústico de Protección de Aprovechamientos Urbanos',
    'SRPF': 'Suelo Rústico de Protección Forestal',
    'SRPPX': 'Suelo Rústico de Protección de Paisaje y Patrimonio',
    'SRPC': 'Suelo Rústico de Protección de Cauces',
}


def _local(tag: str) -> str:
    return tag.split('}')[-1]


def _parse_ring_text(text: str) -> list[list[float]]:
    """Parsea un anillo GML (posList o coordinates) a [[x, y], ...]."""
    text = (text or '').strip()
    if not text:
        return []
    out: list[list[float]] = []
    if ',' in text:
        for c in text.split():
            parts = c.split(',')
            if len(parts) >= 2:
                try:
                    out.append([float(parts[0]), float(parts[1])])
                except ValueError:
                    continue
    else:
        vals = text.split()
        for i in range(0, len(vals) - 1, 2):
            try:
                out.append([float(vals[i]), float(vals[i + 1])])
            except (ValueError, IndexError):
                continue
    return out


def _gml_polygon_to_geojson(poly: ET.Element,
                            swap_axes: bool = False) -> list | None:
    """Convierte un gml:Polygon a coordenadas GeoJSON [exterior, *huecos].

    ``swap_axes`` invierte cada par (GML en EPSG:4326 usa orden lat,lon;
    GeoJSON necesita lon,lat)."""
    rings: list[list[list[float]]] = []
    exterior: list[list[float]] = []
    holes: list[list[list[float]]] = []
    for child in poly:
        role = _local(child.tag)
        for lr in child.iter():
            if _local(lr.tag) != 'LinearRing':
                continue
            ring = None
            for sub in lr:
                if _local(sub.tag) in ('posList', 'coordinates', 'pos'):
                    ring = sub
                    break
            if ring is None:
                continue
            coords = _parse_ring_text(ring.text or '')
            if swap_axes:
                coords = [[b, a] for a, b in coords]
            if len(coords) < 3:
                continue
            if role in ('exterior', 'outerBoundaryIs'):
                exterior = coords
            elif role in ('interior', 'innerBoundaryIs'):
                holes.append(coords)
            break
    if len(exterior) < 3:
        return None
    rings.append(exterior)
    rings.extend(holes)
    return rings


def _feature_is_latlon(feat: ET.Element) -> bool:
    """Detecta si las coordenadas del feature son lat,lon.

    MapServer WFS 1.1.0 con ``srsname=EPSG:4326`` emite ``posList`` en
    orden lat,lon (EPSG axis order); GeoJSON necesita lon,lat. El
    ``srsName`` puede estar en el Polygon, el MultiPolygon o el
    Envelope del ``boundedBy``; si ninguno lo indica, se aplica la
    heurística de rango de Galicia (lat 41-44, lon -10 a -6).
    """
    for elem in feat.iter():
        srs = elem.get('srsName') or ''
        if srs.endswith(('4326', '4258')):
            return True
        if '25829' in srs or '25830' in srs or '32629' in srs:
            return False
    for elem in feat.iter():
        if _local(elem.tag) in ('posList', 'coordinates'):
            vals = (elem.text or '').split()
            if len(vals) >= 2:
                try:
                    if ',' in (elem.text or ''):
                        a, b = vals[0].split(',')[:2]
                    else:
                        a, b = vals[0], vals[1]
                    x, y = float(a), float(b)
                    return 35.0 <= x <= 45.0 and -11.0 <= y <= -5.0
                except (ValueError, IndexError):
                    continue
    return False


def _feature_to_geojson(feat: ET.Element, layer: str) -> dict | None:
    """Extrae {type, geometry, properties} de un featureMember GML.

    Invierte lat,lon → lon,lat cuando el feature está en EPSG:4326/4258
    (``srsName`` en cualquier nivel, o heurística de rango Galicia).
    """
    props: dict[str, Any] = {}
    geometry: dict | None = None
    polygons: list[list] = []
    swap = _feature_is_latlon(feat)
    for child in feat:
        tag = _local(child.tag)
        if tag in ('msGeometry', 'the_geom', 'geometry'):
            for poly in child.iter():
                if _local(poly.tag) == 'Polygon':
                    rings = _gml_polygon_to_geojson(poly, swap_axes=swap)
                    if rings:
                        polygons.append(rings)
        elif tag == 'boundedBy':
            continue
        else:
            val = (child.text or '').strip()
            if val:
                props[tag] = val
    if len(polygons) == 1:
        geometry = {'type': 'Polygon', 'coordinates': polygons[0]}
    elif len(polygons) > 1:
        geometry = {'type': 'MultiPolygon', 'coordinates': polygons}
    if geometry is None:
        return None
    return {'type': 'Feature', 'geometry': geometry, 'properties': props}


def _iter_features(root: ET.Element, layer: str):
    for feat in root.iter():
        if _local(feat.tag) == layer:
            yield feat


def _wfs_get_page(ine_code: str, layer: str, startindex: int,
                  fetch: Callable[[str], bytes] | None = None) -> ET.Element:
    fetch = fetch or (lambda u: http_get(u, timeout=60, retries=2))
    params = {
        'codine': ine_code, 'SERVICE': 'WFS', 'REQUEST': 'GetFeature',
        'version': '1.1.0', 'typename': layer,
        'srsname': 'EPSG:4326', 'maxfeatures': PAGE_SIZE,
        'startindex': startindex,
    }
    raw = fetch(f'{SIOTUGA_WFS}?{urlencode(params)}')
    return ET.fromstring(raw)


def _cache_key(ine_code: str, layer: str) -> str:
    return f'{ine_code}_{layer}'


def descargar_clasificacion_municipio(
    ine_code: str,
    layer_name: str,
    force: bool = False,
    fetch: Callable[[str], bytes] | None = None,
) -> dict:
    """Descarga la capa de clasificación completa del municipio.

    Devuelve un GeoJSON FeatureCollection con miembro ``metadata``
    (fuente, capa, municipio, fecha de descarga). Usa la copia en disco
    cuando está vigente; ``force=True`` fuerza nueva descarga.

    Ejemplo::

        fc = descargar_clasificacion_municipio('36057', '_36057_PXOM_202505_AD_3CLAS_28719')
        len(fc['features'])  # polígonos reales del planeamiento de Vigo
    """
    key = _cache_key(ine_code, layer_name)
    if not force:
        cached = disk_get('siotuga', key, LAYER_TTL_S)
        if cached and cached.get('features'):
            return cached

    features: list[dict] = []
    fetched_pages = 0
    for page in range(MAX_PAGES):
        try:
            root = _wfs_get_page(ine_code, layer_name, page * PAGE_SIZE, fetch)
        except Exception as e:
            if page == 0:
                return {
                    'type': 'FeatureCollection', 'features': [],
                    'metadata': {
                        'error': str(e), 'source': 'SIOTUGA WFS',
                        'data_quality': 'unavailable',
                    },
                }
            break
        page_feats = [
            _feature_to_geojson(f, layer_name) for f in _iter_features(root, layer_name)
        ]
        page_feats = [f for f in page_feats if f]
        features.extend(page_feats)
        fetched_pages += 1
        if len(page_feats) < PAGE_SIZE:
            break

    import datetime as _dt
    fc = {
        'type': 'FeatureCollection',
        'features': features,
        'metadata': {
            'source': 'SIOTUGA WFS',
            'data_quality': 'official',
            'layer': layer_name,
            'ine': ine_code,
            'feature_count': len(features),
            'downloaded_at': _dt.datetime.now(_dt.timezone.utc).isoformat(),
            'srs': 'EPSG:4326',
        },
    }
    if features:
        disk_set('siotuga', key, fc)
    return fc


def _load_local_layer(ine_code: str, layer: str) -> dict | None:
    return disk_get('siotuga', _cache_key(ine_code, layer), LAYER_TTL_S)


def _score_props(props: dict) -> int:
    s = 0
    if props.get('edif_ficha'):
        s += 3
    if props.get('denom'):
        s += 2
    if props.get('uso'):
        s += 1
    return s


def _try_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def props_to_result(props: dict) -> dict:
    """Mapea los atributos brutos del WFS al formato interno."""
    result: dict = {}
    for field, val in props.items():
        if field == 'cat_ley':
            result['clasificacion_ley'] = val
        elif field == 'cat_homo':
            result['clasificacion_homo'] = val
        elif field == 'cat_plan':
            result['clasificacion_plan'] = val
        elif field == 'cla_ley':
            result['clase_ley'] = val
        elif field == 'cla_homo':
            result['clase_homo'] = val
        elif field == 'uso':
            result['uso_zona'] = val
        elif field == 'denom':
            result['denominacion_zona'] = val
        elif field == 'obsv':
            result['observaciones_zona'] = val
        elif field == 'id_recinto':
            result['id_recinto'] = val
        elif field == 'geom_area':
            result['area_zona_m2'] = _try_float(val)
        elif field == 'sup_ficha':
            result['sup_ficha_m2'] = _try_float(val)
        elif field == 'edif_ficha':
            result['edificabilidad_ficha'] = _try_float(val)
        elif field == 'estado':
            result['estado_zona'] = val
        elif field == 'cat_wiug':
            result['categoria_wiug'] = val
    for key in ('clasificacion_ley', 'clasificacion_homo', 'clasificacion_plan',
                'clase_ley', 'clase_homo'):
        if key in result and result[key] in CODE_LABELS:
            result[f'{key}_label'] = CODE_LABELS[result[key]]
    return result


def _pick_best(candidates: list[dict]) -> dict | None:
    """Elige el polígono más específico entre los que contienen el punto."""
    if not candidates:
        return None
    candidates.sort(key=lambda c: _score_props(c.get('properties') or {}),
                    reverse=True)
    return candidates[0]


def _point_in_features(lon: float, lat: float,
                       features: list[dict]) -> list[dict]:
    """Filtra las features cuyo polígono contiene el punto (EPSG:4326)."""
    pt = Point(lon, lat)
    hits = []
    for f in features:
        geom = f.get('geometry')
        if not geom:
            continue
        try:
            if prep(shape(geom)).contains(pt):
                hits.append(f)
        except Exception:
            continue
    return hits


def _fetch_point_live(lon: float, lat: float, ine_code: str, layer: str,
                      fetch: Callable[[str], bytes] | None = None) -> dict:
    """Consulta WFS acotada al punto (fallback sin copia local).

    La capa nativa es EPSG:25829; se pide el bbox en UTM 29N y el resultado
    en EPSG:4326 cuando el servidor lo permite.
    """
    fetch = fetch or (lambda u: http_get(u, timeout=15, retries=2))
    x, y = lonlat_to_utm29(lon, lat)
    delta = 200
    url = (
        f'{SIOTUGA_WFS}?codine={ine_code}&SERVICE=WFS&REQUEST=GetFeature'
        f'&version=1.1.0&typename={layer}&maxfeatures=10'
        f'&srsname=EPSG:25829'
        f'&bbox={x-delta},{y-delta},{x+delta},{y+delta},EPSG:25829'
    )
    try:
        raw = fetch(url)
        root = ET.fromstring(raw)
    except Exception:
        return {}
    # El resultado llega en EPSG:25829; point-in-polygon en UTM
    candidates = []
    for feat in _iter_features(root, layer):
        gj = _feature_to_geojson(feat, layer)
        if not gj:
            continue
        props = gj['properties']
        geom = gj['geometry']
        try:
            if prep(shape(geom)).contains(Point(x, y)):
                candidates.append(gj)
        except Exception:
            continue
    best = _pick_best(candidates)
    if not best:
        return {}
    result = props_to_result(best['properties'])
    result['fuente'] = 'SIOTUGA WFS (consulta puntual)'
    result['vectorial_local'] = False
    return result


def consultar_clasificacion_punto(
    lon: float,
    lat: float,
    ine_code: str,
    layer_name: str | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> dict:
    """Clasificación del punto usando la copia vectorial local si existe.

    Devuelve ``{clase, categoria, clasificacion_ley, ...}`` en el mismo
    formato que la consulta puntual WFS, añadiendo ``fuente`` y
    ``vectorial_local``. Si no hay copia local hace la consulta WFS
    acotada de siempre; si tampoco hay datos, ``{}``.
    """
    if layer_name:
        fc = _load_local_layer(ine_code, layer_name)
        if fc and fc.get('features'):
            best = _pick_best(_point_in_features(lon, lat, fc['features']))
            if best:
                result = props_to_result(best['properties'])
                result['fuente'] = 'SIOTUGA WFS (vectorial local)'
                result['vectorial_local'] = True
                return result
            # Punto fuera de los polígonos descargados: puede ser suelo
            # no clasificado o borde de municipio; seguimos con consulta viva.
    if not layer_name:
        return {}
    return _fetch_point_live(lon, lat, ine_code, layer_name, fetch)


def obtener_capa_geojson(
    ine_code: str,
    layer_name: str,
    bbox: tuple[float, float, float, float] | None = None,
    max_features: int = 6000,
    fetch: Callable[[str], bytes] | None = None,
) -> dict:
    """Devuelve la capa de clasificación como GeoJSON para el visor.

    Descarga la capa completa si no está cacheada y, si se pasa ``bbox``
    ``(minx, miny, maxx, maxy)``, recorta a los polígonos que lo
    intersectan para limitar el payload.
    """
    fc = descargar_clasificacion_municipio(ine_code, layer_name, fetch=fetch)
    feats = fc.get('features') or []
    if bbox:
        from shapely.geometry import box
        bb = box(*bbox)
        feats = [f for f in feats
                 if f.get('geometry') and _safe_intersects(f, bb)]
    if len(feats) > max_features:
        feats = feats[:max_features]
    # Simplificar propiedades al subconjunto útil para el mapa
    slim = []
    for f in feats:
        p = f.get('properties') or {}
        slim.append({
            'type': 'Feature',
            'geometry': f.get('geometry'),
            'properties': {
                'clase_ley': p.get('cla_ley') or p.get('cat_ley'),
                'clasificacion': CODE_LABELS.get(
                    p.get('cla_ley') or p.get('cat_ley') or '', 'Sin clasificar'),
                'cat_plan': p.get('cat_plan'),
                'uso': p.get('uso'),
                'denom': p.get('denom'),
                'id_recinto': p.get('id_recinto'),
                'sup_ficha': p.get('sup_ficha'),
                'edif_ficha': p.get('edif_ficha'),
                'fuente': 'SIOTUGA WFS',
            },
        })
    out = {
        'type': 'FeatureCollection',
        'features': slim,
        'metadata': fc.get('metadata') or {},
    }
    return out


def _safe_intersects(feature: dict, geom) -> bool:
    try:
        return shape(feature['geometry']).intersects(geom)
    except Exception:
        return False


def lonlat_to_utm29(lon: float, lat: float) -> tuple[float, float]:
    """EPSG:4326 → EPSG:25829 (UTM 29N)."""
    try:
        from pyproj import Transformer
        t = Transformer.from_crs('EPSG:4326', 'EPSG:25829', always_xy=True)
        return t.transform(lon, lat)
    except Exception:
        pass
    lon0 = math.radians(-9.0)
    k0 = 0.9996
    a = 6378137.0
    e2 = 0.00669437999014
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
    T = math.tan(lat_rad) ** 2
    C = e2 * math.cos(lat_rad) ** 2 / (1 - e2)
    A = math.cos(lat_rad) * (lon_rad - lon0)
    M = a * ((1 - e2/4 - 3*e2**2/64 - 5*e2**3/256) * lat_rad
             - (3*e2/8 + 3*e2**2/32 + 45*e2**3/1024) * math.sin(2*lat_rad)
             + (15*e2**2/256 + 45*e2**3/1024) * math.sin(4*lat_rad)
             - (35*e2**3/3072) * math.sin(6*lat_rad))
    x = k0 * N * (A + (1-T+C)*A**3/6 + (5-18*T+T**2+72*C-58*e2)*A**5/120) + 500000
    y = k0 * (M + N * math.tan(lat_rad) * (A**2/2 + (5-T+9*C+4*C**2)*A**4/24
             + (61-58*T+T**2+600*C-330*e2)*A**6/720))
    if lat < 0:
        y += 10000000
    return x, y
