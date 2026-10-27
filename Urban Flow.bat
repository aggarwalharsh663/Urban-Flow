@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Urban Flow - Adaptive Traffic Signal System
echo   Launching Windows Desktop Application...
echo ============================================================
echo.

cd /d "%~dp0frontend"
npm run app

endlocal
