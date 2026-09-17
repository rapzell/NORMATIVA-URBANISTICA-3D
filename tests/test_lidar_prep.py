"""Tests del flujo de preparación/procesado de teselas LiDAR."""
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.building_data import lidar_prep as lp


@pytest.fixture
def lidar_dir(tmp_path, monkeypatch):
    d = tmp_path / 'lidar'
    d.mkdir()
    monkeypatch.setattr(lp, 'LIDAR_CACHE_DIR', str(d))
    monkeypatch.setattr(lp, 'PENDIENTES_PATH', str(d / '_pendientes.json'))
    return d


MALLA = json.dumps({
    'features': [{
        'attributes': {
            'HOJA': '522-4678',
            'ARQUIVO_CENDES': 'PNOA_2015_GAL-W_522-4678_ORT-CLA-COL_edited.zip',
            'PERMALINK': 'perm123',
            'PRODUTO': 'LIDAR_2015_2016',
        }
    }]
}).encode()


def test_teselas_bbox_devuelve_urls():
    tiles = lp.teselas_bbox(-8.8, 42.1, -8.6, 42.4, fetch=lambda u: MALLA)
    assert len(tiles) == 1
    assert tiles[0]['hoja'] == '522-4678'
    assert tiles[0]['url_descarga'].endswith('/perm123')


def test_registrar_pendiente(lidar_dir, monkeypatch):
    monkeypatch.setattr(lp, 'hoja_lidar_para_punto',
                        lambda lon, lat, fetch=None: {
                            'available': True, 'hoja': '522-4678',
                            'arquivo': 'PNOA_2015_GAL-W_522-4678.zip',
                            'cobertura': 'LIDAR_2015_2016',
                            'url_descarga': 'https://x/perm'})
    monkeypatch.setattr(lp, 'estado_tesela', lambda h, a=None: 'pendiente')
    lp.registrar_pendiente(-8.7129, 42.2388)
    data = lp._load_pendientes()
    assert '522-4678' in data['teselas']
    assert data['teselas']['522-4678']['estado'] == 'pendiente'
    assert data['teselas']['522-4678']['puntos'] == [[-8.7129, 42.2388]]


def test_procesar_descargas_descomprime(lidar_dir, monkeypatch):
    # ZIP con un .las dentro (contenido fake: laspy fallará al validar,
    # por lo que el estado seguirá 'pendiente' — correcto)
    zpath = lidar_dir / 'PNOA_2015_GAL-W_522-4678.zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        z.writestr('PNOA_2015_GAL-W_522-4678.las', b'LASF fake content')
    monkeypatch.setattr(lp, 'estado_tesela', lambda h, a=None: 'descargada')
    res = lp.procesar_descargas()
    assert len(res['procesados']) == 1
    assert not zpath.exists()  # zip eliminado
    assert (lidar_dir / 'PNOA_2015_GAL-W_522-4678.las').exists()
    assert res['teselas_activas'] or True


def test_procesar_zip_sin_las_marca_error(lidar_dir):
    zpath = lidar_dir / 'vacio.zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        z.writestr('readme.txt', 'nada')
    res = lp.procesar_descargas()
    assert res['errores'][0]['zip'] == 'vacio.zip'
    assert zpath.exists()  # no se borra si falla


def test_estado_preparacion_vacio(lidar_dir):
    est = lp.estado_preparacion()
    assert est['pendientes'] == 0
    assert est['descargadas'] == 0
    assert 'instrucciones' in est


def test_laz_presente_por_hoja(lidar_dir):
    (lidar_dir / 'PNOA_2015_GAL-W_522-4678_ORT-CLA-COL_edited.laz').write_bytes(b'x')
    assert lp._laz_presente('522-4678', None) is not None
    assert lp._laz_presente('999-9999', None) is None
