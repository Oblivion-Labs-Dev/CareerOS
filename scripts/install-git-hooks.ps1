#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$HooksDir = Join-Path $RepoRoot ".githooks"

if (-not (Test-Path $HooksDir)) {
    throw "Missing .githooks directory at $HooksDir"
}

Set-Location $RepoRoot
git config core.hooksPath .githooks
Write-Host "Git hooks path set to .githooks" -ForegroundColor Green
Write-Host "  pre-commit and pre-push run: pnpm ci (all 4 GitHub Actions jobs)"
Write-Host "  Skip once: SKIP_CI=1 git commit ...  or  git commit --no-verify"
