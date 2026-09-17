@echo off
title DataSearchHub - Promote to Production (ConoHa)

echo ===================================================================
echo   [DataSearchHub] Promote from Render(develop) to ConoHa(main)
echo ===================================================================
echo.

set "GIT_CMD=C:\Users\yusuke_tsuchiya\AppData\Local\Programs\Git\cmd\git.exe"
set "KEY_FILE=%USERPROFILE%\Downloads\key-2026-09-17-conoha_2.pem"

if not exist "%KEY_FILE%" (
    echo [ERROR] SSH Key not found: %KEY_FILE%
    pause
    exit /b 1
)

echo [1/4] Switching to main branch...
"%GIT_CMD%" checkout main
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to checkout main branch.
    pause
    exit /b 1
)

echo.
echo [2/4] Merging develop into main...
"%GIT_CMD%" merge develop
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Merge failed.
    pause
    exit /b 1
)

echo.
echo [3/4] Pushing main branch to GitHub...
"%GIT_CMD%" push origin main
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to push main to GitHub.
    pause
    exit /b 1
)

echo.
echo Returning to develop branch for next development...
"%GIT_CMD%" checkout develop

echo.
echo [4/4] Updating ConoHa WING production server...
ssh -i "%KEY_FILE%" -p 8022 -o StrictHostKeyChecking=no c6891274@www1211.conoha.ne.jp "cd /home/c6891274/apps/DataSearchHub/Data_search_engine && git pull origin main ; ./restart_on_conoha.sh"

echo.
echo ===================================================================
echo   [SUCCESS] Promoted to Production (ConoHa WING) successfully!
echo   Production URL: http://2026091711175w334chu.conohawing.com/
echo ===================================================================
echo.
pause
