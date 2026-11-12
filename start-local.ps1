$ErrorActionPreference = "Stop"
$ProjectPath = $PSScriptRoot

# Automatically unblock files if repository or release ZIP was downloaded from web (Zone.Identifier stream)
Get-ChildItem -LiteralPath $ProjectPath -Recurse -File -Include *.exe,*.dll,*.bat,*.ps1,*.vbs,*.js,*.cjs,*.mjs | Unblock-File -ErrorAction SilentlyContinue

$Launcher = Join-Path $ProjectPath "start.bat"

if (-not (Test-Path $Launcher)) {
    throw "Could not find start.bat in $ProjectPath."
}

& $Launcher
