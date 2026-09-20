"""Extrae los ámbitos de planeamiento del PXOM 2025 de Vigo a JSON.

Fuentes oficiales (SIOTUGA, documento 28719 — PXOM aprobado 2025):

- ``28719nu003.pdf`` — Normativa urbanística: tablas de la Disposición
  Final Quinta con el mapa código API → instrumento incorporado
  (tipo, nombre, fechas AD/DOG/BOP) y las disposiciones que recogen
  los APIs definidos en texto (API-101, API-102, API-201, API-601).
- ``28719nu004.pdf`` — Anexo I: fichas individualizadas de los
  ámbitos SUB/SUNC/PE con parámetros (edificabilidad, usos,
  ordenanza de referencia, altura, dotaciones).

Salida: ``datos/normativa/{ine}/ambitos.json``

    {
      "ine": "36057",
      "instrumento": "...",
      "generado": "...",
      "apis":   {"API-106": {...}},
      "fichas": {"SUNC-201": {...}}
    }

Uso:
    venv\\Scripts\\python.exe scripts\\extract_vigo_ambitos.py
    venv\\Scripts\\python.exe scripts\\extract_vigo_ambitos.py --match-docs
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

INE = '36057'
NU_PDF = '28719nu003.pdf'
FICHAS_PDF = '28719nu004.pdf'
BASE_SIOTUGA = ('https://siotuga.xunta.gal/siotuga/documentos/'
                'urbanismo/VIGO/documents/')

# Páginas (1-based) de nu003 con las tablas API de la Disposición
# Final Quinta: la lista SUC empieza en la 346 y sigue en la 347;
# la lista SUNC es la segunda tabla de la 347.
PAG_TABLA_SUC = (346, 347)
PAG_TABLA_SUNC_TABLA_IDX = 1  # segunda tabla de la pág. 347

_HDR_FICHA_RE = re.compile(
    r'(SOLO URBANIZABLE\s+(SUB)|SOLO URBANO NON CONSOLIDADO\s+(SUNC)|'
    r'PLAN ESPECIAL\s+(PE))[\s\-]*(\d{1,4})', re.I)
_API_INLINE_RE = re.compile(r'API[-\s]?(\d{1,4})', re.I)
_FECHA_RE = re.compile(r'\b(\d{1,2})[./](\d{1,2})[./](\d{3,4})\b')


def _norm_txt(s: str) -> str:
    t = ''.join(c for c in unicodedata.normalize('NFD', s or '')
                if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', t).strip()


def _fecha_iso(s: str | None) -> str | None:
    if not s:
        return None
    m = _FECHA_RE.search(s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 1900
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f'{y:04d}-{mo:02d}-{d:02d}'


def _extraer_apis_tablas(pdf) -> list[dict]:
    """Filas de las tablas API de la Disposición Final Quinta."""
    apis: list[dict] = []
    for pag in PAG_TABLA_SUC:
        tables = pdf.pages[pag - 1].extract_tables()
        for ti, tabla in enumerate(tables):
            # pág. 347: la 1ª tabla continúa la lista SUC, la 2ª es SUNC
            estado = 'sunc' if (pag == 347 and
                                ti == PAG_TABLA_SUNC_TABLA_IDX) else 'suc'
            for row in tabla[1:]:
                if not row or len(row) < 6:
                    continue
                celda_api = row[5] or ''
                num_m = re.search(r'\d+', celda_api)
                nombre = _norm_txt(row[1] or '')
                if not num_m:
                    continue
                if 'ELIMINADA' in (nombre + ' ' + celda_api).upper():
                    apis.append({
                        'codigo': f'API-{num_m.group(0)}',
                        'estado_ambito': 'eliminada',
                        'pagina': pag})
                    continue
                api_num = num_m.group(0)
                apis.append({
                    'codigo': f'API-{api_num}',
                    'tipo_instrumento': _norm_txt(row[0] or ''),
                    'instrumento': nombre,
                    'data_ad': _fecha_iso(row[2]) or (row[2] or '').strip()
                               or None,
                    'data_dog': _fecha_iso(row[3]),
                    'data_bop': _fecha_iso(row[4]),
                    'estado_ambito': estado,
                    'pagina': pag,
                })
    return apis


_INST_INLINE_RE = re.compile(
    r'((?:Plan\s+Parcial|Plan\s+Especial(?:\s+de\s+Protecci[oó]n\s+e\s+'
    r'Reforma\s+Interior)?|PEPRI|Modificaci[oó]n\s+Puntual|PERI|'
    r'Estudio\s+de\s+Detalle|ED)\b[^,.;:]{3,120})', re.I)


def _extraer_apis_inline(pdf) -> list[dict]:
    """APIs definidos en el texto de las disposiciones (no en tabla)."""
    encontrados: dict[str, dict] = {}
    for i in range(340, 350):
        text = pdf.pages[i].extract_text() or ''
        for m in _API_INLINE_RE.finditer(text):
            code = f'API-{m.group(1)}'
            ini = max(0, m.start() - 600)
            ctx = text[ini:m.end() + 300]
            insts = _INST_INLINE_RE.findall(ctx[:m.start() - ini])
            inst_txt = _norm_txt(insts[0]) if insts else ''
            inst_txt = re.split(
                r'\b(?:aprobada?|incluso|conforme|seguir[aá])\b',
                inst_txt, flags=re.I)[0].strip(' ,')
            fechas = _FECHA_RE.findall(ctx)
            disp_m = list(re.finditer(
                r'DISPOSICI[OÓ]N\s+(?:TRANSITORIA|FINAL|ADICIONAL)\s+'
                r'[A-ZÁÉÍÓÚÑ]+[^\n]{0,140}', text[:m.start()], re.I))
            disp = _norm_txt(disp_m[-1].group(0)) if disp_m else ''
            ctx_n = _norm_txt(ctx).lower()
            estado = ('suc' if 'consolidado' in ctx_n and
                      'non consolidado' not in ctx_n else
                      'sunc' if 'non consolidado' in ctx_n else
                      'sub' if 'urbanizable' in ctx_n else None)
            entrada = encontrados.get(code) or {
                'codigo': code,
                'estado_ambito': None,
                'pagina': i + 1,
                'menciones': [],
            }
            entrada['menciones'].append({
                'disposicion': disp,
                'instrumento_texto': inst_txt,
                'contexto': _norm_txt(ctx)[-400:],
            })
            if not entrada.get('instrumento') and inst_txt:
                entrada['instrumento'] = inst_txt
            if estado and not entrada.get('estado_ambito'):
                entrada['estado_ambito'] = estado
            elif estado and entrada.get('estado_ambito') \
                    and entrada['estado_ambito'] != estado:
                entrada['estado_ambito'] = 'mixto'
            if fechas and not entrada.get('data_ad'):
                d, mo, y = fechas[0]
                entrada['data_ad'] = _fecha_iso(f'{d}/{mo}/{y}')
            encontrados[code] = entrada
    return list(encontrados.values())


def _extraer_fichas(pdf) -> dict[str, dict]:
    """Fichas SUB/SUNC/PE del anexo nu004, una entrada por ficha."""
    fichas: dict[str, dict] = {}
    actual = None
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ''
        m = _HDR_FICHA_RE.search(text[:400])
        if m:
            clase = (m.group(2) or m.group(3) or m.group(4) or '').upper()
            codigo = f"{clase}-{int(m.group(5))}"
            if codigo not in fichas:
                actual = codigo
                lineas = text.split('\n')
                fichas[codigo] = {
                    'codigo': codigo,
                    'clase_solo': clase,
                    'denominacion': _norm_txt(lineas[1]) if len(
                        lineas) > 1 else '',
                    'pagina_inicio': i + 1,
                    'pagina_fin': i + 1,
                    'texto': text,
                }
                _parse_ficha_header(fichas[codigo], text)
                continue
        if actual:
            fichas[actual]['pagina_fin'] = i + 1
            fichas[actual]['texto'] += '\n' + text
            _parse_ficha_params(fichas[actual], text)
    for f in fichas.values():
        _parse_ficha_params(f, f['texto'])
    return fichas


def _parse_ficha_header(ficha: dict, text: str) -> None:
    m = re.search(r'CATEGOR[ÍI]A\s*(RIRU|URBA|PEP)?\s*DISTRITO\s*(\d+)',
                  text, re.I)
    if m:
        ficha['categoria'] = m.group(1).upper() if m.group(1) else None
        ficha['distrito'] = m.group(2)
    m = re.search(r'PLANO ORDENACI[OÓ]N:\s*([^\n]+)', text, re.I)
    if m:
        ficha['plano_ordenacion'] = _norm_txt(m.group(1))
    m = re.search(r'DISTRITO\s*\d+\s*(AR-[A-Z]+\s*\d+)', text, re.I)
    if m:
        ficha['codigo_ar'] = m.group(1).replace(' ', '-')
    else:
        m = re.search(r'(AR-[A-Z]+\s*\d+)', text)
        if m:
            ficha['codigo_ar'] = m.group(1).replace(' ', '-')


def _parse_ficha_params(ficha: dict, text: str) -> None:
    p = ficha.setdefault('parametros', {})
    reglas = [
        ('sup_bruta_m2', r'SUP\s+BRUTA:\s*([\d.,]+)\s*m2'),
        ('sup_computable_m2', r'SUP\s+COMPUTABLE:\s*([\d.,]+)\s*m2'),
        ('edificabilidade_m2_m2',
         r'EDIFICABILIDADE:\s*([\d.,]+)\s*m2/m2'),
        ('vivenda_proteccion_pct',
         r'VIVENDA\s+PROTECCI[OÓ]N:\s*([\d.,]+)\s*%'),
        ('sistema_actuacion', r'SISTEMA\s+DE\s+ACTUACI[OÓ]N:\s*(\w+)'),
        ('uso_global', r'USO\s+GLOBAL:\s*([^\n]{3,60})'),
        ('uso_caracteristico',
         r'USO\s+CARACTER[ÍI]STICO:\s*(\w+)'),
        ('espazos_libres_pct',
         r'ESPAZOS\s+LIBRES\s+P[ÚU]BLICOS:\s*([\d.,]+)\s*%'),
        ('equipamentos_pct',
         r'EQUIPAMENTOS\s+P[ÚU]BLICOS:\s*([\d.,]+)\s*%'),
        ('ordenanza_referencia',
         r'[Oo]rdenanza\s+de\s+referencia\s*:?\s*([A-Z]{1,4}\d*(?:\.\d+)?)'),
        ('altura_plantas',
         r'Altura\s+n[ºo]?\s*plantas?/\s*metros?:\s*([\d.,]+)'),
    ]
    for key, patron in reglas:
        if key in p:
            continue
        m = re.search(patron, text)
        if m:
            p[key] = _norm_txt(m.group(1))


def _match_docs(apis: list[dict], ine: str) -> None:
    """Cruza cada API con los documentos SIOTUGA por fecha AD + nombre."""
    from src.siotuga.document_client import listar_documentos
    try:
        docs = (listar_documentos(ine) or {}).get('documentos') or []
    except Exception as e:
        print(f'  ! listar_documentos falló: {e}')
        return
    for api in apis:
        fecha = api.get('data_ad')
        if not fecha:
            continue
        cands = [d for d in docs if (d.get('fechaaddef') or '') == fecha]
        if not cands:
            continue
        if len(cands) == 1:
            api['iddoc'] = cands[0].get('id')
            api['docnome_siotuga'] = _norm_txt(
                cands[0].get('docnome') or '')
            api['match_confianza'] = 'fecha_unica'
            continue
        # varios con la misma fecha → cobertura de tokens del
        # instrumento sobre el nombre del documento (recall)
        nom = _norm_txt(api.get('instrumento') or '').upper()
        toks = {re.sub(r'[^A-Z0-9]', '', t) for t in nom.split()}
        toks = {t for t in toks if len(t) > 3}
        scored = []
        for d in cands:
            dn = _norm_txt(d.get('docnome') or '').upper()
            dt = {re.sub(r'[^A-Z0-9]', '', t) for t in dn.split()}
            dt = {t for t in dt if len(t) > 3}
            if not toks or not dt:
                continue
            score = len(toks & dt) / len(toks)
            scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= 0.5 and (
                len(scored) == 1 or scored[0][0] > scored[1][0]):
            best_score, best = scored[0]
            api['iddoc'] = best.get('id')
            api['docnome_siotuga'] = _norm_txt(best.get('docnome') or '')
            api['match_confianza'] = f'fecha+nombre({best_score:.2f})'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ine', default=INE)
    ap.add_argument('--dir', default=None,
                    help='directorio de PDFs (def. datos/normativa/{ine})')
    ap.add_argument('--match-docs', action='store_true',
                    help='cruza APIs con documentos SIOTUGA (red)')
    args = ap.parse_args()

    base = Path(args.dir or f'datos/normativa/{args.ine}')
    nu = pdfplumber.open(str(base / NU_PDF))
    apis_tabla = _extraer_apis_tablas(nu)
    apis_inline = _extraer_apis_inline(nu)
    nu.close()

    apis: dict[str, dict] = {}
    for a in apis_tabla + apis_inline:
        cur = apis.get(a['codigo'])
        if not cur:
            apis[a['codigo']] = a
        else:
            # fusionar: la tabla aporta estructura, el texto la
            # disposición que lo recoge
            for k, v in a.items():
                if v and not cur.get(k):
                    cur[k] = v
            if a.get('menciones'):
                cur.setdefault('menciones', []).extend(a['menciones'])

    if args.match_docs:
        print('Cruzando con documentos SIOTUGA…')
        _match_docs(list(apis.values()), args.ine)

    pdf = pdfplumber.open(str(base / FICHAS_PDF))
    fichas = _extraer_fichas(pdf)
    pdf.close()

    out = {
        'ine': args.ine,
        'instrumento': 'PXOM Vigo 2025 (SIOTUGA doc. 28719, '
                       'AD 26/05/2025)',
        'generado': datetime.now(timezone.utc).isoformat(),
        'fuentes': {
            'apis': f'{NU_PDF} — Normativa urbanística, Disposición '
                    'Final Quinta (tablas y disposiciones)',
            'fichas': f'{FICHAS_PDF} — Anexo I, fichas dos ámbitos de '
                      'planeamento remitido',
            'base_url': BASE_SIOTUGA,
        },
        'apis': apis,
        'fichas': fichas,
    }
    dest = base / 'ambitos.json'
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    n_doc = sum(1 for a in apis.values() if a.get('iddoc'))
    print(f"APIs: {len(apis)} ({n_doc} con documento SIOTUGA enlazado)")
    print(f"Fichas: {len(fichas)}")
    print(f'Escrito: {dest}')
    for probe in ('API-106', 'API-601', 'API-101', 'SUNC-201', 'SUB-201'):
        hit = apis.get(probe) or fichas.get(probe)
        print(f'  {probe}:', 'OK' if hit else 'NO ENCONTRADO')


if __name__ == '__main__':
    main()
