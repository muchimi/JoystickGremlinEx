param(
 [ValidateSet('list','managed','portable')][string]$Action,
 [string]$Asset='',
 [Parameter(Mandatory)][string]$Destination
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$api='https://api.github.com/repos/muchimi/JoystickGremlinEx/releases?per_page=100'
$headers=@{'User-Agent'='GremlinEx-Installer';'Accept'='application/vnd.github+json'}
$pattern='^gremlinEx_(\d+)_(\d+)_m(\d+)(?:(RC|T)(\d+)([A-Za-z]?))?\.zip$'
function Get-Assets {
 $releases=@(Invoke-RestMethod -Uri $api -Headers $headers -TimeoutSec 30)
 $items=foreach($release in $releases) {
  if($release.draft) { continue }
  foreach($a in $release.assets) {
   if($a.name -cmatch $pattern) {
    $kind=if($Matches[4] -eq 'T') { 'Test' } elseif($Matches[4] -eq 'RC') { 'RC' } else { 'Production' }
    $priority=if($kind -eq 'Production'){2}elseif($kind -eq 'RC'){1}else{0}
    [pscustomobject]@{ Name=$a.name; Url=$a.browser_download_url; Kind=$kind; Major=[int]$Matches[1]; Minor=[int]$Matches[2]; Milestone=[int]$Matches[3]; Priority=$priority; Build=if($Matches[5]){[int]$Matches[5]}else{0}; Revision=$Matches[6] }
   }
  }
 }
 return @($items | Sort-Object -Property @{Expression='Major';Descending=$true},@{Expression='Minor';Descending=$true},@{Expression='Milestone';Descending=$true},@{Expression='Priority';Descending=$true},@{Expression='Build';Descending=$true},@{Expression='Revision';Descending=$true})
}
$items=@(Get-Assets)
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
