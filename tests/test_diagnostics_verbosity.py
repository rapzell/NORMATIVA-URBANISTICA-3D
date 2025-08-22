from fastapi.testclient import TestClient
from app.main import app

def _square():
    return {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}

def test_volume_diagnostics_verbosity_min_override(tmp_path, monkeypatch):
    # Provide minimal CSV so municipio resolves
    p = tmp_path / 'planes.csv'
    p.write_text("municipio,subzona,altura_maxima_m\nFoo,,10\n", encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": _square(),
        "municipio": "Foo",
        "diagnostics_verbosity": "min"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data.get('diagnostics_level_applied') == 'min'
    props = data['feature']['properties']
    # kept
    assert 'front_detected_side' in props
    assert 'front_direction_source' in props
    assert 'polygon_type' in props
    # filtered out
    assert 'street_axis_min_distance_m' not in props
    assert 'front_selection_rationale' not in props


def test_volume_diagnostics_verbosity_none_override(tmp_path, monkeypatch):
    p = tmp_path / 'planes.csv'
    p.write_text("municipio,subzona,altura_maxima_m\nFoo,,10\n", encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": _square(),
        "municipio": "Foo",
        "diagnostics_verbosity": "none"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data.get('diagnostics_level_applied') == 'none'
    props = data['feature']['properties']
    # Key diagnostics should be absent
    for k in (
        'front_detected_side','front_direction_source','street_axis_used',
        'street_axis_min_distance_m','street_axis_side_distances','front_selection_rationale',
        'street_axis_ignored_reason','polygon_type','directional_applicability','directional_not_applied_reason'
    ):
        assert k not in props
