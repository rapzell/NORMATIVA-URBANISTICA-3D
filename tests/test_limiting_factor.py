import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_limiting_factor_retranqueos_exhausted():
    # Parcela 12x12 con retranqueo 6 m -> envolvente vacía
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0,0],[12,0],[12,12],[0,12],[0,0]]]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 6.0
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("feature") is None
    assert data.get("limiting_factor") == "retranqueos"
    diag = data.get("diagnostics") or {}
    assert diag.get("reason") == "parcel_exhausted_by_setbacks"


def test_limiting_factor_altura_default():
    # Parcela 12x12 sin retranqueo -> envolvente existe, factor por defecto 'altura'
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0,0],[12,0],[12,12],[0,12],[0,0]]]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("feature") is not None
    # Cuando no hay ocupación/edificabilidad ni retranqueos limitantes, esperamos 'altura'
    assert data.get("limiting_factor") == "altura"
    details = data.get("limiting_details") or {}
    assert "buildable_area_m2" in details
