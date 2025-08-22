from fastapi.testclient import TestClient
from app.main import app


def test_volume_directional_rect_north():
    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "altura_maxima_m": 8,
        "setback_front_m": 2.0,   # north
        "setback_back_m": 1.0,    # south
        "setback_side_m": 0.5,    # east+west
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    j = r.json()
    feat = j['feature']
    assert feat is not None
    props = feat['properties']
    # Width = 10 - 0.5 - 0.5 = 9; Height = 10 - 2 - 1 = 7; Area = 63
    assert abs(props['area_m2'] - 63.0) < 1e-6
    assert props['setback_mode'] == 'rect_directional'
    assert props['front_direction'] == 'north'
    # In directional mode, uniform setback applied is 0.0
    assert abs(props['setback_applied_m'] - 0.0) < 1e-6
