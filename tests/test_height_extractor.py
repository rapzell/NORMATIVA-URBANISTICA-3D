"""Tests del extractor de alturas (LiDAR/Overture) — sin deps pesadas."""
from src.building_data import height_extractor as he
from src.data_quality import DataQuality


def test_percentile():
    vals = sorted([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert he._percentile(vals, 50) == 5.5
    p90 = he._percentile(vals, 90)
    assert 9 <= p90 <= 10
    assert he._percentile([], 90) is None


def test_lidar_sin_cobertura_devuelve_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(he, 'LIDAR_CACHE_DIR', str(tmp_path))
    dp = he.obtener_altura_lidar(lon=-8.72, lat=42.23)
    d = dp.to_dict()
    assert d['data_quality'] == 'unavailable'
    assert d['value'] is None
    assert 'LiDAR' in d['source']


def test_lidar_sin_coords():
    dp = he.obtener_altura_lidar()
    assert dp.quality is DataQuality.UNAVAILABLE


def test_obtener_datos_edificio_estructura(tmp_path, monkeypatch):
    monkeypatch.setattr(he, 'LIDAR_CACHE_DIR', str(tmp_path))
    out = he.obtener_datos_edificio(-8.72, 42.23, osm_height=12.0,
                                  osm_levels=4)
    assert out['altura']['data_quality'] == 'unavailable'
    assert out['altura_osm']['data_quality'] == 'estimated'
    assert out['altura_osm']['value'] == 12.0
    assert out['plantas']['value'] == 4
    assert out['plantas']['data_quality'] == 'estimated'


def test_huellas_sin_duckdb(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == 'duckdb':
            raise ImportError('no duckdb')
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, '__import__', fake_import)
    res = he.obtener_huellas_municipio('x', bbox=(-8.8, 42.2, -8.6, 42.3))
    assert res['available'] is False
    assert 'duckdb' in (res.get('error') or '')
