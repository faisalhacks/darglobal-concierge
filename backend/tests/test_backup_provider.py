"""NVIDIA backup provider (BACKUP_PROVIDER=nvidia) against mocked transports. No network, no key, zero real LLM calls."""
import json

import httpx

from backend.app.backup_provider import BackupConfig, BackupLLM
from backend.app.llm import OpenRouterClient
from backend.app.main import create_app
from fastapi.testclient import TestClient

from conftest import parse_sse  # noqa: F401
from test_router import M, OK_TEXT, _ok, _settings

NV_MODEL = "nvidia/nemotron-test"
STEP = "Worded by Nemotron via NVIDIA (backup: OpenRouter free quota reached)"


def _nv_ok(req):
    assert req.url.host == "integrate.api.nvidia.com" and req.headers["authorization"] == "Bearer nv-test"
    return _ok(NV_MODEL)


def _app(or_handler, nv_handler, enabled=True, cap=200, **kw):
    s = _settings(**kw)
    calls = {"or": 0, "nv": 0}

    def or_h(req):
        calls["or"] += 1
        return or_handler(req)

    def nv_h(req):
        calls["nv"] += 1
        return nv_handler(req)

    primary = OpenRouterClient(s, transport=httpx.MockTransport(or_h))
    cfg = BackupConfig("nvidia" if enabled else "", "nv-test", NV_MODEL, daily_budget=cap)
    llm = BackupLLM(primary, cfg, transport=httpx.MockTransport(nv_h))
    return TestClient(create_app(s, llm=llm)), llm, calls


QUOTA = lambda req: httpx.Response(402, json={"error": {"code": 402}})  # noqa: E731


def test_quota_then_nvidia_backup_answers(ask):
    c, llm, calls = _app(QUOTA, _nv_ok)
    d = ask(c, "Tell me about Fixture Marina Tower")
    t = d["trace"][0]
    assert t["provider"] == "nvidia-backup" and not t["degraded"] and t["model"] == NV_MODEL
    assert t["llm_calls"] == 2 and calls == {"or": 1, "nv": 1}  # the backup hop counts as a call
    assert STEP in t["steps"] and "Fixture Marina Tower" in d["_text"]
    assert d["cards"][0]["projects"]
    # next message: OpenRouter is in quota state (0 calls), backup answers as the single call
    d2 = ask(c, "Tell me about Fixture Creek Villas")
    assert d2["trace"][0]["provider"] == "nvidia-backup" and d2["trace"][0]["llm_calls"] == 1 and calls["or"] == 1


def test_timeouts_and_all_down_use_backup(ask):
    c, _, calls = _app(lambda req: httpx.Response(503, json={"error": {"code": 503}}), _nv_ok)
    d = ask(c, "Tell me about Fixture Marina Tower")
    assert d["trace"][0]["provider"] == "nvidia-backup" and d["trace"][0]["llm_calls"] == 2


def test_openrouter_success_never_touches_backup(ask):
    c, _, calls = _app(lambda req: _ok(M[0]), _nv_ok)
    d = ask(c, "Tell me about Fixture Marina Tower")
    assert d["trace"][0]["provider"] == "openrouter" and calls["nv"] == 0
    assert STEP not in d["trace"][0]["steps"]


def test_backup_disabled_falls_back_to_code(ask):
    c, _, calls = _app(QUOTA, _nv_ok, enabled=False)
    d = ask(c, "Tell me about Fixture Marina Tower")
    t = d["trace"][0]
    assert calls["nv"] == 0 and t["degraded"] and t["degraded_reason"] == "quota" and t["provider"] is None
    assert "1,800,000 AED" in d["_text"]
    m = c.get("/api/meta").json()["llm"]["backup"]
    assert m["enabled"] is False and m["model"] is None


def test_backup_budget_cap(ask):
    c, llm, calls = _app(QUOTA, _nv_ok, cap=1)
    a = ask(c, "Tell me about Fixture Marina Tower")
    assert a["trace"][0]["provider"] == "nvidia-backup"
    b = ask(c, "Tell me about Fixture Creek Villas")
    assert calls["nv"] == 1 and b["trace"][0]["degraded"] and b["trace"][0]["provider"] is None
    assert c.get("/api/meta").json()["llm"]["backup"]["used"] == 1


def test_backup_failure_falls_back_to_code_and_breaker(ask):
    c, llm, calls = _app(QUOTA, lambda req: httpx.Response(500, json={"error": "x"}))
    d = ask(c, "Tell me about Fixture Marina Tower")
    t = d["trace"][0]
    assert t["degraded"] and t["provider"] is None and "1,800,000 AED" in d["_text"] and calls["nv"] == 1
    ask(c, "Tell me about Fixture Creek Villas")  # second failure opens the backup breaker
    assert calls["nv"] == 2 and not llm.available()
    d3 = ask(c, "Tell me about Fixture Oman Heights")
    assert calls["nv"] == 2 and d3["trace"][0]["degraded"]


def test_meta_block(ask):
    c, _, _ = _app(QUOTA, _nv_ok)
    b = c.get("/api/meta").json()["llm"]["backup"]
    assert b == {"enabled": True, "provider": "nvidia", "model": NV_MODEL, "used": 0, "cap": 200}
    assert "nv-test" not in json.dumps(c.get("/api/meta").json())


def test_config_from_env(monkeypatch):
    monkeypatch.delenv("BACKUP_PROVIDER", raising=False)
    assert not BackupConfig.from_env().enabled
    monkeypatch.setenv("BACKUP_PROVIDER", "nvidia")
    assert not BackupConfig.from_env().enabled  # no key
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("BACKUP_DAILY_BUDGET", "7")
    cfg = BackupConfig.from_env()
    assert cfg.enabled and cfg.daily_budget == 7 and cfg.base_url == "https://integrate.api.nvidia.com/v1"


# ---------------------------------------------------------------- Lane A: non-streaming backup, meta, cache header
def _nv_json(req):
    body = json.loads(req.content)
    assert body["stream"] is False and body["chat_template_kwargs"] == {"enable_thinking": False}
    if body.get("tools"):
        msg = {"tool_calls": [{"function": {"name": "search_knowledge", "arguments": "{\"query\": \"x\"}"}}]}
    else:
        msg = {"content": "{\"intent\": \"search\"}"}
    return httpx.Response(200, json={"model": NV_MODEL, "choices": [{"message": msg}]})


def test_complete_json_and_tool_call_fall_back_to_nvidia():
    import asyncio
    from backend.app.llm import LLMResult
    c, llm, calls = _app(QUOTA, _nv_json)
    rec = LLMResult()
    out = asyncio.run(llm.complete_json([{"role": "user", "content": "q"}], rec))
    assert out == '{"intent": "search"}' and rec.provider == "nvidia-backup" and calls["nv"] == 1 and rec.calls == 2
    tc = asyncio.run(llm.tool_call([{"role": "user", "content": "q"}], [{"type": "function"}], LLMResult()))
    assert tc == {"name": "search_knowledge", "arguments": {"query": "x"}} and calls["nv"] == 2
    assert llm.meta()["used"] == 2


def test_json_backup_respects_budget_and_failure():
    import asyncio
    from backend.app.llm import LLMResult
    c, llm, calls = _app(QUOTA, lambda r: httpx.Response(429, json={}), cap=1)
    assert asyncio.run(llm.complete_json([{"role": "user", "content": "q"}], LLMResult())) is None
    assert asyncio.run(llm.complete_json([{"role": "user", "content": "q"}], LLMResult())) is None
    assert calls["nv"] == 1  # second call blocked by the budget


def test_meta_llm_available_with_backup_and_build_and_cache_header():
    c, llm, _ = _app(QUOTA, _nv_ok)
    m = c.get("/api/meta").json()
    assert m["llm_available"] is True and m["llm"]["backup"]["enabled"] and len(m["build"]) >= 3
    r = c.get("/")
    if r.headers.get("content-type", "").startswith("text/html") and "Frontend not built" not in r.text:
        assert r.headers["cache-control"] == "no-cache, must-revalidate"


def test_llm_available_when_only_backup_configured(monkeypatch):
    s = _settings(openrouter_api_key=None)
    monkeypatch.delenv("BACKUP_PROVIDER", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert s.llm_available is False
    monkeypatch.setenv("BACKUP_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    assert s.llm_available is True
