import os
import io
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app


def setup_module(module):
    # Avoid heavy loads at startup
    os.environ['API_LOAD_RESOURCES'] = '0'
    # Enable CSV provider for admin reload
    os.environ['PLAN_PROVIDER'] = 'csv'
    # Default CSV path (can be overridden per-test)
    root = Path(__file__).resolve().parents[1]
    sample_csv = root / 'datos' / 'planes_municipales_sample.csv'
    os.environ['PLAN_CSV_PATH'] = str(sample_csv)


def test_openapi_json_available():
    client = TestClient(app)
    r = client.get('/openapi.json')
    assert r.status_code == 200
    j = r.json()
    assert 'paths' in j
    # A key route is present
    assert '/admin/reload-plan' in j['paths']


def test_admin_reload_plan_accepts_json_body_and_works():
    client = TestClient(app)
    root = Path(__file__).resolve().parents[1]
    sample_csv = root / 'datos' / 'planes_municipales_sample.csv'
    assert sample_csv.exists(), 'Sample CSV must exist for this test'
    r = client.post('/admin/reload-plan', json={"path": str(sample_csv)})
    assert r.status_code == 200
    j = r.json()
    assert j.get('ok') is True
    assert j.get('provider') == 'csv'
    assert Path(j.get('applied_path')).name == sample_csv.name
    assert j.get('rows') and j['rows'] >= 1


def test_viewer_index_served_with_html_content_type():
    client = TestClient(app)
    r = client.get('/viewer')
    assert r.status_code == 200
    ctype = (r.headers.get('content-type') or '').lower()
    assert 'text/html' in ctype
    assert '<title>Visor 3D (GLTF/GLB) - Zoning</title>' in r.text


def test_static_js_and_wasm_content_types(tmp_path):
    # Create temporary assets under the mounted viewer directory
    root = Path(__file__).resolve().parents[1]
    viewer_dir = root / 'web' / 'examples' / 'threejs-viewer'
    temp_dir = viewer_dir / 'tmp_test_assets'
    temp_dir.mkdir(exist_ok=True)

    js_path = temp_dir / 'test.js'
    wasm_path = temp_dir / 'test.wasm'

    js_path.write_text('export const x = 1;\n')
    # Minimal bytes for wasm (not a valid wasm, but only type matters)
    wasm_path.write_bytes(b"\x00asm\x01\x00\x00\x00")

    client = TestClient(app)

    r_js = client.get('/viewer/tmp_test_assets/test.js')
    assert r_js.status_code == 200
    ctype_js = (r_js.headers.get('content-type') or '').lower()
    # Accept common JS types; prefer text/javascript due to explicit registration
    assert 'javascript' in ctype_js

    r_wasm = client.get('/viewer/tmp_test_assets/test.wasm')
    assert r_wasm.status_code == 200
    ctype_wasm = (r_wasm.headers.get('content-type') or '').lower()
    assert 'application/wasm' in ctype_wasm

    # Cleanup
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass
