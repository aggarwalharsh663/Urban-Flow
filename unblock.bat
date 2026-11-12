@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Urban Flow - Unblocking Downloaded Files (Zone.Identifier)
echo ============================================================
echo.
echo Removing Windows Mark-of-the-Web security blocks from project files...

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "Write-Host 'Scanning files...'; " ^
  "$files = Get-ChildItem -LiteralPath '%~dp0' -Recurse -File -Include *.exe,*.dll,*.bat,*.ps1,*.vbs,*.js,*.cjs,*.mjs,*.json; " ^
  "$count = 0; " ^
  "foreach ($f in $files) { " ^
  "  if (Get-Item $f.FullName -Stream 'Zone.Identifier' -ErrorAction SilentlyContinue) { " ^
  "    Unblock-File -LiteralPath $f.FullName -ErrorAction SilentlyContinue; " ^
  "    $count++; " ^
  "  } " ^
  "} " ^
  "Write-Host \"Successfully unblocked $count file(s).\"; "

echo.
echo All project files are unblocked and ready to run.
echo You can now launch Urban Flow with start.bat or Urban Flow.bat.
echo ============================================================
pause
endlocal
