from __future__ import annotations
from typing import Optional, Dict, Any
import os
import logging
from pydantic import BaseModel
from shapely.geometry import shape, mapping, Polygon, box, LineString
from shapely import affinity


class VolumeParams(BaseModel):
    altura_maxima_m: float
    retranqueo_min_m: float = 0.0
    setback_front_m: Optional[float] = None
    setback_side_m: Optional[float] = None
    setback_back_m: Optional[float] = None
    front_direction: Optional[str] = None  # 'north'|'east'|'south'|'west'


def compute_building_envelope(geometry: dict, params: VolumeParams, street_axis: Optional[dict] = None, front_direction_source: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Calcula una envolvente edificable simple: aplica retranqueo (buffer negativo) a la geometría
    de parcela y devuelve un GeoJSON Polygon/MultiPolygon con propiedad de altura (no extrusión 3D real).

    Nota: Se asume geometría en sistema plano adecuado si se quieren metros reales.
    """
    if not geometry:
        raise ValueError("Se requiere geometry (GeoJSON)")
    if params.altura_maxima_m is None or params.altura_maxima_m <= 0:
        raise ValueError("altura_maxima_m debe ser > 0")

    parcel = shape(geometry)
    debug = str(os.getenv('VOLUME_DEBUG', '0')).lower() in ('1', 'true', 'yes')
    logger = logging.getLogger('volume')
    if parcel.is_empty:
        raise ValueError("Geometría de parcela vacía")

    # Try directional for axis-aligned rectangles when front_direction provided
    applied_mode = "conservative_max_uniform"
    street_axis_used = False
    street_axis_ignored_reason: Optional[str] = None  # 'too_far'|'geom_error'|None
    front_side_used: Optional[str] = None  # 'top'|'bottom'|'left'|'right'
    street_axis_min_distance_m: Optional[float] = None
    street_axis_side_distances: Optional[Dict[str, float]] = None
    front_selection_rationale: Optional[str] = None  # 'street_axis_min_distance'|'front_direction_request'|'front_direction_plan_default'|'none'
    uniform_setback = 0.0
    buildable = parcel
    polygon_type = 'general'  # 'rectangle_axis_aligned'|'rectangle_rotated'|'general'
    directional_applicability = 'not_requested'  # 'applied'|'not_applicable'|'not_requested'
    directional_not_applied_reason: Optional[str] = None  # e.g., 'non_rectangular_parcel'
    street = shape(street_axis) if street_axis else None
    # Si el eje de calle está demasiado lejos de la parcela, ignorarlo
    if street is not None:
        try:
            dist = street.distance(parcel)
            minx, miny, maxx, maxy = parcel.bounds
            max_dim = max(maxx - minx, maxy - miny)
            try:
                factor = float(os.getenv('STREET_MAX_DIST_FACTOR', '1.5'))
            except Exception:
                factor = 1.5
            if dist > max_dim * factor:
                street = None
                street_axis_ignored_reason = 'too_far'
                if debug:
                    logger.debug(f"[volume] street_axis ignored: too_far (dist={dist:.3f} > {factor}*{max_dim:.3f})")
        except Exception:
            street = None
            street_axis_ignored_reason = 'geom_error'
            if debug:
                logger.debug("[volume] street_axis ignored: geom_error while computing distance")

    def _has_any_directional():
        return any(v is not None and v > 0 for v in (params.setback_front_m, params.setback_side_m, params.setback_back_m))

    if isinstance(parcel, Polygon) and (params.front_direction or street is not None):
        # Check axis-aligned rectangle (5 coords, orthogonal, aligned to axes)
        coords = list(parcel.exterior.coords)
        if len(coords) == 5:
            minx, miny, maxx, maxy = parcel.bounds
            # Validate axis alignment: all x in {minx,maxx}, y in {miny,maxy}
            if (
                all((abs(x - minx) < 1e-9 or abs(x - maxx) < 1e-9) for x, _ in coords)
                and all((abs(y - miny) < 1e-9 or abs(y - maxy) < 1e-9) for _, y in coords)
            ):
                # Determine front/back/side
                fd = (params.front_direction or 'north').lower()
                if street is not None and params.front_direction is None:
                    # Build side segments and pick the closest to street as front
                    top_seg = LineString([(minx, maxy), (maxx, maxy)])
                    bottom_seg = LineString([(minx, miny), (maxx, miny)])
                    left_seg = LineString([(minx, miny), (minx, maxy)])
                    right_seg = LineString([(maxx, miny), (maxx, maxy)])
                    dists = {
                        'top': top_seg.distance(street),
                        'bottom': bottom_seg.distance(street),
                        'left': left_seg.distance(street),
                        'right': right_seg.distance(street),
                    }
                    fd = min(dists, key=dists.get)
                    street_axis_used = True
                    front_side_used = fd
                    street_axis_side_distances = dists
                    street_axis_min_distance_m = float(min(dists.values()))
                    front_selection_rationale = 'street_axis_min_distance'
                    if debug:
                        logger.debug(f"[volume] front detected by street_axis (axis-aligned): side={fd}")
                sf = float(params.setback_front_m or 0.0)
                sb = float(params.setback_back_m or 0.0)
                ss = float(params.setback_side_m or 0.0)
                left = right = top = bottom = 0.0
                if fd == 'north' or fd == 'top':
                    if front_side_used is None:
                        front_side_used = 'top'
                    top = sf; bottom = sb; left = ss; right = ss
                elif fd == 'south' or fd == 'bottom':
                    if front_side_used is None:
                        front_side_used = 'bottom'
                    bottom = sf; top = sb; left = ss; right = ss
                elif fd == 'east' or fd == 'right':
                    if front_side_used is None:
                        front_side_used = 'right'
                    right = sf; left = sb; top = ss; bottom = ss
                elif fd == 'west' or fd == 'left':
                    if front_side_used is None:
                        front_side_used = 'left'
                    left = sf; right = sb; top = ss; bottom = ss
                else:
                    fd = 'north'
                    if front_side_used is None:
                        front_side_used = 'top'
                    top = sf; bottom = sb; left = ss; right = ss

                new_minx = minx + left
                new_maxx = maxx - right
                new_miny = miny + bottom
                new_maxy = maxy - top
                if new_minx < new_maxx and new_miny < new_maxy:
                    buildable = box(new_minx, new_miny, new_maxx, new_maxy)
                    applied_mode = "rect_directional"
                    polygon_type = 'rectangle_axis_aligned'
                    directional_applicability = 'applied'
                else:
                    buildable = Polygon()
        # If not axis-aligned, try rotated rectangle: align, inset, rotate back
        if buildable is parcel and len(coords) == 5:
            # Compute minimum rotated rectangle
            rect_rot = parcel.minimum_rotated_rectangle
            # Si es casi-rectángulo, también aceptar con tolerancia (configurable por ENV)
            try:
                area_ratio = rect_rot.area / max(parcel.area, 1e-9)
                sym_diff_area = parcel.symmetric_difference(rect_rot).area
                try:
                    tol_min = float(os.getenv('RECT_TOL_AREA_RATIO_MIN', '0.995'))
                except Exception:
                    tol_min = 0.995
                try:
                    tol_max = float(os.getenv('RECT_TOL_AREA_RATIO_MAX', '1.005'))
                except Exception:
                    tol_max = 1.005
                try:
                    symdiff_pct = float(os.getenv('RECT_TOL_SYMDIFF_PCT', '0.005'))
                except Exception:
                    symdiff_pct = 0.005
                tol_ok = (tol_min <= area_ratio <= tol_max) and (sym_diff_area <= max(parcel.area, 1.0) * symdiff_pct)
            except Exception:
                tol_ok = False
            # Rotar a eje global para aplicar setbacks cardinales y volver
            if len(list(rect_rot.exterior.coords)) == 5:
                # Vector of first edge of min rect gives angle
                (x0, y0), (x1, y1) = list(rect_rot.exterior.coords)[0], list(rect_rot.exterior.coords)[1]
                import math
                angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
                # Rotate polygon to axis-aligned frame
                centroid = parcel.centroid
                rot = affinity.rotate(parcel, -angle, origin=(centroid.x, centroid.y))
                rminx, rminy, rmaxx, rmaxy = rot.bounds

                # Determine front/back assignment in rotated frame
                if ((abs(rect_rot.area - parcel.area) / max(parcel.area, 1e-9) < 1e-9 and parcel.buffer(0).equals(rect_rot.buffer(0))) or tol_ok):
                    # Es un rectángulo rotado
                    if street is not None and params.front_direction is None:
                        # Build side segments and pick the closest to street as front
                        street_rot = affinity.rotate(street, -angle, origin=(centroid.x, centroid.y))
                        top_seg = LineString([(rminx, rmaxy), (rmaxx, rmaxy)])
                        bottom_seg = LineString([(rminx, rminy), (rmaxx, rminy)])
                        left_seg = LineString([(rminx, rminy), (rminx, rmaxy)])
                        right_seg = LineString([(rmaxx, rminy), (rmaxx, rmaxy)])
                        dists = {
                            'top': top_seg.distance(street_rot),
                            'bottom': bottom_seg.distance(street_rot),
                            'left': left_seg.distance(street_rot),
                            'right': right_seg.distance(street_rot),
                        }
                        fd = min(dists, key=dists.get)
                        street_axis_used = True
                        front_side_used = fd
                        street_axis_side_distances = dists
                        street_axis_min_distance_m = float(min(dists.values()))
                        front_selection_rationale = 'street_axis_min_distance'
                        if debug:
                            logger.debug(f"[volume] front detected by street_axis (rotated): side={fd}")
                    else:
                        # Use world cardinal projected into rotated frame
                        fd = (params.front_direction or 'north').lower()
                        card = {
                            'north': (0.0, 1.0),
                            'south': (0.0, -1.0),
                            'east': (1.0, 0.0),
                            'west': (-1.0, 0.0),
                        }.get(fd, (0.0, 1.0))
                        theta = -math.radians(angle)
                        c, s = math.cos(theta), math.sin(theta)
                        vnx, vny = card[0] * c - card[1] * s, card[0] * s + card[1] * c
                        normals = {
                            'top': (0.0, 1.0),
                            'bottom': (0.0, -1.0),
                            'right': (1.0, 0.0),
                            'left': (-1.0, 0.0),
                        }
                        dots = {k: vnx * nx + vny * ny for k, (nx, ny) in normals.items()}
                        front_side = max(dots, key=dots.get)
                        front_side_used = front_side
                    back_side = {
                        'top': 'bottom',
                        'bottom': 'top',
                        'left': 'right',
                        'right': 'left',
                    }[front_side]
                    side_pair = [s for s in ['top', 'bottom', 'left', 'right'] if s not in (front_side, back_side)]

                    sf = float(params.setback_front_m or 0.0)
                    sb = float(params.setback_back_m or 0.0)
                    ss = float(params.setback_side_m or 0.0)
                    top = bottom = left = right = 0.0
                    for nm in side_pair:
                        if nm == 'left':
                            left = ss
                        elif nm == 'right':
                            right = ss
                        elif nm == 'top':
                            top = ss
                        elif nm == 'bottom':
                            bottom = ss
                    if front_side == 'top':
                        top = sf
                    elif front_side == 'bottom':
                        bottom = sf
                    elif front_side == 'left':
                        left = sf
                    elif front_side == 'right':
                        right = sf
                    if back_side == 'top':
                        top = sb
                    elif back_side == 'bottom':
                        bottom = sb
                    elif back_side == 'left':
                        left = sb
                    elif back_side == 'right':
                        right = sb

                    new_minx = rminx + left
                    new_maxx = rmaxx - right
                    new_miny = rminy + bottom
                    new_maxy = rmaxy - top
                    if new_minx < new_maxx and new_miny < new_maxy:
                        rect_rot = box(new_minx, new_miny, new_maxx, new_maxy)
                        buildable = affinity.rotate(rect_rot, angle, origin=(centroid.x, centroid.y))
                        applied_mode = "rotated_rect_directional"
                        polygon_type = 'rectangle_rotated'
                        directional_applicability = 'applied'
                    else:
                        buildable = Polygon()
                        directional_not_applied_reason = 'non_rectangular_parcel'

    if buildable is parcel:
        # Fallback to conservative uniform using maximum of provided values
        candidates = [params.retranqueo_min_m or 0.0]
        if _has_any_directional():
            for v in (params.setback_front_m, params.setback_side_m, params.setback_back_m):
                if v is not None and v > 0:
                    candidates.append(v)
        uniform_setback = max(candidates) if candidates else 0.0
        if uniform_setback and uniform_setback > 0:
            buildable = parcel.buffer(-uniform_setback)
            if debug:
                logger.debug(f"[volume] uniform setback applied={uniform_setback}")

    if buildable.is_empty:
        # Retranqueo agota la parcela
        if debug:
            logger.debug("[volume] buildable geometry exhausted -> None")
        return None

    gj = mapping(buildable)
    # Ajustar fuente de dirección de frente para reflejar uso real del eje de calle
    if street_axis_used:
        front_src = 'street_axis'
    else:
        front_src = front_direction_source or ('request' if params.front_direction else 'none')
    if front_selection_rationale is None:
        if front_src == 'request':
            front_selection_rationale = 'front_direction_request'
        elif front_src == 'plan_default':
            front_selection_rationale = 'front_direction_plan_default'
        else:
            front_selection_rationale = 'none'
    feature = {
        "type": "Feature",
        "geometry": gj,
        "properties": {
            "height_m": float(params.altura_maxima_m),
            "setback_m": float(params.retranqueo_min_m or 0.0),
            "setback_front_m": float(params.setback_front_m) if params.setback_front_m is not None else None,
            "setback_side_m": float(params.setback_side_m) if params.setback_side_m is not None else None,
            "setback_back_m": float(params.setback_back_m) if params.setback_back_m is not None else None,
            "setback_applied_m": float(uniform_setback),
            "setback_mode": applied_mode,
            "front_direction": (params.front_direction or None),
            "street_axis_used": bool(street_axis_used),
            "front_detected_side": front_side_used,
            "front_direction_source": front_src,
            "front_selection_rationale": front_selection_rationale,
            "street_axis_ignored_reason": street_axis_ignored_reason,
            "polygon_type": polygon_type,
            "directional_applicability": directional_applicability,
            "directional_not_applied_reason": directional_not_applied_reason,
            "area_m2": float(buildable.area),
            "street_axis_min_distance_m": float(street_axis_min_distance_m) if street_axis_min_distance_m is not None else None,
            "street_axis_side_distances": street_axis_side_distances,
        },
    }
    return feature
