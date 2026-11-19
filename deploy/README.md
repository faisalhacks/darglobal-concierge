# Deploy notes (backend / container)

## Build order (outside Docker first)

1. `data/concierge.sqlite` is final (data lane).
2. `python -m backend.app.build_index --data data/concierge.sqlite --out data/index`
   The in-image index build ran out of memory, so the index is built on the host and `COPY`ed. `data/index/meta.json`
   `dataset_version` must equal the DB's `dataset_meta.version`; if it does not, the app still starts but serves
   BM25-only retrieval and `GET /readyz` reports `"index": "stale"`. Check that before uploading.
3. Optional, spends real quota (max 12 calls): `python -m backend.scripts.warm_cache --max-calls 12`
   writes `data/answer_cache.json` (reviewer questions + starter chips that reach the model). It is keyed by
   dataset version, so re-run it after every dataset change; a stale file is ignored as a whole.
4. `docker build -t darglobal-concierge .` (or `deploy/hf/deploy.ps1 -Space <user>/<space>`, which bundles the DB,
   `data/index`, the optional answer cache and `evals/results/latest.json`, and refuses to upload without the index).

## One Dockerfile, every host

The root `Dockerfile` builds unchanged on Railway, Hugging Face Spaces, Render and a local `docker build .`: it uses no
cache mounts (Railway refuses a `--mount=type=cache` without its own service-specific `id=`), and the CMD listens on
`$PORT` when the host injects one (Railway) and on 7860 otherwise. The prebuilt `data/index/` is `COPY`ed (step 2).
`deploy/railway.json` is the Railway config-as-code file (Dockerfile builder, `/healthz` health check, bounded
restarts, which also bounds the in-memory LLM budget counter); point the service's config path at it. On Railway set
`TRUSTED_PROXY_HOPS` from `GET /readyz` -> `xff_hops_seen` as below.

## Proxy hops (`TRUSTED_PROXY_HOPS`)

The rate limiter takes the client address from the right-most `X-Forwarded-For` hop that **our** edge appended, never
the client-controlled left-most one. After deploying, open `GET /readyz` once from a browser: `xff_hops_seen` is the
number of hops the request arrived with (a count only, no addresses are returned or logged). Set
`TRUSTED_PROXY_HOPS` to the number of proxies you run in front of the app; with one edge proxy (HF Spaces, Render)
that is `1` (the image default). If `xff_hops_seen` is `0`, set it to `0`.

## LLM quota (free OpenRouter tier: 50 requests/day for the whole account)

| Variable | Deploy value | Effect |
|---|---|---|
| `LLM_DAILY_BUDGET` | `45` | outbound requests per UTC day; at the cap no call is made and answers are the extractive code path |
| `LLM_TOOL_ROUTING` | `false` | one LLM call per message; the code planner routes |
| `LLM_BOOT_MODEL_CHECK` | default `true` | boot does a free `GET /models` (no completion) and drops unlisted / non-free models; boot never spends quota |
| `FF_FIND_MY_HOME` | default `true` | same default in `backend/app/config.py` and the image, so evals and prod match; set `false` to turn it off |

State is visible without spending anything: `GET /api/meta` -> `llm.state` (`ok | quota | cooling | off | maintenance`),
`llm.budget`, `llm.pool`; `GET /readyz` -> `llm`. The budget counter is in memory: a restart resets it to 0, so a
crash loop could overspend; keep the host's restart policy bounded.

## Measured on 2026-11-19 (Docker Desktop, linux/amd64)

| | before | after |
|---|---|---|
| image, compressed (`docker image inspect .Size` = `docker save` bytes) | 372 MB | 322 MB |
| image, unpacked filesystem (`du -sx /` in the container) | not measured | ~538 MB (526,060 KiB) |
| `docker images` SIZE (Docker Desktop containerd store: compressed + unpacked) | 1.13 GB | 882 MB |
| resident memory, idle, hybrid retrieval (`docker stats`) | 704 MiB (fastembed loader) | 370 MiB (VmRSS 401 MiB) |
| resident memory after 20 / 40 mixed EN/AR queries (`docker stats`) | not measured | 385 / 368 MiB (VmRSS 404 MiB) |
| peak at boot (`VmHWM` of pid 1, ONNX session creation) | not measured | 576 MiB |
| resident memory, BM25-only (stale/no index) | not measured | 82 MiB |

What moved the numbers: no in-image index build; fastembed is a build-stage tool only (runtime loads the same ONNX file
with onnxruntime directly: identical vectors, checked against all 2,511 shipped index rows, min cosine 0.9999998);
the 17 MB `tokenizer.json` (+281 MB resident) is replaced by the model's SentencePiece file + id table (identical ids
on all 2,519 dataset chunk texts, re-checked at build time); ONNX CPU arena off, 2 threads; vectors memory-mapped;
sympy/mpmath/onnx/Pillow/huggingface_hub/pip/uvloop not in the runtime image. Not done: int8 quantisation of the
embedding model (the model file is still 235 MB, the largest layer). It changes the vectors, so it needs an index
rebuild and an E1 re-run (Arabic hit@6) before it may ship.

## Dependencies

Bumped with the full backend suite green (167 tests): fastapi 0.115.6 -> 0.162.0, starlette 0.41.3 -> 1.10.0,
pydantic 2.10.4 -> 2.14.2 (all released at least two weeks before 2026-11-19). The starlette bump moves past the
published advisories for the 0.41 line (multipart DoS, `FileResponse` Range-header DoS; the app serves the static
export through `FileResponse`). Pillow is no longer in the runtime image (it was only a fastembed dependency).
`uvicorn` stays at 0.32.1 without `[standard]` (+ `httptools`).

## Needs a human

- Deploying to Railway / the Space / Render / Northflank and setting `OPENROUTER_API_KEY` as a host secret.
- Buying OpenRouter credits (raises the free cap from 50 to 1000/day) is a payment: not done.
