@echo off
title Data Search Engine Starter
echo ===================================================
echo  Starting Data Search Engine Application...
echo ===================================================

cd /d "%~dp0"

echo Cleaning up any old server processes on Port 8000 / 8080...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8080 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1

echo [1/3] Launching Mock Web Server (Port 8080)...
start "Mock Server" /min ".venv\Scripts\python.exe" mock_server\server.py

echo [2/3] Launching FastAPI Web Server (Port 8000)...
start "FastAPI App" /min ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo [3/3] Opening Web Site in your browser...
ping -n 4 127.0.0.1 > nul
start http://127.0.0.1:8000

echo.
echo ===================================================
echo  Servers are running!
echo  Site URL: http://127.0.0.1:8000
echo ===================================================
echo.
pause
