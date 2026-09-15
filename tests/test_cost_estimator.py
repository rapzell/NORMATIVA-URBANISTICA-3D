from fastapi.testclient import TestClient

from app.main import app
from src.cost_estimator import CostEstimateInput, estimate_conversion_costs

client = TestClient(app)


def test_full_cost_estimate_with_sale():
    result = estimate_conversion_costs({
        "superficie_util_m2": 50,
        "coste_obra_m2": 800,
        "coste_obra_fijo": 5000,
        "tasas_municipales": 300,
        "valor_venta_esperado": 120000,
        "fuente_costes": "Presupuesto estimado AC8",
    })
    assert result.coste_obra_total == 40000.0
    assert result.coste_total_inversion == 45300.0
    assert result.coste_por_m2_total == 906.0
    assert result.beneficio_bruto_venta == 74700.0
    assert result.roi_venta_pct == round(74700.0 / 45300.0 * 100, 2)


def test_rental_payback_calculation():
    result = estimate_conversion_costs({
        "superficie_util_m2": 45,
        "coste_obra_m2": 700,
        "valor_alquiler_mensual": 800,
    })
    assert result.coste_obra_total == 31500.0
    assert result.coste_total_inversion == 31500.0
    assert result.payback_alquiler_meses == round(31500.0 / 800, 1)
    assert result.rentabilidad_alquiler_anual_pct == round(800 * 12 / 31500 * 100, 2)


def test_missing_cost_per_m2_warns():
    result = estimate_conversion_costs({"superficie_util_m2": 50})
    assert result.coste_obra_total is None
    assert any("coste de obra por m" in w for w in result.advertencias)


def test_no_data_returns_warning():
    result = estimate_conversion_costs({})
    assert any("No hay suficientes datos" in w for w in result.advertencias)
    assert result.coste_obra_total is None
    assert result.coste_total_inversion is None


def test_limitations_are_explicit():
    result = estimate_conversion_costs({"superficie_util_m2": 50, "coste_obra_m2": 800})
    assert len(result.limitaciones) >= 3
    assert any("no son datos de mercado" in l.lower() for l in result.limitaciones)
    assert any("tasas municipales" in l.lower() for l in result.limitaciones)


def test_source_is_preserved():
    result = estimate_conversion_costs({"fuente_costes": "Base de precios 2024"})
    assert result.fuente_costes == "Base de precios 2024"


def test_api_returns_cost_estimate():
    response = client.post("/costes/estimar", json={
        "superficie_util_m2": 50,
        "coste_obra_m2": 800,
        "valor_venta_esperado": 120000,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["coste_obra_total"] == 40000.0
    assert data["beneficio_bruto_venta"] is not None
    assert len(data["limitaciones"]) >= 3


def test_api_rejects_negative_surface():
    response = client.post("/costes/estimar", json={"superficie_util_m2": -1})
    assert response.status_code == 422
