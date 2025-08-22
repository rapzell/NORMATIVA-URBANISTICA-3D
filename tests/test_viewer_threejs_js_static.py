import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

ASSETS = [
    ('/viewer/lib/OrbitControls.js', os.path.join('web','examples','threejs-viewer','lib','OrbitControls.js')),
    ('/viewer/lib/GLTFLoader.js', os.path.join('web','examples','threejs-viewer','lib','GLTFLoader.js')),
]

@pytest.mark.parametrize('url,local_path', ASSETS)
def test_threejs_helpers_js_mime(url, local_path):
    if not os.path.exists(local_path):
        pytest.skip(f"Asset not present locally: {local_path}")
    client = TestClient(app)
    resp = client.get(url)
    assert resp.status_code == 200
    ctype = resp.headers.get('content-type','')
    assert ctype.startswith('text/javascript') or ctype.startswith('application/javascript'), ctype
