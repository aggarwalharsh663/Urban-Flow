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

echo Compiling Urban Flow.exe with metadata, icons, and UAC manifest...
"%CSC_EXE%" /nologo /target:winexe /optimize+ /win32manifest:app.manifest /win32icon:frontend\public\favicon.ico /out:"Urban Flow.exe" launcher.cs
if errorlevel 1 (
    echo [ERROR] Compilation failed.
    exit /b 1
)

echo Urban Flow.exe built successfully.
endlocal
