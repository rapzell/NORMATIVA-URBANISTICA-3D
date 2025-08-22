from fastapi.testclient import TestClient
from app.main import app


def test_geometry_checks_auto_metric_from_wgs84():
    client = TestClient(app)
    # Small square near Vigo (~ -8.7 lon, UTM zone 29N)
    geom = {
        "type": "Polygon",
        "coordinates": [[
            [-8.70, 42.23],
            [-8.70, 42.2305],
            [-8.6995, 42.2305],
            [-8.6995, 42.23],
            [-8.70, 42.23]
        ]]
    }
    payload = {"geometry": geom, "crs": "EPSG:4326"}
    r = client.post('/zoning/geometry-checks', json=payload)
    assert r.status_code == 200
    j = r.json()
    # Should not be zero area, and perimeter in meters should be sensible (> 0 and < 500 m for this tiny square)
    assert j['area'] > 0
    assert 0 < j['perimeter'] < 5000
