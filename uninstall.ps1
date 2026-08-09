param([switch]$PurgeData)
$ErrorActionPreference="Stop"
$Root=(Resolve-Path $PSScriptRoot).Path
& (Join-Path $Root "stop.bat")
Remove-Item -Recurse -Force (Join-Path $Root ".runtime") -ErrorAction SilentlyContinue
$shortcut=Join-Path ([Environment]::GetFolderPath('Desktop')) "Avangard Visual.lnk"
Remove-Item $shortcut -Force -ErrorAction SilentlyContinue
if ($PurgeData) { Remove-Item -Recurse -Force (Join-Path $Root "data") -ErrorAction SilentlyContinue }
Write-Host "Runtime removed. Source and data preserved unless -PurgeData was supplied."
