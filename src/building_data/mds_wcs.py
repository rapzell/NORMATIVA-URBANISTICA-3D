"""Alturas de edificio vía WCS del IDEE (sin captcha ni descarga LAZ).

El IGN publica el Modelo Digital de Superficies por WCS 2.0.1 en
``wcs-mds.idee.es/mds`` con tres coberturas:

- ``mds05``     — MDS absoluto 5 m (elevación de superficie).
- ``mdsn_e025`` — MDS **normalizado de edificación** 2,5 m: altura del
  objeto sobre el terreno (nDSM), derivado del LiDAR 1ª cobertura PNOA.
- ``mdsn_v025`` — MDS normalizado de vegetación 2,5 m.

``mdsn_e025`` devuelve directamente la altura sobre rasante de los
edificios a 2,5 m de resolución — suficiente para altura de edificio
mediante percentil sobre la huella, sin LAZ ni captcha.

CRS nativo EPSG:3042 (ETRS89 UTM 30N extendido a toda España). Los
GeoTIFF se cachean 30 días en ``datos/cache/wcs/`` por bbox redondeado.

Trazabilidad: el resultado es ``measured`` con ``source`` =
"IDEE WCS MDSN" y notas sobre cobertura/resolución/percentil.
"""
from __future__ import annotations

import io
import os
from typing import Callable

from src.cache import disk_get, disk_set, http_get
from src.data_quality import DataPoint, measured, unavailable

WCS_MDS_URL = "https://wcs-mds.idee.es/mds"
COVERAGE_MDSN_EDIF = "mdsn_e025"   # nDSM edificación 2.5 m
COVERAGE_MDSN_VEG = "mdsn_v025"    # nDSM vegetación 2.5 m
COVERAGE_MDS05 = "mds05"           # MDS absoluto 5 m
TARGET_CRS = "EPSG:3042"
WCS_TTL_S = 30 * 24 * 3600
PCT = 90
MAX_HEIGHT_M = 100.0


def _to_3042(lon: float, lat: float) -> tuple[float, float]:
    from pyproj import Transformer
    t = Transformer.from_crs('EPSG:4326', TARGET_CRS, always_xy=True)
    return t.transform(lon, lat)


def _fetch_tiff(coverage_id: str, minx: float, miny: float,
                maxx: float, maxy: float,
                fetch: Callable[[str], bytes] | None = None) -> bytes | None:
    """GeoTIFF del WCS MDS para el bbox en EPSG:3042 (cache 30 días)."""
    key = (f'{coverage_id}_{minx:.0f}_{miny:.0f}_{maxx:.0f}_{maxy:.0f}')
    cached = disk_get('wcs', key, WCS_TTL_S)
    if cached is not None:
        import base64
        return base64.b64decode(cached)
    fetch = fetch or (lambda u: http_get(u, timeout=30, retries=2))
    url = (
        f'{WCS_MDS_URL}?service=WCS&version=2.0.1&request=GetCoverage'
        f'&coverageId={coverage_id}&format=image/tiff'
        f'&subset=x({minx:.0f},{maxx:.0f})&subset=y({miny:.0f},{maxy:.0f})'
    )
    try:
        raw = fetch(url)
    except Exception:
        return None
    if not raw.startswith((b'II', b'MM')):  # no es TIFF (XML excepción)
        return None
    import base64
    disk_set('wcs', key, base64.b64encode(raw).decode('ascii'))
    return raw


def altura_mdsn_edificio(
    footprint: dict | None = None,
    lon: float | None = None,
    lat: float | None = None,
    buffer_m: float = 15.0,
    percentil: int = PCT,
    coverage_id: str = COVERAGE_MDSN_EDIF,
    fetch: Callable[[str], bytes] | None = None,
) -> DataPoint:
    """Altura medida del edificio desde el MDS normalizado WCS.

    Descarga el GeoTIFF de ``mdsn_e025`` (2,5 m) para la huella + buffer,
    enmascara los píxeles dentro del polígono y devuelve el percentil
    P90 como altura — robusto frente a antenas y bordes. Sin huella,
    usa una ventana de ±15 m alrededor del punto.

    Devuelve ``unavailable`` si el servicio falla, no hay píxeles de
    edificación suficientes o la altura es implausible.
    """
    if lon is None or lat is None:
        return unavailable('IDEE WCS MDSN', 'Faltan coordenadas')
    try:
        import numpy as np
        import rasterio
        from rasterio.features import geometry_mask
    except ImportError:
        return unavailable('IDEE WCS MDSN', 'rasterio/numpy no disponibles')

    cx, cy = _to_3042(lon, lat)
    geom_3042 = None
    if footprint and footprint.get('coordinates'):
        try:
            from pyproj import Transformer
            from shapely.geometry import shape
            from shapely.ops import transform as shp_transform
            t = Transformer.from_crs('EPSG:4326', TARGET_CRS, always_xy=True)
            g = shape(footprint)
            geom_3042 = shp_transform(
                lambda x, y, z=None: t.transform(x, y), g)
            bx = geom_3042.bounds
            minx, miny = bx[0] - buffer_m, bx[1] - buffer_m
            maxx, maxy = bx[2] + buffer_m, bx[3] + buffer_m
        except Exception:
            geom_3042 = None
            minx, miny = cx - buffer_m, cy - buffer_m
            maxx, maxy = cx + buffer_m, cy + buffer_m
    else:
        minx, miny = cx - buffer_m, cy - buffer_m
        maxx, maxy = cx + buffer_m, cy + buffer_m

    raw = _fetch_tiff(coverage_id, minx, miny, maxx, maxy, fetch)
    if raw is None:
        return unavailable(
            'IDEE WCS MDSN',
            'Servicio WCS MDS sin respuesta o fuera de cobertura')

    try:
        with rasterio.open(io.BytesIO(raw)) as ds:
            arr = ds.read(1).astype(float)
            transform = ds.transform
            nodata = ds.nodata
            if geom_3042 is not None:
                mask = geometry_mask(
                    [geom_3042.__geo_interface__],
                    out_shape=arr.shape, transform=transform, invert=True)
                vals = arr[mask]
            else:
                vals = arr.ravel()
    except Exception:
        return unavailable('IDEE WCS MDSN', 'GeoTIFF ilegible')

    vals = vals[(vals > 0) & (vals < 200)]
    if nodata is not None:
        vals = vals[vals != nodata]
    if len(vals) < 4:
        return unavailable(
            'IDEE WCS MDSN',
            'Píxeles de edificación insuficientes en la huella')
    height = float(np.percentile(vals, percentil))
    if height <= 0 or height > MAX_HEIGHT_M:
        return unavailable(
            'IDEE WCS MDSN',
            f'Altura P{percentil} implausible ({height:.1f} m)')
    return measured(
        round(height, 1), 'm', 'IDEE WCS MDSN',
        source_ref=f'{coverage_id} 2.5 m, P{percentil}, {len(vals)} px',
        notes=('MDS normalizado de edificación (LiDAR 1ª cobertura PNOA); '
               'resolución 2.5 m, precisión ~±1 m'))
