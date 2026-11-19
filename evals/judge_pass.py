#!/usr/bin/env python3
"""Second pass: Gemini-judge the model-written answers stored in a live result file (resumable).

    python evals/runner.py --base-url http://localhost:8020 --max-llm-calls 400 --live-out live_nvidia.json --save-judge-input
    python evals/judge_pass.py [--file evals/results/live_nvidia.json]

Why a separate pass: Gemini's free tier caps each model at about 20 requests a day. The pass walks a list of Flash
models (EVAL_JUDGE_GEMINI_MODELS, comma list) and moves to the next one when a model reports its daily cap; every
verdict records which model produced it. It stops when the list is used up and can be re-run later: cases already
judged are kept. Judge results never change a deterministic pass/fail.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runner  # noqa: E402
from envload import load_env  # noqa: E402

DEFAULT_MODELS = ("gemini-2.5-flash-lite,gemini-2.5-flash,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3.6-flash,"
                  "gemini-3.7-flash,gemini-3.8-flash")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(HERE / "results" / "live_nvidia.json"))
    ap.add_argument("--rpm", type=float, default=10)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    load_env(names=("GEMINI_API_KEY",))
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print("GEMINI_API_KEY missing", file=sys.stderr)
        return 4
    models = [m.strip() for m in os.environ.get("EVAL_JUDGE_GEMINI_MODELS", DEFAULT_MODELS).split(",") if m.strip()]
    path = Path(a.file)
    d = json.loads(path.read_text(encoding="utf-8"))
    rubric = (HERE / "judge_rubric.md").read_text(encoding="utf-8")
    thr = runner.Throttle(a.rpm)
    counters = {m: {"calls": 0, "http_errors": {}} for m in models}
    todo = [c for c in d["cases"] if c.get("judge_input") and not (c.get("judge") or {}).get("judged")]
    done = 0
    mi = 0

    prev_calls0 = d["run_context"].get("judge_calls") or 0
    errs0 = dict(d["run_context"].get("judge_http_errors") or {})

    def finalize(final=False):
        ran = [x for x in d["cases"] if x.get("status") != "skipped"]
        d["judge_summary"] = runner.judge_summary(ran)
        used = sorted({(x.get("judge") or {}).get("model") for x in ran if (x.get("judge") or {}).get("judged")})
        rc = d["run_context"]
        rc["judge_used"] = bool(used)
        rc["judge_model"] = ", ".join(used) if used else None
        rc["judge_models_tried"] = models
        rc["judge_calls"] = prev_calls0 + sum(v["calls"] for v in counters.values())
        errs = dict(errs0)
        for v in counters.values():
            for k, n in v["http_errors"].items():
                errs[k] = errs.get(k, 0) + n
        rc["judge_http_errors"] = errs
        rc["judge_pass"] = "evals/judge_pass.py (second pass over stored answers)"
        path.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        if final:
            print(f"FINAL judged this pass: {done}; total judged: {d['judge_summary']['n_judged']} of {len(todo) + d['judge_summary']['n_judged'] - done} model-written answers; models: {used}")

    for c in todo:
        if a.limit and done >= a.limit:
            break
        while mi < len(models):
            m = models[mi]
            ex = cf.ThreadPoolExecutor(max_workers=1)
            fut = ex.submit(runner.judge, c["judge_input"], rubric, key, m, thr, counters[m], 60)
            try:
                res = fut.result(timeout=150)  # hard wall-clock cap: a stalled connection must not block the pass
            except cf.TimeoutError:
                res = {"judged": False, "error": "no answer within 150 s (stalled connection)", "model": m}
            ex.shutdown(wait=False, cancel_futures=True)
            if res.get("judged"):
                res["input"] = c["judge_input"]
                c["judge"] = res
                done += 1
                finalize()  # save after every verdict: a stopped pass loses nothing
                print(f"{c['id']} judged by {m}: {'ALL PASS' if res['all_pass'] else 'flags: ' + ','.join(k for k, v in res['dims'].items() if not v['pass'])}", flush=True)
                break
            if counters[m].get("quota_exhausted"):
                print(f"[{m}] daily quota exhausted -> next model", flush=True)
                mi += 1
                continue
            c["judge"] = res  # transient failure: recorded, can be retried by a re-run
            print(f"{c['id']} not judged ({res.get('error')})", flush=True)
            break
        else:
            print("[stop] every judge model's daily quota is exhausted; re-run later to continue", flush=True)
            break
    finalize(final=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
