"""Tests de la vista GeoLibre simplificada."""
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
    resp = client.get("/geolibre/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_geolibre_index_has_maplibre():
    resp = client.get("/geolibre/")
    body = resp.text
    assert "maplibre-gl" in body.lower()


def test_geolibre_index_has_zone_buttons():
    """La vista debe tener botones de municipios."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "zone-btn" in body
    assert "goToMunicipio" in body
    assert "loadMunicipios" in body


def test_geolibre_index_has_3d_extrusion():
    """La vista debe tener edificios 3D extruidos."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "fill-extrusion" in body
    assert "proxy/osm-buildings" in body
    assert "toggle3D" in body


def test_geolibre_index_has_subzone_info():
    """La vista debe mostrar info normativa al clicar una subzona."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "selectSubzone" in body
    assert "selectBuilding" in body
    assert "fetchOfficialContext" in body
    assert "renderOfficialContext" in body
    assert "Afecciones preliminares" in body
    assert "info-panel" in body


def test_geolibre_index_has_building_tooltip():
    """La vista debe tener tooltip flotante para edificios."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "building-tooltip" in body
    assert "showBuildingTooltip" in body
    assert "hideBuildingTooltip" in body


def test_geolibre_index_has_subzone_tooltip_and_summary():
    """La vista debe tener tooltip de subzonas y resumen persistente en el mapa."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "showSubzoneTooltip" in body
    assert "map-summary" in body
    assert "updateMapSummary" in body


def test_geolibre_index_has_selection_and_stats():
    """La vista debe resaltar edificios seleccionados y mostrar estadísticas."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "selected-building" in body
    assert "updateSelectedBuilding" in body
    assert "renderMunicipioStats" in body


def test_geolibre_index_has_building_filters():
    """La vista debe permitir filtrar edificios por estado normativo."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "renderBuildingFilters" in body
    assert "setBuildingFilter" in body
    assert "applyBuildingFilter" in body
    assert "Filtro de edificios" in body
    assert "orientativo_dentro" in body
    assert "orientativo_supera" in body
    assert "no acreditan cumplimiento urbanístico" in body


def test_geolibre_index_has_assess_flow():
    """La vista debe tener el flujo de evaluacion contra el backend."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "assessSubzone" in body
    assert "zoning/assess" in body
    assert "badge" in body


def test_geolibre_index_has_flight_to_zone():
    """La vista debe volar al municipio seleccionado."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "flyTo" in body
    assert "MUNI_CENTERS" in body


def test_geolibre_index_has_afecciones_layer():
    """La vista debe tener toggle y carga de afecciones SIOSE."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "toggleAfecciones" in body
    assert "loadAfecciones" in body
    assert "afecciones-fill" in body
    assert "official/afecciones" in body


def test_geolibre_index_has_ifc_export():
    """La vista debe tener botones de exportación IFC."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "exportBuildingIFC" in body
    assert "exportSubzoneIFC" in body
    assert "Exportar IFC" in body
    assert "volume-export" in body


def test_geolibre_index_has_expanded_legend():
    """La vista debe tener leyenda para edificios, afecciones y sombras."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "Leyenda edificios 3D" in body
    assert "Leyenda afecciones" in body
    assert "Leyenda sombras" in body
    assert "sensible por agua" in body
    assert "sensible natural" in body
    assert "sombra proyectada" in body


def test_geolibre_index_has_shadow_slider():
    """La vista debe tener un slider de hora para sombras dinámicas."""
    resp = client.get("/geolibre/")
    body = resp.text
    assert "shadow-slider" in body
    assert "onShadowSliderChange" in body
    assert "shadow-controls" in body
    assert "updateShadowSliderInfo" in body


def test_geolibre_index_has_habitability_flow():
    resp = client.get("/geolibre/")
    body = resp.text
    assert "showHabitabilityForm" in body
    assert "submitHabitabilityCheck" in body
    assert "/habitabilidad/verificar" in body
    assert "Decreto 128/2023" in body
    assert "programa_declarado_completo" in body


def test_geolibre_index_has_official_source_links():
    """La vista debe tener código para renderizar enlaces a fuentes oficiales."""
    resp = client.get("/geolibre/")
    body = resp.text
    # El visor ahora recibe los enlaces dinámicamente desde el backend (official_links)
    assert "official_links" in body
    assert "Verificar en fuente oficial" in body
    assert "link.url" in body
    assert "link.label" in body
