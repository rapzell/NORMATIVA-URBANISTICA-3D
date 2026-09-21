"""Descarga selectiva de documentos del ZIP PXOM 2025 de Vigo.

El ZIP completo pesa ~12,8 GB (incluye toda la cartografía). Este
script lee el directorio central por HTTP Range y baja solo los
ficheros pedidos (normativa NU, fichas de ámbitos, índices) a
``datos/normativa/36057/pxom2025/``.

Uso:
    venv/Scripts/python.exe scripts/download_pxom2025_nu.py
    venv/Scripts/python.exe scripts/download_pxom2025_nu.py NU_01NU
"""
from __future__ import annotations

import os
import struct
import sys
import zlib

import requests

ZIP_URL = ('http://xmu.vigo.org/docs/PXOM_2025/Planeamiento_vigente/'
           '36057_PXOM_202502_AD01_01PDF_dil_sec.zip')
DEST = os.path.join('datos', 'normativa', '36057', 'pxom2025')


def _range(url: str, start: int, end: int) -> bytes:
    r = requests.get(url, headers={'Range': f'bytes={start}-{end}'},
                     timeout=120)
    r.raise_for_status()
    return r.content


def _zip_dir(url: str) -> tuple[list[dict], int]:
    r0 = requests.get(url, headers={'Range': 'bytes=0-0'}, timeout=30,
                      stream=True)
    cr = r0.headers.get('Content-Range', '')
    if '/' in cr:
        size = int(cr.split('/')[-1])
    else:
        size = int(r0.headers.get('Content-Length')
                   or requests.head(url, timeout=30)
                   .headers['Content-Length'])
    tail = _range(url, size - 2 * 1024 * 1024, size - 1)
    idx = tail.rfind(b'PK\x05\x06')
    if idx < 0:
        raise RuntimeError('EOCD no encontrado')
    eocd = tail[idx:idx + 22]
    _, _, _, _, n_cd, cd_size, cd_off, _ = struct.unpack('<4sHHHHIIH', eocd)
    if cd_off == 0xFFFFFFFF:  # ZIP64
        loc = tail[idx - 20:idx]
        _, _, eocd64_off, _ = struct.unpack('<4sIQI', loc)
        e = _range(url, eocd64_off, eocd64_off + 56)
        f = struct.unpack('<4sQHHIIQQQQ', e[:56])
        n_cd, cd_size, cd_off = f[7], f[8], f[9]
    cd = _range(url, cd_off, cd_off + cd_size - 1)
    entries = []
    i = 0
    while i < len(cd) - 46:
        if cd[i:i + 4] != b'PK\x01\x02':
            break
        f = struct.unpack('<4sHHHHHHIIIHHHHHII', cd[i:i + 46])
        nlen, elen, clen = f[10], f[11], f[12]
        name = cd[i + 46:i + 46 + nlen].decode('utf-8', 'replace')
        extra = cd[i + 46 + nlen:i + 46 + nlen + elen]
        usize, csize, lho = f[8], f[7], f[16]
        # ZIP64: los campos 0xFFFFFFFF viajan en el extra 0x0001
        # en el orden usize, csize, lho (solo los que faltan).
        if 0xFFFFFFFF in (usize, csize, lho):
            j = 0
            vals = []
            while j + 4 <= len(extra):
                tag, tlen = struct.unpack('<HH', extra[j:j + 4])
                body = extra[j + 4:j + 4 + tlen]
                if tag == 0x0001:
                    k = 0
                    for _ in range(3):
                        if k + 8 <= len(body):
                            vals.append(struct.unpack('<Q',
                                                      body[k:k + 8])[0])
                            k += 8
                    break
                j += 4 + tlen
            it = iter(vals)
            if usize == 0xFFFFFFFF:
                usize = next(it, usize)
            if csize == 0xFFFFFFFF:
                csize = next(it, csize)
            if lho == 0xFFFFFFFF:
                lho = next(it, lho)
        entries.append({'name': name, 'method': f[4], 'usize': usize,
                        'csize': csize, 'lho': lho})
        i += 46 + nlen + elen + clen
    return entries, size


def fetch_entry(url: str, entry: dict) -> bytes:
    """Lee y descomprime una entrada concreta por Range."""
    lho = entry['lho']
    lh = _range(url, lho, lho + 30 - 1)
    if lh[:4] != b'PK\x03\x04':
        raise RuntimeError(f"local header inválido: {entry['name']}")
    nlen, elen = struct.unpack('<HH', lh[26:30])
    data_off = lho + 30 + nlen + elen
    raw = _range(url, data_off, data_off + entry['csize'] - 1)
    if entry['method'] == 0:
        return raw
    if entry['method'] == 8:
        return zlib.decompress(raw, -15)
    raise RuntimeError(f"método {entry['method']} no soportado")


def main() -> None:
    patron = sys.argv[1] if len(sys.argv) > 1 else None
    entries, size = _zip_dir(ZIP_URL)
    print(f'ZIP: {size / 1e9:.1f} GB, {len(entries)} entradas')
    os.makedirs(DEST, exist_ok=True)
    if patron:
        targets = [e for e in entries if patron.lower() in e['name'].lower()]
    else:
        # Por defecto: solo la normativa urbanística 2025
        targets = [e for e in entries if '/07.NU/' in e['name']
                   and e['usize'] > 0]
    for e in targets:
        base = os.path.basename(e['name'])
        dst = os.path.join(DEST, base)
        if os.path.exists(dst) and os.path.getsize(dst) == e['usize']:
            print(f'  ya existe: {base}')
            continue
        print(f"  bajando {base} ({e['usize'] / 1e6:.1f} MB)...",
              end=' ', flush=True)
        data = fetch_entry(ZIP_URL, e)
        if base.lower().endswith('.pdf'):
            assert data[:5] == b'%PDF-', f'{base}: firma PDF ausente'
        if len(data) != e['usize']:
            print(f'(aviso: {len(data)} B descomprimidos vs '
                  f"{e['usize']} B declarados) ", end='')
        with open(dst, 'wb') as fh:
            fh.write(data)
        print('ok')


if __name__ == '__main__':
    main()
