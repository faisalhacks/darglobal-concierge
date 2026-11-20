#!/usr/bin/env python3
"""Second pass: judge the stored answers of conversation / persona result files with the NVIDIA-hosted judge (resumable).

    python evals/judge_conv_pass.py evals/results/conv_personas_before.json evals/results/conv_before2.json [--workers 5]

Why a separate pass: NVIDIA's free endpoint queues requests, so a judge call can take a minute. Running the judge after the
answering run keeps the answering loop fast. Turns that already carry a judged verdict are kept. The judge model is
EVAL_JUDGE_NVIDIA_MODEL (default google/gemma-4-31b-it, a different family from the Nemotron model that wrote the answers);
Gemini is used only if the NVIDIA judge is switched off after repeated failures. Judge scores never change a check verdict.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_conversations as RC  # noqa: E402
from envload import load_env  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    load_env()
    if not os.environ.get("NVIDIA_API_KEY"):
        print("NVIDIA_API_KEY missing", file=sys.stderr)
        return 4
    J = RC.Judge("nvidia", a.workers)
    J.limit = a.limit
    for fp in a.files:
        path = Path(fp)
        d = json.loads(path.read_text(encoding="utf-8"))
        todo = []
        for c in d["conversations"]:
            says: list[str] = []
            for t in c["turns"]:
                says.append(t["say"])
                if not (t.get("judge") or {}).get("judged") and (t.get("answer") or "").strip():
                    payload = {"persona": c.get("persona") or "general", "question": t["say"], "earlier_user_turns": says[:-1][-3:],
                               "answer": t["answer"], "cards": (t.get("cards") or [])[:5], "chips": (t.get("chips") or [])[:4], "language": c.get("lang")}
                    fut = J.submit(payload)
                    if fut is not None:
                        todo.append((t, fut))
        print(f"{path.name}: judging {len(todo)} turns with {J.model}", flush=True)
        t0 = time.time()
        for n, (t, fut) in enumerate(todo, 1):
            try:
                t["judge"] = fut.result(timeout=1800)
            except Exception as e:  # noqa: BLE001
                t["judge"] = {"judged": False, "error": type(e).__name__}
            if n % 10 == 0:
                d["summary"] = RC.build_summary(d["conversations"])
                path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  {n}/{len(todo)} done, {round(time.time() - t0)}s, nvidia calls {J.calls['nvidia']}, gemini {J.calls['gemini']}", flush=True)
        d["summary"] = RC.build_summary(d["conversations"])
        d["judge"] = {"mode": "nvidia", "model": J.model, "calls": dict(J.calls), "note": J.note, "nvidia_judge_disabled": J.nv_off,
                      "judged_turns": sum(1 for c in d["conversations"] for t in c["turns"] if (t.get("judge") or {}).get("judged")),
                      "turns": d["summary"]["turns"]}
        d["judge_calls"] = sum(J.calls.values())
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{path.name}: judged {d['judge']['judged_turns']}/{d['judge']['turns']}; means {d['summary']['judge_means']}", flush=True)
        J.submitted = 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
