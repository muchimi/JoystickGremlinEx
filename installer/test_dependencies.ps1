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
function Test-Path { param($LiteralPath) return $script:ConsoleBridgeInstalled }
$script:InstalledKeys = @()
$script:ConsoleBridgeInstalled = $false
Assert-True (Test-DependencyNeeded hidhide) 'Offer missing HidHide.'
Assert-True (Test-DependencyNeeded bridge) 'Offer bridge when no virtual-controller provider exists.'
foreach ($path in @('SYSTEM\CurrentControlSet\Services\HidHide', 'Installer\Dependencies\NSS.Drivers.HidHide.x64')) {
    $script:InstalledKeys = @($path)
    Assert-True (-not (Test-DependencyNeeded hidhide)) "Skip installed HidHide: $path"
}
foreach ($path in @('SYSTEM\CurrentControlSet\Services\vjoy',
    'SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService',
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1')) {
    $script:InstalledKeys = @($path)
    Assert-True (-not (Test-DependencyNeeded bridge)) "Skip bridge: $path"
}
$script:InstalledKeys = @()
$script:ConsoleBridgeInstalled = $true
Assert-True (-not (Test-DependencyNeeded bridge)) 'Skip an existing console bridge.'

function Invoke-RestMethod {
    param($Uri, $Headers, $TimeoutSec)
    $script:LastApi = $Uri
    return $script:Release
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, $Uri, $Headers, $OutFile, $TimeoutSec)
    $script:Downloads++
    [IO.File]::WriteAllBytes($OutFile, (New-Object byte[] 2048))
}
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $WindowStyle, $Verb)
    $script:LastArguments = $ArgumentList
    $script:LastWindowStyle = $WindowStyle
    $script:LastVerb = $Verb
    return [pscustomobject]@{ExitCode = $script:ChildExitCode}
}

$stage = Join-Path ([IO.Path]::GetTempPath()) ('gremlinex-dependency-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
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
    # Only these two known paths are created by this test; no recursive deletion.
    Remove-Item -LiteralPath (Join-Path $stage 'dependency-setup.exe') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stage -Force
}
Write-Host "Passed $script:Checks dependency checks. No installers were run."
