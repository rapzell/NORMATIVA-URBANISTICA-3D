#!/usr/bin/env python3
"""
Convierte anotaciones residenciales en JSONL a un CSV compatible con CSVPlanProvider.

Entrada JSONL (ver documentacion/annotaciones_residencial_schema.md):
  { municipio, subzona, altura_maxima_m, retranqueo_min_m, setback_front_m, setback_side_m, setback_back_m,
    front_direction_default, ocupacion_max, edificabilidad_max_m2_m2, source_refs, notes }

Salida CSV con cabeceras esperadas por src/planes/csv_provider.py:
  municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,
  front_direction_default,ocupacion_max,edificabilidad_max_m2_m2

Uso:
  .\venv\Scripts\python.exe -u scripts\annotations_to_csv.py \
    --jsonl datos\anotaciones\residencial.jsonl \
    --out datos\planes_residencial.csv
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from typing import Any, Dict, Tuple
from collections import Counter, defaultdict


FIELDS = [
    'municipio','subzona','altura_maxima_m','retranqueo_min_m',
    'setback_front_m','setback_side_m','setback_back_m',
    'front_direction_default','ocupacion_max','edificabilidad_max_m2_m2'
]

def normalize_subzona(s: str) -> str:
    if not s:
        return s
    s2 = s.strip()
    # quitar punto final suelto
    if s2.endswith('.'):
        s2 = s2[:-1]
    # normalizar espacios/guiones
    s2 = s2.replace(' ', '')
    # dejar mayúscula primera letra del prefijo (U, NR, NUC, etc.)
    if len(s2) >= 1:
        s2 = s2[0].upper() + s2[1:]
    # filtrar tokens genéricos conocidos
    if s2.lower() in { 'reguladora', 'general', 'ordenanza', 'titulo', 'capitulo' }:
        return ''
    return s2

def to_row(obj: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for k in FIELDS:
        v = obj.get(k)
        # Normalizar a string o vacío
        if v is None:
            row[k] = ''
        else:
            row[k] = str(v)
    # Normalizar municipio/subzona (trim)
    row['municipio'] = (row['municipio'] or '').strip()
    row['subzona'] = (row['subzona'] or '').strip()
    return row


def main():
    ap = argparse.ArgumentParser(description='JSONL anotaciones → CSV residenciales')
    ap.add_argument('--jsonl', required=True, help='Ruta a JSONL de anotaciones')
    ap.add_argument('--out', required=True, help='Ruta CSV de salida')
    args = ap.parse_args()

    rows_in: list[Dict[str, Any]] = []
    with open(args.jsonl, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            rows_in.append(obj)

    # Consolidar por (municipio, subzona) SOLO si subzona no es vacía; si está vacía, conservar filas independientes
    grouped: dict[Tuple[str, str], Dict[str, Any]] = {}
    dir_counters: dict[Tuple[str, str], Counter] = defaultdict(Counter)
    passthrough_rows: list[Dict[str, Any]] = []
    page_re = re.compile(r"\(p\.(\d+)\)")
    def get_page_hint(obj: Dict[str, Any]):
        try:
            srcs = obj.get('source_refs') or []
            if isinstance(srcs, list) and srcs:
                m = page_re.search(str(srcs[0]))
                if m:
                    return int(m.group(1))
        except Exception:
            return None
        return None
    def as_float(v):
        try:
            if v is None or v == '':
                return None
            return float(v)
        except Exception:
            return None
    for obj in rows_in:
        muni = (str(obj.get('municipio') or '').strip())
        subz = normalize_subzona(str(obj.get('subzona') or '').strip())
        if subz == '':
            # Conservar fila sin consolidar (con hint de página)
            obj['_page_hint'] = get_page_hint(obj)
            passthrough_rows.append(obj)
            continue
        key = (muni, subz)
        acc = grouped.get(key)
        if acc is None:
            acc = {k: None for k in FIELDS}
            acc['municipio'] = muni
            acc['subzona'] = subz
            acc['_page_hint'] = get_page_hint(obj)
            grouped[key] = acc
        # numéricos: tomar máximos cuando estén presentes
        for nf in ['altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','ocupacion_max','edificabilidad_max_m2_m2']:
            v = as_float(obj.get(nf))
            if v is None:
                continue
            cur = as_float(acc.get(nf))
            acc[nf] = v if (cur is None or v > cur) else cur
        # dirección: acumular y elegir moda
        fd = obj.get('front_direction_default')
        if isinstance(fd, str) and fd.strip():
            dir_counters[key][fd.strip().lower()] += 1

    # Aplicar moda para dirección
    for key, acc in grouped.items():
        cnt = dir_counters.get(key)
        if cnt:
            acc['front_direction_default'] = cnt.most_common(1)[0][0]
        else:
            acc['front_direction_default'] = ''

    # Intentar fusionar passthrough (sin subzona) hacia el grupo más cercano por página
    # Sólo si comparten municipio y la distancia de página es <= 3
    max_page_gap = 5
    for obj in passthrough_rows:
        muni = (str(obj.get('municipio') or '').strip())
        ph = obj.get('_page_hint')
        # Considerar sólo si tiene algún dato útil que aportar
        useful = any(obj.get(k) not in (None, '') for k in ['ocupacion_max','edificabilidad_max_m2_m2','altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m'])
        if not useful:
            continue
        candidates = [ (key, acc) for key, acc in grouped.items() if key[0] == muni ]
        # Elegir por distancia mínima de página
        best = None
        best_gap = None
        for key, acc in candidates:
            ah = acc.get('_page_hint')
            try:
                if ph is None or ah is None:
                    continue
                gap = abs(int(ph) - int(ah))
                if gap <= max_page_gap and (best_gap is None or gap < best_gap):
                    best = acc
                    best_gap = gap
            except Exception:
                continue
        if best is None:
            continue
        # Fusionar valores en el grupo seleccionado (mismo criterio: máximos para numéricos)
        for nf in ['altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','ocupacion_max','edificabilidad_max_m2_m2']:
            v = as_float(obj.get(nf))
            if v is None:
                continue
            cur = as_float(best.get(nf))
            best[nf] = v if (cur is None or v > cur) else cur

    # Convertir a filas CSV (consolidado) y añadir passthrough no fusionados (opcional)
    # Normalizar subzonas en salida por si quedó alguna sin limpiar
    rows = [to_row(acc) for acc in grouped.values()]
    for r in rows:
        r['subzona'] = normalize_subzona(r.get('subzona',''))
    # Nota: no añadimos passthrough para evitar duplicados en el plan consolidado
    rows.sort(key=lambda r: (r.get('municipio','').lower(), r.get('subzona','').lower()))

    with open(args.out, 'w', encoding='utf-8', newline='') as fo:
        w = csv.DictWriter(fo, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"[annotations_to_csv] Escrito CSV: {args.out} ({len(rows)} filas)")


if __name__ == '__main__':
    main()
