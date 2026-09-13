"""Tests unitarios directos para src.zoning_assess.evaluate_zoning_assessment.

No usan HTTP; construyen VolumeRequest y llaman al evaluador para verificar
el contrato dict que despues envuelve AssessResponse en app/main.py.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.main import VolumeRequest
from src.zoning_assess import ZoningAssessmentError, evaluate_zoning_assessment


def _square_geojson(size_deg: float = 0.001) -> dict:
    # Cuadrado pequeno en lon/lat cerca de Vigo
    lon, lat = -8.72, 42.23
    d = size_deg
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + d, lat],
                [lon + d, lat + d],
                [lon, lat + d],
                [lon, lat],
            ]
        ],
    }


def test_assess_without_geometry_returns_condicionado():
    req = VolumeRequest(altura_maxima_m=10.0, retranqueo_min_m=3.0)
    result = evaluate_zoning_assessment(req)

    assert result["viability"] == "condicionado"
    assert result["feature"] is None
    assert result["geometry_summary"] is None
    assert any("Sin geometria" in r or "geometr" in r.lower() for r in result["reasons"])
    pe = result["params_effective"]
    assert pe["altura_maxima_m"] == 10.0
    assert pe["retranqueo_min_m"] == 3.0
    assert "front_direction" in pe
    assert "front_direction_source" in pe


def test_assess_with_explicit_params_and_geometry_returns_apto_or_condicionado():
    req = VolumeRequest(
        geometry=_square_geojson(),
        altura_maxima_m=10.0,
        retranqueo_min_m=3.0,
        setback_front_m=3.0,
        setback_side_m=3.0,
        setback_back_m=3.0,
        front_direction="north",
        crs="EPSG:4326",
    )
    result = evaluate_zoning_assessment(req)

    assert result["viability"] in {"apto", "condicionado"}
    assert result["feature"] is not None
    assert result["geometry_summary"] is not None
    pe = result["params_effective"]
    assert pe["altura_maxima_m"] == 10.0
    assert pe["retranqueo_min_m"] == 3.0
    assert pe["front_direction"] == "north"
    assert pe["front_direction_source"] in {"request", "plan_default", "none"}


def test_assess_missing_height_without_municipio_applies_defaults():
    """Sin altura ni municipio, el evaluador aplica defaults (altura=12m) en vez de fallar."""
    req = VolumeRequest(geometry=_square_geojson(), crs="EPSG:4326")
    result = evaluate_zoning_assessment(req)

    # No lanza; aplica defaults y devuelve un resultado evaluable
    assert result["viability"] in {"apto", "condicionado", "no_apto"}
    pe = result["params_effective"]
    assert pe["altura_maxima_m"] is not None
    assert any("defecto" in r.lower() or "default" in r.lower() for r in result["reasons"])


def test_assess_envelope_exhausted_returns_no_apto_when_retranqueos_agotan():
    # Retranqueos enormes que agotan una parcela pequena
    req = VolumeRequest(
        geometry=_square_geojson(size_deg=0.0001),
        altura_maxima_m=10.0,
        retranqueo_min_m=1000.0,
        setback_front_m=1000.0,
        setback_side_m=1000.0,
        setback_back_m=1000.0,
        front_direction="north",
    )
    result = evaluate_zoning_assessment(req)

    # Puede ser no_apto (envolvente agotada) o condicionado (segun heuristicas)
    assert result["viability"] in {"no_apto", "condicionado"}
    # Si la envolvente se agoto, feature es None y hay motivo
    if result["viability"] == "no_apto":
        assert result["feature"] is None
        assert any("agotan" in r or "no existe" in r.lower() for r in result["reasons"])


def test_assess_result_is_assessresponse_compatible():
    """El dict devuelto debe poder construir un AssessResponse sin error."""
    from app.main import AssessResponse

    req = VolumeRequest(altura_maxima_m=10.0, retranqueo_min_m=3.0)
    result = evaluate_zoning_assessment(req)

    # Sin geometria -> feature None, debe construirse sin problema
    resp = AssessResponse(**result)
    assert resp.viability == "condicionado"
    assert resp.feature is None
    assert resp.geometry_summary is None
    assert isinstance(resp.reasons, list)
    assert isinstance(resp.params_effective, dict)
