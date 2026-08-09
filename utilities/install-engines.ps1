param(
  [switch]$Core,
  [switch]$WithLLM,
  [switch]$WithOpenCode,
  [switch]$WithComfyUI,
  [switch]$With3D,
  [switch]$Force,
  [switch]$AcceptWanGPLicense
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Data = Join-Path $Root "data"
$Engines = Join-Path $Data "engines"
$Upstream = Join-Path $Root "vendor\opensources\upstream"
$RuntimePython = Join-Path $Root ".runtime\venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $Engines | Out-Null
if (-not (Test-Path $RuntimePython)) { & (Join-Path $Root "utilities\install.ps1") -SkipOpenSources }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
  throw "FFmpeg/ffprobe are required. Run utilities\install.ps1 again or install Gyan.FFmpeg with winget."
}

# Preserve immutable upstreams first. WanGP remains opt-in because of its community license.
$sdSource = Join-Path $Upstream "stable-diffusion.cpp"
if (-not (Test-Path (Join-Path $sdSource ".git"))) {
  $bootstrapArgs = @()
  if ($AcceptWanGPLicense) { $bootstrapArgs += "-AcceptWanGPLicense" }
  & (Join-Path $Root "utilities\bootstrap-opensources.ps1") @bootstrapArgs
}

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Kitware.CMake -e --accept-package-agreements --accept-source-agreements
  } else { throw "CMake is required to build stable-diffusion.cpp." }
}
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) { throw "CMake not found after installation." }
if (-not (Test-Path (Join-Path $sdSource "CMakeLists.txt"))) { throw "stable-diffusion.cpp upstream is missing: $sdSource" }

$build = Join-Path $Root ".runtime\build\stable-diffusion.cpp"
$target = Join-Path $Engines "stable-diffusion.cpp\bin"
if ($Force -and (Test-Path $build)) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force -Path $build,$target | Out-Null
# Ada Lovelace / RTX 4090 = compute capability 8.9. CPU offload remains available in runtime profiles.
cmake -S $sdSource -B $build -DSD_CUDA=ON -DSD_BUILD_EXAMPLES=ON -DSD_WEBM=ON -DCMAKE_CUDA_ARCHITECTURES=89
if ($LASTEXITCODE -ne 0) { throw "stable-diffusion.cpp CMake configure failed." }
cmake --build $build --config Release --parallel
if ($LASTEXITCODE -ne 0) { throw "stable-diffusion.cpp build failed." }
$candidates = Get-ChildItem $build -Recurse -File -Filter "sd-cli.exe"
if (-not $candidates) { throw "sd-cli.exe was not generated." }
$binDir = $candidates[0].Directory.FullName
Copy-Item (Join-Path $binDir "*") $target -Recurse -Force

# Official portable NCNN release archives, including models.
$portableArgs = @((Join-Path $Root "utilities\install_portable_engines.py"))
if ($Force) { $portableArgs += "--force" }
& $RuntimePython @portableArgs
if ($LASTEXITCODE -ne 0) { throw "Portable engine installation failed." }

if ($WithLLM -and -not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Ollama.Ollama -e --scope user --accept-package-agreements --accept-source-agreements
  } else {
    Invoke-Expression (Invoke-RestMethod https://ollama.com/install.ps1)
  }
}
if ($WithLLM -and (Get-Command ollama -ErrorAction SilentlyContinue)) { ollama pull qwen3:8b-q4_K_M }
if ($WithComfyUI) {
  & (Join-Path $Root "utilities\install-comfyui.ps1") -Force:$Force
}
if ($With3D) {
  & (Join-Path $Root "utilities\install-3d-engines.ps1") -Force:$Force
}
if ($WithOpenCode -and -not (Get-Command opencode -ErrorAction SilentlyContinue)) {
  if (Get-Command npm -ErrorAction SilentlyContinue) { npm install -g opencode-ai@latest }
  elseif (Get-Command scoop -ErrorAction SilentlyContinue) { scoop install opencode }
  else { Write-Warning "OpenCode needs npm or Scoop. Upstream source is preserved, but the CLI was not installed." }
}
& $RuntimePython -m cinenode doctor
Write-Host "Core local engines installed under $Engines" -ForegroundColor Green
