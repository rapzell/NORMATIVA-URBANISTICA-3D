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
    from src.rag.synonyms import expandir_query, boost_por_tipo
    from src.rag.hybrid_search import (buscar_semantico, rrf_fusion,
                                       rerank_remoto, chunk_key)

    # Expansión léxica ES/GL para el BM25; la query original se
    # conserva para la vía semántica y el reranker.
    q_expandida = expandir_query(query)
    q_tokens = _norm(q_expandida)
    candidatos: list[dict] = []

    # Corpus autonómico
    n_corpus = 0
    for c in corpus.buscar(q_expandida, top_k=top_k):
        n_corpus += 1
        url = c.get('url_oficial') or c.get('url')
        if url and c.get('pagina') and str(url).lower().endswith('.pdf'):
            url = f"{url}#page={c['pagina']}"
        candidatos.append({
            'documento': c['documento'],
            'referencia': c.get('article_ref'),
            'pagina': c.get('pagina'),
            'texto': c.get('texto') or c.get('extracto') or '',
            'extracto': c.get('extracto'),
            'fuente': c.get('fuente'),
            'url': url,
            'ambito': 'autonomico',
            'score': c.get('score', 0),
            '_key': chunk_key(c.get('doc_id'), c.get('pagina'),
                              c.get('chunk')),
        })

    # PDFs municipales (normativa del PGOM del municipio activo)
    n_muni = 0
    if ine:
        try:
            idx = indexar_municipio(ine)
            for c, score in _bm25(idx.get('chunks') or [], q_tokens, top_k):
                n_muni += 1
                url = c.get('url')
                if url and c.get('pagina'):
                    url = f"{url}#page={c['pagina']}"
                candidatos.append({
                    'documento': idx.get('denominacion') or c['fichero'],
                    'referencia': c['fichero'],
                    'pagina': c.get('pagina'),
                    'texto': c.get('texto') or '',
                    'extracto': _extracto(c.get('texto') or '', q_tokens),
                    'fuente': 'SIOTUGA normativa municipal',
                    'url': url,
                    'ambito': 'municipal',
                    'score': score + 0.5,  # leve prioridad a lo municipal
                    '_key': chunk_key(f"muni:{c['fichero']}",
                                      c.get('pagina'), c.get('chunk')),
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
    unicos = boost_por_tipo(query, unicos)

    # Vía semántica sobre el corpus (embeddings precalculados +
    # servicio :8003). Si no está disponible no cambia nada: queda el
    # orden BM25+sinónimos.
    semantico = False
    try:
        sem = buscar_semantico(query, top_k=top_k * 2)
    except Exception:
        sem = []
    if sem:
        try:
            by_key = {c['_key']: c for c in unicos}
            chunk_map = {
                chunk_key(c['doc_id'], c['pagina'], c['chunk']): c
                for c in (corpus.indexar_corpus().get('chunks') or [])}
            for k, _sim in sem:
                if k in by_key or k not in chunk_map:
                    continue
                c = chunk_map[k]
                url = c.get('url_oficial') or c.get('url')
                if url and c.get('pagina') \
                        and str(url).lower().endswith('.pdf'):
                    url = f"{url}#page={c['pagina']}"
                nuevo = {
                    'documento': c['doc_titulo'],
                    'referencia': c.get('article_ref'),
                    'pagina': c.get('pagina'),
                    'texto': c.get('texto') or '',
                    'extracto': _extracto(c.get('texto') or '', q_tokens),
                    'fuente': c.get('fuente'),
                    'url': url,
                    'ambito': 'autonomico',
                    'score': 0.0,
                    '_key': k,
                }
                by_key[k] = nuevo
                unicos.append(nuevo)
            fused = rrf_fusion(
                [[c['_key'] for c in unicos], [k for k, _ in sem]], k=60)
            for c in unicos:
                c['rrf_score'] = fused.get(c['_key'], 0.0)
            unicos.sort(key=lambda x: x['rrf_score'], reverse=True)
            semantico = True
        except Exception:
            pass

    rerank_modo = False
    if rerank:
        if rerank_disponible():
            seleccion = rerankear(query, unicos, top_n=top_n)
            rerank_modo = 'local'
        else:
            # Cross-encoder remoto en el microservicio (si está vivo)
            docs = [(f.get('texto') or f.get('extracto') or '')
                    for f in unicos[:10]]
            scores = rerank_remoto(query, docs)
            if scores:
                for i, f in enumerate(unicos[:10]):
                    f['rerank_score'] = scores[i]
                seleccion = sorted(
                    unicos[:10],
                    key=lambda x: x['rerank_score'], reverse=True)
                seleccion = (seleccion + unicos[10:])[:top_n]
                rerank_modo = 'remoto'
            else:
                seleccion = unicos[:top_n]
    else:
        seleccion = unicos[:top_n]
    for i, f in enumerate(seleccion):
        f['id'] = i + 1
    return {
        'fragmentos': seleccion,
        'n_corpus': n_corpus,
        'n_municipal': n_muni,
        'rerank': rerank_modo,
        'semantico': semantico,
        'municipio': municipio,
        'ine': ine,
    }
