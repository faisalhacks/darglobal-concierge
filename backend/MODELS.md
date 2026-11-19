# Default free models (OpenRouter)

Candidate pool chosen on 2026-11-19 from the public `GET https://openrouter.ai/api/v1/models` list (480 models,
14 with a `:free` suffix; the three below were re-checked as listed and `:free` on the same day). The app re-checks the
list at boot (free GET, no completion, no quota) and drops any pool member that is gone or no longer free.

Default `OPENROUTER_MODELS` (sent as OpenRouter's `models` fallback array, in this order):

| # | Model | Why this position |
|---|---|---|
| 1 | `nvidia/nemotron-3-ultra-550b-a55b:free` | Answered every live request on 2026-11-19 and passed the deterministic Arabic gate (below). Different provider from #2/#3, so a Google AI Studio outage does not take out the head of the chain. |
| 2 | `google/gemma-4-31b-it:free` | Best-documented multilingual model on the free list (model card: 140+ languages). Failed upstream on both live attempts on 2026-11-19 (OpenRouter fell back past it server-side), so it is second, not first. Not yet gated in Arabic. |
| 3 | `google/gemma-4-26b-a4b-it:free` | Same family as #2, faster MoE. Returned 429 on its only live attempt on 2026-11-19. Not yet gated in Arabic. |

Rejected: coding-specialised models (`cohere/north-mini-code`, `particle-ai/particle-1`, `recursive/flint-v1.0`), the
1.7B `liquid/lfm-3-1.7b` (too small for fluent Arabic; its description says prompts may be retained), and preview or
multimodal-first models whose descriptions give no reason to prefer them for Arabic text.

## Live check, 2026-11-19 (`python -m backend.scripts.live_check --max-calls 9`)

5 real chat requests in total (the router counted 6: one extra 503 was produced in-process to force a fallback and was
never sent). Every answer below went through the full app path (retrieval, prompt contract, output screen).

| Step | Who answered (`response.model`) | fallback_hops | Result |
|---|---|---|---|
| smoke-en "Tell me about Da Vinci Tower" | nemotron-3-ultra | 1 (gemma-4-31b failed server-side) | grounded English answer, streamed |
| smoke-fallback (first model failed locally) | none | - | 2nd hop gemma-4-26b returned 429 -> extractive code answer, `degraded_reason: rate_limited`. The degrade path worked; a successful client-side hop was not observed live (it is covered by mocked tests) |
| gate-ar-1 "كيف تعمل مزادات وصلت؟" | nemotron-3-ultra | 1 | fluent Arabic, facts match the Wasalt FAQ chunk; Arabic ratio 1.00 |
| gate-ar-2 "أخبرني عن Da Vinci Tower" | nemotron-3-ultra | 0 | fluent Arabic with Latin names kept; "price not published" stated; ratio 0.87 |
| gate-ar-3 "هل يمكن للأجانب شراء عقار في السعودية؟" | nemotron-3-ultra | 0 | passed the deterministic checks (ratio 1.00) **but is a false refusal**: it said the information is not published although the retrieved English blog chunk answers it |

Arabic gate verdict for nemotron-3-ultra: 3/3 on the deterministic checks (reply language, Arabic letter ratio >= 0.5,
not degraded, no URL, no prompt leak), 2/3 on content (one false refusal on a cross-language retrieval). This is 3
prompts, not the SPEC §12 85 % gate over a full Arabic set; treat the order as provisional. gemma-4-31b and
gemma-4-26b were not gated (both failing upstream at the time; spending more calls on them would have been wasted).

What could not be verified: each free endpoint's prompt-logging / retention terms (check the OpenRouter model pages
before launch and state them on /privacy, SPEC §12).

## How it is used (`backend/app/llm.py`, `backend/app/router.py`, docs/MODEL_ROUTER.md)

- One streaming request with the healthy part of the pool as the `models` array (max 3); `response.model` is logged and
  returned in the trace together with `fallback_hops`.
- Per-model circuit breaker: 429 / 5xx / timeout / mid-stream error before the first token -> cooldown 30 s doubling to
  10 min (`Retry-After` honoured); then one client-side retry on the remaining healthy models. Never more than 2 HTTP
  requests per message.
- `402` or the daily free cap (`free-models-per-day`) -> account "quota" state until `X-RateLimit-Reset` (or 30 min):
  zero outbound calls. The per-minute account cap -> "cooling" for its window.
- Daily budget guard: `LLM_DAILY_BUDGET` (default 45 of the account's 50/day) counts every outbound request; at the cap
  no call is made; at >= 90 % the tool-routing call is skipped. `LLM_TOOL_ROUTING` defaults to false (1 call/message).
- Requests carry `X-OpenRouter-Cache: true` and `reasoning: {effort: "low", exclude: true}`; tool calls add
  `provider.require_parameters: true`.
- Baked answers (`backend/scripts/warm_cache.py` -> `data/answer_cache.json`) are replayed with `cache_hit: true` and the
  model that wrote them, at 0 calls.
- When no model can answer, the reply is the extractive code-built answer (2-3 verbatim sentences or the published fact
  lines) with cards and sources; there is no apology sentence; the state is in `trace.degraded_reason` and `/api/meta.llm`.
