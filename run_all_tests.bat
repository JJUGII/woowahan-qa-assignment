@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\run_all_tests.ps1" %*
set "run_result=%ERRORLEVEL%"
echo.
if not "%~1"=="-NoPause" pause
exit /b %run_result%
