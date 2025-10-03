#!/usr/bin/env python3
r"""
Ingesta de normativa municipal (Residencial Galicia)
- Registra PDFs con metadatos mínimos
- Extrae texto por páginas a JSONL para indexación/IA

Uso (Windows):
  .\venv\Scripts\python.exe -u scripts\ingesta_normativa.py \
    --municipio Vigo \
    --pdf datos/ normativa/ Vigo/ Normativa_Urbanistica_VIGO.pdf \
    --out-jsonl datos/ normativa/ Vigo/ texto_paginas.jsonl \
    --manifest datos/ normativa/ manifest.jsonl

Nota: usa barras '/' o duplica '\\' si usas '\\' en rutas.

Requisitos: pdfplumber
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import time
from typing import Dict, Any

try:
    import pdfplumber
except Exception as e:
    print("[ingesta] pdfplumber no disponible: pip install pdfplumber", file=sys.stderr)
    raise


def md5_of_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    ensure_dir(path)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def extract_pages_to_jsonl(pdf_path: str, municipio: str, out_jsonl: str, fuente: str | None = None) -> int:
    """Extrae texto por página y lo vuelca a JSONL.
    Devuelve el número de páginas procesadas.
    """
    fuente = fuente or os.path.basename(pdf_path)
    file_id = md5_of_file(pdf_path)
    ts = int(time.time())
    pages = 0
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or '').strip()
            rec = {
                'kind': 'page_text',
                'municipio': municipio,
                'fuente': fuente,
                'file_path': pdf_path,
                'file_md5': file_id,
                'page_number': i,
                'text': text,
                'created_at': ts,
            }
            append_jsonl(out_jsonl, rec)
            pages += 1
    return pages


def append_manifest(manifest_path: str, municipio: str, pdf_path: str, pages: int) -> None:
    entry = {
        'municipio': municipio,
        'file_path': os.path.abspath(pdf_path),
        'file_name': os.path.basename(pdf_path),
        'file_md5': md5_of_file(pdf_path),
        'pages': int(pages),
        'ingested_at': int(time.time()),
    }
    append_jsonl(manifest_path, entry)


def main():
    ap = argparse.ArgumentParser(description='Ingesta de normativa municipal (Residencial)')
    ap.add_argument('--municipio', required=True, help='Nombre del municipio (p.ej., Vigo)')
    ap.add_argument('--pdf', required=True, help='Ruta al PDF de normativa')
    ap.add_argument('--out-jsonl', required=True, help='Salida JSONL con texto por páginas')
    ap.add_argument('--manifest', required=False, default='', help='Ruta JSONL de manifiesto de ficheros')
    args = ap.parse_args()

    pdf_path = args.pdf
    if not os.path.isfile(pdf_path):
        print(f"[ingesta] No se encuentra el PDF: {pdf_path}", file=sys.stderr)
        sys.exit(2)

    pages = extract_pages_to_jsonl(pdf_path, args.municipio, args.out_jsonl)
    print(f"[ingesta] Extraídas {pages} páginas a {args.out_jsonl}")
    if args.manifest:
        append_manifest(args.manifest, args.municipio, pdf_path, pages)
        print(f"[ingesta] Manifiesto actualizado: {args.manifest}")


if __name__ == '__main__':
    main()
