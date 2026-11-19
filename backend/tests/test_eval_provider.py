"""EVAL-ONLY NVIDIA answer provider: off by default, never configured in the image or deploy files, and reported
honestly in /api/meta when it is on. No network, no key."""
import json
import os
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import EVAL_NVIDIA_BASE_URL, EVAL_NVIDIA_MODEL, load_settings
from backend.app.llm import LLMResult, OpenRouterClient
from backend.app.main import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _env(monkeypatch, **kw):
    for k in ("EVAL_LLM_PROVIDER", "EVAL_LLM_MODEL", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_MODELS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_MODE", "auto")
    for k, v in kw.items():
        monkeypatch.setenv(k, v)


def test_default_is_off_and_openrouter(monkeypatch):
    _env(monkeypatch, OPENROUTER_API_KEY="or-key", NVIDIA_API_KEY="nv-key")
    s = load_settings()
    assert s.eval_llm_provider == "" and s.llm_provider == "openrouter"
    assert s.openrouter_base_url.startswith("https://openrouter.ai") and s.openrouter_api_key == "or-key"
    assert EVAL_NVIDIA_MODEL not in s.openrouter_models or s.openrouter_models[0].endswith(":free")


def test_unknown_provider_value_stays_off(monkeypatch):
    _env(monkeypatch, EVAL_LLM_PROVIDER="somethingelse", OPENROUTER_API_KEY="or-key")
    assert load_settings().llm_provider == "openrouter"


def test_image_and_deploy_configs_never_set_the_override():
    paths = [os.path.join(ROOT, "Dockerfile")]
    for base, _d, files in os.walk(os.path.join(ROOT, "deploy")):
        paths += [os.path.join(base, f) for f in files]
    seen = 0
    for p in paths:
        txt = open(p, encoding="utf-8", errors="replace").read()
        seen += 1
        assert "EVAL_LLM_PROVIDER" not in txt and "NVIDIA_API_KEY" not in txt, p
    assert seen >= 2


def test_override_on_uses_nvidia_endpoint_key_and_model(monkeypatch):
    _env(monkeypatch, EVAL_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nv-key", OPENROUTER_API_KEY="or-key")
    s = load_settings()
    assert s.llm_provider == "nvidia" and s.openrouter_base_url == EVAL_NVIDIA_BASE_URL
    assert s.openrouter_api_key == "nv-key" and s.openrouter_models == [EVAL_NVIDIA_MODEL]
    assert EVAL_NVIDIA_MODEL == "nvidia/nemotron-3-ultra-550b-a55b"


@pytest.mark.anyio
async def test_override_request_is_plain_openai_shape(monkeypatch):
    _env(monkeypatch, EVAL_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nv-key")
    s = load_settings()
    s.llm_mode = "auto"
    seen = {}

    def handler(req):
        seen["url"], seen["headers"], seen["body"] = str(req.url), dict(req.headers), json.loads(req.content)
        chunk = json.dumps({"model": EVAL_NVIDIA_MODEL, "choices": [{"delta": {"content": "Hello."}, "finish_reason": "stop"}]})
        return httpx.Response(200, content=f"data: {chunk}\n\ndata: [DONE]\n\n".encode(),
                              headers={"content-type": "text/event-stream"})

    cli = OpenRouterClient(s, transport=httpx.MockTransport(handler))
    rec = LLMResult()
    out = "".join([t async for t in cli.stream([{"role": "user", "content": "hi"}], rec)])
    assert out == "Hello." and rec.model == EVAL_NVIDIA_MODEL
    assert seen["url"] == EVAL_NVIDIA_BASE_URL + "/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer nv-key" and "x-openrouter-cache" not in seen["headers"]
    b = seen["body"]
    assert b["model"] == EVAL_NVIDIA_MODEL and "models" not in b and "reasoning" not in b and "provider" not in b
    assert b["chat_template_kwargs"] == {"enable_thinking": False}


def test_meta_reports_actual_provider_and_model_when_on(monkeypatch):
    _env(monkeypatch, EVAL_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nv-key")
    s = load_settings()
    s.llm_boot_model_check = False
    c = TestClient(create_app(s))
    llm = c.get("/api/meta").json()["llm"]
    assert llm["mode"] == "live" and llm["provider"] == "nvidia" and llm["model"] == EVAL_NVIDIA_MODEL


def test_meta_has_no_provider_override_by_default(monkeypatch):
    _env(monkeypatch, OPENROUTER_API_KEY="or-key")
    s = load_settings()
    s.llm_boot_model_check = False
    llm = TestClient(create_app(s)).get("/api/meta").json()["llm"]
    assert "provider" not in llm
