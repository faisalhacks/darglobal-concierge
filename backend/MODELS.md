# Default free models (OpenRouter)

Chosen on 2026-11-19 from the public, unauthenticated list at `GET https://openrouter.ai/api/v1/models`
(480 models listed, 14 with a `:free` suffix). No API key existed at the time, so **none of these has been
run through the Arabic quality gate (SPEC §12, ≥ 85%) yet.** Treat the order as a starting point and
re-rank after the first real eval run.

Default `OPENROUTER_MODELS` (sent as OpenRouter's `models` fallback array, in this order):

| # | Model | Why |
|---|---|---|
| 1 | `google/gemma-4-31b-it:free` | Largest dense instruction-tuned general model on the free list (30.7B, 256K context). The Gemma line has historically been trained for broad multilingual use, which is what Arabic answers need. Supports tools. |
| 2 | `google/gemma-4-26b-a4b-it:free` | Same family and tokenizer as #1, so Arabic behaviour should be similar, but a different deployment, so it is a useful fallback when #1 is rate-limited. MoE with 3.8B active, so it is fast. |
| 3 | `nvidia/nemotron-3-ultra-550b-a55b:free` | Largest general model on the free list (55B active). Different provider, so a quota or outage on Google models does not take out the whole chain. |

Rejected for this use: coding-specialised models (`cohere/north-mini-code`, `particle-ai/particle-1`,
`recursive/flint-v1.0`), the 1.7B `liquid/lfm-3-1.7b` (too small for fluent Arabic, and its description says
prompts may be retained), and preview or multimodal-first models whose descriptions give no reason to prefer
them for Arabic text.

What I could not verify from the listing:
- None of the 14 descriptions mentions Arabic explicitly. Arabic quality must be measured, not assumed.
- Each free endpoint's prompt-logging or retention conditions. Check them on the OpenRouter model pages
  before launch and state them on /privacy (SPEC §12).

How it is used (`backend/app/llm.py`): one streaming call with the full `models` array; on 429, 5xx or a
timeout before the first token, one retry with the remaining models; then the `degraded` template, with
cards and sources still built in code. Never more than 2 LLM calls per message. Override with the
`OPENROUTER_MODELS` env var (comma-separated).
