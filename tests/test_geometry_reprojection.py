from fastapi.testclient import TestClient
from app.main import app


def test_geometry_checks_identity_reprojection():
    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "crs": "EPSG:4326",
        "target_crs": "EPSG:4326"
    }
    r = client.post('/zoning/geometry-checks', json=payload)
    assert r.status_code == 200
    j = r.json()
    # No reprojection -> same area in degree-space computation path; however, we don't project, so area isn't meters.
    # Identity reprojection should not change geometry; area is as computed by shapely in input CRS.
    assert j['is_valid'] is True
    assert j['convexity_ratio'] == 1.0
