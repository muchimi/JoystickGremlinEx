param(
    [Parameter(Mandatory)][ValidateSet('hidhide', 'bridge')][string]$Component,
    [switch]$Silent,
    [switch]$CheckOnly,
    [switch]$ConnectionOnly,
    [string]$StatusFile
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
    param([string]$Name, [version]$AvailableVersion)
    if ($Name -eq 'hidhide') {
        return -not ((Test-RegistryKey LocalMachine 'SYSTEM\CurrentControlSet\Services\HidHide') -or
            (Test-RegistryKey ClassesRoot 'Installer\Dependencies\NSS.Drivers.HidHide.x64'))
    }
    $installed = Get-BridgeInstallation
    if ($installed.Installed) {
        return ($null -ne $installed.Version -and $null -ne $AvailableVersion -and $AvailableVersion -gt $installed.Version)
    }
    return -not (Test-RegistryKey LocalMachine 'SYSTEM\CurrentControlSet\Services\vjoy')
}

function Get-RegistryValue {
    param([string]$Path, [string]$Name)
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
        $root = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
        try {
            $key = $root.OpenSubKey($Path)
            if ($null -ne $key) {
                try {
                    $value = $key.GetValue($Name)
                    if ($null -ne $value -and "$value" -ne '') { return [string]$value }
                } finally { $key.Dispose() }
            }
        } finally { $root.Dispose() }
    }
    return ''
}

function ConvertTo-BridgeVersion {
    param([string]$Value)
    # Normalize a missing .NET revision to zero; informational versions may add a commit hash.
    if ($Value -match '^\s*v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:\+[0-9A-Za-z.-]+)?\s*$') {
        $revision = if ($Matches[4]) { $Matches[4] } else { '0' }
        $parsed = $null
        if ([version]::TryParse("$($Matches[1]).$($Matches[2]).$($Matches[3]).$revision", [ref]$parsed)) {
            return $parsed
        }
    }
    return $null
}

function Get-BridgeExecutableVersion {
    param([string]$Path)
    $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
    $version = ConvertTo-BridgeVersion $info.ProductVersion
    if ($null -eq $version) { $version = ConvertTo-BridgeVersion $info.FileVersion }
    return $version
}

function Get-BridgeInstallation {
    $serviceKey = 'SYSTEM\CurrentControlSet\Services\GEXMaestroBridgeService'
    $uninstallKey = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D26DA10A-73A7-482A-A711-6B7E04C8D8A0}_is1'
    $installed = (Test-RegistryKey LocalMachine $serviceKey) -or (Test-RegistryKey LocalMachine $uninstallKey)
    $candidates = @()
    $existingPath = ''
    $imagePath = Get-RegistryValue $serviceKey 'ImagePath'
    if ($imagePath -match '^\s*"([^"]+\.exe)"' -or $imagePath -match '^\s*(.+?\.exe)(?:\s|$)') {
        $candidates += [Environment]::ExpandEnvironmentVariables($Matches[1])
    }
    $location = Get-RegistryValue $uninstallKey 'InstallLocation'
    if ($location) { $candidates += Join-Path $location 'GEXMaestroBridgeService.exe' }
    $candidates += Join-Path $env:SystemDrive 'GremlinEx\GEXMaestroBridge\GEXMaestroBridgeService.exe'
    foreach ($programFilesPath in @($env:ProgramW6432, $env:ProgramFiles)) {
        if ($programFilesPath) { $candidates += Join-Path $programFilesPath 'GEXMaestroBridge\GEXMaestroBridgeService.exe' }
    }
    foreach ($path in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $path) {
            $installed = $true
            if (-not $existingPath) { $existingPath = $path }
            try { $version = Get-BridgeExecutableVersion $path } catch { $version = $null }
            if ($null -ne $version) { return [pscustomobject]@{Installed = $true; Version = $version; Path = $path; CommandLine = $imagePath} }
        }
    }
    $version = if ($installed) { ConvertTo-BridgeVersion (Get-RegistryValue $uninstallKey 'DisplayVersion') } else { $null }
    return [pscustomobject]@{Installed = [bool]$installed; Version = $version; Path = $existingPath; CommandLine = $imagePath}
}

function Get-BridgeEnvironmentValue {
    param([string]$Name)
    return [Environment]::GetEnvironmentVariable("MAESTRO_Osc__$Name", [EnvironmentVariableTarget]::Machine)
}

function ConvertFrom-BridgeSettingsJson {
    param([string]$Json)
    # The bridge's .NET configuration reader accepts comments and trailing commas,
    # but Windows PowerShell 5.1's ConvertFrom-Json rejects them. Preserve strings
    # as complete tokens so paths, URLs and escaped quotes are left unchanged.
    $stringToken = '"(?:[^"\\]|\\.)*"'
    $withoutComments = [regex]::Replace($Json, $stringToken + '|//[^\r\n]*|/\*[\s\S]*?\*/', {
        param($match)
        if ($match.Value.StartsWith('"')) { return $match.Value }
        return [regex]::Replace($match.Value, '[^\r\n]', ' ')
    })
    $normalized = [regex]::Replace($withoutComments, $stringToken + '|,(?=\s*[}\]])', {
        param($match)
        if ($match.Value -eq ',') {
            $previous = $match.Index - 1
            while ($previous -ge 0 -and [char]::IsWhiteSpace($withoutComments[$previous])) { $previous-- }
            if ($previous -lt 0 -or '{[:,'.Contains([string]$withoutComments[$previous])) {
                throw 'Invalid trailing comma: a JSON value is missing.'
            }
            return ''
        }
        return $match.Value
    })
    return ConvertFrom-Json -InputObject $normalized
}

function Get-BridgeProbeSettings {
    param($Installation)
    # Setup tests only localhost. Remote bridge addresses are configured in GEX after setup.
    $settings = [pscustomobject]@{Address = '127.0.0.1'; ReceivePort = 8010; SendPort = 8011}
    if ($Installation.Path) {
        $configPath = Join-Path (Split-Path -Parent $Installation.Path) 'appsettings.json'
        if (Test-Path -LiteralPath $configPath) {
            try {
                $osc = (ConvertFrom-BridgeSettingsJson (Get-Content -LiteralPath $configPath -Raw)).Osc
            } catch {
                throw "Cannot read bridge UDP ports from '$configPath'. Check the file's JSON syntax and read permissions."
            }
            if ($null -ne $osc) {
                if ($null -ne $osc.ReceivePort) { $settings.ReceivePort = [int]$osc.ReceivePort }
                if ($null -ne $osc.SendPort) { $settings.SendPort = [int]$osc.SendPort }
                elseif ($null -ne $osc.ReceivePort) { $settings.SendPort = $settings.ReceivePort + 1 }
            }
        }
    }
    # Machine environment overrides apply to the installed Windows service.
    foreach ($name in @('ReceivePort', 'SendPort')) {
        $value = Get-BridgeEnvironmentValue $name
        if ($null -ne $value) {
            $settings.$name = [int]$value
            if ($name -eq 'ReceivePort') { $settings.SendPort = $settings.ReceivePort + 1 }
        }
    }
    # Port switches override JSON. A receive-only override selects receive + 1.
    $arguments = ''
    if ($Installation.CommandLine -match '^\s*(?:"[^"]+\.exe"|.+?\.exe)(.*)$') { $arguments = $Matches[1].Trim() }
    $receiveOverride = $null
    $sendOverride = $null
    $tokens = @([regex]::Matches($arguments, '"([^"]*)"|(\S+)') | ForEach-Object {
        if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value }
    })
    for ($index = 0; $index -lt $tokens.Count; $index++) {
        $token = $tokens[$index]
        if ($token -match '^\d+$') {
            if ($null -eq $receiveOverride) { $receiveOverride = [int]$token } else { $sendOverride = [int]$token }
        } elseif ($token -match '^(?:--?|/)(port|receive-port|udp-port|Osc:ReceivePort|output-port|send-port|Osc:SendPort)(?:=(.*))?$') {
            $key = $Matches[1]
            $value = if ($token.Contains('=')) { $Matches[2] } elseif (++$index -lt $tokens.Count) { $tokens[$index] } else { throw "Missing value for $token" }
            $value = $value.Trim('"')
            switch -Regex ($key) {
                '^(port|receive-port|udp-port|Osc:ReceivePort)$' { $receiveOverride = [int]$value; break }
                '^(output-port|send-port|Osc:SendPort)$' { $sendOverride = [int]$value; break }
            }
        } elseif ($token -match '^(?:--?|/)[^=]+$' -and $token -notmatch '^(?:--?|/)mock$' -and $index + 1 -lt $tokens.Count) {
            # Skip unrelated configuration values, which might themselves be numeric.
            $index++
        }
    }
    if ($null -ne $receiveOverride) {
        $settings.ReceivePort = $receiveOverride
        $settings.SendPort = $receiveOverride + 1
    }
    if ($null -ne $sendOverride) { $settings.SendPort = $sendOverride }
    if ($Installation.CommandLine -and -not $arguments) {
        # Current bridge startup explicitly selects 8010/8011 when started without arguments.
        $settings.ReceivePort = 8010
        $settings.SendPort = 8011
    }
    if ($settings.ReceivePort -lt 1 -or $settings.ReceivePort -gt 65535 -or
        $settings.SendPort -lt 1 -or $settings.SendPort -gt 65535 -or $settings.ReceivePort -eq $settings.SendPort) {
        throw 'The bridge receive and reply ports must be different and between 1 and 65535.'
    }
    return $settings
}

function New-BridgeOscPacket {
    param([int]$RequestId, [switch]$Pong)
    $stream = New-Object IO.MemoryStream
    try {
        $strings = if ($Pong) { @('/maestro_pong', ',isi') } else { @('/maestro_ping', ',i') }
        foreach ($value in $strings) {
            $bytes = [Text.Encoding]::UTF8.GetBytes($value)
            $stream.Write($bytes, 0, $bytes.Length)
            do { $stream.WriteByte(0) } while ($stream.Length % 4 -ne 0)
        }
        $bytes = [BitConverter]::GetBytes($RequestId)
        if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($bytes) }
        $stream.Write($bytes, 0, 4)
        if ($Pong) {
            $bytes = [Text.Encoding]::UTF8.GetBytes('MaestroOscService')
            $stream.Write($bytes, 0, $bytes.Length)
            do { $stream.WriteByte(0) } while ($stream.Length % 4 -ne 0)
            $stream.Write([byte[]]@(0, 0, 0, 1), 0, 4)
        }
        return ,$stream.ToArray()
    } finally { $stream.Dispose() }
}

function Test-BridgeOscPing {
    param([int]$ReceivePort = 8010, [int]$SendPort = 8011,
          [int]$TimeoutMilliseconds = 2000)
    $Address = '127.0.0.1'
    $receiver = $sender = $null
    try {
        $receiver = New-Object Net.Sockets.UdpClient([Net.Sockets.AddressFamily]::InterNetwork)
        $receiver.ExclusiveAddressUse = $true
        try { $receiver.Client.Bind((New-Object Net.IPEndPoint([Net.IPAddress]::Loopback, $SendPort))) }
        catch {
            return [pscustomobject]@{State = 'port_unavailable'; Message = "Cannot test the bridge: reply UDP port $SendPort is unavailable. Close GEX or other clients and retry."}
        }
        $requestId = Get-Random -Minimum 1 -Maximum 2147483647
        $packet = New-BridgeOscPacket $requestId
        $expected = [Convert]::ToBase64String((New-BridgeOscPacket $requestId -Pong))
        $sender = New-Object Net.Sockets.UdpClient([Net.Sockets.AddressFamily]::InterNetwork)
        [void]$sender.Send($packet, $packet.Length, $Address, $ReceivePort)
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $invalidPong = $false
        while ($timer.ElapsedMilliseconds -lt $TimeoutMilliseconds) {
            $receiver.Client.ReceiveTimeout = [Math]::Max(1, $TimeoutMilliseconds - [int]$timer.ElapsedMilliseconds)
            $remote = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0)
            try { $reply = $receiver.Receive([ref]$remote) } catch { break }
            if ($remote.Address.ToString() -ne $Address) { continue }
            if ([Convert]::ToBase64String($reply) -ceq $expected) {
                return [pscustomobject]@{State = 'connected'; Message = "Connected to GEX Maestro Bridge on localhost (${Address}:$ReceivePort; OSC protocol 1; reply UDP $SendPort)."}
            }
            if ([Text.Encoding]::ASCII.GetString($reply).StartsWith("/maestro_pong`0")) { $invalidPong = $true }
        }
        $message = if ($invalidPong) { 'The reply did not match the ping request, service name or OSC protocol 1.' }
                   else { 'No OSC ping reply from localhost. Check that the bridge is running locally and listening on these UDP ports. Configure remote bridges in GEX after setup.' }
        return [pscustomobject]@{State = 'failed'; Message = "Localhost bridge connection to ${Address}:$ReceivePort failed: $message"}
    } catch {
        return [pscustomobject]@{State = 'failed'; Message = "Localhost bridge connection test failed: $($_.Exception.GetBaseException().Message)"}
    } finally {
        if ($null -ne $sender) { $sender.Close() }
        if ($null -ne $receiver) { $receiver.Close() }
    }
}

function Test-BridgeConnection {
    param($Installation)
    if (-not $Installation.Installed) {
        return [pscustomobject]@{State = 'not_installed'; Message = 'No local GEX Maestro Bridge installation was detected; localhost connectivity has not been tested.'}
    }
    try {
        $settings = Get-BridgeProbeSettings $Installation
        return Test-BridgeOscPing -ReceivePort $settings.ReceivePort -SendPort $settings.SendPort
    } catch {
        return [pscustomobject]@{State = 'not_tested'; Message = "Localhost bridge connection could not be tested: $($_.Exception.Message)"}
    }
}

function Get-DependencyRelease {
    param([string]$Name)
    if ($Name -eq 'hidhide') {
        $repository = 'nefarius/HidHide'
        $pattern = '^HidHide_[0-9.]+_x64\.exe$'
    } else {
        $repository = 'muchimi/GEXMaestroBridgeService'
        $pattern = '^GEXMaestroBridgeSetup-[0-9.]+-x64\.exe$'
    }
    $headers = @{'User-Agent' = 'GremlinEx-Installer'; 'Accept' = 'application/vnd.github+json'}
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repository/releases/latest" -Headers $headers -TimeoutSec 15
    if ($release.draft -or $release.prerelease) { throw 'A stable dependency release is required.' }
    $assets = @($release.assets | Where-Object { $_.name -cmatch $pattern })
    if ($assets.Count -ne 1) { throw "No unique x64 setup asset was found in $repository. Install it separately from the project's releases." }
    $asset = $assets[0]
    if (-not $asset.browser_download_url.StartsWith("https://github.com/$repository/releases/download/", [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unexpected dependency download location.'
    }
    $version = $null
    if ($Name -eq 'bridge') {
        $version = ConvertTo-BridgeVersion ($asset.name -replace '^GEXMaestroBridgeSetup-|\-x64\.exe$', '')
        if ($null -eq $version) { throw 'The bridge release does not have a valid version.' }
    }
    return [pscustomobject]@{Asset = $asset; Headers = $headers; Version = $version}
}

function Get-BridgeUpdateStatus {
    param([switch]$CheckConnection, [switch]$SkipReleaseCheck)
    $installed = Get-BridgeInstallation
    $status = [pscustomobject]@{
        Installed = $installed.Installed; InstalledVersion = $installed.Version
        LatestVersion = $null; Action = 'none'; Release = $null; Error = ''
        ConnectionState = 'not_tested'; ConnectionMessage = 'The bridge connection was not tested.'
    }
    if ($CheckConnection) {
        $connection = Test-BridgeConnection $installed
        $status.ConnectionState = $connection.State
        $status.ConnectionMessage = $connection.Message
    }
    if ($SkipReleaseCheck) { return $status }
    if (-not $installed.Installed) {
        if (Test-RegistryKey LocalMachine 'SYSTEM\CurrentControlSet\Services\vjoy') { return $status }
        $status.Action = 'install'
    }
    try {
        $status.Release = Get-DependencyRelease 'bridge'
        $status.LatestVersion = $status.Release.Version
        if ($installed.Installed -and $null -ne $installed.Version -and $status.LatestVersion -gt $installed.Version) {
            $status.Action = 'upgrade'
        }
    } catch { $status.Error = [string]$_ }
    return $status
}

function Write-BridgeUpdateStatus {
    param($Status, [string]$Path)
    $installedVersion = ''
    $latestVersion = ''
    if ($null -ne $Status.InstalledVersion) {
        $parts = if ($Status.InstalledVersion.Revision -eq 0) { 3 } else { 4 }
        $installedVersion = $Status.InstalledVersion.ToString($parts)
    }
    if ($null -ne $Status.LatestVersion) {
        $parts = if ($Status.LatestVersion.Revision -eq 0) { 3 } else { 4 }
        $latestVersion = $Status.LatestVersion.ToString($parts)
    }
    @('[Bridge]', "Installed=$([int]$Status.Installed)", "InstalledVersion=$installedVersion",
      "LatestVersion=$latestVersion", "Action=$($Status.Action)", "ConnectionState=$($Status.ConnectionState)",
      "ConnectionMessage=$($Status.ConnectionMessage -replace '[\r\n]+', ' ')") | Set-Content -LiteralPath $Path -Encoding Unicode
}

function Get-DependencyInstaller {
    param([string]$Name, [string]$Stage, $Release = $null)
    if ($null -eq $Release) { $Release = Get-DependencyRelease $Name }
    $asset = $Release.Asset
    $download = Join-Path $Stage 'dependency-setup.exe'
    Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -Headers $Release.Headers -OutFile $download -TimeoutSec 600
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

function Invoke-DependencyInstall {
    param([string]$Name, [bool]$Quiet)
    $stage = $null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $release = $null
        if ($Name -eq 'bridge') {
            $status = Get-BridgeUpdateStatus
            if ($status.Action -eq 'none') {
                Write-Host "Bridge installation or upgrade is not needed or could not be confirmed; skipping. $($status.Error)"
                return 0
            }
            if ($null -eq $status.Release) { throw $status.Error }
            $release = $status.Release
        }
        # Recheck immediately before installing in case the machine changed since task selection.
        if (-not (Test-DependencyNeeded $Name $release.Version)) {
            Write-Host "$Name is already installed or no longer needed; skipping."
            return 0
        }
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        $stage = Join-Path $tempRoot ('gremlinex-dependency-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $stage | Out-Null
        $InstallerPath = Get-DependencyInstaller $Name $stage $release
        if (-not (Test-DependencyNeeded $Name $release.Version)) {
            Write-Host "$Name was installed or upgraded while downloading; skipping."
            return 0
        }
        $exitCode = Invoke-DependencySetup $Name $InstallerPath $Quiet
    } catch {
        Write-Warning "Optional $Name installation failed: $_"
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
    return $exitCode
}

# Dot-sourcing exposes the functions for verification without running an installer.
if ($MyInvocation.InvocationName -eq '.') { return }
if ($CheckOnly) {
    try {
        if ($Component -ne 'bridge') { throw 'CheckOnly is supported for the bridge component.' }
        if (-not $StatusFile) { throw 'StatusFile is required when checking bridge updates.' }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-BridgeUpdateStatus (Get-BridgeUpdateStatus -CheckConnection -SkipReleaseCheck:$ConnectionOnly) $StatusFile
        exit 0
    } catch {
        Write-Warning "Unable to check the bridge version: $_"
        exit 1
    }
}
exit (Invoke-DependencyInstall $Component ([bool]$Silent))
