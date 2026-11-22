$ErrorActionPreference = "Stop"

Write-Host "=============================================================================="
Write-Host "  ClipStudio Phase 2B.2 Full Physical Acceptance & Verification Suite"
Write-Host "=============================================================================="

Set-Location "D:\dharmendra\clipstudio"

# Step 1: Pre-cleanup
Write-Host "[1/6] Ensuring clean initial state (running stop_clipstudio.bat)..."
cmd.exe /c stop_clipstudio.bat

# Step 2: Physical Start
Write-Host "[2/6] Executing start_clipstudio.bat..."
cmd.exe /c start_clipstudio.bat
$startExit = $LASTEXITCODE
Write-Host "start_clipstudio.bat exited with code: $startExit"
if ($startExit -ne 0) {
    Write-Host "[!] Start failed!" -ForegroundColor Red
    exit 1
}

# Step 3: Wait and probe backend and frontend
Write-Host "[3/6] Probing services until healthy..."
$healthy = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $backendCheck = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
        $frontendConn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
        if ($backendCheck -and $backendCheck.status -eq "ok" -and $frontendConn) {
            Write-Host "Services are listening and responsive (attempt $($i+1))! Backend status: $($backendCheck.status)" -ForegroundColor Green
            $healthy = $true
            break
        }
    } catch {
        # continue waiting
    }
}

if (-not $healthy) {
    Write-Host "[!] Timed out waiting for backend or frontend to become ready." -ForegroundColor Red
    cmd.exe /c stop_clipstudio.bat
    exit 1
}

# Step 4: Run Playwright Browser Acceptance Test
Write-Host "[4/6] Running physical browser acceptance testing with Playwright..."
$env:PATH = "C:\Program Files\nodejs;" + $env:PATH
Set-Location "D:\dharmendra\clipstudio\clipstudio-frontend"
node scripts/browser_acceptance_phase2b2.mjs
$browserExit = $LASTEXITCODE
Write-Host "Browser acceptance exited with code: $browserExit"

Set-Location "D:\dharmendra\clipstudio"

# Step 5: Physical Stop
Write-Host "[5/6] Executing stop_clipstudio.bat on running services..."
cmd.exe /c stop_clipstudio.bat
$stopExit = $LASTEXITCODE
Write-Host "stop_clipstudio.bat exited with code: $stopExit"

# Step 6: Idempotent Stop (already stopped)
Write-Host "[6/6] Executing stop_clipstudio.bat on ALREADY STOPPED services..."
cmd.exe /c stop_clipstudio.bat
$stopIdempotentExit = $LASTEXITCODE
Write-Host "stop_clipstudio.bat (idempotent) exited with code: $stopIdempotentExit"

Write-Host "=============================================================================="
Write-Host "  Summary of Physical Acceptance Verification"
Write-Host "    start_clipstudio.bat exit code         : $startExit"
Write-Host "    Browser Acceptance exit code           : $browserExit"
Write-Host "    stop_clipstudio.bat (active) exit code : $stopExit"
Write-Host "    stop_clipstudio.bat (idle) exit code   : $stopIdempotentExit"
Write-Host "=============================================================================="

if ($startExit -ne 0 -or $browserExit -ne 0 -or $stopExit -ne 0 -or $stopIdempotentExit -ne 0) {
    Write-Host "[!] One or more acceptance steps failed." -ForegroundColor Red
    exit 1
}

Write-Host "[SUCCESS] All physical scripts and browser acceptance tests PASSED!" -ForegroundColor Green
exit 0
