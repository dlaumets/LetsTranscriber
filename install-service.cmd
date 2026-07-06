@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt -r requirements-service.txt

echo.
echo Done. Next steps:
echo   1. Copy .env.example to .env
echo   2. Start PostgreSQL: docker compose up db -d
echo   3. Run API: run-api.cmd
echo   4. Open http://localhost:8000
echo.
