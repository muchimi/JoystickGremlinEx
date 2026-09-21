<#
.SYNOPSIS
    Cleans up Python project workspaces by deleting Scalene profiles and caches.
#>

# 1. Define files and directories to target
\$ScaleneFiles  = @("scalene-profile.json", "profile.json")
\$CacheFolders  = @("__pycache__", ".pytest_cache", ".mypy_cache")

Write-Host "=========================================" -ForegroundColor Crimson
Write-Host " Running Workspace Purge Tool            " -ForegroundColor Crimson
Write-Host "=========================================" -ForegroundColor Crimson

# 2. Delete Scalene profile reports
Write-Host "`n[*] Hunting for Scalene profile outputs..." -ForegroundColor Yellow
foreach (File in ScaleneFiles) {
    FoundFiles = Get-ChildItem -Path . -Filter File -Recurse -File -ErrorAction SilentlyContinue
    foreach (Item in FoundFiles) {
        Write-Host "Deleting profile: (Item.FullName)" -ForegroundColor Gray
        Remove-Item -Path \$Item.FullName -Force
    }
}

# 3. Delete traditional workspace caches
Write-Host "`n[*] Hunting for compiler caches..." -ForegroundColor Yellow
foreach ($Cache in $CacheFolders) {
    $FoundDirs = Get-ChildItem -Path . -Filter $Cache -Recurse -Directory -ErrorAction SilentlyContinue
    foreach ($Item in $FoundDirs) {
        Write-Host "Removing cache directory: $($Item.FullName)" -ForegroundColor Gray
        Remove-Item -Path $Item.FullName -Recurse -Force
    }
}

Write-Host "`n=========================================" -ForegroundColor Green
Write-Host " Workspace is fully sanitized!           " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
