@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Urban Flow - Adaptive Traffic Signal System
echo  Launching Local AI Models & Desktop Application...
echo ============================================================

set "ELECTRON_EXE=%~dp0frontend\node_modules\electron\dist\electron.exe"
set "FRONTEND_DIR=%~dp0frontend"

if not exist "%ELECTRON_EXE%" (
    echo [ERROR] Application components not found.
    echo Please make sure you extracted the complete folder from the ZIP file.
    pause
    exit /b 1
)

start "" "%ELECTRON_EXE%" "%FRONTEND_DIR%"
exit /b 0
