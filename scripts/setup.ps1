Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot 'venv'

Write-Host "OST Visualizer - Python Setup" -ForegroundColor Cyan

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Python not found in PATH." -ForegroundColor Red
    exit 1
}

$PythonVersion = python --version 2>&1
Write-Host "  Python: $PythonVersion" -ForegroundColor Green

# Create venv
if (-not (Test-Path $VenvPath)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv $VenvPath
}
else {
    Write-Host "Virtual environment already exists." -ForegroundColor Green
}

# Activate and install
$ActivateScript = Join-Path $VenvPath 'Scripts\Activate.ps1'
. $ActivateScript

Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
pip install -r (Join-Path $ProjectRoot 'requirements.txt') --quiet

Write-Host "Python setup complete." -ForegroundColor Green
