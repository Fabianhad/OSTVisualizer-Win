Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot 'venv'
$ActivateScript = Join-Path $VenvPath 'Scripts\Activate.ps1'
$RequirementsPath = Join-Path $ProjectRoot 'requirements-mcp.txt'

Write-Host "OST Visualizer - MCP Setup" -ForegroundColor Cyan

if (-not (Test-Path $ActivateScript)) {
    Write-Host "ERROR: Virtual environment not found. Run scripts\setup.ps1 first." -ForegroundColor Red
    exit 1
}

. $ActivateScript

$VersionText = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$Version = [version]$VersionText
if ($Version -lt [version]'3.10') {
    Write-Host "ERROR: MCP SDK requires Python 3.10 or newer. Current Python: $VersionText" -ForegroundColor Red
    exit 1
}

Write-Host "Installing MCP dependencies..." -ForegroundColor Yellow
python -m pip install -r $RequirementsPath --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install MCP dependencies." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "MCP setup complete." -ForegroundColor Green
