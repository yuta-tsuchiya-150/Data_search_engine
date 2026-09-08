@echo off
title Data Search Engine Stopper
echo ===================================================
echo  Stopping Data Search Engine Servers...
echo ===================================================

cd /d "%~dp0"

echo Terminating server processes on port 8000 and 8080...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8080 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1

echo.
echo All server processes stopped successfully.
pause
