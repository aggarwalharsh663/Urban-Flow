$ErrorActionPreference = "Stop"
$ProjectPath = $PSScriptRoot
$Launcher = Join-Path $ProjectPath "start.bat"

if (-not (Test-Path $Launcher)) {
    throw "Could not find start.bat in $ProjectPath."
}

& $Launcher
