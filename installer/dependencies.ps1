param(
    [Parameter(Mandatory)][ValidateSet('hidhide', 'bridge')][string]$Component,
    [switch]$Silent
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Test-RegistryKey {
    param([Microsoft.Win32.RegistryHive]$Hive, [string]$Path)
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
        $root = [Microsoft.Win32.RegistryKey]::OpenBaseKey($Hive, $view)
        try {
            $key = $root.OpenSubKey($Path)
            if ($null -ne $key) {
                $key.Dispose()
                return $true
            }
        } finally { $root.Dispose() }
    }
    return $false
}

function Test-DependencyNeeded {
    param([string]$Name)
    if ($Name -eq 'hidhide') {
        return -not ((Test-RegistryKey LocalMachine 'SYSTEM\CurrentControlSet\Services\HidHide') -or
            (Test-RegistryKey ClassesRoot 'Installer\Dependencies\NSS.Drivers.HidHide.x64'))
    }
    return -not ((Test-RegistryKey LocalMachine 'SYSTEM\CurrentControlSet\Services\vjoy') -or
        (Test-RegistryKey LocalMachine 'SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService') -or
        (Test-RegistryKey LocalMachine 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1') -or
        (Test-Path -LiteralPath (Join-Path $env:ProgramW6432 'GEXMaestroBridge\GEXMaestroBridgeService.exe')))
}

function Get-DependencyInstaller {
    param([string]$Name, [string]$Stage)
    if ($Name -eq 'hidhide') {
        $repository = 'nefarius/HidHide'
        $pattern = '^HidHide_[0-9.]+_x64\.exe$'
    } else {
        $repository = 'muchimi/GEXMaestroBridgeService'
        $pattern = '^GEXMaestroBridgeSetup-[0-9.]+-x64\.exe$'
    }
    $headers = @{'User-Agent' = 'GremlinEx-Installer'; 'Accept' = 'application/vnd.github+json'}
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repository/releases/latest" -Headers $headers -TimeoutSec 30
    if ($release.draft -or $release.prerelease) { throw 'A stable dependency release is required.' }
    $assets = @($release.assets | Where-Object { $_.name -cmatch $pattern })
    if ($assets.Count -ne 1) { throw "No unique x64 setup asset was found in $repository. Install it separately from the project's releases." }
    $asset = $assets[0]
    if (-not $asset.browser_download_url.StartsWith("https://github.com/$repository/releases/download/", [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unexpected dependency download location.'
    }
    $download = Join-Path $Stage 'dependency-setup.exe'
    Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -Headers $headers -OutFile $download -TimeoutSec 600
    if ((Get-Item -LiteralPath $download).Length -lt 1024) { throw 'Dependency download is unexpectedly small.' }
    if ($asset.digest -match '^sha256:([a-fA-F0-9]{64})$') {
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ine $Matches[1]) {
            throw 'Dependency download checksum mismatch.'
        }
    }
    return $download
}

function Invoke-DependencySetup {
    param([string]$Name, [string]$SetupPath, [bool]$Quiet)
    if ($Name -eq 'hidhide') {
        $arguments = @('/norestart')
        if ($Quiet) { $arguments += '/quiet' }
    } else {
        $arguments = @('/NORESTART', '/RESTARTEXITCODE=3010')
        if ($Quiet) { $arguments += @('/VERYSILENT', '/SUPPRESSMSGBOXES') }
    }
    $processOptions = @{FilePath = $SetupPath; ArgumentList = $arguments; Wait = $true; PassThru = $true}
    if ($Name -eq 'bridge') { $processOptions.Verb = 'RunAs' }
    if ($Quiet) { $processOptions.WindowStyle = 'Hidden' }
    $process = Start-Process @processOptions
    return $process.ExitCode
}

# Dot-sourcing exposes the functions for verification without running an installer.
if ($MyInvocation.InvocationName -eq '.') { return }

$stage = $null
try {
    # Recheck immediately before installing in case the machine changed since task selection.
    if (-not (Test-DependencyNeeded $Component)) {
        Write-Host "$Component is already installed or no longer needed; skipping."
        exit 0
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $stage = Join-Path $tempRoot ('gremlinex-dependency-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    $InstallerPath = Get-DependencyInstaller $Component $stage
    $exitCode = Invoke-DependencySetup $Component $InstallerPath ([bool]$Silent)
} catch {
    Write-Warning "Optional $Component installation failed: $_"
    $exitCode = 1
} finally {
    if ($stage) {
        $resolvedStage = [IO.Path]::GetFullPath($stage)
        if ([IO.Path]::GetDirectoryName($resolvedStage) -eq $tempRoot.TrimEnd('\') -and
            [IO.Path]::GetFileName($resolvedStage) -match '^gremlinex-dependency-[a-f0-9]{32}$') {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
exit $exitCode
