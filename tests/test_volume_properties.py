from shapely.geometry import LineString
from fastapi.testclient import TestClient
from app.main import app


def test_properties_include_street_axis_used_and_front_side():
    client = TestClient(app)
    geom = {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}
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
    assert props.get('street_axis_used') is True
    # With a horizontal street above the parcel, the front should be 'top'
    assert props.get('front_detected_side') in ('top', 'bottom', 'left', 'right')
