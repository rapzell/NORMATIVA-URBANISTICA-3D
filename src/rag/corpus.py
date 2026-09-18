"""Corpus normativo autonómico para el asistente IA.

Indexa los documentos oficiales depositados en ``datos/corpus/``
(Ley 2/2016 del suelo, NHV/Decreto 128/2023, NTPU, …) con chunking
orientado a artículo — cada chunk conserva su ``article_ref``
(«Art. 45.2», «Disposición adicional 3ª», «Anexo I A.1.2») para que el
LLM pueda citar con precisión y el arquitecto auditar la fuente.

El índice se cachea en ``_corpus_index.json`` y se invalida cuando
cambia el manifiesto o los PDFs (clave = sha256 del manifiesto +
tamaños). Los documentos se declaran en ``_manifest.json`` con título,
fuente y URL oficial — nunca se indexa nada que no esté declarado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

CORPUS_DIR = os.path.join('datos', 'corpus')
MANIFEST_PATH = os.path.join(CORPUS_DIR, '_manifest.json')
INDEX_PATH = os.path.join(CORPUS_DIR, '_corpus_index.json')

MAX_ARTICLE_CHARS = 2600

# Cabeceras de artículo en castellano y gallego, con ordinal textual.
_ART_RE = re.compile(
    r'(?im)^\s*(?:art[íi]culo|artigo)\s+'
    r'([\d]+(?:\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies))?[\d]*)'
    r'[\.\s:–—-]'
)
_DISP_RE = re.compile(
    r'(?im)^\s*(disposici[oó]n\s+(?:adicional|transitoria|derogatoria|final)\s+'
    r'(?:[a-záéíóúñ]+|\d+[ªº]?))'
)
_ANEXO_RE = re.compile(r'(?im)^\s*(anexo\s+[ivx0-9]+[\.\s:–—-])')


def _manifest() -> dict:
    try:
        with open(MANIFEST_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {'documentos': []}


def _manifest_key(manifest: dict) -> str:
    parts = []
    for d in manifest.get('documentos', []):
        path = os.path.join(CORPUS_DIR, d.get('fichero', ''))
        size = os.path.getsize(path) if os.path.exists(path) else -1
        parts.append(f"{d.get('id')}:{d.get('fichero')}:{size}")
    return hashlib.sha256('|'.join(sorted(parts)).encode()).hexdigest()[:16]


def _extract_pages(pdf_path: str) -> list[tuple[int, str]]:
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


def _article_label(match_text: str) -> str:
    m = re.match(r'(?i)\s*(?:art[íi]culo|artigo)\s*(\S+)', match_text)
    return f"Art. {m.group(1).rstrip('.:')}" if m else match_text.strip()


def _segment_by_articles(full_text: str) -> list[dict]:
    """Segmenta el texto completo en bloques por artículo/disposición.

    Devuelve ``[{ref, texto, start}]``; lo que precede al primer
    artículo (exposición de motivos, índice) se guarda como bloque
    ``PRELIMINAR`` para no perder contexto consultable.
    """
    marks: list[tuple[int, str]] = []
    for m in _ART_RE.finditer(full_text):
        marks.append((m.start(), _article_label(m.group(0))))
    for m in _DISP_RE.finditer(full_text):
        marks.append((m.start(), m.group(1).strip()))
    for m in _ANEXO_RE.finditer(full_text):
        marks.append((m.start(), m.group(1).strip().rstrip('.:–—-')))
    marks.sort()
    # Deduplicar cabeceras repetidas (mismo ref a < 40 chars, p. ej.
    # versiones bilingües o cabecera duplicada por el extractor)
    dedup: list[tuple[int, str]] = []
    for pos, ref in marks:
        if dedup and ref == dedup[-1][1] and pos - dedup[-1][0] < 40:
            continue
        dedup.append((pos, ref))
    blocks: list[dict] = []
    if not dedup:
        return [{'ref': 'DOCUMENTO', 'texto': full_text, 'start': 0}]
    if dedup[0][0] > 400:
        blocks.append({'ref': 'EXPOSICION_MOTIVOS',
                       'texto': full_text[:dedup[0][0]], 'start': 0})
    for i, (pos, ref) in enumerate(dedup):
        end = dedup[i + 1][0] if i + 1 < len(dedup) else len(full_text)
        blocks.append({'ref': ref, 'texto': full_text[pos:end], 'start': pos})
    return blocks


def _page_of(pages: list[tuple[int, str]], offset_map: list[tuple[int, int]],
             pos: int) -> int | None:
    page = None
    for pg, start in offset_map:
        if pos >= start:
            page = pg
        else:
            break
    return page


def _split_article(texto: str) -> list[str]:
    """Divide un artículo largo por apartados numerados/frases."""
    from src.normativa_rag import _split_chunks
    return _split_chunks(texto)


def indexar_corpus(force: bool = False) -> dict:
    """Construye (o reutiliza) el índice del corpus autonómico.

    Devuelve ``{documentos, chunks, manifest_key}``; cada chunk lleva
    ``{doc_id, doc_titulo, article_ref, pagina, texto, tokens,
    fuente, url, url_oficial}``. Sin documentos → ``chunks: []``.
    """
    manifest = _manifest()
    docs = [d for d in manifest.get('documentos', [])
            if os.path.exists(os.path.join(CORPUS_DIR, d.get('fichero', '')))]
    if not docs:
        return {'documentos': [], 'chunks': [], 'manifest_key': '',
                'error': 'Sin documentos en datos/corpus/'}
    key = _manifest_key(manifest)
    if not force:
        try:
            with open(INDEX_PATH, encoding='utf-8') as fh:
                idx = json.load(fh)
            if idx.get('manifest_key') == key:
                return idx
        except Exception:
            pass
    from src.normativa_rag import _norm
    chunks: list[dict] = []
    for doc in docs:
        pdf_path = os.path.join(CORPUS_DIR, doc['fichero'])
        try:
            pages = _extract_pages(pdf_path)
        except Exception:
            continue
        full_parts: list[str] = []
        offset_map: list[tuple[int, int]] = []
        pos = 0
        for pg, text in pages:
            offset_map.append((pg, pos))
            full_parts.append(text)
            pos += len(text) + 1
        full_text = '\n'.join(full_parts)
        for block in _segment_by_articles(full_text):
            page = _page_of(pages, offset_map, block['start'])
            for ci, part in enumerate(_split_article(block['texto'])):
                if not part.strip():
                    continue
                chunks.append({
                    'doc_id': doc['id'],
                    'doc_titulo': doc['titulo'],
                    'article_ref': block['ref'],
                    'pagina': page,
                    'chunk': ci,
                    'texto': part,
                    'tokens': _norm(part),
                    'fuente': doc.get('fuente'),
                    'url': doc.get('url'),
                    'url_oficial': doc.get('url_oficial'),
                    'ambito': doc.get('ambito', 'autonomico'),
                })
    idx = {'manifest_key': key, 'chunks': chunks,
           'documentos': [{k: d.get(k) for k in
                           ('id', 'titulo', 'fuente', 'url', 'url_oficial')}
                          for d in docs]}
    os.makedirs(CORPUS_DIR, exist_ok=True)
    with open(INDEX_PATH, 'w', encoding='utf-8') as fh:
        json.dump(idx, fh, ensure_ascii=False)
    return idx


def estado_corpus() -> dict:
    """Resumen ligero para /qa/health sin reconstruir el índice."""
    manifest = _manifest()
    docs = []
    for d in manifest.get('documentos', []):
        path = os.path.join(CORPUS_DIR, d.get('fichero', ''))
        docs.append({'id': d.get('id'), 'titulo': d.get('titulo'),
                     'presente': os.path.exists(path)})
    chunks = 0
    try:
        with open(INDEX_PATH, encoding='utf-8') as fh:
            chunks = len(json.load(fh).get('chunks') or [])
    except Exception:
        pass
    return {'documentos': docs, 'chunks_indexados': chunks}


def buscar(query: str, top_k: int = 8) -> list[dict]:
    """BM25 sobre el corpus; devuelve citas con article_ref y página."""
    from src.normativa_rag import _norm, _bm25, _extracto
    idx = indexar_corpus()
    chunks = idx.get('chunks') or []
    if not chunks:
        return []
    q_tokens = _norm(query)
    citas = []
    for c, score in _bm25(chunks, q_tokens, top_k):
        citas.append({
            'doc_id': c['doc_id'],
            'documento': c['doc_titulo'],
            'article_ref': c.get('article_ref'),
            'pagina': c.get('pagina'),
            'chunk': c.get('chunk'),
            'score': round(score, 3),
            'extracto': _extracto(c['texto'], q_tokens),
            'texto': c['texto'],
            'fuente': c.get('fuente'),
            'url': c.get('url'),
            'url_oficial': c.get('url_oficial'),
            'ambito': c.get('ambito'),
        })
    return citas
