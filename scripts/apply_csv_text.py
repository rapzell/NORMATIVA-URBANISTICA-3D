import sys, json
from pathlib import Path
from urllib.request import Request, urlopen

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error":"usage: apply_csv_text.py <csv_path>"}))
        sys.exit(2)
    p = Path(sys.argv[1])
    txt = p.read_text(encoding='utf-8')
    payload = json.dumps({"csv_text": txt}).encode('utf-8')
    req = Request('http://127.0.0.1:8000/admin/apply-plan-csv-text', data=payload, headers={'Content-Type':'application/json'})
    with urlopen(req, timeout=20) as resp:
        print(resp.read().decode('utf-8'))

if __name__ == '__main__':
    main()
