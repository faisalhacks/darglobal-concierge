"""Start the backend for an eval run with keys loaded in-process from .env (never printed, never in the image).

  python evals/serve_eval.py nvidia 8020      # LLM_MODE=live EVAL_LLM_PROVIDER=nvidia (answer-quality run)
  python evals/serve_eval.py openrouter 8021  # LLM_MODE=live, normal OpenRouter config (production path)
  python evals/serve_eval.py mock 8019        # LLM_MODE=mock
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envload import ROOT, load_env  # noqa: E402

mode, port = sys.argv[1], sys.argv[2]
have = load_env()
env = dict(os.environ)
for k in ("EVAL_LLM_PROVIDER", "EVAL_LLM_MODEL"):
    env.pop(k, None)
env.update({"FF_FIND_MY_HOME": "true", "RATE_LIMIT": "1000000/300", "STATIC_DIR": str(ROOT / "frontend" / "out"),
            "DATA_PATH": str(ROOT / "data" / "concierge.sqlite"), "FX_FETCH": "off",
            "INDEX_DIR": str(ROOT / "data" / "index"), "EMBED_CACHE_DIR": str(ROOT / "backend" / ".cache" / "fastembed")})
if mode == "nvidia":
    assert "NVIDIA_API_KEY" in have, "NVIDIA_API_KEY missing in .env"
    env.update({"LLM_MODE": "live", "EVAL_LLM_PROVIDER": "nvidia",
                # eval runs are sequential and not limited by the production free-tier guards
                "LLM_DAILY_BUDGET": "100000", "GLOBAL_LLM_PER_MIN": "0"})
    env.pop("OPENROUTER_API_KEY", None)
elif mode == "openrouter":
    assert "OPENROUTER_API_KEY" in have, "OPENROUTER_API_KEY missing in .env"
    env["LLM_MODE"] = "live"
    env.pop("NVIDIA_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
else:
    env["LLM_MODE"] = "mock"
    for k in ("OPENROUTER_API_KEY", "NVIDIA_API_KEY", "GEMINI_API_KEY"):
        env.pop(k, None)
py = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
sys.exit(subprocess.call([str(py), "-m", "uvicorn", "backend.app.main:app", "--port", port, "--host", "127.0.0.1"], cwd=str(ROOT), env=env))
