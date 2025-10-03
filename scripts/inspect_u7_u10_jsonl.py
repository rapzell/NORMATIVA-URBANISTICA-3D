import json, sys
from pathlib import Path
p = Path('datos/anotaciones/Vigo_residencial_sugerencias_clean.jsonl')
count = 0
for i, line in enumerate(p.open('r', encoding='utf-8')):
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    subz = (obj.get('subzona') or '').strip()
    if subz in ('U7','U10'):
        count += 1
        print(f"--- hit #{count} (line {i+1}) subzona={subz}")
        # Imprimir campos relevantes si existen
        for k in ('altura_maxima_m','ocupacion_max','edificabilidad_max_m2_m2','retranqueo_min_m','source_page','source'): 
            if k in obj: 
                print(f"{k}: {obj[k]}")
        # Tratar de obtener el bloque de texto del que se extrajo
        text = obj.get('text') or obj.get('fragment') or obj.get('bloque') or obj.get('raw') or ''
        if isinstance(text, str) and text:
            print('text:', text[:600].replace('\n',' '))
        else:
            # si hay un campo 'context' o similar
            ctx = obj.get('context') or obj.get('page_text') or ''
            if isinstance(ctx, str) and ctx:
                print('context:', ctx[:600].replace('\n',' '))
        print()
print(f"total hits: {count}")
