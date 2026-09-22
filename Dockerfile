# NORMATIVA GALICIA 3D — beta en Hugging Face Spaces (SDK docker)
#
# Todo gratuito: el backend FastAPI sirve API + visor GeoLibre en el
# puerto 7860. El microservicio de embeddings (:8003) NO se incluye —
# el RAG degrada automáticamente a BM25 + sinónimos (diseñado así).
#
# Secrets del Space (Settings → Secrets):
#   BETA_PASSWORD       contraseña única de acceso
#   OPENROUTER_API_KEY  clave LLM (plan :free)
#   MODEL_PROVIDER      openrouter

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

ENV PORT=7860 \
    PYTHONUNBUFFERED=1 \
    MODEL_PROVIDER=openrouter

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
