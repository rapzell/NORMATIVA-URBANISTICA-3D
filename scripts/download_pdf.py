import sys
import os
import urllib.request
from urllib.parse import urlparse

def download(url: str, out_path: str | None = None) -> str:
    if not out_path:
        parsed = urlparse(url)
        name = os.path.basename(parsed.path) or 'document.pdf'
        out_path = os.path.join('datos', 'normativa', 'ACoruna', name)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent":"NormativaGalicia/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(out_path, 'wb') as f:
        f.write(r.read())
    return out_path

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: download_pdf.py <url> [out_path]')
        sys.exit(2)
    url = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    path = download(url, out)
    print(path)
