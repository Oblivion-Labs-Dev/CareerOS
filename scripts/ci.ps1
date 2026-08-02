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
    param([string[]]$PythonArgs)
    $py = Get-ApiPython
    if ($py -is [array]) {
        & $py[0] $py[1] @PythonArgs
    } else {
        & $py @PythonArgs
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

$serverLogDir = Join-Path ([IO.Path]::GetTempPath()) ("careeros-ci-e2e-" + [Guid]::NewGuid().ToString("N"))
$null = New-Item -ItemType Directory -Path $serverLogDir
$apiStdout = Join-Path $serverLogDir "api.stdout.log"
$apiStderr = Join-Path $serverLogDir "api.stderr.log"
$webStdout = Join-Path $serverLogDir "web.stdout.log"
$webStderr = Join-Path $serverLogDir "web.stderr.log"
$py = Get-ApiPython
$apiArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
if ($py -is [array]) {
    $apiProc = Start-Process -FilePath $py[0] -ArgumentList ($py[1..($py.Length - 1)] + $apiArgs) `
        -WorkingDirectory $ApiDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $apiStdout `
        -RedirectStandardError $apiStderr
} else {
    $apiProc = Start-Process -FilePath $py -ArgumentList $apiArgs `
        -WorkingDirectory $ApiDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $apiStdout `
        -RedirectStandardError $apiStderr
}

$nodeCommand = Get-Command "node.exe" -ErrorAction Stop
$webProc = Start-Process -FilePath $nodeCommand.Source `
    -ArgumentList @("node_modules/next/dist/bin/next", "start", "--port", "3000") `
    -WorkingDirectory $WebDir `
    -RedirectStandardOutput $webStdout `
    -RedirectStandardError $webStderr `
    -PassThru -WindowStyle Hidden

try {
    npx --yes wait-on "http-get://127.0.0.1:8000/health" "http://127.0.0.1:3000" -t 120000
    $waitExitCode = $LASTEXITCODE
    if ($waitExitCode -ne 0) {
        Write-Host "--- API stdout ---"
        Get-Content -LiteralPath $apiStdout -ErrorAction SilentlyContinue
        Write-Host "--- API stderr ---"
        Get-Content -LiteralPath $apiStderr -ErrorAction SilentlyContinue
        Write-Host "--- Web stdout ---"
        Get-Content -LiteralPath $webStdout -ErrorAction SilentlyContinue
        Write-Host "--- Web stderr ---"
        Get-Content -LiteralPath $webStderr -ErrorAction SilentlyContinue
        exit $waitExitCode
    }

    $env:CI = "1"
    pnpm --filter @career-os/web exec playwright test
    $exitCode = $LASTEXITCODE
} finally {
    foreach ($proc in @($apiProc, $webProc)) {
        if ($proc -and -not $proc.HasExited) {
            & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
        }
    }
}

if ($exitCode -ne 0) { exit $exitCode }

Write-Host ""
Write-Host "All CI checks passed (typecheck, extension-unit, api, web-e2e)." -ForegroundColor Green
