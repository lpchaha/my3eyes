@echo off
cd /d "%~dp0"

echo ============================================================
echo   3eyes - Launcher
echo ============================================================
echo.

python --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

echo [1/2] Checking dependencies...
pip install -r requirements.txt --quiet 1>nul 2>nul
if errorlevel 1 (
    pip install -r requirements.txt --user --quiet 1>nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
)
echo [OK] Dependencies ready.

echo [2/2] Launching 3eyes...
start "" pythonw app.py

echo Launcher exiting in 2s...
timeout /t 2 /nobreak 1>nul
exit
