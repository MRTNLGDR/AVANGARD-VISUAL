param([switch]$Force)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Upstream = Join-Path $Root "vendor\opensources\upstream\ComfyUI"
$Target = Join-Path $Root "data\engines\ComfyUI"
if (-not (Test-Path (Join-Path $Upstream ".git"))) { & (Join-Path $Root "utilities\bootstrap-opensources.ps1") }
if ($Force) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Target }
if (-not (Test-Path (Join-Path $Target ".git"))) { git clone --shared $Upstream $Target }
git -C $Target checkout --detach 2eb609766a749e3104485979615e062e401bab97
py -3 -m venv (Join-Path $Target "venv")
$Python = Join-Path $Target "venv\Scripts\python.exe"
& $Python -m pip install -r (Join-Path $Target "requirements.txt")
$Launcher = Join-Path $Target "run-cinenode.ps1"
"& `"$Python`" `"$Target\main.py`" --listen 127.0.0.1 --port 8188" | Set-Content -Encoding UTF8 $Launcher
Write-Host "ComfyUI installed. Start: $Launcher" -ForegroundColor Green
