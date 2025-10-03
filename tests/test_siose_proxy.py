import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_proxy_siose_smoke_bbox():
    # BBOX pequeño sobre Vigo aprox (EPSG:4326): minx,miny,maxx,maxy
    bbox = "-8.74,42.20,-8.70,42.24"
    try:
        r = client.get(f"/proxy/siose?bbox={bbox}")
    except Exception:
        pytest.skip("Proxy SIOSE no disponible en entorno de tests")
        return
    if r.status_code != 200:
        pytest.skip(f"SIOSE respondió {r.status_code}")
    data = r.json()
    assert isinstance(data, dict)
    assert data.get("type") == "FeatureCollection"
    # No exigimos mínimo de features por variabilidad de servicio/red
