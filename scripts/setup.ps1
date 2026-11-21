# ClipStudio — Environment and Dependency Setup Script (Windows)
$ErrorActionPreference = "Stop"

$Root = "D:\dharmendra\clipstudio"
$BackendDir = Join-Path $Root "clipstudio-backend"
$FrontendDir = Join-Path $Root "clipstudio-frontend"

Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  ClipStudio - Environment & Dependency Setup" -ForegroundColor Cyan
Write-Host "  Target: $Root" -ForegroundColor DarkGray
Write-Host "==============================================================================" -ForegroundColor DarkGray

# 1. Verify Python
Write-Host "[*] Checking Python 3.10+..." -ForegroundColor Cyan
$pyVer = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] ERROR: Python is not found in PATH." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Detected $pyVer" -ForegroundColor Green

# 2. Verify Node.js & npm
Write-Host "[*] Checking Node.js & npm..." -ForegroundColor Cyan
$nodeVer = node --version 2>&1
if ($LASTEXITCODE -ne 0) {
    if (Test-Path "C:\Program Files\nodejs\node.exe") {
        $env:PATH = "C:\Program Files\nodejs;$env:PATH"
        $nodeVer = node --version 2>&1
    } else {
        Write-Host "[!] ERROR: Node.js is not found in PATH." -ForegroundColor Red
        exit 1
    }
}
$npmVer = npm --version 2>&1
Write-Host "[OK] Detected Node.js $nodeVer (npm v$npmVer)" -ForegroundColor Green

# 3. Virtual Environment
Write-Host "[*] Checking Python virtual environment..." -ForegroundColor Cyan
$venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (!(Test-Path $venvPython)) {
    Write-Host "[*] Creating virtual environment at $BackendDir\.venv..." -ForegroundColor Cyan
    python -m venv (Join-Path $BackendDir ".venv")
    Write-Host "[OK] Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "[OK] Virtual environment already exists." -ForegroundColor Green
}

# 4. Backend Dependencies
Write-Host "[*] Installing backend dependencies..." -ForegroundColor Cyan
& (Join-Path $BackendDir ".venv\Scripts\pip.exe") install -r (Join-Path $BackendDir "requirements.txt")
Write-Host "[OK] Backend dependencies installed." -ForegroundColor Green

# 5. Database Migrations
Write-Host "[*] Running Alembic database migrations..." -ForegroundColor Cyan
Push-Location $BackendDir
& ".\.venv\Scripts\alembic.exe" upgrade head
Pop-Location
Write-Host "[OK] Database migrations completed." -ForegroundColor Green

# 6. Frontend Dependencies
Write-Host "[*] Installing frontend npm packages..." -ForegroundColor Cyan
Push-Location $FrontendDir
& npm.cmd install
Pop-Location
Write-Host "[OK] Frontend packages installed." -ForegroundColor Green

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  [SUCCESS] ClipStudio environment setup completed successfully!" -ForegroundColor Green
Write-Host "  You can now start ClipStudio by running:" -ForegroundColor White
Write-Host "    start_clipstudio.bat" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor DarkGray
