@echo off
setlocal
cd /d "%~dp0"
if not exist ".runtime\venv\Scripts\python.exe" powershell -NoProfile -ExecutionPolicy Bypass -File "utilities\install.ps1" -SkipOpenSources
set "CINENODE_HOME=%CD%\data"
set "CINENODE_HOST=127.0.0.1"
set "CINENODE_PORT=8787"
".runtime\venv\Scripts\python.exe" -m cinenode run
if errorlevel 1 pause
