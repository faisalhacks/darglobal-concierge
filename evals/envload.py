"""Load KEY=VALUE lines from the gitignored .env into os.environ, in-process only. Never prints a value.
Tolerates quotes, a UTF-8 BOM, CRLF and a stray leading '=' on the value (seen in the NVIDIA line)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WANT = ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY")


def load_env(path: Path | None = None, names=WANT) -> list[str]:
    """Set the wanted names that are not already in the environment. Returns the names that ended up set."""
    p = path or ROOT / ".env"
    found: dict[str, str] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().replace("-", "_").upper()
            if k == "NVIDIA_KEY":
                k = "NVIDIA_API_KEY"  # the `nvidia-key=` spelling
            v = v.strip().strip("\"'").lstrip("=").strip()
            if k in names and v:
                found.setdefault(k, v)
    for k, v in found.items():
        os.environ.setdefault(k, v)
    return [n for n in names if os.environ.get(n)]
