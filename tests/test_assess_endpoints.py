import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def make_square(size=10.0):
    s = float(size)
    return {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [s, 0], [s, s], [0, s], [0, 0]]
        ],
    }


def test_zoning_assess_apto_minimal():
    body = {
        "geometry": make_square(10.0),
        "altura_maxima_m": 8,
        "retranqueo_min_m": 0.5,
        "use_plan_front_default": True,
    }
    r = client.post("/zoning/assess", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["viability"] in ("apto", "condicionado")
    # Debe devolver params_effective con altura/retranqueo
    pe = data.get("params_effective") or {}
    assert pe.get("altura_maxima_m") == 8
    assert isinstance(data.get("reasons"), list)


def test_zoning_assess_report_html():
    body = {
        "geometry": make_square(8.0),
        "altura_maxima_m": 6,
        "retranqueo_min_m": 0.0,
        "use_plan_front_default": False,
    }
    b64 = json.dumps(body).encode("utf-8")
    import base64

    body_b64 = base64.b64encode(b64).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")
    r = client.get(f"/zoning/assess-report?body_b64={body_b64}")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("text/html"), r.headers.get("content-type")
    assert "Informe de Viabilidad" in r.text
