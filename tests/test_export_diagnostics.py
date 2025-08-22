import os
from fastapi.testclient import TestClient

os.environ.setdefault('PLAN_PROVIDER', 'mock')
os.environ.setdefault('API_LOAD_RESOURCES', '0')

from app.main import app  # noqa: E402

client = TestClient(app)


def test_export_returns_diagnostics_when_exhausted_cityjson():
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        "municipio": "Vigo",
        "use_plan_front_default": True,
        "format": "cityjson",
    }
    resp = client.post("/zoning/volume-export?download=false", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("cityjson") is None
    diag = data.get("diagnostics") or {}
    assert diag.get("reason") == "parcel_exhausted_by_setbacks"


def test_export_returns_diagnostics_when_exhausted_gltf():
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        "municipio": "Vigo",
        "use_plan_front_default": True,
        "format": "gltf",
    }
    resp = client.post("/zoning/volume-export?download=false", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("gltf") is None
    diag = data.get("diagnostics") or {}
    assert diag.get("reason") == "parcel_exhausted_by_setbacks"
