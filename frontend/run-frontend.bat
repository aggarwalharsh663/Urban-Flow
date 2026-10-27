@echo off
setlocal
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

set "VITE_API_URL=http://127.0.0.1:8001"
echo Starting the Urban Flow - Copy frontend at http://127.0.0.1:5174
echo This frontend uses only the API address http://127.0.0.1:8001.
npm.cmd run dev -- --host 127.0.0.1 --port 5174 --strictPort
if errorlevel 1 (
    echo.
    echo Frontend startup failed. Check the message above.
    pause
    exit /b 1
)

endlocal
