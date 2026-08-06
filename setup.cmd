@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Context Live Translator setup
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set "setup_exit=%ERRORLEVEL%"

echo.
if not "%setup_exit%"=="0" (
  echo Setup did not finish successfully.
  echo See README_FIRST.md and README.md for troubleshooting.
) else (
  echo Setup finished. Double-click run.cmd to start the app.
)
echo.
pause
exit /b %setup_exit%
