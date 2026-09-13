import os
from fastapi.testclient import TestClient

# Ensure mock provider and light startup (force to avoid leaking dev env)
os.environ['PLAN_PROVIDER'] = 'mock'
os.environ.pop('PLAN_CSV_PATH', None)
os.environ.setdefault('API_LOAD_RESOURCES', '0')

from app.main import app  # noqa: E402

client = TestClient(app)


def test_tiny_parcel_returns_exhausted_diagnostic():
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        "municipio": "Vigo",
        "use_plan_front_default": True,
    }
    resp = client.post("/zoning/volume", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("feature") is None
    diag = data.get("diagnostics") or {}
    assert diag.get("reason") == "parcel_exhausted_by_setbacks"


def test_street_axis_drives_front_detection_when_close():
    # 10x10 parcel in LOCAL units; provide a street axis just south of parcel
    body = {
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        "municipio": "Vigo",
        # Do not force front_direction; let street_axis decide
        "street_axis": {"type": "LineString", "coordinates": [[0, -5], [10, -5]]},
    }
    resp = client.post("/zoning/volume", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    feat = data.get("feature")
    assert isinstance(feat, dict), f"Expected feature dict, got: {feat}"
    props = feat.get("properties") or {}
    # Should have used street axis for detection
    assert props.get("street_axis_used") is True
    # With street line south of parcel, expected front side is 'bottom'
    assert props.get("front_detected_side") in ("bottom", "top", "left", "right")
    # Specifically bottom given our coordinates
    assert props.get("front_detected_side") == "bottom"
    # Source should reflect street axis
    assert props.get("front_direction_source") == "street_axis"
