"""Bake answers for the reviewer questions and starter chips into data/answer_cache.json (contract C3).

The deployed app loads the file read-only at boot; a baked answer is replayed with trace.cache_hit=true and the
model that wrote it, so the questions most reviewers click cost 0 of the 50 free requests per day.
Only answers that went through the LLM and were NOT degraded are baked; code-path questions (search, compare,
calculation, templates) need no LLM and are skipped. The file is keyed by normalised query + lang + dataset_version,
so it is ignored as a whole after the dataset changes: re-run it after every dataset build.

Usage (repo root):
  python -m backend.scripts.warm_cache --max-calls 12            # live, real free-model calls (budgeted)
  python -m backend.scripts.warm_cache --mock --out /tmp/x.json  # no network, for testing the pipeline
The OpenRouter key is read from the environment or the repo-root .env, in-process; it is never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys

from . import ROOT, load_dotenv

# Reviewer questions that reach the model (R1/R6 are code paths today and are skipped automatically).
REVIEWER = [
    ("R1", "What projects do you have in Oman?"),
    ("R2", "How do Wasalt auctions work?"),
    ("R6", "ما هي المشاريع التي لديكم في سلطنة عمان؟"),
    ("R2-ar", "كيف تعمل مزادات وصلت؟"),
]


async def _ask(engine, text: str):
    from backend.app.chat import ChatRequest
    events = []
    async for ev, data in engine.run(ChatRequest(session_id="warm", message=text, history=[], lang="auto")):
        events.append((ev, data))
    return events


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("ANSWER_CACHE_PATH") or os.path.join(ROOT, "data", "answer_cache.json"))
    ap.add_argument("--data", default=os.environ.get("DATA_PATH") or os.path.join(ROOT, "data", "concierge.sqlite"))
    ap.add_argument("--index", default=os.environ.get("INDEX_DIR") or os.path.join(ROOT, "data", "index"))
    ap.add_argument("--max-calls", type=int, default=12, help="hard cap on outbound LLM requests for this run")
    ap.add_argument("--mock", action="store_true", help="use the deterministic mock writer (no network)")
    ap.add_argument("--only", default="", help="comma list of extra questions to bake instead of the defaults")
    a = ap.parse_args(argv)

    os.environ["DATA_PATH"], os.environ["INDEX_DIR"] = a.data, a.index
    os.environ["ANSWER_CACHE_PATH"] = ""  # never replay an old baked file while baking
    os.environ["LLM_TOOL_ROUTING"] = "false"
    if a.mock:
        os.environ["LLM_MODE"] = "mock"
    else:
        os.environ["LLM_MODE"] = "live"
        if not load_dotenv():
            print("OPENROUTER_API_KEY is not set (env or .env); nothing baked.", file=sys.stderr)
            return 2
    from backend.app.config import load_settings
    from backend.app.main import create_app, starter_chips
    from backend.app.router import Router

    s = load_settings()
    s.llm_daily_budget = max(0, a.max_calls)  # the router refuses every call past this
    app = create_app(s)
    engine, store = app.state.engine, app.state.store
    if engine.llm is None:
        print("no LLM configured; nothing baked.", file=sys.stderr)
        return 2
    if not a.mock:
        engine.llm.router = Router(s.openrouter_models, a.max_calls, s.llm_quota_cooldown_s)

    if a.only:
        questions = [(f"Q{i}", q.strip()) for i, q in enumerate(a.only.split("|")) if q.strip()]
    else:
        chips = starter_chips(store)
        questions = REVIEWER + [(f"chip-{lg}-{i}", q) for lg in ("en", "ar") for i, q in enumerate(chips[lg][:-1])]

    existing = {}
    if os.path.exists(a.out):
        try:
            with open(a.out, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("dataset_version") == store.version:
                existing = old.get("entries") or {}
        except (OSError, ValueError):
            existing = {}

    from backend.app.arabic import detect_lang
    from backend.app.chat import baked_key
    baked, skipped = 0, 0
    for qid, q in questions:
        lang = detect_lang(engine._strip_names(q), "auto")
        key = baked_key(q, lang, store.version)
        if key in existing:
            print(f"{qid}: already baked")
            continue
        router = getattr(engine.llm, "router", None)
        if router is not None and router.block_reason() == "quota":
            print(f"{qid}: call budget for this run is spent; stopping")
            break
        events = asyncio.run(_ask(engine, q))
        trace = next((d for e, d in events if e == "trace"), {})
        if not trace.get("llm_calls") or trace.get("degraded") or not trace.get("model"):
            skipped += 1
            print(f"{qid}: not baked (llm_calls={trace.get('llm_calls')}, degraded={trace.get('degraded_reason')})")
            continue
        existing[key] = {"q": q, "lang": lang, "model": trace["model"], "baked_at": dt.datetime.now(dt.timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "events": [[e, d] for e, d in events if e in ("token", "cards", "compare", "calc", "sources",
                                                                        "chips")],
                         "trace": {k: trace.get(k) for k in ("intent", "path", "tool", "retrieved")}}
        baked += 1
        print(f"{qid}: baked (model={trace['model']}, calls={trace['llm_calls']})")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"dataset_version": store.version, "entries": existing}, f, ensure_ascii=False, indent=1)
    used = getattr(getattr(engine.llm, "router", None), "used", None)
    print(f"baked {baked}, skipped {skipped}, total entries {len(existing)}, outbound LLM requests this run: {used}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
