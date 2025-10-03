import csv
import io
import sys
import json
from urllib.request import Request, urlopen

CSV_PATH = 'datos/planes_Vigo_residencial.csv'
PATCH = {
    'U6.3': '3.5',
    'U6.4': '3.5',
    'U6.5': '3.5',
    'U9.1': '10.0',
    'U9.2': '15.0',  # usar 15.0 por defecto; la ordenanza puede tener genérico 18.0 en otros apartados
    'U9.4': '25.0',
    'U10':  '25.0',
    'U7':   '15.0',
}


def main():
    rows = []
    with open(CSV_PATH, 'r', encoding='utf-8', newline='') as f:
        rdr = csv.DictReader(f)
        fieldnames = rdr.fieldnames or []
        for r in rdr:
            subz = (r.get('subzona') or '').strip()
            if subz in PATCH and (not r.get('altura_maxima_m') or not r['altura_maxima_m'].strip()):
                r['altura_maxima_m'] = PATCH[subz]
            rows.append(r)
    with open(CSV_PATH, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    # aplicar al backend
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        csv_text = f.read()
    payload = { 'csv_text': csv_text }
    data = json.dumps(payload).encode('utf-8')
    req = Request('http://127.0.0.1:8000/admin/apply-plan-csv-text', data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=15) as resp:
        sys.stdout.write(resp.read().decode('utf-8'))


if __name__ == '__main__':
    main()
