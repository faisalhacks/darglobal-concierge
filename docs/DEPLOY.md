# Deploy

Target: one container on a free Docker host (Northflank, Railway or Render; to be tested), same origin for UI and API, port 7860. Never push a key into the repo or image.

## Build

    docker build -t concierge --build-arg APP_URL=https://<your-host> .

`APP_URL` is a build arg because the static frontend bakes absolute links (how-it-works, evals, share links). Rebuild if the URL changes. `data/index` is built outside Docker and COPYed; its `meta.json.dataset_version` must equal the database's dataset version or `/readyz` reports `index: "stale"` and retrieval falls back (`bm25_only`).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | none | Set as a host secret only. Without it the app runs degraded (extractive answers). |
| `OPENROUTER_MODELS` | built-in `:free` pool | Comma list, in preference order; see backend/MODELS.md. |
| `LLM_MODE` | `auto` | `mock` for tests and load tests (never on the review URL), `off` to disable. |
| `LLM_DAILY_BUDGET` | `45` | App-side cap on real requests per day. The account cap is 50 in total, so 5 stay as reserve. |
| `LLM_TOOL_ROUTING` | `false` in deploy | Keep false: 1 model call per message. |
| `RATE_LIMIT` | `15/300` | Messages per seconds, per client IP. |
| `TRUSTED_PROXY_HOPS` | `0` | Number of proxy hops in front of the app (see below). |
| `ALLOWED_ORIGINS` | empty | Same-origin deploy needs none. |
| `APP_URL` | empty | Runtime copy of the public URL. |
| `DATA_PATH`, `INDEX_DIR`, `STATIC_DIR` | in the image | Leave default. |
| `FF_FIND_MY_HOME`, `FF_MAP`, `FF_VOICE`, `FF_HANDOFF_BRIEF`, `FF_WIDGET_DEMO` | false | Feature flags. |
| `CANDIDATE_NAME`, `CANDIDATE_GITHUB`, `CANDIDATE_LINKEDIN`, `CANDIDATE_EMAIL` | none | Optional footer details; set as host env, never in files. |

## Setting TRUSTED_PROXY_HOPS from /readyz

The rate limiter keys on the client IP. Behind a platform proxy every request looks like it comes from the proxy unless the app reads `X-Forwarded-For` correctly. `/readyz` returns `xff_hops_seen`, the count (never the addresses) of `X-Forwarded-For` entries on that request.

1. Deploy with `TRUSTED_PROXY_HOPS=0`.
2. From your own machine run `curl https://<host>/readyz` and read `xff_hops_seen`.
3. Set `TRUSTED_PROXY_HOPS` to that number (usually 1) and redeploy. A value that is too high lets clients spoof their IP; too low makes all users share one bucket.
4. Re-check with `curl` after the change. If a CDN is added later, repeat.

## Warm-up and smoke

- Free hosts sleep. Hit `/healthz` a few minutes before a review; `/readyz` should show `ready: true`, `index: "ok"`, `retrieval: "hybrid"`.
- Boot spends 0 model requests. Live smoke on the URL is budgeted at 4 requests (EN stream, AR stream, one chip served from the cache, one fallback check). Check `/api/meta.llm.budget` before and after to confirm the count.
- Do not run evals or load tests against the review URL: on review days the full 50 requests belong to reviewers.

## Take-down after review

1. Delete or suspend the service on the host and revoke the OpenRouter key.
2. Remove the repo or make it private if it was shared.
3. Wasalt data was used under a disclosed ToS/llms.txt tension (docs/DECISIONS.md #8); taking the app down after review is part of that position.
