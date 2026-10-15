"""Extracción de parámetros urbanísticos (ocupación, edificabilidad, retranqueos,
altura, parcela mínima) desde los PDFs normativos oficiales descargados de SIOTUGA.

Estrategia: segmentar el texto por ordenanza (bloques "ORDENANZA U.N", "PE.N" o
equivalentes) y aplicar patrones sobre el apartado de "parámetros e condicións de
edificación". Cada valor se devuelve con trazabilidad: fichero, página y fragmento
de texto del que se extrajo.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

_DATOS = Path(__file__).resolve().parent.parent / 'datos' / 'normativa'
_CACHE_TTL_S = 30 * 24 * 3600  # 30 días
_EXTRACTOR_V = 5  # bump al añadir patrones: invalida el caché en disco

# Cabeceras de ordenanza: "ART. 76. ORDENANZA U1. MANTEMENTO...", "ORDENANZA U.4 ...",
# "ORDENANZA RZ-2 ...", "ORDENANZA DE RESIDENCIAL ..." (fallback genérico).
# Case-insensitive: Santiago publica "Art. 140. Ordenanza 3. ..." en
# minúsculas; el filtro ``_header_plausible`` evita falsos positivos.
_ORD_HDR = re.compile(
    r'ORDENANZA\s+([A-ZÁÉÍÓÚÑÜ]{1,5}\.?\s*\d+(?:[.\-]?\d*[A-Za-z]?)?|\d+[A-Za-z]?|[A-ZÁÉÍÓÚÑÜ]{2,}(?:\s+DE\s+[A-ZÁÉÍÓÚÑÜ]+)?)'
    r'\s*[.:\-]?\s*([^\n.]{3,90})?',
    re.I,
)
_ORD_GENERIC = re.compile(
    r'\bORDENANZA\s+([A-Z]{1,4}\.?\s*\d+(?:\.\d+)?[A-Za-z]?|\d+[A-Za-z]?)',
    re.I)
# A Coruña (PGOM 2013): los artículos 7.2.N son «NORMA ZONAL M.
# TÍTULO» y las zonas del mapa llevan código NZ_M[_subzona]. Se emite
# como código NZ_M para que ``buscar_ordenanza`` resuelva NZ_4_1→NZ_4
# por prefijo.
_NZ_HDR = re.compile(
    r'(?:7\.2\.\d+\s*[.\-–]?\s*)?NORMA\s+ZONAL\s+(\d{1,2})'
    r'\s*[.\-–]?\s*([^\n.]{3,90})?',
    re.I)

_NUM = r'(\d+(?:[.,]\d+)?)'

_PATTERNS = {
    'edificabilidad_max_m2_m2': [
        re.compile(r'edificabilidade?\s+m[áa]xima\s+(?:sobre\s+superficie\s+total[^,.]*,?\s*)?(?:establ[ée]cese|f[íi]xase|se\s+establece|é\s+de|de)?\s*(?:en|de)?\s*' + _NUM + r'\s*m2/m2', re.I),
        re.compile(r'edificabilidade?\s+m[áa]xima[^.]{0,60}?' + _NUM + r'\s*m2/m2', re.I),
        re.compile(r'edificabilidad\s+m[áa]xima[^.]{0,60}?' + _NUM + r'\s*m[²2]/m[²2]', re.I),
        re.compile(r'edificabilidade?\s+(?:de|establ[ée]cese\s+en|se\s+establece\s+en)\s*' + _NUM + r'\s*m2/m2', re.I),
    ],
    'ocupacion_max_pct': [
        re.compile(r'ocupaci[óo]n\s+m[áa]xima\s+(?:do|da|de|del|dun|dunha)?\s*' + _NUM + r'\s*%', re.I),
        re.compile(r'ocupaci[óo]n[^.]{0,50}?(?:do|da|de|del)?\s*' + _NUM + r'\s*%', re.I),
    ],
    'retranqueo_lateral_m': [
        re.compile(r'recuados?\s+laterais?\s+m[íi]nimos?\s+de\s+' + _NUM + r'\s*metros?\s+aos?\s+lindes?\s+laterais?', re.I),
        re.compile(r'retranqueos?\s+laterales?\s+m[íi]nimos?\s+de\s+' + _NUM + r'\s*metros?\s+a\s+linderos?\s+laterales?', re.I),
        re.compile(r'lindes?\s+laterais?[^.]{0,40}?de\s+' + _NUM + r'\s*metros?', re.I),
    ],
    'retranqueo_posterior_m': [
        re.compile(r'de\s+' + _NUM + r'\s*metros?\s+ao\s+linde\s+posterior', re.I),
        re.compile(r'de\s+' + _NUM + r'\s*metros?\s+al?\s+lindero\s+(?:posterior|trasero)', re.I),
        re.compile(r'linde\s+posterior[^.]{0,40}?de\s+' + _NUM + r'\s*metros?', re.I),
    ],
    'retranqueo_frontal_m': [
        re.compile(r'recuarse?[^.]{0,60}?m[áa]ximo\s+de\s+' + _NUM + r'\s*metros?', re.I),
        re.compile(r'recuado\s+(?:\w+\s+)?(?:\w+\s+)?de\s+' + _NUM + r'\s*metros?\s+(?:respecto\s+)?(?:\w+\s+)?ali', re.I),
        re.compile(r'retranqueo\s+(?:frontal|a\s+alineaci[óo]n)[^.]{0,50}?' + _NUM + r'\s*metros?', re.I),
    ],
    'altura_maxima_m': [
        re.compile(r'altura\s+m[áa]xima[^.]{0,90}?equivalente\s+a\s+' + _NUM + r'\s*metros', re.I),
        re.compile(r'altura\s+m[áa]xima\s+(?:de|f[íi]xase\s+en|establece\s+en)\s+' + _NUM + r'\s*metros', re.I),
        re.compile(r'altura\s+m[áa]xima[^.]{0,60}?' + _NUM + r'\s*metros', re.I),
        # Coruña: «será de dos plantas (B + 1) y 7,00 m» / «tope máximo
        # de 3 plantas y 9 metros» — altura tras el conteo de plantas.
        # El conector «y/e» es obligatorio: sin él, cabeceras de tabla
        # como «Nº de plantas / Altura en metros / Menor de 6 m»
        # capturarían el ancho de rúa como altura.
        re.compile(r'plantas?[\s\S]{0,35}?\s(?:y|e)\s+' + _NUM
                   + r'\s*(?:metros|m)\b', re.I),
    ],
    'altura_absoluta_m': [
        # 'sen superar os 8,50 metros medidos desde calquera punto do terreo'
        # (tope absoluto tras la altura a cornisa del art. 62.5; la cubierta
        # y el baixocuberta del art. 62.6 pueden ocupar el margen)
        re.compile(r'(?:sen|sin)\s+superar\s+(?:os|las|los)?\s*' + _NUM
                   + r'\s*metros?\s+medidos?\s+desde\s+'
                   r'(?:calquera|cualquier)\s+(?:punto|parte)', re.I),
        re.compile(r'(?:altura|cota)\s+m[áa]xima\s+absoluta[^.]{0,40}?'
                   + _NUM + r'\s*metros?', re.I),
    ],
    'parcela_minima_m2': [
        re.compile(r'parcela\s+m[íi]nima\s+de\s+' + _NUM + r'\s*m2', re.I),
        re.compile(r'parcela\s+m[íi]nima\s+de\s+' + _NUM + r'\s*m[²2]', re.I),
    ],
    'frente_minima_m': [
        re.compile(r'fronte?\s+m[íi]nima[^.]{0,40}?' + _NUM + r'\s*metros?', re.I),
    ],
    'voos_max_pct_fachada': [
        # 'sen ocupar máis do 25% da superficie de fachada' — [\s\S] permite
        # cruzar saltos de línea y refs internas con punto (artigo 62.13)
        re.compile(r'voos?[\s\S]{0,200}?' + _NUM + r'\s*%\s*da\s*superficie\s*de\s*fachada', re.I),
        re.compile(r'voos?[\s\S]{0,80}?m[áa]is\s+d[oe]\s+' + _NUM + r'\s*%', re.I),
    ],
    'entreplantas_max_pct': [
        # 'ocupar máis do cincuenta (50) por cento dos locais de planta baixa'
        re.compile(r'entreplantas?[^.]{0,160}?\(?\s*' + _NUM + r'\s*\)?\s*(?:por\s+cento|%)', re.I),
    ],
}


# Cabeceras/pies de página del BOPPO/DOG que quedan intercaladas en el
# texto extraído y pueden cortar las ventanas de búsqueda de patrones.
_BOILER_MARKED = re.compile(
    r'^[^\n]*(?:Edita:\s*Deputa|Pode verificar|sede\.depo\.gal|'
    r'C[óo]digo seguro|DOG\s+N[úu]m\.|CVE-DOG|ISSN|Dep[óo]sito legal|'
    r'boppo@depo|www\.boppo\.depo\.es)[^\n]*$', re.I | re.M)
_BOILER_EXACT = re.compile(
    r'^\s*(?:N[úu]m\.?|BOPPO|DOG|(?:Luns|Martes|M[ée]rcores|Xoves|Venres|'
    r'S[áa]bado|Domingo),[^\n]*)\s*$', re.I | re.M)
_BOILER_PAGENUM = re.compile(r'^\s*\d{3,4}\s*$', re.M)


def _clean_boilerplate(texto: str) -> str:
    t = _BOILER_MARKED.sub(' ', texto)
    t = _BOILER_EXACT.sub(' ', t)
    return _BOILER_PAGENUM.sub(' ', t)


def _tabla_ancho_rua(texto: str) -> list[dict]:
    """Tablas 'ancho de rúa → nº plantas / altura m' de ordenanzas de
    cuarteirón (U2, U3...). Solo si el bloque habla de ancho de rúa."""
    if not re.search(r'ancho\s+d[aeo]\s*(?:r[úu]a|espazo|v[íi]a)|'
                     r'n[ºo]\.?\s*de\s*plantas', texto, re.I):
        return []
    plantas_altura = r'\s*(\d{1,2})\s*(?:plantas?\.?\s*)?' + _NUM + r'\s*m\.?'
    pat_rango = re.compile(
        r'(?:desde|entre)\s+' + _NUM + r'\s*m\.?,?\s*(?:e|y|a|ata)\s*'
        r'(?:menor|menos)\s+de\s+' + _NUM + r'\s*m\.?,?' + plantas_altura, re.I)
    pat_menor = re.compile(
        r'menor\s+de\s+' + _NUM + r'\s*m\.?,?' + plantas_altura, re.I)
    pat_desde = re.compile(
        r'(?:desde|a\s+partir\s+de|m[áa]is\s+de|superior\s+a)\s+' + _NUM
        + r'\s*m\.?,?' + plantas_altura, re.I)
    rows, spans = [], []
    for m in pat_rango.finditer(texto):
        rows.append({'ancho_min_m': _numtxt(m.group(1)),
                     'ancho_max_m': _numtxt(m.group(2)),
                     'plantas': int(m.group(3)),
                     'altura_m': _numtxt(m.group(4))})
        spans.append((m.start(), m.end()))
    for m in pat_menor.finditer(texto):
        if any(s <= m.start() < e for s, e in spans):
            continue  # 'menor de' dentro de un rango ya capturado
        rows.append({'ancho_min_m': None, 'ancho_max_m': _numtxt(m.group(1)),
                     'plantas': int(m.group(2)), 'altura_m': _numtxt(m.group(3))})
    for m in pat_desde.finditer(texto):
        if any(s <= m.start() < e for s, e in spans):
            continue
        rows.append({'ancho_min_m': _numtxt(m.group(1)),
                     'ancho_max_m': None,
                     'plantas': int(m.group(2)), 'altura_m': _numtxt(m.group(3))})
    rows.sort(key=lambda r: (r['ancho_min_m'] or 0))
    return rows if len(rows) >= 2 else []


def _fmt_num(v: float | None) -> str:
    if v is None:
        return ''
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return s.replace('.', ',')


def _tabla_ancho_txt(rows: list[dict]) -> str:
    partes = []
    for r in rows:
        if r['ancho_min_m'] is None:
            tramo = f"rúa <{_fmt_num(r['ancho_max_m'])} m"
        elif r['ancho_max_m'] is None:
            tramo = f"rúa ≥{_fmt_num(r['ancho_min_m'])} m"
        else:
            tramo = (f"rúa {_fmt_num(r['ancho_min_m'])}–"
                     f"{_fmt_num(r['ancho_max_m'])} m")
        partes.append(f"{tramo}: {r['plantas']} plantas "
                      f"/ {_fmt_num(r['altura_m'])} m")
    return '; '.join(partes)


def _extract_usos(texto: str) -> list[str]:
    """Lista de usos permitidos (bullets '•' tras el apartado 'Usos.')."""
    m = re.search(r'(?im)^[ \t]*\d{0,2}\s*\.?\s*usos\s*[.:]?\s*$', texto)
    if not m:
        m = re.search(r'usos\s*(?:permitidos|autorizados)?\s*[.:]\s*\n',
                      texto, re.I)
    if not m:
        return []
    usos = []
    for line in texto[m.end():m.end() + 6000].split('\n'):
        s = line.strip()
        if re.match(r'\d{1,2}\.\s+[A-ZÁÉÍÓÚ]|ORDENANZA\b|ART\.?\s*\d', s):
            break
        bm = re.match(r'[•·\u2022]\s*(.+)', s)
        if bm:
            item = bm.group(1).strip().rstrip('.').strip()
            if len(item) > 2:
                usos.append(item)
        elif usos and s and len(usos[-1]) < 160:
            usos[-1] += ' ' + s.rstrip('.').strip()
        if len(usos) >= 20:
            break
    return usos


def _numtxt(s: str) -> float | None:
    try:
        return float(str(s).replace('.', '').replace(',', '.') if str(s).count('.') > 1 else str(s).replace(',', '.'))
    except Exception:
        try:
            return float(str(s).replace(',', '.'))
        except Exception:
            return None


def _pdf_pages_text(pdf_path: Path) -> list[str]:
    """Texto por página; usa pypdf (rápido) y devuelve lista indexada por página."""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(pdf_path))
        return [(p.extract_text() or '') for p in r.pages]
    except Exception:
        return []


def _header_plausible(texto: str, start: int, end: int, title: str) -> bool:
    """Descarta menciones de 'ORDENANZA X' que no son cabecera real:
    filas de tablas resumen (p.ej. 'ORDENANZA U9 UNIDADES Edificio Non
    Exclusivo ...' en la tabla de límites de instalaciones industriales).
    Una cabecera real va precedida de 'ART. NN.' o seguida de un título
    en mayúsculas / inicio de apartado numerado."""
    prev = texto[max(0, start - 30):start]
    if re.search(r'art\.?\s*\d+\s*[.:\-]?\s*$', prev, re.I):
        return True
    nxt = texto[end:end + 90]
    if re.match(r'\s*(?:1\s*[.):]|delimitaci[oó]n|[áa]mbito|'
                r'par[áa]metros|obxecto|usos\b|sistema)', nxt, re.I):
        return True
    cand = title or nxt[:60]
    letras = [c for c in cand if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) >= 0.7:
        return True
    return False


def _segment_ordenanzas(pages: list[str]) -> list[dict]:
    """Devuelve bloques {ordenanza, titulo, pag_ini, texto} uniendo páginas."""
    blocks = []
    current = None
    for idx, text in enumerate(pages):
        # buscar cabeceras de ordenanza en esta página
        marks = []
        for m in _ORD_HDR.finditer(text):
            code = (m.group(1) or '').strip().replace(' ', '') \
                .rstrip('.-')
            title = (m.group(2) or '').strip().rstrip('.')
            # Códigos de un solo carácter solo si son numéricos (las
            # ordenanzas de Santiago se llaman "Ordenanza 3", "7"…).
            if len(code) < 2 and not code.isdigit():
                continue
            if code.upper() in ('DE', 'LA', 'DO', 'DA', 'NON', 'QUE',
                                'ESTÁ', 'ESTA', 'O', 'A', 'E', 'SE'):
                continue
            if not _header_plausible(text, m.start(), m.end(), title):
                continue
            marks.append((m.start(), code, title))
        for gm in _ORD_GENERIC.finditer(text):
            code = gm.group(1).replace(' ', '')
            if all(abs(gm.start() - s) > 3 for s, _, _ in marks):
                if not _header_plausible(text, gm.start(), gm.end(), ''):
                    continue
                marks.append((gm.start(), code, ''))
        for nm in _NZ_HDR.finditer(text):
            code = 'NZ_' + nm.group(1)
            if all(abs(nm.start() - s) > 3 for s, _, _ in marks):
                title = (nm.group(2) or '').strip().rstrip('.')
                # Solo cabeceras con título propio o precedidas del
                # número de artículo — descarta menciones en prosa.
                prev = text[max(0, nm.start() - 30):nm.start()]
                if not title and not re.search(
                        r'art\.?\s*\d|7\.2\.\d', prev, re.I):
                    continue
                marks.append((nm.start(), code, title))
        marks.sort()
        if marks:
            if current:
                current['texto'] += '\n' + text[:marks[0][0]]
                blocks.append(current)
            current = {'ordenanza': marks[0][1], 'titulo': marks[0][2] or None,
                       'pag_ini': idx + 1, 'texto': text[marks[0][0]:]}
            for pos, code, title in marks[1:]:
                blocks.append(current)
                current = {'ordenanza': code, 'titulo': title or None,
                           'pag_ini': idx + 1, 'texto': text[pos:]}
        elif current:
            current['texto'] += '\n' + text
    if current:
        blocks.append(current)
    return blocks


# Contextos que invalidan una coincidencia: el número se refiere a otra cosa
# (altura de un peto/muro, ocupación de un proceso, etc.).
_EXCLUDE_PREV = {
    'altura_maxima_m': re.compile(r'(?:peto|muro|cerramento|cerramiento|cerca)[^.]{0,60}$', re.I),
}


def _extract_params(block: dict) -> dict:
    """Extrae parámetros con trazabilidad sobre el texto del bloque."""
    texto = _clean_boilerplate(block['texto'])
    params = {}
    trazas = {}
    for key, pats in _PATTERNS.items():
        excl = _EXCLUDE_PREV.get(key)
        for pat in pats:
            found = False
            for m in pat.finditer(texto):
                if excl and excl.search(texto[max(0, m.start() - 80):m.start()]):
                    continue
                val = _numtxt(m.group(1))
                if val is None:
                    continue
                params[key] = val
                snippet = texto[max(0, m.start() - 60):m.end() + 60]
                trazas[key] = {'pagina': block['pag_ini'], 'texto': ' '.join(snippet.split())[:220]}
                found = True
                break
            if found:
                break
    # Tabla 'ancho de rúa → plantas/altura' (ordenanzas de cuarteirón):
    # la altura depende del ancho de la calle, no es un valor único.
    rows = _tabla_ancho_rua(texto)
    if rows:
        params['altura_por_ancho_rua'] = _tabla_ancho_txt(rows)
        idx = min(texto.find(str(int(r['altura_m']))
                           if r['altura_m'] == int(r['altura_m'])
                           else _fmt_num(r['altura_m']))
                  for r in rows if r['altura_m'] is not None)
        snippet = texto[max(0, idx - 80):idx + 200] if idx >= 0 else ''
        trazas['altura_por_ancho_rua'] = {
            'pagina': block['pag_ini'], 'tabla': rows,
            'texto': ' '.join(snippet.split())[:220]}
    # Fórmulas de altura por ancho de rúa (Santiago ord. 1 Ensanche:
    # «menor de 15 m → ancho+6 m; ≥15 m → ancho×1,5»). La tabla
    # ``_tabla_ancho_rua`` solo cubre alturas fijas por tramo; aquí se
    # emiten filas con ``formula`` que ``_resolve_fila_tabla`` evalúa.
    if 'altura_por_ancho_rua' not in params and re.search(
            r'ancho\s+d[aeo]\s*r[úu]a', texto, re.I):
        partes, rows = [], []
        m = re.search(
            r'menor\s+de\s+' + _NUM + r'\s*metros?[^.]{0,90}?'
            r'sumar\s+' + _NUM + r'\s*metros?\s+ao\s+ancho', texto, re.I)
        if m:
            lim, add = _numtxt(m.group(1)), _numtxt(m.group(2))
            partes.append(f"rúa <{_fmt_num(lim)} m: "
                          f"ancho+{_fmt_num(add)} m")
            rows.append({'ancho_min_m': 0, 'ancho_max_m': lim,
                         'formula': 'ancho+', 'op_m': add})
        m = re.search(
            _NUM + r'\s*ou\s+m[áa]is\s+metros?[^.]{0,90}?'
            r'factor\s+' + _NUM, texto, re.I)
        if m:
            lim, fac = _numtxt(m.group(1)), _numtxt(m.group(2))
            partes.append(f"rúa ≥{_fmt_num(_numtxt(m.group(1)))} m: "
                          f"ancho×{_fmt_num(_numtxt(m.group(2)))}")
            rows.append({'ancho_min_m': lim, 'ancho_max_m': None,
                         'formula': 'ancho*', 'op_m': fac})
        if partes:
            params['altura_por_ancho_rua'] = '; '.join(partes)
            idx = texto.lower().find('ancho')
            snippet = texto[max(0, idx - 100):idx + 400] if idx >= 0 else ''
            trazas['altura_por_ancho_rua'] = {
                'pagina': block['pag_ini'], 'tabla': rows,
                'texto': ' '.join(snippet.split())[:300]}
    # Tablas 'N metros para N plantas' (ordenanzas de Santiago: la
    # altura se fija por número de plantas en metros, p.ej. «9,82
    # metros para 3 plantas»). El máximo es la altura máxima efectiva.
    if 'altura_maxima_m' not in params:
        tabla = re.findall(
            r'(\d+(?:[.,]\d+)?)\s*metros?\s+para\s+(\d+)\s*plantas?',
            texto, re.I)
        vals = [(float(v.replace(',', '.')), int(p)) for v, p in tabla]
        if len(vals) >= 2:
            mx = max(vals)
            params['altura_maxima_m'] = mx[0]
            m = re.search(re.escape(tabla[0][0]) + r'\s*metros?\s+para',
                          texto)
            idx = m.start() if m else 0
            snippet = texto[max(0, idx - 120):idx + 260]
            trazas['altura_maxima_m'] = {
                'pagina': block['pag_ini'],
                'tabla': [{'plantas': p, 'altura_m': v} for v, p in vals],
                'texto': ' '.join(snippet.split())[:220]}
    usos = _extract_usos(texto)
    if usos:
        params['usos_permitidos'] = '; '.join(usos)
        m = re.search(r'(?im)^[ \t]*\d{0,2}\s*\.?\s*usos\s*[.:]?\s*$', texto)
        idx = m.end() if m else 0
        trazas['usos_permitidos'] = {
            'pagina': block['pag_ini'],
            'texto': ' '.join(texto[idx:idx + 220].split())[:220]}
    # Ocupación condicional: cuarteirón compacto sin indicación en
    # planos → puede ocupar toda la parcela edificable (no es un % fijo).
    if 'ocupacion_max_pct' not in params:
        m = re.search(r'ocupaci[óo]n\s+da\s+totalidade\s+da\s+parcela\s+'
                      r'edificable', texto, re.I)
        if m:
            params['ocupacion_condicional'] = (
                'ata o 100% da parcela edificable (cuarteirón compacto '
                'sen indicación en planos)')
            snippet = texto[max(0, m.start() - 80):m.end() + 60]
            trazas['ocupacion_condicional'] = {
                'pagina': block['pag_ini'],
                'texto': ' '.join(snippet.split())[:220]}
    return params, trazas


# ——— A Coruña (PGOM 2013): parámetros por subzona ———
# Las normas zonales (NZ_N) fijan parámetros por subzona con dos
# formatos:
#   A) secciones por letra «a)- Condiciones de la edificación en X.
#      (4.1)» (NZ_4), o
#   B) listados «Subzona N.- valor» bajo cada epígrafe de parámetro
#      (NZ_5, NZ_6…).
_CORUNA_SUB_SEC = re.compile(
    r'(?:^|\n)\s*([a-h])\)\s*[-–]?\s*Condiciones[\s\S]{0,220}?'
    r'\(\s*(?:subzona[s]?\s*)?\d+\.(\d+)\s*\)', re.I)
_CORUNA_SUB_ROW = re.compile(
    r'(?:^|\n)\s*[-–•·]{0,3}\s*Subzona\s+(\d+)(?:\(\d+\))?\s*[.:\-–\s]+'
    + _NUM + r'\s*(m2/m2|m2|m\b|%)', re.I)


def _numtxt_es(s: str) -> float | None:
    """Número con separador de miles español: '1.000'→1000, '0,35'→0.35."""
    s = str(s).strip()
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', s):      # miles con '.'
        return float(s.replace('.', ''))
    return _numtxt(s)


def _coruna_subsecciones(block: dict) -> list[tuple[int, str]]:
    """Secciones por letra con nº de subzona explícito → [(num, texto)]."""
    texto = block['texto']
    marks = []
    for m in _CORUNA_SUB_SEC.finditer(texto):
        # descarta secciones anidadas «a.5)-» (llevan punto tras letra)
        if re.match(r'[a-h]\.\d', texto[m.start():m.start() + 6]):
            continue
        marks.append((m.start(), int(m.group(2))))
    out = []
    for i, (pos, num) in enumerate(marks):
        fin = marks[i + 1][0] if i + 1 < len(marks) else len(texto)
        out.append((num, texto[pos:fin]))
    return out


_CORUNA_PARAM_CTX = re.compile(
    r'parcela\s+m[íi]nima|altura\s+de\s+la\s+edificaci[oó]n|'
    r'altura\s+m[áa]xima|altura[s]?\b|edificabilidad|ocupaci[oó]n|'
    r'metros?\s+y\s+n[úu]mero\s+de\s+plantas', re.I)
_CORUNA_PARAM_KEY = [
    (re.compile(r'parcela\s+m[íi]nima', re.I), 'parcela_minima_m2'),
    (re.compile(r'altura|metros?\s+y\s+n[úu]mero\s+de\s+plantas',
                re.I), 'altura_maxima_m'),
    (re.compile(r'edificabilidad', re.I), 'edificabilidad_max_m2_m2'),
    (re.compile(r'ocupaci[oó]n', re.I), 'ocupacion_max_pct'),
]


def _coruna_listas(block: dict) -> dict[int, dict]:
    """Listados «Subzona N.- valor» bajo epígrafes de parámetro
    (NZ_5, NZ_6…). Solo filas al inicio de línea con valor y unidad,
    agrupadas (≥2 filas por epígrafe) para descartar menciones en prosa.
    Devuelve {num_subzona: {param: valor}}."""
    texto = block['texto']
    # filas candidatas agrupadas por epígrafe de parámetro
    grupos: dict[str, list[tuple[int, float]]] = {}
    for m in _CORUNA_SUB_ROW.finditer(texto):
        ctx = texto[max(0, m.start() - 800):m.start()]
        ctxs = list(_CORUNA_PARAM_CTX.finditer(ctx))
        if not ctxs:
            continue
        last = ctxs[-1].group(0).lower()
        key = next((k for pat, k in _CORUNA_PARAM_KEY
                    if pat.search(last)), None)
        if not key:
            continue
        val = _numtxt_es(m.group(2))
        if val is not None:
            grupos.setdefault(key, []).append((int(m.group(1)), val))
    out: dict[int, dict] = {}
    for key, rows in grupos.items():
        if len({n for n, _ in rows}) < 2:
            continue  # una sola fila = probable mención en prosa
        for num, val in rows:
            out.setdefault(num, {})[key] = val
    return out


# NZ_2 (Ensanche): tres tablas «ancho de calle → nº de plantas» según la
# configuración de manzana; cada configuración cubre varias subzonas.
_CORUNA_NZ2_CFG = re.compile(
    r'Configuraci[oó]n\s+(semiintensiva|intensiva|perif[eé]rica)'
    r'([\s\S]{0,600}?)(?=Configuraci[oó]n|2\.\-|Criterio)', re.I)
_CORUNA_NZ2_ROWS = [
    # '10 ≤ A < 12 m 4'  (orden: rango antes que los casos sueltos)
    (re.compile(_NUM + r'\s*[≤<]?\s*A\s*<\s*' + _NUM + r'\s*m\s*(\d{1,2})\b', re.I),
     lambda m: {'ancho_min_m': _numtxt(m.group(1)),
                'ancho_max_m': _numtxt(m.group(2)),
                'plantas': int(m.group(3))}),
    # 'A ≥ 25 m 8'
    (re.compile(r'A\s*[≥>]\s*' + _NUM + r'\s*m\s*(\d{1,2})\b', re.I),
     lambda m: {'ancho_min_m': _numtxt(m.group(1)),
                'ancho_max_m': None, 'plantas': int(m.group(2))}),
    # 'A < 10 m 3'
    (re.compile(r'A\s*<\s*' + _NUM + r'\s*m\s*(\d{1,2})\b', re.I),
     lambda m: {'ancho_min_m': 0, 'ancho_max_m': _numtxt(m.group(1)),
                'plantas': int(m.group(2))}),
]
_CORUNA_NZ2_SUBZONAS = {
    'semiintensiva': (1, 2),     # calle / manzana semi-intensiva
    'intensiva': (3, 4),         # calle / manzana intensiva
    'periférica': (5,),          # manzana periférica
}


def _coruna_nz2_tablas(block: dict) -> dict[int, list[dict]]:
    """Tablas de plantas por ancho de calle de NZ_2 → {subzona: rows}."""
    out: dict[int, list[dict]] = {}
    for m in _CORUNA_NZ2_CFG.finditer(block['texto']):
        cfg = m.group(1).lower()
        seg = m.group(2)
        rows: list[dict] = []
        spans: list[tuple[int, int]] = []
        for pat, mk in _CORUNA_NZ2_ROWS:
            for rm in pat.finditer(seg):
                if any(s <= rm.start() < e for s, e in spans):
                    continue
                rows.append(mk(rm))
                spans.append((rm.start(), rm.end()))
        if len(rows) >= 2:
            rows.sort(key=lambda r: (r['ancho_min_m'] or 0))
            for num in _CORUNA_NZ2_SUBZONAS.get(cfg, ()):
                out[num] = rows
    return out


def _subzonas_coruna(blocks: list[dict], pdf_name: str) -> dict:
    """A Coruña: desglosa cada bloque NZ_N en subzonas NZ_N_M con sus
    parámetros (letras «x)- … (N.M)» o listas «Subzona N.- valor»)."""
    out: dict = {}
    for block in blocks:
        m = re.fullmatch(r'NZ_(\d+)', block['ordenanza'] or '')
        if not m:
            continue
        nz = int(m.group(1))
        for num, subtexto in _coruna_subsecciones(block):
            sub = {'ordenanza': f'NZ_{nz}_{num}', 'titulo': None,
                   'pag_ini': block['pag_ini'], 'texto': subtexto}
            params, trazas = _extract_params(sub)
            code = f'NZ_{nz}_{num}'
            out[code] = {'ordenanza': code,
                         'titulo': f'Norma Zonal {nz} — subzona {num}',
                         'params': params, 'trazas': trazas,
                         'fuente': f"{pdf_name} pág. {block['pag_ini']}"}
        for num, params in _coruna_listas(block).items():
            code = f'NZ_{nz}_{num}'
            entry = out.setdefault(code, {
                'ordenanza': code,
                'titulo': f'Norma Zonal {nz} — subzona {num}',
                'params': {}, 'trazas': {},
                'fuente': f"{pdf_name} pág. {block['pag_ini']}"})
            entry['params'].update(params)
            for k, v in params.items():
                entry['trazas'].setdefault(k, {
                    'pagina': block['pag_ini'],
                    'texto': f'Subzona {num}: {v}'})
        # NZ_2 Ensanche: altura por nº de plantas según ancho de calle
        # (tablas por configuración de manzana).
        if nz == 2:
            for num, rows in _coruna_nz2_tablas(block).items():
                code = f'NZ_{nz}_{num}'
                entry = out.setdefault(code, {
                    'ordenanza': code,
                    'titulo': f'Norma Zonal 2 — subzona {num}',
                    'params': {}, 'trazas': {},
                    'fuente': f"{pdf_name} pág. {block['pag_ini']}"})
                partes = '; '.join(
                    (f"rúa <{_fmt_num(r['ancho_max_m'])} m"
                     if r['ancho_min_m'] in (0, None)
                     else f"rúa ≥{_fmt_num(r['ancho_min_m'])} m"
                     if r['ancho_max_m'] is None else
                     f"rúa {_fmt_num(r['ancho_min_m'])}–"
                     f"{_fmt_num(r['ancho_max_m'])} m")
                    + f": {r['plantas']} plantas" for r in rows)
                entry['params']['altura_por_ancho_rua'] = (
                    partes + ' — altura en nº de plantas (NU NZ 2, '
                    'art. f)')
                entry['trazas']['altura_por_ancho_rua'] = {
                    'pagina': block['pag_ini'], 'tabla': rows,
                    'texto': 'Tabla ancho de calle → nº de plantas '
                             '(NU NZ_2, configuración de manzana)'}
    return out


def extraer_ordenanzas_municipio(ine: str, *, forzar: bool = False) -> dict:
    """Extrae parámetros por ordenanza de los PDFs normativos cacheados del municipio.
    Devuelve {ordenanza: {titulo, params, trazas, fuente}} con caché en disco."""
    cache_file = _DATOS / str(ine) / '_ordenanzas.json'
    if cache_file.exists() and not forzar:
        try:
            d = json.loads(cache_file.read_text(encoding='utf-8'))
            if (d.get('_extractor_v') == _EXTRACTOR_V
                    and time.time() - d.get('_extracted_at', 0) < _CACHE_TTL_S):
                return d.get('ordenanzas') or {}
        except Exception:
            pass
    out = {}
    pdfs = sorted((_DATOS / str(ine)).glob('*.pdf')) if (_DATOS / str(ine)).is_dir() else []
    # Solo el documento vigente: los PDFs de instrumentos descargados
    # (PERI/ED de un API, manifest 'instrumentos'/'iddoc' por fichero)
    # traen sus propias ordenanzas y no deben contaminar las del plan.
    try:
        manifest = json.loads(
            (_DATOS / str(ine) / '_manifest.json').read_text(
                encoding='utf-8'))
        vigente = manifest.get('iddoc')
        permitidos = {f.get('pathesperado') for f in
                      manifest.get('ficheros', [])
                      if f.get('iddoc') in (None, vigente)}
        if permitidos:
            pdfs = [p for p in pdfs if p.name in permitidos]
    except Exception:
        pass
    for pdf in pdfs:
        pages = _pdf_pages_text(pdf)
        if not pages:
            continue
        blocks = _segment_ordenanzas(pages)
        for block in blocks:
            params, trazas = _extract_params(block)
            key = block['ordenanza'].upper()
            # A Coruña: los parámetros de una NZ se fijan por subzona —
            # los valores a nivel NZ son ambiguos (mezclan subzonas), se
            # conserva solo el título y el detalle va a NZ_N_M.
            if str(ine) == '15030' and re.fullmatch(r'NZ_\d+', key):
                params, trazas = {}, {}
                block['titulo'] = (block.get('titulo')
                                   or 'Norma Zonal').strip(' ,.-')
            prev = out.get(key)
            if prev and len(prev.get('params') or {}) >= len(params):
                continue
            out[key] = {
                'ordenanza': key,
                'titulo': block.get('titulo'),
                'params': params,
                'trazas': trazas,
                'fuente': f"{pdf.name} pág. {block['pag_ini']}",
            }
            if not params:
                out[key]['nota'] = ('A ordenanza non define parámetros numéricos extraíbles '
                                   '(conserva a edificabilidade existente ou expresa alturas en plantas).')
        if str(ine) == '15030':
            for code, entry in _subzonas_coruna(blocks, pdf.name).items():
                prev = out.get(code)
                if (prev and len(prev.get('params') or {})
                        >= len(entry.get('params') or {})):
                    continue
                if not entry.get('params'):
                    entry['nota'] = ('Parámetros definidos en la norma '
                                     'zonal y fichas — ver documento.')
                out[code] = entry
    if out:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(
                {'_extracted_at': time.time(), '_extractor_v': _EXTRACTOR_V,
                 'municipio_ine': str(ine), 'ordenanzas': out},
                ensure_ascii=False, indent=1), encoding='utf-8')
        except Exception:
            pass
    return out


def _norm_code(s: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', (s or '').upper())


def buscar_ordenanza(ordenanzas: dict, consulta: str) -> tuple[str | None, dict | None]:
    """Match por código exacto o normalizado (U4, U.4, u4.1 -> U4/U4.1)."""
    if not ordenanzas or not consulta:
        return None, None
    q = _norm_code(consulta)
    for key in ordenanzas:
        if _norm_code(key) == q:
            return key, ordenanzas[key]
    # El código consultado es una subzona de una ordenanza madre
    # (NZ_4_2_a → NZ_4_2 → NZ_4): gana el prefijo más largo — más
    # específico, nunca ambiguo entre ascendientes.
    padres = [k for k in ordenanzas
              if q.startswith(_norm_code(k)) and _norm_code(k) != q]
    if padres:
        best = max(padres, key=lambda k: len(_norm_code(k)))
        return best, ordenanzas[best]
    # U4 → U4.x si solo existe una descendiente (si no, ambiguo).
    cand = [k for k in ordenanzas if _norm_code(k).startswith(q)]
    if len(cand) == 1:
        return cand[0], ordenanzas[cand[0]]
    return None, None


def parametros_subzona(ine: str, subzona: str | None = None) -> dict:
    """API: parámetros de ordenanza(s) del municipio con trazabilidad oficial."""
    ords = extraer_ordenanzas_municipio(ine)
    res = {'available': bool(ords), 'municipio_ine': str(ine),
           'data_quality': 'official' if ords else 'unavailable',
           'fuente': 'SIOTUGA normativa municipal (PDF oficial)'}
    if not ords:
        res['nota'] = 'No hay PDFs normativos descargados o no se encontraron ordenanzas. Descargue antes con /official/normativa-docs.'
        return res
    if subzona:
        key, found = buscar_ordenanza(ords, subzona)
        if found:
            res['ordenanza'] = key
            res['resultado'] = found
            res['params'] = found.get('params') or {}
            return res
        res['nota'] = f"Ordenanza '{subzona}' no localizada; se listan todas."
    res['ordenanzas'] = ords
    return res
