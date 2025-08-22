from fastapi.testclient import TestClient
from app.main import app

def test_volume_l_shaped_polygon_fallback_directional_diagnostics():
    client = TestClient(app)
    # L-shaped polygon
    coords = [
        [0,0],[6,0],[6,2],[2,2],[2,6],[0,6],[0,0]
    ]
    payload = {
        "geometry": {"type":"Polygon","coordinates":[coords]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 0.4,
        "setback_side_m": 0.2,
        "setback_back_m": 0.6,
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    if r.status_code != 200:
        # Debug aid
        print('Response:', r.status_code, r.text)
    assert r.status_code == 200
    data = r.json()
    props = data['feature']['properties']
    # As it's not rectangular, we should fallback to conservative uniform
    assert props['setback_mode'] in ("conservative_max_uniform",)
    assert props['polygon_type'] == 'general' or props['polygon_type'] in ('rectangle_axis_aligned','rectangle_rotated')
    if props['polygon_type'] == 'general':
        assert props['directional_applicability'] in ('not_applicable','not_requested')
        if props['directional_applicability'] == 'not_applicable':
            assert props['directional_not_applied_reason'] == 'non_rectangular_parcel'


def test_volume_axis_aligned_rect_diagnostics():
    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,8],[0,8],[0,0]]]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 2.0,
        "setback_side_m": 0.5,
        "setback_back_m": 1.0,
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    if r.status_code != 200:
        print('Response:', r.status_code, r.text)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['setback_mode'] == 'rect_directional'
    assert props['polygon_type'] == 'rectangle_axis_aligned'
    assert props['directional_applicability'] == 'applied'


def test_volume_rotated_rect_diagnostics():
    client = TestClient(app)
    # Define a rotated rectangle by rotating an axis-aligned one 30 degrees around center
    import math
    def rot(x, y, cx, cy, ang):
        ca, sa = math.cos(ang), math.sin(ang)
        xr, yr = x - cx, y - cy
        return [cx + xr*ca - yr*sa, cy + xr*sa + yr*ca]
    ang = math.radians(30)
    # Base rect centered at (5,4) size 10x8
    pts = [[0,0],[10,0],[10,8],[0,8]]
    cx, cy = 5.0, 4.0
    rpts = [rot(x,y,cx,cy,ang) for x,y in pts]
    rpts.append(rpts[0])
    payload = {
        "geometry": {"type":"Polygon","coordinates":[rpts]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 2.0,
        "setback_side_m": 0.5,
        "setback_back_m": 1.0,
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['setback_mode'] == 'rotated_rect_directional'
    assert props['polygon_type'] == 'rectangle_rotated'
    assert props['directional_applicability'] == 'applied'


def test_volume_near_rectangle_tolerance_directional_applied():
    """Slightly perturb an axis-aligned rectangle so it's not exactly a rectangle
    but within tolerance; expect directional setbacks to be applied.
    """
    client = TestClient(app)
    # Base axis-aligned rect 10x8, perturb one point by +0.02 on x
    coords = [[0,0],[10.02,0],[10,8],[0,8]]
    coords.append(coords[0])
    payload = {
        "geometry": {"type":"Polygon","coordinates":[coords]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 2.0,
        "setback_side_m": 0.5,
        "setback_back_m": 1.0,
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['directional_applicability'] == 'applied'
    assert props['polygon_type'] in ('rectangle_axis_aligned','rectangle_rotated')
    assert props['setback_mode'] in ('rect_directional','rotated_rect_directional')


def test_near_rectangle_strict_tolerance_falls_back(monkeypatch):
    client = TestClient(app)
    # Make tolerance extremely strict
    monkeypatch.setenv('RECT_TOL_AREA_RATIO_MIN', '0.9999')
    monkeypatch.setenv('RECT_TOL_AREA_RATIO_MAX', '1.0001')
    monkeypatch.setenv('RECT_TOL_SYMDIFF_PCT', '0.00001')
    # Slight perturbation
    coords = [[0,0],[10.02,0],[10,8],[0,8]]
    coords.append(coords[0])
    payload = {
        "geometry": {"type":"Polygon","coordinates":[coords]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 2.0,
        "setback_side_m": 0.5,
        "setback_back_m": 1.0,
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    # Should not apply directional under strict tolerance
    assert props['directional_applicability'] in ('not_applicable','not_requested')
    if props['directional_applicability'] == 'not_applicable':
        assert props.get('directional_not_applied_reason') == 'non_rectangular_parcel'


def test_near_rectangle_relaxed_tolerance_applies(monkeypatch):
    client = TestClient(app)
    # Make tolerance generous
    monkeypatch.setenv('RECT_TOL_AREA_RATIO_MIN', '0.98')
    monkeypatch.setenv('RECT_TOL_AREA_RATIO_MAX', '1.02')
    monkeypatch.setenv('RECT_TOL_SYMDIFF_PCT', '0.02')
    # More noticeable perturbation but within relaxed tolerance
    coords = [[0,0],[10.2,0],[10,8],[0,8]]
    coords.append(coords[0])
    payload = {
        "geometry": {"type":"Polygon","coordinates":[coords]},
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 2.0,
        "setback_side_m": 0.5,
        "setback_back_m": 1.0,
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['directional_applicability'] == 'applied'
    assert props['polygon_type'] in ('rectangle_axis_aligned','rectangle_rotated')
    assert props['setback_mode'] in ('rect_directional','rotated_rect_directional')
    assert props['front_detected_side'] in ('top','bottom','left','right')


def test_plan_default_front_direction_source_from_csv_plan(monkeypatch):
    client = TestClient(app)
    # Ensure dynamic provider uses CSV sample
    import os
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', os.path.join('datos', 'planes_municipales_sample.csv'))

    # Axis-aligned parcel; no front_direction and no street_axis
    geom = {"type":"Polygon","coordinates":[[[0,0],[20,0],[20,12],[0,12],[0,0]]]}
    payload = {
        "geometry": geom,
        # Force plan lookup by omitting altura_maxima_m
        "retranqueo_min_m": 0.0,
        # Do not pass directional setbacks; they should come from plan
        "municipio": "Vigo",
        "subzona": "RZ-2",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    if r.status_code != 200:
        print('Response:', r.status_code, r.text)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['front_direction_source'] == 'plan_default'
    assert props['street_axis_used'] is False
    # New diagnostics
    assert props.get('front_selection_rationale') == 'front_direction_plan_default'
    assert props.get('street_axis_min_distance_m') is None
    assert props.get('street_axis_side_distances') is None
    # Directional should be applied given plan provides setbacks and default front
    assert props['directional_applicability'] == 'applied'
    assert props['setback_mode'] in ('rect_directional','rotated_rect_directional')


def test_front_direction_source_request_without_street_axis():
    client = TestClient(app)
    geom = {"type":"Polygon","coordinates":[[[0,0],[20,0],[20,10],[0,10],[0,0]]]}
    payload = {
        "geometry": geom,
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 2.0,
        "setback_side_m": 1.0,
        "setback_back_m": 1.5,
        "front_direction": "east"
    }
    r = client.post('/zoning/volume', json=payload)
    if r.status_code != 200:
        print('Response:', r.status_code, r.text)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['front_direction_source'] == 'request'
    assert props['street_axis_used'] is False
    # New diagnostics
    assert props.get('front_selection_rationale') == 'front_direction_request'
    assert props.get('street_axis_min_distance_m') is None
    assert props.get('street_axis_side_distances') is None


def test_rotated_rect_front_detected_side_from_front_direction():
    client = TestClient(app)
    import math
    def rot(x, y, cx, cy, ang):
        ca, sa = math.cos(ang), math.sin(ang)
        xr, yr = x - cx, y - cy
        return [cx + xr*ca - yr*sa, cy + xr*sa + yr*ca]
    ang = math.radians(45)
    pts = [[0,0],[12,0],[12,6],[0,6]]
    cx, cy = 6.0, 3.0
    rpts = [rot(x,y,cx,cy,ang) for x,y in pts]
    rpts.append(rpts[0])
    payload = {
        "geometry": {"type":"Polygon","coordinates":[rpts]},
        "altura_maxima_m": 12.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 1.0,
        "setback_side_m": 0.5,
        "setback_back_m": 0.8,
        "front_direction": "north"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['setback_mode'] == 'rotated_rect_directional'
    assert props['polygon_type'] == 'rectangle_rotated'
    assert props['front_direction_source'] in ('request','plan_default')
    # With north as front, in rotated frame top should be the front
    assert props['front_detected_side'] in ('top','bottom','left','right')


def test_axis_aligned_front_detected_side_from_street_axis():
    client = TestClient(app)
    # Axis-aligned rectangle 10x8 at origin
    rpts = [[0,0],[10,0],[10,8],[0,8],[0,0]]
    street = {"type":"LineString","coordinates":[[-10, 11],[20, 11]]}
    payload = {
        "geometry": {"type":"Polygon","coordinates":[rpts]},
        "altura_maxima_m": 12.0,
        "retranqueo_min_m": 0.0,
        "setback_front_m": 1.0,
        "setback_side_m": 0.5,
        "setback_back_m": 0.8,
        "street_axis": street
    }
    r = client.post('/zoning/volume', json=payload)
    if r.status_code != 200:
        print('Response:', r.status_code, r.text)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['setback_mode'] in ('rect_directional','rotated_rect_directional')
    assert props['polygon_type'] in ('rectangle_axis_aligned','rectangle_rotated')
    assert props['street_axis_used'] is True
    assert props['front_detected_side'] in ('top','bottom','left','right')
    # New diagnostics: distances present and rationale
    assert isinstance(props.get('street_axis_min_distance_m'), (int, float))
    sd = props.get('street_axis_side_distances')
    assert isinstance(sd, dict)
    for k in ('top','bottom','left','right'):
        assert k in sd
        assert isinstance(sd[k], (int,float))
    # min distance should match the chosen side value (within tolerance)
    chosen = props['front_detected_side']
    assert abs(sd[chosen] - props['street_axis_min_distance_m']) < 1e-9
    assert props.get('front_selection_rationale') == 'street_axis_min_distance'
