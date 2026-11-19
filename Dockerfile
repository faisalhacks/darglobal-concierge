# One container: FastAPI serves /api/* and the static Next.js export at /.
# One Dockerfile for every host: Railway (listens on the injected $PORT), Hugging Face Spaces / Render (7860, uid
# 1000) and a local `docker build .`. No cache mounts: Railway rejects a cache mount without its own service-specific
# id=, so the file uses nothing a host-specific builder could refuse.
#
# Build inputs that are produced OUTSIDE Docker (the in-Docker index build ran out of memory):
#   data/concierge.sqlite        the dataset
#   data/index/                  python -m backend.app.build_index --data data/concierge.sqlite --out data/index
#                                (meta.json.dataset_version must equal the DB's dataset_meta.version; on a mismatch
#                                 the app serves BM25-only and /readyz reports index: "stale")
#   data/answer_cache.json       optional, backend/scripts/warm_cache.py (baked answers, read-only)
#   evals/results/latest.json    latest real eval run, served at /api/evals

# ---------- Stage 1: frontend static export ----------
FROM node:20.18-slim AS frontend
ENV PNPM_HOME=/pnpm
RUN npm install -g pnpm@9.15.4 --no-fund --no-audit
WORKDIR /build/frontend
# Lockfile may be pnpm-lock.yaml; the glob keeps the layer cacheable when it is absent.
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; else pnpm install; fi
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
# next.config must set output: "export" -> frontend/out
# Public Space URL, used only for absolute og:image links.
ARG APP_URL=""
ENV APP_URL=${APP_URL}
RUN pnpm build && test -d out

# ---------- Stage 2: download the embedding model (fastembed is a build-time tool only) ----------
FROM python:3.11.10-slim AS model
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY backend/scripts/prepare_tokenizer.py /tmp/prepare_tokenizer.py
# The model's own SentencePiece file (pinned revision) + an id table replace the 17 MB tokenizer.json at runtime
# (~15 MB resident instead of ~280 MB). prepare_tokenizer.py fails the build if any id differs from tokenizer.json.
RUN pip install --no-compile fastembed==0.4.2 sentencepiece==0.2.0 \
 && python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/opt/fastembed_cache')" \
 && python -c "from huggingface_hub import hf_hub_download as d; print(d('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 'sentencepiece.bpe.model', revision='e8f8c211226b894fcb81acc59f3b34ba3efd5f42', local_dir='/tmp/sp'))" \
 && python /tmp/prepare_tokenizer.py "$(ls -d /opt/fastembed_cache/models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/snapshots/*)" /tmp/sp/sentencepiece.bpe.model \
 && rm -rf /opt/fastembed_cache/.locks /tmp/sp

# ---------- Stage 3: runtime Python deps (no fastembed / Pillow / sympy / onnx / huggingface_hub) ----------
FROM python:3.11.10-slim AS pydeps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY backend/requirements-runtime.txt /tmp/requirements.txt
# onnxruntime pulls sympy+mpmath (graph tools) and coloredlogs/flatbuffers/packaging/protobuf: inference needs none
# of sympy/mpmath. Tests, caches and pip itself are removed too (measured with `docker history` / du).
RUN pip install --no-compile -r /tmp/requirements.txt \
 && pip uninstall -y sympy mpmath \
 && python -m pip uninstall -y pip setuptools wheel \
 && find /opt/venv -depth \( -name '__pycache__' -o -name 'tests' -o -name 'test' \) -type d -prune -exec rm -rf {} + \
 && find /opt/venv -name '*.pyi' -delete

# ---------- Stage 4: runtime ----------
FROM python:3.11.10-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    FASTEMBED_CACHE_PATH=/opt/fastembed_cache \
    EMBED_CACHE_DIR=/opt/fastembed_cache \
    HF_HOME=/opt/hf_home \
    HF_HUB_OFFLINE=1 \
    DATA_PATH=/app/data/concierge.sqlite \
    INDEX_DIR=/app/data/index \
    ANSWER_CACHE_PATH=/app/data/answer_cache.json \
    STATIC_DIR=/app/static \
    PORT=7860 \
    # 2 ONNX threads on a shared free CPU; one uvicorn worker (memory)
    EMBED_THREADS=2 OMP_NUM_THREADS=2 \
    # Quota on the free OpenRouter tier is 50 requests/day for the whole account: one call per message,
    # stop at 45 and answer extractively from code after that.
    LLM_TOOL_ROUTING=false \
    LLM_DAILY_BUDGET=45 \
    # Same default as backend/app/config.py, so the image, local runs and the eval suite behave the same.
    FF_FIND_MY_HOME=true

# Non-root uid 1000 (required by HF Spaces), created first so files are owned via COPY --chown
# instead of a chown -R layer that would duplicate everything. The pip in the base image is removed (unused).
RUN useradd -m -u 1000 appuser \
 && mkdir -p /app/tmp /app/data/index /opt/hf_home \
 && chown 1000:1000 /app /app/tmp /app/data /app/data/index /opt/hf_home \
 && rm -rf /usr/local/lib/python3.11/site-packages/pip /usr/local/lib/python3.11/site-packages/setuptools \
           /usr/local/bin/pip* /usr/local/lib/python3.11/ensurepip /usr/local/lib/python3.11/idlelib \
           /usr/local/lib/python3.11/lib2to3 /usr/local/lib/python3.11/tkinter

COPY --from=pydeps /opt/venv /opt/venv
COPY --from=model --chown=1000:1000 /opt/fastembed_cache /opt/fastembed_cache

USER 1000
ENV HOME=/home/appuser TMPDIR=/app/tmp
WORKDIR /app

COPY --chown=1000:1000 backend/ /app/backend/
# answer_cache.jso[n]: optional file; the glob lets the build pass when it is absent (the sqlite always matches).
COPY --chown=1000:1000 data/concierge.sqlite data/answer_cache.jso[n] /app/data/
COPY --chown=1000:1000 data/index/ /app/data/index/
COPY --chown=1000:1000 --from=frontend /build/frontend/out /app/static
# Latest real eval run, served read-only at /api/evals (the /evals page).
COPY --chown=1000:1000 evals/results/latest.json /app/evals/results/latest.json

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','7860'),timeout=4).status==200 else 1)"

# No --forwarded-allow-ips "*": uvicorn would then take the client-controlled LEFT-most X-Forwarded-For hop as
# the client address. The app reads the hop its own edge proxy appended (TRUSTED_PROXY_HOPS, right-most);
# GET /readyz reports xff_hops_seen so the value can be checked per host (deploy/README.md).
# --limit-concurrency bounds in-flight requests (memory) on a shared free CPU Space. One worker.
# $PORT: Railway injects it; HF Spaces / Render / local fall back to 7860. `exec` keeps uvicorn as PID 1 (signals).
ENV TRUSTED_PROXY_HOPS=1
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port \"${PORT:-7860}\" --workers 1 --no-proxy-headers --limit-concurrency 64 --no-access-log"]
