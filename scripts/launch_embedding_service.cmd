
@echo off
REM Microservicio de embeddings/reranker para el RAG hibrido (puerto 8003).
REM Corre en el entorno secundario Python 3.13 (venv_rag) porque
REM sentence-transformers/torch no estan disponibles en Python 3.14.
REM Si no esta arrancado, el asistente degrada a BM25 + sinonimos.

SETLOCAL
set HOST=127.0.0.1
set PORT=8003

REM Modelos gratuitos (Apache-2.0) especializados en legal ES (ALIA/SINAI)
REM set EMBED_MODEL=SINAI/ALIA-MrBERT-es-legal-administrative-embeddings
REM set RERANK_MODEL=SINAI/ALIA-MrBERT-es-legal-administrative-reranker

echo === Servicio embeddings RAG ===
echo HOST=%HOST% PORT=%PORT% (entorno venv_rag, Python 3.13)
venv_rag\Scripts\python.exe -m uvicorn src.rag.embedding_service:app --host %HOST% --port %PORT%

ENDLOCAL
