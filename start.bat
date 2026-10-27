@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Urban Flow - Starting Backend and Frontend
echo ============================================================

REM Check Python
where python.exe >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

set "VENV_PYTHON=%~dp0backend\.venv\Scripts\python.exe"
if exist "!VENV_PYTHON!" (
    "!VENV_PYTHON!" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo [INFO] Existing virtual environment is broken. Recreating...
        rmdir /s /q "%~dp0backend\.venv"
    )
)

if not exist "!VENV_PYTHON!" (
    echo [INFO] Creating Python virtual environment...
    python -m venv "%~dp0backend\.venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Verify dependencies
"!VENV_PYTHON!" -c "import fastapi, uvicorn, cv2, ultralytics" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing backend dependencies...
    "%~dp0backend\.venv\Scripts\pip.exe" install -r "%~dp0backend\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Backend dependency installation failed.
        pause
        exit /b 1
    )
)

REM Check Node
where node.exe >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js was not found. Install Node.js 20+ and add it to PATH.
    pause
    exit /b 1
)

REM Check Frontend dependencies
if not exist "%~dp0frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    cd /d "%~dp0frontend"
    call npm install
    cd /d "%~dp0"
)

REM Launch Backend
echo [START] Launching backend at http://127.0.0.1:8000
start "Urban Flow - Backend" /D "%~dp0backend" cmd /k ""!VENV_PYTHON!" -m uvicorn main:app --reload --reload-dir services --reload-include main.py --host 127.0.0.1 --port 8000"

REM Launch Frontend
echo [START] Launching frontend at http://127.0.0.1:5174
start "Urban Flow - Frontend" /D "%~dp0frontend" cmd /k "set VITE_API_URL=http://127.0.0.1:8000&& npm run dev -- --host 127.0.0.1 --port 5174 --strictPort"

echo.
echo ============================================================
echo  Both servers started successfully!
echo   Backend  : http://127.0.0.1:8000
echo   Frontend : http://127.0.0.1:5174
echo ============================================================
echo.
echo You can close this launcher window at any time.
pause
endlocal
