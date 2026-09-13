"""Tests del endpoint de subzonas espaciales (Fase 2 GeoLibre)."""
from __future__ import annotations

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
    assert len(data["features"]) == 2
    for feat in data["features"]:
        assert feat["properties"]["municipio"] == "Vigo"


def test_subzonas_filtra_por_municipio_sin_acentos():
    """'A Coruña' debe encontrar las subzonas de 'A Coruna'."""
    resp = client.get("/planeamiento/subzonas", params={"municipio": "A Coruña"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["municipio"] == "A Coruna"


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
