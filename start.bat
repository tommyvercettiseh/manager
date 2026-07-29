@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Repo Manager is nog niet correct geinstalleerd.
    echo Start eerst install.bat en controleer eventuele foutmeldingen.
    pause
    exit /b 1
)

if exist ".venv\Scripts\pythonw.exe" (
    start "Repo Manager" ".venv\Scripts\pythonw.exe" app.py
) else (
    start "Repo Manager" ".venv\Scripts\python.exe" app.py
)
