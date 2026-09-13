from typing import Optional

from src.plans_service import get_plan_params_dynamic
from src.rules_engine import geometry_checks
from src.volume import VolumeParams, compute_building_envelope
from src.zoning_service import (
    arcgis_feature_query,
    centroid_lonlat_from_geojson,
    wms_config_for_municipio,
)


class ZoningAssessmentError(ValueError):
    pass


def resolve_assess_effective_params(
    *,
    municipio: Optional[str],
    subzona: Optional[str],
    altura_maxima_m: Optional[float],
    retranqueo_min_m: Optional[float],
    setback_front_m: Optional[float],
    setback_side_m: Optional[float],
    setback_back_m: Optional[float],
    front_direction: Optional[str],
    street_axis: Optional[dict],
    use_plan_front_default: Optional[bool],
    geometry: Optional[dict] = None,
) -> dict:
    """Resuelve los parámetros efectivos para la evaluación normativa de una parcela."""
    altura = altura_maxima_m
    retranqueo = retranqueo_min_m or 0.0
    effective_front_direction = front_direction
    front_dir_source = None
    setback_front = setback_front_m
    setback_side = setback_side_m
    setback_back = setback_back_m
    reasons: list[str] = []

    plan = None
    if municipio:
        try:
            plan = get_plan_params_dynamic(municipio, subzona)
        except Exception:
            plan = None

    if plan is not None:
        if altura is None and getattr(plan, 'altura_maxima_m', None) is not None:
            altura = plan.altura_maxima_m
        if retranqueo_min_m is None and getattr(plan, 'retranqueo_min_m', None) is not None:
            retranqueo = plan.retranqueo_min_m

        pfd = getattr(plan, 'front_direction_default', None)
        pf = getattr(plan, 'setback_front_m', None)
        ps = getattr(plan, 'setback_side_m', None)
        pb = getattr(plan, 'setback_back_m', None)
        has_plan_dir_setbacks = (pf is not None) or (ps is not None) or (pb is not None)

        if (
            effective_front_direction is None
            and street_axis is None
            and bool(use_plan_front_default)
            and pfd
            and has_plan_dir_setbacks
        ):
            effective_front_direction = pfd
            front_dir_source = 'plan_default'
            reasons.append("front_direction por defecto del plan aplicado")

        if effective_front_direction is not None or street_axis is not None:
            setback_front = setback_front_m if setback_front_m is not None else pf
            setback_side = setback_side_m if setback_side_m is not None else ps
            setback_back = setback_back_m if setback_back_m is not None else pb

    if altura is None:
        altura = 12.0
        if retranqueo is None:
            retranqueo = 3.0
        reasons.append("Parámetros por defecto aplicados (altura=12m, retranqueo_min=3m)")

    return {
        'altura': altura,
        'retranqueo': retranqueo,
        'effective_front_direction': effective_front_direction,
        'front_dir_source': front_dir_source,
        'setback_front': setback_front,
        'setback_side': setback_side,
        'setback_back': setback_back,
        'reasons': reasons,
        'plan': plan,
    }


def evaluate_zoning_assessment(req) -> dict:
    resolved = resolve_assess_effective_params(
        municipio=req.municipio,
        subzona=req.subzona,
        altura_maxima_m=req.altura_maxima_m,
        retranqueo_min_m=req.retranqueo_min_m,
        setback_front_m=req.setback_front_m,
        setback_side_m=req.setback_side_m,
        setback_back_m=req.setback_back_m,
        front_direction=req.front_direction,
        street_axis=req.street_axis,
        use_plan_front_default=req.use_plan_front_default,
        geometry=req.geometry,
    )
    altura = resolved['altura']
    retranqueo = resolved['retranqueo']
    reasons: list[str] = list(resolved['reasons'])
    effective_front_direction = resolved['effective_front_direction']
    front_dir_source = resolved['front_dir_source']
    setback_front = resolved['setback_front']
    setback_side = resolved['setback_side']
    setback_back = resolved['setback_back']
    plan = resolved['plan']

    if req.geometry is None:
        reasons.append("Sin geometría: no se puede evaluar la viabilidad volumétrica de la parcela")
        return {
            "viability": "condicionado",
            "reasons": reasons,
            "params_effective": {
                "altura_maxima_m": altura,
                "retranqueo_min_m": retranqueo,
                "setback_front_m": setback_front,
                "setback_side_m": setback_side,
                "setback_back_m": setback_back,
                "front_direction": effective_front_direction,
                "front_direction_source": front_dir_source,
                "municipio": req.municipio,
                "subzona": req.subzona,
                "plan_source": getattr(plan, 'source', None) if plan is not None else None,
            },
            "feature": None,
            "geometry_summary": None,
        }

    if altura is None:
        try:
            if req.municipio:
                try:
                    if (not getattr(req, 'subzona', None)) and getattr(req, 'municipio', None):
                        if str(req.municipio).strip().lower().find('vigo') >= 0:
                            cfg = wms_config_for_municipio(req.municipio)
                            feature_url = (cfg or {}).get('feature_url') if isinstance(cfg, dict) else None
                            if feature_url and getattr(req, 'geometry', None):
                                lon, lat = centroid_lonlat_from_geojson(req.geometry, getattr(req, 'crs', None))
                                if (lon is not None) and (lat is not None):
                                    subz, _diag = arcgis_feature_query(feature_url, float(lon), float(lat))
                                    if subz:
                                        req.subzona = subz
                except Exception:
                    pass
                if plan is not None and plan.altura_maxima_m is None:
                    raise ValueError("El plan municipal no devuelve altura máxima")
            else:
                raise ZoningAssessmentError("altura_maxima_m requerida si no se especifica municipio")
        except ZoningAssessmentError:
            raise
        except Exception as e:
            reasons.append(f"Fallback de plan: {e}")

    if altura is None:
        altura = 12.0
        if retranqueo is None:
            retranqueo = 3.0
        reasons.append("Parámetros por defecto aplicados (altura=12m, retranqueo_min=3m)")

    try:
        params = VolumeParams(
            altura_maxima_m=float(altura),
            retranqueo_min_m=float(retranqueo or 0.0),
            setback_front_m=setback_front,
            setback_side_m=setback_side,
            setback_back_m=setback_back,
            front_direction=effective_front_direction,
        )
        feat = compute_building_envelope(
            req.geometry,
            params,
            street_axis=req.street_axis,
            front_direction_source=front_dir_source,
            crs=getattr(req, 'crs', None),
        )
    except Exception as e:
        raise ZoningAssessmentError(f"Error en evaluación volumétrica: {e}")

    geometry_summary = None
    try:
        _gs = geometry_checks(req.geometry)
        try:
            geometry_summary = _gs.model_dump()
        except Exception:
            try:
                geometry_summary = dict(_gs) if isinstance(_gs, dict) else (
                    _gs.__dict__ if hasattr(_gs, '__dict__') else None
                )
            except Exception:
                geometry_summary = None
    except Exception:
        geometry_summary = None

    if feat is None:
        reasons.append("La envolvente edificable no existe (retranqueos agotan la parcela)")
        return {
            "viability": 'no_apto',
            "reasons": reasons,
            "params_effective": {
                'altura_maxima_m': altura,
                'retranqueo_min_m': retranqueo,
                'setback_front_m': setback_front,
                'setback_side_m': setback_side,
                'setback_back_m': setback_back,
                'front_direction': effective_front_direction,
                'front_direction_source': front_dir_source or ('request' if effective_front_direction else 'none'),
                'municipio': (req.municipio or '').strip() if isinstance(req.municipio, str) else req.municipio,
                'subzona': (req.subzona or '').strip() if isinstance(req.subzona, str) else req.subzona,
            },
            "feature": None,
            "geometry_summary": geometry_summary,
        }

    props = feat.get('properties') or {}
    try:
        muni_norm = (req.municipio or '').strip() if isinstance(req.municipio, str) else req.municipio
        subz_norm = (req.subzona or '').strip() if isinstance(req.subzona, str) else req.subzona
        if isinstance(props, dict):
            if muni_norm and 'municipio' not in props:
                props['municipio'] = muni_norm
            if subz_norm and 'subzona' not in props:
                props['subzona'] = subz_norm
            feat['properties'] = props
    except Exception:
        pass

    condicionado = False
    if props.get('directional_not_applied_reason'):
        condicionado = True
        reasons.append(f"No se aplicó retranqueo direccional: {props.get('directional_not_applied_reason')}")
    if props.get('street_axis_ignored_reason'):
        condicionado = True
        reasons.append(f"Eje de calle ignorado: {props.get('street_axis_ignored_reason')}")
    if (front_dir_source == 'plan_default') and not req.front_direction and not req.street_axis:
        condicionado = True
        reasons.append("Dirección de frente por defecto del plan (sin eje de calle ni petición explícita)")

    viability = 'condicionado' if condicionado else 'apto'
    return {
        "viability": viability,
        "reasons": reasons,
        "params_effective": {
            'altura_maxima_m': altura,
            'retranqueo_min_m': retranqueo,
            'setback_front_m': setback_front,
            'setback_side_m': setback_side,
            'setback_back_m': setback_back,
            'front_direction': effective_front_direction,
            'front_direction_source': props.get('front_direction_source') or front_dir_source or ('request' if effective_front_direction else 'none'),
            'municipio': (req.municipio or '').strip() if isinstance(req.municipio, str) else req.municipio,
            'subzona': (req.subzona or '').strip() if isinstance(req.subzona, str) else req.subzona,
        },
        "feature": feat,
        "geometry_summary": geometry_summary,
    }
