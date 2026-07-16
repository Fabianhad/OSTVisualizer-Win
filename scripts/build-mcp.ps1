Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ActivateScript = Join-Path $ProjectRoot 'venv\Scripts\Activate.ps1'
$McpScript = Join-Path $ProjectRoot 'McpServer.py'
$McpOutDir = Join-Path $ProjectRoot 'dist_mcp'
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
$NuitkaArgs = @(
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

$StartTime = Get-Date
Write-Host "OST Visualizer - MCP Release Build" -ForegroundColor Cyan
Write-Host "  Parallel Jobs: $CpuCores" -ForegroundColor Green
Write-Host "Building lightweight MCP helper..." -ForegroundColor Cyan

& nuitka @NuitkaArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Nuitka failed while building the MCP helper." -ForegroundColor Red
    exit $LASTEXITCODE
}

$McpBuildDir = Join-Path $McpOutDir 'McpServer.dist'
$McpHelperExe = Join-Path $McpBuildDir 'ostv-mcp.exe'
if (-not (Test-Path $McpHelperExe)) {
    Write-Host "ERROR: MCP helper build did not produce $McpHelperExe" -ForegroundColor Red
    exit 1
}

$Duration = (Get-Date) - $StartTime
Write-Host "MCP build completed in $($Duration.ToString('hh\:mm\:ss'))" -ForegroundColor Green
