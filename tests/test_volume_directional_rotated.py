from math import cos, sin, radians
from shapely.geometry import Polygon, mapping
from fastapi.testclient import TestClient
from app.main import app


def rotate_point(x, y, angle_deg):
    a = radians(angle_deg)
    return (x * cos(a) - y * sin(a), x * sin(a) + y * cos(a))


def make_rotated_rect(cx, cy, w, h, angle_deg):
    # axis-aligned corners centered at (cx,cy)
    hw, hh = w / 2, h / 2
    pts = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    rpts = [rotate_point(x, y, angle_deg) for (x, y) in pts]
    rpts = [(cx + x, cy + y) for (x, y) in rpts]
    return Polygon(rpts + [rpts[0]])


def test_volume_directional_rotated_rect_east():
    client = TestClient(app)
    # Rotated rectangle ~30 deg, size 20x10 centered at origin
    poly = make_rotated_rect(0, 0, 20, 10, 30)
    payload = {
        "geometry": mapping(poly),
        "altura_maxima_m": 10,
        "setback_front_m": 3.0,   # front (east)
        "setback_back_m": 1.0,    # back (west)
        "setback_side_m": 0.5,    # other sides
        "front_direction": "east"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    feat = r.json()['feature']
    assert feat is not None
    props = feat['properties']
    assert props['setback_mode'] in ('rotated_rect_directional', 'rect_directional')
    # Area should be less than original (20*10=200) and positive
    assert 0 < props['area_m2'] < 200
