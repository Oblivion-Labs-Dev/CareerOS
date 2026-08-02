#Requires -Version 5.1
# Mirrors .github/workflows/ci.yml — all four jobs must pass.
param(
    [switch]$SkipWebE2E
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ApiDir = Join-Path $RepoRoot "apps\api"
$WebDir = Join-Path $RepoRoot "apps\web"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Get-ApiPython {
    $venvPy = Join-Path $ApiDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    $unixPy = Join-Path $ApiDir ".venv/bin/python"
    if (Test-Path $unixPy) { return $unixPy }
    foreach ($cmd in @("python", "py")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            if ($cmd -eq "py") { return @("py", "-3") }
            return $cmd
        }
    }
    throw "Python not found. Run scripts/setup.ps1 first."
}

function Invoke-ApiPython {
    param([string[]]$Args)
    $py = Get-ApiPython
    if ($py -is [array]) {
        & $py[0] $py[1] @Args
    } else {
        & $py @Args
    }
}

Set-Location $RepoRoot

Write-Step "CI / typecheck"
pnpm --filter @career-os/core build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
pnpm typecheck
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Step "CI / extension-unit"
pnpm --filter @career-os/extension test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Step "CI / api"
Push-Location $ApiDir
try {
    Invoke-ApiPython @("-m", "pip", "install", "-q", "-r", "requirements.txt", "pytest", "httpx")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Invoke-ApiPython @("-m", "compileall", "app")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Invoke-ApiPython @("-m", "pytest", "tests", "-q")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

if ($SkipWebE2E) {
    Write-Host ""
    Write-Host "Skipped web-e2e (-SkipWebE2E)." -ForegroundColor Yellow
    exit 0
}

Write-Step "CI / web-e2e (build)"
pnpm --filter @career-os/core build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
pnpm --filter @career-os/web build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Step "CI / web-e2e (playwright install)"
pnpm --filter @career-os/web exec playwright install chromium
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Step "CI / web-e2e (servers + tests)"
Invoke-ApiPython @("-m", "pip", "install", "-q", "-r", (Join-Path $ApiDir "requirements.txt"))

$py = Get-ApiPython
$apiArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
if ($py -is [array]) {
    $apiProc = Start-Process -FilePath $py[0] -ArgumentList ($py[1..($py.Length - 1)] + $apiArgs) `
        -WorkingDirectory $ApiDir -PassThru -WindowStyle Hidden
} else {
    $apiProc = Start-Process -FilePath $py -ArgumentList $apiArgs `
        -WorkingDirectory $ApiDir -PassThru -WindowStyle Hidden
}

$webProc = Start-Process -FilePath "pnpm" `
    -ArgumentList @("start", "--port", "3000") `
    -WorkingDirectory $WebDir `
    -PassThru -WindowStyle Hidden

try {
    npx --yes wait-on "http://127.0.0.1:8000/health" "http://127.0.0.1:3000" -t 120000
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $env:CI = "1"
    pnpm --filter @career-os/web exec playwright test
    $exitCode = $LASTEXITCODE
} finally {
    foreach ($proc in @($apiProc, $webProc)) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($exitCode -ne 0) { exit $exitCode }

Write-Host ""
Write-Host "All CI checks passed (typecheck, extension-unit, api, web-e2e)." -ForegroundColor Green
