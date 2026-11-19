@echo off
setlocal
cd /d "%~dp0"

echo Creating Urban Flow shortcut on your Desktop...

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), 'Urban Flow.lnk')); $s.TargetPath = [System.IO.Path]::Combine('%~dp0', 'Run Urban Flow.bat'); $s.WorkingDirectory = '%~dp0'; if (Test-Path '%~dp0frontend\public\favicon.ico') { $s.IconLocation = '%~dp0frontend\public\favicon.ico' }; $s.Save()"

echo Done! Shortcut 'Urban Flow' has been placed on your Desktop.
ping 127.0.0.1 -n 2 >nul
exit /b 0
