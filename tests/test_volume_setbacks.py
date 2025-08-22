from fastapi.testclient import TestClient
from app.main import app


def test_volume_differentiated_setbacks_conservative_max():
    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "altura_maxima_m": 9,
        "retranqueo_min_m": 1.0,
        "setback_front_m": 2.0,
        "setback_side_m": 3.0,
        "setback_back_m": 0.5
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    j = r.json()
    feat = j['feature']
    assert feat is not None
    props = feat['properties']
    # Max setback among provided is 3.0 (side) -> apply uniform 3.0 on a 10x10 square => 4x4 area
    assert abs(props['setback_applied_m'] - 3.0) < 1e-6
    assert props['setback_mode'] == 'conservative_max_uniform'
    assert abs(props['area_m2'] - 16.0) < 1e-6
