REM Urban Flow - Adaptive Traffic Signal System
REM Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
REM
REM Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
REM Any additions, modifications, or contributed files to this project automatically
REM and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

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
