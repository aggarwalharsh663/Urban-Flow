REM Urban Flow - Adaptive Traffic Signal System
REM Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
REM
REM Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
REM Any additions, modifications, or contributed files to this project automatically
REM and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

@echo off
setlocal
cd /d "%~dp0"

set "CSC_EXE=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC_EXE%" (
    set "CSC_EXE=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)

if not exist "%CSC_EXE%" (
    echo [ERROR] C# compiler csc.exe was not found.
    exit /b 1
)

echo Compiling Urban Flow.exe with metadata, icons, x64 architecture, and UAC manifest...
"%CSC_EXE%" /nologo /target:winexe /platform:x64 /optimize+ /win32manifest:app.manifest /win32icon:frontend\public\favicon.ico /out:"Urban Flow.exe" launcher.cs
if errorlevel 1 (
    echo [ERROR] Compilation failed.
    exit /b 1
)

echo Urban Flow.exe built successfully.

powershell -NoProfile -Command "$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -like '*Harsh Aggarwal*' } | Select-Object -First 1; if ($cert) { Set-AuthenticodeSignature -FilePath 'Urban Flow.exe' -Certificate $cert | Out-Null; Write-Host 'Urban Flow.exe signed with:' $cert.Thumbprint }; Unblock-File -Path 'Urban Flow.exe' -ErrorAction SilentlyContinue"

endlocal
