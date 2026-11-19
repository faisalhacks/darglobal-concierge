"""OpenRouter client (streaming, `models` fallback array) + deterministic mock for tests.

Timeouts: connect 5 s, first token 12 s, total 30 s. 429 / 5xx / timeout -> one retry on the remaining
fallback models -> caller switches to the degraded template. Never more than 2 calls per message.
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

log = logging.getLogger("concierge.llm")


class LLMError(Exception):
    def __init__(self, kind: str, status: int | None = None):
        super().__init__(kind)
        self.kind = kind  # rate_limited | timeout | unavailable | bad_response
        self.status = status


class LLMResult:
    """Mutable record of what happened, read by the trace."""

    def __init__(self):
        self.calls = 0
        self.model: str | None = None


class OpenRouterClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(connect=self.s.llm_connect_timeout_s, read=self.s.llm_first_token_timeout_s,
                                write=10.0, pool=5.0)
        return httpx.AsyncClient(timeout=timeout, transport=self.transport)

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.s.openrouter_api_key}", "Content-Type": "application/json",
             "X-Title": "Property Concierge (candidate prototype)"}
        if self.s.app_url:
            h["HTTP-Referer"] = self.s.app_url
        return h

    async def _stream_once(self, messages: list[dict], models: list[str], rec: LLMResult,
                           max_tokens: int) -> AsyncIterator[str]:
        body = {"models": models, "messages": messages, "stream": True, "temperature": 0.2,
                "max_tokens": max_tokens}
        rec.calls += 1
        deadline = time.monotonic() + self.s.llm_total_timeout_s
        first = True
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self.s.openrouter_base_url}/chat/completions",
                                         headers=self._headers(), json=body) as resp:
                    if resp.status_code == 429:
                        raise LLMError("rate_limited", 429)
                    if resp.status_code >= 500 or resp.status_code in (402, 404, 408):
                        raise LLMError("unavailable", resp.status_code)
                    if resp.status_code >= 400:
                        raise LLMError("bad_response", resp.status_code)
                    async for line in resp.aiter_lines():
                        if time.monotonic() > deadline:
                            raise LLMError("timeout")
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        if "error" in obj:
                            code = (obj.get("error") or {}).get("code")
                            if first:
                                raise LLMError("rate_limited" if code == 429 else "unavailable", code)
                            break
                        rec.model = obj.get("model") or rec.model
                        for ch in obj.get("choices") or []:
                            piece = (ch.get("delta") or {}).get("content")
                            if piece:
                                first = False
                                yield piece
        except httpx.TimeoutException as e:
            raise LLMError("timeout") from e
        except httpx.HTTPError as e:
            raise LLMError("unavailable") from e
        if first:
            raise LLMError("bad_response")

    async def stream(self, messages: list[dict], rec: LLMResult, max_tokens: int = 400,
                     allow_retry: bool = True) -> AsyncIterator[str]:
        """Stream tokens. On failure before the first token, retry once with the fallback models."""
        models = list(self.s.openrouter_models)
        attempts = [models]
        if allow_retry and len(models) > 1:
            attempts.append(models[1:])
        last: LLMError | None = None
        for i, ms in enumerate(attempts):
            started = False
            try:
                async for piece in self._stream_once(messages, ms, rec, max_tokens):
                    started = True
                    yield piece
                return
            except LLMError as e:
                last = e
                log.info("llm attempt %d failed: %s", i + 1, e.kind)
                if started:
                    raise
        raise last or LLMError("unavailable")

    async def tool_call(self, messages: list[dict], tools: list[dict], rec: LLMResult) -> dict | None:
        """Single non-streaming call that may return one tool call. Returns {"name", "arguments"} or None."""
        rec.calls += 1
        body = {"models": self.s.openrouter_models, "messages": messages, "tools": tools, "tool_choice": "auto",
                "temperature": 0, "max_tokens": 200}
        try:
            async with self._client() as client:
                resp = await asyncio.wait_for(
                    client.post(f"{self.s.openrouter_base_url}/chat/completions", headers=self._headers(), json=body),
                    timeout=self.s.llm_first_token_timeout_s)
        except (httpx.HTTPError, asyncio.TimeoutError):
            return None
        if resp.status_code != 200:
            return None
        try:
            obj = resp.json()
            rec.model = obj.get("model") or rec.model
            tc = obj["choices"][0]["message"].get("tool_calls") or []
            if not tc:
                return None
            fn = tc[0]["function"]
            args = json.loads(fn.get("arguments") or "{}")
            return {"name": fn["name"], "arguments": args if isinstance(args, dict) else {}}
        except (ValueError, KeyError, IndexError, TypeError):
            return None


class MockLLM:
    """Deterministic stand-in used with LLM_MODE=mock. Writes prose only from the <context> block.

    `fail_with` simulates provider failures: "429" (every call), "429_once" (first call only), "timeout".
    """

    model_name = "mock/echo"

    def __init__(self, fail_with: str | None = None, leak: bool = False, extra: str = ""):
        self.fail_with = fail_with
        self.leak = leak
        self.extra = extra
        self._failed_once = False

    def _maybe_fail(self):
        if self.fail_with == "429":
            raise LLMError("rate_limited", 429)
        if self.fail_with == "timeout":
            raise LLMError("timeout")
        if self.fail_with == "429_once" and not self._failed_once:
            self._failed_once = True
            raise LLMError("rate_limited", 429)

    async def stream(self, messages: list[dict], rec: LLMResult, max_tokens: int = 400,
                     allow_retry: bool = True) -> AsyncIterator[str]:
        attempts = 2 if allow_retry else 1
        last = None
        for _ in range(attempts):
            rec.calls += 1
            try:
                self._maybe_fail()
            except LLMError as e:
                last = e
                continue
            rec.model = self.model_name
            text = self._compose(messages)
            for tok in re.findall(r"\S+\s*", text):
                yield tok
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

    async def tool_call(self, messages: list[dict], tools: list[dict], rec: LLMResult) -> dict | None:
        rec.calls += 1
        try:
            self._maybe_fail()
        except LLMError:
            return None
        rec.model = self.model_name
        q = messages[-1]["content"]
        return {"name": "search_knowledge", "arguments": {"query": q}}
