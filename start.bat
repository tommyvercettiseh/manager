@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Repo Manager is nog niet geinstalleerd.
  echo Start eerst install.bat.
  pause
  exit /b 1
)
start "Repo Manager" ".venv\Scripts\pythonw.exe" app.py
