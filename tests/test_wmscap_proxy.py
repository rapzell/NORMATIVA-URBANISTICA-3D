import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_wmscap_proxy_smoke():
    # OWS genérico de Xunta (puede cambiar). Si falla, hacemos skip para evitar falsos negativos.
    url = "https://mapas.xunta.gal/servizos/ows?service=WMS&request=GetCapabilities"
    try:
        r = client.get("/proxy/wmscap", params={"url": url})
    except Exception:
        pytest.skip("Proxy /proxy/wmscap no disponible o error de entorno")
        return
    if r.status_code != 200:
        pytest.skip(f"WMS capabilities respondió {r.status_code}")
    ctype = r.headers.get("content-type", "").lower()
    assert "xml" in ctype or "text" in ctype
    assert r.text.strip().startswith("<?xml") or "WMT_MS_Capabilities" in r.text or "WMS_Capabilities" in r.text
