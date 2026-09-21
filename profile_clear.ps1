<#
.SYNOPSIS
    Clears Python and application caches, then runs the Scalene profiler.
.DESCRIPTION
    This script removes __pycache__ directories, deletes testing caches,
    disables bytecode generation for the session, and triggers Scalene.
.PARAMETER ScriptPath
    The path to the Python script you want to profile. Defaults to 'main.py'.
#>

param (
    [string]\$ScriptPath = "main.py"
)

# 1. Define target cache patterns
\$TargetCaches = @(
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache"
)

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " Starting Cold-Start Scalene Profiler     " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 2. Find and remove local Python caches recursively
Write-Host "`n[1/3] Clearing local Python caches..." -ForegroundColor Yellow
foreach ($Cache in $TargetCaches) {
    $Items = Get-ChildItem -Path . -Filter $Cache -Recurse -Directory -ErrorAction SilentlyContinue
    if ($Items) {
        foreach ($Item in $Items) {
            Write-Host "Removing: $($Item.FullName)" -ForegroundColor Gray
            Remove-Item -Path $Item.FullName -Recurse -Force
        }
    }
}
Write-Host "Cache cleanup complete." -ForegroundColor Green

# 3. Configure Environment Variables for Cold Start
Write-Host "`n[2/3] Setting session environment flags..." -ForegroundColor Yellow
# Prevents Python from writing new .pyc files during this profiling run
\$env:PYTHONDONTWRITEBYTECODE = "1"
Write-Host "PYTHONDONTWRITEBYTECODE set to 1 (Bytecode disabled)" -ForegroundColor Gray

# 4. Check if Scalene is installed and run
Write-Host "`n[3/3] Launching Scalene..." -ForegroundColor Yellow
if (-not (Get-Command scalene -ErrorAction SilentlyContinue)) {
    Write-Error "Scalene is not installed or not in your system PATH. Install it via 'pip install scalene'."
    Exit 1
}

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Target Python script '$ScriptPath' not found. Please provide a valid file path."
    Exit 1
}

Write-Host "Running: scalene run $ScriptPath" -ForegroundColor Cyan
Write-Host "-----------------------------------------" -ForegroundColor Gray

# Execute Scalene
scalene run $ScriptPath

Write-Host "`n-----------------------------------------" -ForegroundColor Gray
Write-Host "Profiling execution finished." -ForegroundColor Green
