from fastapi.testclient import TestClient
from app.main import app
import struct


def _client():
    return TestClient(app)


def test_glb_download_and_magic_header():
    client = _client()
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[0,0],[2,0],[2,2],[0,2],[0,0]]
            ]
        },
        "altura_maxima_m": 5.0,
        "retranqueo_min_m": 0.0,
        "format": "glb"
    }
    r = client.post('/zoning/volume-export?download=true', json=payload)
    assert r.status_code == 200
    assert r.headers.get('Content-Type') == 'model/gltf-binary'
    assert r.headers.get('Content-Disposition', '').endswith('building.glb"')
    data = r.content
    # GLB header magic 'glTF' = 0x46546C67 little-endian
    magic, version, total_length = struct.unpack('<III', data[:12])
    assert magic == 0x46546C67
    assert version == 2
    assert total_length == len(data)


def test_glb_rejects_holes():
    client = _client()
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
        "format": "glb"
    }
    r = client.post('/zoning/volume-export', json=payload)
    assert r.status_code == 400
