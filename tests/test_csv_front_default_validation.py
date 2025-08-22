import os
from fastapi.testclient import TestClient
from app.main import app


def test_invalid_front_direction_default_returns_400(tmp_path, monkeypatch):
    # Create a temporary CSV with invalid front_direction_default
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Vigo,RZ-2,12,3,2.0,1.0,0.5,NORTHERN,0.35,0.90\n"
    )
    csv_file = tmp_path / "planes_invalid.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    # Configure provider to use this CSV
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(csv_file))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Vigo",
        "subzona": "RZ-2",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    detail = r.json().get('detail', '')
    assert 'front_direction_default inválido' in detail
    assert 'NORTHERN' in detail
    assert 'north|east|south|west' in detail
