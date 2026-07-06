@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%"

if not exist ".venv\Scripts\uvicorn.exe" (
  echo Run install-service.cmd first.
  exit /b 1
)

".venv\Scripts\uvicorn.exe" src.api.main:app --host 0.0.0.0 --port 8000 --reload %*
