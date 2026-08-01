#Requires -Version 5.1
param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 3000,
    [switch]$Background,
    [switch]$SkipOllamaCheck
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ApiDir = Join-Path $RepoRoot 'apps\api'
$WebDir = Join-Path $RepoRoot 'apps\web'
$VenvPython = Join-Path $ApiDir '.venv\Scripts\python.exe'

function Write-Step([string]$Message) {
    Write-Host ('==> ' + $Message) -ForegroundColor Cyan
}

function Import-DotEnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Write-Step ('Loading ' + (Split-Path $Path -Leaf))
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

function Stop-PortListener([int]$Port) {
    $killed = @()
    $seen = @{}

    foreach ($pass in 1..3) {
        try {
            $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
            foreach ($conn in $connections) {
                $procId = $conn.OwningProcess
                if ($procId -and $procId -gt 0 -and -not $seen.ContainsKey($procId)) {
                    $seen[$procId] = $true
                    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                    if ($proc) {
                        Write-Host ('  Stopping ' + $proc.ProcessName + ' (PID ' + $procId + ') on port ' + $Port)
                        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                        $killed += $procId
                    }
                }
            }
        } catch {
            netstat -ano | Select-String (':' + $Port + '\s') | ForEach-Object {
                if ($_ -match '\s(\d+)\s*$') {
                    $procId = [int]$Matches[1]
                    if ($procId -gt 0 -and -not $seen.ContainsKey($procId)) {
                        $seen[$procId] = $true
                        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                        $killed += $procId
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 400
    }
    return $killed.Count
}

function Wait-PortFree([int]$Port, [int]$TimeoutSec = 15) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $busy = $false
        try {
            $busy = [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        } catch {
            $busy = [bool](netstat -ano | Select-String (':' + $Port + '\s.*LISTENING'))
        }
        if (-not $busy) { return $true }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Test-OllamaRunning([string]$BaseUrl) {
    try {
        $uri = $BaseUrl -replace '/v1/?$', ''
        if (-not $uri.EndsWith('/')) { $uri += '/' }
        $response = Invoke-WebRequest -Uri ($uri + 'api/tags') -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-HttpOk([string]$Url, [int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 800
        }
    }
    return $false
}

Write-Host ''
Write-Host 'CareerOS dev restart' -ForegroundColor Green
Write-Host ('Repo: ' + $RepoRoot)
Write-Host ''

Write-Step ('Stopping servers on ports ' + $ApiPort + ', ' + $WebPort + ' (and legacy 8001)')
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'uvicorn|app\.main:app' } | ForEach-Object {
    Write-Host ('  Stopping uvicorn python PID ' + $_.ProcessId)
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
foreach ($port in @($ApiPort, $WebPort, 8001)) {
    $count = Stop-PortListener -Port $port
    if ($count -eq 0) {
        Write-Host ('  Port ' + $port + ' already free')
    }
}

Start-Sleep -Seconds 2
foreach ($port in @($ApiPort, $WebPort, 8001)) {
    Stop-PortListener -Port $port | Out-Null
}

foreach ($port in @($ApiPort, $WebPort)) {
    $attempt = 0
    while (-not (Wait-PortFree -Port $port -TimeoutSec 3) -and $attempt -lt 5) {
        $attempt++
        Write-Host ('  Retrying stop on port ' + $port + ' (attempt ' + $attempt + ')')
        Stop-PortListener -Port $port | Out-Null
        Start-Sleep -Seconds 1
    }
    if (-not (Wait-PortFree -Port $port -TimeoutSec 2)) {
        Write-Warning ('Port ' + $port + ' still in use - startup may fail.')
    }
}

Write-Step 'Applying environment'
Import-DotEnvFile (Join-Path $RepoRoot '.env')
Import-DotEnvFile (Join-Path $ApiDir '.env')
Import-DotEnvFile (Join-Path $WebDir '.env.local')

$apiUrl = 'http://localhost:' + $ApiPort
$webUrl = 'http://localhost:' + $WebPort
$env:NEXT_PUBLIC_API_URL = $apiUrl
$env:CAREER_OS_API_PUBLIC_URL = $apiUrl
$env:CAREER_OS_CORS_ORIGINS = $webUrl + ',chrome-extension://*'
$env:CAREER_OS_DEV_MODE = 'true'
$env:APPLICATION_ASSISTANT_ENABLED = 'true'

if (-not $env:APPLICATION_ASSISTANT_LLM_BASE_URL) {
    $env:APPLICATION_ASSISTANT_LLM_BASE_URL = 'http://localhost:11434/v1'
}
if (-not $env:APPLICATION_ASSISTANT_LLM_MODEL) {
    $env:APPLICATION_ASSISTANT_LLM_MODEL = 'qwen3:8b'
}
$env:CHRONOS_MAPPING_ENABLED = 'true'
$env:CHRONOS_MAPPING_MODEL = $env:APPLICATION_ASSISTANT_LLM_MODEL
$env:CHRONOS_VISION_ENABLED = 'false'
$env:CHRONOS_MAPPING_CONFIDENCE = '0.90'
$env:CHRONOS_REVIEW_CONFIDENCE = '0.70'

if (Test-Path $VenvPython) {
    $venvScripts = Split-Path $VenvPython -Parent
    $env:PATH = $venvScripts + ';' + $env:PATH
    $env:VIRTUAL_ENV = Join-Path $ApiDir '.venv'
    Write-Host ('  Python venv: ' + $VenvPython)
    $playwrightOk = & $VenvPython -c "import playwright" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  Installing Playwright in API venv...'
        & $VenvPython -m pip install -r (Join-Path $ApiDir 'requirements.txt') | Out-Null
        & $VenvPython -m playwright install chromium | Out-Null
    }
} else {
    Write-Warning '  API venv not found at apps/api/.venv - using system Python'
}

Write-Host ('  API:  ' + $apiUrl)
Write-Host ('  Web:  ' + $webUrl)
Write-Host ('  LLM:  ' + $env:APPLICATION_ASSISTANT_LLM_BASE_URL + ' (' + $env:APPLICATION_ASSISTANT_LLM_MODEL + ')')

if (-not $SkipOllamaCheck) {
    if (Test-OllamaRunning $env:APPLICATION_ASSISTANT_LLM_BASE_URL) {
        Write-Host '  Ollama: reachable' -ForegroundColor DarkGreen
    } else {
        Write-Warning ('  Ollama not reachable at ' + $env:APPLICATION_ASSISTANT_LLM_BASE_URL + ' - start Ollama for Qwen prep')
    }
}

Set-Location $RepoRoot

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw 'pnpm not found on PATH. Install Node 20+ and pnpm 9+, then run: pnpm install'
}

Write-Step 'Starting pnpm dev'
if ($Background) {
    $logDir = Join-Path $RepoRoot 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFile = Join-Path $logDir ('dev-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    $errFile = $logFile + '.err'
    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'pnpm dev' -WorkingDirectory $RepoRoot -PassThru -RedirectStandardOutput $logFile -RedirectStandardError $errFile
    Write-Host ('  PID ' + $proc.Id + ' - log: ' + $logFile)
    Write-Step 'Waiting for API health'
    if (Wait-HttpOk ($apiUrl + '/health')) {
        Write-Host '  API healthy' -ForegroundColor DarkGreen
    } else {
        Write-Warning ('  API not ready yet - check ' + $logFile)
    }
    Write-Step 'Ready'
    Write-Host ('  Dashboard: ' + $webUrl + '/application-assistant')
    Write-Host ('  API docs:  ' + $apiUrl + '/docs')
} else {
    Write-Host ''
    Write-Host 'Press Ctrl+C to stop both servers.' -ForegroundColor DarkGray
    Write-Host ''
    & pnpm dev
}
