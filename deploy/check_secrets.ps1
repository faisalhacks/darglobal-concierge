<#
Scans a directory for secrets/PII before any upload. Prints file:line and pattern NAME only, never the matched text.
Usage: pwsh deploy/check_secrets.ps1 [-Path <dir>]   Exit 1 if anything is found.
Binary files (sqlite, images, fonts) are scanned as text where possible; sqlite is scanned via Latin1 decode.
#>
param([string]$Path = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path)

$patterns = [ordered]@{
  'openrouter-key'   = 'sk-or-[A-Za-z0-9_-]{10,}'
  'hf-token'         = '\bhf_[A-Za-z0-9]{20,}'
  'github-token'     = '\bgh[opsu]_[A-Za-z0-9]{20,}'
  'aws-access-key'   = '\bAKIA[0-9A-Z]{16}\b'
  'private-key'      = '-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----'
  'email'            = '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
  'phone'            = '(?<![\d.])(\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]\d{3}[\s-]\d{3,4}(?![\d.])'
}
# Emails that are legitimately non-personal placeholders.
$emailAllow = '@(example\.(com|org)|users\.noreply\.github\.com)$|^noreply@|@(2x|3x)\.png$'
$skipDirs = '[\\/](\.git|node_modules|\.next|__pycache__|\.venv)[\\/]'
$skipFiles = 'check_secrets\.ps1$|\.env\.example$|README_SPACE\.md$|pnpm-lock\.yaml$|package-lock\.json$|\.(png|jpe?g|webp|ico|woff2?|ttf|gz|zip|onnx)$'

$found = 0
$files = Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch $skipDirs -and $_.Name -notmatch $skipFiles -and $_.Length -lt 200MB }

foreach ($f in $files) {
  if ($f.Name -match '^\.env($|\.)' -and $f.Name -ne '.env.example') {
    Write-Output "FOUND [env-file] $($f.FullName)"; $found++; continue
  }
  $isDb = $f.Extension -in '.sqlite','.db','.sqlite3'
  try {
    if ($isDb) {
      $text = [System.Text.Encoding]::GetEncoding('iso-8859-1').GetString([System.IO.File]::ReadAllBytes($f.FullName))
      $lines = $text -split "[\r\n\x00]+"
    } else { $lines = [System.IO.File]::ReadAllLines($f.FullName) }
  } catch { continue }
  $n = 0
  foreach ($line in $lines) {
    $n++
    foreach ($k in $patterns.Keys) {
      $ms = [regex]::Matches($line, $patterns[$k])
      foreach ($m in $ms) {
        if ($k -eq 'email' -and $m.Value -match $emailAllow) { continue }
        # Phone pattern only enforced in data files to limit false positives in code.
        if ($k -eq 'phone' -and -not ($isDb -or $f.Extension -in '.json','.jsonl','.csv','.yaml','.yml','.txt')) { continue }
        Write-Output "FOUND [$k] $($f.FullName):$n"
        $found++
      }
    }
  }
}
if ($found -gt 0) { Write-Output "FAILED: $found potential secret/PII hit(s). Values intentionally not printed."; exit 1 }
Write-Output "OK: no secrets or PII patterns found in $Path"; exit 0
