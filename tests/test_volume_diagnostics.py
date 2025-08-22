from fastapi.testclient import TestClient
from app.main import app


def test_diagnostics_street_axis_used_source_and_side():
    client = TestClient(app)
    # Axis-aligned square 10x10, street above -> front detected top
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "altura_maxima_m": 10,
        "retranqueo_min_m": 1,
        "setback_front_m": 2,
        "setback_side_m": 1,
        "setback_back_m": 0.5,
        "street_axis": {"type":"LineString","coordinates":[[0, 11],[10,11]]}
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    feat = r.json()['feature']
    props = feat['properties']
    assert props['street_axis_used'] is True
    assert props['front_detected_side'] == 'top'
    assert props['front_direction_source'] == 'street_axis'
    assert props['street_axis_ignored_reason'] is None


def test_diagnostics_street_axis_ignored_reason_too_far(monkeypatch):
    client = TestClient(app)
    # Place street far away so it gets ignored
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "altura_maxima_m": 10,
        "retranqueo_min_m": 1,
        "setback_front_m": 2,
        "setback_side_m": 1,
        "setback_back_m": 0.5,
        "street_axis": {"type":"LineString","coordinates":[[0, 100],[10,100]]}
    }
    # tighten factor to ensure it's ignored
    monkeypatch.setenv('STREET_MAX_DIST_FACTOR', '0.1')
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['street_axis_used'] is False
    assert props['street_axis_ignored_reason'] in ('too_far','geom_error')


def test_diagnostics_front_direction_source_plan_default(monkeypatch):
    # Use CSV provider and plan default front
    import os
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
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['front_direction_source'] in ('plan_default','street_axis')  # street may not be provided; prefer plan_default
    # When no street, should be plan_default
    assert props['front_direction_source'] == 'plan_default'
