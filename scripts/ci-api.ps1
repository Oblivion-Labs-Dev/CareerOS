#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ApiDir = Join-Path $RepoRoot "apps\api"

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
    if ($py -is [array]) { & $py[0] $py[1] @Args } else { & $py @Args }
}

Write-Host "==> CI / api" -ForegroundColor Cyan
Push-Location $ApiDir
try {
    Invoke-ApiPython @("-m", "pip", "install", "-q", "-r", "requirements.txt", "pytest", "httpx")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Invoke-ApiPython @("-m", "compileall", "app")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Invoke-ApiPython @("-m", "pytest", "tests", "-q")
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
