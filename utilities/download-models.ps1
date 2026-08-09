param(
  [ValidateSet("z-image-turbo-fast","wan21-t2v-1.3b-fast","wan21-i2v-14b-first-frame","wan21-flf2v-14b-720p-q4","recommended","all")]
  [string]$Bundle = "recommended",
  [string]$ModelsDir = "",
  [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".runtime\venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { & (Join-Path $Root "utilities\install.ps1") -SkipOpenSources }
& $Python -m pip install "huggingface-hub>=0.27,<2"
$args = @((Join-Path $Root "models\manager.py"))
if ($ModelsDir) { $args += @("--models-dir", $ModelsDir) }
$args += @("install", $Bundle)
if ($Force) { $args += "--force" }
& $Python @args
if ($LASTEXITCODE -ne 0) { throw "Model installation failed with exit code $LASTEXITCODE" }
