<#
.SYNOPSIS
    Development-only backend launcher for Urban Flow contributors (R7).
    Requires explicit developer opt-in via environment variable or confirmation.
#>
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if ($env:URBAN_FLOW_ENV -ne "development") {
    Write-Warning "DEVELOPMENT MODE WARNING: Auto-reloading and debug facilities are active."
    Write-Warning "Set URBAN_FLOW_ENV=development to suppress this notice."
}

$BackendPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $BackendPython)) {
    throw "Backend virtual environment not found at $BackendPython. Run setup.ps1 first."
}

Write-Host "Starting FastAPI in Development Mode (--reload active) at http://127.0.0.1:8000"
$UvicornArgs = @("main:app", "--host", "127.0.0.1", "--port", "8000", "--reload")
& $BackendPython -m uvicorn @UvicornArgs
