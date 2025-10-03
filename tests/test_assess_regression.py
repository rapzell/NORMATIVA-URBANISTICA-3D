from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def rect(w=30.0, h=12.0):
    return {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [w, 0], [w, h], [0, h], [0, 0]]
        ],
    }


def test_assess_condicionado_or_apto_with_params():
    body = {
        "geometry": rect(30, 12),
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 2.0,
        "use_plan_front_default": True,
    }
    r = client.post("/zoning/assess", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("viability") in ("apto", "condicionado", "no_apto")
    assert isinstance(data.get("reasons"), list)
    pe = data.get("params_effective") or {}
    assert pe.get("altura_maxima_m") == 10.0
