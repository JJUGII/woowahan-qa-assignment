@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Build environment missing: .venv\Scripts\python.exe
    echo Install project requirements on the BUILD PC first.
    exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Install PyInstaller in the build environment first.
    exit /b 1
)
echo Building full portable distribution. Personal settings are NOT copied.
".venv\Scripts\python.exe" tools\build_portable.py %*
exit /b %errorlevel%
