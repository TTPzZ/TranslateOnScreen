$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "[clean] Removing generated Python caches"
Get-ChildItem -Path $Root -Recurse -Force -Directory |
    Where-Object { $_.Name -eq "__pycache__" -or $_.Name -eq ".pytest_cache" } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

Write-Host "[clean] Removing rotated local logs over 5MB"
$LogDir = Join-Path $Root "logs"
if (Test-Path $LogDir) {
    Get-ChildItem -Path $LogDir -File |
        Where-Object { $_.Length -gt 5MB } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}

py --version | Out-Null
Write-Host "[clean] Complete"
