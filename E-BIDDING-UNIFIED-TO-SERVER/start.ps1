# E-Bidding Unified - Start Script for Windows PowerShell
# This script creates and uses a virtual environment, then starts both backend and frontend servers

Write-Host "Starting E-Bidding Unified..." -ForegroundColor Green

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $scriptDir ".venv"

# Function to check if a command exists
function Test-CommandExists {
    param($command)
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'stop'
    try { if (Get-Command $command) { return $true } }
    catch { return $false }
    finally { $ErrorActionPreference = $oldPreference }
}

# Check Python availability
Write-Host "Checking Python availability..."
if (-not (Test-CommandExists python)) {
    Write-Host "Error: Python is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Check Node.js availability
Write-Host "Checking Node.js availability..."
if (-not (Test-CommandExists node)) {
    Write-Host "Error: Node.js is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Check npm availability
Write-Host "Checking npm availability..."
if (-not (Test-CommandExists npm)) {
    Write-Host "Error: npm is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Create virtual environment if it doesn't exist
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv $venvPath
    
    Write-Host "Installing backend requirements..." -ForegroundColor Cyan
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $scriptDir "backend\requirements.txt")
}

# Activate virtual environment
Write-Host "Activating virtual environment..."
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
& $activateScript

# Start backend
Write-Host "Starting backend server..." -ForegroundColor Cyan
Set-Location (Join-Path $scriptDir "backend")
uvicorn backend_server:app --host 127.0.0.1 --port 8000
Write-Host "Backend started: http://127.0.0.1:8000" -ForegroundColor Green
Start-Sleep -Seconds 5

# Start frontend using wrapper script
Write-Host "Starting frontend server..." -ForegroundColor Cyan
Set-Location (Join-Path $scriptDir "frontend")
.\start-frontend.ps1
Write-Host "Frontend started: http://localhost:8080" -ForegroundColor Green
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "Both servers are running!" -ForegroundColor Green
Write-Host "  Backend:  http://127.0.0.1:8000"
Write-Host "  Frontend: http://localhost:8080"
Write-Host ""
Write-Host "Press Ctrl+C to stop all servers"
