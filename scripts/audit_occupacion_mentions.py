import argparse
import json
import re
from typing import Iterable, Dict, Any

TERMS = [
    r"ocupaci[oó]n",
    r"porcentaje\s+de\s+ocupaci[oó]n",
    r"ocupaci[oó]n\s+en\s+planta",
    r"ocupaci[oó]n\s+de\s+la\s+parcela",
    r"ocupaci[oó]n\s+del\s+suelo",
    r"sobre\s*rasante",
]
RX = re.compile("|".join(TERMS), re.I)
NUM = re.compile(r"\b(\d{1,3}(?:[\.,]\d{3})*[\.,]\d+|\d{1,3}(?:[\.,]\d{3})*|\d+(?:[\.,]\d+)?)\s*%")


def read_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def main():
    ap = argparse.ArgumentParser(description='Auditar menciones de ocupación en JSONL de páginas')
    ap.add_argument('--jsonl', required=True, help='Ruta a texto_paginas.jsonl')
    ap.add_argument('--municipio', required=True)
    ap.add_argument('--out', default='datos/dataset/audit_ocupacion_vigo.txt')
    args = ap.parse_args()

    hits = []
    total = 0
    for rec in read_jsonl(args.jsonl):
        if (rec.get('municipio') or '').strip().lower() != args.municipio.strip().lower():
            continue
        total += 1
        text = (rec.get('text') or '')
        if RX.search(text):
            # Extract percentage if present
            mnum = NUM.search(text)
            pct = mnum.group(0) if mnum else ''
            hits.append({
                'page': rec.get('page_number'),
                'pct': pct,
                'snippet': text[:400].replace('\n',' ')
            })
    with open(args.out, 'w', encoding='utf-8') as fo:
        fo.write(f"[audit] Municipio={args.municipio} paginas={total} hits={len(hits)}\n")
        for h in hits:
            fo.write(f"p.{h['page']}  {h['pct'] or ''}  |  {h['snippet']}\n")
    print(f"[audit] Escrito informe: {args.out} (hits={len(hits)})")


if __name__ == '__main__':
    main()
