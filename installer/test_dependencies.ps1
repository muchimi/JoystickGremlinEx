# Run with Windows PowerShell 5.1. All network and process calls are mocked.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'dependencies.ps1') -Component hidhide

$script:Checks = 0
function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:Checks++
}
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    $caught = $false
    try { & $Action | Out-Null } catch { $caught = $true }
    Assert-True $caught $Message
}

function Test-RegistryKey($Hive, $Path) { return $Path -in $script:InstalledKeys }
function Get-RegistryValue($Path, $Name) { return $script:RegistryValues["$Path|$Name"] }
function Get-BridgeExecutableVersion($Path) {
    $script:LastVersionPath = $Path
    return ConvertTo-BridgeVersion $script:ExecutableVersions[$Path]
}
function Test-Path {
    param($LiteralPath)
    return $script:ConsoleBridgeInstalled -or $script:ExecutableVersions.ContainsKey($LiteralPath)
}
$script:InstalledKeys = @()
$script:RegistryValues = @{}
$script:ExecutableVersions = @{}
$script:ConsoleBridgeInstalled = $false
Assert-True (Test-DependencyNeeded hidhide) 'Offer missing HidHide.'
Assert-True (Test-DependencyNeeded bridge) 'Offer bridge when it is not installed.'
foreach ($path in @('SYSTEM\CurrentControlSet\Services\HidHide', 'Installer\Dependencies\NSS.Drivers.HidHide.x64')) {
    $script:InstalledKeys = @($path)
    Assert-True (-not (Test-DependencyNeeded hidhide)) "Skip installed HidHide: $path"
}
foreach ($path in @('SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService',
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1')) {
    $script:InstalledKeys = @($path)
    Assert-True (-not (Test-DependencyNeeded bridge)) "Skip bridge: $path"
}
$script:InstalledKeys = @('SYSTEM\CurrentControlSet\Services\vjoy')
Assert-True (Test-DependencyNeeded bridge) 'Allow bridge installation when vJoy is installed.'
$script:InstalledKeys = @()
$script:ConsoleBridgeInstalled = $true
Assert-True (-not (Test-DependencyNeeded bridge)) 'Skip an existing console bridge.'
$script:ConsoleBridgeInstalled = $false

$serviceKey = 'SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService'
$uninstallKey = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1'
Assert-True ((ConvertTo-BridgeVersion '0.1.1') -eq (ConvertTo-BridgeVersion '0.1.1.0')) 'Treat three- and four-part versions equally.'
Assert-True ((ConvertTo-BridgeVersion '0.1.10') -gt (ConvertTo-BridgeVersion '0.1.9')) 'Compare version numbers numerically.'
Assert-True ((ConvertTo-BridgeVersion 'v0.1.1+abcdef') -eq [version]'0.1.1.0') 'Accept informational commit metadata.'
foreach ($invalidVersion in @('', 'unknown', '0.1.1-preview', '0.1.1.0.1', '999999999999999.1.1')) {
    Assert-True ($null -eq (ConvertTo-BridgeVersion $invalidVersion)) "Reject an unconfirmed stable version: $invalidVersion"
}

$script:InstalledKeys = @($serviceKey)
$customExecutable = 'C:\Bridge Test Folder\GEXMaestroBridgeService.exe'
$script:RegistryValues["$serviceKey|ImagePath"] = '"' + $customExecutable + '" --receive-port 9123'
$script:ExecutableVersions[$customExecutable] = '0.1.9+abc123'
$installed = Get-BridgeInstallation
Assert-True ($installed.Installed -and $installed.Version -eq [version]'0.1.9.0') 'Read the version from a custom service location.'
Assert-True ($script:LastVersionPath -eq $customExecutable) 'Strip quotes and service arguments from the executable path.'
Assert-True (Test-DependencyNeeded bridge (ConvertTo-BridgeVersion '0.1.10')) 'Allow a confirmed newer bridge release.'
foreach ($available in @('0.1.9', '0.1.9.0', '0.1.8')) {
    Assert-True (-not (Test-DependencyNeeded bridge (ConvertTo-BridgeVersion $available))) "Do not reinstall or downgrade to $available."
}
$script:RegistryValues = @{"$uninstallKey|InstallLocation" = 'D:\Console Bridge'; "$uninstallKey|DisplayVersion" = '0.1.2'}
$script:InstalledKeys = @($uninstallKey)
$script:ExecutableVersions = @{'D:\Console Bridge\GEXMaestroBridgeService.exe' = '0.1.3'}
Assert-True ((Get-BridgeInstallation).Version -eq [version]'0.1.3.0') 'Use the actual console executable version before stale uninstall metadata.'
$script:ExecutableVersions = @{}
Assert-True ((Get-BridgeInstallation).Version -eq [version]'0.1.2.0') 'Fall back to installer DisplayVersion when the executable cannot be read.'
$script:RegistryValues = @{}
Assert-True (-not (Test-DependencyNeeded bridge (ConvertTo-BridgeVersion '0.1.10'))) 'Do not offer an upgrade when the installed version is unknown.'
$script:InstalledKeys = @()
$defaultExecutable = Join-Path $env:SystemDrive 'GremlinEx\GEXMaestroBridge\GEXMaestroBridgeService.exe'
$script:ExecutableVersions = @{$defaultExecutable = '0.1.4'}
Assert-True ((Get-BridgeInstallation).Version -eq [version]'0.1.4.0') 'Detect console installation in the bridge installer default directory.'
$script:ExecutableVersions = @{}

function Invoke-RestMethod {
    param($Uri, $Headers, $TimeoutSec)
    $script:LastApi = $Uri
    if ($script:ApiFails) { throw 'Offline' }
    return $script:Release
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, $Uri, $Headers, $OutFile, $TimeoutSec)
    $script:Downloads++
    [IO.File]::WriteAllBytes($OutFile, (New-Object byte[] 2048))
    if ($script:VersionAfterDownload) { $script:RegistryValues["$script:BridgeUninstallKey|DisplayVersion"] = $script:VersionAfterDownload }
}
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $WindowStyle, $Verb)
    $script:LastArguments = $ArgumentList
    $script:SetupsStarted++
    $script:LastWindowStyle = $WindowStyle
    $script:LastVerb = $Verb
    return [pscustomobject]@{ExitCode = $script:ChildExitCode}
}
function Get-BridgeEnvironmentValue($Name) {
    if ($Name -notin @('ReceivePort', 'SendPort')) { throw 'The installer must not infer bridge addresses from the environment.' }
    return $script:BridgeEnvironment[$Name]
}
function Test-BridgeOscPing($ReceivePort, $SendPort) {
    $script:ProbeCalls++
    $script:LastProbe = @($ReceivePort, $SendPort)
    return [pscustomobject]@{State = 'connected'; Message = 'Connected to the test bridge.'}
}

$stage = Join-Path ([IO.Path]::GetTempPath()) ('gremlinex-dependency-test-' + [guid]::NewGuid().ToString('N'))
$script:BridgeEnvironment = @{}
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    $configPath = Join-Path $stage 'appsettings.json'
    $probeExecutable = Join-Path $stage 'GEXMaestroBridgeService.exe'
    $script:ExecutableVersions[$configPath] = ''
    @{Osc = @{ListenAddress = '127.0.0.1'; ReplyAddress = '127.0.0.1'; ReceivePort = 9123; SendPort = 9134}} |
        ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
    $probeInstallation = [pscustomobject]@{Installed = $true; Path = $probeExecutable; CommandLine = '"' + $probeExecutable + '" --mock'}
    $settings = Get-BridgeProbeSettings $probeInstallation
    Assert-True ($settings.Address -eq '127.0.0.1' -and $settings.ReceivePort -eq 9123 -and $settings.SendPort -eq 9134) 'Read connection settings beside the registry-resolved executable.'
    $relaxedJson = @'
{
    // Match the bridge configuration reader's JSON extensions.
    "Osc": {
        "ListenAddress": "127.0.0.1",
        "ReceivePort": 9123,
        "SendPort": 9134,
        "AllowedSenders": [
            "127.0.0.1", // A trailing array comma caused the reported installer error.
        ],
        "Note": "http://bridge.local/*keep*/,} // keep \"quotes\"",
        "Path": "C:\\Bridge\\\"quoted\"",
    },
    "Logging": { /* Preserve whitespace between tokens when stripping comments. */
        "Levels": [{"Name": "Info,]"},],
    },
}
'@
    $parsed = ConvertFrom-BridgeSettingsJson $relaxedJson
    Assert-True ($parsed.Osc.AllowedSenders.Count -eq 1 -and $parsed.Osc.AllowedSenders[0] -eq '127.0.0.1') 'Accept a trailing comma in AllowedSenders under Windows PowerShell 5.1.'
    Assert-True ($parsed.Osc.Note -ceq 'http://bridge.local/*keep*/,} // keep "quotes"') 'Keep comment markers and comma delimiters inside strings.'
    Assert-True ($parsed.Osc.Path -ceq 'C:\Bridge\"quoted"') 'Keep escaped Windows paths and quotes.'
    Assert-True ($parsed.Logging.Levels[0].Name -ceq 'Info,]') 'Accept nested trailing commas without changing string contents.'
    Set-Content -LiteralPath $configPath -Value $relaxedJson -Encoding UTF8
    $script:ProbeCalls = 0
    $connection = Test-BridgeConnection $probeInstallation
    Assert-True ($connection.State -eq 'connected' -and $script:ProbeCalls -eq 1 -and $script:LastProbe[0] -eq 9123 -and $script:LastProbe[1] -eq 9134) 'Comments and trailing commas must not prevent the configured localhost probe.'
    foreach ($invalidJson in @('{"Osc":{"AllowedSenders":["127.0.0.1",}}',
        '{"Osc":{"ReceivePort":9123 "SendPort":9134}}', '{"Osc":{"AllowedSenders":["private-marker",,]}}',
        '{"Osc":{"AllowedSenders":[,]}}')) {
        Set-Content -LiteralPath $configPath -Value $invalidJson -Encoding UTF8
        $script:ProbeCalls = 0
        $connection = Test-BridgeConnection $probeInstallation
        Assert-True ($connection.State -eq 'not_tested' -and $script:ProbeCalls -eq 0) 'Reject malformed JSON without guessing ports or reporting a successful connection.'
        Assert-True ($connection.Message -like '*appsettings.json*' -and $connection.Message -like '*JSON syntax*' -and $connection.Message -notlike '*AllowedSenders*') 'Identify the malformed file without dumping its contents into the installer UI.'
    }
    Set-Content -LiteralPath $configPath -Value $relaxedJson -Encoding UTF8
    $script:BridgeEnvironment = @{ReceivePort = '9250'}
    $settings = Get-BridgeProbeSettings $probeInstallation
    Assert-True ($settings.ReceivePort -eq 9250 -and $settings.SendPort -eq 9251) 'A higher-priority environment receive port also selects the next reply port.'
    $script:BridgeEnvironment.SendPort = '9252'
    Assert-True ((Get-BridgeProbeSettings $probeInstallation).SendPort -eq 9252) 'An explicit environment send port overrides the derived reply port.'
    $script:BridgeEnvironment = @{}
    foreach ($case in @(
        @('--port 9234', 9234, 9235), @('--receive-port=9234 --send-port=9236', 9234, 9236),
        @('9234 9236', 9234, 9236), @('--Osc:ReceivePort 9234 --Osc:SendPort 9236', 9234, 9236),
        @('--output-port 9236', 9123, 9236), @('--Osc:MaxDevices 32 --mock', 9123, 9134),
        @('', 8010, 8011))) {
        $probeInstallation.CommandLine = '"' + $probeExecutable + '" ' + $case[0]
        $settings = Get-BridgeProbeSettings $probeInstallation
        Assert-True ($settings.ReceivePort -eq $case[1] -and $settings.SendPort -eq $case[2]) "Match runtime port precedence for service arguments: $($case[0])."
    }
    foreach ($listenAddress in @('', '0.0.0.0', '192.168.2.210', 'bridge.example', '::1')) {
        @{Osc = @{ListenAddress = $listenAddress; ReplyAddress = '192.168.2.205'; ReceivePort = 9123; SendPort = 9134}} |
            ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
        $probeInstallation.CommandLine = '"' + $probeExecutable + '" --mock'
        Assert-True ((Get-BridgeProbeSettings $probeInstallation).Address -eq '127.0.0.1') "Ignore configured listen and reply hosts and use localhost: $listenAddress."
        $probeInstallation.CommandLine = '"' + $probeExecutable + '" --Osc:ListenAddress="' + $listenAddress + '" --mock'
        Assert-True ((Get-BridgeProbeSettings $probeInstallation).Address -eq '127.0.0.1') "Ignore command-line listen hosts and use localhost: $listenAddress."
    }
    $script:BridgeEnvironment = @{ListenAddress = '192.168.2.210'; ReplyAddress = '192.168.2.205'}
    Assert-True ((Get-BridgeProbeSettings $probeInstallation).Address -eq '127.0.0.1') 'Ignore machine environment addresses and use localhost.'
    $script:BridgeEnvironment = @{}
    $probeInstallation.CommandLine = '"' + $probeExecutable + '" --Osc:ReplyAddress 192.0.2.20 --mock'
    $script:ProbeCalls = 0
    $connection = Test-BridgeConnection $probeInstallation
    Assert-True ($connection.State -eq 'connected' -and $script:ProbeCalls -eq 1) 'A remote reply setting must not skip the localhost probe.'
    $probeInstallation.CommandLine = '"' + $probeExecutable + '" --port 9123 --send-port 9123'
    Assert-True ((Test-BridgeConnection $probeInstallation).State -eq 'not_tested') 'Report invalid port configuration without sending a ping.'
    $probeInstallation.CommandLine = '"' + $probeExecutable + '" --mock'
    $connection = Test-BridgeConnection $probeInstallation
    Assert-True ($connection.State -eq 'connected' -and $script:LastProbe[0] -eq 9123 -and $script:LastProbe[1] -eq 9134) 'Pass configured receive and fixed reply ports to the localhost UDP probe.'
    $script:ProbeCalls = 0
    Assert-True ((Test-BridgeConnection ([pscustomobject]@{Installed = $false})).State -eq 'not_installed' -and $script:ProbeCalls -eq 0) 'Do not ping an absent installation.'
    $script:InstalledKeys = @($serviceKey)
    $script:RegistryValues = @{"$serviceKey|ImagePath" = '"' + $probeExecutable + '" --mock'}
    $script:ExecutableVersions[$probeExecutable] = '0.1.9'
    $script:ApiFails = $true
    $status = Get-BridgeUpdateStatus -CheckConnection
    Assert-True ($status.ConnectionState -eq 'connected' -and $status.Error -eq 'Offline') 'Report a working bridge even if the online release check fails.'
    $script:ApiFails = $false
    $script:LastApi = ''
    $status = Get-BridgeUpdateStatus -CheckConnection -SkipReleaseCheck
    Assert-True ($status.ConnectionState -eq 'connected' -and -not $script:LastApi) 'A post-install connection check must not depend on GitHub.'
    $status.ConnectionMessage = "Connected`r`nto the bridge."
    $probeStatusPath = Join-Path $stage 'bridge-status.ini'
    Write-BridgeUpdateStatus $status $probeStatusPath
    $probeStatusLines = Get-Content -LiteralPath $probeStatusPath
    Assert-True ($probeStatusLines -contains 'ConnectionState=connected' -and $probeStatusLines -contains 'ConnectionMessage=Connected to the bridge.') 'Export a single-line connection result to the installer UI.'
    $script:InstalledKeys = @()
    $script:RegistryValues = @{}
    $script:ExecutableVersions = @{}

    $script:Release = [pscustomobject]@{draft = $false; prerelease = $false; assets = @(
        [pscustomobject]@{name = 'GEXMaestroBridgeSetup-0.1.10-x64.exe';
            browser_download_url = 'https://github.com/muchimi/GEXMaestroBridgeService/releases/download/0.1.10/GEXMaestroBridgeSetup-0.1.10-x64.exe'})}
    $script:InstalledKeys = @($uninstallKey)
    foreach ($version in @('0.1.9', '0.1.10', '0.1.10.0', '0.1.11', 'unknown')) {
        $script:RegistryValues = @{"$uninstallKey|DisplayVersion" = $version}
        $status = Get-BridgeUpdateStatus
        $expectedAction = if ($version -eq '0.1.9') { 'upgrade' } else { 'none' }
        Assert-True ($status.Action -eq $expectedAction) "Only offer an upgrade when a newer version is confirmed: installed $version."
        Assert-True ($status.LatestVersion -eq [version]'0.1.10.0') 'Report the available stable release version.'
    }
    $script:RegistryValues = @{"$uninstallKey|DisplayVersion" = '0.1.9'}
    $script:ApiFails = $true
    $status = Get-BridgeUpdateStatus
    Assert-True ($status.Installed -and $status.InstalledVersion -eq [version]'0.1.9.0') 'Keep installed version information when offline.'
    Assert-True ($status.Action -eq 'none' -and $status.Error -eq 'Offline') 'Do not offer an unconfirmed upgrade when offline.'
    $script:ApiFails = $false
    $script:InstalledKeys = @()
    $script:RegistryValues = @{}
    $status = Get-BridgeUpdateStatus
    Assert-True (-not $status.Installed -and $status.Action -eq 'install') 'Continue to offer a missing bridge when vJoy is absent.'
    $script:LastApi = ''
    $script:InstalledKeys = @('SYSTEM\CurrentControlSet\Services\vjoy')
    $status = Get-BridgeUpdateStatus
    Assert-True ($status.Action -eq 'install' -and $script:LastApi) 'Offer bridge installation when vJoy is installed and the bridge is absent.'
    $script:InstalledKeys = @($uninstallKey, 'SYSTEM\CurrentControlSet\Services\vjoy')
    $script:RegistryValues = @{"$uninstallKey|DisplayVersion" = '0.1.9'}
    $status = Get-BridgeUpdateStatus
    Assert-True ($status.Action -eq 'upgrade') 'Offer a confirmed upgrade for an existing bridge even when vJoy is installed.'
    $statusPath = Join-Path $stage 'bridge-status.ini'
    Write-BridgeUpdateStatus $status $statusPath
    $statusLines = Get-Content -LiteralPath $statusPath
    Assert-True ($statusLines -contains 'Installed=1' -and $statusLines -contains 'InstalledVersion=0.1.9' -and
        $statusLines -contains 'LatestVersion=0.1.10' -and $statusLines -contains 'Action=upgrade') 'Export the version and offer decision for the installer UI.'
    $script:RegistryValues["$uninstallKey|DisplayVersion"] = '0.1.11'
    Assert-True (-not (Test-DependencyNeeded bridge $status.Release.Version)) 'Rechecking after a concurrent upgrade prevents a downgrade.'
    $script:BridgeUninstallKey = $uninstallKey
    $script:ChildExitCode = 3010
    foreach ($version in @('0.1.9', '0.1.10', '0.1.11', 'unknown')) {
        $script:RegistryValues = @{"$uninstallKey|DisplayVersion" = $version}
        $script:Downloads = $script:SetupsStarted = 0
        $code = Invoke-DependencyInstall bridge $false
        if ($version -eq '0.1.9') {
            Assert-True ($code -eq 3010 -and $script:Downloads -eq 1 -and $script:SetupsStarted -eq 1) 'Launch a confirmed upgrade and preserve its restart exit code.'
        } else {
            Assert-True ($code -eq 0 -and $script:Downloads -eq 0 -and $script:SetupsStarted -eq 0) "Skip downloads and setup when an upgrade is not needed or confirmed: $version."
        }
    }
    $script:RegistryValues = @{"$uninstallKey|DisplayVersion" = '0.1.9'}
    $script:VersionAfterDownload = '0.1.11'
    $script:SetupsStarted = 0
    Assert-True ((Invoke-DependencyInstall bridge $false) -eq 0 -and $script:SetupsStarted -eq 0) 'Do not launch an older installer if another process upgrades the bridge during download.'
    $script:VersionAfterDownload = ''
    $script:ApiFails = $true
    $script:RegistryValues = @{"$uninstallKey|DisplayVersion" = '0.1.9'}
    $script:Downloads = $script:SetupsStarted = 0
    Assert-True ((Invoke-DependencyInstall bridge $false) -eq 0 -and $script:Downloads -eq 0 -and $script:SetupsStarted -eq 0) 'An unavailable release check must not trigger an installed-bridge download.'
    $script:ApiFails = $false
    $script:InstalledKeys = @()
    $script:RegistryValues = @{}

    foreach ($name in @('hidhide', 'bridge')) {
        $repo = if ($name -eq 'hidhide') { 'nefarius/HidHide' } else { 'muchimi/GEXMaestroBridgeService' }
        $assetName = if ($name -eq 'hidhide') { 'HidHide_1.5.230_x64.exe' } else { 'GEXMaestroBridgeSetup-0.1.0-x64.exe' }
        $asset = [pscustomobject]@{name = $assetName; browser_download_url = "https://github.com/$repo/releases/download/v1/$assetName"; digest = $null}
        $script:Release = [pscustomobject]@{draft = $false; prerelease = $false; assets = @($asset,
            [pscustomobject]@{name = 'source.zip'})}
        $script:Downloads = 0
        $download = Get-DependencyInstaller $name $stage
        Assert-True ($script:LastApi -eq "https://api.github.com/repos/$repo/releases/latest") 'Use the official latest release API.'
        Assert-True ($script:Downloads -eq 1) 'Download only the matching x64 setup.'
        $asset.digest = 'sha256:' + (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash
        Get-DependencyInstaller $name $stage | Out-Null
        $asset.digest = 'sha256:' + ('0' * 64)
        Assert-Throws { Get-DependencyInstaller $name $stage } 'Reject checksum mismatches.'
        $asset.digest = $null
        $script:Release.prerelease = $true
        Assert-Throws { Get-DependencyInstaller $name $stage } 'Reject prereleases.'
        $script:Release.prerelease = $false
        $script:Release.assets = @()
        Assert-Throws { Get-DependencyInstaller $name $stage } 'Report missing setup assets.'
        $script:Release.assets = @($asset, $asset)
        Assert-Throws { Get-DependencyInstaller $name $stage } 'Reject ambiguous setup assets.'
        $script:Release.assets = @($asset)
        $asset.browser_download_url = 'https://example.com/setup.exe'
        $script:Downloads = 0
        Assert-Throws { Get-DependencyInstaller $name $stage } 'Reject unexpected download origins.'
        Assert-True ($script:Downloads -eq 0) 'Validate the URL before downloading.'

        foreach ($code in @(0, 1602, 3010, 1641, 1)) {
            $script:ChildExitCode = $code
            Assert-True ((Invoke-DependencySetup $name 'C:\setup.exe' $false) -eq $code) 'Preserve child success, cancellation, failure and restart codes.'
            Assert-True ($script:LastArguments -contains '/norestart') 'Suppress automatic reboots.'
            Assert-True (-not $script:LastWindowStyle) 'Leave interactive setup visible.'
        }
        Invoke-DependencySetup $name 'C:\setup.exe' $true | Out-Null
        $quietFlag = if ($name -eq 'hidhide') { '/quiet' } else { '/VERYSILENT' }
        Assert-True ($script:LastArguments -contains $quietFlag) 'Use the correct quiet switch.'
        Assert-True ($script:LastWindowStyle -eq 'Hidden') 'Hide explicitly silent setup.'
        if ($name -eq 'bridge') { Assert-True ($script:LastVerb -eq 'RunAs') 'Request elevation when GremlinEx launches bridge setup.' }
    }
} finally {
    # Only these known paths are created by this test; no recursive deletion.
    Remove-Item -LiteralPath (Join-Path $stage 'dependency-setup.exe') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $stage 'bridge-status.ini') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $stage 'appsettings.json') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stage -Force
}
Write-Host "Passed $script:Checks dependency checks. No installers were run."
