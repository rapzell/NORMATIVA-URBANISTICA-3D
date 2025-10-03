import sys, re, csv, json, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# Extract text from ODT (content.xml)
def odt_extract_text(odt_path: Path) -> str:
    with zipfile.ZipFile(str(odt_path), 'r') as z:
        with z.open('content.xml') as f:
            xml_bytes = f.read()
    # content.xml is XML with text nodes in <text:p>, <text:h>, etc.
    # We'll strip tags and join paragraphs with newlines.
    try:
        ET.register_namespace('text', 'urn:oasis:names:tc:opendocument:xmlns:text:1.0')
    except Exception:
        pass
    root = ET.fromstring(xml_bytes)
    ns = {
        'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
        'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'
    }
    parts = []
    for tag in ['text:h','text:p','text:list','text:span','text:s']:
        ET.register_namespace(tag.split(':')[-1], ns.get(tag.split(':')[0], ''))
    # Collect paragraphs and headings in order
    for p in root.findall('.//text:h', ns) + root.findall('.//text:p', ns):
        txt = ''.join(p.itertext()).strip()
        if txt:
            parts.append(txt)
    return '\n'.join(parts)

RE_NUM = r"(?:(?:\d{1,3}(?:[\.,]\d{3})*[\.,]\d+)|(?:\d{1,3}(?:[\.,]\d{3})*)|(?:\d+(?:[\.,]\d+)?))"

num = lambda s: float(s.replace('.', '').replace(',', '.')) if s is not None else None

# Parse text heuristically into rows

def parse_text_to_rows(txt: str):
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    rows = []
    cur_muni = None
    cur = None

    def flush():
        nonlocal cur
        if cur and cur.get('municipio'):
            # normalize
            for k in ('altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','ocupacion_max','edificabilidad_max_m2_m2'):
                if k in cur and isinstance(cur[k], str) and not cur[k].strip():
                    cur[k] = None
            rows.append(cur)
        cur = None

    rx_muni = re.compile(r"^(Vigo|A\s*Coruñ?a)\b", re.I)
    rx_subz = re.compile(r"^(?:Subzona|Ordenanza)\s*[:\-]?\s*(.+)$", re.I)
    rx_u_code = re.compile(r"\b(U\s*\d+(?:\.\d+)*)\b", re.I)

    rx_alt = re.compile(rf"altura\s*(?:m[aá]xima|cornisa|edificaci[oó]n)[^\n\r]{{0,40}}?({RE_NUM})\s*(?:m\b|metro?s?)", re.I)
    rx_ret = re.compile(rf"retranqueo\s*(?:m[ií]nimo|general|uniforme)\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)
    rx_front = re.compile(rf"retranqueo\s*frontal\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)
    rx_side = re.compile(rf"retranqueo\s*lateral\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)
    rx_back = re.compile(rf"retranqueo\s*(?:posterior|fondo)\s*(?:de|:)?\s*({RE_NUM})\s*m\b", re.I)
    rx_ocup = re.compile(rf"ocupaci[oó]n[^\n\r]{{0,30}}?({RE_NUM})\s*%?\b", re.I)
    rx_edif = re.compile(rf"edificabilidad[^\n\r]{{0,30}}?({RE_NUM})\s*(?:m2\s*/\s*m2|m\^?2/m\^?2|m²\s*/\s*m²)?\b", re.I)

    for l in lines:
        m = rx_muni.search(l)
        if m:
            flush()
            cur_muni = m.group(1)
            continue
        ms = rx_subz.search(l) or rx_u_code.search(l)
        if ms:
            flush()
            name = (ms.group(1) if ms.re is rx_subz else ms.group(0)).strip()
            name = re.sub(r"\s+", " ", name)
            cur = {
                'municipio': cur_muni or '',
                'subzona': name,
                'altura_maxima_m': None,
                'retranqueo_min_m': None,
                'setback_front_m': None,
                'setback_side_m': None,
                'setback_back_m': None,
                'front_direction_default': None,
                'ocupacion_max': None,
                'edificabilidad_max_m2_m2': None,
            }
            continue
        if cur is None and cur_muni:
            # create a generic row for municipality if numeric patterns found
            pass
        if cur is None:
            continue
        a = rx_alt.search(l)
        if a and cur.get('altura_maxima_m') is None:
            cur['altura_maxima_m'] = num(a.group(1))
        r = rx_ret.search(l)
        if r and cur.get('retranqueo_min_m') is None:
            cur['retranqueo_min_m'] = num(r.group(1))
        f = rx_front.search(l)
        if f and cur.get('setback_front_m') is None:
            cur['setback_front_m'] = num(f.group(1))
        s = rx_side.search(l)
        if s and cur.get('setback_side_m') is None:
            cur['setback_side_m'] = num(s.group(1))
        b = rx_back.search(l)
        if b and cur.get('setback_back_m') is None:
            cur['setback_back_m'] = num(b.group(1))
        o = rx_ocup.search(l)
        if o and cur.get('ocupacion_max') is None:
            try:
                v = num(o.group(1))
                if v is not None:
                    cur['ocupacion_max'] = v/100.0 if v > 1.5 else v
            except Exception:
                pass
        e = rx_edif.search(l)
        if e and cur.get('edificabilidad_max_m2_m2') is None:
            cur['edificabilidad_max_m2_m2'] = num(e.group(1))

    flush()
    # Clean empty municipio rows
    rows = [r for r in rows if r.get('municipio')]
    return rows


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error":"usage: python odt_to_plan_csv.py <odt_path> <out_csv>"}))
        sys.exit(1)
    odt = Path(sys.argv[1])
    out_csv = Path(sys.argv[2])
    if not odt.exists():
        print(json.dumps({"error": f"file not found: {odt}"}))
        sys.exit(2)
    txt = odt_extract_text(odt)
    rows = parse_text_to_rows(txt)
    if not rows:
        print(json.dumps({"warning":"no rows parsed"}))
    # Write CSV
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['municipio','subzona','altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','front_direction_default','ocupacion_max','edificabilidad_max_m2_m2'])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(json.dumps({"ok": True, "rows": len(rows), "csv": str(out_csv)}))

if __name__ == '__main__':
    main()
