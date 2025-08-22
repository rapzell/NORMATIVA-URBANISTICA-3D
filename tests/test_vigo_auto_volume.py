import os
from fastapi.testclient import TestClient

# Ensure mock plan provider and disable heavy resource loading for tests
os.environ.setdefault('PLAN_PROVIDER', 'mock')
os.environ.setdefault('API_LOAD_RESOURCES', '0')

from app.main import app  # noqa: E402

client = TestClient(app)


def test_vigo_auto_returns_feature_for_large_parcel():
    body = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
        "municipio": "Vigo",
        "use_plan_front_default": True,
    }
    resp = client.post("/zoning/volume", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    feat = data.get("feature")
    assert isinstance(feat, dict), f"Expected feature dict, got: {feat}"
    props = feat.get("properties") or {}
    geom = feat.get("geometry") or {}
    assert geom.get("type") in ("Polygon", "MultiPolygon")
    # Should have a positive height
    h = float(props.get("height_m") or 0)
    assert h > 0.0


def test_vigo_auto_small_parcel_is_handled_gracefully():
    """Tiny parcel should not crash; may return feature None due to setbacks exhaustion."""
    body = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        },
        "municipio": "Vigo",
        "use_plan_front_default": True,
    }
    resp = client.post("/zoning/volume", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Either None (exhausted) or a feature with zero/very small area depending on fallback
    assert "feature" in data
