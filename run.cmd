@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run setup.cmd first.
  exit /b 1
)
".venv\Scripts\python.exe" -m context_live_translator
