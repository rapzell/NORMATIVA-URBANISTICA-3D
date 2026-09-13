from typing import Optional

from src.rules_engine import geometry_checks, get_plan_params_dynamic


def infer_limiting_factor(req_municipio: Optional[str], req_subzona: Optional[str], feature: dict) -> tuple[str, dict]:
    limiting_factor = "altura"
    limiting_details = {}
    try:
        parcel_area = None
        try:
            parcel_area = float(geometry_checks(feature.get('geometry') or {}).area)
        except Exception:
            parcel_area = None
        props = (feature.get('properties') or {})
        build_area = props.get('area_m2')
        setback_applied = float(props.get('setback_applied_m') or 0.0)
        dir_applied = (props.get('directional_applicability') == 'applied')
        occ_used = None
        occ_cap = None
        edi_used = None
        edi_cap = None
        if req_municipio and (parcel_area is not None) and (build_area is not None):
            _plan = get_plan_params_dynamic(req_municipio, req_subzona)
            occ_used = getattr(_plan, 'ocupacion_max', None)
            if occ_used is not None:
                occ_cap = float(parcel_area) * float(occ_used)
                try:
                    ba = float(build_area)
                except Exception:
                    ba = None
                if ba is not None and occ_cap is not None and occ_cap < (ba * 0.99):
                    limiting_factor = 'ocupacion'
            edi_used = getattr(_plan, 'edificabilidad_max_m2_m2', None)
            if edi_used is not None:
                edi_cap = float(parcel_area) * float(edi_used)
                try:
                    ba = float(build_area)
                except Exception:
                    ba = None
                if ba is not None and edi_cap is not None and edi_cap < (ba * 0.99) and limiting_factor == 'altura':
                    limiting_factor = 'edificabilidad'
        if limiting_factor == 'altura' and (dir_applied or (setback_applied > 0.0)):
            if (parcel_area is not None and build_area is not None):
                try:
                    ba = float(build_area)
                except Exception:
                    ba = None
                if ba is not None and ba <= parcel_area * 0.99:
                    limiting_factor = 'retranqueos'
        limiting_details = {
            'parcel_area_m2': parcel_area,
            'buildable_area_m2': build_area,
            'setback_applied_m': props.get('setback_applied_m'),
            'directional_applicability': props.get('directional_applicability'),
            'ocupacion_max': occ_used,
            'ocupacion_cap_area_m2': occ_cap,
            'edificabilidad_max_m2_m2': edi_used,
            'edificabilidad_cap_m2': edi_cap,
        }
    except Exception:
        pass
    return limiting_factor, limiting_details
