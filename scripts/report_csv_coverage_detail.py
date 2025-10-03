import sys
import csv
from pathlib import Path
from collections import defaultdict

REQUIRED = [
    'municipio','subzona','altura_maxima_m','retranqueo_min_m',
    'setback_front_m','setback_side_m','setback_back_m',
    'front_direction_default','ocupacion_max','edificabilidad_max_m2_m2'
]

def analyze(csv_path: Path):
    rows = []
    with csv_path.open('r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for i, r in enumerate(reader, start=2): # header is line 1
            rows.append((i, r))
    total = len(rows)
    per_muni = defaultdict(int)
    miss_counts = defaultdict(int)
    details = []
    for line, r in rows:
        muni = (r.get('municipio') or '').strip() or '—'
        per_muni[muni] += 1
        missing = [h for h in REQUIRED if (r.get(h) is None or str(r.get(h)).strip()=='' )]
        for m in missing:
            miss_counts[m] += 1
        details.append({
            'line': line,
            'municipio': r.get('municipio',''),
            'subzona': r.get('subzona',''),
            'missing': missing,
        })
    return headers, total, dict(per_muni), dict(miss_counts), details


def to_markdown(headers, total, per_muni, miss_counts, details, src_name: str) -> str:
    md = []
    md.append(f"# Cobertura CSV: {src_name}")
    md.append("")
    md.append("## Resumen")
    md.append(f"- Filas totales: {total}")
    md.append("- Por municipio:")
    for k, v in sorted(per_muni.items()):
        md.append(f"  - {k}: {v}")
    md.append("- Columnas con más ausencias:")
    for k, v in sorted(miss_counts.items(), key=lambda x: (-x[1], x[0])):
        md.append(f"  - {k}: {v}")
    md.append("")
    md.append("## Columnas del archivo")
    md.append("```")
    md.append(','.join(headers))
    md.append("```")
    md.append("")
    md.append("## Detalle por fila (si faltan campos)")
    if not any(d['missing'] for d in details):
        md.append("Todas las filas contienen las columnas requeridas")
    else:
        for d in details:
            if not d['missing']:
                continue
            muni = d['municipio'] or '—'
            subz = d['subzona'] or '—'
            miss = ', '.join(d['missing'])
            md.append(f"- L{d['line']}: {muni} · {subz} — faltan: {miss}")
    md.append("")
    md.append("> Nota: 'subzona' vacía es válida como fila por defecto de municipio.")
    return '\n'.join(md)


def main():
    if len(sys.argv) < 3:
        print("usage: py scripts/report_csv_coverage_detail.py <csv_path> <output_md>")
        sys.exit(2)
    csv_path = Path(sys.argv[1])
    out_md = Path(sys.argv[2])
    headers, total, per_muni, miss_counts, details = analyze(csv_path)
    md = to_markdown(headers, total, per_muni, miss_counts, details, src_name=str(csv_path))
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding='utf-8')
    print(out_md)

if __name__ == '__main__':
    main()
