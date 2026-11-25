param(
 [ValidateSet('list','managed','portable','check-installer')][string]$Action,
 [string]$Asset='',
 [string]$CurrentVersion='',
 [Parameter(Mandatory)][string]$Destination
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$repository='muchimi/JoystickGremlinEx'
$releasesApi="https://api.github.com/repos/$repository/releases"
$installerReleaseTag='m77_series'
$headers=@{'User-Agent'='GremlinEx-Installer';'Accept'='application/vnd.github+json'}
$zipPattern='^gremlinEx_(\d+)_(\d+)_m(\d+)(?:(RC|T)(\d+)([A-Za-z]?))?\.zip$'
$installerPattern='^GremlinEx-Setup-(\d+)\.(\d+)(?:ex)?-m(\d+)(?:(RC|T)(\d+)([A-Za-z]*))?\.exe$'
$versionFields = 'Major', 'Minor', 'Milestone', 'Priority', 'Build', 'Revision'

function Get-AssetVersion($Name, $Pattern) {
 if ($Name -cnotmatch $Pattern) { return }
 $kind = if ($Matches[4] -eq 'T') { 'Test' } elseif ($Matches[4] -eq 'RC') { 'RC' } else { 'Production' }
 [pscustomobject]@{
  Name = $Name
  Url = ''
  Kind = $kind
  Major = [int]$Matches[1]
  Minor = [int]$Matches[2]
  Milestone = [int]$Matches[3]
  Priority = if ($kind -eq 'Production') { 2 } elseif ($kind -eq 'RC') { 1 } else { 0 }
  Build = [int]$Matches[5]
  Revision = ([string]$Matches[6]).ToUpperInvariant()
 }
}

function Get-Assets($Uri, $Pattern, $TimeoutSec, [switch]$Installer) {
 $releases=Invoke-RestMethod -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSec
 $items=foreach($release in $releases) {
  if($release.draft) { continue }
  if ($Installer -and $release.tag_name -cne $installerReleaseTag) { continue }
  foreach($a in $release.assets) {
   $version = Get-AssetVersion $a.name $Pattern
   if ($null -eq $version) { continue }
   if ($Installer) {
    $tag = [uri]::EscapeDataString([string]$release.tag_name)
    $expectedUrl = "https://github.com/$repository/releases/download/$tag/$($a.name)"
    if ($a.state -ne 'uploaded' -or $a.browser_download_url -cne $expectedUrl) { continue }
   }
   $version.Url = $a.browser_download_url
   $version
  }
 }
 return @($items | Sort-Object -Property $versionFields -Descending)
}

if ($Action -eq 'check-installer') {
 $current = Get-AssetVersion "GremlinEx-Setup-$CurrentVersion.exe" $installerPattern
 if ($null -eq $current) { throw "Unrecognized GremlinEx installer version: $CurrentVersion" }
 $latest = Get-Assets "$releasesApi/tags/$installerReleaseTag" $installerPattern 8 -Installer | Select-Object -First 1
 if ($null -eq $latest) { exit 0 }
 foreach ($field in $versionFields) {
  if ($latest.$field -eq $current.$field) { continue }
  if ($latest.$field -gt $current.$field) {
   Set-Content -LiteralPath $Destination -Encoding ASCII -Value @($latest.Name, $latest.Url)
  }
  break
 }
 exit 0
}

$items=@(Get-Assets "$($releasesApi)?per_page=100" $zipPattern 30)
if($Action -eq 'list') {
 $items.Name | Set-Content -LiteralPath $Destination -Encoding UTF8
 exit 0
}
$selected=@($items | Where-Object Name -CEQ $Asset)
if($selected.Count -ne 1) { throw "Release asset not found or ambiguous: $Asset" }
if(-not [IO.Path]::IsPathRooted($Destination)) { throw 'Destination must be an absolute path.' }
$Destination=[IO.Path]::GetFullPath($Destination)
$stage=Join-Path ([IO.Path]::GetTempPath()) ('gremlinex-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
 $zip=Join-Path $stage 'release.zip'
 Invoke-WebRequest -Uri $selected[0].Url -Headers $headers -OutFile $zip -TimeoutSec 180
 if((Get-Item $zip).Length -lt 1024) { throw 'Downloaded ZIP is unexpectedly small.' }
 $expanded=Join-Path $stage 'expanded'
 Expand-Archive -LiteralPath $zip -DestinationPath $expanded -Force
 $entries=@(Get-ChildItem -LiteralPath $expanded -Force)
 $source=$expanded
 if($entries.Count -eq 1 -and $entries[0].PSIsContainer) { $source=$entries[0].FullName }
 if($Action -eq 'managed') {
  $registry='HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
  $running=@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Destination+'\',[StringComparison]::OrdinalIgnoreCase) })
  if($running.Count) { throw 'Close GremlinEx before upgrading.' }
  $backup=Join-Path $stage 'backup'
  if(Test-Path -LiteralPath $Destination) {
   Copy-Item -LiteralPath $Destination -Destination $backup -Recurse -Force
  }
  try {
   New-Item -ItemType Directory -Force -Path $Destination | Out-Null
   Copy-Item -Path (Join-Path $source '*') -Destination $Destination -Recurse -Force
   Set-Content -LiteralPath (Join-Path $Destination '.gremlinex-installed-version') -Value $Asset -Encoding UTF8
  } catch {
   if(Test-Path -LiteralPath $backup) {
    Copy-Item -Path (Join-Path $backup '*') -Destination $Destination -Recurse -Force
   }
   throw
  }
 } else {
  if((Test-Path -LiteralPath $Destination) -and @(Get-ChildItem -LiteralPath $Destination -Force).Count -gt 0) {
   throw 'Portable destination must be empty to prevent overwriting files.'
  }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Copy-Item -Path (Join-Path $source '*') -Destination $Destination -Recurse -Force
  Set-Content -LiteralPath (Join-Path $Destination '.gremlinex-installed-version') -Value $Asset -Encoding UTF8
 }
} finally {
 Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
