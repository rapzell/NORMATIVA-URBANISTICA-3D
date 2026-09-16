"""Etiquetado de calidad de datos para trazabilidad de fuentes.

Cada dato que llega a la UI o a un informe debe poder juzgar su credibilidad.
Este módulo define los niveles canónicos y el contenedor `DataPoint` que
serializa `value`, `unit`, `data_quality`, `source`, `source_ref` y `notes`.

Niveles:
- ``official``    → servicios oficiales (SIOTUGA WFS, Catastro INSPIRE, OVC).
- ``measured``    → medición directa (PNOA LiDAR P90).
- ``estimated``   → inferencia por reglas (plantas × 3 m, valores por defecto).
- ``unavailable`` → no se pudo obtener; nunca se sustituye por un valor falso.

Ejemplo::

    from src.data_quality import DataPoint, DataQuality
    altura = DataPoint(14.2, "m", DataQuality.MEASURED, "PNOA LiDAR",
                       source_ref="P90 nDSM").to_dict()
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DataQuality(Enum):
    OFFICIAL = "official"
    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


QUALITY_LABELS = {
    DataQuality.OFFICIAL.value: "Oficial",
    DataQuality.MEASURED.value: "Medido",
    DataQuality.ESTIMATED.value: "Estimado",
    DataQuality.UNAVAILABLE.value: "No disponible",
}


@dataclass
class DataPoint:
    value: Any
    unit: str | None
    quality: DataQuality
    source: str
    source_ref: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "data_quality": self.quality.value,
            "quality_label": QUALITY_LABELS.get(self.quality.value, self.quality.value),
            "source": self.source,
            "source_ref": self.source_ref,
            "notes": self.notes,
        }


def official(value: Any, unit: str | None = None, source: str = "", **kw) -> DataPoint:
    return DataPoint(value, unit, DataQuality.OFFICIAL, source, **kw)


def measured(value: Any, unit: str | None = None, source: str = "", **kw) -> DataPoint:
    return DataPoint(value, unit, DataQuality.MEASURED, source, **kw)


def estimated(value: Any, unit: str | None = None, source: str = "", **kw) -> DataPoint:
    return DataPoint(value, unit, DataQuality.ESTIMATED, source, **kw)


def unavailable(source: str = "", notes: str | None = None, unit: str | None = None) -> DataPoint:
    return DataPoint(None, unit, DataQuality.UNAVAILABLE, source, notes=notes)
