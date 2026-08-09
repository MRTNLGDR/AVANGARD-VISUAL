param(
  [switch]$TrellisOnly,
  [switch]$TripoSROnly,
  [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Upstream = Join-Path $Root "vendor\opensources\upstream"
$Engines = Join-Path $Root "data\engines"
$BuildRoot = Join-Path $Root ".runtime\build"
New-Item -ItemType Directory -Force -Path $Engines,$BuildRoot | Out-Null
if (-not (Test-Path (Join-Path $Upstream "trellis.cpp\.git")) -or -not (Test-Path (Join-Path $Upstream "TripoSR\.git"))) {
  & (Join-Path $Root "utilities\bootstrap-opensources.ps1")
}
$InstallTrellis = -not $TripoSROnly
$InstallTripoSR = -not $TrellisOnly
if ($InstallTrellis) {
  if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) { throw "CMake is required for trellis.cpp." }
  $Source = Join-Path $Upstream "trellis.cpp"
  $Build = Join-Path $BuildRoot "trellis.cpp"
  $Target = Join-Path $Engines "trellis.cpp"
  if ($Force) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Build,$Target }
  cmake -S $Source -B $Build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DTRELLIS_WEBP=ON
  if ($LASTEXITCODE -ne 0) { throw "trellis.cpp configure failed." }
  cmake --build $Build --config Release --parallel
  if ($LASTEXITCODE -ne 0) { throw "trellis.cpp build failed." }
  $Cli = Get-ChildItem $Build -Recurse -File -Filter "trellis-cli.exe" | Select-Object -First 1
  if (-not $Cli) { throw "trellis-cli.exe was not generated." }
  New-Item -ItemType Directory -Force -Path $Target | Out-Null
  Copy-Item (Join-Path $Cli.Directory.FullName "*") $Target -Recurse -Force
  Write-Host "trellis.cpp installed: $Target" -ForegroundColor Green
  Write-Warning "Weights are still required under data\models\trellis2; preflight blocks generation until they exist."
}
if ($InstallTripoSR) {
  $Source = Join-Path $Upstream "TripoSR"
  $Target = Join-Path $Engines "TripoSR"
  if ($Force) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Target }
  if (-not (Test-Path (Join-Path $Target ".git"))) { git clone --shared $Source $Target }
  git -C $Target checkout --detach 107cefdc244c39106fa830359024f6a2f1c78871
  py -3 -m venv (Join-Path $Target "venv")
  $Python = Join-Path $Target "venv\Scripts\python.exe"
  & $Python -m pip install -r (Join-Path $Target "requirements.txt")
  & $Python -c "import torch; print({'torch':torch.__version__,'cuda_available':torch.cuda.is_available()})"
  Write-Host "TripoSR installed: $Target" -ForegroundColor Green
}
