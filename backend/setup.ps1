$ErrorActionPreference = "Stop"
$BackendPath = $PSScriptRoot
# Secure supply chain: Use official PyPI index
$PackageIndex = "https://pypi.org/simple"
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue

if (-not $PythonCommand) {
    throw "Python 3.10 or newer is required. Install Python, then rerun .\backend\setup.ps1."
}

$PythonExecutable = $PythonCommand.Source
$PythonVersionOutput = & $PythonExecutable -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Could not run Python. Install Python 3.10 or newer, then rerun .\backend\setup.ps1."
}

$PythonVersion = [version]$PythonVersionOutput.Trim()
if ($PythonVersion -lt [version]"3.10") {
    throw "Python 3.10 or newer is required; found Python $PythonVersion."
}

$VenvPython = Join-Path $BackendPath ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & $PythonExecutable -m venv (Join-Path $BackendPath ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create backend\.venv." }
}

# Check if dependencies are already satisfied offline (avoids unnecessary outbound firewall traffic)
$DepsCheck = & $VenvPython -c "import fastapi, uvicorn, pydantic; print('OK')" 2>$null
if ($LASTEXITCODE -eq 0 -and $DepsCheck -eq "OK") {
    Write-Host "Backend dependencies are already installed and satisfied offline."
    exit 0
}

# Optional pip upgrade with short timeout to prevent hanging behind firewalls
Write-Host "Checking for pip updates..."
& $VenvPython -m pip install --upgrade pip --index-url $PackageIndex --timeout 15 --retries 1 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Pip upgrade skipped (network offline or restricted by firewall)."
}

# Install requirements with timeout and clear firewall diagnostics
Write-Host "Installing dependencies from requirements.txt..."
& $VenvPython -m pip install -r (Join-Path $BackendPath "requirements.txt") --index-url $PackageIndex --timeout 30 --retries 2
if ($LASTEXITCODE -ne 0) {
    $DepsCheckPost = & $VenvPython -c "import fastapi, uvicorn, pydantic; print('OK')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $DepsCheckPost -eq "OK") {
        Write-Host "[WARNING] Outbound connection to PyPI was limited by firewall, but essential dependencies are available."
    } else {
        throw "Backend dependencies could not be downloaded. If your network firewall blocks outbound traffic to pypi.org, configure HTTP_PROXY or use the pre-bundled Python runtime at backend\python\."
    }
}

Write-Host "Backend dependencies are ready."
