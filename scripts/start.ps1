#Requires -Version 5.1
<#
.SYNOPSIS
  One-command CareerOS startup: prereqs, deps, builds, Ollama, servers, health checks.

.EXAMPLE
  .\start.bat
  .\scripts\start.ps1 -SkipJobs
#>
param(
    [switch]$SkipJobs,
    [switch]$SkipExtension,
    [switch]$SkipOllama,
    [switch]$SkipNightBatch,
    [switch]$Background
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ApiDir = Join-Path $RepoRoot 'apps\api'
$WebDir = Join-Path $RepoRoot 'apps\web'
$ExtDir = Join-Path $RepoRoot 'apps\extension'
$VenvPython = Join-Path $ApiDir '.venv\Scripts\python.exe'

function Write-Step([string]$Message) {
    Write-Host ('==> ' + $Message) -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host ('  OK  ' + $Message) -ForegroundColor DarkGreen
}

function Write-Warn([string]$Message) {
    Write-Host ('  !!  ' + $Message) -ForegroundColor Yellow
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Import-DotEnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $name = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

function Wait-HttpOk([string]$Url, [int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return $true }
        } catch { Start-Sleep -Milliseconds 800 }
    }
    return $false
}

Write-Host ''
Write-Host 'CareerOS one-command startup' -ForegroundColor Green
Write-Host ('Repo: ' + $RepoRoot)
Write-Host ''

# ── Prerequisites ─────────────────────────────────────────────────────────────
Write-Step 'Checking prerequisites'
if (-not (Test-Command node)) { throw 'Node.js 20+ not found. Install from https://nodejs.org/' }
$nodeVer = (node -v) -replace '^v',''
Write-Ok "Node $nodeVer"
if (-not (Test-Command pnpm)) { throw 'pnpm not found. Run: corepack enable' }
Write-Ok "pnpm $(pnpm -v)"
if (-not (Test-Command python)) { throw 'Python 3.11+ not found.' }
Write-Ok "Python $((python -c 'import sys; print(sys.version)').Split(' ')[0])"

# ── Dependencies ──────────────────────────────────────────────────────────────
Write-Step 'Installing JS dependencies (pnpm install)'
Set-Location $RepoRoot
pnpm install
Write-Ok 'pnpm install complete'

Write-Step 'Installing Python dependencies'
if (-not (Test-Path $VenvPython)) {
    python -m venv (Join-Path $ApiDir '.venv')
    Write-Ok 'Created apps/api/.venv'
}
& $VenvPython -m pip install --upgrade pip | Out-Null
& $VenvPython -m pip install -r (Join-Path $ApiDir 'requirements.txt') | Out-Null
Write-Ok 'pip requirements installed'

# ── Builds ────────────────────────────────────────────────────────────────────
Write-Step 'Building workspace packages (@career-os/core, @career-os/ui)'
pnpm -r --filter "@career-os/core" --filter "@career-os/ui" run build
Write-Ok 'Workspace builds complete'

if (-not $SkipExtension) {
    Write-Step 'Building Chrome extension'
    pnpm --filter @career-os/extension build
    Write-Ok 'Extension built to apps/extension/dist'
}

# ── Stop any existing servers ─────────────────────────────────────────────────
Write-Step 'Stopping existing servers on ports 4000, 5000'
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'uvicorn|app\.main:app' } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
foreach ($port in @(4000, 5000, 8001)) {
    try {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}
Start-Sleep -Seconds 2

# ── Env ───────────────────────────────────────────────────────────────────────
Write-Step 'Applying environment'
Import-DotEnvFile (Join-Path $RepoRoot '.env')
Import-DotEnvFile (Join-Path $ApiDir '.env')
Import-DotEnvFile (Join-Path $WebDir '.env.local')

$apiUrl = 'http://127.0.0.1:4000'
$webUrl = 'http://localhost:5000'
$env:NEXT_PUBLIC_API_URL = $apiUrl
$env:CAREER_OS_API_PUBLIC_URL = $apiUrl
$env:CAREER_OS_CORS_ORIGINS = $webUrl + ',chrome-extension://*'
$env:CAREER_OS_DEV_MODE = 'true'
$env:APPLICATION_ASSISTANT_ENABLED = 'true'
if (-not $env:APPLICATION_ASSISTANT_LLM_BASE_URL) { $env:APPLICATION_ASSISTANT_LLM_BASE_URL = 'http://localhost:11434/v1' }
if (-not $env:APPLICATION_ASSISTANT_LLM_MODEL) { $env:APPLICATION_ASSISTANT_LLM_MODEL = 'mistral-small3.2:24b' }
$env:CHRONOS_MAPPING_ENABLED = 'true'
$env:CHRONOS_MAPPING_MODEL = $env:APPLICATION_ASSISTANT_LLM_MODEL

if (Test-Path $VenvPython) {
    $env:PATH = (Split-Path $VenvPython -Parent) + ';' + $env:PATH
    $env:VIRTUAL_ENV = Join-Path $ApiDir '.venv'
}

# ── Ollama ────────────────────────────────────────────────────────────────────
$localLlmOff = @('off', '0', 'false', 'no') -contains ("$env:CAREEROS_LOCAL_LLM".Trim().ToLower())
if (-not $localLlmOff -and -not $SkipOllama) {
    Write-Step 'Ensuring Ollama is running'
    & (Join-Path $PSScriptRoot 'restart-dev.ps1') -SkipOllamaCheck:$false -ApiPort 4000 -WebPort 5000 -ErrorAction SilentlyContinue | Out-Null
}

# ── Start servers ─────────────────────────────────────────────────────────────
Write-Step 'Starting CareerOS (API + Web)'
Set-Location $RepoRoot
if ($Background) {
    $logDir = Join-Path $RepoRoot 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFile = Join-Path $logDir ('start-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    $errFile = $logFile + '.err'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'pnpm dev' -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError $errFile | Out-Null
    Write-Host ('  Log: ' + $logFile)
} else {
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'pnpm dev' -WorkingDirectory $RepoRoot | Out-Null
}

Write-Step 'Waiting for health checks'
$apiOk = Wait-HttpOk ($apiUrl + '/health') -TimeoutSec 45
$webOk = Wait-HttpOk ($webUrl + '/applications') -TimeoutSec 45

if ($apiOk -and $webOk) {
    Write-Host ''
    Write-Host '=======================================================================' -ForegroundColor Green
    Write-Host '  [OK] CAREEROS UP AND RUNNING' -ForegroundColor Green
    Write-Host ('  API:  ' + $apiUrl)
    Write-Host ('  Web:  ' + $webUrl)
    Write-Host ('  Docs: ' + $apiUrl + '/docs')
    Write-Host '=======================================================================' -ForegroundColor Green
} else {
    if (-not $apiOk) { Write-Warning 'API health check failed' }
    if (-not $webOk) { Write-Warning 'Web health check failed' }
}

# ── Optional: pull jobs + dedup + night batch ──────────────────────────────────
if (-not $SkipJobs) {
    Write-Step 'Triggering fresh job scrape (last 24h)'
    try {
        $body = @{ hours = 24; roles = 'swe'; mode = 'all' } | ConvertTo-Json
        Invoke-RestMethod -Uri ($apiUrl + '/jobs/discover/scrape') -Method POST -Body $body -ContentType 'application/json' -TimeoutSec 10 | Out-Null
        Write-Ok 'Scrape started'
    } catch { Write-Warn ('Scrape trigger failed: ' + $_.Exception.Message) }

    Start-Sleep -Seconds 20
    try {
        Invoke-RestMethod -Uri ($apiUrl + '/application-assistant/autopilot/dedupe-applications') -Method POST -TimeoutSec 15 | Out-Null
        Write-Ok 'Dedup check complete'
    } catch { Write-Warn ('Dedup failed: ' + $_.Exception.Message) }
}

if (-not $SkipNightBatch) {
    Write-Step 'Starting queue preprocessor + night batch'
    try {
        Invoke-RestMethod -Uri ($apiUrl + '/application-assistant/autopilot/queue-preparation/start') -Method POST -TimeoutSec 10 | Out-Null
        Write-Ok 'Queue preprocessor started'
    } catch { Write-Warn ('Queue preprocessor start failed: ' + $_.Exception.Message) }

    try {
        $body = '{}'
        Invoke-RestMethod -Uri ($apiUrl + '/application-assistant/autopilot/start') -Method POST -Body $body -ContentType 'application/json' -TimeoutSec 10 | Out-Null
        Write-Ok 'Autopilot night batch started'
    } catch { Write-Warn ('Autopilot start failed: ' + $_.Exception.Message) }
}

Write-Host ''
Write-Host 'Startup complete.' -ForegroundColor Green
