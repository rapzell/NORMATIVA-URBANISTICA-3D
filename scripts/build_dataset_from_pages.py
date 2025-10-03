import argparse
import json
import os
from typing import Dict, Any, Iterable

"""
Construye un dataset etiquetado inicial (semi-automático) para entrenamiento a partir
de un JSONL de páginas (texto crudo) como datos/normativa/<MUNICIPIO>/texto_paginas.jsonl

- Para cada página, genera un ejemplo con los campos de destino del modelo:
  zona, municipio, subzona, altura_maxima_m, retranqueo_min_m, ocupacion_max, edificabilidad_max_m2_m2, source_refs
- Usa el extractor heurístico residencial para pre-rellenar (cuando proceda) y facilitar la anotación manual.
- Limita el número de ejemplos con --limit (por defecto 300)

Salida: JSONL con objetos listos para curación manual.
"""


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


def build_example(rec: Dict[str, Any], municipio: str) -> Dict[str, Any]:
    text = (rec.get('text') or '').strip()
    page_num = rec.get('page_number')
    fuente = rec.get('fuente') or rec.get('file_path') or 'desconocido'

    # Predicción heurística (residencial) para prefijar etiquetas
    try:
        from scripts.extract_residencial_from_text import extract_from_text
        heur = extract_from_text(text)
    except Exception:
        heur = {}

    ex: Dict[str, Any] = {
        'zona': None,  # urbano / urbanizable / rústico / núcleo (a etiquetar)
        'municipio': municipio,
        'subzona': heur.get('subzona'),
        'altura_maxima_m': heur.get('altura_maxima_m'),
        'retranqueo_min_m': heur.get('retranqueo_min_m'),
        'ocupacion_max': heur.get('ocupacion_max'),
        'edificabilidad_max_m2_m2': heur.get('edificabilidad_max_m2_m2'),
        'source_refs': [f"{fuente} (p.{page_num})"],
        'text': text,
    }
    return ex


def main():
    ap = argparse.ArgumentParser(description='Construir dataset etiquetado inicial desde JSONL de páginas')
    ap.add_argument('--municipio', required=True, help='Municipio (p. ej., Vigo)')
    ap.add_argument('--pages-jsonl', required=True, help='Ruta a texto_paginas.jsonl')
    ap.add_argument('--out-jsonl', required=True, help='Ruta de salida del dataset JSONL')
    ap.add_argument('--limit', type=int, default=300, help='Límite de ejemplos (default: 300)')
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out_jsonl) or '.', exist_ok=True)

    count = 0
    with open(args.out_jsonl, 'w', encoding='utf-8', newline='') as fo:
        for rec in read_jsonl(args.pages_jsonl):
            ex = build_example(rec, args.municipio)
            fo.write(json.dumps(ex, ensure_ascii=False) + "\n")
            count += 1
            if args.limit and count >= args.limit:
                break
    print(f"[dataset] Escrito dataset en: {args.out_jsonl} ({count} ejemplos)")


if __name__ == '__main__':
    main()
