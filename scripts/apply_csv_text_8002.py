import sys
import json
from pathlib import Path
from urllib.request import Request, urlopen

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: py scripts/apply_csv_text_8002.py <csv_path> [hostport]"}))
        sys.exit(2)
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(json.dumps({"error": f"file not found: {csv_path}"}))
        sys.exit(3)
    hostport = (sys.argv[2] if len(sys.argv) >= 3 else '127.0.0.1:8002')
    csv_text = csv_path.read_text(encoding='utf-8')
    payload = json.dumps({"csv_text": csv_text}).encode('utf-8')
    url = f"http://{hostport}/admin/apply-plan-csv-text"
    req = Request(url, data=payload, headers={'Content-Type':'application/json'})
    with urlopen(req, timeout=25) as resp:
        body = resp.read().decode('utf-8')
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = {"raw": body}
    print(json.dumps(parsed, ensure_ascii=False))

if __name__ == '__main__':
    main()
