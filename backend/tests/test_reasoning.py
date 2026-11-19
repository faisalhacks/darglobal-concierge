"""Live regression (Railway b3b8bcc): reasoning models spent every token on hidden reasoning (finish_reason=length,
0 content chars) and gemma's answers were rejected. Mocked transport only; no network, no key."""
import json

import httpx
import pytest

from backend.app import llm as llm_mod
from backend.app.chat import ChatRequest, Engine
from backend.app.llm import LLMError, LLMResult, OpenRouterClient, normalize_finish

from test_router import M, OK_TEXT, _client, _ok, _run, _settings


def _reasoning_only(model, n=40, finish="length"):
    chunks = [json.dumps({"model": model, "choices": [{"delta": {"content": "", "reasoning": "thinking hard. "}}]})
              for _ in range(n)]
    chunks.append(json.dumps({"model": model, "choices": [{"delta": {}, "finish_reason": finish}]}))
    body = "".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


@pytest.mark.anyio
async def test_all_tokens_spent_on_reasoning_hops_to_next_model():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        return _reasoning_only(body["models"][0]) if len(seen) == 1 else _ok(body["models"][0])

    out, rec = await _run(_client(handler))
    assert out == OK_TEXT and rec.calls == 2 and rec.model == M[1]
    # reasoning is never shown; visible content counted separately
    assert "thinking" not in out and rec.reasoning_chars == 0 and rec.content_chars == len(OK_TEXT)
    assert seen[0]["max_tokens"] >= 1200 and seen[0]["reasoning"] == {"effort": "low", "exclude": True}


@pytest.mark.anyio
async def test_reasoning_only_stream_is_abandoned_after_the_abort_window(monkeypatch):
    monkeypatch.setattr(llm_mod, "REASONING_ABORT_S", -1.0)  # any reasoning without content -> abort at once
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        return _reasoning_only(body["models"][0], finish="stop") if len(seen) == 1 else _ok(body["models"][0])

    out, rec = await _run(_client(handler))
    assert out == OK_TEXT and rec.calls == 2


@pytest.mark.anyio
async def test_reasoning_only_on_every_model_raises_bad_response():
    def handler(req):
        return _reasoning_only(json.loads(req.content)["models"][0])

    with pytest.raises(LLMError) as ei:
        await _run(_client(handler))
    assert ei.value.kind == "bad_response"


def test_native_finish_reasons_count_as_complete():
    for v in ("stop", "STOP", "end_turn", "eos", "stop_sequence"):
        assert normalize_finish(v) == "stop"
    assert normalize_finish("length") == "length" and normalize_finish(None) is None


class _CutLLM:
    """Writer that returns real content but finishes with finish_reason=length."""
    model_name = "mock/cut"

    def __init__(self, text):
        self.text = text
        from backend.app.router import Router
        self.router = Router([self.model_name], daily_budget=10 ** 9)

    async def stream(self, messages, rec, max_tokens=1200, allow_retry=True):
        rec.calls += 1
        rec.model = self.model_name
        for w in self.text.split(" "):
            yield w + " "
        rec.finish_reason = "length"

    async def tool_call(self, *a, **k):
        return None


def _engine(llm):
    from backend.app.config import load_settings
    from backend.app.retrieval import Retriever
    from backend.app.store import Store
    s = load_settings()
    st = Store.load(s.data_path)
    return Engine(s, st, Retriever(st, None), llm=llm)


async def _collect(eng, msg):
    evs = [ev async for ev in eng.run(ChatRequest("t", msg, []))]
    text = "".join(d["t"] for e, d in evs if e == "token")
    trace = next(d for e, d in evs if e == "trace")
    return text, trace


@pytest.mark.anyio
async def test_cut_off_answer_with_content_is_kept_trimmed_to_full_sentence():
    long = ("Fixture Marina Tower is a published DarGlobal project in Dubai. Its status is listed on the official "
            "page and the sales team can confirm prices. The tower also")
    text, trace = await _collect(_engine(_CutLLM(long)), "Tell me about Fixture Marina Tower")
    assert not trace["degraded"]
    assert text.rstrip().endswith("confirm prices.") and "The tower also" not in text


@pytest.mark.anyio
async def test_cut_off_short_answer_is_rejected_for_the_code_fallback():
    text, trace = await _collect(_engine(_CutLLM("Fixture Marina Tower is")), "Tell me about Fixture Marina Tower")
    assert trace["degraded"] and "Fixture Marina Tower is " != text


# ---------------- first-token limit (live: gemma sent only keep-alives for 30 s before the hop)
def _keepalive_then_content(model, n_keepalive=5, text=OK_TEXT):
    body = ": OPENROUTER PROCESSING\n\n" * n_keepalive
    body += "".join(f"data: {json.dumps({'model': model, 'choices': [{'delta': {'content': w + ' '}}]})}\n\n"
                    for w in text.split(" "))
    body += f"data: {json.dumps({'model': model, 'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\ndata: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


@pytest.mark.anyio
async def test_first_token_limit_applies_through_keepalive_comments():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body["models"])
        return _keepalive_then_content(body["models"][0])

    # limit 0 s: the first model's keep-alive-only opening exceeds it -> breaker + hop to the next model
    cli = _client(handler, llm_first_token_timeout_s=-1.0)
    with pytest.raises(LLMError) as ei:
        await _run(cli)
    assert ei.value.kind == "timeout" and seen == [[M[0]], [M[1]]]  # one model per request, two requests max
    snap = {x["model"]: x["state"] for x in cli.router.snapshot()}
    assert snap[M[0]] == "cooling" and snap[M[1]] == "cooling"


@pytest.mark.anyio
async def test_keepalives_within_the_limit_still_answer():
    out, rec = await _run(_client(lambda req: _keepalive_then_content(json.loads(req.content)["models"][0])))
    assert out.strip() == OK_TEXT and rec.calls == 1


def test_default_first_token_limit_and_model_order():
    from backend.app.config import load_settings
    s = load_settings()
    assert s.llm_first_token_timeout_s <= 8.0 and s.llm_connect_timeout_s <= 5.0 and s.llm_total_timeout_s <= 30.0
    assert OpenRouterClient.MAX_MODELS_PER_CALL == 1
    from backend.app.config import DEFAULT_MODELS
    assert DEFAULT_MODELS.split(",")[0].startswith("nvidia/nemotron")


@pytest.mark.anyio
async def test_model_pool_refresh_reads_listing_only(monkeypatch):
    import asyncio
    from backend.app import main as main_mod
    calls = []

    class L:
        async def check_models(self):
            calls.append(1)
            if len(calls) >= 2:
                raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await main_mod._refresh_models(L(), 0.0)
    assert len(calls) == 2  # GET /models only: check_models never sends a completion
