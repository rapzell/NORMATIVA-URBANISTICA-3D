from fastapi.testclient import TestClient
from app.main import app


def test_draco_decoder_wasm_served_with_correct_type():
    client = TestClient(app)
    r = client.get('/viewer/lib/draco/draco_decoder.wasm')
    assert r.status_code == 200
    ctype = (r.headers.get('content-type') or '').lower()
    assert 'application/wasm' in ctype
