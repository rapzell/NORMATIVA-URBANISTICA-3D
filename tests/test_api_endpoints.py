import os
from fastapi.testclient import TestClient
from app.main import app


def setup_module(module):
    # Evitar cargas pesadas en startup
    os.environ['API_LOAD_RESOURCES'] = '0'


def test_health():
    client = TestClient(app)
    r = client.get('/health')
    assert r.status_code == 200
    body = r.json()
    assert body.get('status') == 'ok'


def test_geometry_checks_endpoint():
    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}
    }
    r = client.post('/zoning/geometry-checks', json=payload)
    assert r.status_code == 200
    j = r.json()
    assert j['area'] == 100.0
    assert j['is_valid'] is True


def test_volume_with_municipal_params():
    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio":"Vigo",
        "subzona":"RZ-2"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    j = r.json()
    assert 'feature' in j
    feat = j['feature']
    assert feat is not None
    props = feat['properties']
    # Mock RZ-2: altura 12, retranqueo 3 => buildable square 4x4 => area 16
    assert abs(props['height_m'] - 12.0) < 1e-6
    assert abs(props['setback_m'] - 3.0) < 1e-6
    assert abs(props['area_m2'] - 16.0) < 1e-6


def test_infer_subzone_without_municipality_config():
    client = TestClient(app)
    r = client.post('/zoning/infer-subzone', json={
        "lon": -8.72,
        "lat": 42.23,
        "municipio": "Municipio Inexistente",
    })
    assert r.status_code == 200
    j = r.json()
    assert j['subzona'] is None
    assert j['source'] == 'wms'
    assert j['diagnostics']['reason'] == 'no_cfg_for_municipio'
