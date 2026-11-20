# evals/

- `cases.yaml` 135 cases (SPEC 20.1 table), written before any backend code. Check vocabulary is documented in its header.
- `runner.py` SSE runner. `python evals/runner.py --list` validates without network.
- `experiments.py` E1 (retrieval) and E2 (routing). Skips with a message when it cannot measure.
- `judge_rubric.md` binary Gemini-judge rubric (grounded, next_step, tone, language); the same literal rules are used for hand labels.
- `fixtures/planted_chunk.json` test chunk for case I12; load into a TEST db copy, run with `--planted-chunk`.
- `results/` written only by real runs (`latest.json`, `<timestamp>.json`, `REPORT_SECTION.md`, `E1.json`, `E2.json`).

Run against a backend started with `LLM_MODE=mock RATE_LIMIT=100000/300` (the default 15 msgs / 5 min per IP
would throttle a 135-case suite; the runner also sleeps on `RATE_LIMITED` and retries). Needs `data/concierge.sqlite`
for bound cases; without it they are reported as skipped, never passed.

    python evals/runner.py --base-url http://localhost:7860 --rpm 12
    backend/.venv/Scripts/python evals/experiments.py        # E1 needs the backend deps (rank_bm25 etc.)
    python loadtest/load.py --mock-confirmed                 # 5 -> 20 -> 50 sessions
- `make_report.py` regenerates `REPORT.md` and the README numbers block from result files only (`--check` for staleness).
- Runner flags added: `--max-llm-calls N` (hard stop; required when the target reports llm.mode=live; judge is off in live runs), `--split tune|heldout`, `--llm-mode`. Result file adds `targets.*.ci95/n`, `by_language`, `by_split`, `run_context.llm_mode`; `live_subset.json` and `E1.json` are attached to `latest.json` by the next full mock run.
- `results/INVALID_db_swapped_mid_run_*.json`: a run whose database was replaced by the data lane mid-run; kept for transparency, never used.

## One source of truth
`results/latest.json` feeds `/api/evals` (baked into the image), REPORT.md and the README blocks (`make_report.py`). `python evals/make_report.py --check [--url https://APP] [--final]` fails on stale output, mismatched dataset ids, "all ... pass" claims the run contradicts, and (with `--final`) unfilled deploy placeholders. E1 now runs through `evals/e1_adapter.py` (`backend/.venv/Scripts/python evals/experiments.py --only E1`; no model calls) and records the dataset id it was measured on. See docs/DEPLOY.md for the order of steps.

## Live runs and the Gemini judge (eval only)
- `serve_eval.py nvidia|openrouter|mock PORT` starts the backend with keys loaded in-process from the gitignored `.env` (`envload.py`; values are never printed). `nvidia` sets `EVAL_LLM_PROVIDER=nvidia`: the same app, prompts, router and guardrails call the NVIDIA-hosted `nvidia/nemotron-3-ultra-550b-a55b`. The override is never set in the Dockerfile or deploy files (a test pins that).
- Answer-quality run: `runner.py --base-url http://localhost:8020 --max-llm-calls 400 --live-out live_nvidia.json --save-judge-input`, then `judge_pass.py` (Gemini, resumable, rotates Flash models when a free-tier daily cap is hit). Production-path check: `serve_eval.py openrouter 8021` with `LLM_DAILY_BUDGET=8`, then `runner.py --only R1,...,R7,A03,T01,O02 --live-out live_openrouter.json`.
- `judge_agreement.py sample|score`: 20 hand-labelled answers vs the judge, Cohen's kappa -> `results/judge_agreement.json`. Judge results are reported separately and never override a deterministic check.

## Persona round (frozen sets, NVIDIA-hosted different-family judge)
- `conversations_personas.yaml`: 60 frozen multi-turn conversations (2-4 turns) through five personas: buyer, investor, DarGlobal sales team, recruiter / HR, Head of AI. Written before the before-run; do not edit between before and after.
- `run_conversations.py --conv evals/conversations_personas.yaml --label personas_before --judge nvidia` records per-turn checks plus a 1-5 judge on helpful, honest, tone, persona_fit. New deterministic checks: `no_advice`, `no_raw_quote` (no 12-word run copied from a stored description), `no_leak`, `safety_template`, `graceful` (clean reply or clean 4xx on empty/long input), `no_code`, `no_emoji`; a turn may `repeat: N` its text. The cap rules are unchanged (`EVAL_MAX_LLM_CALLS`, stop on 402/quota or three 429s in a row).
- Judge: `EVAL_JUDGE_NVIDIA_MODEL` (default `google/gemma-4-31b-it`, a different family from the Nemotron model that writes the answers). It runs in a thread pool; if it is switched off after repeated failures Gemini takes over. `judge_conv_pass.py <result files>` is the resumable second pass for turns left unjudged.
- `make_showcase.py` now also writes `frontend/public/evals-all.json` (every case of the suites and every turn of the conversation and persona runs, with source label, persona, category, failing check names). The `/evals` page "Every measured case" section reads it: source / category / persona / result / answered-by filters, search, "show more" paging, totals per source.
