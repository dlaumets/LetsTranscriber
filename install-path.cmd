@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = '%~dp0'.TrimEnd('\');" ^
  "$userPath = [Environment]::GetEnvironmentVariable('Path', 'User');" ^
  "if ($userPath -like ('*' + $root + '*')) { Write-Host 'Already in PATH:' $root; exit 0 }" ^
  "[Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $root), 'User');" ^
  "Write-Host 'Added to user PATH:' $root;" ^
  "Write-Host 'Open a new terminal, then run: transcribe your-file.ogg'"
endlocal
