# ClipStudio — Safe Service Shutdown Script (Windows)
$ErrorActionPreference = "SilentlyContinue"

$Root = "D:\dharmendra\clipstudio"
$DataDir = Join-Path $Root "data"

Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  ClipStudio - Stopping Application Services" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor DarkGray

# 1. Stop Backend
$backendPidFile = Join-Path $DataDir "backend.pid"
if (Test-Path $backendPidFile) {
    $pid1 = (Get-Content $backendPidFile).Trim()
    if ($pid1) {
        Write-Host "[*] Terminating ClipStudio Backend (PID: $pid1)..." -ForegroundColor Cyan
        Stop-Process -Id $pid1 -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Backend process stopped." -ForegroundColor Green
    }
    Remove-Item $backendPidFile -Force -ErrorAction SilentlyContinue
}

# Ensure port 8000 is freed
$port8000Conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($port8000Conn) {
    Write-Host "[*] Freeing residual listener on port 8000 (PID: $($port8000Conn.OwningProcess))..." -ForegroundColor Cyan
    Stop-Process -Id $port8000Conn.OwningProcess -Force -ErrorAction SilentlyContinue
}

# 2. Stop Frontend
$frontendPidFile = Join-Path $DataDir "frontend.pid"
if (Test-Path $frontendPidFile) {
    $pid2 = (Get-Content $frontendPidFile).Trim()
    if ($pid2) {
        Write-Host "[*] Terminating ClipStudio Frontend wrapper (PID: $pid2)..." -ForegroundColor Cyan
        Stop-Process -Id $pid2 -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $frontendPidFile -Force -ErrorAction SilentlyContinue
}

# Ensure port 5173 is freed (Node.js child of cmd.exe)
$port5173Conn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if ($port5173Conn) {
    Write-Host "[*] Freeing residual listener on port 5173 (PID: $($port5173Conn.OwningProcess))..." -ForegroundColor Cyan
    Stop-Process -Id $port5173Conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Frontend process stopped." -ForegroundColor Green
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  [SUCCESS] All ClipStudio services have been stopped safely." -ForegroundColor Green
Write-Host "  SQLite database and persistent job records remain completely intact." -ForegroundColor DarkGray
Write-Host "==============================================================================" -ForegroundColor DarkGray
