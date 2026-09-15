"""Estimación preliminar de costes de conversión de local a vivienda.

Calculadora basada en inputs del usuario: no inventa precios de mercado
ni costes por m². El profesional o propietario aporta los valores, y el
módulo calcula el investimento total, beneficio bruto y ROI.

Limitaciones explícitas:
- Los costes por m² y valores de venta/alquiler son aportados por el usuario.
- No sustituye un presupuesto real de obra ni una tasación oficial.
- Las tasas municipales deben verificarse con el ayuntamiento correspondiente.
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class CostEstimateInput(BaseModel):
    superficie_util_m2: float | None = Field(default=None, gt=0)
    coste_obra_m2: float | None = Field(default=None, gt=0, description="Coste de obra por m² aportado por el profesional")
    coste_obra_fijo: float | None = Field(default=None, ge=0, description="Coste fijo adicional (licencias, honorarios, etc.)")
    tasas_municipales: float | None = Field(default=None, ge=0, description="Tasas de licencia del ayuntamiento")
    valor_venta_esperado: float | None = Field(default=None, ge=0, description="Valor de venta esperado de la vivienda resultante")
    valor_alquiler_mensual: float | None = Field(default=None, ge=0, description="Valor de alquiler mensual esperado")
    municipio: str | None = None
    fuente_costes: str | None = Field(default=None, description="Fuente de los costes aportados (presupuesto, base de precios, etc.)")


class CostEstimateResult(BaseModel):
    coste_obra_total: float | None
    coste_total_inversion: float | None
    coste_por_m2_total: float | None
    beneficio_bruto_venta: float | None
    roi_venta_pct: float | None
    payback_alquiler_meses: float | None
    rentabilidad_alquiler_anual_pct: float | None
    advertencias: list[str]
    fuente_costes: str | None
    limitaciones: list[str]


def estimate_conversion_costs(data: CostEstimateInput | dict[str, Any]) -> CostEstimateResult:
    """Calcula costes y rentabilidad preliminar de una conversión.

    Todos los valores son aportados por el usuario; el módulo no inventa precios.
    Los campos faltantes se omiten (no se asume cero).
    """
    if isinstance(data, dict):
        data = CostEstimateInput.model_validate(data)

    warnings: list[str] = []
    limitations = [
        "Los costes y valores son aportados por el usuario; no son datos de mercado verificados.",
        "No sustituye un presupuesto real de obra ni una tasación oficial.",
        "Las tasas municipales deben verificarse con el ayuntamiento correspondiente.",
    ]

    coste_obra_total = None
    if data.superficie_util_m2 is not None and data.coste_obra_m2 is not None:
        coste_obra_total = round(data.superficie_util_m2 * data.coste_obra_m2, 2)
    elif data.superficie_util_m2 is not None and data.coste_obra_m2 is None:
        warnings.append("Falta el coste de obra por m² para calcular el coste total de obra.")

    coste_total_inversion = None
    components = []
    if coste_obra_total is not None:
        components.append(coste_obra_total)
    if data.coste_obra_fijo is not None:
        components.append(data.coste_obra_fijo)
    if data.tasas_municipales is not None:
        components.append(data.tasas_municipales)
    if components:
        coste_total_inversion = round(sum(components), 2)

    coste_por_m2_total = None
    if coste_total_inversion is not None and data.superficie_util_m2 is not None and data.superficie_util_m2 > 0:
        coste_por_m2_total = round(coste_total_inversion / data.superficie_util_m2, 2)

    beneficio_bruto_venta = None
    roi_venta_pct = None
    if data.valor_venta_esperado is not None and coste_total_inversion is not None:
        beneficio_bruto_venta = round(data.valor_venta_esperado - coste_total_inversion, 2)
        if coste_total_inversion > 0:
            roi_venta_pct = round((beneficio_bruto_venta / coste_total_inversion) * 100, 2)

    payback_alquiler_meses = None
    rentabilidad_alquiler_anual_pct = None
    if data.valor_alquiler_mensual is not None and data.valor_alquiler_mensual > 0:
        if coste_total_inversion is not None:
            payback_alquiler_meses = round(coste_total_inversion / data.valor_alquiler_mensual, 1)
        rentabilidad_alquiler_anual_pct = round((data.valor_alquiler_mensual * 12 / coste_total_inversion) * 100, 2) if coste_total_inversion and coste_total_inversion > 0 else None

    if not any(v is not None for v in [coste_obra_total, coste_total_inversion, beneficio_bruto_venta, payback_alquiler_meses]):
        warnings.append("No hay suficientes datos para calcular ninguna estimación.")

    return CostEstimateResult(
        coste_obra_total=coste_obra_total,
        coste_total_inversion=coste_total_inversion,
        coste_por_m2_total=coste_por_m2_total,
        beneficio_bruto_venta=beneficio_bruto_venta,
        roi_venta_pct=roi_venta_pct,
        payback_alquiler_meses=payback_alquiler_meses,
        rentabilidad_alquiler_anual_pct=rentabilidad_alquiler_anual_pct,
        advertencias=warnings,
        fuente_costes=data.fuente_costes,
        limitaciones=limitations,
    )
