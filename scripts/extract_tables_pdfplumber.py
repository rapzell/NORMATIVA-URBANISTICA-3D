import sys, json, re, csv
from pathlib import Path

# Ensure project src is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.text_extractor import RE_NUM

NUM_RX = re.compile(RE_NUM)
KEYWORDS_PAGE = [
    'suelo urbano',
    'ordenanza',
    'residencial',
    'edificación', 'edificacion',
]
HEADER_HINTS = [
    'altura', 'cornisa', 'límite', 'limite', 'fachada', 'edificación', 'edificacion',
    'retranqueo', 'alineación', 'alineacion', 'separación', 'separacion', 'frontal', 'lateral', 'posterior', 'fondo',
    'ocupación', 'ocupacion', 'edificabilidad', 'aprovechamiento'
]


def to_float(s: str):
    if s is None:
        return None
    s2 = str(s).strip().replace(' ', '').replace(',', '.')
    m = NUM_RX.search(s2)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def cell_contains_any(cell: str, keys):
    if not cell:
        return False
    t = str(cell).lower()
    return any(k in t for k in keys)


def scan_table(rows):
    # rows: list[list[str]]
    found = {
        'altura_maxima_m': None,
        'retranqueo_min_m': None,
        'setback_front_m': None,
        'setback_side_m': None,
        'setback_back_m': None,
        'ocupacion_max': None,
        'edificabilidad_max_m2_m2': None,
    }
    if not rows or not any(any(cell_contains_any(c, HEADER_HINTS) for c in row) for row in rows[:2]):
        return None
    for row in rows:
        rowl = [str(c or '').strip().lower() for c in row]
        line = ' | '.join(rowl)
        # Altura máxima
        if 'altura' in line or 'cornisa' in line or 'fachada' in line or 'límite' in line or 'limite' in line:
            # aceptar solo alturas plausibles (0 < h <= 60 m)
            nums = [v for v in (to_float(c) for c in row) if v is not None and 0 < v <= 60]
            if nums:
                v = max(nums)
                if found['altura_maxima_m'] is None or v > found['altura_maxima_m']:
                    found['altura_maxima_m'] = v
        # Retranqueos
        if 'retranqueo' in line or 'alineación' in line or 'alineacion' in line or 'separación' in line or 'separacion' in line:
            # captar el menor (más restrictivo) dentro de rango plausible (0 < r <= 15 m)
            nums = [v for v in (to_float(c) for c in row) if v is not None and 0 < v <= 15]
            if nums:
                v = min(nums)
                if found['retranqueo_min_m'] is None or v < found['retranqueo_min_m']:
                    found['retranqueo_min_m'] = v
            # direccionales
            if 'frontal' in line:
                for c in row:
                    n = to_float(c)
                    if n is not None and 0 < n <= 15:
                        if found['setback_front_m'] is None or n > found['setback_front_m']:
                            found['setback_front_m'] = n
            if 'lateral' in line:
                for c in row:
                    n = to_float(c)
                    if n is not None and 0 < n <= 15:
                        if found['setback_side_m'] is None or n > found['setback_side_m']:
                            found['setback_side_m'] = n
            if 'posterior' in line or 'fondo' in line:
                for c in row:
                    n = to_float(c)
                    if n is not None and 0 < n <= 15:
                        if found['setback_back_m'] is None or n > found['setback_back_m']:
                            found['setback_back_m'] = n
        # Ocupación
        if 'ocupación' in line or 'ocupacion' in line:
            # aceptar valores en [0..100] como % o [0..1.0] como fracción
            nums_raw = [to_float(c) for c in row]
            nums = []
            for x in nums_raw:
                if x is None:
                    continue
                if 0 <= x <= 1.0:
                    nums.append(x)
                elif 0 < x <= 100:
                    nums.append(x/100.0)
            if nums:
                v = max(nums)
                # clamp a [0,1]
                v = max(0.0, min(1.0, v))
                if found['ocupacion_max'] is None or v > found['ocupacion_max']:
                    found['ocupacion_max'] = v
        # Edificabilidad
        if 'edificabilidad' in line or 'aprovechamiento' in line:
            # edificabilidad (m2/m2) plausible [0..5]
            nums = [v for v in (to_float(c) for c in row) if v is not None and 0 < v <= 5]
            if nums:
                v = max(nums)
                if found['edificabilidad_max_m2_m2'] is None or v > found['edificabilidad_max_m2_m2']:
                    found['edificabilidad_max_m2_m2'] = v
    if any(v is not None for v in found.values()):
        return found
    return None


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error":"usage: python extract_tables_pdfplumber.py <pdf_path> [export_csv_path] [filters_comma_separated]"}))
        sys.exit(1)
    pdf = Path(sys.argv[1])
    export_csv = Path(sys.argv[2]) if len(sys.argv) >= 3 and sys.argv[2] else None
    filters = None
    if len(sys.argv) >= 4 and sys.argv[3]:
        filters = [s.strip().lower() for s in sys.argv[3].split(',') if s.strip()]
    try:
        import pdfplumber
    except Exception as e:
        print(json.dumps({"error": f"pdfplumber not available: {e}"}))
        sys.exit(2)
    if not pdf.exists():
        print(json.dumps({"error": f"file not found: {pdf}"}))
        sys.exit(3)

    agg = {
        'altura_maxima_m': None,
        'retranqueo_min_m': None,
        'setback_front_m': None,
        'setback_side_m': None,
        'setback_back_m': None,
        'ocupacion_max': None,
        'edificabilidad_max_m2_m2': None,
    }
    total_tables = 0
    relevant_pages = 0
    with pdfplumber.open(str(pdf)) as pdf_doc:
        for page in pdf_doc.pages:
            txt = (page.extract_text() or '').lower()
            keys = filters or KEYWORDS_PAGE
            if not any(k in txt for k in keys):
                continue
            relevant_pages += 1
            # Try multiple table extraction settings
            settings_list = [
                {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
                {"vertical_strategy": "text", "horizontal_strategy": "lines"},
                {"vertical_strategy": "lines", "horizontal_strategy": "text"},
                {"vertical_strategy": "text", "horizontal_strategy": "text"},
            ]
            for ts in settings_list:
                try:
                    tables = page.extract_tables(table_settings=ts)
                except Exception:
                    tables = []
                for t in tables or []:
                    total_tables += 1
                    res = scan_table(t)
                    if not res:
                        continue
                    # merge into agg
                    for k, v in res.items():
                        if v is None:
                            continue
                        if k == 'retranqueo_min_m':
                            if agg[k] is None or v < agg[k]:
                                agg[k] = v
                        elif k in ('altura_maxima_m','setback_front_m','setback_side_m','setback_back_m','ocupacion_max','edificabilidad_max_m2_m2'):
                            if agg[k] is None or v > agg[k]:
                                agg[k] = v
    out = {"pdf": str(pdf), "relevant_pages": relevant_pages, "total_tables_scanned": total_tables, "params": agg}
    if export_csv is not None:
        export_csv.parent.mkdir(parents=True, exist_ok=True)
        with export_csv.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['municipio','subzona','altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','front_direction_default','ocupacion_max','edificabilidad_max_m2_m2'])
            w.writerow(['Vigo','SUELO URBANO',
                        agg['altura_maxima_m'] if agg['altura_maxima_m'] is not None else '',
                        agg['retranqueo_min_m'] if agg['retranqueo_min_m'] is not None else '',
                        agg['setback_front_m'] if agg['setback_front_m'] is not None else '',
                        agg['setback_side_m'] if agg['setback_side_m'] is not None else '',
                        agg['setback_back_m'] if agg['setback_back_m'] is not None else '',
                        '',
                        agg['ocupacion_max'] if agg['ocupacion_max'] is not None else '',
                        agg['edificabilidad_max_m2_m2'] if agg['edificabilidad_max_m2_m2'] is not None else '',
                        ])
        out['exported_csv'] = str(export_csv)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()
