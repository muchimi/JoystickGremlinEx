param(
 [Parameter(Mandatory)][string]$Destination
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Windows FFmpeg builds provided by gyan.dev (third-party distributor linked by ffmpeg.org).
$url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
if(-not [IO.Path]::IsPathRooted($Destination)) { throw 'Destination must be absolute.' }
$Destination=[IO.Path]::GetFullPath($Destination)
$target=Join-Path $Destination 'tools\ffmpeg'
if(Test-Path (Join-Path $target 'bin\ffmpeg.exe')) {
 Write-Host 'FFmpeg already installed in the selected destination; skipping.'
 exit 0
}
$stage=Join-Path ([IO.Path]::GetTempPath()) ('gremlinex-ffmpeg-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
 $zip=Join-Path $stage 'ffmpeg.zip'
 Invoke-WebRequest -Uri $url -OutFile $zip -TimeoutSec 600
 if((Get-Item $zip).Length -lt 1000000) { throw 'FFmpeg download is unexpectedly small.' }
 $extract=Join-Path $stage 'unpacked'
 Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
 $binary=Get-ChildItem -LiteralPath $extract -Filter 'ffmpeg.exe' -File -Recurse | Where-Object { $_.Directory.Name -eq 'bin' } | Select-Object -First 1
 if(-not $binary) { throw 'Downloaded archive does not contain bin\ffmpeg.exe.' }
 $sourceRoot=$binary.Directory.Parent.FullName
 $stagedTarget=Join-Path $stage 'ffmpeg-ready'
 Copy-Item -LiteralPath $sourceRoot -Destination $stagedTarget -Recurse -Force
 if(-not (Test-Path (Join-Path $stagedTarget 'bin\ffprobe.exe'))) { throw 'ffprobe.exe missing from archive.' }
 $parent=Split-Path $target -Parent
 New-Item -ItemType Directory -Path $parent -Force | Out-Null
 if(Test-Path $target) { throw "Target already exists without FFmpeg binary: $target" }
 Move-Item -LiteralPath $stagedTarget -Destination $target
 Write-Host "FFmpeg installed to $target"
} finally {
 Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
