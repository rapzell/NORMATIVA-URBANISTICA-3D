from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel


class PlanParams(BaseModel):
    municipio: str
    subzona: Optional[str] = None
    altura_maxima_m: Optional[float] = None
    retranqueo_min_m: Optional[float] = None
    setback_front_m: Optional[float] = None
    setback_side_m: Optional[float] = None
    setback_back_m: Optional[float] = None
    front_direction_default: Optional[str] = None  # 'north'|'east'|'south'|'west'
    ocupacion_max: Optional[float] = None
    edificabilidad_max_m2_m2: Optional[float] = None
    # Metadatos opcionales de procedencia y precedencia normativa
    source: Optional[str] = None  # p.ej., 'csv', 'mock', 'autonomica', 'municipal'
    source_refs: Optional[List[str]] = None  # p.ej., ["VIGO Tomo III p.307-310", "PXOM Boiro p.119-120"]
    precedence: Optional[str] = None  # p.ej., 'municipal_over_autonomic'

# Alias semántico para el modelo canónico de reglas municipales.
# Mantiene compatibilidad con el resto del código que ya usa PlanParams.
PlanRules = PlanParams
