"""OpenRouter client (streaming, `models` fallback array, router-aware) + deterministic mock for tests.

Timeouts: connect 5 s, first token 12 s, total 30 s. 429 / 5xx / timeout / mid-stream error before the first
token -> breaker on that model + one retry on the remaining healthy models -> caller builds the extractive answer.
402 / daily cap -> quota state, no further calls. Never more than 2 calls per message. See docs/MODEL_ROUTER.md.
The API key is only ever placed in the Authorization header; it is never logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

import httpx

from .config import Settings
from .router import Router, same_model

log = logging.getLogger("concierge.llm")


class LLMError(Exception):
    def __init__(self, kind: str, status: int | None = None, retry_after_s: float | None = None):
        super().__init__(kind)
        # rate_limited | quota | timeout | unavailable | bad_response | all_models_down
        self.kind = kind
        self.status = status
        self.retry_after_s = retry_after_s


# LLMError.kind -> trace.degraded_reason (SSE contract C2)
DEGRADED_REASON = {"rate_limited": "rate_limited", "quota": "quota", "timeout": "timeout",
                   "unavailable": "all_models_down", "bad_response": "all_models_down",
                   "all_models_down": "all_models_down"}


class LLMResult:
    """Mutable record of what happened, read by the trace (metadata only)."""

    def __init__(self):
        self.calls = 0
        self.model: str | None = None
        self.fallback_hops = 0
        self.error: str | None = None
        # finish_reason of the last streamed answer ("stop" = complete; "length" etc. = cut off; None = not reported)
        self.finish_reason: str | None = None
        # per-call metadata (never content): visible characters vs hidden-reasoning characters of the last call
        self.content_chars = 0
        self.reasoning_chars = 0
        self.understanding: dict | None = None  # validated query-understanding result (trace only)
        # BACKUP-PROVIDER HOOK (backup_provider.py): who worded the answer, and why the backup was used
        self.provider: str | None = None  # "openrouter" | "nvidia-backup" | None
        self.backup_reason: str | None = None


# Provider spellings of "the answer is complete" (OpenRouter normalises most to "stop"; some pass native values).
_COMPLETE = {"stop", "end_turn", "eos", "stop_sequence", "complete", "completed", "finished"}
# A stream that only produces hidden reasoning for this long, with no visible content, is abandoned for the next
# model (nemotron spent all max_tokens on reasoning: finish_reason=length, 0 content chars).
REASONING_ABORT_S = 8.0
PROSE_MAX_TOKENS = 1200


def normalize_finish(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    return "stop" if s in _COMPLETE else s


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_error(status: int, headers, body: bytes) -> tuple[str, str, float | None, float | None]:
    """-> (kind, scope, retry_after_s, reset_epoch_s). scope: model | account_minute | account_day.

    OpenRouter's own account caps say so in the message ("free-models-per-day" / "free-models-per-min");
    an upstream provider 429 ("temporarily rate-limited upstream") only concerns that model."""
    text, meta_headers = "", {}
    try:
        obj = json.loads(body or b"{}")
        err = obj.get("error") or {}
        text = (str(err.get("message") or "") + " " + json.dumps(err.get("metadata") or {})).lower()
        meta_headers = {str(k).lower(): v for k, v in ((err.get("metadata") or {}).get("headers") or {}).items()}
    except (ValueError, AttributeError, TypeError):
        text = (body or b"")[:2000].decode("utf-8", "replace").lower()
    hdr = {**meta_headers, **{str(k).lower(): v for k, v in dict(headers or {}).items()}}
    retry = _num(hdr.get("retry-after"))
    reset = _num(hdr.get("x-ratelimit-reset"))
    reset_s = (reset / 1000.0 if reset > 1e11 else reset) if reset else None
    if status == 402:
        return "quota", "account_day", retry, reset_s
    if status == 429:
        if "per-day" in text or "per_day" in text or "daily" in text:
            return "quota", "account_day", retry, reset_s
        if "per-min" in text or "per_min" in text:
            return "rate_limited", "account_minute", retry or 60.0, None
        return "rate_limited", "model", retry, None
    if status in (408, 504):
        return "timeout", "model", retry, None
    if status >= 500 or status == 404:
        return "unavailable", "model", retry, None
    return "bad_response", "model", None, None


class OpenRouterClient:
    """Streams from OpenRouter with the `models` fallback array (layer 2) and the in-memory router (layers 1, 3, 4).

    Per message: at most 2 HTTP requests (the second only if the first failed before any token was sent),
    zero when the account is in quota / cooling state or the daily budget is spent."""

    # One model per request: OpenRouter's server-side `models` failover waited out a silent model for 30 s (live
    # check), so the hop is done here, under the first-token limit. Two requests per message at most.
    MAX_MODELS_PER_CALL = 1

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
                 router: Router | None = None):
        self.s = settings
        self.transport = transport
        self.router = router or Router(settings.openrouter_models, settings.llm_daily_budget,
                                       settings.llm_quota_cooldown_s)

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(connect=self.s.llm_connect_timeout_s, read=self.s.llm_first_token_timeout_s,
                                write=10.0, pool=5.0)
        return httpx.AsyncClient(timeout=timeout, transport=self.transport)

    def _headers(self) -> dict:
        if self.s.llm_provider == "nvidia":
            return {"Authorization": f"Bearer {self.s.openrouter_api_key}", "Content-Type": "application/json"}
        h = {"Authorization": f"Bearer {self.s.openrouter_api_key}", "Content-Type": "application/json",
             "X-Title": "Property Concierge (candidate prototype)",
             # Layer 5: OpenRouter response cache (byte-identical requests only; our own caches are the bigger win).
             "X-OpenRouter-Cache": "true"}
        if self.s.app_url:
            h["HTTP-Referer"] = self.s.app_url
        return h

    def _wire(self, body: dict) -> dict:
        """EVAL-ONLY NVIDIA override: same request, spelled for a plain OpenAI-compatible endpoint (one `model`,
        no OpenRouter-only fields). Production (OpenRouter) bodies pass through untouched."""
        if self.s.llm_provider != "nvidia":
            return body
        b = dict(body)
        b["model"] = (b.pop("models", None) or self.s.openrouter_models)[0]
        b.pop("provider", None)
        if b.pop("reasoning", None) is not None:
            # production asks OpenRouter for reasoning effort=low + exclude and measured 0 reasoning chars; NVIDIA's
            # endpoint spends 8 s+ on hidden reasoning (tripping the 8 s first-token limit), so thinking is switched off
            b["chat_template_kwargs"] = {"enable_thinking": False}
        return b

    def _on_failure(self, models: list[str], kind: str, scope: str, retry: float | None, reset: float | None):
        if scope == "account_day":
            self.router.set_quota(reset_epoch_s=reset)
        elif scope == "account_minute":
            self.router.set_account_cooling(retry or 60.0)
        elif models:
            self.router.fail(models[0], kind, retry)

    def _on_success(self, sent: list[str], answered: str | None, rec: LLMResult, ttft_ms: float | None,
                    hops_before: int):
        idx = next((i for i, m in enumerate(sent) if same_model(m, answered)), 0)
        for m in sent[:idx]:  # OpenRouter failed over server-side past these
            self.router.fail(m, "server_fallback")
        if sent:
            self.router.ok(sent[idx], ttft_ms)
        rec.fallback_hops = hops_before + idx
        rec.provider = "openrouter"  # BACKUP-PROVIDER HOOK

    async def _stream_once(self, messages: list[dict], models: list[str], rec: LLMResult,
                           max_tokens: int, hops_before: int) -> AsyncIterator[str]:
        body = {"models": models, "messages": messages, "stream": True, "temperature": 0.2,
                "max_tokens": max_tokens, "reasoning": {"effort": "low", "exclude": True}}
        rec.calls += 1
        rec.finish_reason = None
        rec.content_chars = rec.reasoning_chars = 0
        self.router.note_call()
        t0 = time.monotonic()
        deadline = t0 + self.s.llm_total_timeout_s
        first = True
        reasoning_t0: float | None = None
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self.s.openrouter_base_url}/chat/completions",
                                         headers=self._headers(), json=self._wire(body)) as resp:
                    if resp.status_code != 200:
                        raw = await resp.aread()
                        kind, scope, retry, reset = classify_error(resp.status_code, resp.headers, raw)
                        self._on_failure(models, kind, scope, retry, reset)
                        raise LLMError(kind, resp.status_code, retry)
                    async for line in resp.aiter_lines():
                        now = time.monotonic()
                        if now > deadline:
                            if first:
                                self.router.fail(models[0], "timeout")
                            raise LLMError("timeout")
                        if first and now - t0 > self.s.llm_first_token_timeout_s:
                            # keep-alive comments (": OPENROUTER PROCESSING") reset httpx's read timeout, so the
                            # first-token limit is enforced here on every line, content or not
                            self.router.fail(models[0], "timeout")
                            raise LLMError("timeout")
                        if first and reasoning_t0 is not None and now - reasoning_t0 > REASONING_ABORT_S:
                            self.router.fail(models[0], "bad_response")  # reasoning-only stream: hop now
                            raise LLMError("bad_response")
                        if not line.startswith("data:"):
                            continue  # blank lines and ": OPENROUTER PROCESSING" keep-alive comments
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        choices = obj.get("choices") or []
                        if "error" in obj or any((ch or {}).get("finish_reason") == "error" for ch in choices):
                            code = (obj.get("error") or {}).get("code")
                            kind = "rate_limited" if code == 429 else "unavailable"
                            if first:  # error chunk inside HTTP 200 before any token: that model failed
                                self.router.fail(models[0], kind)
                            raise LLMError(kind, code if isinstance(code, int) else None)
                        if obj.get("model"):
                            rec.model = obj["model"]
                        for ch in choices:
                            if (ch or {}).get("finish_reason"):
                                rec.finish_reason = normalize_finish(ch["finish_reason"])
                            delta = (ch or {}).get("delta") or {}
                            hidden = delta.get("reasoning") or delta.get("reasoning_content") or ""
                            if hidden and isinstance(hidden, str):  # counted, never shown
                                rec.reasoning_chars += len(hidden)
                                if reasoning_t0 is None:
                                    reasoning_t0 = time.monotonic()
                            piece = delta.get("content")  # only visible content is ever yielded
                            if piece and isinstance(piece, str):
                                rec.content_chars += len(piece)
                                if first:
                                    first = False
                                    self._on_success(models, rec.model, rec, (time.monotonic() - t0) * 1000,
                                                     hops_before)
                                yield piece
        except httpx.TimeoutException as e:
            if first:
                self.router.fail(models[0], "timeout")
            raise LLMError("timeout") from e
        except httpx.HTTPError as e:
            if first:
                self.router.fail(models[0], "unavailable")
            raise LLMError("unavailable") from e
        finally:
            log.info("llm call model=%s finish_reason=%s content_chars=%d reasoning_chars=%d ms=%d",
                     rec.model or (models[0] if models else None), rec.finish_reason, rec.content_chars,
                     rec.reasoning_chars, int((time.monotonic() - t0) * 1000))
        if first:
            self.router.fail(models[0], "bad_response")
            raise LLMError("bad_response")

    async def stream(self, messages: list[dict], rec: LLMResult, max_tokens: int = PROSE_MAX_TOKENS,
                     allow_retry: bool = True) -> AsyncIterator[str]:
        """Stream tokens. A failure before the first token opens that model's breaker and, unless the account is
        now blocked, retries once on the remaining healthy models. A failure after the first token is raised."""
        tried: list[str] = []
        last: LLMError | None = None
        for attempt in range(2 if allow_retry else 1):
            blocked = self.router.block_reason()
            if blocked:
                last = last if (last and blocked == "all_models_down") else LLMError(blocked)
                break
            models = [m for m in self.router.ordered() if m not in tried][:self.MAX_MODELS_PER_CALL]
            if not models:
                last = last or LLMError("all_models_down")
                break
            started = False
            try:
                async for piece in self._stream_once(messages, models, rec, max_tokens, len(tried)):
                    started = True
                    yield piece
                return
            except LLMError as e:
                last = e
                rec.error = e.kind
                log.info("llm attempt %d failed: %s", attempt + 1, e.kind)
                if started or e.kind == "quota":
                    raise
                tried.append(models[0])
        raise last or LLMError("unavailable")

    async def complete_json(self, messages: list[dict], rec: LLMResult, max_tokens: int = 400) -> str | None:
        """One non-streaming call for query understanding (JSON). One model, first-token limit as the timeout.
        None on any failure (the code planner's result is used instead); never retried."""
        if self.router.block_reason() or self.router.near_cap():
            return None
        models = self.router.ordered()[:1]
        if not models:
            return None
        rec.calls += 1
        self.router.note_call()
        body = {"models": models, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
                "reasoning": {"effort": "low", "exclude": True}, "response_format": {"type": "json_object"}}
        try:
            async with self._client() as client:
                resp = await asyncio.wait_for(
                    client.post(f"{self.s.openrouter_base_url}/chat/completions", headers=self._headers(), json=self._wire(body)),
                    timeout=self.s.llm_first_token_timeout_s + 4)
        except (httpx.HTTPError, asyncio.TimeoutError):
            self.router.fail(models[0], "timeout")
            return None
        if resp.status_code != 200:
            kind, scope, retry, reset = classify_error(resp.status_code, resp.headers, resp.content)
            self._on_failure(models, kind, scope, retry, reset)
            return None
        try:
            obj = resp.json()
            rec.model = obj.get("model") or rec.model
            content = obj["choices"][0]["message"].get("content")
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        log.info("llm understanding model=%s content_chars=%d", rec.model, len(content or ""))
        if content:
            self._on_success(models, rec.model, rec, None, 0)
        return content or None

    async def tool_call(self, messages: list[dict], tools: list[dict], rec: LLMResult) -> dict | None:
        """Single non-streaming call that may return one tool call. Returns {"name", "arguments"} or None.
        Skipped (None, no request) when the router blocks calls or the daily budget is >= 90 % used."""
        if self.router.block_reason() or self.router.near_cap():
            return None
        models = self.router.ordered()[:self.MAX_MODELS_PER_CALL]
        rec.calls += 1
        self.router.note_call()
        body = {"models": models, "messages": messages, "tools": tools, "tool_choice": "auto",
                "temperature": 0, "max_tokens": 200, "reasoning": {"effort": "low", "exclude": True},
                "provider": {"require_parameters": True}}
        try:
            async with self._client() as client:
                resp = await asyncio.wait_for(
                    client.post(f"{self.s.openrouter_base_url}/chat/completions", headers=self._headers(), json=self._wire(body)),
                    timeout=self.s.llm_first_token_timeout_s)
        except (httpx.HTTPError, asyncio.TimeoutError):
            if models:
                self.router.fail(models[0], "timeout")
            return None
        if resp.status_code != 200:
            kind, scope, retry, reset = classify_error(resp.status_code, resp.headers, resp.content)
            self._on_failure(models, kind, scope, retry, reset)
            return None
        try:
            obj = resp.json()
            rec.model = obj.get("model") or rec.model
            self._on_success(models, rec.model, rec, None, 0)
            tc = obj["choices"][0]["message"].get("tool_calls") or []
            if not tc:
                return None
            fn = tc[0]["function"]
            args = json.loads(fn.get("arguments") or "{}")
            return {"name": fn["name"], "arguments": args if isinstance(args, dict) else {}}
        except (ValueError, KeyError, IndexError, TypeError):
            return None

    async def check_models(self) -> list[str]:
        """Layer 1 boot check: GET the public model list (no completion, so no quota is spent) and drop pool
        members that are gone or no longer free. Returns removed ids; network errors change nothing."""
        if self.s.llm_provider == "nvidia":
            return []  # eval override: NVIDIA's list has no pricing; the single pinned model is used as configured
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), transport=self.transport) as client:
                resp = await client.get(f"{self.s.openrouter_base_url}/models")
            if resp.status_code != 200:
                return []
            removed = self.router.apply_listing((resp.json() or {}).get("data") or [])
            if removed:
                log.warning("models removed from pool (not listed or not free): %s", ",".join(removed))
            return removed
        except (httpx.HTTPError, ValueError, AttributeError):
            return []


class MockLLM:
    """Deterministic stand-in used with LLM_MODE=mock. Writes prose only from the <context> block.

    `fail_with` simulates provider failures: "429" (every call), "429_once" (first call only), "timeout".
    """

    model_name = "mock/echo"

    def __init__(self, fail_with: str | None = None, leak: bool = False, extra: str = "",
                 truncate: str | None = None, understanding=None):
        # understanding: None -> the mock declines (no call counted); a dict/str -> returned as the JSON reply
        self.understanding = understanding
        self.fail_with = fail_with
        self.leak = leak
        self.extra = extra
        self.truncate = truncate  # e.g. "Was": stream only this text and end with finish_reason "length"
        self._failed_once = False
        self.router = Router([self.model_name], daily_budget=10**9)

    def _maybe_fail(self):
        if self.fail_with == "429":
            raise LLMError("rate_limited", 429)
        if self.fail_with == "timeout":
            raise LLMError("timeout")
        if self.fail_with == "429_once" and not self._failed_once:
            self._failed_once = True
            raise LLMError("rate_limited", 429)

    async def stream(self, messages: list[dict], rec: LLMResult, max_tokens: int = 600,
                     allow_retry: bool = True) -> AsyncIterator[str]:
        attempts = 2 if allow_retry else 1
        last = None
        for i in range(attempts):
            rec.calls += 1
            try:
                self._maybe_fail()
            except LLMError as e:
                last = e
                rec.error = e.kind
                continue
            rec.model = self.model_name
            rec.fallback_hops = i
            text = self.truncate if self.truncate is not None else self._compose(messages)
            for tok in re.findall(r"\S+\s*", text):
                yield tok
            rec.finish_reason = "length" if self.truncate is not None else "stop"
            return
        raise last

    def _compose(self, messages: list[dict]) -> str:
        sys_msg = messages[0]["content"]
        user = messages[-1]["content"]
        ar = "Reply in Arabic" in sys_msg
        m = re.search(r"\[1\] \(([^)]*)\) (.+)", user)
        if self.leak:
            return "Sure. Rule 1. Use ONLY facts in <context>. " + (m.group(2)[:80] if m else "")
        if not m:
            return "هذه المعلومة غير منشورة." if ar else "That is not published."
        fact = " ".join(re.split(r"(?<=[.!?؟])\s", m.group(2).strip())[:2])[:300]
        lead = "وفقاً للمعلومات المنشورة: " if ar else "According to the published information: "
        return lead + fact + (" " + self.extra if self.extra else "")

    async def complete_json(self, messages: list[dict], rec: LLMResult, max_tokens: int = 400) -> str | None:
        if self.understanding is None:
            return None
        rec.calls += 1
        try:
            self._maybe_fail()
        except LLMError:
            return None
        rec.model = self.model_name
        u = self.understanding(messages) if callable(self.understanding) else self.understanding
        return u if isinstance(u, str) else json.dumps(u)

    async def tool_call(self, messages: list[dict], tools: list[dict], rec: LLMResult) -> dict | None:
        rec.calls += 1
        try:
            self._maybe_fail()
        except LLMError:
            return None
        rec.model = self.model_name
        q = messages[-1]["content"]
        return {"name": "search_knowledge", "arguments": {"query": q}}
