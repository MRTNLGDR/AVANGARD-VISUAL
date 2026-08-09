@echo off
setlocal
cd /d "%~dp0"
if exist "data\cinenode.pid" (
  set /p PID=<"data\cinenode.pid"
  taskkill /PID %PID% /T /F >nul 2>&1
  del /q "data\cinenode.pid" >nul 2>&1
  echo Avangard Visual encerrado.
) else (
  echo O aplicativo nao esta em execucao.
)
