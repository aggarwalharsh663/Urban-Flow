@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0frontend\node_modules\electron\dist\electron.exe" (
    start "" "%~dp0frontend\node_modules\electron\dist\electron.exe" "%~dp0frontend"
    exit /b 0
)

if exist "%~dp0Urban Flow.exe" (
    start "" "%~dp0Urban Flow.exe"
    exit /b 0
)

echo [Error] Urban Flow executable not found.
pause
