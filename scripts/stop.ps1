# ClipStudio — Safe Service Shutdown Script (Windows)
param(
    [string]$Root = "D:\dharmendra\clipstudio",
    [string]$DataDir = "",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

if (-not $DataDir) {
    $DataDir = Join-Path $Root "data"
}

$ErrorActionPreference = "SilentlyContinue"
$failureCount = 0

Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  ClipStudio - Stopping Application Services" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor DarkGray

function Stop-ClipStudioProcess {
    param(
        [int]$ProcessId,
        [string]$Description
    )
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) {
        # Already stopped or does not exist - expected condition, NOT a failure
        return $true
    }

    Write-Host "[*] Terminating $Description (PID: $ProcessId)..." -ForegroundColor Cyan
    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    } catch {
        Write-Host "[!] Failed to terminate $Description (PID: $ProcessId): $_" -ForegroundColor Red
        return $false
    }

    # Verify process terminated
    $stopped = $proc.WaitForExit(3000)
    if (-not $stopped) {
        $checkProc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($checkProc) {
            Write-Host "[!] $Description (PID: $ProcessId) did not terminate within timeout." -ForegroundColor Red
            return $false
        }
    }

    Write-Host "[OK] $Description stopped." -ForegroundColor Green
    return $true
}

function Get-PortListenerPids {
    param([int]$Port)
    $pids = @()
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            foreach ($c in $conns) {
                if ($c.OwningProcess -and $c.OwningProcess -gt 0) {
                    $pids += [int]$c.OwningProcess
                }
            }
        }
    } catch {
        try {
            $netstatOutput = netstat -ano -p tcp | Select-String ":$Port\s+.*LISTENING"
            foreach ($line in $netstatOutput) {
                $parts = ($line.ToString().Trim() -split '\s+')
                if ($parts.Length -ge 5) {
                    $p = $parts[-1] -as [int]
                    if ($p -and $p -gt 0) {
                        $pids += $p
                    }
                }
            }
        } catch {}
    }
    return ($pids | Select-Object -Unique)
}

function Free-PortListener {
    param(
        [int]$Port,
        [string]$Description
    )
    $pids = Get-PortListenerPids -Port $Port
    if (-not $pids -or $pids.Count -eq 0) {
        return $true
    }

    $allFreed = $true
    foreach ($p in $pids) {
        Write-Host "[*] Freeing residual listener on port $Port (PID: $p)..." -ForegroundColor Cyan
        try {
            Stop-Process -Id $p -Force -ErrorAction Stop
            $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
            if ($proc) {
                $null = $proc.WaitForExit(3000)
            }
            Write-Host "[OK] $Description stopped." -ForegroundColor Green
        } catch {
            Write-Host "[!] Failed to terminate listener on port $Port (PID: $p): $_" -ForegroundColor Red
            $allFreed = $false
        }
    }

    Start-Sleep -Milliseconds 300
    $remaining = Get-PortListenerPids -Port $Port
    if ($remaining -and $remaining.Count -gt 0) {
        Write-Host "[!] Port $Port remains occupied by PID(s): $($remaining -join ', ')" -ForegroundColor Red
        return $false
    }
    return $allFreed
}

function Remove-PidFileSafely {
    param([string]$FilePath)
    if (Test-Path $FilePath) {
        try {
            Remove-Item $FilePath -Force -ErrorAction Stop
            return $true
        } catch {
            Write-Host "[!] Failed to remove PID file '$FilePath': $_" -ForegroundColor Red
            return $false
        }
    }
    return $true
}

# 1. Stop Backend
$backendPidFile = Join-Path $DataDir "backend.pid"
if (Test-Path $backendPidFile) {
    $rawPid = (Get-Content $backendPidFile -ErrorAction SilentlyContinue | Out-String).Trim()
    $backendPid = $rawPid -as [int]
    if ($backendPid -and $backendPid -gt 0) {
        $backendStopped = Stop-ClipStudioProcess -ProcessId $backendPid -Description "ClipStudio Backend"
        if (-not $backendStopped) {
            $failureCount++
        }
    }
    $cleaned = Remove-PidFileSafely -FilePath $backendPidFile
    if (-not $cleaned) {
        $failureCount++
    }
}

# Ensure port 8000 is freed
$port8000Clean = Free-PortListener -Port $BackendPort -Description "ClipStudio Backend"
if (-not $port8000Clean) {
    $failureCount++
}

# 2. Stop Frontend
$frontendPidFile = Join-Path $DataDir "frontend.pid"
if (Test-Path $frontendPidFile) {
    $rawPid = (Get-Content $frontendPidFile -ErrorAction SilentlyContinue | Out-String).Trim()
    $frontendPid = $rawPid -as [int]
    if ($frontendPid -and $frontendPid -gt 0) {
        $frontendStopped = Stop-ClipStudioProcess -ProcessId $frontendPid -Description "ClipStudio Frontend wrapper"
        if (-not $frontendStopped) {
            $failureCount++
        }
    }
    $cleaned = Remove-PidFileSafely -FilePath $frontendPidFile
    if (-not $cleaned) {
        $failureCount++
    }
}

# Ensure port 5173 is freed (Node.js child of cmd.exe)
$port5173Clean = Free-PortListener -Port $FrontendPort -Description "Frontend"
if (-not $port5173Clean) {
    $failureCount++
}

Write-Host ""
if ($failureCount -eq 0) {
    Write-Host "==============================================================================" -ForegroundColor DarkGray
    Write-Host "  [SUCCESS] All ClipStudio services have been stopped safely." -ForegroundColor Green
    Write-Host "  SQLite database and persistent job records remain completely intact." -ForegroundColor DarkGray
    Write-Host "==============================================================================" -ForegroundColor DarkGray
    exit 0
} else {
    Write-Host "==============================================================================" -ForegroundColor DarkGray
    Write-Host "  [!] ERROR: Failed to cleanly stop all services ($failureCount failure(s) recorded)." -ForegroundColor Red
    Write-Host "==============================================================================" -ForegroundColor DarkGray
    exit 1
}
