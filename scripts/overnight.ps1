#Requires -Version 5.1
# Overnight loops (supervisor + improver). See docs/overnight-loops.md.
#   scripts/overnight.ps1 start | stop [-Now] | resume | status | report | groups | promote | mark-live <branch>
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("start", "stop", "resume", "status", "report", "groups", "promote", "mark-live",
                 "supervise-once", "improve-once")]
    [string]$Command,
    [Parameter(Position = 1)][string]$Branch,
    [switch]$Now,
    [switch]$AutoStart,
    [string]$Note = "",
    [string]$Database,
    [double]$Interval = 30
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ApiDir = Join-Path $RepoRoot "apps\api"

function Get-ApiPython {
    $venvPy = Join-Path $ApiDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    foreach ($cmd in @("python", "py")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { return $cmd }
    }
    throw "Python not found. Run scripts/setup.ps1 first."
}

$argv = @("-m", "app.services.overnight", "--interval", "$Interval")
if ($Database) { $argv += @("--db", $Database) }
if ($AutoStart) { $argv += "--auto-start" }
$argv += $Command
if ($Command -eq "stop" -and $Now) { $argv += "--now" }
if ($Command -eq "mark-live") {
    if (-not $Branch) { throw "mark-live needs the branch name of the fix that is now live." }
    $argv += @($Branch, "--note", $Note)
}

Push-Location $ApiDir
try {
    & (Get-ApiPython) @argv
    if ($LASTEXITCODE -ne 0) { throw "overnight $Command failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}
