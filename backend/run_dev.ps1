# Local dev server for the backend (Windows PowerShell).
# Usage (from the repo root):  .\backend\run_dev.ps1            # no key -> degraded answers
#                              .\backend\run_dev.ps1 -Mock      # deterministic mock LLM
# Set $env:OPENROUTER_API_KEY in your shell (never in a file) to use real free models.
param([switch]$Mock, [int]$Port = 7860)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    uv venv backend\.venv --python 3.12
    uv pip install --python $py -r backend\requirements-dev.txt
}
if (-not $env:DATA_PATH) { $env:DATA_PATH = "data/concierge.sqlite" }
if (-not $env:INDEX_DIR) { $env:INDEX_DIR = "data/index" }
if (-not $env:STATIC_DIR) { $env:STATIC_DIR = "frontend/out" }
if (-not $env:EMBED_CACHE_DIR) { $env:EMBED_CACHE_DIR = "backend/.cache/fastembed" }
if ($Mock) { $env:LLM_MODE = "mock" }
if (-not (Test-Path (Join-Path $env:INDEX_DIR "embeddings.npy"))) {
    Write-Host "Building embedding index (first run downloads the ONNX model)..."
    & $py -m backend.app.build_index --data $env:DATA_PATH --out $env:INDEX_DIR --cache-dir $env:EMBED_CACHE_DIR
}
& $py -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port --no-access-log
