import sys, json, re
from pathlib import Path

# Ensure src import
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.text_extractor import RE_NUM

ALT_PAT = re.compile(rf"(altura\s*(?:m[aá]xima|de\s*cornisa|l[ií]mite|de\s*la\s*edificaci[oó]n)[^\n\r]{{0,80}}?({RE_NUM})\s*(?:m\b|metros?))", re.I)
RETR_MIN_PAT = re.compile(rf"(retranqueo\s*(?:m[ií]nimo|general|uniforme)\s*(?:de|:)?\s*({RE_NUM})\s*m\b)", re.I)
FRONTAL_PAT = re.compile(rf"(retranqueo\s*frontal\s*(?:de|:)?\s*({RE_NUM})\s*m\b)", re.I)
LATERAL_PAT = re.compile(rf"(retranqueo\s*lateral\s*(?:de|:)?\s*({RE_NUM})\s*m\b)", re.I)
POST_PAT = re.compile(rf"(retranqueo\s*posterior\s*(?:de|:)?\s*({RE_NUM})\s*m\b)", re.I)

CTX = 120


def num_to_float(s: str):
    s = s.replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None


def scan_page(txt: str):
    hits = []
    for name, rx in (
        ("altura_maxima_m", ALT_PAT),
        ("retranqueo_min_m", RETR_MIN_PAT),
        ("setback_front_m", FRONTAL_PAT),
        ("setback_side_m", LATERAL_PAT),
        ("setback_back_m", POST_PAT),
    ):
        for m in rx.finditer(txt):
            seg = m.group(1)
            val = num_to_float(m.group(2))
            if val is None:
                continue
            # build short context
            start = max(0, m.start() - CTX)
            end = min(len(txt), m.end() + CTX)
            ctx = txt[start:end].replace('\n', ' ')
            hits.append({"key": name, "val": val, "text": seg, "context": ctx})
    return hits


def filter_pages(texts, filters):
    if not filters:
        return texts
    low = [f.lower() for f in filters]
    out = []
    for obj in texts:
        t = (obj.get('text') or '').lower()
        if any(f in t for f in low):
            out.append(obj)
    return out


def read_pdf_text(pdf_path: Path):
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                txt = page.extract_text() or ''
            except Exception:
                txt = ''
            yield i, txt


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: python scan_pdf_candidates.py <pdf_path> [filters comma-separated]"}))
        sys.exit(1)
    pdf = Path(sys.argv[1])
    filters = None
    if len(sys.argv) >= 3 and sys.argv[2]:
        filters = [s.strip() for s in sys.argv[2].split(',') if s.strip()]
    out = []
    for page_num, txt in read_pdf_text(pdf):
        if filters:
            tlow = txt.lower()
            if not any(f.lower() in tlow for f in filters):
                continue
        page_hits = scan_page(txt)
        if page_hits:
            for h in page_hits:
                h['page'] = page_num
                out.append(h)
    # Simple ranking: by key, then by value desc for altura, asc for retranqueos
    alturas = [h for h in out if h['key'] == 'altura_maxima_m']
    retrs = [h for h in out if h['key'] != 'altura_maxima_m']
    alturas.sort(key=lambda x: x['val'] if isinstance(x['val'], float) else -1, reverse=True)
    # For retranqueos, prefer smaller (more restrictive)
    retrs.sort(key=lambda x: x['val'] if isinstance(x['val'], float) else 1e9)
    result = {
        "top_alturas": alturas[:10],
        "top_retranqueos": retrs[:10],
        "total_hits": len(out)
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
