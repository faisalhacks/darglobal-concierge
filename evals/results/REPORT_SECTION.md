## Evaluation results

- Run at: 2026-11-19T15:33:17+00:00  |  Target: `http://localhost:8002`  |  Dataset: `20261119-eb33f465` (as of 2026-11-19)
- LLM available at run time: **True**  |  models: ['nvidia/nemotron-3-ultra-550b-a55b:free', 'google/gemma-4-31b-it:free', 'google/gemma-4-26b-a4b-it:free']
- Result: **170 passed, 0 failed, 1 skipped**

### Scores vs targets

| Metric | Target | Actual | Met |
|---|---|---|---|
| factual_rate | >= 0.9 | 1.0 | yes |
| citation_rate | >= 1.0 | 1.0 | yes |
| trap_rate | >= 1.0 | 1.0 | yes |
| injection_rate | >= 1.0 | 1.0 | yes |
| false_refusal_rate | <= 0.05 | 0.0 | yes |
| arabic_rate | >= 0.85 | 1.0 | yes |
| ttft_p95_ms | <= 3000 | 2390.5 | yes |
| crashes | <= 0 | 0 | yes |
| lighthouse_mobile | >= 90 | n/a | n/a |

### By category

| Category | Passed | Failed | Skipped | Rate |
|---|---|---|---|---|
| arabic | 20 | 0 | 0 | 1.0 |
| calculation | 5 | 0 | 0 | 1.0 |
| darglobal | 20 | 0 | 0 | 1.0 |
| factual | 30 | 0 | 0 | 1.0 |
| find_my_home | 5 | 0 | 0 | 1.0 |
| injection | 17 | 0 | 1 | 1.0 |
| live_sample | 10 | 0 | 0 | 1.0 |
| multi_turn | 15 | 0 | 0 | 1.0 |
| out_of_scope | 8 | 0 | 0 | 1.0 |
| over_blocking | 9 | 0 | 0 | 1.0 |
| reviewer | 7 | 0 | 0 | 1.0 |
| showcase | 4 | 0 | 0 | 1.0 |
| trap | 20 | 0 | 0 | 1.0 |

### Latency (ms)

p50 2156.5  |  p95 2406.0  |  TTFT p50 2156.0  |  TTFT p95 2390.5  (n=190)

### Failures (to be fixed and re-run)

- none

### Skipped (not counted as passed)

- I12: needs --planted-chunk (fixture not loaded)

### Confusion (expected intent -> actual)

```json
{
 "location_overview": {
  "location_overview": 1
 },
 "off_topic": {
  "off_topic": 12
 },
 "injection": {
  "injection": 17
 },
 "advice": {
  "advice": 4
 },
 "general": {
  "general": 1
 },
 "project_info": {
  "project_info": 1
 },
 "compare": {
  "compare": 3
 },
 "greeting": {
  "greeting": 1
 },
 "contact_sales": {
  "contact_sales": 3
 },
 "find_my_home": {
  "find_my_home": 4
 },
 "calculation": {
  "calculation": 5
 }
}
```

### Limitations

- Numbers checks use retrieved/card ids from the trace; they are a proxy for 'in context'.
- live_sample cases are sampled from the DB (scraped from live sites); the runner never contacts the live sites.
- Arabic judge scores appear only when OPENROUTER_API_KEY was set and the run is not live; otherwise Arabic is deterministic-only.
- CIs: Wilson 95% for proportions, percentile bootstrap for TTFT p95. n is small, so intervals are wide.
- llm_calls_counted counts every attempt (retries included) as one request: a ceiling, not a measurement.
