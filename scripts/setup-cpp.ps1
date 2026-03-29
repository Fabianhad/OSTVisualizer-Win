Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CppDir = Join-Path $ProjectRoot 'cpp_extensions'

Write-Host "OST Visualizer - C++ Extensions Setup" -ForegroundColor Cyan

# =============================================================================
# Check prerequisites
# =============================================================================

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: CMake not found in PATH." -ForegroundColor Red
    exit 1
}
Write-Host "  CMake: $(cmake --version | Select-Object -First 1)" -ForegroundColor Green

# =============================================================================
# Download PDFium
# =============================================================================

$PdfiumDir = Join-Path $CppDir 'pdfium'

if (Test-Path $PdfiumDir) {
    Write-Host "PDFium already present, skipping download." -ForegroundColor Green
} else {
    Write-Host "Downloading PDFium..." -ForegroundColor Yellow

    $PdfiumUrl = "https://github.com/bblanchon/pdfium-binaries/releases/latest/download/pdfium-win-x64.tgz"
    $PdfiumArchive = Join-Path $env:TEMP 'pdfium-win-x64.tgz'

    & curl.exe -L --fail -o $PdfiumArchive $PdfiumUrl
    if ($LASTEXITCODE -ne 0) { throw "Failed to download PDFium" }

    New-Item -ItemType Directory -Path $PdfiumDir -Force | Out-Null
    tar -xzf $PdfiumArchive -C $PdfiumDir
    Remove-Item $PdfiumArchive -Force

    # Rename pdfium.dll.lib to pdfium.lib (CMakeLists expects pdfium.lib)
    $DllLib = Join-Path $PdfiumDir 'lib\pdfium.dll.lib'
    if (Test-Path $DllLib) {
        Rename-Item $DllLib 'pdfium.lib'
    }

    Write-Host "  PDFium downloaded to $PdfiumDir" -ForegroundColor Green
}

# =============================================================================
# Download QPDF
# =============================================================================

$QpdfVersion = '12.3.2'
$QpdfDirName = "qpdf-$QpdfVersion-msvc64"
$QpdfDir = Join-Path $CppDir $QpdfDirName

if (Test-Path $QpdfDir) {
    Write-Host "QPDF already present, skipping download." -ForegroundColor Green
} else {
    Write-Host "Downloading QPDF $QpdfVersion..." -ForegroundColor Yellow

    $QpdfUrl = "https://github.com/qpdf/qpdf/releases/download/v$QpdfVersion/$QpdfDirName.zip"
    $QpdfArchive = Join-Path $env:TEMP "$QpdfDirName.zip"

    & curl.exe -L --fail -o $QpdfArchive $QpdfUrl
    if ($LASTEXITCODE -ne 0) { throw "Failed to download QPDF" }

    Expand-Archive -Path $QpdfArchive -DestinationPath $CppDir -Force
    Remove-Item $QpdfArchive -Force

    # Remove MSVC runtime DLLs (available on any dev machine)
    $QpdfBin = Join-Path $QpdfDir 'bin'
    Get-ChildItem $QpdfBin -Filter 'concrt140*.dll' | Remove-Item -Force
    Get-ChildItem $QpdfBin -Filter 'msvcp140*.dll' | Remove-Item -Force
    Get-ChildItem $QpdfBin -Filter 'vcruntime140*.dll' | Remove-Item -Force

    Write-Host "  QPDF downloaded to $QpdfDir" -ForegroundColor Green
}

# =============================================================================
# Build C++ extensions
# =============================================================================

Write-Host "Building C++ extensions..." -ForegroundColor Yellow

$BuildDir = Join-Path $CppDir 'build'
if (-not (Test-Path $BuildDir)) {
    New-Item -ItemType Directory -Path $BuildDir | Out-Null
}

Push-Location $BuildDir
try {
    $CMakeArgs = @('..', '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5')
    if ($env:PROCESSOR_ARCHITECTURE -eq 'AMD64') {
        $CMakeArgs += '-A', 'x64'
    }

    cmake @CMakeArgs
    if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed' }

    cmake --build . --config Release --parallel
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }

    Write-Host "C++ extensions built successfully." -ForegroundColor Green
} finally {
    Pop-Location
}
