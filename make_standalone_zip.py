# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

# Urban Flow - Build Standalone ZIP Package
import sys
import zipfile
from pathlib import Path

PAYLOAD_ZIP = Path(r"C:\Users\HARSH AGGARWAL\.gemini\antigravity\scratch\Urban-Flow\urban_flow_payload.zip")
APP_DIR = Path(r"C:\Users\HARSH AGGARWAL\AppData\Local\Programs\Urban Flow")
OUT_ZIP = Path(r"C:\Users\HARSH AGGARWAL\OneDrive\Desktop\Urban-Flow-v1.0-Standalone.zip")

print("Reading source payload...")
if not PAYLOAD_ZIP.is_file():
    print(f"Error: {PAYLOAD_ZIP} not found.")
    sys.exit(1)

with zipfile.ZipFile(PAYLOAD_ZIP, "r") as in_zf, zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as out_zf:
    total = len(in_zf.infolist())
    for i, info in enumerate(in_zf.infolist()):
        arcname = "Urban-Flow/" + info.filename
        content = in_zf.read(info.filename)
        out_zf.writestr(arcname, content)
        if (i + 1) % 2500 == 0 or (i + 1) == total:
            print(f"Packaged {i + 1}/{total} files...")

    # Ensure top-level launcher batch & vbs files are in Urban-Flow root
    for fname in ["Run Urban Flow.bat", "Create Desktop Shortcut.bat", "README.txt", "Urban Flow.vbs", "Urban Flow.bat"]:
        fpath = APP_DIR / fname
        if fpath.is_file():
            out_zf.write(fpath, arcname=f"Urban-Flow/{fname}")
            print(f"Added {fname}")

size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
print(f"SUCCESS: Created {OUT_ZIP.name} ({size_mb:.1f} MB)")
