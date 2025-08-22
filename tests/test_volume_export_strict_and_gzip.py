from fastapi.testclient import TestClient
from app.main import app
import json
import gzip


def _client():
    return TestClient(app)


def test_cityjson_strict_true_returns_400_when_envelope_none_and_non_strict_200():
    client = _client()
    # Polígono pequeño válido pero con retranqueo enorme que anula la envolvente (feature None)
    tiny = {
        "type": "Polygon",
        "coordinates": [
            [[0,0],[2,0],[2,2],[0,2],[0,0]]
        ]
    }
    payload = {"geometry": tiny, "altura_maxima_m": 5.0, "retranqueo_min_m": 100.0, "format": "cityjson"}
    r = client.post('/zoning/volume-export?strict=true', json=payload)
    assert r.status_code == 400
    # En modo no estricto debe aplicar fallback y devolver 200
    r2 = client.post('/zoning/volume-export', json=payload)
    assert r2.status_code == 200


def test_cityjson_download_gzip_payload_and_headers():
    client = _client()
    payload = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[0,0],[10,0],[10,10],[0,10],[0,0]]
            ]
        },
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 0.0,
        "format": "cityjson"
    }
    r = client.post('/zoning/volume-export?download=true&gzip=true', json=payload)
    assert r.status_code == 200
    # Check headers
    assert r.headers.get('Content-Type') == 'application/city+json'
    assert r.headers.get('Content-Disposition') and r.headers['Content-Disposition'].endswith('building.city.json.gz"')
    assert r.headers.get('Content-Encoding') == 'gzip'
    # Decompress and validate JSON
    raw = r.content
    # httpx puede decodificar automáticamente gzip; si falla la descompresión, usamos el contenido tal cual
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass
    obj = json.loads(raw.decode('utf-8'))
    assert isinstance(obj, dict)
    assert obj.get('type') == 'CityJSON'
