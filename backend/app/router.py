"""Model router state (docs/MODEL_ROUTER.md, layers 1, 3 and 4). In memory, per process, metadata only.

Layer 1  candidate pool: OPENROUTER_MODELS (all `:free`); models no longer listed / no longer free are removed.
Layer 3  per-model circuit breaker: 429 / 5xx / timeout / mid-stream error -> cooldown 30 s doubling to 10 min,
         `Retry-After` honoured; EWMA of time-to-first-token kept per model; healthy models ordered by
         configured (Arabic-gate) rank, then latency.
Layer 4  account states: 402 or the daily free cap -> "quota" for N minutes (no LLM calls at all); the per-minute
         account cap -> "cooling" until it resets; a daily budget guard (LLM_DAILY_BUDGET) counts every outbound
         request and blocks at the cap. At >= 90 % of the budget only answer-writing calls are allowed (no tool
         routing call), so the remaining calls go to questions that need prose.

Nothing here is persisted and nothing here ever contains a key, a prompt or a client address.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

BASE_COOLDOWN_S = 30.0
MAX_COOLDOWN_S = 600.0
EWMA_ALPHA = 0.3


def _utc_day() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def same_model(a: str | None, b: str | None) -> bool:
    """OpenRouter may report the answering model without the `:free` suffix (or with a provider date tag)."""
    if not a or not b:
        return False
    a, b = a.split(":")[0].lower(), b.split(":")[0].lower()
    return a == b or a.startswith(b) or b.startswith(a)


@dataclass
class ModelHealth:
    model: str
    rank: int
    removed: bool = False
    open_until: float = 0.0
    cooldown_s: float = 0.0
    fails: int = 0
    ewma_ttft_ms: float | None = None
    last_error: str | None = None

    def state(self, now: float) -> str:
        if self.removed:
            return "removed"
        return "cooling" if self.open_until > now else "healthy"


class Router:
    def __init__(self, models: list[str], daily_budget: int = 45, quota_cooldown_s: float = 1800.0,
                 clock=time.monotonic, wall=time.time, day=_utc_day):
        self.pool = [ModelHealth(m, i) for i, m in enumerate(dict.fromkeys(models))]
        self.daily_budget = max(0, int(daily_budget))
        self.quota_cooldown_s = quota_cooldown_s
        self._clock, self._wall, self._day = clock, wall, day
        self.quota_until = 0.0  # monotonic
        self.cool_until = 0.0   # account-wide per-minute cap
        self.used = 0
        self.used_day = day()

    # ------------------------------------------------------------ budget
    def _roll(self):
        d = self._day()
        if d != self.used_day:
            self.used_day, self.used = d, 0

    def budget(self) -> dict:
        self._roll()
        return {"used": self.used, "cap": self.daily_budget}

    def note_call(self):
        """Count one outbound HTTP request (failed attempts count too: the provider probably counts them)."""
        self._roll()
        self.used += 1

    def near_cap(self) -> bool:
        self._roll()
        return self.daily_budget > 0 and self.used >= 0.9 * self.daily_budget

    # ------------------------------------------------------------ account states
    def block_reason(self) -> str | None:
        """Why no LLM call may be made right now (None = calls allowed)."""
        now = self._clock()
        self._roll()
        if self.quota_until > now or self.used >= self.daily_budget:
            return "quota"
        if self.cool_until > now:
            return "rate_limited"
        if not self.ordered():
            return "all_models_down"
        return None

    def set_quota(self, seconds: float | None = None, reset_epoch_s: float | None = None):
        secs = self.quota_cooldown_s if seconds is None else seconds
        if reset_epoch_s:
            until_wall = reset_epoch_s - self._wall()
            if 0 < until_wall < 36 * 3600:
                secs = until_wall
        self.quota_until = max(self.quota_until, self._clock() + max(1.0, secs))

    def set_account_cooling(self, seconds: float):
        self.cool_until = max(self.cool_until, self._clock() + max(1.0, min(seconds, MAX_COOLDOWN_S)))

    @property
    def state(self) -> str:
        r = self.block_reason()
        if r == "quota":
            return "quota"
        if r in ("rate_limited", "all_models_down"):
            return "cooling"
        return "ok"

    # ------------------------------------------------------------ per-model breaker
    def _get(self, model: str) -> ModelHealth | None:
        return next((h for h in self.pool if h.model == model), None) or \
            next((h for h in self.pool if same_model(h.model, model)), None)

    def ordered(self) -> list[str]:
        now = self._clock()
        healthy = [h for h in self.pool if h.state(now) == "healthy"]
        healthy.sort(key=lambda h: (h.rank, h.ewma_ttft_ms if h.ewma_ttft_ms is not None else 0.0))
        return [h.model for h in healthy]

    def fail(self, model: str, kind: str, retry_after_s: float | None = None):
        h = self._get(model)
        if h is None:
            return
        h.fails += 1
        h.cooldown_s = BASE_COOLDOWN_S if h.cooldown_s <= 0 else min(MAX_COOLDOWN_S, h.cooldown_s * 2)
        wait = h.cooldown_s
        if retry_after_s:
            wait = max(wait, min(float(retry_after_s), MAX_COOLDOWN_S))
        h.open_until = self._clock() + wait
        h.last_error = kind

    def ok(self, model: str, ttft_ms: float | None = None):
        h = self._get(model)
        if h is None:
            return
        h.fails, h.cooldown_s, h.open_until, h.last_error = 0, 0.0, 0.0, None
        if ttft_ms is not None:
            h.ewma_ttft_ms = ttft_ms if h.ewma_ttft_ms is None else \
                (1 - EWMA_ALPHA) * h.ewma_ttft_ms + EWMA_ALPHA * ttft_ms

    def apply_listing(self, listing: list[dict]) -> list[str]:
        """Layer 1 boot check against the public /api/v1/models list: drop models that are gone or no longer free.
        Returns the removed ids. Never removes the whole pool on an empty/garbled listing."""
        if not listing:
            return []
        free = {}
        for m in listing:
            mid = m.get("id") if isinstance(m, dict) else None
            if not mid:
                continue
            p = (m.get("pricing") or {}) if isinstance(m, dict) else {}
            is_free = mid.endswith(":free") or (str(p.get("prompt", "1")) in ("0", "0.0") and
                                                str(p.get("completion", "1")) in ("0", "0.0"))
            free[mid] = is_free
        removed = []
        for h in self.pool:
            if not free.get(h.model, False):
                h.removed = True
                removed.append(h.model)
        return removed

    def snapshot(self) -> list[dict]:
        now = self._clock()
        return [{"model": h.model, "state": h.state(now)} for h in self.pool]
