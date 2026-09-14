"""Análisis preliminar de sombras proyectadas por edificios.

Calcula la posición solar (azimut y elevación) para una latitud/longitud y
fecha/hora dadas, y proyecta la sombra de un edificio extruido sobre el
plano horizontal. Sin dependencias externas: usa fórmulas astronómicas
simplificadas (modelo NOAA simplificado).

Limitaciones:
- No tiene en cuenta sombras arrojadas por otros edificios.
- No tiene en cuenta relieve.
- La sombra se proyecta sobre un plano horizontal z=0.
- Es una estimación preliminar orientativa.
"""
from __future__ import annotations

import math
import datetime
from typing import Optional


def _day_of_year(dt: datetime.datetime) -> int:
    return dt.timetuple().tm_yday


def solar_position(lat_deg: float, lon_deg: float, dt: datetime.datetime) -> dict:
    """Calcula la posición solar (azimut y elevación) para una fecha/hora UTC.

    Usa un modelo astronómico simplificado basado en las ecuaciones de NOAA.
    Precisión suficiente para análisis preliminar de sombras urbanísticas.

    Args:
        lat_deg: latitud en grados decimales.
        lon_deg: longitud en grados decimales.
        dt: fecha y hora en UTC.

    Returns:
        dict con:
          - elevation_deg: elevación solar en grados (0 = horizonte, 90 = cenit)
          - azimuth_deg: azimut solar en grados (0 = norte, 180 = sur, sentido horario)
          - solar_noon: hora del mediodía solar aproximada
    """
    # Día del año
    doy = _day_of_year(dt)

    # Fracción de año en radianes
    gamma = 2 * math.pi / 365.0 * (doy - 1 + (dt.hour - 12) / 24.0)

    # Declinación solar (radianes)
    declination = 0.006918 \
        - 0.399912 * math.cos(gamma) \
        + 0.070257 * math.sin(gamma) \
        - 0.006758 * math.cos(2 * gamma) \
        + 0.000907 * math.sin(2 * gamma) \
        - 0.002697 * math.cos(3 * gamma) \
        + 0.001480 * math.sin(3 * gamma)

    # Ecuación del tiempo (minutos)
    eq_time = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))

    # Hora solar verdadera (minutos desde mediodía solar)
    time_offset = eq_time + 4.0 * lon_deg
    solar_time = dt.hour * 60 + dt.minute + time_offset
    solar_hour_angle = (solar_time / 4.0) - 180.0  # grados

    # Ángulo horario en radianes
    ha = math.radians(solar_hour_angle)

    lat_rad = math.radians(lat_deg)

    # Elevación solar
    sin_elev = math.sin(lat_rad) * math.sin(declination) \
        + math.cos(lat_rad) * math.cos(declination) * math.cos(ha)
    elevation_deg = math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))

    # Azimut solar (0 = norte, sentido horario)
    cos_az = (math.sin(declination) * math.cos(lat_rad) - math.cos(declination) * math.sin(lat_rad) * math.cos(ha)) / max(math.cos(math.radians(elevation_deg)), 1e-10)
    cos_az = max(-1.0, min(1.0, cos_az))
    azimuth_deg = math.degrees(math.acos(cos_az))
    if solar_hour_angle > 0:
        azimuth_deg = 360.0 - azimuth_deg

    solar_noon = 720 - time_offset  # minutos desde medianoche UTC

    return {
        'elevation_deg': round(elevation_deg, 2),
        'azimuth_deg': round(azimuth_deg, 2),
        'solar_noon_minutes': round(solar_noon, 1),
    }


def project_shadow_polygon(
    geometry: dict,
    height_m: float,
    elevation_deg: float,
    azimuth_deg: float,
) -> dict | None:
    """Proyecta la sombra de un edificio sobre el plano horizontal.

    Args:
        geometry: GeoJSON Polygon (anillo exterior).
        height_m: altura del edificio en metros.
        elevation_deg: elevación solar en grados.
        azimuth_deg: azimut solar en grados (0=norte, sentido horario).

    Returns:
        GeoJSON Polygon con la sombra proyectada, o None si el sol está
        bajo el horizonte o la geometría es inválida.
    """
    if elevation_deg <= 0.5:
        return None
    if not geometry or geometry.get('type') != 'Polygon':
        return None
    coords = geometry.get('coordinates') or []
    if not coords:
        return None
    ring = coords[0]
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        return None

    # Longitud de la sombra = altura / tan(elevación)
    shadow_len = height_m / math.tan(math.radians(elevation_deg))

    # Dirección opuesta al sol (la sombra se proyecta en sentido contrario)
    az_rad = math.radians(azimuth_deg)
    dx = -shadow_len * math.sin(az_rad)
    dy = -shadow_len * math.cos(az_rad)

    # Proyectar cada vértice: la base se queda, la cima se proyecta
    shadow_ring: list[list[float]] = []
    for (x, y) in ring:
        shadow_ring.append([float(x), float(y)])
    for (x, y) in ring:
        shadow_ring.append([float(x) + dx, float(y) + dy])

    # Cerrar el polígono
    shadow_ring.append(shadow_ring[0])

    return {
        'type': 'Polygon',
        'coordinates': [shadow_ring],
    }


def shadow_analysis(
    geometry: dict,
    height_m: float,
    lat: float,
    lon: float,
    dt: datetime.datetime,
) -> dict:
    """Análisis completo de sombra para un momento dado.

    Returns:
        dict con:
          - solar: posición solar
          - shadow_polygon: GeoJSON Polygon de la sombra (o None)
          - shadow_length_m: longitud de la sombra en metros
          - has_shadow: si hay sombra proyectada
    """
    solar = solar_position(lat, lon, dt)
    elevation = solar['elevation_deg']
    azimuth = solar['azimuth_deg']

    shadow_poly = None
    shadow_len = 0.0
    if elevation > 0.5:
        shadow_poly = project_shadow_polygon(geometry, height_m, elevation, azimuth)
        shadow_len = height_m / math.tan(math.radians(elevation))

    return {
        'solar': solar,
        'shadow_polygon': shadow_poly,
        'shadow_length_m': round(shadow_len, 2),
        'has_shadow': shadow_poly is not None,
    }


def shadow_analysis_multi_hour(
    geometry: dict,
    height_m: float,
    lat: float,
    lon: float,
    date: datetime.date,
    hours: list[int] | None = None,
) -> dict:
    """Análisis de sombras en múltiples horas del día.

    Args:
        hours: lista de horas UTC a analizar. Por defecto: 8, 10, 12, 14, 16, 18.

    Returns:
        dict con:
          - date: fecha analizada
          - results: lista de análisis por hora
          - max_shadow_length_m: longitud máxima de sombra
          - summary: resumen textual
    """
    if hours is None:
        hours = [8, 10, 12, 14, 16, 18]

    results = []
    max_len = 0.0
    for h in hours:
        dt = datetime.datetime(date.year, date.month, date.day, h, 0, 0)
        analysis = shadow_analysis(geometry, height_m, lat, lon, dt)
        analysis['hour_utc'] = h
        results.append(analysis)
        if analysis['shadow_length_m'] > max_len:
            max_len = analysis['shadow_length_m']

    return {
        'date': date.isoformat(),
        'results': results,
        'max_shadow_length_m': round(max_len, 2),
        'summary': f'Análisis de {len(results)} horas. Sombra máxima: {round(max_len, 2)} m.',
    }
