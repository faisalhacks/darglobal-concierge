<#
Assembles a clean deploy bundle and uploads it to a Hugging Face Docker Space.
Never reads or prints secrets. Auth comes from the hf CLI's own login (`hf auth login`) or HF_TOKEN already in your environment.

Usage: pwsh deploy/hf/deploy.ps1 -Space <user-or-org>/<space-name> [-DryRun]

--- One-time setup (placeholders only; run yourself, never commit real values) ---
Create the Space:     hf repo create <user>/<space> --repo-type space --space_sdk docker
Set secrets (HF API): python -c "from huggingface_hub import HfApi; a=HfApi(); a.add_space_secret('<user>/<space>','OPENROUTER_API_KEY','<value>')"
Set public vars:      python -c "from huggingface_hub import HfApi; a=HfApi(); [a.add_space_variable('<user>/<space>',k,v) for k,v in {'LLM_MODE':'live','APP_URL':'<https://...>','CANDIDATE_NAME':'<name>','CANDIDATE_GITHUB':'<url>','CANDIDATE_LINKEDIN':'<url>','CANDIDATE_EMAIL':'<email>'}.items()]"
Note: CANDIDATE_* are variables (not secrets) because /api/meta serves them publicly in the footer.
#>
param(
  [Parameter(Mandatory)][string]$Space,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$bundle = Join-Path ([System.IO.Path]::GetTempPath()) ("hf-bundle-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $bundle | Out-Null
try {
  $xd = @('node_modules','.next','out','__pycache__','.venv','.git','.pytest_cache','snapshots','screenshots','test-results','playwright-report','results','index')
  foreach ($d in 'backend','frontend') {
    if (-not (Test-Path (Join-Path $root $d))) { throw "Missing directory: $d" }
    robocopy (Join-Path $root $d) (Join-Path $bundle $d) /E /NFL /NDL /NJH /NJS /NP /XD @xd /XF '.env' '.env.*' '*.pyc' | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $d ($LASTEXITCODE)" }
  }
  $db = Join-Path $root 'data\concierge.sqlite'
  if (-not (Test-Path $db)) { throw 'data/concierge.sqlite not found' }
  New-Item -ItemType Directory -Path (Join-Path $bundle 'data') | Out-Null
  Copy-Item $db (Join-Path $bundle 'data\concierge.sqlite')
  # The embedding index is built OUTSIDE Docker (the in-image build ran out of memory) and COPYed by the Dockerfile.
  $idx = Join-Path $root 'data\index'
  foreach ($f in 'embeddings.npy','ids.json','meta.json') {
    if (-not (Test-Path (Join-Path $idx $f))) { throw "data/index/$f missing: run python -m backend.app.build_index first" }
  }
  Copy-Item -Recurse $idx (Join-Path $bundle 'data\index')
  $cache = Join-Path $root 'data\answer_cache.json'
  if (Test-Path $cache) { Copy-Item $cache (Join-Path $bundle 'data\answer_cache.json') }
  $evals = Join-Path $root 'evals\results\latest.json'
  if (-not (Test-Path $evals)) { throw 'evals/results/latest.json not found (the Dockerfile COPYs it)' }
  New-Item -ItemType Directory -Path (Join-Path $bundle 'evals\results') -Force | Out-Null
  Copy-Item $evals (Join-Path $bundle 'evals\results\latest.json')
  Copy-Item (Join-Path $root 'Dockerfile') $bundle
  Copy-Item (Join-Path $root '.dockerignore') $bundle
  Copy-Item (Join-Path $PSScriptRoot 'README_SPACE.md') (Join-Path $bundle 'README.md')

  Write-Output "Scanning bundle for secrets/PII..."
  & (Join-Path $root 'deploy\check_secrets.ps1') -Path $bundle
  if ($LASTEXITCODE -ne 0) { throw 'Secret scan failed; aborting upload.' }

  if ($DryRun) { Write-Output "DryRun: bundle at $bundle (not uploaded, not deleted)"; return }
  hf upload $Space $bundle . --repo-type space --commit-message "Deploy bundle"
  if ($LASTEXITCODE -ne 0) { throw 'hf upload failed' }
  Write-Output "Uploaded. Build logs: https://huggingface.co/spaces/$Space"
  Remove-Item -Recurse -Force $bundle
} catch { Write-Error $_; exit 1 }
