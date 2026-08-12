Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CppDir = Join-Path $ProjectRoot 'cpp_extensions'
Import-Module (Join-Path $PSScriptRoot 'native-dependency-install.psm1') -Force

function Invoke-VerifiedDownload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256
    )

    try {
        & curl.exe -L --fail --output $Destination $Url
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to download $Url"
        }

        $ActualSha256 = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if (-not $ActualSha256.Equals($ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)) {
            throw "SHA-256 mismatch for $Url (expected $ExpectedSha256, got $ActualSha256)"
        }
    }
    catch {
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        throw
    }
}

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
$PdfiumVersion = '146.0.7651.0'
$PdfiumReleaseTag = 'chromium/7651'
$PdfiumSha256 = '17c2f2fdb09607163304b19ee5724ac0ea71d244cd74c45d3a8e524396357f59'

if (Test-Path $PdfiumDir) {
    Assert-PdfiumInstallation -Directory $PdfiumDir -ExpectedVersion $PdfiumVersion
    Write-Host "PDFium $PdfiumVersion already present and verified." -ForegroundColor Green
}
else {
    Write-Host "Downloading PDFium $PdfiumVersion..." -ForegroundColor Yellow

    $PdfiumUrl = "https://github.com/bblanchon/pdfium-binaries/releases/download/$PdfiumReleaseTag/pdfium-win-x64.tgz"
    $PdfiumArchive = Join-Path $env:TEMP "pdfium-$PdfiumVersion-win-x64.tgz"

    Invoke-VerifiedDownload -Url $PdfiumUrl -Destination $PdfiumArchive -ExpectedSha256 $PdfiumSha256

    try {
        Install-NativeDependencyDirectory `
            -FinalDirectory $PdfiumDir `
            -PrepareDirectory {
                param($StagingDirectory)
                tar -xzf $PdfiumArchive -C $StagingDirectory
                if ($LASTEXITCODE -ne 0) { throw 'Failed to extract PDFium' }
                $DllLib = Join-Path $StagingDirectory 'lib\pdfium.dll.lib'
                if (Test-Path -LiteralPath $DllLib) {
                    Rename-Item -LiteralPath $DllLib -NewName 'pdfium.lib'
                }
                return $StagingDirectory
            } `
            -ValidateDirectory {
                param($Directory)
                Assert-PdfiumInstallation `
                    -Directory $Directory `
                    -ExpectedVersion $PdfiumVersion
            } | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $PdfiumArchive -Force -ErrorAction SilentlyContinue
    }

    Write-Host "  PDFium downloaded to $PdfiumDir" -ForegroundColor Green
}

# =============================================================================
# Download QPDF
# =============================================================================

$QpdfVersion = '12.3.2'
$QpdfSha256 = '8941870a604e7c87ed24566b038d46c24ce76616254d2383c578f60c0677f202'
$QpdfDirName = "qpdf-$QpdfVersion-msvc64"
$QpdfDir = Join-Path $CppDir $QpdfDirName

if (Test-Path $QpdfDir) {
    Assert-QpdfInstallation -Directory $QpdfDir -ExpectedVersion $QpdfVersion
    Write-Host "QPDF $QpdfVersion already present and verified." -ForegroundColor Green
}
else {
    Write-Host "Downloading QPDF $QpdfVersion..." -ForegroundColor Yellow

    $QpdfUrl = "https://github.com/qpdf/qpdf/releases/download/v$QpdfVersion/$QpdfDirName.zip"
    $QpdfArchive = Join-Path $env:TEMP "$QpdfDirName.zip"

    Invoke-VerifiedDownload -Url $QpdfUrl -Destination $QpdfArchive -ExpectedSha256 $QpdfSha256

    try {
        Install-NativeDependencyDirectory `
            -FinalDirectory $QpdfDir `
            -PrepareDirectory {
                param($StagingDirectory)
                Expand-Archive `
                    -LiteralPath $QpdfArchive `
                    -DestinationPath $StagingDirectory
                $PreparedDirectory = Join-Path $StagingDirectory $QpdfDirName
                $QpdfBin = Join-Path $PreparedDirectory 'bin'
                Get-ChildItem $QpdfBin -Filter 'concrt140*.dll' | Remove-Item -Force
                Get-ChildItem $QpdfBin -Filter 'msvcp140*.dll' | Remove-Item -Force
                Get-ChildItem $QpdfBin -Filter 'vcruntime140*.dll' | Remove-Item -Force
                return $PreparedDirectory
            } `
            -ValidateDirectory {
                param($Directory)
                Assert-QpdfInstallation `
                    -Directory $Directory `
                    -ExpectedVersion $QpdfVersion
            } | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $QpdfArchive -Force -ErrorAction SilentlyContinue
    }

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
}
finally {
    Pop-Location
}
