@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo Run install-service.cmd first.
  exit /b 1
)

".venv\Scripts\python.exe" -m src.bot.main %*
