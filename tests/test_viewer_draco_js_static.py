import os
import mimetypes
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.skipif(
    not os.path.exists(os.path.join('web', 'examples', 'threejs-viewer', 'lib', 'draco', 'draco_decoder.js')),
    reason="DRACO JS asset not present in local /viewer/lib path"
)
def test_draco_decoder_js_served_with_js_mime():
    client = TestClient(app)
    resp = client.get('/viewer/lib/draco/draco_decoder.js')
    assert resp.status_code == 200
    ctype = resp.headers.get('content-type', '')
    # Accept common JS MIME types and optional charset
    ok_types = (
        'text/javascript',
        'application/javascript',
    )
    assert any(ctype.startswith(t) for t in ok_types), f"Unexpected content-type: {ctype}"
