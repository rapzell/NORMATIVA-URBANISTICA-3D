from __future__ import annotations
import re
from typing import Any, Dict

# Número robusto: 12, 12.5, 12,50, 1.234,56, etc.
RE_NUM = r"(?:(?:\d{1,3}(?:[\.,]\d{3})*[\.,]\d+)|(?:\d{1,3}(?:[\.,]\d{3})*)|(?:\d+(?:[\.,]\d+)?))"

# Patrones comunes para parámetros urbanísticos residenciales
PATTERNS = [
    # Altura máxima (m)
    ("altura_maxima_m", re.compile(rf"altura\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"se\s*establece\s*una\s*altura\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"de\s*forma\s*gen[eé]rica\s*se\s*establece\s*una\s*altura\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*m[aá]xima\s*permitida\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*de\s*cornisa\s*(?:m[aá]xima)?\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*m[aá]xima\s*de\s*fachada\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*l[ií]mite\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*m[aá]xima\s*de\s*la\s*edificaci[oó]n\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*de\s*la\s*edificaci[oó]n\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*autorizada\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*hasta\s*(?:la\s*)?cornisa\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*hasta\s*(?:la\s*)?cubierta\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    # Variantes genéricas
    ("altura_maxima_m", re.compile(rf"una\s*altura\s*de\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*de\s*({RE_NUM})\s*(?:m\b|metro?s?\b)\s*,?\s*medidos?\s*en\s*el\s*arranque\s*de\s*la\s*cubierta", re.I)),
    ("altura_maxima_m", re.compile(rf"\baltura\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"se\s*fija\s*una\s*altura\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"se\s*autoriza\s*una\s*altura\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    # Frases U7/U10 equivalencias por plantas
    ("altura_maxima_m", re.compile(rf"bajo\s*y\s*(?:una|1)\s*planta\s*(?:equivalente\s*a\s*)?({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"bajo\s*y\s*(?:dos|2)\s*plantas\s*o\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    # Retanqueo uniforme
    ("retranqueo_min_m", re.compile(rf"retranqueo\s*(?:m[ií]nimo|general|uniforme)\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    # Setbacks direccionales
    ("setback_front_m", re.compile(rf"retranqueo\s*frontal\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    ("setback_side_m", re.compile(rf"retranqueo\s*lateral\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    ("setback_back_m", re.compile(rf"retranqueo\s*posterior\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    # Ocupación
    ("ocupacion_max_pct", re.compile(rf"ocupaci[oó]n\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max_pct", re.compile(rf"ocupaci[oó]n\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:por\s*ciento)\b", re.I)),
    ("ocupacion_max", re.compile(rf"ocupaci[oó]n\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\b", re.I)),
    ("ocupacion_max", re.compile(rf"coeficiente\s+de\s+ocupaci[oó]n\s*(?:m[aá]ximo[a]?)?\s*(?:de|:)?\s*({RE_NUM})\b", re.I)),
    ("ocupacion_max_pct", re.compile(rf"(?:porcentaje\s+de\s+)?ocupaci[oó]n(?:\s+de\s+la\s+parcela|\s+en\s+planta|\s+del\s+suelo)?\s*(?:m[aá]xima)?\s*(?:sobre\s*rasante)?\s*(?:de|:)?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max_pct", re.compile(rf"\bocupaci[oó]n\b\s*(?:m[aá]xima)?\s*[:\-]?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max", re.compile(rf"\bocupaci[oó]n\b\s*(?:m[aá]xima)?\s*[:\-]?\s*({RE_NUM})\b", re.I)),
    ("ocupacion_max_pct", re.compile(rf"\bocu(?:p\.|pac\.)\b\s*(?:m[aá]x(?:\.|ima)?)?\s*[:\-]?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max", re.compile(rf"\bocu(?:p\.|pac\.)\b\s*(?:m[aá]x(?:\.|ima)?)?\s*[:\-]?\s*({RE_NUM})\b", re.I)),
    # Edificabilidad (m2/m2)
    ("edificabilidad_max_m2_m2", re.compile(rf"edificabilidad\s*(?:m[aá]xima)?\s*(?:de|:)?\s*({RE_NUM})\s*(?:m2\s*/\s*m2|m\^?2/m\^?2|m²\s*/\s*m²)?\b", re.I)),
    ("edificabilidad_max_m2_m2", re.compile(rf"coeficiente\s+de\s+edificabilidad\s*(?:m[aá]ximo[a]?)?\s*(?:de|:)?\s*({RE_NUM})\s*(?:m2\s*/\s*m2|m\^?2/m\^?2|m²\s*/\s*m²)?\b", re.I)),
    ("edificabilidad_max_m2_m2", re.compile(rf"aprovechamiento\s*(?:urban[ií]stico)?\s*(?:m[aá]ximo[a]?)?\s*(?:de|:)?\s*({RE_NUM})\s*(?:m2\s*/\s*m2|m\^?2/m\^?2|m²\s*/\s*m²)?\b", re.I)),
    ("edificabilidad_max_m2_m2", re.compile(rf"({RE_NUM})\s*(?:m2\s*(?:techo)?\s*/\s*m2\s*(?:suelo)?|m²\s*(?:techo)?\s*/\s*m²\s*(?:suelo)?)\b", re.I)),
]

# Detección de subzona/ordenanza
SUBZ_PAT = re.compile(
    r"subzona\s*([A-Za-z0-9\-_.]+)"  # 'Subzona X'
    r"|zona\s*([A-Za-z0-9\-_.]+)"     # 'Zona X'
    r"|ordenanza\s*([A-Za-z0-9\-_.]+)"  # 'Ordenanza U9.2'
    , re.I)
DIR_PAT = re.compile(r"frente\s*([ns]ur|norte|sur|este|oeste)|orientaci[oó]n\s*(norte|sur|este|oeste)", re.I)
STOPWORDS_SUBZ = { 'de','del','la','el','los','las','y','en','por','para','con','sin','pr' }

# Validadores estrictos de códigos de subzona/ordenanza
_RX_U = re.compile(r"^U\d+(?:\.\d+)*$", re.I)
_RX_NR = re.compile(r"^NR\d+$", re.I)
_RX_RZ = re.compile(r"^RZ-\d+$", re.I)
_RX_NUMERIC_SUBZ = re.compile(r"^\d+(?:\.\d+)+$", re.I)  # p.ej., '2.1', '3.2.1'

def is_valid_subzona_code(s: str) -> bool:
    if not s:
        return False
    if s.lower() in STOPWORDS_SUBZ:
        return False
    return bool(
        _RX_U.match(s)
        or _RX_NR.match(s)
        or _RX_RZ.match(s)
        or _RX_NUMERIC_SUBZ.match(s)
    )


def num_to_float(s: str) -> float | None:
    s = s.replace(" ","")
    s = s.replace(",",".")
    try:
        return float(s)
    except Exception:
        return None


def extract_from_text(txt: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, rx in PATTERNS:
        m = rx.search(txt)
        if not m:
            continue
        val = m.group(1)
        if key == 'ocupacion_max_pct':
            v = num_to_float(val)
            if v is not None:
                out['ocupacion_max'] = max(0.0, min(1.0, v/100.0))
            continue
        v = num_to_float(val)
        if v is None:
            continue
        # Política: conservar máximos para altura y edificabilidad si aparecen múltiples menciones
        if key == 'altura_maxima_m' and ('altura_maxima_m' in out) and (out['altura_maxima_m'] is not None):
            try:
                out['altura_maxima_m'] = max(float(out['altura_maxima_m']), float(v))
            except Exception:
                pass
        elif key == 'edificabilidad_max_m2_m2' and ('edificabilidad_max_m2_m2' in out) and (out['edificabilidad_max_m2_m2'] is not None):
            try:
                out['edificabilidad_max_m2_m2'] = max(float(out['edificabilidad_max_m2_m2']), float(v))
            except Exception:
                pass
        else:
            if key in out and out[key] is not None:
                continue
            out[key] = v
    # Heurística de respaldo para ocupación (si aparece % cerca de 'ocup...')
    if 'ocupacion_max' not in out:
        try:
            rx_a = re.compile(rf"ocup\w{{0,24}}[\s\S]{{0,400}}?({RE_NUM})\s*%", re.I)
            m2 = rx_a.search(txt)
            if m2:
                v = num_to_float(m2.group(1))
                if v is not None:
                    out['ocupacion_max'] = max(0.0, min(1.0, v/100.0))
            if 'ocupacion_max' not in out:
                rx_b = re.compile(rf"({RE_NUM})\s*%[\s\S]{{0,400}}?ocup\w{{0,24}}", re.I)
                m3 = rx_b.search(txt)
                if m3:
                    v = num_to_float(m3.group(1))
                    if v is not None:
                        out['ocupacion_max'] = max(0.0, min(1.0, v/100.0))
            rx_bajo = re.compile(r"bajo\s*rasante", re.I)
            if rx_bajo.search(txt):
                # Si 'ocup...' aparece cerca de 'bajo rasante' (en cualquiera de los dos órdenes), descartar
                rx_near_bajo = re.compile(rf"(ocup\w{{0,24}}[\s\S]{{0,200}}?bajo\s*rasante|bajo\s*rasante[\s\S]{{0,200}}?ocup\w{{0,24}})", re.I)
                if rx_near_bajo.search(txt):
                    if 'ocupacion_max' in out:
                        del out['ocupacion_max']
                else:
                    # Caso genérico: si se menciona 'bajo rasante' y la ocupación capturada es >= 0.95, descartar por prudencia
                    if ('ocupacion_max' in out) and (out['ocupacion_max'] is not None):
                        ov = float(out['ocupacion_max'])
                        if ov >= 0.95:
                            del out['ocupacion_max']
        except Exception:
            pass
    # Normalización: si ocupación parece porcentaje en lugar de fracción, convertir
    try:
        if 'ocupacion_max' in out and out['ocupacion_max'] is not None:
            ov = float(out['ocupacion_max'])
            if ov > 1.5:  # 30 -> 0.30; 100 -> 1.0
                out['ocupacion_max'] = max(0.0, min(1.0, ov/100.0))
    except Exception:
        pass
    # Salvaguarda: si el texto trata sobre 'bajo rasante', no inferir ocupación sobre rasante
    try:
        if re.search(r"bajo\s*rasante", txt, re.I):
            if 'ocupacion_max' in out:
                del out['ocupacion_max']
    except Exception:
        pass
    # Subzona desde encabezados
    msub = SUBZ_PAT.search(txt)
    if msub:
        sz = (msub.group(1) or msub.group(2) or msub.group(3) or '').strip()
        sz_norm = re.sub(r"[^A-Za-z0-9\-_.]","", sz)
        if sz_norm.endswith('.'):
            sz_norm = sz_norm.rstrip('.')
        if is_valid_subzona_code(sz_norm):
            out['subzona'] = sz_norm
    # Heurística de altura por rango (p.ej., 7-9 m) si no se detectó altura explícita
    try:
        if 'altura_maxima_m' not in out or out.get('altura_maxima_m') is None:
            # Buscar patrones tipo 'altura ... 7-9 m' o 'ábaco ... 7–9 m'
            rx_range = re.compile(r"(?:altura|ábaco)[\s\S]{0,120}?" + rf"({RE_NUM})\s*[\-–]\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)
            mrg = rx_range.search(txt)
            if not mrg:
                # fallback: sólo rango con m
                rx_range2 = re.compile(rf"({RE_NUM})\s*[\-–]\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)
                mrg = rx_range2.search(txt)
            if mrg:
                a = num_to_float(mrg.group(1))
                b = num_to_float(mrg.group(2))
                vals = [v for v in (a, b) if isinstance(v, float)]
                if vals:
                    out['altura_maxima_m'] = max(vals)
    except Exception:
        pass
    # Dirección por defecto tentativa
    mdir = DIR_PAT.search(txt)
    if mdir:
        d = (mdir.group(1) or mdir.group(2) or '').lower()
        map_dir = {'norte':'north','sur':'south','este':'east','oeste':'west','nsur':'south'}
        out['front_direction_default'] = map_dir.get(d)
    return out
