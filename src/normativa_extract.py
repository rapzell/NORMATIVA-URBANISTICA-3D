import re
from typing import Optional


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(',', '.'))
    except Exception:
        return None


def extract_normativa_fields(text: str, municipio: Optional[str] = None) -> dict:
    """Extrae campos normativos básicos de texto libre con heurística regex."""
    t = (text or "").strip()
    res: dict = {
        "municipio": municipio or None,
        "uso_suelo": None,
        "altura_maxima_m": None,
        "retranqueo_min_m": None,
        "setback_front_m": None,
        "setback_side_m": None,
        "setback_back_m": None,
        "ocupacion_max": None,
        "edificabilidad_max_m2_m2": None,
        "subzona": None,
        "referencias": [],
    }
    if not t:
        return res

    if re.search(r"\bresidencial\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "residencial"
    elif re.search(r"\bindustrial\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "industrial"
    elif re.search(r"\bcomercial\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "comercial"
    elif re.search(r"\br[úu]stic[oa]\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "rustico"
    elif re.search(r"\burbano\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "urbano"
    elif re.search(r"\burbanizable\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "urbanizable"
    elif re.search(r"\b(dotacional|equipamientos?)\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "dotacional"
    elif re.search(r"\bterciari[oa]\b", t, flags=re.IGNORECASE):
        res["uso_suelo"] = "terciario"

    m = re.search(r"altura\s*m[aá]x\.?\s*(?:permitida|m[ií]nima|\w+)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"\b(?:altura|alzada)\b[^\d]*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
    if m:
        res["altura_maxima_m"] = _to_float(m.group(1))

    rf = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*(?:al\s*frente|frontal)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
    if rf:
        res["setback_front_m"] = _to_float(rf.group(1))

    rl = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*(?:lateral(?:es)?)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
    if not rl:
        rl = re.search(r"\blateral(?:es)?\b[^\d]*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
    if rl:
        res["setback_side_m"] = _to_float(rl.group(1))

    rb = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*(?:de\s*fondo|posterior|trasero)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
    if not rb:
        rb = re.search(r"\b(?:de\s*fondo|posterior|trasero)\b[^\d]*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
    if rb:
        res["setback_back_m"] = _to_float(rb.group(1))

    if res["setback_front_m"] is None and res["retranqueo_min_m"] is None:
        r = re.search(r"retranqueo\s*(?:m[ií]n(?:imo)?)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*m\b", t, flags=re.IGNORECASE)
        if r:
            res["retranqueo_min_m"] = _to_float(r.group(1))

    occ = re.search(r"ocupaci[^\d%]*\s*(?:m[aá]x\.?|m[aá]xima)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*%?\b", t, flags=re.IGNORECASE)
    if occ:
        v = _to_float(occ.group(1))
        if v is not None:
            res["ocupacion_max"] = v / 100.0 if v > 1.0 else v

    edi = re.search(r"edificabilidad\s*(?:m[aá]x\.?|m[aá]xima)?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\s*(?:m2|m²)?\s*/\s*(?:m2|m²)\b", t, flags=re.IGNORECASE)
    if not edi:
        edi = re.search(r"edificabilidad\b[^\d]*(\d+(?:[\.,]\d+)?)\b", t, flags=re.IGNORECASE)
    if edi:
        res["edificabilidad_max_m2_m2"] = _to_float(edi.group(1))

    cz = re.search(r"\b((?:U\s*\d+(?:\.\d+)?)|(?:NR\s*-?\s*\d+))\b", t, flags=re.IGNORECASE)
    if cz:
        res["subzona"] = cz.group(1).upper().replace(" ", "").replace("NR-", "NR-")

    refs: list[str] = []
    for mref in re.findall(r"\bArt\.?\s*\d+(?:\.\d+)?\b", t, flags=re.IGNORECASE):
        refs.append(mref)
    for url in re.findall(r"https?://\S+", t, flags=re.IGNORECASE):
        refs.append(url.rstrip(').,;'))
    if refs:
        res["referencias"] = refs

    return res
