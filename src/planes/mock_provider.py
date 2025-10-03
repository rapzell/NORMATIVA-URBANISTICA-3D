from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class PlanParams(BaseModel):
    municipio: str
    subzona: Optional[str] = None
    altura_maxima_m: Optional[float] = None
    retranqueo_min_m: Optional[float] = None
    ocupacion_max: Optional[float] = None  # 0..1
    edificabilidad_max_m2_m2: Optional[float] = None


def get_plan_params(municipio: str, subzona: Optional[str] = None) -> PlanParams:
    """Proveedor mock de planeamiento municipal.
    Devuelve parámetros predefinidos para pruebas. En producción, esto consultaría
    una base de datos o ficheros del plan general/planeamiento.
    """
    m = (municipio or '').strip().lower()
    s = (subzona or '').strip().lower() or None

    # Ejemplos ficticios
    if m == 'vigo':
        if s in (None, 'rz-1', 'residencial_general'):
            return PlanParams(
                municipio=municipio,
                subzona=subzona,
                altura_maxima_m=15.0,
                retranqueo_min_m=3.0,
                ocupacion_max=0.4,
                edificabilidad_max_m2_m2=1.2,
            )
        if s == 'rz-2':
            return PlanParams(
                municipio=municipio,
                subzona=subzona,
                altura_maxima_m=12.0,
                retranqueo_min_m=3.0,
                ocupacion_max=0.35,
                edificabilidad_max_m2_m2=0.9,
            )
        if s == 'u7':
            return PlanParams(
                municipio=municipio,
                subzona=subzona,
                altura_maxima_m=9.0,
                retranqueo_min_m=3.0,
                ocupacion_max=0.35,
                edificabilidad_max_m2_m2=1.0,
            )
        if s == 'u10':
            return PlanParams(
                municipio=municipio,
                subzona=subzona,
                altura_maxima_m=8.0,
                retranqueo_min_m=3.0,
                ocupacion_max=0.3,
                edificabilidad_max_m2_m2=0.9,
            )
    if m == 'a coruña' or m == 'a coruna' or m == 'coruna':
        return PlanParams(
            municipio=municipio,
            subzona=subzona,
            altura_maxima_m=13.5,
            retranqueo_min_m=3.0,
            ocupacion_max=0.45,
            edificabilidad_max_m2_m2=1.1,
        )

    # Por defecto: sin datos
    return PlanParams(municipio=municipio, subzona=subzona)
