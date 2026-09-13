"""Tests de la vista GeoLibre (Fase 3)."""
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


def test_geolibre_index_serves_html():
    """La vista GeoLibre debe servir un HTML con MapLibre."""
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert "maplibre-gl" in body.lower()
    assert "planeamiento/subzonas" in body
    assert "zoning/assess" in body


def test_geolibre_index_has_maplibre_container():
    """El HTML debe tener el contenedor del mapa."""
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    assert 'id="map"' in resp.text


def test_geolibre_index_has_subzone_interaction():
    """El HTML debe tener logica de seleccion de subzonas."""
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    body = resp.text
    assert "selectSubzone" in body or "subzone" in body.lower()
    assert "loadSubzones" in body


def test_geolibre_index_has_assess_flow():
    """El HTML debe tener el flujo de evaluacion contra el backend."""
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    body = resp.text
    assert "assessParcel" in body
    assert "viability" in body
    assert "badge" in body


def test_geolibre_index_has_draw_mode():
    """El HTML debe tener el modo de dibujo de parcelas (Fase 4)."""
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    body = resp.text
    assert "toggleDrawMode" in body
    assert "finishDraw" in body
    assert "drawnParcel" in body
    assert "draw-panel" in body


def test_geolibre_index_has_draw_assess_flow():
    """El HTML debe conectar el dibujo con la evaluacion del backend."""
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    body = resp.text
    assert "assessDrawnParcel" in body
    assert "zoning/assess" in body
    assert "subzonas/lookup" in body


def test_geolibre_index_has_envelope_display():
    """El HTML debe mostrar la envolvente resultante sobre el mapa."""
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    body = resp.text
    assert "showEnvelopeOnMap" in body
    assert "drawn-result" in body
