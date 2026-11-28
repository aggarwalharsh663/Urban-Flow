REM Urban Flow - Adaptive Traffic Signal System
REM Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
REM
REM Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
REM Any additions, modifications, or contributed files to this project automatically
REM and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

@echo off
setlocal
cd /d "%~dp0"

echo Creating Urban Flow shortcut on your Desktop...

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('DesktopDirectory'), 'Urban Flow.lnk'); $s = $ws.CreateShortcut($desktop); $electron = [System.IO.Path]::Combine('%~dp0', 'frontend\node_modules\electron\dist\electron.exe'); $frontend = [System.IO.Path]::Combine('%~dp0', 'frontend'); if (Test-Path $electron) { $s.TargetPath = $electron; $s.Arguments = '\"' + $frontend + '\"'; $s.WorkingDirectory = $frontend } else { $s.TargetPath = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('System'), 'wscript.exe'); $s.Arguments = '\"' + [System.IO.Path]::Combine('%~dp0', 'Urban Flow.vbs') + '\"'; $s.WorkingDirectory = '%~dp0' }; if (Test-Path '%~dp0frontend\public\favicon.ico') { $s.IconLocation = '%~dp0frontend\public\favicon.ico,0' }; $s.Description = 'Urban Flow - Adaptive Traffic Signal System'; $s.Save()"

echo Done! Shortcut 'Urban Flow' has been placed on your Desktop.
ping 127.0.0.1 -n 2 >nul
exit /b 0
