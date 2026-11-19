# Superseded eval runs

Kept for transparency only; none of these describes the current build or dataset.

- `20261119T0904..0943Z.json`, `baseline_before.json`: dataset 20261119-a983bac1 (before the DarGlobal extracts and third-party facts).
- `20261119T110754Z.json`, `20261119T111456Z.json`: dataset 20261119-99557436 (before the AIDA city fix and the honest source labels).
- `20261119T112217Z.json`: dataset 20261119-e5604e7e, but run by another lane against port 7897 while the fixer was still changing code; not reproducible.
- `INVALID_db_swapped_mid_run_*.json`: the database was replaced mid-run.

The current run is `../latest.json` (= `../20261119T113646Z.json`, mock LLM, dataset 20261119-e5604e7e) plus the
real-model subset `../live_subset.json` (5 cases, 4 real OpenRouter requests counted by the app budget).
`../E1.json` (retrieval experiment) was NOT re-run on this dataset: `evals/experiments.py --only E1` currently
fails with `TypeError: 'BM25Okapi' object is not iterable`.
