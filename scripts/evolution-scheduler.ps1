param(
    [int]$IntervalSeconds = 1800,
    [int]$MaxIterations = 0,
    [string]$RepoPath = ( (Get-Location).Path ),
    [string]$LogPath = "$env:TEMP\opencode\evolution-scheduler.log",
    [switch]$Force
)

$ErrorActionPreference = "Continue"
$Node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $Node) { throw "node not found on PATH" }
$Engine = Join-Path $HOME "agent-skills\nightly-evolution\scripts\evolve.mjs"
if (-not (Test-Path $Engine)) { throw "evolve.mjs not found: $Engine" }

$LogDir = Split-Path -Parent $LogPath
if ($LogDir) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

function Write-Log([string]$line) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $msg = "[$stamp] $line"
    $msg | Tee-Object -FilePath $LogPath -Append | Out-Null
    Write-Output $msg
}

$iteration = 0
Write-Log "Evolution scheduler started. interval=${IntervalSeconds}s force=$($Force.IsPresent) repo=$RepoPath"

while ($true) {
    $iteration++
    Write-Log "AGENT_LOOP_TICK_evolution iteration=$iteration"
    $args = @($Engine, "tick", "--repo", $RepoPath, "--agent", "evolution-scheduler")
    if ($Force) { $args += "--force" }
    Write-Log "Running: node $($args -join ' ')"
    try {
        & $Node @args 2>&1 | ForEach-Object {
            $_ | Tee-Object -FilePath $LogPath -Append | Out-Null
        }
        $exit = $LASTEXITCODE
        Write-Log "Tick iteration=$iteration exit=$exit"
    } catch {
        Write-Log "Tick iteration=$iteration error: $($_.Exception.Message)"
    }

    if ($MaxIterations -gt 0 -and $iteration -ge $MaxIterations) {
        Write-Log "MaxIterations ($MaxIterations) reached; scheduler stopping."
        break
    }
    Write-Log "Sleeping ${IntervalSeconds}s before next iteration."
    Start-Sleep -Seconds $IntervalSeconds
}