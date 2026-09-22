# NORMATIVA GALICIA 3D — beta pública (Render free / HF Spaces docker)
#
# Backend FastAPI sirviendo API + visor GeoLibre. Los datos (~170 MB)
# no van en la imagen: `fetch_beta_data.py` los descarga del dataset
# público HF al arrancar. El microservicio de embeddings (:8003) NO se
# incluye — el RAG degrada a BM25 + sinónimos automáticamente.
#
# Variables de entorno:
#   BETA_PASSWORD       contraseña única de acceso (gate en app/main.py)
#   OPENROUTER_API_KEY  clave LLM (plan :free)
#   MODEL_PROVIDER      openrouter
#   PORT                el puerto lo fija la plataforma (Render lo inyecta)

FROM python:3.11-slim

WORKDIR /app

# Dependencias de sistema mínimas (rasterio/shapely traen wheels; GDAL
# no hace falta porque se usan las wheels manylinux).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY src ./src
COPY web ./web
COPY scripts ./scripts
COPY datos ./datos

ENV PYTHONUNBUFFERED=1 \
    MODEL_PROVIDER=openrouter

EXPOSE 7860

# Descarga los datos del dataset HF (idempotente) y arranca en $PORT
# (Render lo inyecta; en local/HF cae a 7860).
CMD python scripts/fetch_beta_data.py && \
    uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}
