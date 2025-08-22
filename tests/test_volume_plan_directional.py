import os
from fastapi.testclient import TestClient
from app.main import app


def test_volume_uses_csv_plan_directional_setbacks(monkeypatch):
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
        # No height or setbacks provided; should use CSV: altura=12, front=2, side=1, back=0.5
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    feat = r.json()['feature']
    assert feat is not None
    props = feat['properties']
    # Width = 10 - 1 - 1 = 8; Height = 10 - 2 - 0.5 = 7.5; Area = 60
    assert abs(props['area_m2'] - 60.0) < 1e-6
    assert props['height_m'] == 12.0
    assert props['setback_mode'] in ('rect_directional', 'rotated_rect_directional')
