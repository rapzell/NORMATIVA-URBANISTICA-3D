from fastapi.testclient import TestClient
from app.main import app


def test_street_axis_far_is_ignored():
    client = TestClient(app)
    geom = {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}
    # Very far street axis
    street = {"type":"LineString","coordinates":[[1000,1000],[1010,1010]]}
    payload = {
        "geometry": geom,
        "altura_maxima_m": 10,
        # No directional context; far street should be ignored and fallback to uniform retranqueo_min
        "retranqueo_min_m": 1.0,
        "street_axis": street
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    feat = r.json()['feature']
    assert feat is not None
    props = feat['properties']
    # Fallback uniform with retranqueo_min=1.0 -> buildable square side 8 => area 64
    assert abs(props['area_m2'] - 64.0) < 1e-6


def test_exhausted_geometry_returns_none():
    client = TestClient(app)
    # Parcel 4x4, uniform setback 3 -> buildable  (4-6) negative -> None
    geom = {"type":"Polygon","coordinates":[[[0,0],[4,0],[4,4],[0,4],[0,0]]]}
    payload = {
        "geometry": geom,
        "altura_maxima_m": 10,
        "retranqueo_min_m": 3.0
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    assert r.json()['feature'] is None
