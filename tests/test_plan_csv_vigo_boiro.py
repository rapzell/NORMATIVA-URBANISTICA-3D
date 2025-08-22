import os
from fastapi.testclient import TestClient
from app.main import app


def test_validate_and_smoke_volume_with_vigo_boiro_csv(tmp_path, monkeypatch):
    # Copy sample CSV path
    csv_path = os.path.join('datos', 'planes_vigo_boiro.csv')

    client = TestClient(app)

    # Validate CSV via endpoint (path mode uses provider-level validations too)
    r = client.post('/zoning/validate-plan-csv', json={"path": csv_path})
    assert r.status_code == 200
    data = r.json()
    assert data['summary']['errors'] == 0
    assert data['valid'] is True

    # Configure provider env for subsequent requests
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', csv_path)
    monkeypatch.setenv('API_LOAD_RESOURCES', '0')

    # Simple square geometry
    geom = {"type": "Polygon", "coordinates": [[[0,0],[10,0],[10,10],[0,10],[0,0]]]} 

    # Smoke 1: Vigo O3_grado_alto
    r1 = client.post('/zoning/volume', json={
        "geometry": geom,
        "municipio": "Vigo",
        "subzona": "O3_grado_alto"
    })
    assert r1.status_code == 200
    assert r1.json().get('feature') is not None

    # Smoke 2: Boiro Residencial_baja (tiene setbacks direccionales pero sin front default, debería seguir siendo válido)
    r2 = client.post('/zoning/volume', json={
        "geometry": geom,
        "municipio": "Boiro",
        "subzona": "Residencial_baja"
    })
    assert r2.status_code == 200
    assert r2.json().get('feature') is not None
