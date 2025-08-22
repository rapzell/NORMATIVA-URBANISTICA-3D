import os
from fastapi.testclient import TestClient
from app.main import app


def test_volume_uses_plan_front_direction_default(monkeypatch):
    # Configure CSV provider
    csv_path = os.path.join(os.path.dirname(__file__), '..', 'datos', 'planes_municipales_sample.csv')
    csv_path = os.path.abspath(csv_path)
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', csv_path)

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Vigo",
        "subzona": "RZ-2",
        "use_plan_front_default": True
        # No front_direction and no street_axis -> should use plan.front_direction_default ('north')
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    feat = r.json()['feature']
    assert feat is not None
    props = feat['properties']
    # With plan setbacks front=2, back=0.5, side=1 and front default north (top), area is (10-1-1)*(10-2-0.5) = 8*7.5 = 60
    assert abs(props['area_m2'] - 60.0) < 1e-6
    assert props['setback_mode'] in ('rect_directional', 'rotated_rect_directional')
