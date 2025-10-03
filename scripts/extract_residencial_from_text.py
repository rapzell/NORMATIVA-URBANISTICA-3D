#!/usr/bin/env python3
"""
Extractor heurístico (versión inicial) para normativa residencial desde texto por páginas (JSONL).

Lee JSONL generado por scripts/ingesta_normativa.py y propone anotaciones por municipio/subzona
usando expresiones regulares robustas para altura máxima, retranqueo(s), ocupación y edificabilidad.

Limitaciones: heurístico, dependiente del texto. La precisión mejora si el PDF tiene buen OCR.

Uso:
  .\venv\Scripts\python.exe -u scripts\extract_residencial_from_text.py \
    --municipio Vigo \
    --pages-jsonl datos\normativa\Vigo\texto_paginas.jsonl \
    --out-jsonl datos\anotaciones\residencial_sugerencias.jsonl

Salida: JSONL con objetos de anotación parcial (ver documentacion/annotaciones_residencial_schema.md)
"""
from __future__ import annotations
import argparse
import json
import os
import re
from typing import Any, Dict, List

RE_NUM = r"(?:(?:\d{1,3}(?:[\.,]\d{3})*[\.,]\d+)|(?:\d{1,3}(?:[\.,]\d{3})*)|(?:\d+(?:[\.,]\d+)?))"

# Patrones comunes (normalizados a minúsculas y sin tildes idealmente)
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
    # Variantes genéricas (controladas por contexto de bloque Ordenanza)
    ("altura_maxima_m", re.compile(rf"una\s*altura\s*de\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"altura\s*de\s*({RE_NUM})\s*(?:m\b|metro?s?\b)\s*,?\s*medidos?\s*en\s*el\s*arranque\s*de\s*la\s*cubierta", re.I)),
    ("altura_maxima_m", re.compile(rf"\baltura\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"se\s*fija\s*una\s*altura\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"se\s*autoriza\s*una\s*altura\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    # Frases típicas U7/U10 con equivalencias por plantas
    ("altura_maxima_m", re.compile(rf"bajo\s*y\s*(?:una|1)\s*planta\s*(?:equivalente\s*a\s*)?({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    ("altura_maxima_m", re.compile(rf"bajo\s*y\s*(?:dos|2)\s*plantas\s*o\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)),
    # Retanqueo mínimo uniforme
    ("retranqueo_min_m", re.compile(rf"retranqueo\s*(?:m[ií]nimo|general|uniforme)\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    # Setbacks direccionales
    ("setback_front_m", re.compile(rf"retranqueo\s*frontal\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    ("setback_side_m", re.compile(rf"retranqueo\s*lateral\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    ("setback_back_m", re.compile(rf"retranqueo\s*posterior\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)),
    # Ocupación máxima [0,1] o %
    ("ocupacion_max_pct", re.compile(rf"ocupaci[oó]n\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max_pct", re.compile(rf"ocupaci[oó]n\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\s*(?:por\s*ciento)\b", re.I)),
    ("ocupacion_max", re.compile(rf"ocupaci[oó]n\s*m[aá]xima\s*(?:de|:)?\s*({RE_NUM})\b", re.I)),
    ("ocupacion_max", re.compile(rf"coeficiente\s+de\s+ocupaci[oó]n\s*(?:m[aá]ximo[a]?)?\s*(?:de|:)?\s*({RE_NUM})\b", re.I)),
    # Variantes frecuentes: en planta / de la parcela / del suelo / sobre rasante / formato tabla
    ("ocupacion_max_pct", re.compile(rf"(?:porcentaje\s+de\s+)?ocupaci[oó]n(?:\s+de\s+la\s+parcela|\s+en\s+planta|\s+del\s+suelo)?\s*(?:m[aá]xima)?\s*(?:sobre\s*rasante)?\s*(?:de|:)?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max_pct", re.compile(rf"\bocupaci[oó]n\b\s*(?:m[aá]xima)?\s*[:\-]?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max", re.compile(rf"\bocupaci[oó]n\b\s*(?:m[aá]xima)?\s*[:\-]?\s*({RE_NUM})\b", re.I)),
    # Abreviaturas: "Ocup.", "Ocupac.", "máx." y tolerancias
    ("ocupacion_max_pct", re.compile(rf"\bocu(?:p\.|pac\.)\b\s*(?:m[aá]x(?:\.|ima)?)?\s*[:\-]?\s*({RE_NUM})\s*%\b", re.I)),
    ("ocupacion_max", re.compile(rf"\bocu(?:p\.|pac\.)\b\s*(?:m[aá]x(?:\.|ima)?)?\s*[:\-]?\s*({RE_NUM})\b", re.I)),
    # Edificabilidad (m2/m2)
    ("edificabilidad_max_m2_m2", re.compile(rf"edificabilidad\s*(?:m[aá]xima)?\s*(?:de|:)?\s*({RE_NUM})\s*(?:m2\s*/\s*m2|m\^?2/m\^?2|m²\s*/\s*m²)?\b", re.I)),
    ("edificabilidad_max_m2_m2", re.compile(rf"coeficiente\s+de\s+edificabilidad\s*(?:m[aá]ximo[a]?)?\s*(?:de|:)?\s*({RE_NUM})\s*(?:m2\s*/\s*m2|m\^?2/m\^?2|m²\s*/\s*m²)?\b", re.I)),
    ("edificabilidad_max_m2_m2", re.compile(rf"aprovechamiento\s*(?:urban[ií]stico)?\s*(?:m[aá]ximo[a]?)?\s*(?:de|:)?\s*({RE_NUM})\s*(?:m2\s*/\s*m2|m\^?2/m\^?2|m²\s*/\s*m²)?\b", re.I)),
    ("edificabilidad_max_m2_m2", re.compile(rf"({RE_NUM})\s*(?:m2\s*(?:techo)?\s*/\s*m2\s*(?:suelo)?|m²\s*(?:techo)?\s*/\s*m²\s*(?:suelo)?)\b", re.I)),
]

# Detección de subzona/ordenanza en encabezados o texto destacado
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
_RX_NUMERIC_SUBZ = re.compile(r"^\d+(?:\.\d+)+$", re.I)  # p.ej., '2.1', '3.1.2'

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

# Whitelist municipal (Vigo) como último recurso (flexible con espacios)
VIGO_WHITELIST = [
    'U6.3','U6.4','U6.5','U7','U9.1','U9.2','U9.4','U10','NR1'
]
_VIGO_RX = re.compile(
    r"(" +
    r"|".join([
        r"\b" + code.replace('.', r"\s*\.")
        .replace('U', r"U\s*")
        .replace('NR', r"NR\s*")
        for code in VIGO_WHITELIST
    ]) +
    r")\b",
    re.I
)


def num_to_float(s: str) -> float:
    s = s.replace(" ","")
    s = s.replace(",",".")
    try:
        return float(s)
    except Exception:
        return None  # type: ignore


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
        if key == 'altura_maxima_m' and ('altura_maxima_m' in out) and (out['altura_maxima_m'] is not None):
            try:
                # Conservar la mayor para evitar que frases menos específicas (p.ej., "14 m" en un área concreta)
                # sobreescriban una "altura máxima" previa de mayor rango (p.ej., 15 m general).
                out['altura_maxima_m'] = max(float(out['altura_maxima_m']), float(v))
            except Exception:
                # Si falla, no sobreescribir el valor existente
                pass
        elif key == 'edificabilidad_max_m2_m2' and ('edificabilidad_max_m2_m2' in out) and (out['edificabilidad_max_m2_m2'] is not None):
            try:
                # En caso de múltiples menciones (general vs excepción local), conservar la mayor por defecto.
                out['edificabilidad_max_m2_m2'] = max(float(out['edificabilidad_max_m2_m2']), float(v))
            except Exception:
                pass
        else:
            # No sobreescribir otros campos si ya existen; mantenemos la primera detección (más específica por orden)
            if key in out and out[key] is not None:
                continue
            out[key] = v
    # Heurística de respaldo para ocupación: porcentaje cercano a "ocup..." (multi-línea)
    if 'ocupacion_max' not in out:
        try:
            # Caso A: 'ocup...' seguido del porcentaje (hasta 400 chars, incluyendo saltos de línea)
            rx_a = re.compile(rf"ocup\w{{0,24}}[\s\S]{{0,400}}?({RE_NUM})\s*%", re.I)
            m2 = rx_a.search(txt)
            if m2:
                v = num_to_float(m2.group(1))
                if v is not None:
                    out['ocupacion_max'] = max(0.0, min(1.0, v/100.0))
            # Caso B: porcentaje seguido de 'ocup...' (a veces el % está en columna previa)
            if 'ocupacion_max' not in out:
                rx_b = re.compile(rf"({RE_NUM})\s*%[\s\S]{{0,400}}?ocup\w{{0,24}}", re.I)
                m3 = rx_b.search(txt)
                if m3:
                    v = num_to_float(m3.group(1))
                    if v is not None:
                        out['ocupacion_max'] = max(0.0, min(1.0, v/100.0))
        except Exception:
            pass
    # No considerar el 100% bajo rasante como ocupación máxima sobre rasante
    try:
        if ('ocupacion_max' in out) and (out['ocupacion_max'] is not None):
            ov = float(out['ocupacion_max'])
            if ov >= 0.95:
                rx_bajo = re.compile(r"bajo\s*rasante", re.I)
                rx_near = re.compile(rf"(ocup\w{{0,24}}[\s\S]{{0,120}}?100\s*%|100\s*%[\s\S]{{0,120}}?ocup\w{{0,24}})", re.I)
                if rx_bajo.search(txt) and rx_near.search(txt):
                    # Probablemente se refiere a ocupación bajo rasante → descartar
                    del out['ocupacion_max']
    except Exception:
        pass
    # Detección simple de subzona (si aparece en el encabezado)
    msub = SUBZ_PAT.search(txt)
    if msub:
        sz = (msub.group(1) or msub.group(2) or msub.group(3) or '').strip()
        sz_norm = re.sub(r"[^A-Za-z0-9\-_.]","", sz)
        # Eliminar punto final suelto (p.ej., 'U9.2.' -> 'U9.2') para pasar validación estricta
        if sz_norm.endswith('.'):
            sz_norm = sz_norm.rstrip('.')
        if is_valid_subzona_code(sz_norm):
            out['subzona'] = sz_norm
    # Dirección por defecto (muy tentativa)
    mdir = DIR_PAT.search(txt)
    if mdir:
        d = (mdir.group(1) or mdir.group(2) or '').lower()
        map_dir = {'norte':'north','sur':'south','este':'east','oeste':'west','nsur':'south'}
        out['front_direction_default'] = map_dir.get(d)
    return out


def main():
    ap = argparse.ArgumentParser(description='Extractor heurístico residencial desde texto por páginas (JSONL)')
    ap.add_argument('--municipio', required=True)
    ap.add_argument('--pages-jsonl', required=True)
    ap.add_argument('--out-jsonl', required=True)
    args = ap.parse_args()

    municipio = args.municipio
    os.makedirs(os.path.dirname(args.out_jsonl), exist_ok=True)
    seen_keys: set[tuple[str, str|None]] = set()
    # Memoria de subzona reciente para asignar a páginas sin encabezado claro
    last_subzona: str | None = None
    last_subzona_page: int | None = None
    max_page_gap = 10
    # Contadores de logging
    cnt_pages = 0
    cnt_blocks_total = 0
    cnt_blocks_emitted = 0
    cnt_skipped_no_fields = 0
    cnt_assigned_propagation = 0
    cnt_assigned_page_scan = 0
    cnt_assigned_whitelist = 0
    with open(args.pages_jsonl, 'r', encoding='utf-8') as f, open(args.out_jsonl, 'w', encoding='utf-8') as fo:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if (rec.get('municipio') or '').strip().lower() != municipio.strip().lower():
                continue
            txt = (rec.get('text') or '').strip()
            if not txt:
                continue
            # Parser por bloques: segmentar por encabezados 'Ordenanza <codigo>' dentro de la página
            block_sugs: List[Dict[str, Any]] = []
            try:
                # Capturar encabezados clave: 'Ordenanza ...' y 'Subzona X.Y: ...'
                ord_rx = re.compile(r"ordenanza[^\n]{0,60}", re.I)
                subz_hdr_rx = re.compile(r"subzona\s*\d+(?:\.\d+)+[^\n]{0,120}", re.I)
                matches = list(ord_rx.finditer(txt)) + list(subz_hdr_rx.finditer(txt))
                matches.sort(key=lambda m: m.start())
            except Exception:
                matches = []
            if matches:
                # Segmentar por rangos [start_i, start_{i+1}) y extraer por bloque
                for i, m in enumerate(matches):
                    start = m.start()
                    end = matches[i+1].start() if i+1 < len(matches) else len(txt)
                    seg = txt[start:end]
                    # Buscar código dentro del encabezado próximo
                    header_span = txt[m.start(): min(m.end()+50, len(txt))]
                    subz_clean = None
                    m_u_h = _RX_U.search(header_span)
                    if m_u_h:
                        subz_clean = m_u_h.group(0)
                    if not subz_clean:
                        m_nr_h = _RX_NR.search(header_span)
                        if m_nr_h:
                            subz_clean = m_nr_h.group(0)
                    if not subz_clean:
                        m_rz_h = _RX_RZ.search(header_span)
                        if m_rz_h:
                            subz_clean = m_rz_h.group(0)
                    if not subz_clean:
                        # Encabezados tipo 'Subzona 2.1: ...'
                        m_num_h = re.search(r"subzona\s*(\d+(?:\.\d+)+)", header_span, re.I)
                        if m_num_h:
                            subz_clean = m_num_h.group(1)
                    seg_sug = extract_from_text(seg)
                    if seg_sug is None:
                        seg_sug = {}
                    # Guardar longitud del segmento para deduplicación posterior
                    seg_sug['_seg_len'] = len(seg)
                    # Heurística: si no hay altura explícita, intentar rango '7-9 m' o '7–9 m' cercano
                    if 'altura_maxima_m' not in seg_sug or seg_sug.get('altura_maxima_m') is None:
                        try:
                            rx_range = re.compile(r"(?:altura|ábaco)[\s\S]{0,120}?" + rf"({RE_NUM})\s*[\-–]\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)
                            mrg = rx_range.search(seg)
                            if not mrg:
                                rx_range2 = re.compile(rf"({RE_NUM})\s*[\-–]\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)
                                mrg = rx_range2.search(seg)
                            if mrg:
                                a = num_to_float(mrg.group(1))
                                b = num_to_float(mrg.group(2))
                                vals = [v for v in (a, b) if isinstance(v, float)]
                                if vals:
                                    seg_sug['altura_maxima_m'] = max(vals)
                        except Exception:
                            pass
                    # 1) Si el encabezado trae un código válido, usarlo
                    if subz_clean and is_valid_subzona_code(subz_clean):
                        seg_sug['subzona'] = subz_clean
                    else:
                        # 2) Buscar un código válido dentro del bloque
                        inner = None
                        m_u = _RX_U.search(seg)
                        if m_u:
                            inner = m_u.group(0)
                        if inner is None:
                            m_nr = _RX_NR.search(seg)
                            if m_nr:
                                inner = m_nr.group(0)
                        if inner is None:
                            m_rz = _RX_RZ.search(seg)
                            if m_rz:
                                inner = m_rz.group(0)
                        if inner is None:
                            m_num = _RX_NUMERIC_SUBZ.search(seg)
                            if m_num:
                                inner = m_num.group(0)
                        if inner and is_valid_subzona_code(inner):
                            seg_sug['subzona'] = inner
                    block_sugs.append(seg_sug)
                    cnt_blocks_total += 1
            else:
                # Fallback: extracción de toda la página
                page_sug = extract_from_text(txt) or {}
                if 'altura_maxima_m' not in page_sug or page_sug.get('altura_maxima_m') is None:
                    try:
                        rx_range_pg = re.compile(r"(?:altura|ábaco)[\s\S]{0,160}?" + rf"({RE_NUM})\s*[\-–]\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)
                        mrgp = rx_range_pg.search(txt)
                        if not mrgp:
                            rx_range2_pg = re.compile(rf"({RE_NUM})\s*[\-–]\s*({RE_NUM})\s*(?:m\b|metro?s?\b)", re.I)
                            mrgp = rx_range2_pg.search(txt)
                        if mrgp:
                            a = num_to_float(mrgp.group(1)); b = num_to_float(mrgp.group(2))
                            vals = [v for v in (a, b) if isinstance(v, float)]
                            if vals:
                                page_sug['altura_maxima_m'] = max(vals)
                    except Exception:
                        pass
                block_sugs.append(page_sug)
                cnt_blocks_total += 1

            # Emitir sugerencias válidas por bloque
            try:
                pg = int(rec.get('page_number')) if rec.get('page_number') is not None else None
            except Exception:
                pg = None
            src = rec.get('fuente') or rec.get('file_path') or 'desconocido'
            for seg_sug in block_sugs:
                # Aceptar si contiene al menos un campo clave
                if not seg_sug or not any(k in seg_sug for k in (
                    'altura_maxima_m', 'ocupacion_max', 'edificabilidad_max_m2_m2', 'retranqueo_min_m',
                    'setback_front_m','setback_side_m','setback_back_m'
                )):
                    cnt_skipped_no_fields += 1
                    continue
                # Asignar/propagar subzona
                if not seg_sug.get('subzona'):
                    if last_subzona and (pg is not None) and (last_subzona_page is not None) and (abs(pg - last_subzona_page) <= max_page_gap):
                        seg_sug['subzona'] = last_subzona
                        cnt_assigned_propagation += 1
                    else:
                        # Fallback final: intentar obtener un código válido en todo el texto de la página
                        inner_page = None
                        m_u_pg = _RX_U.search(txt)
                        if m_u_pg:
                            inner_page = m_u_pg.group(0)
                        if inner_page is None:
                            m_nr_pg = _RX_NR.search(txt)
                            if m_nr_pg:
                                inner_page = m_nr_pg.group(0)
                        if inner_page is None:
                            m_rz_pg = _RX_RZ.search(txt)
                            if m_rz_pg:
                                inner_page = m_rz_pg.group(0)
                        if inner_page is None:
                            # Buscar 'Subzona X.Y' en toda la página
                            m_num_pg = re.search(r"subzona\s*(\d+(?:\.\d+)+)", txt, re.I)
                            if m_num_pg:
                                inner_page = m_num_pg.group(1)
                        if inner_page and is_valid_subzona_code(inner_page):
                            seg_sug['subzona'] = inner_page
                            cnt_assigned_page_scan += 1
                        elif municipio.strip().lower() == 'vigo':
                            # Último recurso: whitelist municipal para PDFs con encabezados "sucios"
                            m_wh = _VIGO_RX.search(txt)
                            if m_wh:
                                cand = re.sub(r"\s+", "", m_wh.group(0))  # quitar espacios internos (e.g. 'U 9.4' -> 'U9.4')
                                if is_valid_subzona_code(cand):
                                    seg_sug['subzona'] = cand
                                    cnt_assigned_whitelist += 1
                else:
                    last_subzona = str(seg_sug.get('subzona'))
                    last_subzona_page = pg
                seg_sug['municipio'] = municipio
                seg_sug['source_refs'] = [f"{src} (p.{pg})"]
                # Deduplicación: permitir múltiples por subzona; diferenciar por campos y página
                interesting_fields = (
                    'altura_maxima_m','ocupacion_max','edificabilidad_max_m2_m2',
                    'retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m'
                )
                present = tuple(sorted([k for k in interesting_fields if k in seg_sug]))
                key = (municipio, seg_sug.get('subzona'), pg, present)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                fo.write(json.dumps(seg_sug, ensure_ascii=False) + "\n")
                cnt_blocks_emitted += 1
    print(f"[extract_residencial] Sugerencias escritas en: {args.out_jsonl}")
    # Resumen de logging
    print("[extract_residencial] resumen:")
    print(f"  bloques_total={cnt_blocks_total} emitidos={cnt_blocks_emitted} skip_sin_campos={cnt_skipped_no_fields}")
    print(f"  subzona_por_propagacion={cnt_assigned_propagation} subzona_por_escaneo_pagina={cnt_assigned_page_scan} subzona_por_whitelist={cnt_assigned_whitelist}")


if __name__ == '__main__':
    main()
