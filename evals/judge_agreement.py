#!/usr/bin/env python3
"""Judge agreement: Gemini judge vs hand labels, Cohen's kappa.

    python evals/judge_agreement.py sample   # writes evals/hand_label_sheet.json: 20 model-written answers, seed-fixed, chosen BEFORE looking at any verdict,
                                              # WITHOUT the judge's verdicts (what the judge saw, nothing else)
    python evals/judge_agreement.py score    # reads evals/hand_labels.json + the judge verdicts in
                                              # evals/results/live_nvidia.json -> evals/results/judge_agreement.json

Hand labels are a literal reading of evals/judge_rubric.md (binary per dimension), made before the judge's verdicts for
those answers were looked at. Nothing here calls a model.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
DIMS = ("grounded", "next_step", "tone", "language")


def sample(n=20, seed=7, src="live_nvidia.json"):
    d = json.loads((RES / src).read_text(encoding="utf-8"))
    pool = [c for c in d["cases"] if c.get("judge_input") or (c.get("judge") or {}).get("input")]  # model-written answers with a stored judge payload
    rng = random.Random(seed)
    key = lambda c: c["id"]  # noqa: E731
    model_ar = sorted([c for c in pool if c["lang"] == "ar" and c["turns"][-1].get("model")], key=key)
    model_en = sorted([c for c in pool if c["lang"] != "ar" and c["turns"][-1].get("model")], key=key)
    code_ar = sorted([c for c in pool if c["lang"] == "ar" and not c["turns"][-1].get("model")], key=key)
    code_en = sorted([c for c in pool if c["lang"] != "ar" and not c["turns"][-1].get("model")], key=key)
    pick: list = []
    for grp, k in ((model_ar, 5), (model_en, 7), (code_ar, 3), (code_en, 5)):
        pick += rng.sample(grp, min(k, len(grp)))
    rest = [c for c in pool if c not in pick]
    while len(pick) < n and rest:
        pick.append(rest.pop(rng.randrange(len(rest))))
    pick = sorted(pick[:n], key=key)
    sheet = [{"id": c["id"], "lang": c["lang"], "category": c["category"], "model_written": bool(c["turns"][-1].get("model")),
              "judge_input": c.get("judge_input") or c["judge"]["input"]} for c in pick]
    (HERE / "hand_label_sheet.json").write_text(json.dumps({"seed": seed, "source": src, "items": sheet}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(sheet)} items to evals/hand_label_sheet.json: " + ", ".join(x["id"] for x in sheet))


def kappa(pairs):
    """Cohen's kappa for binary labels [(hand, judge)]. None when chance agreement is 1 (kappa undefined)."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ph, pj = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = ph * pj + (1 - ph) * (1 - pj)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 4)


def score(src="live_nvidia.json"):
    d = json.loads((RES / src).read_text(encoding="utf-8"))
    hl = json.loads((HERE / "hand_labels.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in d["cases"]}
    labels = hl["labels"]
    out_dims, allp, rows = {}, [], []
    for dim in DIMS:
        pairs = []
        for cid, lab in labels.items():
            j = (by_id.get(cid) or {}).get("judge") or {}
            if not j.get("judged"):
                continue
            pairs.append((bool(lab[dim]), bool(j["dims"][dim]["pass"])))
        allp += pairs
        out_dims[dim] = {"n": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 4) if pairs else None,
                         "kappa": kappa(pairs), "hand_pass": sum(a for a, _ in pairs), "judge_pass": sum(b for _, b in pairs)}
    for cid, lab in labels.items():
        j = (by_id.get(cid) or {}).get("judge") or {}
        if j.get("judged"):
            for dim in DIMS:
                if bool(lab[dim]) != bool(j["dims"][dim]["pass"]):
                    rows.append({"id": cid, "dimension": dim, "hand": bool(lab[dim]), "judge": bool(j["dims"][dim]["pass"]),
                                 "hand_note": lab.get("notes", {}).get(dim, ""), "judge_critique": j["dims"][dim]["critique"]})
    pooled = {"n": len(allp), "agreement": round(sum(a == b for a, b in allp) / len(allp), 4) if allp else None, "kappa": kappa(allp),
              "hand_pass": sum(a for a, _ in allp), "judge_pass": sum(b for _, b in allp)}
    undefined = [k for k, v in out_dims.items() if v["kappa"] is None]
    note = (f"Pooled over {pooled['n']} binary decisions ({len(labels)} answers x {len(DIMS)} dimensions). " +
            ("Kappa is undefined for " + ", ".join(undefined) + " (one rater, or both, gave a single constant value, so chance agreement is 1); raw agreement is given instead. " if undefined else "") +
            f"{len(rows)} disagreement(s) are listed in evals/results/judge_agreement.json. With n={len(labels)} answers the kappa is a rough guide only. "
            "Labeller: the model that ran this evaluation (not an independent human); the labels follow the rubric text literally and were set from the rubric text, but they are not independent of the model family that wrote the rubric; the judge progress log was visible while labelling (see hand_labels.json method).")
    res = {"source": src, "n_answers": len(labels), "dims": out_dims, "pooled": pooled, "disagreements": rows, "note": note,
           "judge_model": (d.get("run_context") or {}).get("judge_model"), "hand_labels_file": "evals/hand_labels.json"}
    (RES / "judge_agreement.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dims": out_dims, "pooled": pooled}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sample", "score"])
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    sample(a.n) if a.cmd == "sample" else score()
    sys.exit(0)
