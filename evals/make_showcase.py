"""Build data/showcase.json (the "Stress-tested" block) from RECORDED eval results only.

    python evals/make_showcase.py [--results-dir evals/results] [--cases evals/cases.yaml] [--out data/showcase.json]

Reads evals/results/latest.json and every evals/results/live_*.json. For each scenario it walks a list of candidate
case ids (the exact showcase phrasing first, then the closest existing case) and takes the first one a LIVE file
recorded, else the first one latest.json recorded. Every reply excerpt, count and trace field is copied from the
results file; nothing is written by hand. A scenario with no recorded candidate is left out of the JSON and listed
under "missing" (its showcase case lives in evals/cases.yaml, category "showcase", so the next run captures it).

Verdict lines are assembled from fixed phrases, and each phrase is used only when the recorded case PASSED and the
case's own checks in cases.yaml back it (for example "nothing leaked" needs a passed no_prompt_leak check).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXCERPT_CHARS = 220

# key, candidate case ids (preferred first), labels, the action phrase (claimed only on a pass), extra phrases
# keyed by the check that backs them, and whether the scenario rotates in the home-rail block.
SCENARIOS = [
    {"key": "greeting", "cands": ["SH01", "A07"], "label": ("Vague greeting", "تحية بلا سؤال"),
     "act": ("Answered the greeting", "ردّ على التحية"), "extras": ["chips_min"], "rail": False},
    {"key": "messy_search", "cands": ["SH02", "SH04", "A09", "A10"], "label": ("Messy search", "بحث بصياغة عفوية"),
     "act": ("Understood the request", "فهم الطلب"), "extras": ["no_invented_prices"], "rail": False},
    {"key": "off_topic", "cands": ["O01"], "label": ("Off-topic", "خارج الموضوع"),
     "act": ("Declined and pointed back to property", "اعتذر وأعاد الحديث إلى العقارات"), "extras": [], "rail": True},
    {"key": "injection_en", "cands": ["I01", "R4", "I14"], "label": ("Prompt injection, English", "محاولة تجاوز التعليمات بالإنجليزية"),
     "act": ("Refused calmly", "رفض بهدوء"), "extras": ["no_prompt_leak"], "rail": True},
    {"key": "injection_ar", "cands": ["I04", "I17", "A04"], "label": ("Prompt injection, Arabic", "محاولة تجاوز التعليمات بالعربية"),
     "act": ("Refused calmly", "رفض بهدوء"), "extras": ["no_prompt_leak"], "rail": False},
    {"key": "investment_advice", "cands": ["SH03", "R5", "A05"], "label": ("Investment advice", "طلب نصيحة استثمارية"),
     "act": ("Declined to promise a return", "امتنع عن الوعد بأي عائد"), "extras": [], "rail": False},
    {"key": "invented_project", "cands": ["R7", "T01"], "label": ("Invented project", "مشروع غير موجود"),
     "act": ("Said it is not in the data", "أوضح أنه غير موجود في البيانات"), "extras": ["no_invented_prices"], "rail": True},
    {"key": "steering", "cands": ["S01", "S02", "S04"], "label": ("Steering trap", "طلب فرز السكان حسب الهوية"),
     "act": ("Declined to filter people by identity", "رفض فرز الناس حسب هويتهم"), "extras": [], "rail": False},
    {"key": "multi_turn", "cands": ["M02", "M03", "M10"], "label": ("Multi-turn follow-up", "سؤال متابعة"),
     "act": ("Kept the context of the first question", "حافظ على سياق السؤال الأول"), "extras": [], "rail": False},
]
EXTRA = {
    "no_prompt_leak": ("nothing leaked", "لم يكشف شيئًا من تعليماته"),
    "no_invented_prices": ("no price invented", "لم يختلق أي سعر"),
    "chips_min": ("offered next questions", "اقترح أسئلة تالية"),
}
# Rail order: injection, invented project, off-topic.
RAIL_ORDER = ["injection_en", "invented_project", "off_topic"]


def _load(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def load_case_checks(cases_path: str) -> dict[str, dict]:
    """id -> {"checks": merged checks of the LAST turn}. YAML anchors (<<: *safe) are resolved by the loader."""
    try:
        import yaml  # the runner's dependency; run with backend/.venv
    except ImportError:
        print("PyYAML is needed (run with backend/.venv/Scripts/python)", file=sys.stderr)
        raise
    with open(cases_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    out = {}
    for c in doc.get("cases") or []:
        checks = dict(c.get("checks") or {})
        turns = c.get("turns") or []
        if turns and isinstance(turns[-1], dict):
            checks.update(turns[-1].get("checks") or {})
        out[c["id"]] = {"checks": checks, "category": c.get("category")}
    return out


def sources_in(results_dir: str) -> list[dict]:
    """Live files first (preferred), then latest.json."""
    srcs = []
    order = {"live_nvidia.json": 0, "live_openrouter.json": 1, "live_subset.json": 2}  # NVIDIA answers first
    for p in sorted(glob.glob(os.path.join(results_dir, "live_*.json")), key=lambda x: (order.get(os.path.basename(x), 9), x)):
        d = _load(p)
        if d and isinstance(d.get("cases"), list):
            srcs.append({"path": p, "data": d, "live": True, "llm_mode": "live"})
    p = os.path.join(results_dir, "latest.json")
    d = _load(p)
    if d and isinstance(d.get("cases"), list):
        mode = ((d.get("run_context") or {}).get("llm_mode")) or None
        srcs.append({"path": p, "data": d, "live": mode == "live", "llm_mode": mode})
    return srcs


def find(cands: list[str], srcs: list[dict]):
    for live_pass in (True, False):
        for cid in cands:
            for s in srcs:
                if s["live"] != live_pass:
                    continue
                for c in s["data"]["cases"]:
                    if c.get("id") == cid and c.get("status") != "skipped" and c.get("turns"):
                        return c, s
    return None, None


def llm_calls_for(turn: dict, case: dict, llm_mode: str | None):
    """(value, basis). Recorded when the run stored it; otherwise derived only where the path makes it certain."""
    if isinstance(turn.get("llm_calls"), int):
        return turn["llm_calls"], "recorded"
    path, model = turn.get("path") or case.get("path"), turn.get("model") or case.get("model")
    if path == "template" and not model:
        return 0, "derived: template path, no model answered"
    if llm_mode == "live" and not model:
        return 0, "derived: live run, no model answered"
    if llm_mode == "mock":
        return None, "not measured: the language model was mocked in this run"
    return None, "not recorded"


def verdict(sc: dict, case: dict, checks: dict, calls: int | None, model: str | None, llm_mode: str | None):
    if not case.get("passed"):
        why = "; ".join(case.get("failures") or [])[:160] or "a check failed"
        return {"en": f"Did not pass: {why}", "ar": f"لم يجتز الاختبار: {why}"}
    en, ar = [sc["act"][0]], [sc["act"][1]]
    if calls == 0:
        en.append("0 AI calls"); ar.append("دون أي استدعاء للذكاء الاصطناعي")
    elif isinstance(calls, int):
        en.append(f"{calls} AI call" + ("" if calls == 1 else "s")); ar.append("استدعاء واحد للنموذج" if calls == 1 else f"{calls} استدعاءات للنموذج")
    elif model and llm_mode == "live" and not str(model).startswith("mock"):
        en.append("written by a live model"); ar.append("كتبه نموذج حقيقي")
    for k in sc["extras"]:
        if k in checks and checks[k] and k in EXTRA:
            en.append(EXTRA[k][0]); ar.append(EXTRA[k][1])
    return {"en": " · ".join(en), "ar": " · ".join(ar)}


GALLERY_EXCERPT_CHARS = 320
# Gallery categories: (key, EN, AR, candidate case ids in preference order). Each case is used once (first category
# that lists it wins). Up to PER_CATEGORY are shown: passed first, live-model records before mocked ones.
GALLERY = [
    ("greetings", "Greetings and small talk", "التحيات والحديث العابر", ["SH01", "A07", "A20", "A13"]),
    ("vague", "Vague requests", "طلبات غامضة", ["M11", "H01", "A14", "H05"]),
    ("messy_search", "Messy search (BHK, budgets, $)", "بحث عفوي (غرف، ميزانيات، $)", ["SH02", "A09", "H03", "A18", "B02"]),
    ("arabic", "Arabic and dialect", "العربية واللهجات", ["SH04", "A10", "A17", "A01", "R6", "A08"]),
    ("multi_turn", "Multi-turn follow-ups", "أسئلة المتابعة", ["M02", "M05", "M12", "H02", "M07", "M03"]),
    ("comparisons", "Comparisons", "المقارنات", ["F29", "F30", "A16", "M07"]),
    ("calculations", "Calculations and currency", "الحسابات والعملات", ["C04", "C01", "C03", "A11", "M14", "C02"]),
    ("not_found", "Invented projects and places", "مشاريع وأماكن غير موجودة", ["R7", "T03", "T01", "T04", "T15", "A06", "T11"]),
    ("off_topic", "Off-topic pivot", "خارج الموضوع", ["O01", "O03", "O05", "R3", "A19", "O06"]),
    ("adjacent", "Adjacent topics (mortgage, rules, tax)", "مواضيع مجاورة (رهن، أنظمة، ضرائب)", ["T13", "B03", "T10"]),
    ("unknowable", "Facts it does not have", "معلومات لا يملكها", ["T06", "T07", "T08", "T09", "T12", "T14"]),
    ("investment", "Investment advice", "النصيحة الاستثمارية", ["SH03", "R5", "A05", "D09"]),
    ("injection_en", "Prompt injection, English", "تجاوز التعليمات بالإنجليزية", ["I01", "R4", "I02", "I14", "I10", "I03"]),
    ("injection_ar", "Prompt injection, Arabic", "تجاوز التعليمات بالعربية", ["I04", "I05", "A04", "I17"]),
    ("injection_obf", "Prompt injection, obfuscated", "تجاوز التعليمات بالتمويه", ["I11", "I16", "I18", "I07", "I09", "I06", "I12"]),
    ("steering", "Steering and fair housing", "التوجيه والإسكان العادل", ["S01", "S02", "S04", "S05", "S03"]),
    ("over_blocking", "Over-blocking: legit questions that sound suspicious", "حجب مفرط: أسئلة مشروعة تبدو مريبة", ["B04", "B01", "B06", "B07", "S06", "B05"]),
]
PER_CATEGORY = 3


def _failed_keys(case: dict, keys: list[str]) -> set[str]:
    txt = " ".join(case.get("failures") or []).lower()
    return {k for k in keys if k.lower() in txt}


def source_label(src: dict, case: dict, turn: dict) -> dict:
    """provider/model/label of the run that produced a record, from the result file only."""
    d = src["data"]
    if src["llm_mode"] != "live":
        return {"provider": None, "model": None, "label": "model mocked"}
    rc = d.get("run_context") or {}
    prov = rc.get("llm_provider") or "openrouter"  # live_subset.json predates the field and was an OpenRouter run
    model = turn.get("model") or case.get("model")  # per card: only when a model wrote this answer
    via = {"nvidia": "NVIDIA API", "openrouter": "OpenRouter"}.get(prov, prov)
    if not model:  # the answer on this card was built by code; the run was still live
        return {"provider": prov, "model": None, "label": f"live run via {via}; answer built by code"}
    return {"provider": prov, "model": model, "label": f"live model: {model} via {via}"}


def _gallery_entry(cat_key: str, case: dict, src: dict, checks: dict) -> dict:
    d, turns = src["data"], case["turns"]
    last = turns[-1]
    answer = last.get("answer") if isinstance(last.get("answer"), str) else (last.get("reply_excerpt") or "")
    calls, basis = llm_calls_for(last, case, src["llm_mode"])
    base = d.get("base_url")
    bad = _failed_keys(case, list(checks))
    live = src["llm_mode"] == "live"
    return {
        "id": case["id"], "category": cat_key, "lang": case.get("lang"),
        "questions": [t.get("say") for t in turns],
        "reply_excerpt": answer[:GALLERY_EXCERPT_CHARS],  # verbatim prefix of the recorded reply
        "reply_truncated": len(answer) > GALLERY_EXCERPT_CHARS,
        "cards_count": len(last.get("card_ids") or []),
        "sources_count": len(last.get("sources") or []),
        "trace": {"intent": last.get("intent") or case.get("intent"), "path": last.get("path") or case.get("path"),
                  "llm_calls": calls, "llm_calls_basis": basis, "model": last.get("model") or case.get("model"),
                  "latency_ms": case.get("latency_ms")},
        "passed": bool(case.get("passed")), "failures": case.get("failures") or [],
        "checks": [{"key": k, "ok": k not in bad} for k in checks],
        "source": {"llm_mode": src["llm_mode"], **source_label(src, case, last),
                   "host": urlparse(base).netloc if isinstance(base, str) and base else None,
                   "run_at": d.get("run_at"), "file": _rel(src["path"]), "dataset_version": d.get("dataset_version")},
    }


def build_gallery(srcs: list[dict], checks_by_id: dict) -> dict:
    recs: dict[str, list] = {}
    for s in srcs:
        for c in s["data"]["cases"]:
            if c.get("status") != "skipped" and c.get("turns") and c.get("id"):
                recs.setdefault(c["id"], []).append((c, s))
    used, cats, any_failed = set(), [], False
    for key, en, ar, cands in GALLERY:
        opts = []
        for i, cid in enumerate(cands):
            if cid in used or cid not in recs:
                continue
            # live record preferred, else the latest.json one
            c, s = sorted(recs[cid], key=lambda cs: not cs[1]["live"])[0]
            opts.append((not c.get("passed"), not s["live"], i, c, s))
        opts.sort(key=lambda o: o[:3])
        picked = opts[:PER_CATEGORY]
        # honesty: a failed record of a candidate case is always shown, replacing the last pick
        failed = [o for o in opts if o[0]]
        if failed and not any(p[0] for p in picked):
            picked = picked[:PER_CATEGORY - 1] + [failed[0]]
        entries = []
        for _, _, _, c, s in picked:
            used.add(c["id"])
            any_failed |= not c.get("passed")
            entries.append(_gallery_entry(key, c, s, (checks_by_id.get(c["id"]) or {}).get("checks") or {}))
        if entries:
            cats.append({"id": key, "label": {"en": en, "ar": ar}, "entries": entries})
    ents = [e for c in cats for e in c["entries"]]
    return {"categories": cats, "excerpt_chars": GALLERY_EXCERPT_CHARS, "per_category": PER_CATEGORY,
            "stats": {"entries": len(ents), "categories": len(cats), "passed": sum(e["passed"] for e in ents),
                      "failed": sum(not e["passed"] for e in ents), "failed_case_exists_in_results": any_failed,
                      "live_entries": sum(e["source"]["llm_mode"] == "live" for e in ents)}}


def build(results_dir: str, cases_path: str) -> dict:
    srcs = sources_in(results_dir)
    checks_by_id = load_case_checks(cases_path)
    scenarios, missing = [], []
    for sc in SCENARIOS:
        case, src = find(sc["cands"], srcs)
        if not case:
            missing.append({"key": sc["key"], "candidates": sc["cands"]})
            continue
        d = src["data"]
        turns = case["turns"]
        last = turns[-1]
        answer = last.get("answer") if isinstance(last.get("answer"), str) else (last.get("reply_excerpt") or "")
        excerpt = answer[:EXCERPT_CHARS]  # verbatim prefix of the recorded reply
        calls, basis = llm_calls_for(last, case, src["llm_mode"])
        model = last.get("model") or case.get("model")
        base = d.get("base_url")
        checks = (checks_by_id.get(case["id"]) or {}).get("checks") or {}
        scenarios.append({
            "id": sc["key"],
            "case_id": case["id"],
            "category": {"en": sc["label"][0], "ar": sc["label"][1]},
            "lang": case.get("lang"),
            "question": turns[0].get("say") if len(turns) > 1 else last.get("say"),
            "follow_ups": [t.get("say") for t in turns[1:]],
            "reply_excerpt": excerpt,
            "reply_truncated": len(answer) > len(excerpt),
            "cards_count": len(last.get("card_ids") or []),
            "sources_count": len(last.get("sources") or []),
            "trace": {
                "intent": last.get("intent") or case.get("intent"),
                "path": last.get("path") or case.get("path"),
                "llm_calls": calls,
                "llm_calls_basis": basis,
                "model": model,
                "latency_ms": case.get("latency_ms"),
            },
            "passed": bool(case.get("passed")),
            "failures": case.get("failures") or [],
            "checks": sorted(k for k, v in checks.items() if v),
            "verdict": verdict(sc, case, checks, calls, model, src["llm_mode"]),
            "rail": sc["key"] in RAIL_ORDER,
            "captured_at": d.get("run_at"),
            "host": urlparse(base).netloc if isinstance(base, str) and base else None,
            "llm_mode": src["llm_mode"],
            "dataset_version": d.get("dataset_version"),
            "source_file": _rel(src["path"]),
        })
    captured = {s["case_id"] for s in scenarios}
    pending = sorted(cid for cid, v in checks_by_id.items() if v.get("category") == "showcase" and cid not in captured)
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "generator": "evals/make_showcase.py",
        "excerpt_chars": EXCERPT_CHARS,
        "rail_order": [k for k in RAIL_ORDER if any(s["id"] == k for s in scenarios)],
        "inputs": [{"file": _rel(s["path"]), "run_at": s["data"].get("run_at"), "llm_mode": s["llm_mode"],
                    "dataset_version": s["data"].get("dataset_version")} for s in srcs],
        "scenarios": scenarios,
        "gallery": build_gallery(srcs, checks_by_id),
        "missing": missing,
        "pending_showcase_cases": pending,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", default=os.path.join(HERE, "results"))
    ap.add_argument("--cases", default=os.path.join(HERE, "cases.yaml"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "showcase.json"))
    a = ap.parse_args(argv)
    out = build(a.results_dir, a.cases)
    if not out["scenarios"]:
        print("no recorded results found; showcase not written", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"{len(out['scenarios'])} scenarios -> {a.out}; missing={[m['key'] for m in out['missing']]}; "
          f"pending showcase cases={out['pending_showcase_cases']}")
    g = out["gallery"]
    print(f"gallery: {g['stats']}")
    for c in g["categories"]:
        print(f"  [{c['id']}] " + ", ".join(f"{e['id']}{'' if e['passed'] else '(FAIL)'}/{e['source']['llm_mode']}" for e in c["entries"]))
    for s in out["scenarios"]:
        print(f"  {s['id']:<18} {s['case_id']:<5} {'PASS' if s['passed'] else 'FAIL'}  {s['source_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
