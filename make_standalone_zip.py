# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

# Urban Flow - Build Standalone ZIP Package
import subprocess
import sys
import zipfile
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent
PAYLOAD_ZIP = WORK_DIR / "urban_flow_payload.zip"
APP_DIR = Path(r"C:\Users\HARSH AGGARWAL\AppData\Local\Programs\Urban Flow")
OUT_ZIP = Path(r"C:\Users\HARSH AGGARWAL\OneDrive\Desktop\Urban-Flow-v1.0-Standalone.zip")

print("Ensuring binaries are unblocked before standalone packaging...")
sign_script = f"""
$targets = @(
    '{WORK_DIR}\\backend\\python\\python.exe',
    '{WORK_DIR}\\backend\\python\\pythonw.exe',
    '{WORK_DIR}\\Urban Flow.exe',
    '{WORK_DIR}\\updater.exe'
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
        '{WORK_DIR}\\Urban Flow.exe',
        '{WORK_DIR}\\updater.exe'
    )
    foreach ($t in $customTargets) {{
        if (Test-Path $t) {{
            Set-AuthenticodeSignature -FilePath $t -Certificate $cert | Out-Null
        }}
    }}
}}
"""
subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", sign_script], capture_output=True, text=True)

print("Reading source payload...")
if not PAYLOAD_ZIP.is_file():
    print(f"Error: {PAYLOAD_ZIP} not found.")
    sys.exit(1)

override_names = {"Run Urban Flow.bat", "Create Desktop Shortcut.bat", "README.txt", "Urban Flow.vbs", "Urban Flow.bat", "Urban Flow.exe"}

with zipfile.ZipFile(PAYLOAD_ZIP, "r") as in_zf, zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as out_zf:
    total = len(in_zf.infolist())
    for i, info in enumerate(in_zf.infolist()):
        if info.filename in override_names:
            continue
        arcname = "Urban-Flow/" + info.filename
        content = in_zf.read(info.filename)
        out_zf.writestr(arcname, content)
        if (i + 1) % 2500 == 0 or (i + 1) == total:
            print(f"Packaged {i + 1}/{total} files...")

    # Ensure top-level launcher batch & vbs files are in Urban-Flow root
    for fname in ["Run Urban Flow.bat", "Create Desktop Shortcut.bat", "README.txt", "Urban Flow.vbs", "Urban Flow.bat", "Urban Flow.exe"]:
        fpath = WORK_DIR / fname if (WORK_DIR / fname).is_file() else (APP_DIR / fname)
        if fpath.is_file():
            out_zf.write(fpath, arcname=f"Urban-Flow/{fname}")
            print(f"Added {fname}")

size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
print(f"SUCCESS: Created {OUT_ZIP.name} ({size_mb:.1f} MB)")
