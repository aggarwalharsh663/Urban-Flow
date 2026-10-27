$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$BackendPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $BackendPython)) {
    Write-Host "Backend environment not found. Setting it up now..."
    & (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Backend setup failed. Fix the setup error above, then run start.bat again."
    }
}

& $BackendPython -c "import cv2, ultralytics, dotenv"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Computer-vision packages are missing. Installing backend dependencies..."
    & (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency setup failed. Fix the setup error above, then run start.bat again."
    }
}

& $BackendPython -c "import cv2, ultralytics, dotenv"
if ($LASTEXITCODE -ne 0) {
    throw "OpenCV/Ultralytics could not be imported from backend\.venv. Review the setup output above."
}

Write-Host "Starting FastAPI at http://127.0.0.1:8000"
$ModelFile = @("yolov8m.pt", "yolov8s.pt", "yolov8n.pt") |
    Where-Object { Test-Path (Join-Path $PSScriptRoot $_) } |
    Select-Object -First 1
if ($ModelFile) {
    Write-Host "Local YOLO weights: $(Join-Path $PSScriptRoot $ModelFile)"
} else {
    Write-Host "No YOLO weights found. Add yolov8m.pt, yolov8s.pt, or yolov8n.pt to backend\."
}
& $BackendPython -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0) {
    throw "FastAPI stopped with exit code $LASTEXITCODE. Check whether port 8000 is already in use."
}
