@echo off
title ConoHa WING - Update and Restart

echo ===================================================================
echo   DataSearchHub: ConoHa WING Update and Restart
echo ===================================================================
echo.

set "KEY_FILE=%USERPROFILE%\Downloads\key-2026-09-17-conoha_2.pem"

if not exist "%KEY_FILE%" (
    echo [ERROR] SSH Key file not found: %KEY_FILE%
    pause
    exit /b 1
)

echo Connecting to ConoHa server and updating...
echo.

ssh -i "%KEY_FILE%" -p 8022 -o StrictHostKeyChecking=no c6891274@www1211.conoha.ne.jp "cd /home/c6891274/apps/DataSearchHub/Data_search_engine && git pull origin main ; ./restart_on_conoha.sh"

echo.
echo ===================================================================
echo   [SUCCESS] Update and restart completed!
echo   URL: http://2026091711175w334chu.conohawing.com/
echo ===================================================================
echo.
pause
