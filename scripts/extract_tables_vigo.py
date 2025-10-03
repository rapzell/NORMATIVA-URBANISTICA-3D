import sys, json, re, csv
from pathlib import Path

# Ensure project src is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.text_extractor import RE_NUM

NUM_RX = re.compile(RE_NUM)

CAND_HEADER_KEYS = {
    'altura': ['altura', 'cornisa', 'límite', 'limite', 'fachada', 'edificación', 'edificacion'],
    'retranqueo': ['retranqueo', 'alineación', 'alineacion', 'separación', 'separacion'],
    'front': ['frontal', 'a la via', 'a la calle', 'alineación', 'alineacion'],
    'side': ['lateral'],
    'back': ['posterior', 'fondo'],
    'ocup': ['ocupación', 'ocupacion', 'ocup'],
    'edificab': ['edificabilidad', 'aprovechamiento'],
}


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


def classify_column(col_name: str) -> str | None:
    n = (col_name or '').strip().lower()
    for key, words in CAND_HEADER_KEYS.items():
        for w in words:
            if w in n:
                return key
    return None


def extract_from_table(df):
    # df: pandas DataFrame
    best = {
        'altura_maxima_m': None,
        'retranqueo_min_m': None,
        'setback_front_m': None,
        'setback_side_m': None,
        'setback_back_m': None,
        'ocupacion_max': None,
        'edificabilidad_max_m2_m2': None,
    }
    cols = list(df.columns)
    cls = [classify_column(c) for c in cols]
    # quick pass: if no useful columns, skip
    if not any(x in cls for x in ('altura','retranqueo','front','side','back','ocup','edificab')):
        return None
    for _, row in df.iterrows():
        for c, label in zip(cols, cls):
            val = row[c]
            num = to_float(val)
            if num is None:
                continue
            if label == 'altura':
                if best['altura_maxima_m'] is None or num > best['altura_maxima_m']:
                    best['altura_maxima_m'] = num
            elif label == 'retranqueo':
                if best['retranqueo_min_m'] is None or num < best['retranqueo_min_m']:
                    best['retranqueo_min_m'] = num
            elif label == 'front':
                if best['setback_front_m'] is None or num > best['setback_front_m']:
                    best['setback_front_m'] = num
            elif label == 'side':
                if best['setback_side_m'] is None or num > best['setback_side_m']:
                    best['setback_side_m'] = num
            elif label == 'back':
                if best['setback_back_m'] is None or num > best['setback_back_m']:
                    best['setback_back_m'] = num
            elif label == 'ocup':
                # normalize percent if clearly > 1.5
                v = num/100.0 if num > 1.5 else num
                if best['ocupacion_max'] is None or v > best['ocupacion_max']:
                    best['ocupacion_max'] = v
            elif label == 'edificab':
                if best['edificabilidad_max_m2_m2'] is None or num > best['edificabilidad_max_m2_m2']:
                    best['edificabilidad_max_m2_m2'] = num
    # Return only if something was found
    if any(v is not None for v in best.values()):
        return best
    return None


def merge_results(acc, cur):
    if not cur:
        return acc
    for k, v in cur.items():
        if v is None:
            continue
        if k == 'retranqueo_min_m':
            if acc.get(k) is None or v < acc[k]:
                acc[k] = v
        elif k in ('altura_maxima_m','setback_front_m','setback_side_m','setback_back_m','ocupacion_max','edificabilidad_max_m2_m2'):
            if acc.get(k) is None or v > acc[k]:
                acc[k] = v
    return acc


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error":"usage: python extract_tables_vigo.py <pdf_path> [export_csv_path]"}))
        sys.exit(1)
    pdf = Path(sys.argv[1])
    export_csv = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
    try:
        import camelot
    except Exception as e:
        print(json.dumps({"error": f"camelot not available: {e}"}))
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
    pages = 'all'
    had_any = False
    for flavor in ('lattice','stream'):
        try:
            tables = camelot.read_pdf(str(pdf), pages=pages, flavor=flavor)
        except Exception:
            continue
        for t in tables:
            try:
                df = t.df
            except Exception:
                continue
            # Promote first row to header if seems header-like
            if df.shape[0] >= 2:
                df.columns = df.iloc[0]
                df = df[1:]
            res = extract_from_table(df)
            if res:
                had_any = True
                agg = merge_results(agg, res)
    out = {"pdf": str(pdf), "found_any": had_any, "params": agg}
    # Export CSV row if requested
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
