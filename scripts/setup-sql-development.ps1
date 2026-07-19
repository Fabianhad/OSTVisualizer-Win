param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$RotateClientPassword,
    [switch]$RemoveOwnedEnvironment,
    [switch]$ConfirmDestructive
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This setup must run from an elevated PowerShell session."
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "ost_visualizer"))) {
    throw "RepoRoot does not identify the OST Visualizer repository."
}

$instanceName = "OSTVDEV"
$instanceService = "MSSQL`$$instanceName"
$sqlPort = 1433
$workRoot = Join-Path $env:ProgramData "OSTVisualizer\SqlIntegrationSetup"
$backupRoot = Join-Path $env:ProgramData "OSTVisualizer\SqlIntegrationBackups"
$secretsRoot = Join-Path $RepoRoot ".secrets"
$secretsPath = Join-Path $secretsRoot "sql-development.json"
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run scripts\setup.ps1 first to create the repository virtual environment."
}
if ($RotateClientPassword -and $RemoveOwnedEnvironment) {
    throw "Password rotation cannot be combined with environment removal."
}
if ($RemoveOwnedEnvironment -and -not $ConfirmDestructive) {
    throw "Pass -ConfirmDestructive to remove the owned SQL environment."
}
if ($ConfirmDestructive -and -not $RemoveOwnedEnvironment) {
    throw "-ConfirmDestructive is valid only with -RemoveOwnedEnvironment."
}
$null = New-Item -ItemType Directory -Path $workRoot -Force
$null = New-Item -ItemType Directory -Path $backupRoot -Force
$locationPushed = $false

function Remove-SetupCache {
    $expected = [IO.Path]::GetFullPath(
        (Join-Path $env:ProgramData "OSTVisualizer\SqlIntegrationSetup")
    ).TrimEnd('\')
    $actual = [IO.Path]::GetFullPath($workRoot).TrimEnd('\')
    if ($actual -ne $expected) {
        throw "Refusing to remove an unexpected SQL setup cache path."
    }
    if (Test-Path -LiteralPath $actual) {
        Remove-Item -LiteralPath $actual -Recurse -Force
    }
}

trap {
    $failure = $_
    try {
        Remove-SetupCache
    }
    catch {
        Write-Warning "The SQL setup cache could not be removed."
    }
    if ($locationPushed) {
        Pop-Location
        $locationPushed = $false
    }
    Write-Error $failure
    exit 1
}

function Write-Stage([string]$Message) {
    Write-Host "[OSTV SQL Setup] $Message"
}

function Get-LocalSqlFirewallAddresses {
    $addresses = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $null = $addresses.Add("127.0.0.1")
    foreach ($address in [Net.Dns]::GetHostAddresses($env:COMPUTERNAME)) {
        if ($address.Equals([Net.IPAddress]::Any) -or
            $address.Equals([Net.IPAddress]::IPv6Any) -or
            $address.IsIPv6Multicast -or
            $address.IsIPv6LinkLocal) {
            continue
        }
        $null = $addresses.Add($address.IPAddressToString)
    }
    return @($addresses | Sort-Object)
}

function Assert-MicrosoftSignature([string]$Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Downloaded installer does not have a valid Authenticode signature."
    }
    if ($signature.SignerCertificate.Subject -notmatch "Microsoft") {
        throw "Downloaded installer is not signed by Microsoft."
    }
}

function Invoke-CheckedProcess(
    [string]$FilePath,
    [string[]]$ArgumentList
) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = [string]::Join(" ", $ArgumentList)
    $startInfo.UseShellExecute = $false
    $process = [Diagnostics.Process]::Start($startInfo)
    $process.WaitForExit()
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "Installer failed with exit code $($process.ExitCode)."
    }
}

function Set-RestrictedSecretsAcl([string]$Path, [switch]$Container) {
    if ($Container) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        $acl = [Security.AccessControl.FileSecurity]::new()
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($identity.User)
    foreach ($sid in @(
        $identity.User,
        [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
    )) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Get-RequiredOwnershipRegistry {
    $path = "HKLM:\SOFTWARE\OSTVisualizer\SqlDevelopment"
    if (-not (Test-Path -LiteralPath $path)) {
        throw "The SQL development ownership registry is missing."
    }
    $owned = Get-ItemProperty -LiteralPath $path
    $expected = @{
        InstanceName = "OSTVDEV"
        DatabaseName = "OSTV_CLIENT_TEST"
        ClientLogin = "OSTV_CLIENT_TEST_USER"
        ClientCredentialTarget = "OSTVisualizer/Development/OSTVDEV/Client"
        IntegrationCredentialTarget = "OSTVisualizer/Integration/OSTVDEV/Executor"
        FirewallRuleName = "OST Visualizer SQL Development - Local Only"
    }
    foreach ($entry in $expected.GetEnumerator()) {
        $property = $owned.PSObject.Properties[$entry.Key]
        if (-not $property -or [string]$property.Value -ne [string]$entry.Value) {
            throw "The SQL development ownership registry is invalid."
        }
    }
    foreach ($name in @(
        "OwnershipMarker",
        "LeafCertificateThumbprint",
        "RootCertificateThumbprint",
        "InstallerPrincipal"
    )) {
        $property = $owned.PSObject.Properties[$name]
        if (-not $property -or -not [string]$property.Value) {
            throw "The SQL development ownership registry is incomplete."
        }
    }
    return $owned
}

function Assert-OwnedMachineResources($Owned) {
    $instanceRegistry = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL"
    if (-not (Test-Path -LiteralPath $instanceRegistry)) {
        throw "The owned SQL instance registry is missing."
    }
    $instances = Get-ItemProperty -LiteralPath $instanceRegistry
    $instanceProperty = $instances.PSObject.Properties["OSTVDEV"]
    if (-not $instanceProperty -or [string]$instanceProperty.Value -ne "MSSQL16.OSTVDEV") {
        throw "The OSTVDEV instance identity does not match the owned environment."
    }
    $networkKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL16.OSTVDEV\MSSQLServer\SuperSocketNetLib"
    $boundCertificate = [string](Get-ItemProperty -LiteralPath $networkKey).Certificate
    if ($boundCertificate -ne ([string]$Owned.LeafCertificateThumbprint).ToLowerInvariant()) {
        throw "The SQL certificate binding does not match the ownership registry."
    }
    foreach ($property in $instances.PSObject.Properties) {
        if ($property.Name -eq "OSTVDEV" -or $property.Name -like "PS*") {
            continue
        }
        $otherNetwork = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$($property.Value)\MSSQLServer\SuperSocketNetLib"
        if (Test-Path -LiteralPath $otherNetwork) {
            $otherCertificate = [string](
                Get-ItemProperty -LiteralPath $otherNetwork
            ).Certificate
            if ($otherCertificate -and $otherCertificate -eq $boundCertificate) {
                throw "The SQL certificate is shared with another instance."
            }
        }
    }

    $leafPath = "Cert:\LocalMachine\My\$($Owned.LeafCertificateThumbprint)"
    $rootPrivatePath = "Cert:\LocalMachine\My\$($Owned.RootCertificateThumbprint)"
    $rootTrustedPath = "Cert:\LocalMachine\Root\$($Owned.RootCertificateThumbprint)"
    foreach ($path in @($leafPath, $rootPrivatePath, $rootTrustedPath)) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "An owned SQL certificate is missing."
        }
    }
    $leaf = Get-Item -LiteralPath $leafPath
    $root = Get-Item -LiteralPath $rootPrivatePath
    if ($leaf.FriendlyName -ne "OST Visualizer SQL Development" -or
        $leaf.Subject -ne "CN=localhost" -or
        $leaf.Issuer -ne "CN=OSTV Local SQL Development Root" -or
        $root.Subject -ne "CN=OSTV Local SQL Development Root") {
        throw "An owned SQL certificate no longer matches its expected identity."
    }
    $otherIssuedCertificates = @(Get-ChildItem Cert:\LocalMachine\My |
        Where-Object Issuer -eq $root.Subject |
        Where-Object Thumbprint -ne $leaf.Thumbprint |
        Where-Object Thumbprint -ne $root.Thumbprint)
    if ($otherIssuedCertificates.Count -ne 0) {
        throw "The local SQL issuer is used by another certificate."
    }

    $firewallRules = @(Get-NetFirewallRule -DisplayName $Owned.FirewallRuleName `
        -ErrorAction SilentlyContinue)
    if ($firewallRules.Count -ne 1) {
        throw "The owned SQL firewall rule is missing or duplicated."
    }
    $portFilter = $firewallRules[0] | Get-NetFirewallPortFilter
    $addressFilter = $firewallRules[0] | Get-NetFirewallAddressFilter
    if ($firewallRules[0].Direction -ne "Inbound" -or
        $firewallRules[0].Action -ne "Allow" -or
        $firewallRules[0].Profile -ne "Private" -or
        $portFilter.Protocol -ne "TCP" -or
        $portFilter.LocalPort -ne "1433" -or
        @(Compare-Object
            @(Get-LocalSqlFirewallAddresses)
            @($addressFilter.RemoteAddress)).Count -ne 0) {
        throw "The owned SQL firewall rule no longer matches the safe configuration."
    }
    if (-not (Test-Path -LiteralPath $secretsPath -PathType Leaf)) {
        throw "The owned SQL secrets file is missing."
    }
    $backupFiles = @(Get-ChildItem -LiteralPath $backupRoot -File -Force `
        -ErrorAction SilentlyContinue)
    if ($backupFiles.Count -ne 0) {
        throw "The SQL backup directory is not empty; teardown was refused."
    }
}

function Invoke-OwnedEnvironmentRemoval {
    $owned = Get-RequiredOwnershipRegistry
    Assert-OwnedMachineResources $owned
    $uninstaller = Join-Path $env:ProgramFiles `
        "Microsoft SQL Server\160\Setup Bootstrap\SQL2022\setup.exe"
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        throw "The Microsoft SQL Server instance uninstaller was not found."
    }
    Assert-MicrosoftSignature $uninstaller
    Push-Location -LiteralPath $RepoRoot
    $script:locationPushed = $true
    & $python -m tools.manage_sql_development --verify-teardown `
        --repo-root $RepoRoot
    $verifyExitCode = $LASTEXITCODE
    Pop-Location
    $script:locationPushed = $false
    if ($verifyExitCode -ne 0) {
        throw "SQL ownership verification refused teardown."
    }

    Push-Location -LiteralPath $RepoRoot
    $script:locationPushed = $true
    & $python -m tools.manage_sql_development --prepare-teardown `
        --repo-root $RepoRoot
    $prepareExitCode = $LASTEXITCODE
    Pop-Location
    $script:locationPushed = $false
    if ($prepareExitCode -ne 0) {
        throw "SQL resource teardown failed before instance removal."
    }

    Invoke-CheckedProcess $uninstaller @(
        "/Q",
        "/ACTION=Uninstall",
        "/FEATURES=SQLENGINE",
        "/INSTANCENAME=OSTVDEV"
    )
    $instanceRegistry = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL"
    if (Test-Path -LiteralPath $instanceRegistry) {
        $remaining = Get-ItemProperty -LiteralPath $instanceRegistry
        if ($remaining.PSObject.Properties["OSTVDEV"]) {
            throw "OSTVDEV is still registered; supporting resources were retained."
        }
    }

    Remove-NetFirewallRule -DisplayName $owned.FirewallRuleName `
        -ErrorAction Stop
    Remove-Item -LiteralPath `
        "Cert:\LocalMachine\My\$($owned.LeafCertificateThumbprint)" -Force
    Remove-Item -LiteralPath `
        "Cert:\LocalMachine\Root\$($owned.RootCertificateThumbprint)" -Force
    Remove-Item -LiteralPath `
        "Cert:\LocalMachine\My\$($owned.RootCertificateThumbprint)" -Force

    Push-Location -LiteralPath $RepoRoot
    $script:locationPushed = $true
    & $python -m tools.manage_sql_development --complete-teardown `
        --repo-root $RepoRoot
    $completeExitCode = $LASTEXITCODE
    Pop-Location
    $script:locationPushed = $false
    if ($completeExitCode -ne 0) {
        throw "Local credential and secrets teardown failed."
    }

    if (Test-Path -LiteralPath $backupRoot) {
        $resolvedBackup = (Resolve-Path -LiteralPath $backupRoot).Path
        $expectedBackup = [IO.Path]::GetFullPath(
            (Join-Path $env:ProgramData "OSTVisualizer\SqlIntegrationBackups")
        )
        if ($resolvedBackup -ne $expectedBackup) {
            throw "Refusing to remove an unexpected backup directory."
        }
        Remove-Item -LiteralPath $resolvedBackup -Recurse -Force
    }
    Remove-SetupCache
    Remove-Item -LiteralPath "HKLM:\SOFTWARE\OSTVisualizer\SqlDevelopment" `
        -Recurse -Force
    $programDataRoot = Join-Path $env:ProgramData "OSTVisualizer"
    if ((Test-Path -LiteralPath $programDataRoot) -and
        @(Get-ChildItem -LiteralPath $programDataRoot -Force).Count -eq 0) {
        Remove-Item -LiteralPath $programDataRoot -Force
    }
    Write-Stage "Owned OSTVDEV environment removed; shared SQL tooling was retained."
}

if ($RemoveOwnedEnvironment) {
    Invoke-OwnedEnvironmentRemoval
    exit 0
}

$odbcRegistry = "HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server"
$odbcVersion = $null
if (Test-Path -LiteralPath $odbcRegistry) {
    $odbcDriver = (Get-ItemProperty -LiteralPath $odbcRegistry).Driver
    if (Test-Path -LiteralPath $odbcDriver) {
        $odbcVersion = [Version](Get-Item -LiteralPath $odbcDriver).VersionInfo.ProductVersion
    }
}
if (-not $odbcVersion -or $odbcVersion -lt [Version]"18.6.2.1") {
    Write-Stage "Installing or updating Microsoft ODBC Driver 18."
    $wingetAction = if ($odbcVersion) { "upgrade" } else { "install" }
    & winget $wingetAction --id Microsoft.msodbcsql.18 --exact --source winget --silent `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -notin @(0, -1978335189)) {
        throw "ODBC Driver 18 installation failed."
    }
}

$instanceRegistry = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL"
$instanceId = $null
if (Test-Path -LiteralPath $instanceRegistry) {
    $instanceId = (Get-ItemProperty -LiteralPath $instanceRegistry).$instanceName
}

if (-not $instanceId) {
    Write-Stage "Downloading SQL Server 2022 Developer installation media."
    $bootstrapper = Join-Path $workRoot "SQL2022-SSEI-Dev.exe"
    Invoke-WebRequest `
        -Uri "https://download.microsoft.com/download/c/c/9/cc9c6797-383c-4b24-8920-dc057c1de9d3/SQL2022-SSEI-Dev.exe" `
        -OutFile $bootstrapper
    Assert-MicrosoftSignature $bootstrapper
    $mediaRoot = Join-Path $workRoot "Media"
    $null = New-Item -ItemType Directory -Path $mediaRoot -Force
    Invoke-CheckedProcess $bootstrapper @(
        "/Action=Download",
        "/MediaType=ISO",
        "/Language=en-US",
        "/MediaPath=$mediaRoot",
        "/Quiet"
    )
    $iso = Get-ChildItem -LiteralPath $mediaRoot -Filter "*.iso" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $iso) {
        throw "SQL Server installation media was not downloaded."
    }
    Write-Stage "Installing the dedicated OSTVDEV Database Engine instance."
    $disk = Mount-DiskImage -ImagePath $iso.FullName -PassThru
    try {
        $volume = $disk | Get-Volume
        $setup = "$($volume.DriveLetter):\setup.exe"
        $windowsAdmin = "$env:USERDOMAIN\$env:USERNAME"
        Invoke-CheckedProcess $setup @(
            "/Q",
            "/ACTION=Install",
            "/FEATURES=SQLENGINE",
            "/INSTANCENAME=$instanceName",
            "/INSTANCEID=$instanceName",
            "/SQLSVCACCOUNT=`"NT Service\$instanceService`"",
            "/SQLSVCSTARTUPTYPE=Automatic",
            "/SQLSYSADMINACCOUNTS=`"$windowsAdmin`"",
            "/TCPENABLED=1",
            "/NPENABLED=0",
            "/BROWSERSVCSTARTUPTYPE=Disabled",
            "/UPDATEENABLED=True",
            "/IACCEPTSQLSERVERLICENSETERMS",
            "/SUPPRESSPRIVACYSTATEMENTNOTICE=True"
        )
    }
    finally {
        Dismount-DiskImage -ImagePath $iso.FullName
    }
    $instanceId = (Get-ItemProperty -LiteralPath $instanceRegistry).$instanceName
}

$targetSqlBuild = [Version]"16.0.4265.3"
$installedSqlBuild = [Version](Get-ItemProperty `
    -LiteralPath "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId\Setup"
).PatchLevel
if ($installedSqlBuild -lt $targetSqlBuild) {
    Write-Stage "Applying the current SQL Server 2022 cumulative update."
    $cuInstaller = Join-Path $workRoot "SQLServer2022-KB5093420-x64.exe"
    if (-not (Test-Path -LiteralPath $cuInstaller)) {
        Invoke-WebRequest `
            -Uri "https://download.microsoft.com/download/a89001cb-9c99-48d3-9f14-ded054b35fe4/SQLServer2022-KB5093420-x64.exe" `
            -OutFile $cuInstaller
    }
    Assert-MicrosoftSignature $cuInstaller
    Invoke-CheckedProcess $cuInstaller @(
        "/quiet",
        "/action=patch",
        "/instancename=$instanceName",
        "/IAcceptSQLServerLicenseTerms"
    )
}

$ssmsPackage = Get-ItemProperty `
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*", `
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" `
    -ErrorAction SilentlyContinue |
    Where-Object {
        $_.PSObject.Properties["DisplayName"] -and
        $_.DisplayName -eq "SQL Server Management Studio 22"
    } |
    Select-Object -First 1
if (-not $ssmsPackage -or [Version]$ssmsPackage.DisplayVersion -lt [Version]"22.8.0") {
    Write-Stage "Installing SQL Server Management Studio 22."
    $ssmsInstaller = Join-Path $workRoot "vs_SSMS.exe"
    if (-not (Test-Path -LiteralPath $ssmsInstaller)) {
        Invoke-WebRequest -Uri "https://aka.ms/ssms/22/release/vs_SSMS.exe" `
            -OutFile $ssmsInstaller
    }
    Assert-MicrosoftSignature $ssmsInstaller
    Invoke-CheckedProcess $ssmsInstaller @(
        "--quiet",
        "--wait",
        "--norestart",
        "--locale",
        "en-US"
    )
}

Write-Stage "Verifying SQL network and authentication settings."
$instanceRoot = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId"
$serverKey = Join-Path $instanceRoot "MSSQLServer"
$networkKey = Join-Path $serverKey "SuperSocketNetLib"
$tcpKey = Join-Path $networkKey "Tcp"
$ipAllKey = Join-Path $tcpKey "IPAll"
$restartRequired = $false
function Set-SqlRegistryValue([string]$Path, [string]$Name, $Value) {
    $current = (Get-ItemProperty -LiteralPath $Path).$Name
    if ([string]$current -ne [string]$Value) {
        Set-ItemProperty -LiteralPath $Path -Name $Name -Value $Value
        $script:restartRequired = $true
    }
}
Set-SqlRegistryValue $serverKey LoginMode 2
Set-SqlRegistryValue $networkKey ForceEncryption 1
Set-SqlRegistryValue $networkKey HideInstance 1
Set-SqlRegistryValue $tcpKey Enabled 1
Set-SqlRegistryValue $tcpKey ListenOnAllIPs 1
Set-SqlRegistryValue $ipAllKey TcpDynamicPorts ""
Set-SqlRegistryValue $ipAllKey TcpPort "$sqlPort"

Write-Stage "Verifying the trusted SQL development certificate."
$leafFriendlyName = "OST Visualizer SQL Development"
$configuredThumbprint = [string](Get-ItemProperty -LiteralPath $networkKey).Certificate
$leafCandidates = @(Get-ChildItem Cert:\LocalMachine\My |
    Where-Object FriendlyName -eq $leafFriendlyName |
    Where-Object Subject -eq "CN=localhost" |
    Where-Object Issuer -eq "CN=OSTV Local SQL Development Root" |
    Where-Object HasPrivateKey |
    Where-Object NotAfter -gt (Get-Date).AddDays(30) |
    Where-Object {
        $enhancedKeyUsages = @(
            $_.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId }
        )
        $_.DnsNameList.Unicode -contains "localhost" -and
        $_.DnsNameList.Unicode -contains $env:COMPUTERNAME -and
        $enhancedKeyUsages -contains "1.3.6.1.5.5.7.3.1"
    })
$leaf = $leafCandidates |
    Where-Object Thumbprint -eq $configuredThumbprint |
    Select-Object -First 1
if (-not $leaf) {
    $leaf = $leafCandidates | Sort-Object NotAfter -Descending | Select-Object -First 1
}
if (-not $leaf) {
    $root = Get-ChildItem Cert:\LocalMachine\My |
        Where-Object Subject -eq "CN=OSTV Local SQL Development Root" |
        Where-Object Issuer -eq "CN=OSTV Local SQL Development Root" |
        Where-Object HasPrivateKey |
        Where-Object NotAfter -gt (Get-Date).AddYears(2) |
        Sort-Object NotAfter -Descending | Select-Object -First 1
    if (-not $root) {
        $root = New-SelfSignedCertificate -Type Custom `
            -Subject "CN=OSTV Local SQL Development Root" `
            -CertStoreLocation "Cert:\LocalMachine\My" `
            -KeyAlgorithm RSA -KeyLength 4096 -HashAlgorithm SHA256 `
            -KeyExportPolicy NonExportable -KeyUsage CertSign,CRLSign,DigitalSignature `
            -NotAfter (Get-Date).AddYears(5)
    }
    $rootStore = [Security.Cryptography.X509Certificates.X509Store]::new(
        "Root",
        [Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine
    )
    $rootStore.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    try {
        if (-not ($rootStore.Certificates | Where-Object Thumbprint -eq $root.Thumbprint)) {
            $rootStore.Add($root)
        }
    }
    finally {
        $rootStore.Close()
    }
    $leaf = New-SelfSignedCertificate -Type Custom -Subject "CN=localhost" `
        -DnsName @("localhost", $env:COMPUTERNAME) -Signer $root `
        -CertStoreLocation "Cert:\LocalMachine\My" `
        -Provider "Microsoft RSA SChannel Cryptographic Provider" `
        -KeySpec KeyExchange -KeyAlgorithm RSA -KeyLength 2048 `
        -HashAlgorithm SHA256 -KeyExportPolicy NonExportable `
        -KeyUsage DigitalSignature,KeyEncipherment `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.1") `
        -NotAfter (Get-Date).AddYears(2)
    $leaf.FriendlyName = $leafFriendlyName
}

$trustedIssuer = Get-ChildItem Cert:\LocalMachine\Root |
    Where-Object Subject -eq $leaf.Issuer |
    Where-Object NotAfter -gt (Get-Date).AddDays(30) |
    Select-Object -First 1
if (-not $trustedIssuer) {
    throw "The SQL development certificate issuer is not trusted locally."
}

$containerName = $leaf.PrivateKey.CspKeyContainerInfo.UniqueKeyContainerName
$keyPath = Join-Path $env:ProgramData "Microsoft\Crypto\RSA\MachineKeys\$containerName"
$acl = Get-Acl -LiteralPath $keyPath
$accessRule = [Security.AccessControl.FileSystemAccessRule]::new(
    "NT SERVICE\$instanceService",
    [Security.AccessControl.FileSystemRights]::Read,
    [Security.AccessControl.AccessControlType]::Allow
)
$acl.SetAccessRule($accessRule)
Set-Acl -LiteralPath $keyPath -AclObject $acl
$leafThumbprint = $leaf.Thumbprint.ToLowerInvariant()
if ($configuredThumbprint -ne $leafThumbprint) {
    Set-ItemProperty -LiteralPath $networkKey -Name Certificate -Value $leafThumbprint
    $restartRequired = $true
}

Write-Stage "Verifying local-only Windows Firewall access."
$firewallRuleName = "OST Visualizer SQL Development - Local Only"
$firewallRules = @(Get-NetFirewallRule -DisplayName $firewallRuleName `
    -ErrorAction SilentlyContinue)
$localFirewallAddresses = @(Get-LocalSqlFirewallAddresses)
$firewallValid = $firewallRules.Count -eq 1
if ($firewallValid) {
    $portFilter = $firewallRules[0] | Get-NetFirewallPortFilter
    $addressFilter = $firewallRules[0] | Get-NetFirewallAddressFilter
    $firewallValid = (
        $firewallRules[0].Enabled -eq "True" -and
        $firewallRules[0].Direction -eq "Inbound" -and
        $firewallRules[0].Action -eq "Allow" -and
        $firewallRules[0].Profile -eq "Private" -and
        $portFilter.Protocol -eq "TCP" -and
        $portFilter.LocalPort -eq "$sqlPort" -and
        @(Compare-Object
            $localFirewallAddresses
            @($addressFilter.RemoteAddress)).Count -eq 0
    )
}
if (-not $firewallValid) {
    Remove-NetFirewallRule -DisplayName $firewallRuleName -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $firewallRuleName -Direction Inbound `
        -Action Allow -Protocol TCP -LocalPort $sqlPort -Profile Private `
        -RemoteAddress $localFirewallAddresses | Out-Null
}

Set-Service -Name SQLBrowser -StartupType Disabled -ErrorAction SilentlyContinue
Stop-Service -Name SQLBrowser -Force -ErrorAction SilentlyContinue
Set-Service -Name "SQLAgent`$$instanceName" -StartupType Disabled -ErrorAction SilentlyContinue
Stop-Service -Name "SQLAgent`$$instanceName" -Force -ErrorAction SilentlyContinue
Set-Service -Name "SQLTELEMETRY`$$instanceName" -StartupType Disabled `
    -ErrorAction SilentlyContinue
Stop-Service -Name "SQLTELEMETRY`$$instanceName" -Force `
    -ErrorAction SilentlyContinue
Set-Service -Name $instanceService -StartupType Automatic
if ((Get-Service -Name $instanceService).Status -ne "Running") {
    Start-Service -Name $instanceService
}
elseif ($restartRequired) {
    Restart-Service -Name $instanceService -Force
}

$listening = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Get-NetTCPConnection -State Listen -LocalPort $sqlPort `
        -ErrorAction SilentlyContinue) {
        $listening = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $listening) {
    throw "OSTVDEV did not begin listening on the configured TCP port."
}

$serviceAccount = "NT SERVICE\$instanceService"
$backupAcl = Get-Acl -LiteralPath $backupRoot
$backupRule = [Security.AccessControl.FileSystemAccessRule]::new(
    $serviceAccount,
    [Security.AccessControl.FileSystemRights]::Modify,
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
        [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)
$backupAcl.SetAccessRule($backupRule)
$backupUserRule = [Security.AccessControl.FileSystemAccessRule]::new(
    $identity.Name,
    [Security.AccessControl.FileSystemRights]::Modify,
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
        [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)
$backupAcl.SetAccessRule($backupUserRule)
Set-Acl -LiteralPath $backupRoot -AclObject $backupAcl

Write-Stage "Provisioning guarded database procedures and Credential Manager secret."
Push-Location -LiteralPath $RepoRoot
$locationPushed = $true
& $python -m tools.provision_sql_integration --backup-root $backupRoot
$provisionExitCode = $LASTEXITCODE
Pop-Location
$locationPushed = $false
if ($provisionExitCode -ne 0) {
    throw "SQL integration provisioning failed."
}

$null = New-Item -ItemType Directory -Path $secretsRoot -Force
Set-RestrictedSecretsAcl -Path $secretsRoot -Container
Write-Stage "Provisioning the persistent local SQL client database."
$clientArguments = @(
    "-m",
    "tools.manage_sql_development",
    "--provision",
    "--repo-root",
    $RepoRoot
)
if ($RotateClientPassword) {
    $clientArguments += "--rotate-client-password"
}
Push-Location -LiteralPath $RepoRoot
$locationPushed = $true
& $python @clientArguments
$clientExitCode = $LASTEXITCODE
Pop-Location
$locationPushed = $false
if ($clientExitCode -ne 0) {
    throw "SQL client development provisioning failed."
}
if (-not (Test-Path -LiteralPath $secretsPath -PathType Leaf)) {
    throw "SQL client development secrets were not created."
}
Set-RestrictedSecretsAcl -Path $secretsPath

$ownershipRegistry = "HKLM:\SOFTWARE\OSTVisualizer\SqlDevelopment"
if (-not (Test-Path -LiteralPath $ownershipRegistry)) {
    throw "SQL development ownership registry was not created."
}
Set-ItemProperty -LiteralPath $ownershipRegistry -Name LeafCertificateThumbprint `
    -Value $leaf.Thumbprint
Set-ItemProperty -LiteralPath $ownershipRegistry -Name RootCertificateThumbprint `
    -Value $trustedIssuer.Thumbprint
Set-ItemProperty -LiteralPath $ownershipRegistry -Name FirewallRuleName `
    -Value $firewallRuleName

Write-Stage "Setup completed successfully."
Remove-SetupCache
