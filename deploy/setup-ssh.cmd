@echo off
setlocal
echo === LetsScribe: SSH setup for 62.60.151.100 ===
echo.
echo Your public key (add this to the server):
echo.
type "%USERPROFILE%\.ssh\id_ed25519.pub"
echo.
echo --- Option A: if you have password access to the server ---
echo ssh root@62.60.151.100
echo Then on server run:
echo   mkdir -p ~/.ssh ^&^& chmod 700 ~/.ssh
echo   echo "PASTE_KEY_ABOVE" ^>^> ~/.ssh/authorized_keys
echo   chmod 600 ~/.ssh/authorized_keys
echo.
echo --- Option B: from Windows (if ssh-copy-id available) ---
echo type "%USERPROFILE%\.ssh\id_ed25519.pub" ^| ssh root@62.60.151.100 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
echo.
echo --- Test connection ---
echo ssh letsscribe
echo   (add deploy\ssh-config-snippet.txt to %%USERPROFILE%%\.ssh\config first)
echo.
echo --- After SSH works, on server run once ---
echo ssh root@62.60.151.100 "curl -fsSL https://raw.githubusercontent.com/dlaumets/LetsScribe/main/deploy/setup-server.sh | bash"
echo.
pause
