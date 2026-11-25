$ErrorActionPreference = 'Stop'
$helper = Join-Path $PSScriptRoot 'release.ps1'
$status = Join-Path ([IO.Path]::GetTempPath()) ('gremlinex-test-' + [guid]::NewGuid() + '.txt')
$downloadBase = 'https://github.com/muchimi/JoystickGremlinEx/releases/download'

function New-Asset($Name, $Tag = 'm77_series') {
    [pscustomobject]@{
        name = $Name
        state = 'uploaded'
        browser_download_url = "$downloadBase/$Tag/$Name"
    }
}

function Invoke-RestMethod($Uri, $Headers, $TimeoutSec) {
    switch -CaseSensitive ($Uri) {
        'https://api.github.com/repos/muchimi/JoystickGremlinEx/releases/tags/m77_series' {
            return $tagLookupResult
        }
        'https://api.github.com/repos/muchimi/JoystickGremlinEx/releases?per_page=100' {
            # Windows PowerShell can return the JSON array as a single pipeline object.
            return ,$releases
        }
        default { throw "Unexpected release endpoint: $Uri" }
    }
}

function Assert-Update($Current, $Expected = '') {
    & $helper -Action check-installer -CurrentVersion $Current -Destination $status
    if ($LASTEXITCODE -ne 0) { throw "Update check failed for $Current." }
    if ($Expected) {
        $lines = @(Get-Content -LiteralPath $status)
        if ($lines.Count -ne 2 -or $lines[0] -cne $Expected -or
            $lines[1] -cne "$downloadBase/m77_series/$Expected") {
            throw "Unexpected update result for $Current."
        }
        Remove-Item -LiteralPath $status
    } elseif (Test-Path -LiteralPath $status) {
        throw "An update was offered for $Current."
    }
}

$otherHost = New-Asset 'GremlinEx-Setup-1.0ex-m99.exe'
$otherHost.browser_download_url = 'https://example.com/redirect'
$incomplete = New-Asset 'GremlinEx-Setup-1.0ex-m98.exe'
$incomplete.state = 'starter'
$releases = @(
    [pscustomobject]@{
        tag_name = 'm77_series'
        draft = $false
        prerelease = $true
        assets = @(
            (New-Asset 'GremlinEx-Setup-1.0ex-m77T99.exe')
            (New-Asset 'GremlinEx-Setup-1.0ex-m77T110.exe')
            (New-Asset 'GremlinEx-Setup-1.0ex-m77T110A.exe')
            (New-Asset 'gremlinEx_1_0_m77T111.zip')
            $otherHost
            $incomplete
        )
    }
    [pscustomobject]@{
        tag_name = 'm78_series'
        draft = $false
        assets = @((New-Asset 'GremlinEx-Setup-1.0ex-m78.exe' 'm78_series'))
    }
)
$tagLookupResult = $releases[0]

try {
    Assert-Update '1.0ex-m77T99' 'GremlinEx-Setup-1.0ex-m77T110A.exe'
    Assert-Update '1.0ex-m77T110' 'GremlinEx-Setup-1.0ex-m77T110A.exe'
    Assert-Update '1.0ex-m77T110A'
    Assert-Update '1.0ex-m77T111'
    Assert-Update '1.0ex-m77'
    $tagLookupResult = $releases[1]
    Assert-Update '1.0ex-m77T110'
    & $helper -Action list -Destination $status
    if (((Get-Content -LiteralPath $status) -join ',') -cne 'gremlinEx_1_0_m77T111.zip') {
        throw 'The online installer ZIP list changed.'
    }
    Write-Host 'GremlinEx release checks passed.'
} finally {
    if (Test-Path -LiteralPath $status) { Remove-Item -LiteralPath $status }
}
