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
    subzonas = {feat["properties"]["subzona_piloto"] for feat in data["features"]}
    assert {"R-1", "R-2", "R-3"}.issubset(subzonas)
    for feat in data["features"]:
        assert feat["properties"]["municipio"] == "Vigo"
        assert feat["properties"]["normative_status"] == "pilot"
        assert "subzona" not in feat["properties"]


def test_subzonas_filtra_por_municipio_sin_acentos():
    """'A Coruña' debe encontrar las subzonas de 'A Coruna'."""
    resp = client.get("/planeamiento/subzonas", params={"municipio": "A Coruña"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["features"]) >= 2
    subzonas = {feat["properties"]["subzona_piloto"] for feat in data["features"]}
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
    """Punto dentro de la subzona piloto UC-1 (A Coruña no tiene capa
    oficial configurada → cae al piloto etiquetado)."""
    resp = client.get("/planeamiento/subzonas/lookup",
                      params={"lon": -8.40, "lat": 43.37})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert data["subzona"]["municipio"] == "A Coruna"
    assert data["subzona"]["subzona_piloto"] == "UC-1"
    assert data["subzona"]["normative_status"] == "pilot"
    assert "subzona" not in data["subzona"] or \
        data["subzona"].get("subzona") is None


def test_subzonas_lookup_municipio_con_capa(monkeypatch):
    """En un municipio con capa oficial el lookup la consulta primero;
    un hueco de cobertura devuelve indisponible, nunca el piloto."""
    import src.subzones_service as _ss
    monkeypatch.setattr(
        _ss, "_ordenanza_municipal_punto",
        lambda lon, lat, municipio: {
            "subzona": None, "municipio": municipio,
            "normative_status": "unavailable",
            "nota": "Punto fuera de la capa de ordenanzas SUC"})
    resp = client.get("/planeamiento/subzonas/lookup",
                      params={"lon": -8.72, "lat": 42.235,
                              "municipio": "Vigo"})
    data = resp.json()
    assert data["found"] is True
    assert data["subzona"]["normative_status"] == "unavailable"
    assert data["subzona"].get("subzona") is None
    assert "subzona_piloto" not in data["subzona"]


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
        assert "subzona_piloto" in props
        assert "subzona" not in props
        assert props["normative_status"] == "pilot"
        assert "fuente" in props


def _fake_overpass():
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
    return lambda req, timeout=25: _FakeResp()


def _osm_test(monkeypatch, ordenanza_result):
    """Cablea Overpass falso + resolución de ordenanza + cachés limpias."""
    import src.subzones_service as _ss
    monkeypatch.setattr(_ss, "urlopen", _fake_overpass(), raising=True)
    monkeypatch.setattr(_ss, "_ordenanza_municipal_punto",
                        lambda lon, lat, municipio: ordenanza_result)
    _ss._OVERPASS_CACHE.clear()
    monkeypatch.setattr(_ss, "_overpass_disk_read",
                        lambda muni_key, limit: None)
    monkeypatch.setattr(_ss, "_overpass_disk_write",
                        lambda muni_key, limit, data: None)


def test_proxy_osm_buildings_returns_geojson(monkeypatch):
    # Sin capa oficial → cae al piloto etiquetado (nunca como 'subzona')
    _osm_test(monkeypatch, None)

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
    assert props["subzona"] is None
    assert props["subzona_piloto"] is not None
    assert props["cumplimiento_altura"] in ("orientativo_dentro", "orientativo_supera", "sin_dato")


def test_proxy_osm_buildings_subzona_oficial(monkeypatch):
    """Con capa oficial, el edificio lleva la ordenanza real en
    'subzona' — nunca un código piloto."""
    _osm_test(monkeypatch, {
        "subzona": "U1.1", "ordenanza": "U1",
        "titulo": "MANTEMENTO DA EDIFICACIÓN EXISTENTE",
        "municipio": "Vigo",
        "normative_status": "official",
        "fuente": "GeoServer municipal Concello de Vigo",
        "instrumento": "capa 4ordsuc",
        "altura_maxima_m": 7.0,
    })

    resp = client.get("/proxy/osm-buildings",
                      params={"municipio": "Vigo", "limit": 10})
    assert resp.status_code == 200
    props = resp.json()["features"][0]["properties"]
    assert props["subzona"] == "U1.1"
    assert props["ordenanza"] == "U1"
    assert props["normative_status"] == "official"
    assert props["subzona_piloto"] is None


def test_proxy_osm_buildings_hueco_cobertura(monkeypatch):
    """Punto fuera de la capa oficial → indisponible, sin piloto."""
    _osm_test(monkeypatch, {
        "subzona": None, "municipio": "Vigo",
        "normative_status": "unavailable",
        "fuente": "GeoServer municipal Concello de Vigo",
        "nota": "Punto fuera de la capa de ordenanzas SUC"})

    resp = client.get("/proxy/osm-buildings",
                      params={"municipio": "Vigo", "limit": 10})
    assert resp.status_code == 200
    props = resp.json()["features"][0]["properties"]
    assert props["subzona"] is None
    assert props["subzona_piloto"] is None
    assert props["normative_status"] == "unavailable"


def test_classify_supera_cornisa_dentro_tope_absoluto():
    """Altura medida entre la cornisa y el tope absoluto → supera_cornisa
    (la cubierta/baixocuberta puede ocupar el margen, art. 62.6)."""
    from src.subzones_service import _classify_building_compliance
    props = {"subzona": "U6.6", "normative_status": "official",
             "altura_maxima_m": 7.0, "altura_absoluta_m": 8.5}
    comp = _classify_building_compliance(8.0, props)
    assert comp["status"] == "supera_cornisa"
    assert "8.5" in comp["detail"] or "8,5" in comp["detail"]


def test_classify_supera_tope_absoluto_sigue_siendo_supera_altura():
    """Superar también el tope absoluto sigue siendo supera_altura,
    con el detalle citando ambos límites."""
    from src.subzones_service import _classify_building_compliance
    props = {"subzona": "U6.6", "normative_status": "official",
             "altura_maxima_m": 7.0, "altura_absoluta_m": 8.5}
    comp = _classify_building_compliance(9.0, props)
    assert comp["status"] == "supera_altura"
    assert "tope absoluto" in comp["detail"]


def test_classify_sin_tope_absoluto_mantiene_supera_altura():
    """Ordenanza sin tope absoluto → comportamiento original."""
    from src.subzones_service import _classify_building_compliance
    props = {"subzona": "U5", "normative_status": "official",
             "altura_maxima_m": 10.5}
    comp = _classify_building_compliance(12.0, props)
    assert comp["status"] == "supera_altura"
