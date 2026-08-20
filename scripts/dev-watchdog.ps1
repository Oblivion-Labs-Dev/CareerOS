#Requires -Version 5.1
<#
.SYNOPSIS
    CareerOS Dev Watchdog — keeps Backend API and Web Frontend alive.

.DESCRIPTION
    Polls both servers every few seconds. If either stops responding,
    the watchdog kills any stale listeners on that port and relaunches
    the service. Designed to run in a dedicated terminal window.

.PARAMETER ApiPort
    Port for the Backend API (default 8000).

.PARAMETER WebPort
    Port for the Web Frontend (default 3000).

.PARAMETER PollInterval
    Seconds between health checks (default 10).

.PARAMETER MaxRestarts
    Max consecutive restarts per service before pausing (default 5).

.PARAMETER CooldownSec
    Seconds to wait after hitting MaxRestarts before retrying (default 60).
#>
param(
    [int]$ApiPort       = 8000,
    [int]$WebPort       = 3000,
    [int]$PollInterval  = 10,
    [int]$MaxRestarts   = 5,
    [int]$CooldownSec   = 60
)

$ErrorActionPreference = 'Continue'
$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ApiDir     = Join-Path $RepoRoot 'apps\api'
$VenvPython = Join-Path $ApiDir '.venv\Scripts\python.exe'
$LogDir     = Join-Path $RepoRoot 'logs'

# ── Ensure logs directory ─────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ── Load .env files (same as restart-dev.ps1) ─────────────────────────
function Import-DotEnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $name  = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

Import-DotEnvFile (Join-Path $RepoRoot '.env')
Import-DotEnvFile (Join-Path $ApiDir   '.env')
Import-DotEnvFile (Join-Path $RepoRoot 'apps\web\.env.local')

# Set env vars the same way restart-dev.ps1 does
$apiUrl = "http://localhost:$ApiPort"
$webUrl = "http://localhost:$WebPort"
$env:NEXT_PUBLIC_API_URL          = $apiUrl
$env:CAREER_OS_API_PUBLIC_URL     = $apiUrl
$env:CAREER_OS_CORS_ORIGINS       = "$webUrl,chrome-extension://*"
$env:CAREER_OS_DEV_MODE           = 'true'
$env:APPLICATION_ASSISTANT_ENABLED = 'true'

if (-not $env:APPLICATION_ASSISTANT_LLM_BASE_URL) {
    $env:APPLICATION_ASSISTANT_LLM_BASE_URL = 'http://localhost:11434/v1'
}
if (-not $env:APPLICATION_ASSISTANT_LLM_MODEL) {
    $env:APPLICATION_ASSISTANT_LLM_MODEL = 'qwen3:8b'
}
$env:CHRONOS_MAPPING_ENABLED    = 'true'
$env:CHRONOS_MAPPING_MODEL      = $env:APPLICATION_ASSISTANT_LLM_MODEL
$env:CHRONOS_VISION_ENABLED     = 'false'
$env:CHRONOS_MAPPING_CONFIDENCE = '0.90'
$env:CHRONOS_REVIEW_CONFIDENCE  = '0.70'

if (Test-Path $VenvPython) {
    $venvScripts   = Split-Path $VenvPython -Parent
    $env:PATH      = "$venvScripts;$env:PATH"
    $env:VIRTUAL_ENV = Join-Path $ApiDir '.venv'
}

# ── Helpers ────────────────────────────────────────────────────────────
function Write-Log([string]$Level, [string]$Msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $color = switch ($Level) {
        'INFO'  { 'Cyan' }
        'WARN'  { 'Yellow' }
        'ERROR' { 'Red' }
        'OK'    { 'Green' }
        default { 'White' }
    }
    Write-Host "[$ts] [$Level] $Msg" -ForegroundColor $color
}

function Test-ServiceAlive([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Stop-PortListener([int]$Port) {
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $connections) {
            $procId = $conn.OwningProcess
            if ($procId -and $procId -gt 0) {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Log 'WARN' "Killing stale $($proc.ProcessName) (PID $procId) on port $Port"
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } catch {
        netstat -ano | Select-String (":${Port}\s") | ForEach-Object {
            if ($_ -match '\s(\d+)\s*$') {
                $procId = [int]$Matches[1]
                if ($procId -gt 0) {
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }
}

# ── Process tracker ────────────────────────────────────────────────────
$script:ApiProcess = $null
$script:WebProcess = $null
$script:ApiRestarts = 0
$script:WebRestarts = 0
$script:ApiCooldownUntil = [datetime]::MinValue
$script:WebCooldownUntil = [datetime]::MinValue

function Start-ApiServer {
    $logFile = Join-Path $LogDir "api-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
    Write-Log 'INFO' "Starting Backend API on port $ApiPort (log: $logFile)"

    # Kill anything on the port first
    Stop-PortListener -Port $ApiPort
    Start-Sleep -Seconds 1

    $script:ApiProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', $ApiPort `
        -WorkingDirectory $ApiDir `
        -PassThru `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError "$logFile.err" `
        -WindowStyle Hidden

    Write-Log 'OK' "Backend API started (PID $($script:ApiProcess.Id))"
}

function Start-WebServer {
    $logFile = Join-Path $LogDir "web-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
    Write-Log 'INFO' "Starting Web Frontend on port $WebPort (log: $logFile)"

    # Kill anything on the port first
    Stop-PortListener -Port $WebPort
    Start-Sleep -Seconds 1

    $script:WebProcess = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', "cd /d `"$(Join-Path $RepoRoot 'apps\web')`" && npx next dev --port $WebPort" `
        -WorkingDirectory (Join-Path $RepoRoot 'apps\web') `
        -PassThru `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError "$logFile.err" `
        -WindowStyle Hidden

    Write-Log 'OK' "Web Frontend started (PID $($script:WebProcess.Id))"
}

# ── Banner ─────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '╔══════════════════════════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host '║          CareerOS Dev Watchdog — Process Supervisor         ║' -ForegroundColor Cyan
Write-Host '╠══════════════════════════════════════════════════════════════╣' -ForegroundColor Cyan
Write-Host "║  Backend API:   http://localhost:$ApiPort                        ║" -ForegroundColor Cyan
Write-Host "║  Web Frontend:  http://localhost:$WebPort                        ║" -ForegroundColor Cyan
Write-Host "║  Poll interval: ${PollInterval}s | Max restarts: $MaxRestarts | Cooldown: ${CooldownSec}s  ║" -ForegroundColor Cyan
Write-Host '║  Press Ctrl+C to stop the watchdog and all services.       ║' -ForegroundColor Cyan
Write-Host '╚══════════════════════════════════════════════════════════════╝' -ForegroundColor Cyan
Write-Host ''

# ── Initial launch ────────────────────────────────────────────────────
Start-ApiServer
Start-Sleep -Seconds 3
Start-WebServer
Start-Sleep -Seconds 5

Write-Log 'OK' 'Initial launch complete. Entering watchdog loop...'
Write-Host ''

# ── Main watchdog loop ─────────────────────────────────────────────────
try {
    while ($true) {
        $now = Get-Date

        # ── Check Backend API ──
        $apiAlive = Test-ServiceAlive "$apiUrl/health"
        if (-not $apiAlive) {
            # Double-check: maybe the health endpoint isn't set up, try root
            $apiAlive = Test-ServiceAlive "$apiUrl/"
        }

        if (-not $apiAlive) {
            if ($now -lt $script:ApiCooldownUntil) {
                # In cooldown — don't restart yet
            } else {
                $script:ApiRestarts++
                if ($script:ApiRestarts -gt $MaxRestarts) {
                    Write-Log 'ERROR' "Backend API crashed $MaxRestarts times. Cooling down for ${CooldownSec}s..."
                    $script:ApiCooldownUntil = $now.AddSeconds($CooldownSec)
                    $script:ApiRestarts = 0
                } else {
                    Write-Log 'WARN' "Backend API not responding (restart $($script:ApiRestarts)/$MaxRestarts)"
                    Start-ApiServer
                    Start-Sleep -Seconds 5
                }
            }
        } else {
            if ($script:ApiRestarts -gt 0) {
                Write-Log 'OK' 'Backend API recovered!'
            }
            $script:ApiRestarts = 0
        }

        # ── Check Web Frontend ──
        $webAlive = Test-ServiceAlive "$webUrl/"
        if (-not $webAlive) {
            if ($now -lt $script:WebCooldownUntil) {
                # In cooldown
            } else {
                $script:WebRestarts++
                if ($script:WebRestarts -gt $MaxRestarts) {
                    Write-Log 'ERROR' "Web Frontend crashed $MaxRestarts times. Cooling down for ${CooldownSec}s..."
                    $script:WebCooldownUntil = $now.AddSeconds($CooldownSec)
                    $script:WebRestarts = 0
                } else {
                    Write-Log 'WARN' "Web Frontend not responding (restart $($script:WebRestarts)/$MaxRestarts)"
                    Start-WebServer
                    Start-Sleep -Seconds 5
                }
            }
        } else {
            if ($script:WebRestarts -gt 0) {
                Write-Log 'OK' 'Web Frontend recovered!'
            }
            $script:WebRestarts = 0
        }

        Start-Sleep -Seconds $PollInterval
    }
} finally {
    Write-Host ''
    Write-Log 'INFO' 'Watchdog shutting down — stopping services...'

    if ($script:ApiProcess -and -not $script:ApiProcess.HasExited) {
        Stop-Process -Id $script:ApiProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Log 'INFO' "Stopped Backend API (PID $($script:ApiProcess.Id))"
    }
    if ($script:WebProcess -and -not $script:WebProcess.HasExited) {
        Stop-Process -Id $script:WebProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Log 'INFO' "Stopped Web Frontend (PID $($script:WebProcess.Id))"
    }

    # Cleanup any remaining listeners
    Stop-PortListener -Port $ApiPort
    Stop-PortListener -Port $WebPort

    Write-Log 'OK' 'All services stopped. Goodbye.'
}
