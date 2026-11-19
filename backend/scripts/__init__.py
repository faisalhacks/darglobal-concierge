"""Operator scripts (run from the repo root): warm_cache.py, live_check.py. Never print or log secrets."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_dotenv(path: str | None = None, keys: tuple[str, ...] = ("OPENROUTER_API_KEY",)) -> bool:
    """Read only the named keys from the repo-root .env into this process's environment (never printed).
    Returns True if OPENROUTER_API_KEY is set afterwards."""
    path = path or os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k in keys and v and not os.environ.get(k):
                    os.environ[k] = v
    return bool(os.environ.get("OPENROUTER_API_KEY"))
