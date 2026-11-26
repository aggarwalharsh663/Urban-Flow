# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

import os
import subprocess
import sys
import zipfile
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent

# Check for installation in LocalAppData or fallback to WORK_DIR
LOCALAPPDATA = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
candidate_source = Path(LOCALAPPDATA) / "Programs" / "Urban Flow"
SOURCE_DIR = candidate_source if candidate_source.is_dir() else WORK_DIR

# Determine output directory (Desktop or current work dir)
desktop_candidate = Path(os.getenv("USERPROFILE", str(Path.home()))) / "Desktop"
onedrive_desktop = Path(os.getenv("USERPROFILE", str(Path.home()))) / "OneDrive" / "Desktop"
if onedrive_desktop.is_dir():
    DESKTOP = onedrive_desktop
elif desktop_candidate.is_dir():
    DESKTOP = desktop_candidate
else:
    DESKTOP = WORK_DIR

OUT_EXE = DESKTOP / "Urban Flow Setup.exe"

# 64-bit / 32-bit CSC compiler resolution
CSC_EXE = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
if not CSC_EXE.is_file():
    CSC_EXE = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")

for arg in sys.argv[1:]:
    if arg.startswith("--source="):
        SOURCE_DIR = Path(arg.split("=", 1)[1])
    elif arg.startswith("--out="):
        OUT_EXE = Path(arg.split("=", 1)[1])

EXCLUDE_PATTERNS = [
    ".git",
    "__pycache__",
    ".pytest_cache",
    "backend/uploads",
    "backend/reports",
    "backend/.urban_flow_token",
    "electron.log",
    "debug.log",
    ".urban_flow_token",
]

def is_excluded(rel_str: str) -> bool:
    normalized = rel_str.replace("\\", "/").lower()
    for pat in EXCLUDE_PATTERNS:
        if pat.lower() in normalized:
            return True
    if normalized.endswith((".pyc", ".pyo", ".log", ".tmp")):
        return True
    return False

def sign_binaries_in_dir(target_dir: Path):
    """Ensure critical Windows executables in target_dir are unblocked.
    Only sign if a genuine, non-self-signed certificate from a trusted CA is available.
    Never sign with local self-signed certificates, as Smart App Control blocks them."""
    if not target_dir.is_dir():
        return
    unblock_script = f"""
    $targets = @(
        '{target_dir}\\backend\\python\\python.exe',
        '{target_dir}\\backend\\python\\pythonw.exe',
        '{target_dir}\\Urban Flow.exe',
        '{target_dir}\\updater.exe'
    )
    foreach ($t in $targets) {{
        if (Test-Path $t) {{
            Unblock-File -Path $t -ErrorAction SilentlyContinue
        }}
    }}
    $cert = Get-ChildItem Cert:\\CurrentUser\\My | Where-Object {{
        $_.HasPrivateKey -and ($_.Issuer -ne $_.Subject) -and $_.Verify()
    }} | Select-Object -First 1
    if ($cert) {{
        $customTargets = @(
            '{target_dir}\\Urban Flow.exe',
            '{target_dir}\\updater.exe'
        )
        foreach ($t in $customTargets) {{
            if (Test-Path $t) {{
                Set-AuthenticodeSignature -FilePath $t -Certificate $cert | Out-Null
            }}
        }}
    }}
    """
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", unblock_script], capture_output=True, text=True)

def main():
    payload_zip = WORK_DIR / "urban_flow_payload.zip"
    has_source_override = any(arg.startswith("--source=") for arg in sys.argv[1:])
    rebuild_zip = "--rebuild-zip" in sys.argv or has_source_override or not payload_zip.exists() or payload_zip.stat().st_size < 100 * 1024 * 1024

    if rebuild_zip:
        print("=== [1/3] Signing binaries and building Complete Urban Flow payload ZIP ===")
        sign_binaries_in_dir(SOURCE_DIR)
        sign_binaries_in_dir(WORK_DIR)
        if payload_zip.exists():
            payload_zip.unlink()

        added_arcnames = set()
        total_files = 0

        with zipfile.ZipFile(payload_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            # 1. Add all files from SOURCE_DIR (full runtime, models, electron)
            for root, dirs, files in os.walk(SOURCE_DIR):
                for file in files:
                    full_path = Path(root) / file
                    rel = full_path.relative_to(SOURCE_DIR)
                    rel_str = str(rel)

                    if is_excluded(rel_str):
                        continue

                    arcname = rel_str.replace("\\", "/")

                    # Always take latest files from WORK_DIR if they exist
                    work_override = WORK_DIR / rel
                    if work_override.is_file():
                        zf.write(work_override, arcname=arcname)
                    else:
                        zf.write(full_path, arcname=arcname)

                    added_arcnames.add(arcname)
                    total_files += 1

                    if total_files % 1000 == 0:
                        print(f"Packaged {total_files} files...")

            # 2. Add any additional files from WORK_DIR that might not be in SOURCE_DIR
            for root, dirs, files in os.walk(WORK_DIR):
                rel_dir = Path(root).relative_to(WORK_DIR)
                if any(k in str(rel_dir).replace("\\", "/").lower() for k in [".git", "__pycache__", "dist-zip", "urbanflow-update", "update_stage"]):
                    continue

                for file in files:
                    if file in ["urban_flow_payload.zip", "update_payload.zip"]:
                        continue
                    full_path = Path(root) / file
                    rel = full_path.relative_to(WORK_DIR)
                    rel_str = str(rel)

                    if is_excluded(rel_str):
                        continue

                    arcname = rel_str.replace("\\", "/")
                    if arcname not in added_arcnames:
                        zf.write(full_path, arcname=arcname)
                        added_arcnames.add(arcname)
                        total_files += 1
    else:
        print(f"Using existing payload ZIP: {payload_zip.name} ({payload_zip.stat().st_size / (1024 * 1024):.1f} MB)")

    payload_size_mb = payload_zip.stat().st_size / (1024 * 1024)

    print(f"=== [2/3] Compiling {OUT_EXE.name} with csc.exe ===")
    setup_cs = WORK_DIR / "setup_form.cs"
    icon_ico = WORK_DIR / "frontend/public/favicon.ico"
    manifest = WORK_DIR / "app.manifest"
    emblem = WORK_DIR / "frontend/public/urban-flow-dark.png"

    cmd = [
        str(CSC_EXE),
        "/nologo",
        "/target:winexe",
        "/platform:x64",
        "/optimize+",
        f"/out:{OUT_EXE}",
        f"/win32icon:{icon_ico}",
        f"/win32manifest:{manifest}",
        "/reference:System.IO.Compression.dll",
        "/reference:System.IO.Compression.FileSystem.dll",
        f"/resource:{payload_zip},urban_flow_payload.zip",
    ]
    if emblem.is_file():
        cmd.append(f"/resource:{emblem},urban_flow_emblem.png")
    cmd.append(str(setup_cs))

    print("Running 64-bit C# compilation...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Compilation STDERR:\n", res.stderr)
        print("Compilation STDOUT:\n", res.stdout)
        sys.exit(res.returncode)

    print(f"SUCCESS: {OUT_EXE} compiled cleanly! ({OUT_EXE.stat().st_size / (1024 * 1024):.1f} MB)")

    print("=== [3/4] Unblocking and verifying output executable ===")
    sign_script = f"""
    Unblock-File -Path '{OUT_EXE}' -ErrorAction SilentlyContinue
    $cert = Get-ChildItem Cert:\\CurrentUser\\My | Where-Object {{
        $_.HasPrivateKey -and ($_.Issuer -ne $_.Subject) -and $_.Verify()
    }} | Select-Object -First 1
    if ($cert) {{
        Set-AuthenticodeSignature -FilePath '{OUT_EXE}' -Certificate $cert | Out-Null
        Write-Host "Authenticode signed with: $($cert.Thumbprint)"
    }}
    """
    subprocess.run(["powershell", "-NoProfile", "-Command", sign_script], capture_output=True, text=True)

    if "--clean" in sys.argv and payload_zip.is_file():
        try:
            payload_zip.unlink()
            print("Temporary payload ZIP removed.")
        except Exception:
            pass

if __name__ == "__main__":
    main()
