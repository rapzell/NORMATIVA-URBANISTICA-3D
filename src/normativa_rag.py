"""Consulta en lenguaje natural sobre los PDFs oficiales del planeamiento.

RAG ligero sobre los documentos descargados por
``src.siotuga.document_client`` en ``datos/normativa/{ine}/``:

1. ``indexar_municipio`` extrae el texto página a página con pypdf y
   construye un índice de chunks (por página, partidas si son largas)
   cacheado en ``_index.json``; se reconstruye solo si cambian los PDFs
   (clave = sha256 del manifiesto).
2. ``consultar`` puntúa los chunks con un esquema BM25 (tf·idf sobre
   tokens normalizados sin acentos) y devuelve las citas más
   relevantes ``{fichero, seccion, pagina, extracto}``.
3. Si hay un proveedor LLM configurado (``model_gateway``), sintetiza
   una respuesta citando los fragmentos; si no, devuelve un resumen
   extractivo. Las citas siempre se devuelven — la respuesta LLM nunca
   sustituye a la fuente.

Principio: solo se indexan documentos descargados del inventario
oficial SIOTUGA (o depositados manualmente con el mismo manifiesto).
Sin PDFs → ``data_quality: unavailable`` con instrucciones.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from typing import Any

NORMATIVA_DIR = os.path.join('datos', 'normativa')
MAX_CHUNK_CHARS = 1800
CHUNK_OVERLAP = 120

_STOPWORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'de', 'del',
    'en', 'y', 'o', 'a', 'al', 'que', 'es', 'se', 'su', 'sus', 'con',
    'por', 'para', 'como', 'más', 'mas', 'no', 'si', 'lo', 'le', 'les',
    'este', 'esta', 'estos', 'estas', 'ese', 'esa', 'esos', 'esas',
    'ser', 'son', 'fue', 'han', 'ha', 'hay', 'muy', 'ya', 'todo',
    'toda', 'todos', 'todas', 'otro', 'otra', 'entre', 'sobre', 'tras',
    'the', 'do', 'da', 'dos', 'das', 'no', 'na', 'nas', 'ao', 'aos',
    'ou', 'polo', 'pola', 'pelo', 'pela', 'cada', 'segundo', 'segunda',
    'cal', 'cales', 'cómo', 'cuál', 'cual', 'cuáles', 'cuando', 'donde',
    'cuánto', 'cuanta', 'puede', 'pueden', 'debe', 'deben', 'tiene',
    'permitir', 'permitido', 'permitida', 'municipio', 'concello',
}


def _norm(text: str) -> list[str]:
    """Tokens normalizados (minúsculas, sin acentos, sin stopwords)."""
    t = unicodedata.normalize('NFKD', text.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return [w for w in re.findall(r'[a-zñ0-9]+', t)
            if len(w) >= 3 and w not in _STOPWORDS]


def _split_chunks(text: str) -> list[str]:
    """Parte un texto largo en chunks con solape, cortando en frases."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        if end < len(text):
            cut = text.rfind('. ', start + MAX_CHUNK_CHARS // 2, end)
            if cut > start:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end - CHUNK_OVERLAP, start + 1)
        if end >= len(text):
            break
    return chunks


def _extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    """Texto por página ``[(nº_página, texto), ...]`` (1-based)."""
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ''
        except Exception:
            t = ''
        pages.append((i + 1, t))
    return pages


def _index_path(ine_code: str) -> str:
    return os.path.join(NORMATIVA_DIR, ine_code, '_index.json')


def _manifest_key(manifest: dict) -> str:
    import hashlib
    parts = sorted(
        f"{f.get('pathesperado')}:{f.get('sha256')}"
        for f in manifest.get('ficheros', [])
    )
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]


def indexar_municipio(ine_code: str, force: bool = False) -> dict:
    """Construye (o reutiliza) el índice de chunks del municipio.

    Lee el manifiesto de ``document_client`` y extrae texto de cada PDF
    con ``status`` downloaded/cached. Devuelve
    ``{ine, chunks, manifest_key, ficheros}``; la clave del manifiesto
    invalida el índice cuando cambian los PDFs.
    """
    from src.siotuga.document_client import manifiesto_municipio
    manifest = manifiesto_municipio(ine_code)
    ficheros = [f for f in manifest.get('ficheros', [])
                if f.get('status') in ('downloaded', 'cached')]
    if not ficheros:
        return {'ine': ine_code, 'chunks': [], 'ficheros': [],
                'error': 'Sin PDFs descargados; usa /official/normativa-docs'}
    key = _manifest_key(manifest)
    path = _index_path(ine_code)
    if not force:
        try:
            with open(path, encoding='utf-8') as fh:
                idx = json.load(fh)
            if idx.get('manifest_key') == key:
                return idx
        except Exception:
            pass
    chunks: list[dict] = []
    for fich in ficheros:
        local = fich.get('local_path')
        if not local or not os.path.exists(local):
            continue
        try:
            pages = _extract_pages(local)
        except Exception:
            continue
        for page_no, text in pages:
            if not text.strip():
                continue
            for ci, chunk in enumerate(_split_chunks(text)):
                chunks.append({
                    'fichero': fich['pathesperado'],
                    'seccion': fich.get('seccion'),
                    'seccion_desc': fich.get('seccion_desc'),
                    'pagina': page_no,
                    'chunk': ci,
                    'texto': chunk,
                    'tokens': _norm(chunk),
                })
    idx = {'ine': ine_code, 'manifest_key': key, 'chunks': chunks,
           'ficheros': [f.get('pathesperado') for f in ficheros],
           'iddoc': manifest.get('iddoc'),
           'denominacion': manifest.get('denominacion')}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(idx, fh, ensure_ascii=False)
    return idx


def _bm25(chunks: list[dict], query_tokens: list[str],
          top_k: int) -> list[tuple[dict, float]]:
    """Ranking BM25 estándar (k1=1.5, b=0.75) sobre tokens precalculados."""
    if not query_tokens or not chunks:
        return []
    df: dict[str, int] = {}
    for c in chunks:
        for t in set(c.get('tokens') or []):
            df[t] = df.get(t, 0) + 1
    n = len(chunks)
    avg_len = sum(len(c.get('tokens') or []) for c in chunks) / max(n, 1)
    k1, b = 1.5, 0.75
    scored = []
    for c in chunks:
        toks = c.get('tokens') or []
        if not toks:
            continue
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in set(query_tokens):
            if t not in tf:
                continue
            idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            score += idf * (tf[t] * (k1 + 1)) / (
                tf[t] + k1 * (1 - b + b * len(toks) / max(avg_len, 1)))
        if score > 0:
            scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _extracto(texto: str, query_tokens: list[str], width: int = 320) -> str:
    """Recorte del chunk centrado en el primer término de la consulta."""
    low = texto.lower()
    best = 0
    for t in query_tokens:
        pos = low.find(t)
        if pos >= 0:
            best = pos
            break
    start = max(0, best - width // 3)
    frag = texto[start:start + width].strip()
    return ('…' if start > 0 else '') + frag + ('…' if start + width < len(texto) else '')


def _sintesis_llm(pregunta: str, citas: list[dict]) -> str | None:
    """Respuesta sintetizada por el proveedor LLM configurado, o None."""
    try:
        from src.model_gateway import generate_with_fallback
        ctx = '\n\n'.join(
            f"[{i+1}] {c['fichero']} pág.{c['pagina']}: {c['extracto']}"
            for i, c in enumerate(citas))
        prompt = (
            'Eres un asistente de normativa urbanística gallega. Responde '
            'en español, de forma breve y precisa, usando SOLO los '
            'fragmentos oficiales citados. Indica entre corchetes de qué '
            'fragmento procede cada afirmación. Si los fragmentos no '
            'bastan, dilo explícitamente.\n\n'
            f'PREGUNTA: {pregunta}\n\nFRAGMENTOS:\n{ctx}\n\nRESPUESTA:')
        ans = generate_with_fallback(prompt, None)
        if ans and 'No ha sido posible' not in ans and 'fallo' not in ans[:60]:
            return ans.strip()
    except Exception:
        pass
    return None


def consultar(ine_code: str, pregunta: str, top_k: int = 6,
              use_llm: bool = True) -> dict:
    """Consulta normativa sobre los PDFs del municipio.

    Devuelve ``{respuesta, citas, documentos, data_quality}``. Cada cita
    lleva fichero, sección, página y extracto — la respuesta siempre es
    trazable a la fuente oficial. Sin índice/documentos devuelve
    ``unavailable`` con la instrucción de descarga.
    """
    idx = indexar_municipio(ine_code)
    chunks = idx.get('chunks') or []
    if not chunks:
        return {
            'ine': ine_code, 'respuesta': None, 'citas': [],
            'data_quality': 'unavailable',
            'error': idx.get('error') or 'Índice vacío',
            'instrucciones': ('Descargar primero con '
                              'GET /official/normativa-docs?municipio=...'),
        }
    q_tokens = _norm(pregunta)
    ranked = _bm25(chunks, q_tokens, top_k)
    citas = []
    for c, score in ranked:
        citas.append({
            'fichero': c['fichero'],
            'seccion': c.get('seccion'),
            'seccion_desc': c.get('seccion_desc'),
            'pagina': c['pagina'],
            'score': round(score, 3),
            'extracto': _extracto(c['texto'], q_tokens),
        })
    respuesta = None
    llm_used = False
    if use_llm and citas:
        respuesta = _sintesis_llm(pregunta, citas)
        llm_used = respuesta is not None
    if respuesta is None and citas:
        respuesta = (
            f"Fragmentos más relevantes de la normativa (índice "
            f"{idx.get('denominacion') or ine_code}). Revisar las citas "
            "completas en el PDF original.")
    return {
        'ine': ine_code,
        'pregunta': pregunta,
        'respuesta': respuesta,
        'llm': llm_used,
        'citas': citas,
        'documento': {
            'iddoc': idx.get('iddoc'),
            'denominacion': idx.get('denominacion'),
            'ficheros': idx.get('ficheros'),
        },
        'data_quality': 'official',
        'source': 'SIOTUGA inventario documental',
        'nota': ('Respuesta extractiva/sobre texto oficial; verificar '
                 'siempre el artículo completo en el PDF citado'),
    }
