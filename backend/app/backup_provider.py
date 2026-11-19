"""Production resilience backup: the same Nemotron model via NVIDIA's OpenAI-compatible API.

Order of writers: OpenRouter free models (unchanged) -> NVIDIA backup (only here) -> code-built fallback.
The backup is used ONLY when the OpenRouter chain fails before any token with quota (402 / daily-cap 429),
all-models-down, or timeouts. Same prompts and guardrails (the caller screens every token), same first-token
limit, a hop counts as an LLM call (max 2 per message), its own daily budget and breaker.
Off by default: BACKUP_PROVIDER=nvidia switches it on. The key (NVIDIA_API_KEY) is read from the environment
only and goes only into the Authorization header; it is never logged and never stored in code or the image.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import AsyncIterator

import httpx

from .llm import REASONING_ABORT_S, LLMError, LLMResult, normalize_finish
from .router import _utc_day

log = logging.getLogger("concierge.backup")

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# TODO: the exact NVIDIA-hosted Nemotron Ultra id is confirmed by the eval run (EVAL_LLM_PROVIDER=nvidia);
# override with NVIDIA_MODEL until then.
NVIDIA_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
# OpenRouter-side failures that hand over to the backup (rate_limited on one model does not).
BACKUP_ON = {"quota", "timeout", "all_models_down", "unavailable"}
BREAKER_FAILS = 2
BREAKER_COOLDOWN_S = 300.0


class BackupConfig:
    def __init__(self, provider: str = "", api_key: str | None = None, model: str = NVIDIA_DEFAULT_MODEL,
                 base_url: str = NVIDIA_BASE_URL, daily_budget: int = 200):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.daily_budget = max(0, daily_budget)

    @property
    def enabled(self) -> bool:
        return self.provider == "nvidia" and bool(self.api_key)

    @classmethod
    def from_env(cls) -> "BackupConfig":
        try:
            cap = int(os.environ.get("BACKUP_DAILY_BUDGET", 200))
        except ValueError:
            cap = 200
        return cls(provider=(os.environ.get("BACKUP_PROVIDER") or "").strip().lower(),
                   api_key=(os.environ.get("NVIDIA_API_KEY") or "").strip() or None,
                   model=(os.environ.get("NVIDIA_MODEL") or "").strip() or NVIDIA_DEFAULT_MODEL,
                   base_url=os.environ.get("NVIDIA_BASE_URL") or NVIDIA_BASE_URL, daily_budget=cap)


class BackupLLM:
    """Wraps the primary client. Everything but `stream` is delegated untouched (no backup for JSON / tool calls)."""

    def __init__(self, primary, cfg: BackupConfig, first_token_s: float = 8.0, total_s: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None, clock=time.monotonic, day=_utc_day):
        self.primary, self.cfg = primary, cfg
        self.first_token_s, self.total_s, self.transport = first_token_s, total_s, transport
        self._clock, self._day = clock, day
        self.used, self.used_day = 0, day()
        self.fails, self.open_until = 0, 0.0

    def __getattr__(self, name):  # router, check_models, tool_call, complete_json, model_name ...
        return getattr(self.primary, name)

    # ---------------------------------------------------------------- budget + breaker
    def _roll(self):
        d = self._day()
        if d != self.used_day:
            self.used_day, self.used = d, 0

    def meta(self) -> dict:
        self._roll()
        return {"enabled": self.cfg.enabled, "provider": "nvidia" if self.cfg.provider == "nvidia" else None,
                "model": self.cfg.model if self.cfg.enabled else None,
                "used": self.used, "cap": self.cfg.daily_budget}

    def available(self) -> bool:
        self._roll()
        return self.cfg.enabled and self.used < self.cfg.daily_budget and self._clock() >= self.open_until

    def _fail(self):
        self.fails += 1
        if self.fails >= BREAKER_FAILS:
            self.open_until, self.fails = self._clock() + BREAKER_COOLDOWN_S, 0

    # ---------------------------------------------------------------- stream
    async def stream(self, messages: list[dict], rec: LLMResult, max_tokens: int = 1200,
                     allow_retry: bool = True) -> AsyncIterator[str]:
        if not self.cfg.enabled:
            async for p in self.primary.stream(messages, rec, max_tokens=max_tokens, allow_retry=allow_retry):
                yield p
            return
        # A backup hop is a call: the primary gets one attempt so that hop is still within 2 calls per message.
        started = False
        try:
            async for p in self.primary.stream(messages, rec, max_tokens=max_tokens, allow_retry=False):
                started = True
                rec.provider = "openrouter"
                yield p
            return
        except LLMError as e:
            if started or e.kind not in BACKUP_ON or rec.calls >= 2 or not self.available():
                raise
            reason = e.kind
        log.info("openrouter failed (%s); trying nvidia backup", reason)
        rec.backup_reason = reason
        async for p in self._stream_nvidia(messages, rec, max_tokens):
            yield p

    async def _stream_nvidia(self, messages, rec: LLMResult, max_tokens: int) -> AsyncIterator[str]:
        body = {"model": self.cfg.model, "messages": messages, "stream": True, "temperature": 0.2,
                "max_tokens": max_tokens}
        rec.calls += 1
        rec.finish_reason = None
        rec.content_chars = rec.reasoning_chars = 0
        self._roll()
        self.used += 1
        t0 = self._clock()
        first, reasoning_t0 = True, None
        timeout = httpx.Timeout(connect=5.0, read=self.first_token_s, write=10.0, pool=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
                async with client.stream("POST", f"{self.cfg.base_url}/chat/completions", json=body, headers={
                        "Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json",
                        "Accept": "text/event-stream"}) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        self._fail()
                        raise LLMError("quota" if resp.status_code in (402, 429) else "unavailable", resp.status_code)
                    async for line in resp.aiter_lines():
                        now = self._clock()
                        if now - t0 > self.total_s or (first and now - t0 > self.first_token_s):
                            self._fail()
                            raise LLMError("timeout")
                        if first and reasoning_t0 is not None and now - reasoning_t0 > REASONING_ABORT_S:
                            self._fail()
                            raise LLMError("bad_response")
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
                            self._fail()
                            raise LLMError("unavailable")
                        if obj.get("model"):
                            rec.model = obj["model"]
                        for ch in obj.get("choices") or []:
                            if (ch or {}).get("finish_reason"):
                                rec.finish_reason = normalize_finish(ch["finish_reason"])
                            delta = (ch or {}).get("delta") or {}
                            hidden = delta.get("reasoning") or delta.get("reasoning_content") or ""
                            if hidden and isinstance(hidden, str):
                                rec.reasoning_chars += len(hidden)
                                reasoning_t0 = reasoning_t0 or self._clock()
                            piece = delta.get("content")
                            if piece and isinstance(piece, str):
                                rec.content_chars += len(piece)
                                if first:
                                    first = False
                                    self.fails = 0
                                    rec.model = rec.model or self.cfg.model
                                    rec.provider = "nvidia-backup"
                                yield piece
        except httpx.TimeoutException as e:
            if first:
                self._fail()
            raise LLMError("timeout") from e
        except httpx.HTTPError as e:
            if first:
                self._fail()
            raise LLMError("unavailable") from e
        finally:
            log.info("backup call model=%s finish_reason=%s content_chars=%d ms=%d", rec.model, rec.finish_reason,
                     rec.content_chars, int((self._clock() - t0) * 1000))
        if first:
            self._fail()
            raise LLMError("bad_response")


def wrap_with_backup(llm, cfg: BackupConfig | None = None, **kw):
    """Hook for main._make_llm: the primary unchanged unless BACKUP_PROVIDER=nvidia (+ NVIDIA_API_KEY) is set."""
    cfg = cfg or BackupConfig.from_env()
    if llm is None or not cfg.enabled:
        return llm
    return BackupLLM(llm, cfg, **kw)
