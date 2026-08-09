param(
  [switch]$AcceptWanGPLicense,
  [switch]$Force
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
    $env:Path += ";$env:ProgramFiles\Git\cmd"
  } else { throw "Git is required and winget is unavailable." }
}
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $Python) { throw "Python 3 is required." }
$argsList = @((Join-Path $PSScriptRoot "sync_opensources.py"), "--project-root", $ProjectRoot)
if ($AcceptWanGPLicense) { $argsList += "--accept-wangp-license" }
if ($Force) { $argsList += "--force" }
& $Python.Source @argsList
if ($LASTEXITCODE -ne 0) { throw "Open-source synchronization failed security or integrity gates." }
