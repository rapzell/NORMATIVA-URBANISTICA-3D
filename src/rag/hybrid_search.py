"""Búsqueda híbrida BM25 + embeddings con Reciprocal Rank Fusion.

Cliente ligero del microservicio de embeddings
(``src.rag.embedding_service``, puerto 8003) que corre en el entorno
secundario Python ≤3.13. Este módulo NO importa torch ni
sentence-transformers — solo ``requests`` y ``numpy`` — así funciona
en el Python 3.14 principal.

Diseño degradable: si el servicio está caído, tarda demasiado o los
embeddings precalculados no existen/están obsoletos, todas las
funciones devuelven ``None``/``[]`` y el llamador sigue con BM25 +
sinónimos. Nunca se tumba una consulta por la vía semántica.

Los embeddings del corpus autonómico se precalculan una vez con
``scripts/precompute_embeddings.py`` y se guardan en
``datos/rag/embeddings_corpus.npz`` junto a su manifiesto de
invalidación (sha256 del manifiesto del corpus).
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import requests

RAG_DIR = os.path.join('datos', 'rag')
EMB_PATH = os.path.join(RAG_DIR, 'embeddings_corpus.npz')
META_PATH = os.path.join(RAG_DIR, 'embeddings_corpus.meta.json')

SERVICE_URL = os.getenv('EMBEDDING_SERVICE_URL', 'http://127.0.0.1:8003')
_TIMEOUT = float(os.getenv('EMBEDDING_TIMEOUT_S', '25'))

_health_cache: tuple[float, bool] = (0.0, False)


def servicio_disponible() -> bool:
    """Health-check con caché de 30 s — no golpear el servicio en cada
    consulta ni esperar el timeout cada vez si está caído."""
    global _health_cache
    ahora = time.time()
    ts, ok = _health_cache
    if ahora - ts < 30:
        return ok
    try:
        r = requests.get(f'{SERVICE_URL}/health', timeout=2)
        ok = bool(r.ok and r.json().get('status') == 'ok')
    except Exception:
        ok = False
    _health_cache = (ahora, ok)
    return ok


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embeddings normalizados vía servicio; ``None`` si falla."""
    if not texts:
        return []
    try:
        r = requests.post(f'{SERVICE_URL}/embed', json={'texts': texts},
                          timeout=_TIMEOUT)
        data = r.json()
        embs = data.get('embeddings')
        if isinstance(embs, list) and len(embs) == len(texts):
            return embs
    except Exception:
        pass
    return None


def rerank_remoto(query: str, documentos: list[str]) -> list[float] | None:
    """Scores del cross-encoder legal; ``None`` si el servicio falla."""
    if not documentos:
        return []
    try:
        r = requests.post(f'{SERVICE_URL}/rerank',
                          json={'query': query, 'documents': documentos},
                          timeout=_TIMEOUT)
        scores = r.json().get('scores')
        if isinstance(scores, list) and len(scores) == len(documentos):
            return [float(s) for s in scores]
    except Exception:
        pass
    return None


def _manifest_key_corpus() -> str | None:
    try:
        from src.rag import corpus
        return corpus.indexar_corpus().get('manifest_key')
    except Exception:
        return None


def cargar_embeddings() -> tuple[np.ndarray, list[str]] | None:
    """``(matriz [n,dim], chunk_keys)`` o ``None`` si falta/es viejo.

    La matriz se invalida por el sha256 del manifiesto del corpus: si
    cambió el contenido normativo hay que regenerar con
    ``scripts/precompute_embeddings.py``.
    """
    try:
        if not (os.path.exists(EMB_PATH) and os.path.exists(META_PATH)):
            return None
        with open(META_PATH, encoding='utf-8') as fh:
            meta = json.load(fh)
        key = _manifest_key_corpus()
        if not key or meta.get('manifest_key') != key:
            return None
        data = np.load(EMB_PATH)
        matriz = data['embeddings']
        keys = [str(k) for k in data['keys'].tolist()]
        if matriz.shape[0] != len(keys):
            return None
        return matriz, keys
    except Exception:
        return None


def buscar_semantico(query: str, top_k: int = 20) -> list[tuple[str, float]]:
    """Ranking semántico sobre el corpus: ``[(chunk_key, sim)]``.

    Devuelve ``[]`` si el servicio o los embeddings no están — el
    llamador sigue solo con BM25.
    """
    if not servicio_disponible():
        return []
    cargado = cargar_embeddings()
    if cargado is None:
        return []
    matriz, keys = cargado
    embs = embed_texts([query])
    if not embs:
        return []
    q = np.asarray(embs[0], dtype=np.float32)
    sims = matriz @ q  # normalizados → producto escalar = coseno
    n = min(top_k, len(keys))
    idx = np.argpartition(-sims, n - 1)[:n]
    idx = idx[np.argsort(-sims[idx])]
    return [(keys[i], float(sims[i])) for i in idx]


def chunk_key(doc_id: str | None, pagina, chunk) -> str:
    """Clave estable compartida por BM25, embeddings y RRF."""
    return f'{doc_id}:{pagina}:{chunk}'


def rrf_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion estándar (k=60 de la literatura).

    ``rankings`` es una lista de listas ordenadas de claves; devuelve
    ``{clave: score_fusionado}`` ordenable de mayor a menor.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return scores
