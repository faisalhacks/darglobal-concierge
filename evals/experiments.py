#!/usr/bin/env python3
"""SPEC 20.3 experiments.  Never fabricates: an experiment that cannot run is SKIPPED with a reason
and writes no result file.

E1  BM25 vs embeddings vs hybrid retrieval, English and Arabic separately.
    Imports retrieval functions from backend.app (module `retrieval` by default). If it is not
    importable or exposes no recognisable functions, E1 is skipped. Override with
      --retrieval-module backend.app.retrieval --bm25 NAME --vector NAME --hybrid NAME
    Each function is called as fn(query, k=K) (falling back to fn(query)) and must return a list of
    results, each a dict/obj/tuple carrying a chunk id and/or entity id.
    Ground truth is built from the DB: known-item queries (project name EN / AR) with the gold project,
    plus "projects in <city>" queries scored by precision@K on chunk.city. This is a proxy benchmark;
    it is NOT a measure of end-to-end answer quality.

E2  Code routing vs LLM routing, on the static single-turn cases of cases.yaml that declare an `intent`.
    code side  = the running backend (trace.intent / trace.llm_calls / latency), via --base-url.
    llm side   = a free OpenRouter model asked to classify the intent; only when OPENROUTER_API_KEY is set.

Usage: python evals/experiments.py [--only E1|E2] [--base-url ...] [--db ...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import runner as R  # noqa: E402  (reuse DB + SSE helpers)

K = 6
INTENTS = ["project_info", "compare", "search", "calculation", "location_overview", "brand_partner",
           "contact_sales", "find_my_home", "off_topic", "injection", "advice", "general"]


def _pick(mod, names, hints):
    for n in names:
        if n and hasattr(mod, n):
            return getattr(mod, n), n
    for attr in dir(mod):
        if callable(getattr(mod, attr)) and all(h in attr.lower() for h in hints) and not attr.startswith("_"):
            return getattr(mod, attr), attr
    return None, None


def _ids(results):
    """Normalise retrieval results -> list of (chunk_id, entity_id)."""
    out = []
    for r in results or []:
        if isinstance(r, dict):
            out.append((r.get("id") or r.get("chunk_id"), r.get("entity_id")))
        elif isinstance(r, (tuple, list)):
            out.append((r[0] if not isinstance(r[0], (dict, list, tuple)) else (r[0].get("id") if isinstance(r[0], dict) else None), None))
        else:
            out.append((getattr(r, "id", None) or getattr(r, "chunk_id", None), getattr(r, "entity_id", None)))
    return out


def e1(args, db):
    if not db.ok:
        return skip("E1", f"database not found at {args.db}")
    try:
        mod = importlib.import_module(args.retrieval_module)
    except Exception as e:  # noqa: BLE001
        return skip("E1", f"cannot import {args.retrieval_module}: {type(e).__name__}: {e}")
    fns = {
        "bm25": _pick(mod, [args.bm25, "bm25_search", "search_bm25", "bm25"], ["bm25"]),
        "embeddings": _pick(mod, [args.vector, "vector_search", "search_vector", "embedding_search", "dense_search"], ["vec"]),
        "hybrid": _pick(mod, [args.hybrid, "hybrid_search", "search_hybrid", "search", "retrieve"], ["hybrid"]),
    }
    missing = [k for k, (f, _) in fns.items() if f is None]
    if len(missing) == 3:
        return skip("E1", f"{args.retrieval_module} exposes no recognisable bm25/vector/hybrid function; pass --bm25/--vector/--hybrid")

    chunk_entity = {r["id"]: r["entity_id"] for r in db.all("SELECT id, entity_id FROM chunks")}
    chunk_city = {r["id"]: r["city"] for r in db.all("SELECT id, city FROM chunks")}
    projs = db.all("SELECT id, name_en, name_ar, city FROM projects ORDER BY id")
    cities = [r["city"] for r in db.all("SELECT city, COUNT(*) n FROM projects WHERE city IS NOT NULL GROUP BY city ORDER BY n DESC, city LIMIT 10")]
    sets = {
        "en_name": [(p["name_en"], p["id"]) for p in projs if p["name_en"]],
        "ar_name": [(p["name_ar"], p["id"]) for p in projs if p["name_ar"]],
        "en_city": [(f"projects in {c}", c) for c in cities],
    }
    table, notes = {}, []
    for method, (fn, fname) in fns.items():
        if fn is None:
            notes.append(f"{method}: function not found, not measured")
            continue
        for qs, items in sets.items():
            hit1 = hit3 = hit6 = mrr = prec = n = 0
            t0 = time.monotonic()
            for q, gold in items:
                try:
                    try:
                        res = fn(q, k=K)
                    except TypeError:
                        res = fn(q)
                except Exception as e:  # noqa: BLE001
                    notes.append(f"{method}/{qs}: {type(e).__name__}: {e}")
                    break
                ids = _ids(res)[:K]
                ents = [e or chunk_entity.get(c) for c, e in ids]
                n += 1
                if qs.endswith("_name"):
                    if ents and ents[0] == gold:
                        hit1 += 1
                    if gold in ents[:3]:
                        hit3 += 1
                    if gold in ents:
                        hit6 += 1
                        mrr += 1 / (ents.index(gold) + 1)
                else:
                    cs = [chunk_city.get(c) for c, _ in ids]
                    prec += (sum(1 for c in cs if c == gold) / len(cs)) if cs else 0
            if n:
                table.setdefault(method, {})[qs] = (
                    {"n": n, "hit@1": round(hit1 / n, 3), "recall@1": round(hit1 / n, 3), "recall@3": round(hit3 / n, 3), f"recall@{K}": round(hit6 / n, 3), f"hit@{K}": round(hit6 / n, 3), "mrr": round(mrr / n, 3)}
                    if qs.endswith("_name") else {"n": n, f"precision@{K}": round(prec / n, 3)}
                ) | {"ms_per_query": round((time.monotonic() - t0) * 1000 / n, 1)}
    if not table:
        return skip("E1", "no method produced results: " + "; ".join(notes))
    return {"experiment": "E1", "functions": {k: v[1] for k, v in fns.items()}, "results": table, "notes": notes,
            "caveat": "Proxy benchmark built from the DB itself (known-item + city precision); small n; not end-to-end quality."}


def e2(args, db):
    import yaml
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    items = []
    for c in cases:
        if c.get("bind") or c.get("requires") or len(c["turns"]) != 1:
            continue
        exp = (c.get("checks") or {}).get("intent")
        if exp and isinstance(c["turns"][0], str):
            items.append((c["id"], c["turns"][0], exp))
    try:
        R.http_json(args.base_url, "/api/meta")
    except Exception as e:  # noqa: BLE001
        return skip("E2", f"backend not reachable at {args.base_url}: {e}")
    thr = R.Throttle(args.rpm)
    code = {"correct": 0, "n": 0, "lat": [], "llm_calls": 0, "details": []}
    for cid, msg, exp in items:
        thr.wait()
        rep = R.Reply(R.chat_stream(args.base_url, {"session_id": f"exp-{cid}", "message": msg, "history": [], "lang": "auto"}))
        if rep.error or not rep.done:
            code["details"].append({"id": cid, "error": (rep.error or {}).get("code") or rep.raw.get("transport_error")})
            continue
        code["n"] += 1
        code["correct"] += rep.intent in exp
        code["lat"].append(rep.latency_ms)
        code["llm_calls"] += int(rep.trace.get("llm_calls") or 0)
        if rep.intent not in exp:
            code["details"].append({"id": cid, "expected": exp, "got": rep.intent})
    out = {"experiment": "E2", "n_cases": len(items), "code_routing": {
        "accuracy": round(code["correct"] / code["n"], 3) if code["n"] else None, "n": code["n"],
        "latency_p50_ms": R.pct(code["lat"], 0.5), "latency_p95_ms": R.pct(code["lat"], 0.95),
        "llm_calls_per_message": round(code["llm_calls"] / code["n"], 3) if code["n"] else None, "misses": code["details"][:20]},
        "note": "code routing = full backend answer path; its latency includes retrieval + rendering, the LLM side measures the classification call only."}
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        out["llm_routing"] = {"skipped": "OPENROUTER_API_KEY not set"}
        return out
    model = os.getenv("EVAL_JUDGE_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    thr = R.Throttle(min(args.rpm, 15))
    ok = n = 0
    lat, miss = [], []
    for cid, msg, exp in items:
        thr.wait()
        body = {"model": model, "temperature": 0, "messages": [
            {"role": "system", "content": "Classify the user message for a property concierge. Answer with exactly one label from: " + ", ".join(INTENTS)},
            {"role": "user", "content": msg}]}
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                txt = json.loads(r.read())["choices"][0]["message"]["content"].strip().lower()
        except Exception as e:  # noqa: BLE001
            miss.append({"id": cid, "error": f"{type(e).__name__}"})
            continue
        lat.append((time.monotonic() - t0) * 1000)
        label = next((i for i in INTENTS if re.search(rf"\b{i}\b", txt)), txt[:30])
        n += 1
        ok += label in exp
        if label not in exp:
            miss.append({"id": cid, "expected": exp, "got": label})
    out["llm_routing"] = {"model": model, "accuracy": round(ok / n, 3) if n else None, "n": n, "latency_p50_ms": R.pct(lat, 0.5),
                          "latency_p95_ms": R.pct(lat, 0.95), "llm_calls_per_message": 1.0, "misses": miss[:20]}
    return out


def skip(name, why):
    print(f"[SKIP] {name}: {why}")
    return {"experiment": name, "skipped": why}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["E1", "E2"])
    ap.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://localhost:7860"))
    ap.add_argument("--db", default=str(ROOT / "data" / "concierge.sqlite"))
    ap.add_argument("--rpm", type=float, default=12)
    ap.add_argument("--retrieval-module", default="backend.app.retrieval")
    ap.add_argument("--bm25"), ap.add_argument("--vector"), ap.add_argument("--hybrid")
    ap.add_argument("--out-dir", default=str(HERE / "results"))
    args = ap.parse_args()
    db = R.DB(Path(args.db))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in (("E1", e1), ("E2", e2)):
        if args.only and args.only != name:
            continue
        res = fn(args, db)
        if res.get("skipped"):
            continue  # nothing real was measured -> write nothing
        res["run_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        (out_dir / f"{name}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[{name}] wrote {out_dir / (name + '.json')}")
        print(json.dumps(res, indent=1, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
