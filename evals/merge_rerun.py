"""Merge a fix-round re-run (only the conversations that failed) into an after-run file.

    python evals/merge_rerun.py conv_personas_after.json conv_personas_rerun.json
    python evals/merge_rerun.py conv_after2.json conv_30_rerun.json

The after file keeps every conversation it measured; the re-run conversations replace theirs (whole conversations, so
turn state carries over as it did live). The pre-merge after file and the raw re-run file are moved to
results/superseded/, so make_showcase.py (which reads every results/conv_*.json) does not count them twice. The merged
file records what was replaced under "fix_round", and its summary is rebuilt with the runner's own build_summary()."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_conversations import build_summary  # noqa: E402

RES = HERE / "results"


def main(after_name: str, rerun_name: str) -> int:
    ap, rp = RES / after_name, RES / rerun_name
    a = json.loads(ap.read_text(encoding="utf-8"))
    r = json.loads(rp.read_text(encoding="utf-8"))
    new = {c["id"]: c for c in r["conversations"] if c.get("turns")}
    for c in new.values():
        for t in c["turns"]:
            t["fix_round"] = True
    sup = RES / "superseded"
    sup.mkdir(exist_ok=True)
    shutil.copy2(ap, sup / ap.name.replace(".json", ".pre_fixround.json"))
    a["conversations"] = [new.get(c["id"], c) for c in a["conversations"]]
    rounds = a.setdefault("fix_rounds", [])
    rounds.append({"label": r.get("label"), "run_at": r.get("run_at"), "conversations": sorted(new),
                   "llm_calls_counted": r.get("llm_calls_counted"), "max_llm_calls": r.get("max_llm_calls"),
                   "judge_calls": r.get("judge_calls"), "judge": r.get("judge"), "stop_reason": r.get("stop_reason"),
                   "provider": r.get("provider"), "model": r.get("model"),
                   "summary_rerun_only": r.get("summary")})
    a["summary_pre_fixround"] = a.get("summary_pre_fixround") or a.get("summary")
    a["summary"] = build_summary(a["conversations"])
    ap.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.move(str(rp), str(sup / rp.name))
    def passed(s):
        return sum(v["passed"] for v in s["turn_pass_by_category"].values()), s["turns"]
    print(f"{after_name}: replaced {len(new)} conversations; turns passed {passed(a['summary_pre_fixround'])} -> "
          f"{passed(a['summary'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
