"""Tests del cliente WCS MDS del IDEE (alturas nDSM sin captcha)."""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.building_data import mds_wcs


def _fake_tiff(x0=28500, y0=4692000, size=20, res=2.5, value=15.0):
    """GeoTIFF sintético en memoria con elevación uniforme."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    arr = np.full((size, size), value, dtype='float32')
    buf = io.BytesIO()
    with rasterio.open(
        buf, 'w', driver='GTiff', width=size, height=size, count=1,
        dtype='float32', crs='EPSG:3042',
        transform=from_origin(x0, y0 + size * res, res, res),
    ) as dst:
        dst.write(arr, 1)
    return buf.getvalue()


def test_fetch_tiff_cachea(monkeypatch):
    monkeypatch.setattr(mds_wcs, 'disk_get', lambda *a, **k: None)
    saved = {}
    monkeypatch.setattr(mds_wcs, 'disk_set',
                        lambda s, k, v: saved.update({k: v}))
    tiff = _fake_tiff()
    raw = mds_wcs._fetch_tiff('mdsn_e025', 28000, 4692000, 28100, 4692100,
                            fetch=lambda u: tiff)
    assert raw == tiff
    assert saved, 'debe cachear el GeoTIFF'


def test_fetch_tiff_rechaza_no_tiff(monkeypatch):
    monkeypatch.setattr(mds_wcs, 'disk_get', lambda *a, **k: None)
    raw = mds_wcs._fetch_tiff('mdsn_e025', 0, 0, 1, 1,
                            fetch=lambda u: b'<xml>Exception</xml>')
    assert raw is None


def test_altura_mdsn_p90_sobre_huella(monkeypatch):
    pytest.importorskip('rasterio')
    monkeypatch.setattr(mds_wcs, 'disk_get', lambda *a, **k: None)
    monkeypatch.setattr(mds_wcs, 'disk_set', lambda *a, **k: None)
    lon, lat = -8.7, 42.23
    footprint = {
        'type': 'Polygon',
        'coordinates': [[[lon, lat], [lon + 0.0003, lat],
                         [lon + 0.0003, lat + 0.0002], [lon, lat + 0.0002],
                         [lon, lat]]],
    }
    # TIFF de 12 m de altura cubriendo la huella transformada + margen
    from pyproj import Transformer
    t = Transformer.from_crs('EPSG:4326', 'EPSG:3042', always_xy=True)
    x0, y0 = t.transform(lon - 0.001, lat - 0.001)
    tiff = _fake_tiff(value=12.0, size=80, x0=x0, y0=y0)
    monkeypatch.setattr(mds_wcs, '_fetch_tiff', lambda *a, **k: tiff)
    dp = mds_wcs.altura_mdsn_edificio(footprint, lon, lat)
    d = dp.to_dict()
    assert d['data_quality'] == 'measured'
    assert d['value'] == pytest.approx(12.0, abs=0.5)
    assert 'mdsn_e025' in (d['source_ref'] or '')


def test_altura_mdsn_unavailable_sin_servicio(monkeypatch):
    monkeypatch.setattr(mds_wcs, 'disk_get', lambda *a, **k: None)
    monkeypatch.setattr(mds_wcs, '_fetch_tiff', lambda *a, **k: None)
    dp = mds_wcs.altura_mdsn_edificio(None, -8.7, 42.23)
    assert dp.to_dict()['data_quality'] == 'unavailable'


def test_altura_mdsn_unavailable_sin_pixeles(monkeypatch):
    pytest.importorskip('rasterio')
    monkeypatch.setattr(mds_wcs, 'disk_get', lambda *a, **k: None)
    tiff = _fake_tiff(value=0.0)  # sin edificación
    monkeypatch.setattr(mds_wcs, '_fetch_tiff', lambda *a, **k: tiff)
    dp = mds_wcs.altura_mdsn_edificio(None, -8.7, 42.23)
    assert dp.to_dict()['data_quality'] == 'unavailable'


def test_beta_light_desactiva_lidar(monkeypatch):
    """En Render free (RENDER=true) no se importa rasterio ni se llama WCS."""
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.delenv('BETA_LIGHT', raising=False)
    assert mds_wcs.beta_light()
    monkeypatch.setattr(mds_wcs, '_fetch_tiff',
                        lambda *a, **k: pytest.fail('no debe descargar'))
    dp = mds_wcs.altura_mdsn_edificio(None, -8.7, 42.23)
    d = dp.to_dict()
    assert d['data_quality'] == 'unavailable'
    assert 'beta ligera' in (d['notes'] or '')


def test_beta_light_escape(monkeypatch):
    """BETA_LIGHT=0 reactiva la medición aunque RENDER esté definido."""
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('BETA_LIGHT', '0')
    assert not mds_wcs.beta_light()
