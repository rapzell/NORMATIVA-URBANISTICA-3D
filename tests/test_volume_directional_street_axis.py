from shapely.geometry import LineString
from fastapi.testclient import TestClient
from app.main import app


def test_volume_directional_auto_front_with_street_axis():
    client = TestClient(app)
    # Parcel axis-aligned 10x10 at origin
    geom = {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}
    # Street axis close to the top edge (y ~ 11): should pick 'top' as front
    street = LineString([(0, 11), (10, 11)]).__geo_interface__
    payload = {
        "geometry": geom,
        "altura_maxima_m": 9,
        "setback_front_m": 2.0,
        "setback_back_m": 1.0,
        "setback_side_m": 0.5,
        "street_axis": street
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    feat = r.json()['feature']
    assert feat is not None
    props = feat['properties']
    # Should be treated as directional; rect or rotated_rect
    assert props['setback_mode'] in ('rect_directional', 'rotated_rect_directional')
    # Area should be (10-0.5-0.5)*(10-2-1) = 63
    assert abs(props['area_m2'] - 63.0) < 1e-6
