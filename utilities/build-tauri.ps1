param([switch]$Clean)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".runtime\venv\Scripts\python.exe"
$TauriRoot = Join-Path $Root "source\desktop\src-tauri"
$Binaries = Join-Path $TauriRoot "binaries"
$Installers = Join-Path $Root "installers"
if (-not (Test-Path $VenvPython)) { & (Join-Path $Root "utilities\install.ps1") -SkipOpenSources }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Rustlang.Rustup -e --scope user --accept-package-agreements --accept-source-agreements
    $env:Path += ";$env:USERPROFILE\.cargo\bin"
  } else { throw "Rust/Cargo is required to build the desktop installer." }
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "Cargo is unavailable after Rust installation. Reopen PowerShell and rerun." }
if (-not (Get-Command cargo-tauri -ErrorAction SilentlyContinue)) { cargo install tauri-cli --version "^2" --locked }
& $VenvPython -m pip install "pyinstaller>=6,<7"
$HostTriple = ((rustc -vV | Select-String '^host:').ToString().Split(':',2)[1].Trim())
if (-not $HostTriple) { throw "Could not determine Rust host target." }
if ($Clean) {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $Root ".runtime\pyinstaller"),(Join-Path $TauriRoot "target"),$Binaries
}
New-Item -ItemType Directory -Force -Path $Binaries,$Installers,(Join-Path $Root ".runtime\pyinstaller") | Out-Null
$Dist = Join-Path $Root ".runtime\pyinstaller\dist"
$Work = Join-Path $Root ".runtime\pyinstaller\work"
$Spec = Join-Path $Root ".runtime\pyinstaller\spec"
& $VenvPython -m PyInstaller --noconfirm --clean --onefile --name cinenode-backend --collect-all cinenode --distpath $Dist --workpath $Work --specpath $Spec (Join-Path $Root "utilities\backend_entry.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller sidecar build failed." }
$Built = Join-Path $Dist "cinenode-backend.exe"
if (-not (Test-Path $Built)) { throw "Backend sidecar was not generated: $Built" }
$Sidecar = Join-Path $Binaries "cinenode-backend-$HostTriple.exe"
Copy-Item $Built $Sidecar -Force
$env:CINENODE_HOME = Join-Path $Root ".runtime\sidecar-smoke"
& $Built init
if ($LASTEXITCODE -ne 0) { throw "Backend sidecar smoke test failed." }
Push-Location $TauriRoot
try { cargo tauri build } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "Tauri build failed." }
Get-ChildItem (Join-Path $TauriRoot "target\release\bundle") -Recurse -File | Where-Object { $_.Extension -in '.exe','.msi','.dmg','.AppImage','.deb','.rpm' } | Copy-Item -Destination $Installers -Force
Write-Host "Desktop installers copied to $Installers" -ForegroundColor Green
