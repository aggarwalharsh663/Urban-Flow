import hashlib
import os
import re
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

def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().upper()

def main():
    print("=== [1/4] Building Urban Flow payload ZIP ===")
    payload_zip = WORK_DIR / "urban_flow_payload.zip"
    if payload_zip.exists():
        payload_zip.unlink()

    total_files = 0
    with zipfile.ZipFile(payload_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        # 1. Add root files from WORK_DIR (to ensure latest code)
        for fname in ["Urban Flow.exe", "start.bat", "Urban Flow.bat", "app.manifest", "README.md", "README-WINDOWS-APP.md"]:
            fpath = WORK_DIR / fname
            if fpath.is_file():
                zf.write(fpath, arcname=fname)
                total_files += 1

        # 2. Add full installed application tree (python runtime, electron, node_modules, models, dist)
        for root, dirs, files in os.walk(SOURCE_DIR):
            for file in files:
                full_path = Path(root) / file
                rel = full_path.relative_to(SOURCE_DIR)
                rel_str = str(rel)

                if is_excluded(rel_str):
                    continue

                # Ensure we take the latest video_tracker.py and frontend dist from WORK_DIR
                if rel_str.replace("\\", "/") == "backend/services/video_tracker.py":
                    zf.write(WORK_DIR / "backend/services/video_tracker.py", arcname=rel_str)
                elif rel_str.replace("\\", "/").startswith("frontend/dist/"):
                    zf.write(WORK_DIR / rel_str, arcname=rel_str)
                elif rel_str.replace("\\", "/") == "Urban Flow.exe":
                    # Already added
                    continue
                else:
                    zf.write(full_path, arcname=rel_str)
                total_files += 1

                if total_files % 500 == 0:
                    print(f"Packaged {total_files} files...")

    payload_size_mb = payload_zip.stat().st_size / (1024 * 1024)
    print(f"Payload ZIP created: {total_files} files, {payload_size_mb:.1f} MB")

    print("=== [2/4] Computing SHA-256 Checksum ===")
    sha256 = compute_sha256(payload_zip)
    print(f"Payload SHA-256: {sha256}")

    print("=== [3/4] Embedding SHA-256 into setup_form.cs ===")
    setup_cs = WORK_DIR / "setup_form.cs"
    code = setup_cs.read_text(encoding="utf-8")
    code_updated = re.sub(
        r'public static string ExpectedPayloadSha256\s*=\s*"[^"]*";',
        f'public static string ExpectedPayloadSha256 = "{sha256}";',
        code
    )
    setup_cs.write_text(code_updated, encoding="utf-8")

    print(f"=== [4/4] Compiling {OUT_EXE.name} with csc.exe ===")
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

    print(f"SUCCESS: {OUT_EXE} compiled cleanly!")
    print(f"Final executable size: {OUT_EXE.stat().st_size / (1024 * 1024):.1f} MB")

    # Clean up temporary payload zip to free disk space
    if payload_zip.is_file():
        try:
            payload_zip.unlink()
            print("Temporary payload ZIP cleaned up.")
        except Exception:
            pass

if __name__ == "__main__":
    main()
