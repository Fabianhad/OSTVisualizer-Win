Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ActivateScript = Join-Path $ProjectRoot 'venv\Scripts\Activate.ps1'
$TakeoffScript = Join-Path $ProjectRoot 'McpTakeoffServer.py'
$TakeoffOutDir = Join-Path $ProjectRoot 'dist_takeoff_mcp'
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
    "--output-dir=$TakeoffOutDir"
    '--output-filename=ostv-takeoff-mcp.exe'
    '--include-windows-runtime-dlls=no'
    "--nofollow-import-to=PySide6,shiboken6,ost_visualizer.presentation,ost_visualizer.config.di_config,ost_visualizer.mcp_server"
) + $CommonNofollowArgs + @(
    '--assume-yes-for-downloads'
    '--lto=yes'
    "--jobs=$CpuCores"
    '--low-memory'
    $TakeoffScript
)

$StartTime = Get-Date
Write-Host "OST Visualizer - AI Takeoff MCP Release Build" -ForegroundColor Cyan
Write-Host "  Parallel Jobs: $CpuCores" -ForegroundColor Green
Write-Host "Building AI takeoff MCP proxy..." -ForegroundColor Cyan

& nuitka @NuitkaArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Nuitka failed while building the AI takeoff MCP proxy." -ForegroundColor Red
    exit $LASTEXITCODE
}

$TakeoffBuildDir = Join-Path $TakeoffOutDir 'McpTakeoffServer.dist'
$TakeoffHelperExe = Join-Path $TakeoffBuildDir 'ostv-takeoff-mcp.exe'
if (-not (Test-Path $TakeoffHelperExe)) {
    Write-Host "ERROR: AI takeoff MCP build did not produce $TakeoffHelperExe" -ForegroundColor Red
    exit 1
}

$Duration = (Get-Date) - $StartTime
Write-Host "AI takeoff MCP build completed in $($Duration.ToString('hh\:mm\:ss'))" -ForegroundColor Green
