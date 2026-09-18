"""Precalcula los embeddings del corpus autonómico vía el servicio :8003.

Uso (entorno principal, solo necesita requests+numpy)::

    venv\\Scripts\\python.exe scripts\\precompute_embeddings.py

Requisito previo: el microservicio de embeddings corriendo::

    venv_rag\\Scripts\\python.exe -m uvicorn \\
        src.rag.embedding_service:app --host 127.0.0.1 --port 8003

Genera ``datos/rag/embeddings_corpus.npz`` + ``.meta.json`` con el
sha256 del manifiesto del corpus — si el corpus cambia, el índice de
embeddings se invalida solo y hay que relanzar este script.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rag import corpus  # noqa: E402
from src.rag.hybrid_search import (EMB_PATH, META_PATH, SERVICE_URL,  # noqa: E402
                                   chunk_key)

BATCH = 32


def main() -> int:
    try:
        r = requests.get(f'{SERVICE_URL}/health', timeout=5)
        assert r.ok
    except Exception:
        print(f'Servicio de embeddings no disponible en {SERVICE_URL}.\n'
              'Arranca primero: venv_rag\\Scripts\\python.exe -m uvicorn '
              'src.rag.embedding_service:app --port 8003')
        return 1

    idx = corpus.indexar_corpus()
    chunks = idx.get('chunks') or []
    if not chunks:
        print('Corpus vacío — nada que embeber.')
        return 1
    textos = [c['texto'] for c in chunks]
    keys = [chunk_key(c['doc_id'], c['pagina'], c['chunk']) for c in chunks]
    print(f'{len(textos)} chunks del corpus — embebiendo en lotes de {BATCH}…')

    t0 = time.time()
    embeddings: list[list[float]] = []
    for i in range(0, len(textos), BATCH):
        lote = textos[i:i + BATCH]
        resp = requests.post(f'{SERVICE_URL}/embed',
                             json={'texts': lote}, timeout=120)
        data = resp.json()
        if len(data.get('embeddings') or []) != len(lote):
            print(f'Error en lote {i}: {data.get("error") or resp.text[:200]}')
            return 1
        embeddings.extend(data['embeddings'])
        print(f'  {i + len(lote)}/{len(textos)}')

    os.makedirs(os.path.dirname(EMB_PATH), exist_ok=True)
    np.savez_compressed(EMB_PATH,
                        embeddings=np.asarray(embeddings, dtype=np.float32),
                        keys=np.asarray(keys))
    with open(META_PATH, 'w', encoding='utf-8') as fh:
        json.dump({'manifest_key': idx['manifest_key'],
                   'n_chunks': len(chunks),
                   'modelo': 'servicio :8003 (EMBED_MODEL)',
                   'generado': time.strftime('%Y-%m-%d %H:%M:%S')}, fh,
                  ensure_ascii=False, indent=2)
    print(f'OK — {len(embeddings)} embeddings en {EMB_PATH} '
          f'({time.time() - t0:.0f} s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
