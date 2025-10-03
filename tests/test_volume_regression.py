import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def make_square(size=20.0):
    s = float(size)
    return {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [s, 0], [s, s], [0, s], [0, 0]]
        ],
    }


def test_zoning_volume_basic_feature():
    body = {
        "geometry": make_square(20.0),
        "altura_maxima_m": 12,
        "retranqueo_min_m": 3.0,
        "use_plan_front_default": True,
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    # Debe venir un feature GeoJSON con propiedades
    feat = data.get("feature")
    assert isinstance(feat, dict), data
    assert feat.get("type") == "Feature"
    props = feat.get("properties") or {}
    # Propiedades mínimas esperadas
    assert "height_m" in props
    # Diagnóstico presente aunque sea mínimo
    assert "diagnostics_level_applied" in data or "diagnostics" in data
