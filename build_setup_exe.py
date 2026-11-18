import os
import subprocess
import sys
import zipfile
from pathlib import Path

SOURCE_DIR = Path(r"C:\Users\HARSH AGGARWAL\AppData\Local\Programs\Urban Flow")
WORK_DIR = Path(r"C:\Users\HARSH AGGARWAL\.gemini\antigravity\scratch\Urban-Flow")
CSC_EXE = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
OUT_EXE = Path(r"C:\Users\HARSH AGGARWAL\OneDrive\Desktop\Urban Flow Setup.exe")

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

def main():
    print("=== [1/3] Building Complete Urban Flow payload ZIP ===")
    payload_zip = WORK_DIR / "urban_flow_payload.zip"
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
            # Skip build outputs or temp dirs
            rel_dir = Path(root).relative_to(WORK_DIR)
            if any(k in str(rel_dir).replace("\\", "/").lower() for k in [".git", "__pycache__", "dist-zip", "urbanflow-update", "update_stage"]):
                continue

            for file in files:
                full_path = Path(root) / file
                if full_path.name in ["urban_flow_payload.zip", "update_payload.zip"]:
                    continue
                rel = full_path.relative_to(WORK_DIR)
                rel_str = str(rel)

                if is_excluded(rel_str):
                    continue

                arcname = rel_str.replace("\\", "/")
                if arcname not in added_arcnames:
                    zf.write(full_path, arcname=arcname)
                    added_arcnames.add(arcname)
                    total_files += 1

    payload_size_mb = payload_zip.stat().st_size / (1024 * 1024)
    print(f"Payload ZIP created: {total_files} unique files, {payload_size_mb:.1f} MB")

    print(f"=== [2/3] Compiling {OUT_EXE.name} with csc.exe ===")
    setup_cs = WORK_DIR / "setup_form.cs"
    icon_ico = WORK_DIR / "frontend/public/favicon.ico"
    manifest = WORK_DIR / "app.manifest"
    emblem = WORK_DIR / "frontend/public/urban-flow-dark.png"

    cmd = [
        str(CSC_EXE),
        "/nologo",
        "/target:winexe",
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

    print("Running C# compilation...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Compilation STDERR:\n", res.stderr)
        print("Compilation STDOUT:\n", res.stdout)
        sys.exit(res.returncode)

    print(f"SUCCESS: {OUT_EXE} compiled cleanly! ({OUT_EXE.stat().st_size / (1024 * 1024):.1f} MB)")

    print("=== [3/3] Cleaning up temporary zip ===")
    if payload_zip.is_file():
        try:
            payload_zip.unlink()
            print("Temporary payload ZIP removed.")
        except Exception:
            pass

if __name__ == "__main__":
    main()
