@echo off
setlocal
cd /d "%~dp0"

echo Repo Manager installeren...
echo.

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py"
if not defined PYTHON_CMD where python >nul 2>nul && set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    echo FOUT: Python is niet gevonden.
    echo Installeer Python en vink "Add Python to PATH" aan.
    pause
    exit /b 1
)

echo Python gevonden via: %PYTHON_CMD%

if exist ".venv" rmdir /s /q ".venv"

%PYTHON_CMD% -m venv .venv
if errorlevel 1 goto :failed

if not exist ".venv\Scripts\python.exe" goto :failed

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo Repo Manager is correct geinstalleerd.
echo Start hem nu met start.bat.
pause
exit /b 0

:failed
echo.
echo FOUT: Repo Manager kon niet volledig worden geinstalleerd.
echo Bekijk de foutmelding hierboven.
pause
exit /b 1