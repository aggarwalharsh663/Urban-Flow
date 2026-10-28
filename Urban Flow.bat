@echo off
setlocal
cd /d "%~dp0"

if exist "Urban Flow.exe" (
    start "" "Urban Flow.exe"
    exit /b 0
)

if exist "frontend\node_modules\electron\dist\electron.exe" (
    start "" "frontend\node_modules\electron\dist\electron.exe" "%~dp0frontend"
    exit /b 0
)

echo [Error] Urban Flow executable not found.
pause
