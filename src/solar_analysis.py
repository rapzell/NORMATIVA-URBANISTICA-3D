"""Análisis preliminar de soleamiento por orientación de fachada.

Calcula las horas de sol directo potencial que recibe cada orientación
(N, NE, E, SE, S, SW, W, NW) para fechas representativas (equinoccios y
solsticios). Usa el modelo astronómico de shadow_service; no requiere
dependencias externas.

Limitaciones explícitas:
- No tiene en cuenta edificios colindantes ni relieve.
- No sustituye un estudio de sombras con modelo 3D (CityJSON/SWAN).
- Es una estimación preliminar de potencial de soleamiento por orientación.
"""
from __future__ import annotations

import datetime
import math
from typing import Any

from src.shadow_service import solar_position


ORIENTATIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_ORIENTATION_AZIMUTH = {
    "N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0,
    "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0,
}

REPRESENTATIVE_DATES = {
    "equinoccio_primavera": (3, 21),
    "solsticio_verano": (6, 21),
    "equinoccio_otonio": (9, 23),
    "solsticio_invierno": (12, 21),
}


def _azimuth_diff(a1: float, a2: float) -> float:
    """Diferencia angular mínima entre dos azimutes (0-180)."""
    diff = abs(a1 - a2) % 360.0
    return min(diff, 360.0 - diff)


def _facade_receives_sun(solar_azimuth: float, solar_elevation: float, facade_azimuth: float, half_angle: float = 45.0) -> bool:
    """Determina si una fachada recibe sol directo.

    Una fachada recibe sol si el sol está sobre el horizonte y su azimut
    está dentro del sector angular de la fachada (±half_angle).
    Para fachadas orientadas al norte en el hemisferio norte, el sol
    directo es muy improbable salvo en verano.
    """
    if solar_elevation <= 0.5:
        return False
    return _azimuth_diff(solar_azimuth, facade_azimuth) <= half_angle


def analyze_solar_exposure(
    lat: float,
    lon: float,
    *,
    dates: dict[str, tuple[int, int]] | None = None,
    hour_step: int = 1,
) -> dict[str, Any]:
    """Analiza el potencial de soleamiento por orientación para fechas representativas.

    Args:
        lat: latitud en grados decimales.
        lon: longitud en grados decimales.
        dates: dict de nombre -> (mes, dia). Por defecto usa REPRESENTATIVE_DATES.
        hour_step: paso de horas para el muestreo (1 = cada hora).

    Returns:
        dict con:
          - dates: resultados por fecha y orientación
          - summary: resumen textual
          - limitations: limitaciones del análisis
    """
    dates = dates or REPRESENTATIVE_DATES
    year = datetime.datetime.now().year
    results_by_date: dict[str, dict] = {}

    for date_name, (month, day) in dates.items():
        hours_sun: dict[str, float] = {o: 0.0 for o in ORIENTATIONS}
        max_elevation = 0.0
        sunrise_hour: int | None = None
        sunset_hour: int | None = None

        for hour in range(4, 22, hour_step):
            dt = datetime.datetime(year, month, day, hour, 0, 0)
            solar = solar_position(lat, lon, dt)
            elev = solar["elevation_deg"]
            az = solar["azimuth_deg"]

            if elev > 0.5:
                if sunrise_hour is None:
                    sunrise_hour = hour
                sunset_hour = hour

            if elev > max_elevation:
                max_elevation = elev

            for orient in ORIENTATIONS:
                if _facade_receives_sun(az, elev, _ORIENTATION_AZIMUTH[orient]):
                    hours_sun[orient] += hour_step

        daylight_hours = ((sunset_hour or 0) - (sunrise_hour or 0)) if sunrise_hour else 0.0

        results_by_date[date_name] = {
            "hours_sun_by_orientation": {k: round(v, 1) for k, v in hours_sun.items()},
            "daylight_hours": round(float(daylight_hours), 1),
            "max_solar_elevation_deg": round(max_elevation, 1),
            "sunrise_hour_utc": sunrise_hour,
            "sunset_hour_utc": sunset_hour,
        }

    best_orientation = max(
        ORIENTATIONS,
        key=lambda o: sum(
            results_by_date[d]["hours_sun_by_orientation"][o]
            for d in results_by_date
        ),
    )
    worst_orientation = min(
        ORIENTATIONS,
        key=lambda o: sum(
            results_by_date[d]["hours_sun_by_orientation"][o]
            for d in results_by_date
        ),
    )

    inv_hours = results_by_date.get("solsticio_invierno", {}).get("hours_sun_by_orientation", {})
    south_winter = inv_hours.get("S", 0.0)
    north_winter = inv_hours.get("N", 0.0)

    summary_parts = [
        f"Mejor orientación: {best_orientation}.",
        f"Peor orientación: {worst_orientation}.",
        f"Sur en invierno: {south_winter:g} h de sol potencial.",
    ]
    if north_winter > 0:
        summary_parts.append(f"Norte recibe sol en verano pero {north_winter:g} h en invierno.")

    return {
        "lat": lat,
        "lon": lon,
        "dates": results_by_date,
        "best_orientation": best_orientation,
        "worst_orientation": worst_orientation,
        "summary": " ".join(summary_parts),
        "limitations": [
            "No tiene en cuenta edificios colindantes ni relieve.",
            "No sustituye un estudio de sombras con modelo 3D (CityJSON/SWAN).",
            "Estimación preliminar de potencial por orientación de fachada.",
        ],
    }


def render_solar_exposure_html(analysis: dict[str, Any]) -> str:
    """Genera una tabla HTML resumida del análisis de soleamiento."""
    dates = analysis.get("dates", {})
    if not dates:
        return "<div class='muted'>Sin datos de soleamiento.</div>"

    import html as _html

    def esc(x):
        return _html.escape(str(x))

    header = "<tr><th>Fecha</th><th>" + "</th><th>".join(esc(o) for o in ORIENTATIONS) + "</th><th>Horas luz</th></tr>"
    rows = ""
    for date_name, data in dates.items():
        hours = data.get("hours_sun_by_orientation", {})
        cells = "".join(f"<td>{esc(f'{hours.get(o, 0):g}')}</td>" for o in ORIENTATIONS)
        daylight = f'{data.get("daylight_hours", 0):g}'
        rows += f"<tr><td>{esc(date_name)}</td>{cells}<td>{esc(daylight)}</td></tr>"

    limitations = "".join(f"<li>{esc(l)}</li>" for l in analysis.get("limitations", []))

    return (
        f"<p><b>Resumen:</b> {esc(analysis.get('summary', ''))}</p>"
        "<table style='width:100%;font-size:12px'>"
        f"<thead>{header}</thead><tbody>{rows}</tbody></table>"
        f"<ul class='muted'>{limitations}</ul>"
    )
