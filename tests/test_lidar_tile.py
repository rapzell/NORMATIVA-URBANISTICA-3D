"""Tests del descubrimiento de teselas LiDAR (malla CENDES/IDEGA)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.building_data import height_extractor as he


MALLA_RESP = json.dumps({
    'features': [{
        'attributes': {
            'HOJA': '522-4676',
            'ARQUIVO_CENDES': 'PNOA_2015_GAL-W_522-4676_ORT-CLA-COL_edited.zip',
            'PERMALINK': 'abc123permalink',
            'PRODUTO': 'LIDAR_2015_2016',
            'ETIQUETA': 'LIDAR_2015_2016_clasificado',
        }
    }]
}).encode()


def test_hoja_lidar_devuelve_permalink(monkeypatch):
    monkeypatch.setattr(he, 'disk_get', lambda *a, **k: None)
    monkeypatch.setattr(he, 'disk_set', lambda *a, **k: None)
    r = he.hoja_lidar_para_punto(-8.72, 42.23, fetch=lambda u: MALLA_RESP)
    assert r['available'] is True
    assert r['hoja'] == '522-4676'
    assert r['arquivo'].endswith('.zip')
    assert r['url_descarga'] == 'https://descargas.xunta.es/abc123permalink'
    assert r['data_quality'] == 'official'


def test_hoja_lidar_fuera_de_cobertura(monkeypatch):
    monkeypatch.setattr(he, 'disk_get', lambda *a, **k: None)
    empty = json.dumps({'features': []}).encode()
    r = he.hoja_lidar_para_punto(-3.0, 40.0, fetch=lambda u: empty)
    assert r['available'] is False
    assert 'cobertura' in r['error'].lower() or 'fuera' in r['error'].lower()


def test_hoja_lidar_error_de_red(monkeypatch):
    monkeypatch.setattr(he, 'disk_get', lambda *a, **k: None)

    def boom(url):
        raise RuntimeError('timeout')
    r = he.hoja_lidar_para_punto(-8.72, 42.23, fetch=boom)
    assert r['available'] is False
    assert 'timeout' in r['error']


def test_hoja_lidar_usa_cache(monkeypatch):
    cached = {'available': True, 'hoja': '999-9999', 'cached': True}
    monkeypatch.setattr(he, 'disk_get', lambda *a, **k: cached)
    r = he.hoja_lidar_para_punto(-8.72, 42.23,
                               fetch=lambda u: (_ for _ in ()).throw(
                                   AssertionError('no debe llamar a red')))
    assert r['hoja'] == '999-9999'
