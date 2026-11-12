@echo off
setlocal
cd /d "%~dp0"

REM Automatically clear web-download block (Zone.Identifier stream) if extracted from archive
powershell.exe -NoProfile -NonInteractive -Command "Unblock-File -LiteralPath '%~dp0Urban Flow.exe','%~dp0Urban Flow.bat','%~dp0Urban Flow.vbs' -ErrorAction SilentlyContinue; if (Test-Path '%~dp0frontend\node_modules\electron\dist\electron.exe') { Unblock-File -LiteralPath '%~dp0frontend\node_modules\electron\dist\electron.exe' -ErrorAction SilentlyContinue }" >nul 2>&1

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
