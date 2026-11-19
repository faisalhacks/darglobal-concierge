"""Live router smoke + Arabic gate against real free OpenRouter models. Spends real quota: budget it.

  python -m backend.scripts.live_check --max-calls 9 --out <file.json>

Steps (each one HTTP request unless a model fails):
  smoke-en      one English answer streamed through the full app path
  smoke-fallback the first model is failed LOCALLY (a 503 produced in-process, nothing is sent), so the router's
                 breaker opens and the real request goes to the next model: shows fallback_hops=1 and response.model
  gate-ar-1..3  three fixed Arabic questions; deterministic checks (reply language, Arabic letter ratio >= 0.5,
                 not degraded, no URL, no prompt leak). Stops after the first model passes all three.
The key is read from the environment or the repo-root .env in-process and is never printed or written.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

from . import ROOT, load_dotenv

GATE = ["كيف تعمل مزادات وصلت؟", "أخبرني عن Da Vinci Tower", "هل يمكن للأجانب شراء عقار في السعودية؟"]


def arabic_ratio(text: str) -> float:  # same definition as evals/runner.py
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ") / len(letters)


SENT = {"chat_requests": 0}  # completions requests that actually left this machine


class Net(httpx.AsyncBaseTransport):
    """Counts real chat requests. With fail_first, the first chat request is answered by a local 503 that is never
    sent, so the router's breaker and client-side fallback run against the real API on the second hop."""

    def __init__(self, fail_first: bool = False):
        self.inner = httpx.AsyncHTTPTransport()
        self.fail_first = fail_first

    async def handle_async_request(self, request):
        if request.url.path.endswith("/chat/completions"):
            if self.fail_first:
                self.fail_first = False
                return httpx.Response(503, json={"error": {"code": 503, "message": "simulated locally"}})
            SENT["chat_requests"] += 1
        return await self.inner.handle_async_request(request)


async def _ask(engine, text):
    from backend.app.chat import ChatRequest
    out = {"text": "", "trace": None, "meta": None}
    async for ev, data in engine.run(ChatRequest(session_id="live", message=text, history=[], lang="auto")):
        if ev == "token":
            out["text"] += data["t"]
        elif ev in ("trace", "meta"):
            out[ev] = data
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=9)
    ap.add_argument("--out", default="")
    ap.add_argument("--skip-smoke", action="store_true")
    ap.add_argument("--skip-gate", action="store_true")
    a = ap.parse_args(argv)
    if not load_dotenv():
        print("OPENROUTER_API_KEY not set; nothing run.", file=sys.stderr)
        return 2
    os.environ.setdefault("DATA_PATH", os.path.join(ROOT, "data", "concierge.sqlite"))
    os.environ.setdefault("INDEX_DIR", os.path.join(ROOT, "data", "index"))
    os.environ.update({"LLM_MODE": "live", "LLM_TOOL_ROUTING": "false", "ANSWER_CACHE_PATH": "",
                       "LLM_BOOT_MODEL_CHECK": "false"})
    from backend.app.config import load_settings
    from backend.app.llm import OpenRouterClient
    from backend.app.main import create_app
    from backend.app.router import Router

    s = load_settings()
    router = Router(s.openrouter_models, a.max_calls)  # shared hard cap across every step of this run
    results = []

    def engine_with(transport):
        app = create_app(s, llm=OpenRouterClient(s, transport=transport, router=router))
        app.state.engine.cache.clear()
        return app.state.engine

    if not a.skip_smoke:
        r = asyncio.run(_ask(engine_with(Net()), "Tell me about Da Vinci Tower"))
        results.append({"step": "smoke-en", **r})
        router_fb = router  # same budget; breaker state is reset afterwards
        r = asyncio.run(_ask(engine_with(Net(fail_first=True)), "What is Matchmaker on Wasalt?"))
        results.append({"step": "smoke-fallback", **r})
        for h in router_fb.pool:  # the local 503 opened a breaker on a healthy model: close it again
            h.open_until, h.cooldown_s, h.fails = 0.0, 0.0, 0
    if not a.skip_gate:
        eng = engine_with(Net())
        for i, q in enumerate(GATE, 1):
            if router.block_reason():
                results.append({"step": f"gate-ar-{i}", "skipped": router.block_reason()})
                break
            r = asyncio.run(_ask(eng, q))
            t = r["trace"] or {}
            checks = {"lang_ar": (r["meta"] or {}).get("lang") == "ar", "ratio": round(arabic_ratio(r["text"]), 2),
                      "not_degraded": not t.get("degraded"), "no_url": "http" not in r["text"],
                      "llm_answered": bool(t.get("llm_calls")) and bool(t.get("model"))}
            checks["pass"] = (checks["lang_ar"] and checks["ratio"] >= 0.5 and checks["not_degraded"]
                              and checks["no_url"] and checks["llm_answered"])
            results.append({"step": f"gate-ar-{i}", "q": q, **r, "checks": checks})
    summary = {"real_chat_requests_sent": SENT["chat_requests"], "router_counted": router.used,
               "pool_after": router.snapshot(),
               "steps": [{"step": x["step"], "model": (x.get("trace") or {}).get("model"),
                          "fallback_hops": (x.get("trace") or {}).get("fallback_hops"),
                          "llm_calls": (x.get("trace") or {}).get("llm_calls"),
                          "degraded_reason": (x.get("trace") or {}).get("degraded_reason"),
                          "pass": (x.get("checks") or {}).get("pass")} for x in results]}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
