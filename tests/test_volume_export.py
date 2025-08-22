import os
from fastapi.testclient import TestClient
from app.main import app


def setup_module(module):
    # speed up startup
    os.environ['API_LOAD_RESOURCES'] = '0'


def _client():
    return TestClient(app)


def test_cityjson_polygon_with_hole_exports_top_with_hole():
    client = _client()
    # square 10x10 with inner hole 4x4
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[0,0],[10,0],[10,10],[0,10],[0,0]],
                [[3,3],[7,3],[7,7],[3,7],[3,3]]
            ]
        },
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "format": "cityjson"
    }
    r = client.post('/zoning/volume-export', json=payload)
    assert r.status_code == 200
    cj = r.json()
    assert cj.get('type') == 'CityJSON'
    assert isinstance(cj.get('vertices'), list) and len(cj['vertices']) > 0
    co = cj['CityObjects']['building-1']
    geoms = co['geometry']
    assert isinstance(geoms, list) and len(geoms) == 1
    solid = geoms[0]
    assert solid['type'] == 'Solid'
    # boundaries: [ [surfaces...] ] ; surfaces[0] is top, which should include outer+hole loops
    boundaries = solid['boundaries']
    assert isinstance(boundaries, list) and len(boundaries) == 1
    surfaces = boundaries[0]
    assert isinstance(surfaces, list) and len(surfaces) >= 2  # top and bottom at least
    top = surfaces[0]
    assert isinstance(top, list) and len(top) == 2  # outer + 1 hole


def test_cityjson_multipolygon_exports_multiple_solids():
    client = _client()
    payload = {
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [
                [ [[0,0],[2,0],[2,2],[0,2],[0,0]] ],
                [ [[5,5],[7,5],[7,7],[5,7],[5,5]] ]
            ]
        },
        "altura_maxima_m": 5.0,
        "retranqueo_min_m": 0.0,
        "format": "cityjson"
    }
    r = client.post('/zoning/volume-export', json=payload)
    assert r.status_code == 200
    cj = r.json()
    geoms = cj['CityObjects']['building-1']['geometry']
    assert len(geoms) == 2
    assert all(g['type'] == 'Solid' for g in geoms)


essages = (
    "GLTF should reject polygons with holes"
)

def test_gltf_rejects_holes():
    client = _client()
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[0,0],[10,0],[10,10],[0,10],[0,0]],
                [[3,3],[7,3],[7,7],[3,7],[3,3]]
            ]
        },
        "altura_maxima_m": 8.0,
        "retranqueo_min_m": 0.0,
        "format": "gltf"
    }
    r = client.post('/zoning/volume-export', json=payload)
    # Expect 400 Bad Request due a limitación documentada
    assert r.status_code == 400
