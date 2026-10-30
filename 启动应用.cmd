@echo off
cd /d "%~dp0"
if not exist "runtime\tmp" mkdir "runtime\tmp"
set "TEMP=%CD%\runtime\tmp"
set "TMP=%TEMP%"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "import streamlit, requests, dotenv, pandas" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m ensurepip --upgrade
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" scripts\launch.py
if errorlevel 1 goto fail
exit /b 0
:fail
echo Startup failed. Please keep this window and share the error text without API keys.
pause
