import json
from urllib.error import HTTPError
from fastapi.testclient import TestClient
from app.main import app
import types

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert isinstance(j.get("version"), str)
    assert isinstance(j.get("time"), int)


def test_proxy_siose_amortize_4xx(monkeypatch):
    # Simula que el WFS externo responde 400 para que el proxy devuelva FeatureCollection vacío (200)
    def fake_urlopen(req, timeout=15):
        # urllib.error.HTTPError: (url, code, msg, hdrs, fp)
        raise HTTPError(url=getattr(req, 'full_url', 'http://fake'), code=400, msg='Bad Request', hdrs=None, fp=None)

    import urllib.request as _ur
    monkeypatch.setattr(_ur, 'urlopen', fake_urlopen, raising=True)

    r = client.get("/proxy/siose", params={
        'bbox': '-8.72,42.21,-8.70,42.23,EPSG:4326',
        'typeNames': 'elu:LandCoverUnit',
        'srsName': 'EPSG:4326',
        'version': '2.0.0'
    })
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, dict)
    assert j.get('type') == 'FeatureCollection'
    assert isinstance(j.get('features'), list)


def test_proxy_wmscap_amortize_4xx(monkeypatch):
    # Simula 400 para que el proxy responda XML mínimo (200)
    def fake_urlopen(req, timeout=15):
        raise HTTPError(url=getattr(req, 'full_url', 'http://fake'), code=404, msg='Not Found', hdrs=None, fp=None)

    import urllib.request as _ur
    monkeypatch.setattr(_ur, 'urlopen', fake_urlopen, raising=True)

    r = client.get("/proxy/wmscap", params={
        'url': 'https://mapas.xunta.gal/servizos/ows?service=WMS&request=GetCapabilities'
    })
    assert r.status_code == 200
    # Debe ser XML mínimo; no validamos estructura completa, solo tipo de contenido y comienzo de payload
    ctype = r.headers.get('content-type', '')
    assert 'xml' in ctype
    txt = r.text.strip()
    assert txt.startswith('<WMS_Capabilities')
