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
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue

# Filter out 0-byte WindowsApps Store stubs if present
if ($pythonCommand -and (Test-Path $pythonCommand.Source)) {
    $fileItem = Get-Item $pythonCommand.Source -ErrorAction SilentlyContinue
    if ($fileItem -and $fileItem.Length -eq 0) {
        $pythonCommand = $null
    }
}

if (-not $pythonCommand) {
    Write-Host "[!] ERROR: Python 3.10+ is not found in PATH." -ForegroundColor Red
    Write-Host "    Please ensure Python 3.10 or newer is installed and added to PATH." -ForegroundColor Red
    exit 1
}

try {
    $pyVer = & $pythonCommand.Source --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $pyVer) {
        throw "python.exe exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host "[!] ERROR: Failed to execute python.exe at '$($pythonCommand.Source)'." -ForegroundColor Red
    Write-Host "    Please ensure Python is working and accessible." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Detected $pyVer" -ForegroundColor Green

# 2. Verify Node.js & npm
Write-Host "[*] Checking Node.js & npm..." -ForegroundColor Cyan

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

# Validate node.exe execution
$nodeExe = Join-Path $nodeDir "node.exe"
if (-not (Test-Path $nodeExe)) {
    Write-Host "[!] ERROR: node.exe was not found at '$nodeExe'." -ForegroundColor Red
    exit 1
}
try {
    $nodeVer = & $nodeExe --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $nodeVer) {
        throw "node.exe exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host "[!] ERROR: Failed to execute node.exe at '$nodeExe'." -ForegroundColor Red
    exit 1
}

# Resolve npm executable safely
$npmPath = Join-Path $nodeDir "npm.cmd"
if (-not (Test-Path $npmPath)) {
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCommand -and $npmCommand.Source) {
        $npmPath = $npmCommand.Source
    } else {
        Write-Host "[!] ERROR: npm.cmd could not be located in '$nodeDir' or PATH." -ForegroundColor Red
        Write-Host "    Please ensure npm is installed alongside Node.js." -ForegroundColor Red
        exit 1
    }
}
try {
    $npmVer = & $npmPath --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $npmVer) {
        throw "npm exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host "[!] ERROR: Failed to execute npm at '$npmPath'." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Detected Node.js $nodeVer (npm v$npmVer)" -ForegroundColor Green

# 3. Virtual Environment
Write-Host "[*] Checking Python virtual environment..." -ForegroundColor Cyan
$venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (!(Test-Path $venvPython)) {
    Write-Host "[*] Creating virtual environment at $BackendDir\.venv..." -ForegroundColor Cyan
    & $pythonCommand.Source -m venv (Join-Path $BackendDir ".venv")
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
& $npmPath install
Pop-Location
Write-Host "[OK] Frontend packages installed." -ForegroundColor Green

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor DarkGray
Write-Host "  [SUCCESS] ClipStudio environment setup completed successfully!" -ForegroundColor Green
Write-Host "  You can now start ClipStudio by running:" -ForegroundColor White
Write-Host "    start_clipstudio.bat" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor DarkGray
