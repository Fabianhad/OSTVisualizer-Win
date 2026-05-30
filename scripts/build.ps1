Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ActivateScript = Join-Path $ProjectRoot 'venv\Scripts\Activate.ps1'
$MainScript = Join-Path $ProjectRoot 'Visualizer.py'
$McpScript = Join-Path $ProjectRoot 'McpServer.py'
$OutDir = Join-Path $ProjectRoot 'dist_visualizer'
$McpOutDir = Join-Path $ProjectRoot 'dist_mcp'
$IconPath = Join-Path $ProjectRoot 'ost_visualizer\resources\icon.ico'
$TemplatePath = Join-Path $ProjectRoot 'ost_visualizer\presentation\visualization\renderers\threejs\templates\viewer.html'
$IconsDir = Join-Path $ProjectRoot 'ost_visualizer\resources\icons'
$SecretsPublicKeyPath = Join-Path $ProjectRoot '.secrets\license_public_key.pem'
$CommonNofollowArgs = @(
    "--nofollow-import-to=aifc,antigravity,asynchat,asyncore,audioop,cgitb,chunk,codeop,crypt,doctest,ensurepip,faulthandler,ftplib,genericpath,idlelib,imaplib,imghdr,lib2to3,mailbox,mailcap,modulefinder,msilib,nis,nntplib,nt,opcode,ossaudiodev,pickletools,pipes,poplib,posix,pydoc_data"
    "--nofollow-import-to=quopri,rlcompleter,sched,shelve,smtpd,smtplib,sndhdr,spwd,sqlite3,sre_compile,sre_constants,sre_parse,sunau,symtable,syslog,tabnanny,telnetlib,test,this,token,trace,tty,turtle,turtledemo,uu,venv,wave,winsound,wsgiref,xdrlib,zipapp,Nuitka"
)

if (-not (Test-Path $ActivateScript)) {
    Write-Host "ERROR: Virtual environment not found. Run scripts\setup.ps1 first." -ForegroundColor Red
    exit 1
}

. $ActivateScript

$CpuCores = $env:NUMBER_OF_PROCESSORS
Write-Host "OST Visualizer - Release Build" -ForegroundColor Cyan
Write-Host "  Parallel Jobs: $CpuCores" -ForegroundColor Green

if (-not (Test-Path $SecretsPublicKeyPath)) {
    Write-Host "ERROR: Missing bundled license public key: $SecretsPublicKeyPath" -ForegroundColor Red
    Write-Host "Copy the server public key to .secrets\license_public_key.pem before building." -ForegroundColor Yellow
    exit 1
}

$nuitkaArgs = @(
    '--standalone'
    '--windows-console-mode=disable'
    "--output-dir=$OutDir"
    '--enable-plugin=pyside6'
    '--include-windows-runtime-dlls=no'
    "--windows-icon-from-ico=$IconPath"
    "--include-data-file=$IconPath=ost_visualizer/resources/icon.ico"
    "--include-data-file=$SecretsPublicKeyPath=ost_visualizer/config/license_public_key.pem"
    "--include-data-file=$TemplatePath=ost_visualizer/presentation/visualization/renderers/threejs/templates/viewer.html"
    "--include-data-dir=$IconsDir=ost_visualizer/resources/icons"
) + $CommonNofollowArgs + @(
    '--assume-yes-for-downloads'
    '--lto=yes'
    "--jobs=$CpuCores"
    '--low-memory'
    $MainScript
)

$StartTime = Get-Date

function Invoke-NuitkaBuild {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Label,
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    Write-Host $Label -ForegroundColor Cyan
    & nuitka @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Nuitka failed while $($Label.ToLowerInvariant())" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Invoke-NuitkaBuild -Label "Building desktop app..." -Arguments $nuitkaArgs

$mcpNuitkaArgs = @(
    '--standalone'
    '--windows-console-mode=force'
    "--output-dir=$McpOutDir"
    '--output-filename=ostv-mcp.exe'
    '--include-windows-runtime-dlls=no'
    "--nofollow-import-to=PySide6,ost_visualizer.config.di_config"
) + $CommonNofollowArgs + @(
    '--assume-yes-for-downloads'
    '--lto=yes'
    "--jobs=$CpuCores"
    '--low-memory'
    $McpScript
)

Invoke-NuitkaBuild -Label "Building lightweight MCP helper..." -Arguments $mcpNuitkaArgs

$McpBuildDir = Join-Path $McpOutDir 'McpServer.dist'
$McpHelperExe = Join-Path $McpBuildDir 'ostv-mcp.exe'
$DesktopBuildDir = Join-Path $OutDir 'Visualizer.dist'
if (-not (Test-Path $McpHelperExe)) {
    Write-Host "ERROR: MCP helper build did not produce $McpHelperExe" -ForegroundColor Red
    exit 1
}
if (Test-Path $DesktopBuildDir) {
    Copy-Item (Join-Path $McpBuildDir '*') -Destination $DesktopBuildDir -Recurse -Force
    Write-Host "Copied MCP helper and runtime files into desktop distribution." -ForegroundColor Green
}
else {
    Write-Host "ERROR: Desktop distribution directory not found: $DesktopBuildDir" -ForegroundColor Red
    exit 1
}

$Duration = (Get-Date) - $StartTime
Write-Host "Build completed in $($Duration.ToString('hh\:mm\:ss'))" -ForegroundColor Green
