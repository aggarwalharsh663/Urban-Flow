# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

param(
    [Parameter(Mandatory=$true)][string]$Action,
    [Parameter(Mandatory=$false)][string]$Arg1 = "",
    [Parameter(Mandatory=$false)][string]$Arg2 = "",
    [Parameter(Mandatory=$false)][string]$Arg1B64 = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$updaterPath = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "updater.cs"
if (-not (Test-Path $updaterPath)) {
    $updaterPath = Join-Path $PSScriptRoot "..\..\updater.cs"
}
$updaterPath = [System.IO.Path]::GetFullPath($updaterPath)

Add-Type -ReferencedAssemblies 'System.Windows.Forms.dll','System.Drawing.dll','System.IO.Compression.dll','System.IO.Compression.FileSystem.dll' -Path $updaterPath

if ($Arg1B64 -ne "") {
    $bytes = [System.Convert]::FromBase64String($Arg1B64)
    $Arg1 = [System.Text.Encoding]::UTF8.GetString($bytes)
}

if ($Action -eq "entry") {
    $dest = ""
    $res = [UrbanFlowUpdater.Program]::IsSafeZipEntry($Arg1, $Arg2, [ref]$dest)
    Write-Output "$res|$dest"
} elseif ($Action -eq "locate") {
    $electronExe = ""
    $frontendDir = ""
    $res = [UrbanFlowUpdater.Program]::LocateElectron($Arg1, [ref]$electronExe, [ref]$frontendDir)
    Write-Output "$res|$electronExe|$frontendDir"
} elseif ($Action -eq "extract") {
    $zipFullPath = [System.IO.Path]::GetFullPath($Arg1)
    $targetFullPath = [System.IO.Path]::GetFullPath($Arg2)
    $fs = [System.IO.File]::OpenRead($zipFullPath)
    $zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Read)
    try {
        $count = [UrbanFlowUpdater.Program]::ExtractArchiveSafely($zip, $targetFullPath)
        Write-Output "EXTRACTED:$count"
    } finally {
        $zip.Dispose()
        $fs.Dispose()
    }
}
