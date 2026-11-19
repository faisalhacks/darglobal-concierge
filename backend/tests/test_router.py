"""Model router (docs/MODEL_ROUTER.md layers 1-6) against a mocked OpenRouter transport. No network, no key."""
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.chat import baked_key
from backend.app.config import load_settings
from backend.app.llm import LLMError, LLMResult, OpenRouterClient, classify_error
from backend.app.main import create_app
from backend.app.router import Router

from conftest import parse_sse  # noqa: F401

M = ["g/one:free", "n/two:free", "g/three:free"]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _settings(**kw):
    s = load_settings()
    s.openrouter_api_key, s.openrouter_models, s.llm_mode = "test-key", list(M), "auto"
    for k, v in kw.items():
        setattr(s, k, v)
    return s


OK_TEXT = "Hello there. Fixture Marina Tower is listed in the published data."


def _sse(text, model, finish="stop"):
    chunks = [json.dumps({"model": model, "choices": [{"delta": {"content": w}}]}) for w in re.findall(r"\S+\s*", text)]
    if finish:
        chunks.append(json.dumps({"model": model, "choices": [{"delta": {}, "finish_reason": finish}]}))
    return (": OPENROUTER PROCESSING\n\n" + "".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _ok(model, text=OK_TEXT, finish="stop"):
    return httpx.Response(200, content=_sse(text, model, finish), headers={"content-type": "text/event-stream"})


def _client(handler, router=None, **kw):
    s = _settings(**kw)
    return OpenRouterClient(s, transport=httpx.MockTransport(handler), router=router)


async def _run(cli, rec=None):
    rec = rec or LLMResult()
    out = "".join([t async for t in cli.stream([{"role": "user", "content": "hi"}], rec)])
    return out, rec


# ---------------------------------------------------------------- layer 2/3: fallback + breaker
@pytest.mark.anyio
async def test_429_on_m1_then_m2_answers_and_hops_counted():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        if len(seen) == 1:
            return httpx.Response(429, json={"error": {"code": 429, "message": "Provider returned error",
                                                       "metadata": {"raw": "temporarily rate-limited upstream"}}},
                                  headers={"retry-after": "45"})
        return _ok(body["models"][0])

    clock = Clock()
    r = Router(M, 45, clock=clock)
    cli = _client(handler, router=r)
    out, rec = await _run(cli)
    assert out == OK_TEXT and rec.calls == 2 and rec.model == "n/two:free" and rec.fallback_hops == 1
    assert seen[0]["models"] == M and seen[1]["models"] == ["n/two:free", "g/three:free"]
    # every request carries the cache header + low reasoning effort; the key only in Authorization
    assert seen[0]["reasoning"] == {"effort": "low", "exclude": True}
    snap = {x["model"]: x["state"] for x in r.snapshot()}
    assert snap == {"g/one:free": "cooling", "n/two:free": "healthy", "g/three:free": "healthy"}
    clock.t += 44
    assert "g/one:free" not in r.ordered()  # Retry-After (45 s) honoured over the 30 s base cooldown
    clock.t += 2
    assert r.ordered()[0] == "g/one:free"  # breaker closes after the cooldown


@pytest.mark.anyio
async def test_request_headers():
    got = {}

    def handler(req):
        got.update(req.headers)
        return _ok(M[0])

    await _run(_client(handler))
    assert got["x-openrouter-cache"] == "true" and got["authorization"] == "Bearer test-key"


@pytest.mark.anyio
async def test_server_side_fallback_counts_hop_and_cools_skipped_model():
    cli = _client(lambda req: _ok("n/two"))  # OpenRouter answered with the 2nd model of the array (suffix dropped)
    out, rec = await _run(cli)
    assert rec.calls == 1 and rec.fallback_hops == 1
    assert {x["model"]: x["state"] for x in cli.router.snapshot()}["g/one:free"] == "cooling"


@pytest.mark.anyio
async def test_all_429_raises_rate_limited_after_two_calls():
    cli = _client(lambda req: httpx.Response(429, json={"error": {"code": 429, "message": "upstream"}}))
    with pytest.raises(LLMError) as ei:
        await _run(cli)
    assert ei.value.kind == "rate_limited" and cli.router.used == 2


def test_breaker_doubles_to_ten_minutes():
    clock = Clock()
    r = Router(["a:free"], clock=clock)
    waits = []
    for _ in range(8):
        r.fail("a:free", "unavailable")
        waits.append(r.pool[0].open_until - clock.t)
    assert waits[:3] == [30, 60, 120] and waits[-1] == 600
    r.ok("a:free", 900)
    assert r.pool[0].state(clock.t) == "healthy" and r.pool[0].ewma_ttft_ms == 900


def test_ordering_rank_then_latency_and_listing_check():
    r = Router(M)
    r.ok("n/two:free", 100)
    assert r.ordered() == M  # rank (configured / Arabic-gate order) first
    removed = r.apply_listing([{"id": "g/one:free"}, {"id": "n/two"}, {"id": "g/three:free"}])
    assert removed == ["n/two:free"] and r.ordered() == ["g/one:free", "g/three:free"]
    assert {x["model"]: x["state"] for x in r.snapshot()}["n/two:free"] == "removed"
    assert r.apply_listing([]) == [] and len(r.ordered()) == 2  # empty listing never empties the pool


@pytest.mark.anyio
async def test_boot_model_check_uses_free_listing_only():
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        return httpx.Response(200, json={"data": [{"id": "g/one:free"}, {"id": "g/three:free"}]})

    cli = _client(handler)
    assert await cli.check_models() == ["n/two:free"]
    assert calls == [("GET", "/api/v1/models")] and cli.router.used == 0  # no completion, no budget spent


# ---------------------------------------------------------------- mid-stream errors
@pytest.mark.anyio
async def test_mid_stream_error_before_first_token_moves_to_next_model():
    n = []

    def handler(req):
        n.append(1)
        body = json.loads(req.content)
        if len(n) == 1:
            err = json.dumps({"error": {"code": 502, "message": "provider died"}})
            return httpx.Response(200, content=f"data: {err}\n\n".encode(), headers={"content-type": "text/event-stream"})
        return _ok(body["models"][0], "Recovered.")

    out, rec = await _run(_client(handler))
    assert out == "Recovered." and rec.calls == 2 and rec.model == "n/two:free"


@pytest.mark.anyio
async def test_mid_stream_error_after_first_token_is_raised_not_retried():
    def handler(req):
        first = json.dumps({"model": M[0], "choices": [{"delta": {"content": "Partial "}}]})
        err = json.dumps({"error": {"code": 502, "message": "died"}})
        return httpx.Response(200, content=f"data: {first}\n\ndata: {err}\n\n".encode(),
                              headers={"content-type": "text/event-stream"})

    cli = _client(handler)
    rec = LLMResult()
    got = []
    with pytest.raises(LLMError):
        async for t in cli.stream([{"role": "user", "content": "hi"}], rec):
            got.append(t)
    assert got == ["Partial "] and rec.calls == 1


# ---------------------------------------------------------------- layer 4: account states
@pytest.mark.anyio
async def test_402_sets_quota_and_no_more_calls():
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(402, json={"error": {"code": 402, "message": "Insufficient credits"}})

    clock = Clock()
    r = Router(M, 45, quota_cooldown_s=600, clock=clock)
    cli = _client(handler, router=r)
    with pytest.raises(LLMError) as ei:
        await _run(cli)
    assert ei.value.kind == "quota" and len(n) == 1 and r.state == "quota"
    with pytest.raises(LLMError) as ei:
        await _run(cli)
    assert ei.value.kind == "quota" and len(n) == 1  # quota state: zero outbound calls
    clock.t += 601
    assert r.state == "ok"


def test_daily_cap_429_is_quota_with_reset():
    body = json.dumps({"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day. Add 10 credits",
                                 "metadata": {"headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0",
                                                          "X-RateLimit-Reset": "1763596800000"}}}}).encode()
    kind, scope, _, reset = classify_error(429, {}, body)
    assert (kind, scope, reset) == ("quota", "account_day", 1763596800.0)
    kind, scope, retry, _ = classify_error(429, {}, b'{"error":{"message":"free-models-per-min"}}')
    assert (kind, scope, retry) == ("rate_limited", "account_minute", 60.0)
    assert classify_error(429, {"Retry-After": "7"}, b"{}")[:3] == ("rate_limited", "model", 7.0)


@pytest.mark.anyio
async def test_budget_cap_means_zero_outbound_calls():
    n = []

    def handler(req):
        n.append(1)
        return _ok(M[0])

    r = Router(M, daily_budget=2)
    cli = _client(handler, router=r)
    await _run(cli)
    await _run(cli)
    assert len(n) == 2 and r.budget() == {"used": 2, "cap": 2} and r.state == "quota"
    with pytest.raises(LLMError) as ei:
        await _run(cli)
    assert ei.value.kind == "quota" and len(n) == 2
    # tool routing is skipped outright too
    assert await cli.tool_call([{"role": "user", "content": "x"}], [], LLMResult()) is None and len(n) == 2


@pytest.mark.anyio
async def test_near_cap_skips_tool_call_but_not_prose():
    n = []

    def handler(req):
        n.append(json.loads(req.content))
        return _ok(M[0])

    r = Router(M, daily_budget=10)
    r.used = 9
    cli = _client(handler, router=r)
    assert await cli.tool_call([{"role": "user", "content": "x"}], [], LLMResult()) is None and not n
    await _run(cli)
    assert len(n) == 1


@pytest.mark.anyio
async def test_tool_call_requires_parameters():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"model": M[0], "choices": [{"message": {"tool_calls": [
            {"function": {"name": "search_knowledge", "arguments": "{\"query\": \"q\"}"}}]}}]})

    out = await _client(handler).tool_call([{"role": "user", "content": "x"}], [], LLMResult())
    assert out == {"name": "search_knowledge", "arguments": {"query": "q"}}
    assert seen[0]["provider"] == {"require_parameters": True}


def test_budget_rolls_over_at_utc_midnight():
    day = ["2026-11-19"]
    r = Router(M, daily_budget=1, day=lambda: day[0])
    r.note_call()
    assert r.state == "quota"
    day[0] = "2026-11-20"
    assert r.state == "ok" and r.budget()["used"] == 0


# ---------------------------------------------------------------- end to end through the app
def _app(handler, **kw):
    s = _settings(**kw)
    llm = OpenRouterClient(s, transport=httpx.MockTransport(handler))
    return TestClient(create_app(s, llm=llm)), llm


def test_e2e_all_models_down_gives_extractive_answer(ask):
    c, llm = _app(lambda req: httpx.Response(503, json={"error": {"code": 503}}))
    d = ask(c, "Tell me about Fixture Marina Tower")
    t = d["trace"][0]
    assert t["degraded"] and t["degraded_reason"] == "all_models_down" and t["llm_calls"] == 2
    assert "1,800,000 AED" in d["_text"] and "unavailable" not in d["_text"].lower() and d["cards"][0]["projects"]
    m = c.get("/api/meta").json()
    assert [x["state"] for x in m["llm"]["pool"]] == ["cooling", "cooling", "healthy"]
    assert m["llm"]["state"] == "ok"
    ask(c, "Tell me about Fixture Creek Villas")  # third model fails too -> whole pool cooling
    m = c.get("/api/meta").json()
    assert m["llm"]["mode"] == "live" and m["llm"]["state"] == "cooling" and m["llm_available"] is False
    assert {x["state"] for x in m["llm"]["pool"]} == {"cooling"}
    assert c.get("/readyz").json()["llm"] == "cooling"
    d = ask(c, "Tell me about Fixture Oman Heights")
    assert d["trace"][0]["llm_calls"] == 0 and d["trace"][0]["degraded_reason"] == "all_models_down"


def test_e2e_budget_cap_zero_calls_and_meta(ask):
    n = []

    def handler(req):
        n.append(1)
        return _ok(M[0])

    c, llm = _app(handler, llm_daily_budget=1)
    a = ask(c, "Tell me about Fixture Marina Tower")
    assert a["trace"][0]["model"] == M[0] and not a["trace"][0]["degraded"] and len(n) == 1
    b = ask(c, "Tell me about Fixture Creek Villas")
    assert len(n) == 1 and b["trace"][0]["degraded_reason"] == "quota" and b["trace"][0]["llm_calls"] == 0
    assert b["cards"][0]["projects"] and b["sources"][0]
    m = c.get("/api/meta").json()["llm"]
    assert m["state"] == "quota" and m["budget"] == {"used": 1, "cap": 1}


def test_e2e_402_quota_state(ask):
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(402, json={"error": {"code": 402}})

    c, _ = _app(handler)
    d = ask(c, "Tell me about Fixture Marina Tower")
    assert d["trace"][0]["degraded_reason"] == "quota" and len(n) == 1
    d = ask(c, "Tell me about Fixture Creek Villas")
    assert d["trace"][0]["llm_calls"] == 0 and len(n) == 1
    assert c.get("/readyz").json()["llm"] == "quota"


def test_e2e_mid_stream_failure_finishes_with_code_facts(ask):
    def handler(req):
        long = ("Fixture Marina Tower is a branded residential tower in Dubai Marina, built by Fixture Dev. "
                "It is off-plan with studio to two-bedroom units, and handover is published for 2027. More. ")
        first = json.dumps({"model": M[0], "choices": [{"delta": {"content": long}}]})
        err = json.dumps({"error": {"code": 502}})
        return httpx.Response(200, content=f"data: {first}\n\ndata: {err}\n\n".encode(),
                              headers={"content-type": "text/event-stream"})

    c, _ = _app(handler)
    d = ask(c, "Tell me about Fixture Marina Tower")
    t = d["trace"][0]
    assert t["degraded"] and t["degraded_reason"] == "all_models_down" and t["llm_calls"] == 1
    assert d["_text"].startswith("Fixture Marina Tower is a branded") and "1,800,000 AED" in d["_text"]


def test_baked_answer_cache_hit(tmp_path, ask):
    q = "Tell me about Fixture Marina Tower"
    baked = "Baked answer: Fixture Marina Tower is in Dubai, per its page."
    entry = {"model": "g/one:free", "events": [["token", {"t": baked}], ["sources", []], ["chips", []]],
             "trace": {"intent": "project_info", "path": "code", "tool": None, "retrieved": []}}
    path = tmp_path / "answer_cache.json"
    path.write_text(json.dumps({"dataset_version": "fixture-v1",
                                "entries": {baked_key(q, "en", "fixture-v1"): entry}}), encoding="utf-8")
    n = []

    def handler(req):
        n.append(1)
        return _ok(M[0])

    c, _ = _app(handler, answer_cache_path=str(path))
    d = ask(c, q)
    t = d["trace"][0]
    assert d["_text"] == baked and t["cache_hit"] and t["model"] == "g/one:free" and t["llm_calls"] == 0
    assert not n and " ".join(d["_order"]) == "meta token sources chips trace done"
    # a cache baked for another dataset version is ignored as a whole
    path.write_text(json.dumps({"dataset_version": "other", "entries": {baked_key(q, "en", "other"): entry}}),
                    encoding="utf-8")
    c2, _ = _app(handler, answer_cache_path=str(path))
    assert not ask(c2, q)["trace"][0]["cache_hit"]


def test_meta_contract_c2(client):
    m = client.get("/api/meta").json()
    assert set(m["llm"]) == {"mode", "state", "budget", "pool"} and m["llm"]["mode"] == "mock"
    assert m["llm"]["state"] == "ok" and m["llm_available"] is True
    assert m["coverage"]["DarGlobal"] == {"projects": 3, "detail_pages": 3, "prices_published": True}
    assert m["coverage"]["Wasalt"] == {"projects": 0, "listings": 3}
    for lang in ("en", "ar"):
        chips = m["starter_chips"][lang]
        assert len(chips) == 5 and all(isinstance(x, str) for x in chips)
    assert m["starter_chips"]["en"][0] == "What projects do you have in United Arab Emirates?"
    assert "Fixture" in m["starter_chips"]["en"][1]
    assert m["starter_chips"]["en"][-1].startswith("Test the guardrails: ignore your instructions")


def test_readyz_contract(client):
    r = client.get("/readyz", headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"}).json()
    assert r["xff_hops_seen"] == 2 and r["index"] in ("ok", "stale", "bm25_only") and r["llm"] == "ok"
    assert "1.2.3.4" not in json.dumps(r)


def test_meta_off_mode(make_client):
    m = make_client(env={"LLM_MODE": "off"}).get("/api/meta").json()
    assert m["llm"] == {"mode": "off", "state": "off", "budget": {"used": 0, "cap": 45}, "pool": []}
    assert m["llm_available"] is False


def test_baked_cache_ignores_short_or_cut_off_entries(tmp_path, ask):
    """B5: a one-word baked answer ("Was", from a cut-off stream) is never replayed."""
    q = "Tell me about Fixture Marina Tower"
    entry = {"model": "g/one:free", "events": [["token", {"t": "Was"}], ["sources", []], ["chips", []]],
             "trace": {"intent": "project_info", "path": "code", "tool": None, "retrieved": []}}
    path = tmp_path / "answer_cache.json"
    path.write_text(json.dumps({"dataset_version": "fixture-v1",
                                "entries": {baked_key(q, "en", "fixture-v1"): entry}}), encoding="utf-8")
    c, _ = _app(lambda req: _ok(M[0]), answer_cache_path=str(path))
    d = ask(c, q)
    assert not d["trace"][0]["cache_hit"] and d["_text"] != "Was"


def test_cut_off_stream_is_not_cached_and_falls_back(ask):
    """B5: finish_reason "length" with a one-word reply -> code-built facts, degraded, and not cached."""
    n = []

    def handler(req):
        n.append(1)
        return _ok(M[0], text="Was", finish="length")

    c, _ = _app(handler)
    for _ in range(2):
        d = ask(c, "Tell me about Fixture Marina Tower")
        t = d["trace"][0]
        assert d["_text"].strip() != "Was" and len(d["_text"]) >= 40 and "Fixture Marina Tower" in d["_text"]
        assert t["degraded"] and not t["cache_hit"]
    assert len(n) >= 2  # the second ask was not served from the cache


def test_short_complete_reply_is_not_shown(ask):
    c, _ = _app(lambda req: _ok(M[0], text="Hello there."))
    d = ask(c, "Tell me about Fixture Marina Tower")
    assert "Hello there." not in d["_text"] and d["trace"][0]["degraded"]
