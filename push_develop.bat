@echo off
title GitHub Develop Push

echo ===================================================================
echo   Pushing develop branch to GitHub (Render Staging)
echo ===================================================================
echo.

"C:\Users\yusuke_tsuchiya\AppData\Local\Programs\Git\cmd\git.exe" push origin develop

echo.
echo ===================================================================
echo   Push process finished.
echo ===================================================================
echo.
pause
