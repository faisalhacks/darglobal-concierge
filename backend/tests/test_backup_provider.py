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
