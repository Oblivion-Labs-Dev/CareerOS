#Requires -Version 5.1
param(
    [int]$ApiPort = 4000,
    [int]$WebPort = 5000,
    [switch]$Background,
    [switch]$SkipOllamaCheck,
    # Serve the web app from a production build (next build + next start)
    # instead of next dev. Much faster for daily use; use dev for UI work.
    [switch]$Prod,
    # With -Prod, reuse the last build instead of rebuilding.
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ApiDir = Join-Path $RepoRoot 'apps\api'
$WebDir = Join-Path $RepoRoot 'apps\web'
$VenvPython = Join-Path $ApiDir '.venv\Scripts\python.exe'
# PID of the cmd.exe that roots the pnpm tree this script last started.
$StackPidFile = Join-Path $RepoRoot 'logs\dev-stack.pid'

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

function Stop-ProcessTree([int]$RootId, [string]$Why) {
    if (-not (Get-Process -Id $RootId -ErrorAction SilentlyContinue)) { return }
    Write-Host ('  Stopping process tree PID ' + $RootId + ' (' + $Why + ')')
    & taskkill.exe /PID $RootId /T /F 2>&1 | Out-Null
}

# Walk up from a server process to the outermost launcher of the stack
# (cmd /c pnpm ... -> pnpm -> cmd -> next/uvicorn), so stopping it takes the
# whole pnpm tree. Killing only the port owner left pnpm --parallel alive, and
# the next restart stacked another tree beside it.
function Get-StackRoot([int]$ProcId) {
    $root = $ProcId
    $current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ProcId) -ErrorAction SilentlyContinue
    while ($current) {
        $parent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $current.ParentProcessId) -ErrorAction SilentlyContinue
        if (-not $parent -or $parent.CommandLine -notmatch 'pnpm|next(\.cmd)? (dev|start)|uvicorn') { break }
        $root = $parent.ProcessId
        $current = $parent
    }
    return $root
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

function Start-OllamaIfNeeded([string]$BaseUrl) {
    if (Test-OllamaRunning $BaseUrl) {
        Write-Host '  Ollama: already running and reachable' -ForegroundColor DarkGreen
        return $true
    }

    Write-Step 'Starting Ollama service...'

    # Memory tuning for a 16GB laptop that also runs the dev stack and a
    # browser. Measured on qwen3:4b-instruct at an 8192 context: 3.87 GB
    # resident before, 3.31 GB after, with no context reduction and no change
    # to output quality.
    #   FLASH_ATTENTION  - required for the quantised KV cache below
    #   KV_CACHE_TYPE    - q8_0 roughly halves KV cache memory
    #   MAX_LOADED_MODELS- stops a second model becoming resident alongside the
    #                      first; mistral:7b and qwen3:4b were both loaded at
    #                      once (5.6 + 3.9 GB) before this was set
    #   NUM_PARALLEL     - each parallel slot allocates its own KV cache
    $env:OLLAMA_FLASH_ATTENTION   = '1'
    $env:OLLAMA_KV_CACHE_TYPE     = 'q8_0'
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    $env:OLLAMA_NUM_PARALLEL      = '1'

    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    $ollamaPath = $null
    if ($ollamaCmd) {
        $ollamaPath = $ollamaCmd.Source
    } else {
        $candidate = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
        if (Test-Path $candidate) {
            $ollamaPath = $candidate
        }
    }

    if ($ollamaPath) {
        try {
            Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -WindowStyle Hidden
            Write-Host ('  Launched Ollama serve (' + $ollamaPath + ')') -ForegroundColor DarkGreen
            $deadline = (Get-Date).AddSeconds(15)
            while ((Get-Date) -lt $deadline) {
                if (Test-OllamaRunning $BaseUrl) {
                    Write-Host '  Ollama is ready!' -ForegroundColor DarkGreen
                    return $true
                }
                Start-Sleep -Milliseconds 600
            }
            Write-Warning '  Ollama started but taking longer than 15s to respond.'
        } catch {
            Write-Warning ('  Failed to start Ollama automatically: ' + $_.Exception.Message)
        }
    } else {
        Write-Warning '  Ollama executable not found on PATH or default location. Please install Ollama.'
    }
    return $false
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

$Mode = if ($Prod) { 'production' } else { 'dev' }
Write-Host ''
Write-Host ('CareerOS restart (' + $Mode + ')') -ForegroundColor Green
Write-Host ('Repo: ' + $RepoRoot)
Write-Host ''

Write-Step 'Applying environment'
Import-DotEnvFile (Join-Path $RepoRoot '.env')
Import-DotEnvFile (Join-Path $ApiDir '.env')
Import-DotEnvFile (Join-Path $WebDir '.env.local')

$apiUrl = 'http://127.0.0.1:' + $ApiPort
$webUrl = 'http://localhost:' + $WebPort
$env:NEXT_PUBLIC_API_URL = $apiUrl
$env:CAREER_OS_API_PUBLIC_URL = $apiUrl
$env:CAREER_OS_CORS_ORIGINS = $webUrl + ',chrome-extension://*'
$env:CAREER_OS_DEV_MODE = 'true'
$env:APPLICATION_ASSISTANT_ENABLED = 'true'

Set-Location $RepoRoot
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw 'pnpm not found on PATH. Install Node 20+ and pnpm 9+, then run: pnpm install'
}

# Build before stopping anything, so the running stack keeps serving for the
# ~80 s the build takes. The build writes to apps/web/.next-prod, never the
# .next a running next dev uses (see next.config.ts).
if ($Prod -and -not $SkipBuild) {
    Write-Step 'Building @career-os/core, @career-os/ui and the web app (next build)'
    & pnpm build:web
    if ($LASTEXITCODE -ne 0) { throw ('Production build failed (exit ' + $LASTEXITCODE + '); the running stack was left as it was.') }
} elseif ($Prod -and -not (Test-Path (Join-Path $WebDir '.next-prod\BUILD_ID'))) {
    throw '-SkipBuild given but apps/web/.next-prod has no build. Run without -SkipBuild.'
}

Write-Step ('Stopping servers on ports ' + $ApiPort + ', ' + $WebPort + ' (and legacy 8001)')
if (Test-Path $StackPidFile) {
    $oldRoot = [int](Get-Content $StackPidFile -Raw).Trim()
    Stop-ProcessTree $oldRoot 'previous pnpm tree'
    Remove-Item $StackPidFile -Force -ErrorAction SilentlyContinue
}
foreach ($port in @($ApiPort, $WebPort)) {
    foreach ($conn in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
        if ($conn.OwningProcess -gt 0) { Stop-ProcessTree (Get-StackRoot $conn.OwningProcess) ('tree serving port ' + $port) }
    }
}
# Port owners are not always visible (sandboxed shells, no admin), so also
# match this checkout's own next server by command line.
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'node.exe' -and $_.CommandLine -and $_.CommandLine.Contains($WebDir) -and $_.CommandLine -match 'next[\\/]dist[\\/]bin[\\/]next"? +(dev|start)'
} | ForEach-Object {
    Stop-ProcessTree (Get-StackRoot $_.ProcessId) 'next server of this checkout'
}
# Only the uvicorn serving this API port: other checkouts or agents may run
# their own API on another port against their own database.
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like 'python*' -and $_.CommandLine -match 'uvicorn|app\.main:app' -and $_.CommandLine -match ('--port[= ]' + $ApiPort + '(\s|$)')
} | ForEach-Object {
    Stop-ProcessTree (Get-StackRoot $_.ProcessId) ('uvicorn on port ' + $ApiPort)
}
Start-Sleep -Seconds 1

# Orphaned worker processes must go too, and this is not tidiness.
#
# The API spawns multiprocessing workers, and a worker INHERITS the listening
# socket on the API port. When the uvicorn parent dies without reaping them,
# the orphan keeps that socket open and keeps answering requests - with the
# code it was started with. The restart then appears to succeed, the health
# check passes, and every subsequent edit looks like it had no effect because
# a months-old process is still serving. Observed with three orphans holding
# port 4000 at once, serving routes that no longer matched the source.
#
# Get-NetTCPConnection attributes that socket to the DEAD parent pid, so the
# port-based sweep below cannot find them; they have to be matched by command
# line instead.
#
# Only orphans are swept: a spawned worker whose parent is still alive belongs
# to some other tool (MCP servers, language servers) and is not ours to kill.
# The uvicorn parents were stopped just above, so the API's own workers are
# orphans by now.
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like 'python*' -and $_.CommandLine -like '*multiprocessing.spawn*'
} | ForEach-Object {
    if (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) { return }
    Write-Host ('  Stopping spawned worker PID ' + $_.ProcessId + ' (ORPHAN, parent ' + $_.ParentProcessId + ' is gone)')
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

if (-not $env:APPLICATION_ASSISTANT_LLM_BASE_URL) {
    $env:APPLICATION_ASSISTANT_LLM_BASE_URL = 'http://localhost:11434/v1'
}
if (-not $env:APPLICATION_ASSISTANT_LLM_MODEL) {
    $env:APPLICATION_ASSISTANT_LLM_MODEL = 'mistral-small3.2:24b'
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

# Same switch the API reads: with the local model off, nothing may call it,
# so Ollama is not started either.
$env:CAREEROS_LOCAL_LLM = 'off'
$localLlmOff = @('off', '0', 'false', 'no') -contains ("$env:CAREEROS_LOCAL_LLM".Trim().ToLower())
if ($localLlmOff) {
    Write-Host '  Ollama: not started (CAREEROS_LOCAL_LLM=off)' -ForegroundColor DarkGray
} elseif (-not $SkipOllamaCheck) {
    Start-OllamaIfNeeded $env:APPLICATION_ASSISTANT_LLM_BASE_URL | Out-Null
}

$pnpmScript = if ($Prod) { 'start:prod' } else { 'dev' }
Write-Step ('Starting pnpm ' + $pnpmScript)
if ($Background) {
    $logDir = Join-Path $RepoRoot 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFile = Join-Path $logDir ('dev-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    $errFile = $logFile + '.err'
    # -WindowStyle Hidden forces a genuinely separate console/process group for the
    # child cmd.exe, so a Ctrl+C delivered to this script's own console (e.g. from a
    # subsequent tool invocation sharing the terminal) doesn't get broadcast to the
    # dev servers and kill them out from under a running session.
    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', ('pnpm ' + $pnpmScript) -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError $errFile
    Set-Content -Path $StackPidFile -Value $proc.Id -Encoding ascii
    Write-Host ('  PID ' + $proc.Id + ' - log: ' + $logFile)
    Write-Step 'Waiting for both Backend API & Web Frontend to be healthy...'
    $apiOk = Wait-HttpOk ($apiUrl + '/health') -TimeoutSec 45
    $webOk = Wait-HttpOk ($webUrl + '/applications') -TimeoutSec 45

    if ($apiOk -and $webOk) {
        Write-Host ''
        Write-Host '=======================================================================' -ForegroundColor Green
        Write-Host '  [OK] SYSTEM UP AND RUNNING' -ForegroundColor Green
        Write-Host ('  [✓] Backend API:   ' + $apiUrl + ' (Healthy & Connected)') -ForegroundColor DarkGreen
        Write-Host ('  [✓] Web Frontend:  ' + $webUrl + ' (Healthy & Connected)') -ForegroundColor DarkGreen
        Write-Host '  Both health checks passed and servers are fully operational!' -ForegroundColor Green
        Write-Host '=======================================================================' -ForegroundColor Green
        Write-Host ''
    } else {
        if (-not $apiOk) { Write-Warning ('  [!] Backend API failed health check at ' + $apiUrl + '/health') }
        if (-not $webOk) { Write-Warning ('  [!] Web Frontend failed health check at ' + $webUrl) }
    }
    Write-Step 'Ready'
    Write-Host ('  Dashboard: ' + $webUrl + '/applications')
    Write-Host ('  API docs:  ' + $apiUrl + '/docs')
} else {
    Write-Host ''
    Write-Host 'Press Ctrl+C to stop both servers.' -ForegroundColor DarkGray
    Write-Host ''
    & pnpm $pnpmScript
}
