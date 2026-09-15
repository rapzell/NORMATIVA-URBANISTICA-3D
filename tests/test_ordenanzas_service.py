import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from src.ordenanzas_service import (
    ORDENANZAS_DIR,
    get_ordenanza_municipio,
    get_ordenanza_subzona,
    list_municipios_with_ordenanzas,
    _normalize_municipio,
)

client = TestClient(app)


@pytest.fixture
def temp_ordenanza(tmp_path, monkeypatch):
    """Crea una ordenanza temporal para un municipio de prueba."""
    muni_dir = tmp_path / "vigo"
    muni_dir.mkdir()
    ordenanza = {
        "municipio": "Vigo",
        "subzonas": {
            "U3": {
                "requisitos_cambio_uso": {
                    "superficie_minima_vivienda_m2": 40,
                    "altura_minima_m": 2.5,
                    "ventilacion": "un hueco por estancia",
                    "documentacion_especifica": ["estudio de soleamiento"],
                },
                "criterios_tecnicos_municipales": "Los técnicos exigen ventilación cruzada.",
                "plazo_estimado_tramitacion_dias": 90,
                "fuente": "Ordenanza municipal de Vigo, art. 45",
                "fecha_actualizacion": "2025-06-15",
            }
        },
        "requisitos_generales_licencia": {
            "documentacion": ["memoria", "planos"],
            "plazo_estimado_dias": 90,
            "fuente": "Ordenanza municipal de Vigo",
        },
        "fuente": "Ordenanza municipal de Vigo",
    }
    (muni_dir / "ordenanza.json").write_text(json.dumps(ordenanza), encoding="utf-8")
    monkeypatch.setattr("src.ordenanzas_service.ORDENANZAS_DIR", tmp_path)
    return ordenanza


def test_normalize_municipio_handles_accents():
    assert _normalize_municipio("A Coruña") == "a_coruna"
    assert _normalize_municipio("Vigo") == "vigo"
    assert _normalize_municipio("") == ""


def test_get_ordenanza_municipio_not_available():
    result = get_ordenanza_municipio("MunicipioInexistente")
    assert result["disponible"] is False
    assert "No hay ordenanzas cargadas" in result["mensaje"]
    assert result["subzonas"] == {}


def test_get_ordenanza_municipio_empty_name():
    result = get_ordenanza_municipio("")
    assert result["disponible"] is False
    assert result["municipio"] is None


def test_get_ordenanza_municipio_with_data(temp_ordenanza):
    result = get_ordenanza_municipio("Vigo")
    assert result["disponible"] is True
    assert "U3" in result["subzonas"]
    assert result["requisitos_generales_licencia"] is not None
    assert len(result["fuentes"]) >= 1


def test_get_ordenanza_subzona_with_data(temp_ordenanza):
    result = get_ordenanza_subzona("Vigo", "U3")
    assert result["disponible"] is True
    assert result["subzona"] == "U3"
    assert "ordenanza" in result
    assert result["ordenanza"]["requisitos_cambio_uso"]["superficie_minima_vivienda_m2"] == 40


def test_get_ordenanza_subzona_not_found(temp_ordenanza):
    result = get_ordenanza_subzona("Vigo", "ZONA_INEXISTENTE")
    assert result["disponible"] is True
    assert "No hay ordenanzas específicas" in result["mensaje"]
    assert "U3" in result["subzonas_disponibles"]


def test_list_municipios_with_ordenanzas(temp_ordenanza):
    municipios = list_municipios_with_ordenanzas()
    assert len(municipios) == 1
    assert "Vigo" in municipios[0]


def test_api_ordenanzas_municipios_empty():
    response = client.get("/ordenanzas/municipios")
    assert response.status_code == 200
    data = response.json()
    assert "municipios" in data


def test_api_ordenanzas_municipio_not_available():
    response = client.get("/ordenanzas/MunicipioInexistente")
    assert response.status_code == 200
    data = response.json()
    assert data["disponible"] is False


def test_api_ordenanzas_subzona_not_available():
    response = client.get("/ordenanzas/MunicipioInexistente/U3")
    assert response.status_code == 200
    data = response.json()
    assert data["disponible"] is False
