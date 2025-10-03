import argparse
import csv
import json
from typing import Dict, Any, Iterable

FIELDS = [
    'zona', 'municipio', 'subzona',
    'altura_maxima_m', 'retranqueo_min_m', 'ocupacion_max', 'edificabilidad_max_m2_m2',
    'source_refs', 'text'
]


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
    ap = argparse.ArgumentParser(description='Exporta un dataset JSONL a CSV para curación manual')
    ap.add_argument('--in-jsonl', required=True)
    ap.add_argument('--out-csv', required=True)
    args = ap.parse_args()

    rows = []
    for rec in read_jsonl(args.in_jsonl):
        row = {k: rec.get(k) for k in FIELDS}
        # Aplanar listas simples
        if isinstance(row.get('source_refs'), list):
            row['source_refs'] = ' | '.join(map(str, row['source_refs']))
        rows.append(row)

    with open(args.out_csv, 'w', encoding='utf-8', newline='') as fo:
        w = csv.DictWriter(fo, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"[export] CSV escrito: {args.out_csv} ({len(rows)} filas)")


if __name__ == '__main__':
    main()
