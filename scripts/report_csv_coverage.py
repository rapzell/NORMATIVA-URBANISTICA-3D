import sys, csv, json
from pathlib import Path

def coverage(path: Path) -> dict:
    with path.open('r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    con_altura = sum(1 for r in rows if (r.get('altura_maxima_m') or '').strip())
    con_ocup = sum(1 for r in rows if (r.get('ocupacion_max') or '').strip())
    con_edi = sum(1 for r in rows if (r.get('edificabilidad_max_m2_m2') or '').strip())
    return {
        'total': total,
        'con_altura': con_altura,
        'con_ocupacion': con_ocup,
        'con_edificabilidad': con_edi,
    }

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'usage: report_csv_coverage.py <csv_path>'}))
        sys.exit(2)
    p = Path(sys.argv[1])
    print(json.dumps(coverage(p)))
