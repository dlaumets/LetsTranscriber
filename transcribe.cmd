@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%"
"%ROOT%.venv\Scripts\python.exe" "%ROOT%transcribe.py" %*
