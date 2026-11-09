@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Urban Flow - Starting System
echo ============================================================

REM 1. Identify Python Runtime
set "VENV_PYTHON="
if exist "%~dp0backend\python\python.exe" (
    set "VENV_PYTHON=%~dp0backend\python\python.exe"
) else if exist "%~dp0backend\.venv\Scripts\python.exe" (
    set "VENV_PYTHON=%~dp0backend\.venv\Scripts\python.exe"
) else (
    where python.exe >nul 2>nul
    if not errorlevel 1 (
        if not exist "%~dp0backend\.venv" (
            echo [INFO] Creating Python virtual environment...
            python -m venv "%~dp0backend\.venv"
        )
        if exist "%~dp0backend\.venv\Scripts\python.exe" (
            set "VENV_PYTHON=%~dp0backend\.venv\Scripts\python.exe"
        )
    )
)

REM 2. Identify Frontend / Launcher Mode
where node.exe >nul 2>nul
if errorlevel 1 (
    echo [INFO] System Node.js not detected in PATH.
    if exist "%~dp0Urban Flow.exe" (
        echo [START] Launching Urban Flow Desktop Application...
        start "" "%~dp0Urban Flow.exe"
        exit /b 0
    )
    if exist "%~dp0frontend\node_modules\electron\dist\electron.exe" (
        echo [START] Launching Urban Flow Desktop Application...
        start "" "%~dp0frontend\node_modules\electron\dist\electron.exe" "%~dp0frontend"
        exit /b 0
    )
    echo [ERROR] Neither Node.js nor bundled Electron executable was found.
    pause
    exit /b 1
)

REM If Python runtime is not ready for local server mode
if not defined VENV_PYTHON (
    echo [ERROR] Python was not found. Install Python 3.10+ or verify backend\python\python.exe exists.
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

REM Launch Backend (R2: Secrets retrieved from DPAPI encrypted token file at rest; never passed on command line)
echo [START] Launching backend at http://127.0.0.1:8000
start "Urban Flow - Backend" /D "%~dp0backend" cmd /k ""!VENV_PYTHON!" -m uvicorn main:app --host 127.0.0.1 --port 8000"

REM Launch Frontend (R2: No secrets exposed in environment flags or command-line arguments)
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
