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


def _make_las(path, pts):
    """LAS sintético: pts = [(x, y, z, classification)]."""
    import laspy
    import numpy as np
    hdr = laspy.LasHeader(point_format=3, version='1.2')
    try:
        from pyproj import CRS
        hdr.add_crs(CRS.from_epsg(4326))
    except Exception:
        pass
    hdr.scales = np.array([1e-6, 1e-6, 0.01])
    hdr.offsets = np.array([0.0, 0.0, 0.0])
    las = laspy.LasData(hdr)
    las.x = np.array([p[0] for p in pts])
    las.y = np.array([p[1] for p in pts])
    las.z = np.array([p[2] for p in pts])
    las.classification = np.array([p[3] for p in pts], dtype=np.uint8)
    las.write(str(path))


def _footprint(cx, cy, d=0.0002):
    return {'type': 'Polygon', 'coordinates': [[
        [cx - d, cy - d], [cx + d, cy - d],
        [cx + d, cy + d], [cx - d, cy + d],
        [cx - d, cy - d]]]}


def test_lidar_p90_sobre_huella(tmp_path, monkeypatch):
    """Fin a fino: LAS sintético → altura P90 − terreno medida."""
    import pytest
    pytest.importorskip('laspy')
    monkeypatch.setattr(he, 'LIDAR_CACHE_DIR', str(tmp_path))
    import random
    rng = random.Random(7)
    cx, cy = -8.72, 42.23
    pts = []
    # Terreno a ~100 m (clase 2) dentro y alrededor de la huella
    for _ in range(300):
        pts.append((cx + rng.uniform(-0.0004, 0.0004),
                    cy + rng.uniform(-0.0004, 0.0004),
                    100.0 + rng.uniform(-0.2, 0.2), 2))
    # Tejado a ~114 m (clase 6, edificio) dentro de la huella
    for _ in range(120):
        pts.append((cx + rng.uniform(-0.00015, 0.00015),
                    cy + rng.uniform(-0.00015, 0.00015),
                    114.0 + rng.uniform(-0.3, 0.3), 6))
    # Ruido (antena) en minoría — el P90 no debe tomarlo
    for _ in range(10):
        pts.append((cx + rng.uniform(-0.0001, 0.0001),
                    cy + rng.uniform(-0.0001, 0.0001),
                    150.0, 6))
    _make_las(tmp_path / 'tile.las', pts)
    dp = he.obtener_altura_lidar(_footprint(cx, cy), lon=cx, lat=cy).to_dict()
    assert dp['data_quality'] == 'measured'
    assert dp['source'] == 'PNOA LiDAR'
    assert 10.0 <= dp['value'] <= 18.0


def test_lidar_altura_fuera_de_rango_unavailable(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip('laspy')
    monkeypatch.setattr(he, 'LIDAR_CACHE_DIR', str(tmp_path))
    import random
    rng = random.Random(1)
    cx, cy = -8.72, 42.23
    pts = []
    for _ in range(200):
        pts.append((cx + rng.uniform(-0.0004, 0.0004),
                    cy + rng.uniform(-0.0004, 0.0004),
                    100.0 + rng.uniform(-0.2, 0.2), 2))
    for _ in range(120):
        pts.append((cx + rng.uniform(-0.00015, 0.00015),
                    cy + rng.uniform(-0.00015, 0.00015),
                    200.0, 6))  # 100 m > MAX_HEIGHT_M → ruido
    _make_las(tmp_path / 'tile.las', pts)
    dp = he.obtener_altura_lidar(_footprint(cx, cy), lon=cx, lat=cy).to_dict()
    assert dp['data_quality'] == 'unavailable'
    assert 'rango' in (dp['notes'] or '')


def test_lidar_puntos_insuficientes_unavailable(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip('laspy')
    monkeypatch.setattr(he, 'LIDAR_CACHE_DIR', str(tmp_path))
    cx, cy = -8.72, 42.23
    _make_las(tmp_path / 'tile.las',
              [(cx, cy, 100.0, 2), (cx + 0.0001, cy, 114.0, 6)])
    dp = he.obtener_altura_lidar(_footprint(cx, cy), lon=cx, lat=cy).to_dict()
    assert dp['data_quality'] == 'unavailable'


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
