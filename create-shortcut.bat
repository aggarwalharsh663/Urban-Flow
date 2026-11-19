REM Urban Flow - Adaptive Traffic Signal System
REM Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
REM
REM Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
REM Any additions, modifications, or contributed files to this project automatically
REM and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Urban Flow - Desktop Shortcut Setup
echo ============================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$sh = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $link = $sh.CreateShortcut(\"$desktop\Urban Flow.lnk\"); $link.TargetPath = '%~dp0frontend\node_modules\electron\dist\electron.exe'; $link.Arguments = '\"%~dp0frontend\"'; $link.WorkingDirectory = '%~dp0frontend'; $link.IconLocation = '%~dp0frontend\public\favicon.ico,0'; $link.Description = 'Urban Flow - Adaptive Traffic Signal System'; $link.Save(); Write-Host 'Shortcut created on Desktop successfully!'"

if errorlevel 1 (
    echo [ERROR] Could not create Desktop shortcut automatically.
    echo You can start the app directly by double-clicking 'Urban Flow.bat' or 'Urban Flow.vbs'.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Urban Flow shortcut has been placed on your Desktop.
echo You can now double-click 'Urban Flow' on your Desktop to start the app.
echo.
pause
