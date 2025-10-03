import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

CSV_HEADER = \
"municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"


def apply_csv_text(csv_text: str):
    r = client.post("/admin/apply-plan-csv-text", json={"csv_text": csv_text})
    assert r.status_code == 200, r.text


def test_limiting_factor_ocupacion_plan():
    # Plan con ocupación muy baja (0.1) y altura grande -> debe limitar ocupación
    csv = CSV_HEADER + "Vigo,,50,0,,,,,0.1,\n"
    apply_csv_text(csv)
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0,0],[10,0],[10,10],[0,10],[0,0]]]},  # 100 m2
        "municipio": "Vigo",
        "subzona": "",
        "use_plan_front_default": True
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("feature") is not None
    assert data.get("limiting_factor") == "ocupacion"
    det = data.get("limiting_details") or {}
    assert det.get("ocupacion_max") == 0.1
    assert det.get("parcel_area_m2") == 100.0


def test_limiting_factor_edificabilidad_plan():
    # Plan con edificabilidad muy baja (0.05 m2/m2) -> incluso una planta (100 m2) excede cap=5 m2
    csv = CSV_HEADER + "Vigo,,50,0,,,,,,0.05\n"
    apply_csv_text(csv)
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0,0],[10,0],[10,10],[0,10],[0,0]]]},  # 100 m2
        "municipio": "Vigo",
        "subzona": "",
        "use_plan_front_default": True
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("feature") is not None
    assert data.get("limiting_factor") == "edificabilidad"
    det = data.get("limiting_details") or {}
    assert det.get("edificabilidad_max_m2_m2") == 0.05
    assert det.get("parcel_area_m2") == 100.0
