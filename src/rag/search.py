"""Búsqueda normativa unificada para el asistente IA.

Combina dos índices y los presenta al orquestador con una forma común:

1. Corpus autonómico (``src.rag.corpus``): Ley 2/2016, NHV, NTPU…
   chunks por artículo con ``article_ref``.
2. PDFs municipales SIOTUGA (``src.normativa_rag``): normativa del
   municipio activo, chunks por página.

Motor base: BM25 (no requiere dependencias pesadas). Si
``sentence_transformers`` está instalado y ``RAG_RERANKER=1``,
se aplica un cross-encoder de re-ranking (por defecto el modelo ALIA
de español legal, ``SINAI/ALIA-MrBERT-es-legal-administrative-reranker``,
Apache-2.0). En Python 3.14 sin torch el rerank se desactiva solo y el
resultado sigue siendo el BM25 — nunca falla por la dependencia.
"""
from __future__ import annotations

import os

_RERANKER = None
_RERANKER_TRIED = False


def _reranker():
    """Cross-encoder opcional; ``None`` si la dependencia no está."""
    global _RERANKER, _RERANKER_TRIED
    if _RERANKER_TRIED:
        return _RERANKER
    _RERANKER_TRIED = True
    if os.getenv('RAG_RERANKER', '1') in ('0', 'false', 'no'):
        return None
    try:
        from sentence_transformers import CrossEncoder
        model = os.getenv(
            'RAG_RERANKER_MODEL',
            'SINAI/ALIA-MrBERT-es-legal-administrative-reranker')
        _RERANKER = CrossEncoder(model)
    except Exception:
        _RERANKER = None
    return _RERANKER


def rerank_disponible() -> bool:
    return _reranker() is not None


def rerankear(query: str, fragmentos: list[dict], top_n: int = 5) -> list[dict]:
    """Re-ranking con cross-encoder; sin modelo devuelve el orden BM25."""
    model = _reranker()
    if model is None or not fragmentos:
        return fragmentos[:top_n]
    try:
        pairs = [(query, f.get('texto') or f.get('extracto') or '')
                 for f in fragmentos]
        scores = model.predict(pairs)
        for i, f in enumerate(fragmentos):
            f['rerank_score'] = float(scores[i])
        return sorted(fragmentos, key=lambda x: x['rerank_score'],
                      reverse=True)[:top_n]
    except Exception:
        return fragmentos[:top_n]


def buscar_normativa(query: str, ine: str | None = None,
                     municipio: str | None = None, top_k: int = 10,
                     rerank: bool = True, top_n: int = 6) -> dict:
    """Recupera fragmentos normativos combinando corpus y PDFs locales.

    Devuelve ``{fragmentos, n_corpus, n_municipal, rerank}``. Cada
    fragmento: ``{id, documento, referencia, pagina, texto, extracto,
    fuente, url, ambito, score}`` listo para citar como ``[FUENTE i]``.
    """
    from src.rag import corpus
    from src.normativa_rag import (_norm, _bm25, _extracto,
                                   indexar_municipio)

    q_tokens = _norm(query)
    candidatos: list[dict] = []

    # Corpus autonómico
    n_corpus = 0
    for c in corpus.buscar(query, top_k=top_k):
        n_corpus += 1
        candidatos.append({
            'documento': c['documento'],
            'referencia': c.get('article_ref'),
            'pagina': c.get('pagina'),
            'texto': c.get('texto') or c.get('extracto') or '',
            'extracto': c.get('extracto'),
            'fuente': c.get('fuente'),
            'url': c.get('url_oficial') or c.get('url'),
            'ambito': 'autonomico',
            'score': c.get('score', 0),
        })

    # PDFs municipales (normativa del PGOM del municipio activo)
    n_muni = 0
    if ine:
        try:
            idx = indexar_municipio(ine)
            for c, score in _bm25(idx.get('chunks') or [], q_tokens, top_k):
                n_muni += 1
                candidatos.append({
                    'documento': idx.get('denominacion') or c['fichero'],
                    'referencia': c['fichero'],
                    'pagina': c.get('pagina'),
                    'texto': c.get('texto') or '',
                    'extracto': _extracto(c.get('texto') or '', q_tokens),
                    'fuente': 'SIOTUGA normativa municipal',
                    'url': None,
                    'ambito': 'municipal',
                    'score': score + 0.5,  # leve prioridad a lo municipal
                })
        except Exception:
            pass

    candidatos.sort(key=lambda x: x.get('score', 0), reverse=True)
    # Dedup por contenido: el mismo texto puede aparecer en varios PDFs
    vistos: set = set()
    unicos: list[dict] = []
    for c in candidatos:
        norm = ' '.join((c.get('texto') or '').split()).lower()
        firma = norm[40:200] if len(norm) > 200 else norm
        if firma and firma in vistos:
            continue
        vistos.add(firma)
        unicos.append(c)
    if rerank:
        seleccion = rerankear(query, unicos, top_n=top_n)
    else:
        seleccion = unicos[:top_n]
    for i, f in enumerate(seleccion):
        f['id'] = i + 1
    return {
        'fragmentos': seleccion,
        'n_corpus': n_corpus,
        'n_municipal': n_muni,
        'rerank': rerank_disponible(),
        'municipio': municipio,
        'ine': ine,
    }
