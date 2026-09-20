# Creates a Desktop shortcut that launches GremlinEx from a given git branch.
# Uses a sibling git worktree so multiple branches can run without switching the main checkout.
#
# Usage:
#   .\scripts\create_branch_shortcut.ps1 -Branch T51
#   .\scripts\create_branch_shortcut.ps1 -Branch T51L2R -UseMainRepo
#   .\scripts\create_branch_shortcut.ps1 -Branch T52L -CreateWorktree

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Branch,

    # Launch from the primary repo checkout (must already be on $Branch).
    [switch]$UseMainRepo,

    # Force creating/updating a sibling worktree even if main is on this branch.
    [switch]$CreateWorktree,

    [string]$ShortcutName,

    [string]$DesktopPath = ([Environment]::GetFolderPath('Desktop'))
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ParentDir = Split-Path $RepoRoot -Parent
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Icon = Join-Path $RepoRoot 'icons\gex.ico'

if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python"
}

$current = (git -C $RepoRoot branch --show-current).Trim()
$refExists = git -C $RepoRoot rev-parse --verify --quiet $Branch
if ($LASTEXITCODE -ne 0) {
    throw "Branch/ref not found: $Branch"
}

$useMain = $UseMainRepo -or (($current -eq $Branch) -and -not $CreateWorktree)
$workDir = $RepoRoot

if (-not $useMain) {
    $safe = ($Branch -replace '[\\/:*?"<>|]', '-')
    $workDir = Join-Path $ParentDir "JoystickGremlinEx-$safe"

    $existing = git -C $RepoRoot worktree list --porcelain |
        Select-String -Pattern '^worktree ' |
        ForEach-Object { $_.Line.Substring(9) }

    $workDirSlash = $workDir -replace '\\', '/'
    $already = $false
    foreach ($p in $existing) {
        $norm = ($p -replace '\\', '/').TrimEnd('/')
        if ($norm -eq $workDirSlash.TrimEnd('/')) { $already = $true; break }
    }
    if ($already) {
        git -C $RepoRoot worktree repair $workDir 2>$null | Out-Null
        Write-Host "Using existing worktree: $workDir"
    }
    elseif (Test-Path $workDir) {
        throw "Path exists but is not a registered worktree: $workDir"
    }
    else {
        Write-Host "Creating worktree $workDir @ $Branch"
        git -C $RepoRoot worktree add -B $Branch $workDir $Branch
    }
}

$entry = Join-Path $workDir 'gremlinEx.py'
if (-not (Test-Path $entry)) {
    throw "gremlinEx.py missing in $workDir"
}

if (-not $ShortcutName) {
    $ShortcutName = "GremlinEx $Branch"
}
$lnkPath = Join-Path $DesktopPath "$ShortcutName.lnk"

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($lnkPath)
$sc.TargetPath = $Python
$sc.Arguments = 'gremlinEx.py --nmh'
$sc.WorkingDirectory = $workDir
$sc.WindowStyle = 1
$sc.Description = "GremlinEx from branch $Branch ($workDir)"
if (Test-Path $Icon) {
    $sc.IconLocation = "$Icon,0"
}
$sc.Save()

Write-Host "Shortcut: $lnkPath"
Write-Host "  Target : $Python"
Write-Host "  Args   : gremlinEx.py --nmh"
Write-Host "  CWD    : $workDir"
Write-Host "  Branch : $Branch"
