Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-PdfiumInstallation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Directory,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion
    )

    $VersionPath = Join-Path $Directory 'VERSION'
    if (-not (Test-Path -LiteralPath $VersionPath -PathType Leaf)) {
        throw "The PDFium installation is missing its VERSION file: $Directory"
    }
    $Parts = @{}
    foreach ($Line in Get-Content -LiteralPath $VersionPath) {
        if ($Line -notmatch '\A(MAJOR|MINOR|BUILD|PATCH)=([0-9]+)\z') {
            throw "The PDFium VERSION file is invalid: $VersionPath"
        }
        if ($Parts.ContainsKey($Matches[1])) {
            throw "The PDFium VERSION file contains duplicate fields: $VersionPath"
        }
        $Parts[$Matches[1]] = $Matches[2]
    }
    if ($Parts.Count -ne 4) {
        throw "The PDFium VERSION file is incomplete: $VersionPath"
    }
    $ActualVersion = '{0}.{1}.{2}.{3}' -f (
        $Parts['MAJOR'],
        $Parts['MINOR'],
        $Parts['BUILD'],
        $Parts['PATCH']
    )
    if (-not $ActualVersion.Equals($ExpectedVersion, [StringComparison]::Ordinal)) {
        throw "PDFium $ActualVersion is installed; expected $ExpectedVersion. Remove $Directory and rerun setup."
    }
}

function Assert-QpdfInstallation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Directory,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion
    )

    $VersionPath = Join-Path $Directory 'lib\cmake\qpdf\QPDFConfigVersion.cmake'
    if (-not (Test-Path -LiteralPath $VersionPath -PathType Leaf)) {
        throw "The QPDF installation is missing QPDFConfigVersion.cmake: $Directory"
    }
    $Contents = Get-Content -LiteralPath $VersionPath -Raw
    $VersionMatches = [regex]::Matches(
        $Contents,
        '(?m)^[ \t]*set\(PACKAGE_VERSION[ \t]+"([0-9]+\.[0-9]+\.[0-9]+)"\)[ \t]*\r?$'
    )
    if ($VersionMatches.Count -ne 1) {
        throw "The QPDF version file is invalid: $VersionPath"
    }
    $ActualVersion = $VersionMatches[0].Groups[1].Value
    if (-not $ActualVersion.Equals($ExpectedVersion, [StringComparison]::Ordinal)) {
        throw "QPDF $ActualVersion is installed; expected $ExpectedVersion. Remove $Directory and rerun setup."
    }
}

function Install-NativeDependencyDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FinalDirectory,
        [Parameter(Mandatory = $true)]
        [scriptblock]$PrepareDirectory,
        [Parameter(Mandatory = $true)]
        [scriptblock]$ValidateDirectory
    )

    if (Test-Path -LiteralPath $FinalDirectory) {
        & $ValidateDirectory $FinalDirectory
        return $false
    }

    $ParentDirectory = Split-Path -Parent $FinalDirectory
    if (-not (Test-Path -LiteralPath $ParentDirectory -PathType Container)) {
        throw "Native dependency parent directory is missing: $ParentDirectory"
    }
    $LeafName = Split-Path -Leaf $FinalDirectory
    $StagingDirectory = Join-Path (
        $ParentDirectory
    ) ".$LeafName.staging-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $StagingDirectory | Out-Null
    try {
        $PreparedDirectory = & $PrepareDirectory $StagingDirectory
        if (-not $PreparedDirectory) {
            throw 'Native dependency preparation did not return a directory.'
        }
        $StagingFullPath = [IO.Path]::GetFullPath($StagingDirectory).TrimEnd(
            [IO.Path]::DirectorySeparatorChar,
            [IO.Path]::AltDirectorySeparatorChar
        )
        $PreparedFullPath = [IO.Path]::GetFullPath([string]$PreparedDirectory).TrimEnd(
            [IO.Path]::DirectorySeparatorChar,
            [IO.Path]::AltDirectorySeparatorChar
        )
        $StagingPrefix = $StagingFullPath + [IO.Path]::DirectorySeparatorChar
        if (
            -not $PreparedFullPath.Equals(
                $StagingFullPath,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            -not $PreparedFullPath.StartsWith(
                $StagingPrefix,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw 'Native dependency preparation escaped its staging directory.'
        }
        if (-not (Test-Path -LiteralPath $PreparedFullPath -PathType Container)) {
            throw "Prepared native dependency directory is missing: $PreparedFullPath"
        }
        & $ValidateDirectory $PreparedFullPath
        $FinalFullPath = [IO.Path]::GetFullPath($FinalDirectory)
        [IO.Directory]::Move($PreparedFullPath, $FinalFullPath)
        return $true
    }
    finally {
        if (Test-Path -LiteralPath $StagingDirectory) {
            Remove-Item -LiteralPath $StagingDirectory -Recurse -Force
        }
    }
}

Export-ModuleMember -Function (
    'Assert-PdfiumInstallation',
    'Assert-QpdfInstallation',
    'Install-NativeDependencyDirectory'
)
