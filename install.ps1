param(
  [switch]$SkipOpenSources,
  [switch]$InstallCoreEngines
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "utilities\install.ps1") -SkipOpenSources:$SkipOpenSources -InstallCoreEngines:$InstallCoreEngines
