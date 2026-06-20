@echo off
rem invest-calculator launcher: start backend, open browser
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [error] .venv not found. Run: python -m venv .venv ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

start "invest-calculator" ".venv\Scripts\python.exe" -m uvicorn backend.main:app
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8000"
