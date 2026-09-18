"""Microservicio de embeddings/reranking para el RAG híbrido.

Se ejecuta en el entorno secundario Python ≤3.13 (``venv_rag``), donde
``sentence-transformers`` + torch sí funcionan — en el Python 3.14
principal no están disponibles. El backend principal lo consume por
HTTP (``src.rag.hybrid_search``) y degrada a BM25 puro si este
servicio no responde.

Arranque::

    venv_rag\\Scripts\\python.exe -m uvicorn \\
        src.rag.embedding_service:app --host 127.0.0.1 --port 8003

Los modelos se cargan de forma perezosa en la primera petición para
que ``/health`` responda al instante aunque la descarga del modelo
tarde. Ambos son gratuitos (Apache-2.0) y especializados en texto
legal-administrativo español.
"""
from __future__ import annotations

import os
import threading

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title='rag-embeddings', version='1.0')

_EMBED_MODEL = os.getenv(
    'EMBED_MODEL',
    'SINAI/ALIA-MrBERT-es-legal-administrative-embeddings')
_RERANK_MODEL = os.getenv(
    'RERANK_MODEL',
    'SINAI/ALIA-MrBERT-es-legal-administrative-reranker')

_lock = threading.Lock()
_embedder = None
_reranker = None
_embed_err: str | None = None
_rerank_err: str | None = None


def _get_embedder():
    global _embedder, _embed_err
    if _embedder is not None or _embed_err is not None:
        return _embedder
    with _lock:
        if _embedder is None and _embed_err is None:
            try:
                from sentence_transformers import SentenceTransformer
                _embedder = SentenceTransformer(_EMBED_MODEL)
            except Exception as e:  # noqa: BLE001 - degradación explícita
                _embed_err = str(e)
    return _embedder


def _get_reranker():
    global _reranker, _rerank_err
    if _reranker is not None or _rerank_err is not None:
        return _reranker
    with _lock:
        if _reranker is None and _rerank_err is None:
            try:
                from sentence_transformers import CrossEncoder
                _reranker = CrossEncoder(_RERANK_MODEL)
            except Exception as e:  # noqa: BLE001
                _rerank_err = str(e)
    return _reranker


class EmbedRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(default_factory=list)


@app.get('/health')
def health() -> dict:
    return {
        'status': 'ok',
        'embed_model': _EMBED_MODEL,
        'rerank_model': _RERANK_MODEL,
        'embedder_loaded': _embedder is not None,
        'reranker_loaded': _reranker is not None,
        'embedder_error': _embed_err,
        'reranker_error': _rerank_err,
    }


@app.post('/embed')
def embed(req: EmbedRequest) -> dict:
    model = _get_embedder()
    if model is None:
        return {'embeddings': [], 'error': _embed_err or 'modelo no cargado'}
    if not req.texts:
        return {'embeddings': []}
    vecs = model.encode(req.texts, normalize_embeddings=True)
    return {'embeddings': [v.tolist() for v in vecs]}


@app.post('/rerank')
def rerank(req: RerankRequest) -> dict:
    model = _get_reranker()
    if model is None or not req.documents:
        return {'scores': [],
                'error': _rerank_err or 'sin documentos'}
    pairs = [(req.query, d) for d in req.documents]
    scores = model.predict(pairs)
    return {'scores': [float(s) for s in scores]}
