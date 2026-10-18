@echo off
rem Double-click this file (Windows) to open WikiSplice.
cd /d "%~dp0"
rem Rebuild the environment if its Python no longer runs (e.g. after a Python upgrade)
".venv\Scripts\python.exe" -c "import sys" 2>nul
if errorlevel 1 (
  echo Setting up a private Python environment...
  py -3 -m venv --clear .venv 2>nul || python -m venv --clear .venv
  ".venv\Scripts\python.exe" -c "import sys" 2>nul
  if errorlevel 1 (
    echo Python 3 isn't installed. Get it from https://www.python.org/downloads/ then try again.
    pause
    exit /b 1
  )
)
rem (Re)install packages if missing, or if requirements.txt changed (e.g. after an update)
set NEEDS_INSTALL=0
".venv\Scripts\python.exe" -c "import playwright, requests" 2>nul || set NEEDS_INSTALL=1
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1 || set NEEDS_INSTALL=1
if "%NEEDS_INSTALL%"=="1" (
  echo Installing required packages...
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt && copy /y requirements.txt ".venv\requirements.installed" >nul
)
".venv\Scripts\python.exe" -m playwright install chromium
".venv\Scripts\python.exe" app.py
pause
