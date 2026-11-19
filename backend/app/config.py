"""Runtime configuration. Everything comes from environment variables (SPEC §25).

No secrets are ever stored in files; OPENROUTER_API_KEY is read from the environment only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

FLAG_NAMES = ("FF_FIND_MY_HOME", "FF_MAP", "FF_VOICE", "FF_HANDOFF_BRIEF", "FF_WIDGET_DEMO")

# Chosen from the public OpenRouter /models list on 2026-11-19 and ordered by the live check of the same day
# (NVIDIA first: the only model that answered in the 2026-11-19 live check and passed the Arabic gate; see MODELS.md).
DEFAULT_MODELS = "nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free"
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    data_path: str = "data/concierge.sqlite"
    index_dir: str = "data/index"
    static_dir: str = "/app/static"
    openrouter_api_key: str | None = None
    openrouter_models: list[str] = field(default_factory=list)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    app_url: str = ""
    allowed_origins: list[str] = field(default_factory=list)
    rate_limit_n: int = 15
    rate_limit_window_s: int = 300
    retrieval_threshold: float = 0.45
    llm_connect_timeout_s: float = 5.0
    llm_first_token_timeout_s: float = 12.0
    llm_total_timeout_s: float = 30.0
    cache_ttl_s: int = 3600
    maintenance_mode: bool = False
    llm_mode: str = "auto"  # auto | mock | off
    embeddings: str = "auto"  # auto | off
    embed_cache_dir: str | None = None
    max_body_bytes: int = 16_384
    trusted_proxy_hops: int = 0  # proxies in front of us that append to X-Forwarded-For (1 on HF Spaces / Render)
    global_llm_per_min: int = 30  # process-wide chat cap while an LLM is configured (0 = off)
    llm_tool_routing: bool = False  # off by default: one LLM call per message, the code planner routes
    llm_daily_budget: int = 45  # outbound LLM requests per UTC day; at the cap: no calls, extractive answers
    llm_quota_cooldown_s: float = 1800.0  # 402 / daily free cap -> quota state this long (or until X-RateLimit-Reset)
    llm_boot_model_check: bool = True  # GET /models at boot (free, no completion) and drop unlisted / non-free models
    answer_cache_path: str = "data/answer_cache.json"  # baked, read-only answer cache (backend/scripts/warm_cache.py)
    flags: dict[str, bool] = field(default_factory=dict)
    candidate: dict[str, str | None] = field(default_factory=dict)

    @property
    def llm_mode_label(self) -> str:
        """live | mock | off, as reported by /api/meta."""
        if self.llm_mode == "mock":
            return "mock"
        return "live" if self.llm_available else "off"

    @property
    def llm_available(self) -> bool:
        if self.llm_mode == "off":
            return False
        if self.llm_mode == "mock":
            return True
        return bool(self.openrouter_api_key)


def _rate_limit() -> tuple[int, int]:
    # RATE_LIMIT="15/300" (messages / seconds)
    raw = os.environ.get("RATE_LIMIT", "15/300")
    try:
        n, w = raw.split("/")
        return int(n), int(w)
    except ValueError:
        return 15, 300


def load_settings() -> Settings:
    n, w = _rate_limit()
    origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    app_url = os.environ.get("APP_URL", "").strip()
    if app_url and app_url not in origins:
        origins.append(app_url)
    for local in ("http://localhost:3000", "http://localhost:7860", "http://127.0.0.1:7860"):
        if local not in origins:
            origins.append(local)
    total = _float("LLM_TIMEOUT_S", 30.0)
    return Settings(
        data_path=os.environ.get("DATA_PATH", "data/concierge.sqlite"),
        index_dir=os.environ.get("INDEX_DIR", "data/index"),
        static_dir=os.environ.get("STATIC_DIR", "/app/static"),
        openrouter_api_key=(os.environ.get("OPENROUTER_API_KEY") or "").strip() or None,
        openrouter_models=[m.strip() for m in os.environ.get("OPENROUTER_MODELS", DEFAULT_MODELS).split(",") if m.strip()],
        openrouter_base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        app_url=app_url,
        allowed_origins=origins,
        rate_limit_n=n,
        rate_limit_window_s=w,
        retrieval_threshold=_float("RETRIEVAL_THRESHOLD", 0.45),
        llm_total_timeout_s=total,
        cache_ttl_s=_int("CACHE_TTL_S", 3600),
        maintenance_mode=_bool("MAINTENANCE_MODE"),
        llm_mode=os.environ.get("LLM_MODE", "auto").strip().lower(),
        embeddings=os.environ.get("EMBEDDINGS", "auto").strip().lower(),
        embed_cache_dir=os.environ.get("EMBED_CACHE_DIR") or None,
        max_body_bytes=_int("MAX_BODY_BYTES", 16_384),
        trusted_proxy_hops=max(0, _int("TRUSTED_PROXY_HOPS", 0)),
        global_llm_per_min=max(0, _int("GLOBAL_LLM_PER_MIN", 30)),
        llm_tool_routing=_bool("LLM_TOOL_ROUTING", False),
        llm_daily_budget=max(0, _int("LLM_DAILY_BUDGET", 45)),
        llm_quota_cooldown_s=max(1.0, _float("LLM_QUOTA_COOLDOWN_S", 1800.0)),
        llm_boot_model_check=_bool("LLM_BOOT_MODEL_CHECK", True),
        answer_cache_path=os.environ.get("ANSWER_CACHE_PATH", "data/answer_cache.json"),
        flags={f: _bool(f) for f in FLAG_NAMES},
        candidate={
            "name": os.environ.get("CANDIDATE_NAME") or None,
            "github": os.environ.get("CANDIDATE_GITHUB") or None,
            "linkedin": os.environ.get("CANDIDATE_LINKEDIN") or None,
            "email": os.environ.get("CANDIDATE_EMAIL") or None,
        },
    )
