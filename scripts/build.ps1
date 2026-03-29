Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ActivateScript = Join-Path $ProjectRoot 'venv\Scripts\Activate.ps1'
$MainScript = Join-Path $ProjectRoot 'Visualizer.py'
$OutDir = Join-Path $ProjectRoot 'dist_visualizer'
$IconPath = Join-Path $ProjectRoot 'ost_visualizer\resources\icon.ico'
$TemplatePath = Join-Path $ProjectRoot 'ost_visualizer\presentation\visualization\renderers\threejs\templates\viewer.html'
$IconsDir = Join-Path $ProjectRoot 'ost_visualizer\resources\icons'
$SecretsPublicKeyPath = Join-Path $ProjectRoot '.secrets\license_public_key.pem'

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
    "--nofollow-import-to=aifc,antigravity,asynchat,asyncore,audioop,cgitb,chunk,codeop,crypt,doctest,ensurepip,faulthandler,ftplib,genericpath,idlelib,imaplib,imghdr,lib2to3,mailbox,mailcap,modulefinder,msilib,nis,nntplib,nt,opcode,ossaudiodev,pickletools,pipes,poplib,posix,pydoc_data"
    "--nofollow-import-to=quopri,rlcompleter,sched,shelve,smtpd,smtplib,sndhdr,spwd,sqlite3,sre_compile,sre_constants,sre_parse,sunau,symtable,syslog,tabnanny,telnetlib,test,this,token,trace,tty,turtle,turtledemo,uu,venv,wave,winsound,wsgiref,xdrlib,zipapp,zoneinfo,Nuitka"
    '--assume-yes-for-downloads'
    '--lto=yes'
    "--jobs=$CpuCores"
    '--low-memory'
    $MainScript
)

$StartTime = Get-Date

& nuitka @nuitkaArgs

$Duration = (Get-Date) - $StartTime
Write-Host "Build completed in $($Duration.ToString('hh\:mm\:ss'))" -ForegroundColor Green
