# syntax=docker/dockerfile:1.7
# One container: FastAPI serves /api/* and the static Next.js export at /.
# Target: Hugging Face Docker Space (port 7860, uid 1000). Same image runs on Render.

# ---------- Stage 1: frontend static export ----------
FROM node:20.18-slim AS frontend
ENV PNPM_HOME=/pnpm
RUN npm install -g pnpm@9.15.4 --no-fund --no-audit
WORKDIR /build/frontend
# Lockfile may be pnpm-lock.yaml; the glob keeps the layer cacheable when it is absent.
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN --mount=type=cache,target=/pnpm/store \
    if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; else pnpm install; fi
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
# next.config must set output: "export" -> frontend/out
# Public Space URL, used only for absolute og:image links.
ARG APP_URL=""
ENV APP_URL=${APP_URL}
RUN pnpm build && test -d out

# ---------- Stage 2: backend deps + model + index ----------
FROM python:3.11.10-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed_cache \
    EMBED_CACHE_DIR=/opt/fastembed_cache \
    HF_HOME=/opt/hf_home \
    DATA_PATH=/app/data/concierge.sqlite \
    INDEX_DIR=/app/data/index \
    STATIC_DIR=/app/static \
    PORT=7860

# Non-root uid 1000 (required by HF Spaces), created first so files are owned via COPY --chown
# instead of a chown -R layer that would duplicate everything.
RUN useradd -m -u 1000 appuser     && mkdir -p /app/tmp /app/data/index /opt/fastembed_cache /opt/hf_home     && chown 1000:1000 /app /app/tmp /app/data /app/data/index /opt/fastembed_cache /opt/hf_home

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

USER 1000
ENV HOME=/home/appuser TMPDIR=/app/tmp
# Bake the embedding model into the image (no runtime download, no cold-start network).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/opt/fastembed_cache')"

COPY --chown=1000:1000 backend/ /app/backend/
COPY --chown=1000:1000 data/concierge.sqlite /app/data/concierge.sqlite
# Bake retrieval indexes from the dataset.
RUN python -m backend.app.build_index

COPY --chown=1000:1000 --from=frontend /build/frontend/out /app/static
# Latest real eval run, served read-only at /api/evals (the /evals page).
COPY --chown=1000:1000 evals/results/latest.json /app/evals/results/latest.json

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/healthz',timeout=4).status==200 else 1)"

# No --forwarded-allow-ips "*": uvicorn would then take the client-controlled LEFT-most X-Forwarded-For hop as
# the client address. The app reads the hop its own edge proxy appended (TRUSTED_PROXY_HOPS, right-most).
# --limit-concurrency bounds in-flight requests (memory) on a shared free CPU Space.
ENV TRUSTED_PROXY_HOPS=1
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "7860", "--no-proxy-headers", "--limit-concurrency", "64", "--no-access-log"]
