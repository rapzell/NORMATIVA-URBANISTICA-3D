"""Huellas y alturas reales de edificios (Overture Maps + PNOA LiDAR).

Sustituye la altura estimada de OSM ("plantas × 3 m") por datos
verificables:

- **Huellas**: Overture Maps vía DuckDB (Parquet remoto, opcional).
- **Alturas**: PNOA LiDAR. El IGN/CNIG distribuye nubes de puntos LAZ por
  hoja MTN; las descargadas se guardan en ``datos/cache/lidar/`` y este
  módulo extrae la altura de cada huella con el método de percentiles
  (P90 sobre la huella, recorte a 60 m) menos la cota del terreno
  (mediana de puntos clasificados ``ground`` o MDT WCS 5 m como apoyo).
- **Apoyo oficial**: edificios Catastro INSPIRE BU (uso, fecha,
  plantas cuando el servicio las publica).

Principio de la guía: si LiDAR no está disponible se devuelve
``unavailable``; nunca se cae en silencio a la estimación OSM.

Dependencias opcionales (si faltan, el resultado es ``unavailable``):
``duckdb`` (Overture), ``laspy`` + ``lazrs`` (LAZ), ``rasterio`` (WCS/GeoTIFF).

Ejemplo::

    from src.building_data import height_extractor as he
    dp = he.obtener_altura_lidar(huella_geojson, lon=-8.713, lat=42.238)
    dp.to_dict()  # {'value': 14.2, 'data_quality': 'measured', ...}
"""
from __future__ import annotations

import glob
import os
from typing import Any

from src.cache import disk_get, disk_set, http_get
from src.data_quality import (DataPoint, DataQuality, estimated, measured,
                              unavailable)

LIDAR_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "datos", "cache", "lidar",
)
OVERTURE_RELEASE = "2025-08-20.0"
OVERTURE_PARQUET = (
    f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/"
    "theme=buildings/type=building/*"
)
MDT_WCS_URL = "https://servicios.idee.es/wcs-inspire/mdt"
MDT_COVERAGE = "Elevacion4258_5"
MAX_HEIGHT_M = 60.0
PCT = 90  # percentil recomendado por la guía (P90/P95)


def _percentile(sorted_vals: list[float], pct: float) -> float | None:
    """Percentil con interpolación lineal sobre lista ordenada."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def obtener_huellas_municipio(codigo_ine: str,
                              bbox: tuple[float, float, float, float] | None = None,
                              limite: int = 20000) -> dict:
    """Huellas de edificios del municipio desde Overture Maps (DuckDB).

    ``bbox`` es ``(minx, miny, maxx, maxy)`` en EPSG:4326; si se omite se
    usa el centro municipal conocido. Devuelve
    ``{available, features, source}`` — nunca datos inventados.
    """
    if bbox is None:
        try:
            from src.subzones_service import MUNICIPIO_CENTERS
        except Exception:
            return {'available': False, 'features': [],
                    'error': 'Sin bbox ni centros municipales'}
        from src.zoning_service import _norm_text as _nt
        key = _nt(codigo_ine)
        cfg = MUNICIPIO_CENTERS.get(key)
        if not cfg:
            return {'available': False, 'features': [],
                    'error': f'Sin bbox para {codigo_ine}'}
        cx, cy = cfg['center']
        d = cfg['delta']
        bbox = (cx - d, cy - d, cx + d, cy + d)
    cache_key = f'ov_{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}'
    cached = disk_get('overture', cache_key, 30 * 24 * 3600)
    if cached is not None:
        return cached
    try:
        import duckdb
    except ImportError:
        return {'available': False, 'features': [],
                'error': 'duckdb no instalado',
                'source': 'Overture Maps'}
    try:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("INSTALL spatial; LOAD spatial;")
        con.execute("SET s3_region='us-west-2';")
        rows = con.execute(
            """
            SELECT id, height, num_floors, class,
                   ST_AsGeoJSON(geometry) AS geom
            FROM read_parquet(?, filename=true, hive_partitioning=1)
            WHERE bbox.xmin < ? AND bbox.xmax > ?
              AND bbox.ymin < ? AND bbox.ymax > ?
            LIMIT ?
            """,
            [OVERTURE_PARQUET, bbox[2], bbox[0], bbox[3], bbox[1], limite],
        ).fetchall()
    except Exception as e:
        return {'available': False, 'features': [],
                'error': f'Overture: {e}', 'source': 'Overture Maps'}
    import json as _j
    features = []
    for oid, h, floors, cls, geom in rows:
        try:
            g = _j.loads(geom)
        except Exception:
            continue
        features.append({
            'type': 'Feature', 'geometry': g,
            'properties': {
                'overture_id': oid, 'height': h, 'num_floors': floors,
                'class': cls, 'source': 'Overture Maps',
            },
        })
    result = {
        'available': bool(features),
        'features': features,
        'source': f'Overture Maps release {OVERTURE_RELEASE}',
    }
    if features:
        disk_set('overture', cache_key, result)
    return result


def _laz_files_covering(lon: float, lat: float) -> list[str]:
    """LAZ/LAS en caché cuyas cotas cubren el punto (auto-detecta CRS)."""
    try:
        import laspy
    except ImportError:
        return []
    files = sorted(glob.glob(os.path.join(LIDAR_CACHE_DIR, '*.la[sz]')))
    covering = []
    for path in files:
        try:
            with laspy.open(path) as rdr:
                hdr = rdr.header
                crs = None
                try:
                    crs = hdr.parse_crs()
                except Exception:
                    pass
                x, y = lon, lat
                if crs is not None and '25829' in str(crs.to_epsg() or ''):
                    from src.siotuga.vector_downloader import lonlat_to_utm29
                    x, y = lonlat_to_utm29(lon, lat)
                elif crs is not None and str(crs.to_epsg() or '') not in ('4326', '4258'):
                    from pyproj import Transformer
                    t = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
                    x, y = t.transform(lon, lat)
                if (hdr.mins[0] - 1 <= x <= hdr.maxs[0] + 1 and
                        hdr.mins[1] - 1 <= y <= hdr.maxs[1] + 1):
                    covering.append((path, crs, x, y))
        except Exception:
            continue
    return covering


def obtener_altura_lidar(footprint: dict | None = None,
                        lon: float | None = None,
                        lat: float | None = None) -> DataPoint:
    """Altura medida del edificio desde nube de puntos PNOA LiDAR.

    Método: P90 de la Z de los puntos dentro de la huella (recorte
    global a 60 m para excluir antenas/ruido) menos la mediana de los
    puntos clasificados ``ground`` (clase 2) en la huella. Si no hay
    clasificación de suelo, usa el MDT 5 m del WCS IDEE como cota de
    terreno. Sin ficheros LAZ/LAS que cubran el punto devuelve
    ``unavailable`` — no hay fallback silencioso a estimaciones.
    """
    if lon is None or lat is None:
        return unavailable('PNOA LiDAR', 'Faltan coordenadas')
    files = _laz_files_covering(lon, lat)
    if not files:
        return unavailable(
            'PNOA LiDAR',
            'Sin cobertura LiDAR en caché local '
            f'({os.path.relpath(LIDAR_CACHE_DIR)}) o extracción fallida')
    try:
        import laspy
        from shapely.geometry import Point, shape
        from shapely.prepared import prep
    except ImportError:
        return unavailable('PNOA LiDAR', 'laspy/shapely no disponibles')

    footprint_prep = None
    if footprint and footprint.get('coordinates'):
        try:
            footprint_prep = prep(shape(footprint))
        except Exception:
            footprint_prep = None

    zs_all: list[float] = []
    zs_ground: list[float] = []
    for path, crs, px, py in files:
        try:
            las = laspy.read(path)
        except Exception:
            continue
        xs = las.x
        ys = las.y
        poly = None
        if footprint_prep is not None and crs is not None:
            try:
                if str(crs.to_epsg() or '') in ('4326', '4258'):
                    poly = footprint_prep
                else:
                    from pyproj import Transformer
                    t = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
                    def _tx(coords):
                        return [t.transform(a, b) for a, b in coords]
                    geom = footprint
                    ext = _tx(geom['coordinates'][0])
                    from shapely.geometry import Polygon
                    poly = prep(Polygon(ext))
            except Exception:
                poly = None
        for i in range(len(xs)):
            x, y = xs[i], ys[i]
            if poly is not None:
                if not poly.contains(Point(x, y)):
                    continue
            else:
                if abs(x - px) > 15 or abs(y - py) > 15:
                    continue
            z = float(las.z[i])
            if z <= 0 or z > 1200:
                continue
            zs_all.append(z)
            try:
                if int(las.classification[i]) == 2:
                    zs_ground.append(z)
            except Exception:
                pass
    if len(zs_all) < 10:
        return unavailable('PNOA LiDAR', 'Puntos insuficientes dentro de la huella')
    zs_all.sort()
    roof = _percentile(zs_all, PCT)
    terrain = None
    if len(zs_ground) >= 5:
        zs_ground.sort()
        terrain = _percentile(zs_ground, 50)
    if terrain is None:
        terrain = _terreno_mdt(lon, lat)
    if terrain is None or roof is None:
        return unavailable('PNOA LiDAR', 'No se pudo derivar cota de terreno')
    height = roof - terrain
    if height < 0 or height > MAX_HEIGHT_M:
        return unavailable(
            'PNOA LiDAR',
            f'Altura P90−terreno fuera de rango ({height:.1f} m); probable ruido')
    return measured(
        round(height, 1), 'm', 'PNOA LiDAR',
        source_ref=f'nDSM P{PCT}, {len(zs_all)} puntos',
        notes='Precisión vertical PNOA ≈ ±25 cm')


def _terreno_mdt(lon: float, lat: float) -> float | None:
    """Cota de terreno (m) en un punto vía WCS MDT 5 m del IDEE."""
    d = 0.00045  # ~50 m
    url = (
        f'{MDT_WCS_URL}?SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage'
        f'&COVERAGEID={MDT_COVERAGE}'
        f'&SUBSET=Lat({lat - d},{lat + d})'
        f'&SUBSET=Long({lon - d},{lon + d})'
        '&FORMAT=image/tiff'
    )
    key = f'mdt_{lon:.5f}_{lat:.5f}'
    cached = disk_get('lidar', key, 90 * 24 * 3600)
    try:
        if cached is not None:
            return cached
        raw = http_get(url, timeout=30, retries=2)
        import io
        import rasterio
        with rasterio.open(io.BytesIO(raw)) as ds:
            val = list(ds.sample([(lon, lat)]))[0][0]
            val = float(val) if val == val else None  # NaN check
        if val is not None:
            disk_set('lidar', key, val)
        return val
    except Exception:
        return None


def obtener_datos_edificio(lon: float, lat: float,
                           refcat: str | None = None,
                           footprint: dict | None = None,
                           osm_height: float | None = None,
                           osm_levels: int | None = None,
                           fetch=None) -> dict:
    """Consolidado por punto con etiquetado :class:`DataPoint` por campo.

    Devuelve ``{altura, huella_m2, plantas, uso, fuente_altura}`` donde
    cada valor es ``DataPoint.to_dict()``; los campos no obtenibles
    figuran como ``unavailable`` con la razón, nunca se omiten.
    """
    out: dict[str, Any] = {}
    out['altura'] = obtener_altura_lidar(footprint, lon, lat).to_dict()
    if out['altura']['data_quality'] == DataQuality.UNAVAILABLE.value:
        if osm_height:
            out['altura_osm'] = estimated(
                osm_height, 'm', 'OpenStreetMap',
                source_ref='tag height o plantas × 3 m',
                notes='Dato comunitario, no verificado oficialmente'
            ).to_dict()
    if footprint and footprint.get('coordinates'):
        try:
            from shapely.geometry import shape
            area = shape(footprint).area
            import math
            m2 = area * (111320.0 ** 2) * math.cos(math.radians(lat))
            out['huella_m2'] = estimated(
                round(m2, 1), 'm²', 'Geometría OSM/Overture').to_dict()
        except Exception:
            pass
    if refcat:
        try:
            from src.catastro.client import obtener_edificios_por_parcela
            bu = obtener_edificios_por_parcela(refcat, fetch=fetch)
            eds = bu.get('edificios') or []
            if eds:
                ed = eds[0]
                if ed.get('plantas'):
                    out['plantas'] = DataPoint(
                        ed['plantas'], None, DataQuality.OFFICIAL,
                        'Catastro INSPIRE BU').to_dict()
                if ed.get('uso'):
                    out['uso'] = DataPoint(
                        ed['uso'], None, DataQuality.OFFICIAL,
                        'Catastro INSPIRE BU').to_dict()
                if ed.get('anio_construccion'):
                    out['anio_construccion'] = DataPoint(
                        ed['anio_construccion'], None, DataQuality.OFFICIAL,
                        'Catastro INSPIRE BU').to_dict()
                out['edificios_catastro'] = DataPoint(
                    len(eds), 'edificios', DataQuality.OFFICIAL,
                    'Catastro INSPIRE BU').to_dict()
        except Exception:
            pass
    if osm_levels and 'plantas' not in out:
        out['plantas'] = estimated(
            osm_levels, 'plantas', 'OpenStreetMap').to_dict()
    return out
