# Railway single-service deployment (ADR-011, docs/sdd.md Appendix B).
# FastAPI serves the built SPA same-origin - see backend/app/api/spa.py.

# ---- Stage 1: build the frontend --------------------------------------
FROM node:20-slim AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: backend runtime -------------------------------------------
# python:3.12-slim, not 3.13: pin to what the pinned torch build (a
# sentence-transformers/BGE dependency, SDD Appendix A / ADR-002) supports.
FROM python:3.12-slim AS runtime

# hnswlib/tokenizers (chromadb, sentence-transformers deps) don't always
# ship a prebuilt wheel for every cp312 platform combination and fall
# back to a source build without a C/C++ toolchain present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/app ./backend/app

# torch is a sentence-transformers/BGE dependency (SDD Appendix A / ADR-002)
# pulled in transitively - with no index override, pip resolves PyPI's
# default CUDA build (~2GB+ of nvidia_cublas/nccl/nvshmem/triton wheels)
# even though this container has no GPU and never will on Railway. Install
# the CPU-only build from PyTorch's own index first so the later
# `pip install ./backend` finds torch already satisfied and skips it.
RUN pip install --no-cache-dir torch==2.12.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir ./backend

COPY backend/alembic ./backend/alembic
COPY backend/alembic.ini ./backend/alembic.ini

COPY --from=frontend-build /app/dist ./frontend_dist

# Pre-download the BGE embedding model into the image so the container
# never fetches from HuggingFace at startup (HF_HUB_OFFLINE=1 below
# enforces that at runtime, turning a silent network dependency into a
# build-time failure if this step is ever skipped or the model changes).
ENV HF_HOME=/opt/hf-cache
RUN mkdir -p "$HF_HOME" && python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('BAAI/bge-small-en-v1.5')"

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /opt/hf-cache /data

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER appuser
WORKDIR /app/backend

ENV HF_HUB_OFFLINE=1 \
    FRONTEND_DIST_DIR=/app/frontend_dist \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
