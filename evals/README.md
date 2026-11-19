# evals/

- `cases.yaml` 135 cases (SPEC 20.1 table), written before any backend code. Check vocabulary is documented in its header.
- `runner.py` SSE runner. `python evals/runner.py --list` validates without network.
- `experiments.py` E1 (retrieval) and E2 (routing). Skips with a message when it cannot measure.
- `judge_rubric.md` Arabic LLM-judge rubric (used only when `OPENROUTER_API_KEY` is set; model via `EVAL_JUDGE_MODEL`).
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
