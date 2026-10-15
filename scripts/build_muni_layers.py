"""Genera las capas precalculadas de ``datos/mapas/`` para municipios
cuya fuente oficial es un ArcGIS REST municipal (no SIOTUGA).

SIOTUGA sufre caídas prolongadas y no vectoriza todos los planes;
varios concellos publican cartografía oficial equivalente en sus
propios servicios. Este script descarga esas capas y las escribe en el
mismo formato que consume la app:

- ``{ine}_clasif_puntos.geojson`` — props crudas para consultas
  punto-en-polígono (``vector_downloader._point_tree``).
- ``{ine}_clasificacion.geojson`` — props de mapa
  (``/official/siotuga-clasificacion``).
- ``{ine}_ordenanzas.geojson`` — contornos de ordenanzas
  (``/official/ordenanzas-vector``), desde la caché de ``muni_wfs``.

Uso:
    venv\\Scripts\\python.exe scripts\\build_muni_layers.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from shapely.geometry import mapping, shape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.siotuga.vector_downloader import CODE_LABELS
from src.muni_wfs import capa_features

OUT = Path('datos/mapas')

# Misma tolerancia que scripts/generate_map_layers.py (~0,9 m) —
# sobra para pintar el mapa y para punto-en-polígono urbano.
TOLERANCE_DEG = 0.000008
COORD_DIGITS = 6


def _round_coords(coords):
    if isinstance(coords[0], (int, float)):
        return [round(c, COORD_DIGITS) for c in coords]
    return [_round_coords(c) for c in coords]


def _slim_geometry(geom: dict) -> dict | None:
    if not geom:
        return None
    shp = shape(geom).simplify(TOLERANCE_DEG, preserve_topology=True)
    if shp.is_empty:
        return None
    g = mapping(shp)
    return {'type': g['type'],
            'coordinates': _round_coords(list(g['coordinates']))}

# Configuración por INE: lista de capas ArcGIS de clasificación del
# suelo y cómo mapear sus campos al esquema interno. Las capas se
# insertan en orden — la primera que contiene el punto gana cuando hay
# solape (granularidad fina primero, clase gruesa de relleno después).
CLASIF_SOURCES = {
    # A Coruña: "CLASIFICACIÓN DEL SUELO" del Mapa de Gestión PGM 2013
    # (349 polígonos, clase + categoría + etiqueta de recinto).
    '15030': {
        'fuente': ('IDE Concello da Coruña — PGM 2013 Mapa de Gestión '
                   '(CLASIFICACIÓN DEL SUELO)'),
        'capas': [{
            'url': ('https://ide.coruna.gal/server/rest/services/'
                    'Publica/PGM13_FICHAS_INFORMACION/MapServer/1/query'),
            'where': '1=1',
            'cla': 'CLASE_S_C',
            'cat': 'CAT_S_C',
            'denom': 'CAT_S_L',
            'id_recinto': 'ETIQUETA',
            'area': 'SUPERFICIE',
            'estado': 'ESTADO',
        }],
    },
    # Santiago: Planeamento_urbanistico — capa 10 (categorías finas:
    # SUNC, SUC, SUBLED…) delante de la 9 (clases gruesas: SU, SR…).
    '15078': {
        'fuente': ('Xeoportal Concello de Santiago — Planeamento '
                   'urbanístico (clasificación e categorías do solo)'),
        'capas': [
            {
                'url': ('https://xeoportal.santiagodecompostela.gal/'
                        'ags/rest/services/Planeamento_urbanistico/'
                        'MapServer/10/query'),
                'where': '1=1',
                'cat': 'CLAVE',
                'denom': 'DETERMINAC',
                'area': 'SHAPE.AREA',
                # categoría → clase madre para rellenar cla_*
                'cat_a_cla': {
                    'SUNC': 'SU', 'SUC': 'SU',
                    'SUBLED': 'SUBLE', 'SUBLEND': 'SUBLE',
                    'SR-PO': 'SR', 'SR-EP': 'SR', 'CSNR': 'SNR',
                },
            },
            {
                'url': ('https://xeoportal.santiagodecompostela.gal/'
                        'ags/rest/services/Planeamento_urbanistico/'
                        'MapServer/9/query'),
                'where': '1=1',
                'cla': 'CLAVE',
                'denom': 'ENTIDAD',
                'area': 'SHAPE.AREA',
            },
        ],
    },
}


def _fetch_arcgis(url: str, where: str = '1=1') -> list[dict]:
    """Descarga paginada de una capa ArcGIS REST como features GeoJSON."""
    feats: list[dict] = []
    offset = 0
    while True:
        r = requests.get(url, params={
            'where': where, 'outFields': '*', 'f': 'geojson',
            'outSR': '4326', 'resultRecordCount': '2000',
            'resultOffset': str(offset),
        }, timeout=60)
        page = (r.json() or {}).get('features') or []
        feats.extend(page)
        if len(page) < 2000:
            break
        offset += len(page)
        if offset > 200000:
            break
    return feats


def _puntos_props(attrs: dict, m: dict, fuente: str) -> dict:
    """Mapea los atributos ArcGIS al esquema que consume
    ``props_to_result`` (cat_*/cla_*/denom/uso/id_recinto…)."""
    cla = (attrs.get(m['cla']) if m.get('cla') else None) or ''
    cat = (attrs.get(m['cat']) if m.get('cat') else None) or ''
    cla, cat = str(cla).strip(), str(cat).strip()
    if not cla and cat and m.get('cat_a_cla'):
        cla = m['cat_a_cla'].get(cat.upper(), '')
    area = attrs.get(m['area']) if m.get('area') else None
    props = {
        'cla_ley': cla or None, 'cla_homo': cla or None,
        'cla_plan': cla or None,
        'cat_ley': cat.upper() or None, 'cat_homo': cat.upper() or None,
        'cat_plan': cat.upper() or None,
        'denom': attrs.get(m['denom']) if m.get('denom') else None,
        'uso': attrs.get(m['uso']) if m.get('uso') else None,
        'id_recinto': (attrs.get(m['id_recinto'])
                       if m.get('id_recinto') else None),
        'geom_area': area, 'sup_ficha': area,
        'estado': attrs.get(m['estado']) if m.get('estado') else None,
        'fuente': fuente,
    }
    return {k: v for k, v in props.items() if v is not None}


def _map_props(p: dict) -> dict:
    """Props reducidas para el GeoJSON del mapa — el mismo subconjunto
    que devuelve ``obtener_capa_geojson`` para capas SIOTUGA."""
    cla = p.get('cla_ley') or p.get('cat_ley') or ''
    return {
        'clase_ley': p.get('cla_ley'),
        'clasificacion': CODE_LABELS.get(
            p.get('cla_ley') or p.get('cat_ley') or '', 'Sin clasificar'),
        'cat_plan': p.get('cat_plan'),
        'uso': p.get('uso'),
        'denom': p.get('denom'),
        'id_recinto': p.get('id_recinto'),
        'sup_ficha': p.get('sup_ficha'),
        'edif_ficha': p.get('edif_ficha'),
        'fuente': p.get('fuente'),
        '_cla_code': cla or None,
    }


def _write(name: str, fc: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(fc, ensure_ascii=False, separators=(',', ':'))
    (OUT / name).write_text(raw, encoding='utf-8')
    print(f'{name}: {len(fc["features"])} features, '
          f'{len(raw) / 1e6:.1f} MB')


def main() -> int:
    for ine, cfg in CLASIF_SOURCES.items():
        fuente = cfg['fuente']
        puntos_feats: list[dict] = []
        for capa in cfg['capas']:
            raw = _fetch_arcgis(capa['url'], capa.get('where') or '1=1')
            for f in raw:
                geom = _slim_geometry(f.get('geometry'))
                if not geom:
                    continue
                props = _puntos_props(f.get('properties') or {},
                                      capa, fuente)
                puntos_feats.append({'type': 'Feature',
                                     'geometry': geom,
                                     'properties': props})
            print(f'  {ine}: {capa["url"].split("/")[-2]}/'
                  f'{capa["url"].split("/")[-1].replace("query", "")} '
                  f'→ {len(raw)} features')
        if not puntos_feats:
            print(f'{ine}: SIN FEATURES — se omite')
            continue
        _write(f'{ine}_clasif_puntos.geojson', {
            'type': 'FeatureCollection', 'features': puntos_feats,
            'metadata': {'source': fuente, 'data_quality': 'official',
                         'ine': ine},
        })
        _write(f'{ine}_clasificacion.geojson', {
            'type': 'FeatureCollection',
            'features': [
                {'type': 'Feature', 'geometry': f['geometry'],
                 'properties': _map_props(f['properties'])}
                for f in puntos_feats],
            'metadata': {'source': fuente, 'data_quality': 'official',
                         'ine': ine,
                         'feature_count': len(puntos_feats)},
        })
        # Capa de ordenanzas (contornos para el mapa) desde la caché
        # oficial de muni_wfs — props.ord es lo que pinta el visor.
        ords = capa_features(ine)
        if ords:
            ord_feats = []
            for f in ords:
                geom = _slim_geometry(f.get('geometry'))
                if geom:
                    ord_feats.append({
                        'type': 'Feature', 'geometry': geom,
                        'properties': {
                            'ord': (f.get('properties') or {})
                                   .get('ordenanza')}})
            _write(f'{ine}_ordenanzas.geojson', {
                'type': 'FeatureCollection', 'features': ord_feats,
                'metadata': {'source': 'Concello — ordenanzas',
                             'data_quality': 'official', 'ine': ine},
            })
        else:
            print(f'  {ine}: sin capa de ordenanzas cacheada — '
                  f'ejecuta antes capa_features("{ine}")')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
