# Model router — design (to implement in the polish fleet)

Goal: an answer is always produced. If a model is busy, rate-limited, rotated out, or the account's
credit/quota is gone, the router moves on, and in the worst case the code-built answer (cards + sources +
template) is shown. **Brief constraint:** the answer path uses free models via OpenRouter only.
No paid models, no extra accounts or keys to dodge limits (SPEC §33).

## Layers
1. **Candidate pool** (`OPENROUTER_MODELS`, comma list, all `:free`). Default order comes from the
   Arabic gate + live `/api/v1/models` check at boot (drop models no longer listed or no longer `:free`).
   Starting candidates from TECH_RADAR: gemma-4-31b → nemotron-3-ultra → gemma-4-26b (verify IDs at boot).
2. **Per-request fallback inside OpenRouter**: send `models: [m1, m2, m3]` so OpenRouter fails over
   server-side in one HTTP call; log `response.model` to see who answered.
   For tool-call requests add `provider.require_parameters: true`.
3. **Health-aware ordering (client-side)**, per model, in memory:
   - circuit breaker: 429 / 5xx / timeout → cooldown (30 s, doubling to 10 min); skip while open.
   - honour `Retry-After` and the `X-RateLimit-*` headers.
   - EWMA of time-to-first-token; reorder healthy models by Arabic-gate rank, then latency.
   - mid-stream `error` chunk inside HTTP 200 = failure → next model, resend (only if no tokens sent yet;
     otherwise finish with the code-built answer and mark `degraded`).
4. **Account-level states**:
   - `402` (credit exhausted) or daily free-cap hit → global "quota" state for N minutes: skip LLM entirely,
     serve the degraded path, `/readyz` reports `llm: quota`.
   - Budget guard: count LLM calls per day; at 90% of the cap, only answer uncached questions that are not
     templates or pure code paths (search/compare/calc never need the LLM).
5. **Cache first**: normalised query + entity IDs + lang (1 h TTL, pre-warmed with every chip) +
   `X-OpenRouter-Cache: true` header.
6. **Last resort**: the degraded template + cards + sources, always correct, built in code.

## Observability (metadata only)
Trace event gains `model`, `fallback_hops`, `breaker_state`, `cache_hit`, `degraded_reason`
(`rate_limited | quota | timeout | all_models_down | maintenance`). `/api/meta` exposes the live pool
with each model's state (healthy / cooling / removed) for the /how-it-works page.

## Tests
Mock OpenRouter: 429 on m1 → m2 answers; all 429 → degraded; 402 → quota state, no LLM calls for N min;
mid-stream error before/after the first token; model missing from `/models` at boot → dropped;
breaker reopens after cooldown.

## Optional, OFF by default (brief deviation, documented only)
`FF_SECONDARY_PROVIDER`: another free provider as an emergency fallback after OpenRouter. Off because
the brief says "free model via OpenRouter". Listed in the README as a production next step, not used in the demo.
