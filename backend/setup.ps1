$ErrorActionPreference = "Stop"
$BackendPath = $PSScriptRoot
$PackageIndex = "https://mirrors.ustc.edu.cn/pypi/simple"
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

& $VenvPython -m pip install --upgrade pip --index-url $PackageIndex --timeout 120 --retries 3
if ($LASTEXITCODE -ne 0) { throw "Could not update pip from the configured Python package mirror." }

& $VenvPython -m pip install -r (Join-Path $BackendPath "requirements.txt") --index-url $PackageIndex --timeout 120 --retries 3
if ($LASTEXITCODE -ne 0) { throw "Backend dependencies did not install successfully." }

Write-Host "Backend dependencies are ready."
