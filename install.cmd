@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
)

echo Installing faster-whisper...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt

echo Removing old openai-whisper / torch if present...
".venv\Scripts\pip.exe" uninstall -y openai-whisper torch torchvision torchaudio imageio-ffmpeg 2>nul

echo.
echo Done. Usage:
echo   transcribe path\to\audio.ogg
echo   transcribe-latest              ^(last audio in Downloads^)
echo.
echo To call "transcribe" from anywhere, run once:
echo   install-path.cmd
