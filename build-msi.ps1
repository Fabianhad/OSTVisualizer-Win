Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host "OST Visualizer MSI Builder" -ForegroundColor Cyan

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Get-Location }
Write-Host "Script Directory: $ScriptDir" -ForegroundColor Gray

$ProjectsRoot = Split-Path -Parent $ScriptDir
$MSICreatorDir = Join-Path $ProjectsRoot 'msicreator-master'
$BuildOutputDir = Join-Path $ScriptDir 'dist_visualizer\Visualizer.dist'
$StagingDir = Join-Path $MSICreatorDir 'staging'
$ApplicationInfoFile = Join-Path $ScriptDir 'ost_visualizer\application\dtos\application_info.py'
$RepoMsiConfigFile = Join-Path $ScriptDir 'installer\ostvisualizer.json'
$JsonConfigFile = Join-Path $MSICreatorDir 'ostvisualizer.json'
$MSICreatorScript = Join-Path $MSICreatorDir 'createmsi.py'
$LicenseFile = Join-Path $MSICreatorDir 'License.rtf'

function Test-RegistryEntry {
    param(
        [Parameter(Mandatory = $true)] [object[]] $Entries,
        [Parameter(Mandatory = $true)] [string] $Root,
        [Parameter(Mandatory = $true)] [string] $Key,
        [AllowNull()] [object] $Name,
        [Parameter(Mandatory = $true)] [string] $Value
    )

    $ExpectedName = if ($null -eq $Name) { $null } else { [string]$Name }
    foreach ($Entry in $Entries) {
        $EntryName = if ($null -eq $Entry.name) { $null } else { [string]$Entry.name }
        if (
            $Entry.root -eq $Root -and
            $Entry.key -eq $Key -and
            $EntryName -eq $ExpectedName -and
            $Entry.value -eq $Value
        ) {
            return $true
        }
    }

    return $false
}

function Assert-MsiFileAssociationConfig {
    param([Parameter(Mandatory = $true)] [object] $Config)

    $Entries = @($Config.registry_entries)
    $RequiredEntries = @(
        @{ Root = 'HKLM'; Key = 'Software\Classes\.ost'; Name = $null; Value = 'OSTVisualizer.ost' },
        @{ Root = 'HKLM'; Key = 'Software\Classes\.osp'; Name = $null; Value = 'OSTVisualizer.osp' },
        @{ Root = 'HKLM'; Key = 'Software\Classes\OSTVisualizer.ost\shell\open\command'; Name = $null; Value = '"[INSTALLDIR]Visualizer.exe" "%1"' },
        @{ Root = 'HKLM'; Key = 'Software\Classes\OSTVisualizer.osp\shell\open\command'; Name = $null; Value = '"[INSTALLDIR]Visualizer.exe" "%1"' }
    )

    foreach ($Required in $RequiredEntries) {
        $Exists = Test-RegistryEntry `
            -Entries $Entries `
            -Root $Required['Root'] `
            -Key $Required['Key'] `
            -Name $Required['Name'] `
            -Value $Required['Value']

        if (-not $Exists) {
            throw "MSI config is missing registry entry $($Required['Root'])\$($Required['Key']) = $($Required['Value'])"
        }
    }
}

function Assert-MsiCreatorSupportsDefaultRegistryValues {
    param([Parameter(Mandatory = $true)] [string] $Path)

    $CreatorContent = Get-Content $Path -Raw
    if (
        $CreatorContent -notmatch "reg\.get\('name'\)\s+is\s+not\s+None" -or
        $CreatorContent -notmatch "registry_value\['Name'\]\s*=\s*reg\['name'\]"
    ) {
        throw "External MSI creator does not support default registry values. Preserve/copy the updated msicreator-master\createmsi.py before building."
    }
}

Write-Host "Step 1/7: Validating prerequisites..." -ForegroundColor Cyan

if (-not (Test-Path $BuildOutputDir)) {
    Write-Host "ERROR: Build output not found." -ForegroundColor Red
    Write-Host "  Expected: $BuildOutputDir" -ForegroundColor Red
    Write-Host "  Please run Build.ps1 first to compile the application." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "  Build output found" -ForegroundColor Green

if (-not (Test-Path $MSICreatorDir)) {
    Write-Host "ERROR: MSI creator directory not found." -ForegroundColor Red
    Write-Host "  Expected: $MSICreatorDir" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "  MSI creator directory found" -ForegroundColor Green

if (-not (Test-Path $MSICreatorScript)) {
    Write-Host "ERROR: MSI creator script not found." -ForegroundColor Red
    Write-Host "  Expected: $MSICreatorScript" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

try {
    Assert-MsiCreatorSupportsDefaultRegistryValues -Path $MSICreatorScript
    Write-Host "  MSI creator file-association support found" -ForegroundColor Green
} catch {
    Write-Host "ERROR: MSI creator is missing required file-association support." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $RepoMsiConfigFile)) {
    Write-Host "ERROR: Repo MSI config not found." -ForegroundColor Red
    Write-Host "  Expected: $RepoMsiConfigFile" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

try {
    $RepoMsiConfig = Get-Content $RepoMsiConfigFile -Raw | ConvertFrom-Json
    Assert-MsiFileAssociationConfig -Config $RepoMsiConfig
    Write-Host "  Repo MSI config file-association metadata found" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Repo MSI config is invalid." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $LicenseFile)) {
    Write-Host "ERROR: License.rtf not found." -ForegroundColor Red
    Write-Host "  Expected: $LicenseFile" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "  License file found" -ForegroundColor Green

if (-not (Test-Path $ApplicationInfoFile)) {
    Write-Host "ERROR: Version source file not found." -ForegroundColor Red
    Write-Host "  Expected: $ApplicationInfoFile" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "  Version source file found" -ForegroundColor Green

Write-Host "`nStep 2/7: Extracting version from source code..." -ForegroundColor Cyan

$VersionPattern = 'APPLICATION_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?)"'
$FileContent = Get-Content $ApplicationInfoFile -Raw

if ($FileContent -match $VersionPattern) {
    $Version = $Matches[1]
    Write-Host "  Version extracted: $Version" -ForegroundColor Green
} else {
    Write-Host "ERROR: Could not extract APPLICATION_VERSION from application_info.py" -ForegroundColor Red
    Write-Host "  Please ensure APPLICATION_VERSION is defined in the format: APPLICATION_VERSION = `"x.x.x`" or `"x.x.x.x`"" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`nStep 3/7: Synchronizing MSI configuration..." -ForegroundColor Cyan

try {
    Copy-Item $RepoMsiConfigFile $JsonConfigFile -Force
    $JsonContent = Get-Content $JsonConfigFile -Raw | ConvertFrom-Json
    $OldVersion = $JsonContent.version
    Assert-MsiFileAssociationConfig -Config $JsonContent

    if ($OldVersion -eq $Version) {
        Write-Host "  Version already up to date: $Version" -ForegroundColor Green
    } else {
        $JsonContent.version = $Version
        $JsonContent | ConvertTo-Json -Depth 10 | Set-Content $JsonConfigFile -Encoding UTF8
        Write-Host "  Version updated: $OldVersion -> $Version" -ForegroundColor Green
    }
} catch {
    Write-Host "ERROR: Failed to update JSON configuration." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`nStep 4/7: Preparing staging directory..." -ForegroundColor Cyan

try {
    if (Test-Path $StagingDir) {
        Write-Host "  Removing old staging files..." -ForegroundColor Gray
        Remove-Item $StagingDir -Recurse -Force
    }

    New-Item -ItemType Directory -Path $StagingDir -Force | Out-Null
    Write-Host "  Staging directory created" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to prepare staging directory." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`nStep 5/7: Copying files to staging..." -ForegroundColor Cyan

try {
    Copy-Item "$BuildOutputDir\*" -Destination $StagingDir -Recurse -Force
    Write-Host "  Files copied successfully" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to copy files to staging." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`nStep 6/7: Building MSI package..." -ForegroundColor Cyan
Write-Host "  This may take a few minutes..." -ForegroundColor Gray

Push-Location $MSICreatorDir
try {
    python createmsi.py ostvisualizer.json

    if ($LASTEXITCODE -ne 0) {
        throw "MSI creation failed with exit code $LASTEXITCODE"
    }

    Write-Host "  MSI build completed successfully" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to build MSI package." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Pop-Location
    Read-Host "Press Enter to exit"
    exit 1
} finally {
    Pop-Location
}

Write-Host "`nStep 7/7: Moving MSI to output location..." -ForegroundColor Cyan

$MSIFile = "ost3dvisualizer-$Version-64.msi"
$SourceMSI = Join-Path $MSICreatorDir $MSIFile
$DestMSI = Join-Path $ScriptDir $MSIFile

if (Test-Path $SourceMSI) {
    try {
        if (Test-Path $DestMSI) {
            Remove-Item $DestMSI -Force
        }

        Move-Item $SourceMSI $DestMSI -Force
        Write-Host "  MSI moved successfully" -ForegroundColor Green
    } catch {
        Write-Host "WARNING: Failed to move MSI file." -ForegroundColor Yellow
        Write-Host "  MSI is available at: $SourceMSI" -ForegroundColor Yellow
        $DestMSI = $SourceMSI
    }
} else {
    Write-Host "ERROR: MSI file was not created." -ForegroundColor Red
    Write-Host "  Expected: $MSIFile" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "MSI Package Created Successfully!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  Version:  $Version" -ForegroundColor Cyan
Write-Host "  File:     $MSIFile" -ForegroundColor Cyan
Write-Host "  Location: $DestMSI" -ForegroundColor Cyan
Write-Host "" -ForegroundColor Green
Write-Host "The MSI includes .ost and .osp file associations." -ForegroundColor Cyan

Read-Host "Press Enter to exit"
