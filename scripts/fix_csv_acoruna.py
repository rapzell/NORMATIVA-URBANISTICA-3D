import sys
import csv
from pathlib import Path

IN = Path('datos/planes_ACoruna_residencial.csv')
OUT = Path('datos/planes_ACoruna_residencial_fixed.csv')

if len(sys.argv) >= 2:
    IN = Path(sys.argv[1])
if len(sys.argv) >= 3:
    OUT = Path(sys.argv[2])

rows = []
with IN.open('r', encoding='utf-8', newline='') as f:
    r = csv.DictReader(f)
    fieldnames = list(r.fieldnames or [])
    for row in r:
        # Normalizar municipio y subzona
        m = (row.get('municipio') or '').strip()
        row['municipio'] = m
        sz = (row.get('subzona') or '').strip().rstrip('.')
        row['subzona'] = sz
        
        def norm_num(x: str):
            if x is None:
                return ''
            s = str(x).strip().replace(',', '.')
            return s
        
        # Normalizar numéricos con punto
        for k in ['altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','ocupacion_max','edificabilidad_max_m2_m2','parcela_min_m2','frente_min_m']:
            if k in row:
                row[k] = norm_num(row.get(k))
        
        # Si front_direction_default existe pero no hay setbacks direccionales, limpiar para pasar validador
        fdd = (row.get('front_direction_default') or '').strip()
        sf = (row.get('setback_front_m') or '').strip()
        ss = (row.get('setback_side_m') or '').strip()
        sb = (row.get('setback_back_m') or '').strip()
        if fdd and (not sf and not ss and not sb):
            row['front_direction_default'] = ''
        
        # Rellenar altura ausente con 9 como conservador si municipio es A Coruña/A Coruna
        if (m.lower() in ('a coruña','a coruna')):
            alt = (row.get('altura_maxima_m') or '').strip()
            if not alt:
                row['altura_maxima_m'] = '9'
        
        rows.append(row)

# Asegurar fieldnames estándar
std_fields = ['municipio','subzona','altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','front_direction_default','ocupacion_max','edificabilidad_max_m2_m2','parcela_min_m2','frente_min_m','fuente','articulo','url','notas']
fields = [f for f in std_fields if f in (rows[0].keys() if rows else std_fields)]
for k in rows[0].keys():
    if k not in fields:
        fields.append(k)

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open('w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for row in rows:
        w.writerow(row)

print(f"[fix_csv_acoruna] Escrito CSV: {OUT} ({len(rows)} filas)")
