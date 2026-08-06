@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Context Live Translator optional NVIDIA GPU runtime
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-gpu.ps1"
set "setup_exit=%ERRORLEVEL%"

echo.
if not "%setup_exit%"=="0" (
  echo GPU runtime setup did not finish successfully.
  echo You can still select CPU mode in the application.
)
echo.
pause
exit /b %setup_exit%
