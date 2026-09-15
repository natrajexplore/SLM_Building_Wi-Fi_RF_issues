# Starts the portable PostgreSQL instance (if not already running) and then
# the FastAPI backend on :8090. PostgreSQL isn't a Windows service here -
# see CLAUDE.md - so it has to be brought up manually every session; this
# folds that step into one command instead of two.

param(
    [switch]$Lan  # bind 0.0.0.0 instead of 127.0.0.1, for a real ESP32 board on the LAN
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pgCtl = Join-Path $repoRoot ".local/postgres/bin/pg_ctl.exe"
$pgData = Join-Path $repoRoot ".local/postgres/data"
$pgLog = Join-Path $repoRoot ".local/postgres/logs.log"

if (Test-Path $pgCtl) {
    & $pgCtl -D $pgData status | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Starting PostgreSQL..."
        & $pgCtl -D $pgData -l $pgLog `
            -o "-c shared_buffers=32MB -c max_connections=20 -c listen_addresses=127.0.0.1 -p 5432" `
            start
    } else {
        Write-Host "PostgreSQL already running."
    }
} else {
    Write-Host "No portable PostgreSQL at $pgCtl - skipping (Submit/Ask will run with stored: false)."
}

Set-Location $repoRoot
$bindHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
uvicorn backend.main:app --reload --host $bindHost --port 8090
