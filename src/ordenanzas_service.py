"""Consulta de ordenanzas municipales para cambio de uso.

Lee ficheros JSON de `datos/ordenanzas/{municipio}/` y los sirve vía API.
No inventa requisitos: si no hay fichero para un municipio, devuelve
`disponible: false` con un mensaje explícito.

Esquema esperado de cada fichero (ver datos/ordenanzas/_esquema.json):
{
  "municipio": "Vigo",
  "subzonas": {
    "U3": {
      "requisitos_cambio_uso": {
        "superficie_minima_vivienda_m2": 40,
        "altura_minima_m": 2.5,
        "ventilacion": "un hueco por estancia",
        "documentacion_especifica": ["estudio de soleamiento", "informe acústico"]
      },
      "criterios_tecnicos_municipales": "Los técnicos exigen justificación de ventilación cruzada en plantas bajas.",
      "plazo_estimado_tramitacion_dias": 90,
      "fuente": "Ordenanza municipal de Vigo, art. 45",
      "fecha_actualizacion": "2025-06-15"
    }
  },
  "requisitos_generales_licencia": {
    "documentacion": ["memoria", "planos", "justificación Decreto 128/2023"],
    "plazo_estimado_dias": 90,
    "fuente": "Ordenanza municipal de Vigo"
  }
}

Los datos los aporta AC8 o el estudio; el sistema no los genera.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ORDENANZAS_DIR = Path(__file__).resolve().parent.parent / "datos" / "ordenanzas"


def _normalize_municipio(municipio: str) -> str:
    """Normaliza el nombre del municipio para buscar el directorio."""
    if not municipio:
        return ""
    return municipio.strip().lower().replace(" ", "_").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n")


def list_municipios_with_ordenanzas() -> list[str]:
    """Lista los municipios que tienen ficheros de ordenanzas cargados."""
    if not ORDENANZAS_DIR.exists():
        return []
    result = []
    for entry in ORDENANZAS_DIR.iterdir():
        if entry.is_dir() and not entry.name.startswith("_"):
            json_files = list(entry.glob("*.json"))
            if json_files:
                result.append(entry.name.replace("_", " ").title())
    return sorted(result)


def get_ordenanza_municipio(municipio: str) -> dict[str, Any]:
    """Devuelve las ordenanzas de un municipio, o un dict con disponible=False.

    No inventa datos: si no hay fichero, lo indica explícitamente.
    """
    if not municipio:
        return {
            "disponible": False,
            "municipio": None,
            "mensaje": "No se especificó municipio.",
            "subzonas": {},
            "requisitos_generales_licencia": None,
        }

    norm = _normalize_municipio(municipio)
    muni_dir = ORDENANZAS_DIR / norm
    if not muni_dir.exists():
        # Ordenanzas reales extraídas automáticamente del PDF oficial
        # del plan (normativa_params) — datos oficiales con página.
        try:
            from app.main import _get_ine_for_municipio
            ine = _get_ine_for_municipio(municipio)
        except Exception:
            ine = None
        ords: dict = {}
        if ine:
            try:
                from src.normativa_params import \
                    extraer_ordenanzas_municipio
                ords = extraer_ordenanzas_municipio(ine) or {}
            except Exception:
                ords = {}
        if ords:
            return {
                "disponible": True,
                "municipio": municipio,
                "origen": "extracción automática del PDF oficial del plan",
                "subzonas": {code: {
                    "titulo": d.get("titulo"),
                    "parametros": d.get("params") or {},
                    "fuente": d.get("fuente"),
                    "nota": d.get("nota"),
                } for code, d in sorted(ords.items())},
                "requisitos_generales_licencia": None,
                "fuentes": ["PDFs normativos del plan (oficiales)"],
                "mensaje": ("Ordenanzas extraídas del documento oficial. "
                            "Los requisitos específicos de cambio de uso "
                            "aportados por el estudio se suman en "
                            f"datos/ordenanzas/{norm}/."),
            }
        return {
            "disponible": False,
            "municipio": municipio,
            "mensaje": f"No hay ordenanzas cargadas para {municipio}. Consúltese el ayuntamiento o aporte los datos vía datos/ordenanzas/{norm}/.",
            "subzonas": {},
            "requisitos_generales_licencia": None,
        }

    data: dict[str, Any] = {
        "disponible": True,
        "municipio": municipio,
        "subzonas": {},
        "requisitos_generales_licencia": None,
        "fuentes": [],
    }

    for json_file in sorted(muni_dir.glob("*.json")):
        try:
            with open(json_file, encoding="utf-8") as f:
                content = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if "subzonas" in content:
            data["subzonas"].update(content["subzonas"])
        if "requisitos_generales_licencia" in content:
            data["requisitos_generales_licencia"] = content["requisitos_generales_licencia"]
        if "fuente" in content:
            data["fuentes"].append(content["fuente"])

    if not data["subzonas"] and not data["requisitos_generales_licencia"]:
        data["disponible"] = False
        data["mensaje"] = f"El directorio de {municipio} existe pero no contiene ordenanzas válidas."

    return data


def get_ordenanza_subzona(municipio: str, subzona: str) -> dict[str, Any]:
    """Devuelve las ordenanzas de una subzona concreta de un municipio."""
    muni_data = get_ordenanza_municipio(municipio)
    if not muni_data.get("disponible"):
        return muni_data

    subzonas = muni_data.get("subzonas", {})
    if not subzona:
        return {
            "disponible": True,
            "municipio": municipio,
            "subzona": None,
            "mensaje": "No se especificó subzona.",
            "subzonas_disponibles": list(subzonas.keys()),
        }

    subzona_data = subzonas.get(subzona) or subzonas.get(subzona.upper()) or subzonas.get(subzona.lower())
    if not subzona_data:
        return {
            "disponible": True,
            "municipio": municipio,
            "subzona": subzona,
            "mensaje": f"No hay ordenanzas específicas para la subzona {subzona} en {municipio}.",
            "subzonas_disponibles": list(subzonas.keys()),
        }

    return {
        "disponible": True,
        "municipio": municipio,
        "subzona": subzona,
        "ordenanza": subzona_data,
    }
