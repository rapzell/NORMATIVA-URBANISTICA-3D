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

# Cabeceras de ordenanza: "ART. 76. ORDENANZA U1. MANTEMENTO...", "ORDENANZA U.4 ...",
# "ORDENANZA RZ-2 ...", "ORDENANZA DE RESIDENCIAL ..." (fallback genérico).
_ORD_HDR = re.compile(
    r'ORDENANZA\s+([A-ZÁÉÍÓÚÑÜ]{1,5}\.?\s*\d+(?:\.\d+)?|[A-ZÁÉÍÓÚÑÜ]{2,}(?:\s+DE\s+[A-ZÁÉÍÓÚÑÜ]+)?)'
    r'\s*[.:\-]?\s*([A-ZÁÉÍÓÚÑÜ0-9][^\n.]{3,90})?',
)
_ORD_GENERIC = re.compile(r'\bORDENANZA\s+([A-Z]{1,4}\.?\s*\d+(?:\.\d+)?)')

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
    ],
    'parcela_minima_m2': [
        re.compile(r'parcela\s+m[íi]nima\s+de\s+' + _NUM + r'\s*m2', re.I),
        re.compile(r'parcela\s+m[íi]nima\s+de\s+' + _NUM + r'\s*m[²2]', re.I),
    ],
}


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


def _segment_ordenanzas(pages: list[str]) -> list[dict]:
    """Devuelve bloques {ordenanza, titulo, pag_ini, texto} uniendo páginas."""
    blocks = []
    current = None
    for idx, text in enumerate(pages):
        # buscar cabeceras de ordenanza en esta página
        marks = []
        for m in _ORD_HDR.finditer(text):
            code = (m.group(1) or '').strip().replace(' ', '')
            title = (m.group(2) or '').strip().rstrip('.')
            if len(code) < 2 or code.upper() in ('DE', 'LA', 'DO', 'DA', 'NON', 'QUE'):
                continue
            marks.append((m.start(), code, title))
        for gm in _ORD_GENERIC.finditer(text):
            code = gm.group(1).replace(' ', '')
            if all(abs(gm.start() - s) > 3 for s, _, _ in marks):
                marks.append((gm.start(), code, ''))
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
    params = {}
    trazas = {}
    for key, pats in _PATTERNS.items():
        excl = _EXCLUDE_PREV.get(key)
        for pat in pats:
            found = False
            for m in pat.finditer(block['texto']):
                if excl and excl.search(block['texto'][max(0, m.start() - 80):m.start()]):
                    continue
                val = _numtxt(m.group(1))
                if val is None:
                    continue
                params[key] = val
                snippet = block['texto'][max(0, m.start() - 60):m.end() + 60]
                trazas[key] = {'pagina': block['pag_ini'], 'texto': ' '.join(snippet.split())[:220]}
                found = True
                break
            if found:
                break
    return params, trazas


def extraer_ordenanzas_municipio(ine: str, *, forzar: bool = False) -> dict:
    """Extrae parámetros por ordenanza de los PDFs normativos cacheados del municipio.
    Devuelve {ordenanza: {titulo, params, trazas, fuente}} con caché en disco."""
    cache_file = _DATOS / str(ine) / '_ordenanzas.json'
    if cache_file.exists() and not forzar:
        try:
            d = json.loads(cache_file.read_text(encoding='utf-8'))
            if time.time() - d.get('_extracted_at', 0) < _CACHE_TTL_S:
                return d.get('ordenanzas') or {}
        except Exception:
            pass
    out = {}
    pdfs = sorted((_DATOS / str(ine)).glob('*.pdf')) if (_DATOS / str(ine)).is_dir() else []
    for pdf in pdfs:
        pages = _pdf_pages_text(pdf)
        if not pages:
            continue
        for block in _segment_ordenanzas(pages):
            params, trazas = _extract_params(block)
            key = block['ordenanza'].upper()
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
    if out:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(
                {'_extracted_at': time.time(), 'municipio_ine': str(ine), 'ordenanzas': out},
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
    # prefijo (U4 matchea U4 si solo hay una U4*)
    cand = [k for k in ordenanzas if _norm_code(k).startswith(q) or q.startswith(_norm_code(k))]
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
