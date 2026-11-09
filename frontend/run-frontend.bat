@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist "package.json" (
    echo Could not find frontend\package.json.
    pause
    exit /b 1
)

where node.exe >nul 2>nul
if errorlevel 1 (
    echo Node.js was not found. Install Node.js 20 or newer, then try again.
    pause
    exit /b 1
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
    echo npm was not found. Install Node.js with npm, then try again.
    pause
    exit /b 1
)

if not exist "node_modules\.bin\vite.cmd" (
    echo Frontend dependencies are not installed.
    echo Open a terminal in the frontend folder and run: npm install
    pause
    exit /b 1
)

REM Retrieve dev token if backend Python runtime is available (U-01)
set "VITE_API_TOKEN="
set "PY_EXE="
if exist "%~dp0..\backend\python\python.exe" (
    set "PY_EXE=%~dp0..\backend\python\python.exe"
) else if exist "%~dp0..\backend\.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0..\backend\.venv\Scripts\python.exe"
)

if defined PY_EXE (
    for /f "tokens=*" %%T in ('""!PY_EXE!" -c "import sys; sys.path.insert(0, r'%~dp0..\backend'); import security_config; print(security_config.get_or_create_api_token())""') do (
        set "VITE_API_TOKEN=%%T"
    )
)

set "VITE_API_URL=http://127.0.0.1:8000"
echo Starting the Urban Flow frontend at http://127.0.0.1:5174
echo Connecting to API at http://127.0.0.1:8000
npm.cmd run dev -- --host 127.0.0.1 --port 5174 --strictPort
if errorlevel 1 (
    echo.
    echo Frontend startup failed. Check the message above.
    pause
    exit /b 1
)

endlocal
