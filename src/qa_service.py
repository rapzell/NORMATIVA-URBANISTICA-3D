import logging
import re
import unicodedata
from typing import Optional

from src.normativa_extract import extract_normativa_fields
from src.plans_service import get_plan_params_dynamic


def _strip_accents(text: str) -> str:
    try:
        return ''.join(ch for ch in unicodedata.normalize('NFD', text) if unicodedata.category(ch) != 'Mn')
    except Exception:
        return text


def _detect_municipio(base_text: str) -> Optional[str]:
    base = _strip_accents(base_text.lower())
    if 'vigo' in base:
        return 'Vigo'
    if ('a coruna' in base) or ('a corun' in base) or ('coruna' in base) or ('corun' in base):
        return 'A Coruna'
    if 'santiago' in base:
        return 'Santiago'
    if 'ourense' in base or 'orense' in base:
        return 'Ourense'
    if 'lugo' in base:
        return 'Lugo'
    if 'boiro' in base:
        return 'Boiro'
    return None


def _detect_subzona(text: str) -> Optional[str]:
    m_sub = re.search(r"\b((?:U\s*\d+(?:\.\d+)?)|(?:NR\s*-?\s*\d+))\b", text, flags=re.IGNORECASE)
    return m_sub.group(1).upper().replace(" ", "") if m_sub else None


def _wants_local(text: str) -> bool:
    return bool(re.search(r"\b(altura|maxim|retranqueo|setback|ocupaci[oó]n|edificabilidad|m2\s*/\s*m2)\b", text, flags=re.IGNORECASE))


def _format_value(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    return value


def _build_fallback_summary(raw_text: str) -> dict:
    txt = "\n".join([ln for ln in (raw_text or '').splitlines() if not ln.strip().startswith('[Contexto visor]')]).strip()
    wants_local = _wants_local(txt)
    muni = _detect_municipio(txt) if wants_local else None
    subz = _detect_subzona(txt) if wants_local else None

    plan = None
    if wants_local and muni:
        try:
            plan = get_plan_params_dynamic(muni, subz)
        except Exception:
            plan = None

    basic = extract_normativa_fields(txt, municipio=None)
    resumen: list[str] = []

    if wants_local and muni:
        resumen.append(f"Municipio: {muni}")
    if subz:
        resumen.append(f"Subzona: {subz}")

    if wants_local and plan is not None:
        am = _format_value(getattr(plan, 'altura_maxima_m', None))
        rm = _format_value(getattr(plan, 'retranqueo_min_m', None))
        sf = _format_value(getattr(plan, 'setback_front_m', None))
        ss = _format_value(getattr(plan, 'setback_side_m', None))
        sb = _format_value(getattr(plan, 'setback_back_m', None))
        oc = getattr(plan, 'ocupacion_max', None)
        ed = _format_value(getattr(plan, 'edificabilidad_max_m2_m2', None))
        if am is not None:
            resumen.append(f"Altura máxima (m): {am}")
        if rm is not None:
            resumen.append(f"Retanqueo mínimo (m): {rm}")
        if sf is not None:
            resumen.append(f"Frente (m): {sf}")
        if ss is not None:
            resumen.append(f"Laterales (m): {ss}")
        if sb is not None:
            resumen.append(f"Fondo (m): {sb}")
        if oc is not None:
            resumen.append(f"Ocupación máx.: {oc}")
        if ed is not None:
            resumen.append(f"Edificabilidad (m2/m2): {ed}")

    if basic.get("uso_suelo") and all("Uso del suelo:" not in x for x in resumen):
        resumen.append(f"Uso del suelo: {basic['uso_suelo']}")
    if basic.get("altura_maxima_m") is not None and all("Altura máxima" not in x for x in resumen):
        resumen.append(f"Altura máxima (m): {basic['altura_maxima_m']}")
    if basic.get("retranqueo_min_m") is not None and all("Retanqueo mínimo" not in x for x in resumen):
        resumen.append(f"Retanqueo mínimo (m): {basic['retranqueo_min_m']}")
    if basic.get("setback_front_m") is not None and all("Frente (m):" not in x for x in resumen):
        resumen.append(f"Frente (m): {basic['setback_front_m']}")
    if basic.get("setback_side_m") is not None and all("Laterales (m):" not in x for x in resumen):
        resumen.append(f"Laterales (m): {basic['setback_side_m']}")
    if basic.get("setback_back_m") is not None and all("Fondo (m):" not in x for x in resumen):
        resumen.append(f"Fondo (m): {basic['setback_back_m']}")
    if basic.get("edificabilidad_max_m2_m2") is not None and all("Edificabilidad" not in x for x in resumen):
        resumen.append(f"Edificabilidad (m2/m2): {basic['edificabilidad_max_m2_m2']}")

    if not wants_local:
        uso_det = str(basic.get("uso_suelo") or '').lower()
        if uso_det in ("rustico", "rústico"):
            resumen = [
                "Suelo rústico: usos compatibles con su naturaleza (agrícolas, ganaderos, forestales, de protección ambiental e infraestructuras), evitando transformaciones urbanísticas.",
                "Referencia: Ley 2/2016 del Suelo de Galicia, Artículos 31–32."
            ]
        elif uso_det.startswith("urbano") or uso_det == "urbana":
            resumen = [
                "Suelo urbano consolidado: integrado en la malla urbana, con servicios urbanísticos completos; reúne la condición de solar o puede adquirirla con obras accesorias menores.",
                "Referencia: Ley 2/2016 del Suelo de Galicia, Artículo 17."
            ]
        else:
            base = _strip_accents(txt.lower())
            if ('rustico' in base) and ('urbano' not in base):
                resumen = [
                    "Suelo rústico: usos compatibles con su naturaleza (agrícolas, ganaderos, forestales, de protección ambiental e infraestructuras), evitando transformaciones urbanísticas.",
                    "Referencia: Ley 2/2016 del Suelo de Galicia, Artículos 31–32."
                ]
            elif ('urbano' in base) and ('rustico' not in base):
                resumen = [
                    "Suelo urbano consolidado: integrado en la malla urbana, con servicios urbanísticos completos; reúne la condición de solar o puede adquirirla con obras accesorias menores.",
                    "Referencia: Ley 2/2016 del Suelo de Galicia, Artículo 17."
                ]

    if wants_local and (plan is None):
        base2 = _strip_accents(txt.lower())
        resumen.append("No se encontraron parámetros en el CSV para el municipio/subzona indicados.")
        if ('rustico' in base2) and ('urbano' not in base2):
            resumen.append("Referencia: Ley 2/2016 del Suelo de Galicia, Artículos 31–32 (suelo rústico).")
        elif ('urbano' in base2) and ('rustico' not in base2):
            resumen.append("Referencia: Ley 2/2016 del Suelo de Galicia, Artículo 17 (suelo urbano).")

    if not resumen:
        resumen = ["Servicio operativo. Aporta municipio y, si lo conoces, la subzona (p. ej., Vigo RZ-2 o A Coruña NR-1)."]

    return {
        "txt": txt,
        "wants_local": wants_local,
        "muni": muni,
        "subz": subz,
        "plan": plan,
        "basic": basic,
        "resumen": resumen,
    }


def build_qa_fallback_response(pregunta: str) -> str:
    data = _build_fallback_summary(pregunta)
    msg = "\n".join(data["resumen"]) + "\n\nNota: respuesta generada en modo básico (sin modelo)."
    low = (pregunta or '').strip().lower()
    if any(x in low for x in ("hola", "buenas", "qué tal", "que tal", "hola?", "buenos días", "buenas tardes", "buenas noches")):
        return "¡Hola! Puedo ayudarte con normativa urbanística. Indícame municipio y, si procede, la subzona."
    if any(x in low for x in ("gracias", "muchas gracias", "graci")):
        return "¡De nada! Si necesitas parámetros, indícame municipio y subzona."
    if any(x in low for x in ("adios", "adiós", "hasta luego", "chao")):
        return "¡Hasta luego! Cuando quieras, seguimos con la normativa."
    if any(x in low for x in ("quien eres", "quién eres", "que puedes hacer", "qué puedes hacer")):
        return "Soy una IA especializada en normativa urbanística de Galicia. Puedo darte altura, retranqueos, ocupación y edificabilidad por municipio/subzona, y generar volúmenes 3D."
    if ("donde estoy" in low) or ("dónde estoy" in low):
        muni = _detect_municipio(low)
        if muni:
            return f"Según tu mensaje, estás consultando {muni}. Si quieres, dime la subzona y te doy parámetros."
        return "Si usas el visor, abre 'IA diag' y te diré tu municipio/subzona actuales. También puedes decirme el municipio aquí."
    return msg


def build_qa_verbose_fallback_response(pregunta: str) -> dict:
    data = _build_fallback_summary(pregunta)
    resumen = data["resumen"]
    low = data["txt"].lower()
    if any(x in low for x in ("hola", "buenas", "qué tal", "que tal", "hola?", "buenos días", "buenas tardes", "buenas noches")) and not data["wants_local"] and not data["muni"]:
        return {
            "respuesta": "¡Hola! Puedo ayudarte con normativa urbanística y el visor. Indícame municipio y, si procede, la subzona.",
            "diag": {"mode": "smalltalk"},
        }
    if any(x in low for x in ("gracias", "muchas gracias", "graci")) and not data["wants_local"]:
        return {
            "respuesta": "¡De nada! ¿Te ayudo con altura o retranqueos en algún municipio?",
            "diag": {"mode": "smalltalk"},
        }
    if any(x in low for x in ("adios", "adiós", "hasta luego", "chao")) and not data["wants_local"]:
        return {"respuesta": "¡Hasta luego!", "diag": {"mode": "smalltalk"}}
    if any(x in low for x in ("quien eres", "quién eres", "que puedes hacer", "qué puedes hacer")) and not data["wants_local"]:
        return {
            "respuesta": "Soy una IA de normativa urbanística de Galicia. Dime municipio y subzona para darte parámetros y generar un volumen.",
            "diag": {"mode": "smalltalk"},
        }
    if ("donde estoy" in low) or ("dónde estoy" in low):
        if data["muni"]:
            return {
                "respuesta": f"Parece que estás consultando {data['muni']}{(' ' + data['subz']) if data['subz'] else ''}.",
                "diag": {"mode": "fallback", "municipio": data["muni"], "subzona": data["subz"], "provider_used": "none", "fields_source": {}},
            }
        return {
            "respuesta": "No puedo conocer tu posición si no me indicas municipio (puedes usar el botón IA diag desde el visor).",
            "diag": {"mode": "fallback", "municipio": None, "subzona": None, "provider_used": "none", "fields_source": {}},
        }

    provider = 'csv' if data["plan"] is not None else None
    from_src = {}
    if data["plan"] is not None:
        fields = {
            'altura_maxima_m': getattr(data["plan"], 'altura_maxima_m', None),
            'retranqueo_min_m': getattr(data["plan"], 'retranqueo_min_m', None),
            'setback_front_m': getattr(data["plan"], 'setback_front_m', None),
            'setback_side_m': getattr(data["plan"], 'setback_side_m', None),
            'setback_back_m': getattr(data["plan"], 'setback_back_m', None),
            'ocupacion_max': getattr(data["plan"], 'ocupacion_max', None),
            'edificabilidad_max_m2_m2': getattr(data["plan"], 'edificabilidad_max_m2_m2', None),
        }
        for k, v in fields.items():
            from_src[k] = 'csv' if v is not None else 'none'
    else:
        from_src = {
            'uso_suelo': 'heuristica' if data["basic"].get('uso_suelo') else 'none',
            'altura_maxima_m': 'heuristica' if data["basic"].get('altura_maxima_m') is not None else 'none',
            'retranqueo_min_m': 'heuristica' if data["basic"].get('retranqueo_min_m') is not None else 'none',
            'setback_front_m': 'heuristica' if data["basic"].get('setback_front_m') is not None else 'none',
            'setback_side_m': 'heuristica' if data["basic"].get('setback_side_m') is not None else 'none',
            'setback_back_m': 'heuristica' if data["basic"].get('setback_back_m') is not None else 'none',
            'ocupacion_max': 'heuristica' if data["basic"].get('ocupacion_max') is not None else 'none',
            'edificabilidad_max_m2_m2': 'heuristica' if data["basic"].get('edificabilidad_max_m2_m2') is not None else 'none',
        }

    return {
        "respuesta": "\n".join(resumen) if resumen else "Sin datos suficientes. Indique municipio/subzona para mayor precisión.",
        "diag": {
            "mode": "fallback",
            "wants_local": data["wants_local"],
            "municipio": data["muni"],
            "subzona": data["subz"],
            "provider_used": provider or ('none' if not data["muni"] else 'heuristica'),
            "fields_source": from_src,
        },
    }
