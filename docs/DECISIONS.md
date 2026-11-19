# Decisions and deviations

Deviations from SPEC.md, why, and what it costs. Numbers are not repeated here; see REPORT.md (generated).

| # | Decision | Why | Cost / honest caveat |
|---|---|---|---|
| 1 | **Free Docker host** (Northflank, Railway or Render) instead of Cloud Run (SPEC D1) | No paid cloud budget. Same-origin single container is unchanged. Target resident memory <= 512 MB if achievable, else <= 1 GB; image < 800 MB. | Free tiers sleep or limit CPU; first request after idle is slow (see DEPLOY warm-up). Decision at the time of the final build: Railway (1 GB trial) is primary because hybrid retrieval peaked at about 0.86 GB and was out-of-memory killed at 512 MB; the 512 MB backup host runs keyword-only retrieval. |
| 2 | **No credit bought; free `:free` OpenRouter models only** | Owner decision. | Account cap of 50 requests/day in total, shared by build and deploy. Failed attempts probably count and it is unverified whether a `models` fallback counts as one request, so all budgets are ceilings with a reserve. At the cap the app serves an extractive, code-built answer with cards and sources. |
| 3 | **Daily budget in the app** (`LLM_DAILY_BUDGET`, default 45) and a **baked answer cache** | Review days must not exhaust the cap. Chips and reviewer questions are answered with 0 calls; boot spends nothing. | Cached answers are frozen at the dataset version they were baked for; a stale key is a miss, not a wrong answer. |
| 4 | **DarGlobal collected manually** by the owner in a normal browser at human pace | The site's bot challenge blocks automated clients. The fetch lane stopped after the first challenge and never retried, rotated user agents or drove a headless browser. | A handful of pages, not a crawl. Projects known only from the index carry name and location only (`detail: "index"`) and the app says so. Re-runnable: the extractor reads `scraper/manual/darglobal/extracts/*.json`. |
| 5 | **No DarGlobal prices** | DarGlobal pages publish none. | "Price on request" / "not published" everywhere; price-trap cases check that no number is invented. |
| 6 | **"Why invest" pages excluded** | Marketing and return claims, not factual project data; quoting them invites yield promises the concierge must not make. | The concierge cannot answer "why invest in Dubai" from DarGlobal copy; yield and ROI questions get the advice template. |
| 7 | **Tool routing off in deploy** (`LLM_TOOL_ROUTING=false`) | One LLM call per message instead of two; the planner already routes in code. | Fewer model-chosen tool paths; the code planner decides. Tool routing remains available for local experiments, but E2 (routing comparison) is not re-measured against the real API. |
| 8 | **Wasalt ToS vs llms.txt conflict accepted for a small sample** | `llms.txt` permits extraction of public listing content for non-commercial use; the Terms of Use restrict copying. | Sample only, attribution on every card, no contact data, images hot-linked. Take the bot down after review (DEPLOY). |
| 9 | **One unified concierge, badge per card** | Owner decision. | Cross-brand questions retrieve from both sites; the badge and source site show which brand a fact came from. |
| 10 | **Judge not used** | The judge would spend requests from the 50/day cap. | Arabic is scored by deterministic checks plus the owner's spot check. Stated in REPORT.md. |
| 11 | **Mock LLM for the full suite, load test and unit tests** | Zero real calls outside the budgeted stages. | Mock numbers measure routing, retrieval, citations and guardrails, not answer quality. REPORT.md labels every block mock or real. |

## Feature flags

The flags `FF_FIND_MY_HOME`, `FF_MAP`, `FF_VOICE`, `FF_HANDOFF_BRIEF`, `FF_WIDGET_DEMO` are read from the environment and reported in `/api/meta.flags`. The state at the last eval run is recorded in `evals/results/latest.json` under `run_context.flags`. At the last recorded full run all five were false (find-my-home cases therefore exercise the off state). Check `run_context.flags` in the current result file before quoting this.

## Rejected designs (quality pass, 2026-11)

| Design | Why it was rejected |
|---|---|
| **LLM-first everywhere** (send every turn to a model to classify, rewrite and plan) | The free tiers are capped (50 requests a day on OpenRouter). A call per turn for greetings, calculations and plain filtered searches spends the budget on work that code does deterministically and testably. The "before" run showed only 29% of turns reach the understanding call; the gate is widened only for reference words, unresolved ordering words and thin filters. |
| **Multi-agent** (planner, retriever, writer and critic as separate model calls) | Each extra hop multiplies latency and free-tier calls, and adds failure surfaces (the 6 degraded turns in the before run were already all-models-down events). Grounding is cheaper to enforce with code: fact sheets built from the store, location repair, number checks. |
| **Saved answers** (a bank of canned replies keyed by question) | Cached answers go stale against the dataset and cannot follow a conversation (refine, reference, topic switch). The baked cache stays for chips and reviewer questions only; everything else is answered from live structured data and the 32-type playbook, which carries policy, never facts. |
