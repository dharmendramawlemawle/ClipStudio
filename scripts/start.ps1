# ClipStudio — Service Startup Script (Windows)
$ErrorActionPreference = "Stop"

$Root = "D:\dharmendra\clipstudio"
$BackendDir = Join-Path $Root "clipstudio-backend"
$FrontendDir = Join-Path $Root "clipstudio-frontend"
$LogsDir = Join-Path $Root "logs"
$DataDir = Join-Path $Root "data"

if (!(Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir | Out-Null }
if (!(Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }

Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  ClipStudio - Starting Application Services" -ForegroundColor Cyan
Write-Host "  Directory: $Root" -ForegroundColor DarkGray
Write-Host "==============================================================================" -ForegroundColor DarkGray

# 1. Start FastAPI Backend
$backendConn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($backendConn) {
    Write-Host "[!] Backend is already running on port 8000 (PID: $($backendConn.OwningProcess))." -ForegroundColor Yellow
} else {
    Write-Host "[*] Starting FastAPI Backend on http://127.0.0.1:8000..." -ForegroundColor Cyan
    $pythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
    if (!(Test-Path $pythonExe)) {
        Write-Host "[!] Python venv not found at $pythonExe. Run setup_clipstudio.bat first." -ForegroundColor Red
        exit 1
    }

    $backendOut = Join-Path $LogsDir "backend.log"
    $backendErr = Join-Path $LogsDir "backend_err.log"

    $backendProc = Start-Process -FilePath $pythonExe `
        -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 2
    $backendProc.Id | Out-File (Join-Path $DataDir "backend.pid") -Encoding ascii
    Write-Host "[OK] Backend service started (PID: $($backendProc.Id))." -ForegroundColor Green
}

# 2. Start React Studio Frontend
$frontendConn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if ($frontendConn) {
    Write-Host "[!] Frontend is already running on port 5173 (PID: $($frontendConn.OwningProcess))." -ForegroundColor Yellow
} else {
    Write-Host "[*] Starting React Studio Frontend on http://localhost:5173..." -ForegroundColor Cyan
    $frontendOut = Join-Path $LogsDir "frontend.log"
    $frontendErr = Join-Path $LogsDir "frontend_err.log"

    # Resolve Node.js installation directory safely and dynamically
    $nodeDir = $null
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($nodeCommand -and $nodeCommand.Source) {
        $nodeDir = Split-Path -Parent $nodeCommand.Source
    }

    if (-not $nodeDir) {
        $candidatePaths = @(
            "C:\Program Files\nodejs",
            "C:\Program Files (x86)\nodejs",
            "$env:LOCALAPPDATA\Programs\nodejs",
            "$env:ProgramFiles\nodejs"
        )
        foreach ($cand in $candidatePaths) {
            if ($cand -and (Test-Path (Join-Path $cand "node.exe"))) {
                $nodeDir = $cand
                break
            }
        }
    }

    if (-not $nodeDir) {
        Write-Host "[!] ERROR: Node.js could not be located in PATH or standard installation directories." -ForegroundColor Red
        Write-Host "    Please ensure Node.js LTS is installed and node.exe is accessible." -ForegroundColor Red
        exit 1
    }

    # Ensure $nodeDir is included in PATH if not already present
    $pathParts = $env:PATH -split [System.IO.Path]::PathSeparator
    $isNodeInPath = $false
    foreach ($part in $pathParts) {
        if ($part.TrimEnd('\') -ieq $nodeDir.TrimEnd('\')) {
            $isNodeInPath = $true
            break
        }
    }
    if (-not $isNodeInPath) {
        $env:PATH = "$nodeDir" + [System.IO.Path]::PathSeparator + $env:PATH
    }

    # Resolve npm executable safely
    $npmPath = Join-Path $nodeDir "npm.cmd"
    if (-not (Test-Path $npmPath)) {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($npmCommand -and $npmCommand.Source) {
            $npmPath = $npmCommand.Source
        } else {
            Write-Host "[!] ERROR: npm.cmd could not be located in '$nodeDir' or PATH." -ForegroundColor Red
            exit 1
        }
    }

    # Spawn frontend with guaranteed PATH inheritance
    $frontendArg = "/c set `"PATH=$env:PATH`" && `"$npmPath`" run dev"
    $frontendProc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList $frontendArg `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr `
        -WindowStyle Hidden `
        -PassThru


    Start-Sleep -Seconds 3
    $frontendProc.Id | Out-File (Join-Path $DataDir "frontend.pid") -Encoding ascii
    Write-Host "[OK] Frontend service started (PID: $($frontendProc.Id))." -ForegroundColor Green
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  ClipStudio Services Are Active" -ForegroundColor Green
Write-Host ""
Write-Host "    Frontend Studio URL : http://localhost:5173" -ForegroundColor White
Write-Host "    Backend REST API    : http://127.0.0.1:8000" -ForegroundColor White
Write-Host "    API Documentation   : http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "    Real-time WebSocket : ws://127.0.0.1:8000/ws/events" -ForegroundColor White
Write-Host ""
Write-Host "    Logs Directory      : $LogsDir" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  To stop services safely, run: stop_clipstudio.bat" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor DarkGray
