import re, json
from pathlib import Path

P = Path('datos/normativa/Vigo/texto_paginas.jsonl')
want_codes = {'U7','U10','U 7','U 10'}
pat_height = re.compile(r"(?:altura|cornisa|cubierta|fachada|l[ií]mite)\s*(?:m[aá]xima)?[^\n\r]{0,40}?([0-9]+(?:[\.,][0-9]+)?)\s*(?:m\b|metros?)", re.IGNORECASE)
pat_any_m = re.compile(r"([0-9]+(?:[\.,][0-9]+)?)\s*(?:m\b|metros?)")

def has_code(txt: str) -> bool:
    t = txt
    return any(c in t for c in want_codes) or bool(re.search(r"Ordenanza\s+U\s*10\b", t)) or bool(re.search(r"Ordenanza\s+U\s*7\b", t))

def main():
    if not P.exists():
        print("ERROR: no existe", P)
        return
    hits = 0
    with P.open('r', encoding='utf-8') as f:
        for i, line in enumerate(f, start=1):
            try:
                obj = json.loads(line)
            except Exception:
                continue
            txt = obj.get('text') or obj.get('page_text') or obj.get('contenido') or ''
            if not isinstance(txt, str) or not txt:
                continue
            if has_code(txt):
                page = obj.get('page') or obj.get('num') or obj.get('page_num') or '?'
                m = pat_height.search(txt)
                if m:
                    hits += 1
                    print(f"[page {page} line {i}] HEIGHT: {m.group(0)}")
                    continue
                # fallback: any meters mention
                m2 = pat_any_m.search(txt)
                if m2:
                    seg = txt[max(0, m2.start()-40):m2.end()+40].replace('\n',' ')
                    print(f"[page {page} line {i}] ANY-M: ...{seg}...")
    print(f"done. hits={hits}")

if __name__ == '__main__':
    main()
