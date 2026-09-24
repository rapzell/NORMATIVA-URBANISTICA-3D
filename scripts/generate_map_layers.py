"""Genera GeoJSONs ligeros precomputados para el mapa de la beta.

Los endpoints ``/official/siotuga-clasificacion`` y
``/official/ordenanzas-vector`` devuelven capas de varios MB que en un
contenedor de 512 MB (Render free) matan el proceso al parsear +
reserializar. Este script toma la salida real del servidor local,
conserva solo las props que el visor usa, simplifica la geometría a
precisión submétrica y guarda el resultado en ``datos/mapas/`` para
que el endpoint lo sirva con FileResponse (sin parse en RAM).

Uso (con el servidor local en :8002 y las cachés ya generadas):
    venv\\Scripts\\python.exe scripts\\generate_map_layers.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape

API = 'http://127.0.0.1:8002'
OUT = Path('datos/mapas')

# Props que el visor lee para pintar y para el panel al hacer clic.
CLASIF_PROPS = {
    'clase_ley', 'clasificacion', 'cat_plan', 'denom', 'uso',
    'edif_ficha', 'sup_ficha', 'id_recinto', 'fuente',
}
ORDS_PROPS = {'ord'}

# Props crudas que necesitan las consultas punto-en-polígono
# (props_to_result + detección de ámbitos por obsv/denom).
PUNTOS_PROPS = {
    'cat_ley', 'cat_homo', 'cat_plan', 'cla_ley', 'cla_homo', 'uso',
    'denom', 'obsv', 'id_recinto', 'geom_area', 'estado', 'cat_wiug',
    'sup_ficha', 'edif_ficha',
}

TOLERANCE_DEG = 0.000008  # ~0.9 m a la latitud de Galicia
COORD_DIGITS = 6          # ~0.11 m — sobra para pintar en el mapa


def _round_coords(coords):
    if isinstance(coords[0], (int, float)):
        return [round(c, COORD_DIGITS) for c in coords]
    return [_round_coords(c) for c in coords]


def _slim_feature(feat, keep):
    geom = feat.get('geometry')
    if not geom:
        return None
    shp = shape(geom).simplify(TOLERANCE_DEG, preserve_topology=True)
    if shp.is_empty:
        return None
    props = {k: v for k, v in (feat.get('properties') or {}).items()
             if k in keep and v is not None}
    return {'type': 'Feature',
            'geometry': {**mapping(shp), 'coordinates': _round_coords(
                list(mapping(shp)['coordinates']))},
            'properties': props}


def _fetch(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=300) as r:
        return json.load(r)


def _write(name: str, fc: dict, keep: set, extra_meta: dict | None = None):
    feats = [s for s in (_slim_feature(f, keep)
                       for f in fc.get('features') or []) if s]
    out = {'type': 'FeatureCollection', 'features': feats}
    meta = dict(fc.get('metadata') or {})
    meta.update(extra_meta or {})
    meta['source_slim'] = 'precomputed'
    out['metadata'] = meta
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    raw = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    path.write_text(raw, encoding='utf-8')
    print(f'{name}: {len(feats)} features, {len(raw)/1e6:.1f} MB')


def _write_puntos(ine: str):
    """Capa ligera con props crudas para ``vector_downloader._point_tree``
    — evita parsear la caché completa (~14 MB) en cada consulta."""
    import glob as _glob
    best = None
    for path in _glob.glob(f'datos/cache/siotuga/{ine}_*.json'):
        try:
            d = json.loads(Path(path).read_text(encoding='utf-8'))
        except Exception:
            continue
        fc = d.get('data') or d
        n = len(fc.get('features') or [])
        if n > len((best or {}).get('features') or []):
            best = fc
    if not best:
        print(f'{ine}: sin caché siotuga — se omite clasif_puntos')
        return
    _write(f'{ine}_clasif_puntos.geojson', best, PUNTOS_PROPS,
           {'source': 'SIOTUGA WFS — props crudas para consulta puntual'})


def main() -> int:
    fc = _fetch('/official/siotuga-clasificacion?municipio=Vigo')
    _write('36057_clasificacion.geojson', fc, CLASIF_PROPS)

    fc = _fetch('/official/ordenanzas-vector?ine=36057')
    _write('36057_ordenanzas.geojson', fc, ORDS_PROPS,
           {'source': 'Concello de Vigo — ordenanzas SUC'})

    _write_puntos('36057')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
