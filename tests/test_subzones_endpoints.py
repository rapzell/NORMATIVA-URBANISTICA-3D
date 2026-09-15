"""Tests del endpoint de subzonas espaciales (Fase 2 GeoLibre)."""
from __future__ import annotations

import io
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.main import app

client = TestClient(app)


def test_subzonas_devuelve_geojson_completo():
    resp = client.get("/planeamiento/subzonas")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 4


def test_subzonas_filtra_por_municipio():
    resp = client.get("/planeamiento/subzonas", params={"municipio": "Vigo"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 3
    subzonas = {feat["properties"]["subzona"] for feat in data["features"]}
    assert {"R-1", "R-2", "R-3"}.issubset(subzonas)
    for feat in data["features"]:
        assert feat["properties"]["municipio"] == "Vigo"


def test_subzonas_filtra_por_municipio_sin_acentos():
    """'A Coruña' debe encontrar las subzonas de 'A Coruna'."""
    resp = client.get("/planeamiento/subzonas", params={"municipio": "A Coruña"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["features"]) >= 2
    subzonas = {feat["properties"]["subzona"] for feat in data["features"]}
    assert {"UC-1", "UC-2"}.issubset(subzonas)
    for feat in data["features"]:
        assert feat["properties"]["municipio"] == "A Coruna"


def test_subzonas_municipios_lista():
    resp = client.get("/planeamiento/subzonas/municipios")
    assert resp.status_code == 200
    data = resp.json()
    assert "municipios" in data
    assert "Vigo" in data["municipios"]
    assert len(data["municipios"]) >= 3


def test_subzonas_lookup_punto_dentro():
    """Punto dentro de la subzona R-1 de Vigo."""
    resp = client.get("/planeamiento/subzonas/lookup", params={"lon": -8.72, "lat": 42.235})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert data["subzona"]["municipio"] == "Vigo"
    assert data["subzona"]["subzona"] == "R-1"


def test_subzonas_lookup_punto_fuera():
    """Punto fuera de cualquier subzona."""
    resp = client.get("/planeamiento/subzonas/lookup", params={"lon": 0.0, "lat": 0.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert data["subzona"] is None


def test_subzonas_tiene_propiedades_normativas():
    """Las features deben incluir parametros normativos para GeoLibre."""
    resp = client.get("/planeamiento/subzonas", params={"municipio": "Vigo"})
    data = resp.json()
    for feat in data["features"]:
        props = feat["properties"]
        assert "altura_maxima_m" in props
        assert "retranqueo_min_m" in props
        assert "subzona" in props
        assert "fuente" in props


def test_proxy_osm_buildings_returns_geojson(monkeypatch):
    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            payload = {
                "elements": [
                    {
                        "type": "way",
                        "id": 123,
                        "tags": {"building": "residential", "building:levels": "3"},
                        "geometry": [
                            {"lon": -8.72, "lat": 42.23},
                            {"lon": -8.719, "lat": 42.23},
                            {"lon": -8.719, "lat": 42.231},
                            {"lon": -8.72, "lat": 42.231},
                        ],
                    }
                ]
            }
            return json.dumps(payload).encode("utf-8")

    import src.subzones_service as _ss
    monkeypatch.setattr(_ss, "urlopen", lambda req, timeout=25: _FakeResp(), raising=True)

    resp = client.get("/proxy/osm-buildings", params={"municipio": "Vigo", "limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    props = data["features"][0]["properties"]
    assert props["building"] == "residential"
    assert props["height"] > 0
    assert props["_altura_visual"] == props["height"]
    assert "cumplimiento_altura" in props
    assert "cumplimiento_detalle" in props
    assert "color_semantica" in props
    assert "height_source" in props
    assert "height_estimated" in props
    assert props["normative_status"] == "pilot"
    assert props["cumplimiento_altura"] in ("orientativo_dentro", "orientativo_supera", "sin_dato")
