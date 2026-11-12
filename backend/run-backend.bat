@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM 1. Identify Python Runtime (portable bundle or venv)
set "PY_EXE="
if exist "%~dp0python\python.exe" (
    set "PY_EXE=%~dp0python\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
)

REM 2. If environment not found, trigger setup using RemoteSigned policy (never Bypass)
if not defined PY_EXE (
    echo [INFO] Backend virtual environment not found. Setting it up now...
    powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0setup.ps1"
    if exist "%~dp0.venv\Scripts\python.exe" (
        set "PY_EXE=%~dp0.venv\Scripts\python.exe"
    )
)

if not defined PY_EXE (
    echo [ERROR] Python environment was not found. Install Python 3.10+ or run setup.ps1.
    pause
    exit /b 1
)

REM 3. Launch FastAPI in hardened production mode directly without script wrapping
echo Starting FastAPI in Production Mode at http://127.0.0.1:8000
echo Production mode active (secure non-reload execution)
"!PY_EXE!" -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-server-header
if errorlevel 1 (
    echo.
    echo Backend startup failed. Check whether port 8000 is already in use.
    pause
    exit /b 1
)

endlocal
