# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

"""
Automated Security Tests for Zip Slip Prevention in updater.cs extraction helper.
Verifies canonical path validation, containment checks, traversal prevention,
and safe archive extraction across all 10 required vulnerability scenarios.
"""

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
RUNNER_PS1 = Path(__file__).resolve().parent / "updater_test_runner.ps1"
UPDATER_CS = ROOT_DIR / "updater.cs"


def run_entry_check(entry_name: str, target_dir: str) -> tuple[bool, str]:
    """Invoke updater.cs IsSafeZipEntry via PowerShell test runner with base64 encoding."""
    entry_b64 = base64.b64encode(entry_name.encode("utf-8")).decode("ascii")
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER_PS1),
        "-Action",
        "entry",
        "-Arg1B64",
        entry_b64,
        "-Arg2",
        target_dir,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Process execution failed: {res.stderr}\n{res.stdout}"
    line = res.stdout.strip()
    assert "|" in line, f"Runner returned invalid output format (expected 'status|destination'): {line}"
    status, dest = line.split("|", 1)
    assert status in ("True", "False"), f"Runner returned unexpected status: {status}"
    return (status == "True", dest)


def run_extract_test(zip_path: Path, target_dir: Path) -> int:
    """Invoke updater.cs ExtractArchiveSafely via PowerShell test runner."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER_PS1),
        "-Action",
        "extract",
        "-Arg1",
        str(zip_path),
        "-Arg2",
        str(target_dir),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Process extraction failed: {res.stderr}\n{res.stdout}"
    for line in res.stdout.splitlines():
        if line.startswith("EXTRACTED:"):
            return int(line.split(":", 1)[1].strip())
    return 0


# --- Scenario 1: Normal ZIP Extraction ---
def test_scenario1_normal_zip_extraction(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    safe, dest = run_entry_check("main.js", str(target_dir))
    assert safe is True
    assert Path(dest).name == "main.js"
    assert Path(dest).parent.resolve() == target_dir.resolve()

    # End-to-end archive extraction
    zip_path = tmp_path / "test1.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("bundle.js", "console.log('safe');")
        z.writestr("index.html", "<h1>UrbanFlow</h1>")

    extracted = run_extract_test(zip_path, target_dir)
    assert extracted == 2
    assert (target_dir / "bundle.js").read_text() == "console.log('safe');"
    assert (target_dir / "index.html").read_text() == "<h1>UrbanFlow</h1>"


# --- Scenario 2: Nested Directory Extraction ---
def test_scenario2_nested_directory_extraction(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    safe, dest = run_entry_check("assets/images/logo.png", str(target_dir))
    assert safe is True
    assert Path(dest).resolve() == (target_dir / "assets" / "images" / "logo.png").resolve()

    zip_path = tmp_path / "test2.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("frontend/dist/client/assets/style.css", "body { margin: 0; }")

    extracted = run_extract_test(zip_path, target_dir)
    assert extracted == 1
    extracted_file = target_dir / "frontend" / "dist" / "client" / "assets" / "style.css"
    assert extracted_file.is_file()
    assert extracted_file.read_text() == "body { margin: 0; }"


# --- Scenario 3: ../ Traversal Sequences ---
def test_scenario3_forward_slash_traversal_rejected(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    evil_entries = [
        "../evil.dll",
        "../../Windows/System32/calc.exe",
        "sub/../../evil.txt",
        "a/b/../../../secret.txt",
    ]
    for evil in evil_entries:
        safe, _ = run_entry_check(evil, str(target_dir))
        assert safe is False, f"Expected {evil} to be rejected"

    # End-to-end extraction test with zipfile containing traversal entry
    outside_file = tmp_path / "escaped.txt"
    assert not outside_file.exists()

    zip_path = tmp_path / "malicious_forward.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("../escaped.txt", "MALICIOUS")
        z.writestr("legit.txt", "LEGIT")

    extracted = run_extract_test(zip_path, target_dir)
    assert extracted == 1
    assert not outside_file.exists(), "Zip slip wrote outside target directory!"
    assert (target_dir / "legit.txt").read_text() == "LEGIT"


# --- Scenario 4: ..\ Traversal Sequences ---
def test_scenario4_backward_slash_traversal_rejected(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    evil_entries = [
        r"..\evil.dll",
        r"..\..\Windows\System32\cmd.exe",
        r"folder\..\..\evil.txt",
        r"a\b\..\..\..\outside.bin",
    ]
    for evil in evil_entries:
        safe, _ = run_entry_check(evil, str(target_dir))
        assert safe is False, f"Expected {evil} to be rejected"

    outside_file = tmp_path / "back_escaped.txt"
    assert not outside_file.exists()

    zip_path = tmp_path / "malicious_back.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr(r"..\back_escaped.txt", "MALICIOUS_BACK")
        z.writestr("valid.txt", "VALID")

    extracted = run_extract_test(zip_path, target_dir)
    assert extracted == 1
    assert not outside_file.exists(), "Zip slip backslash wrote outside target directory!"
    assert (target_dir / "valid.txt").read_text() == "VALID"


# --- Scenario 5: Absolute Windows Paths ---
def test_scenario5_absolute_windows_paths_rejected(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    absolute_entries = [
        "/Windows/System32/evil.dll",
        r"\Windows\System32\evil.dll",
        "/etc/shadow",
        r"\escaped.txt",
    ]
    for entry in absolute_entries:
        safe, _ = run_entry_check(entry, str(target_dir))
        assert safe is False, f"Expected absolute path {entry} to be rejected"


# --- Scenario 6: Drive-Letter Paths ---
def test_scenario6_drive_letter_paths_rejected(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    drive_entries = [
        r"C:\Windows\System32\evil.dll",
        "C:/Windows/System32/evil.dll",
        "D:payload.exe",
        "C:evil.txt",
        r"Z:\data.bin",
    ]
    for entry in drive_entries:
        safe, _ = run_entry_check(entry, str(target_dir))
        assert safe is False, f"Expected drive-letter path {entry} to be rejected"


# --- Scenario 7: UNC Paths ---
def test_scenario7_unc_paths_rejected(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    unc_entries = [
        r"\\attacker-server\share\evil.dll",
        "//attacker-server/share/evil.dll",
        r"\\127.0.0.1\c$\Windows\System32\cmd.exe",
        r"\\?\C:\Windows\evil.dll",
    ]
    for entry in unc_entries:
        safe, _ = run_entry_check(entry, str(target_dir))
        assert safe is False, f"Expected UNC path {entry} to be rejected"


# --- Scenario 8: Prefix-Confusion Paths ---
def test_scenario8_prefix_confusion_paths_rejected(tmp_path):
    target_dir = tmp_path / "UrbanFlow"
    target_dir.mkdir()
    confusion_dir = tmp_path / "UrbanFlow_Attacker"
    confusion_dir.mkdir()

    evil_entry = "../UrbanFlow_Attacker/evil.dll"
    safe, _ = run_entry_check(evil_entry, str(target_dir))
    assert safe is False, "Prefix-confusion traversal must be rejected"

    zip_path = tmp_path / "prefix_confusion.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("../UrbanFlow_Attacker/evil.dll", "PWNED")
        z.writestr("safe_component.dll", "SAFE")

    extracted = run_extract_test(zip_path, target_dir)
    assert extracted == 1
    assert not (confusion_dir / "evil.dll").exists(), "Prefix-confusion bypassed directory containment!"
    assert (target_dir / "safe_component.dll").read_text() == "SAFE"


# --- Scenario 9: Empty, Whitespace, or Malformed Archive Entry Names ---
def test_scenario9_malformed_entries_rejected(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    malformed_entries = [
        "",
        "   ",
        "\t\r\n",
        "file\0name.txt",
        "illegal<char>.txt",
        "illegal|pipe.txt",
        "illegal?mark.txt",
        "illegal*star.txt",
    ]
    for entry in malformed_entries:
        safe, _ = run_entry_check(entry, str(target_dir))
        assert safe is False, f"Expected malformed entry {repr(entry)} to be rejected"


# --- Scenario 10: Mixed Slash and Backslash Paths ---
def test_scenario10_mixed_slash_and_backslash_handling(tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()

    # Valid mixed-slash path inside target directory
    safe, dest = run_entry_check(r"nested\folder/sub\file.txt", str(target_dir))
    assert safe is True
    expected_path = target_dir / "nested" / "folder" / "sub" / "file.txt"
    assert Path(dest).resolve() == expected_path.resolve()

    # Malicious mixed-slash traversal
    malicious_mixed = [
        r"sub/dir\..\..\..\evil.txt",
        r"folder\sub/../../outside.dll",
        r"a/b\c/..\..\..\..\escaped.txt",
    ]
    for evil in malicious_mixed:
        safe, _ = run_entry_check(evil, str(target_dir))
        assert safe is False, f"Expected mixed-slash traversal {evil} to be rejected"

    # End-to-end extraction with mixed slashes
    zip_path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr(r"valid/folder\component.json", '{"status": "ok"}')
        z.writestr(r"nested\dir/../../escaped.txt", "PWNED")

    outside_file = tmp_path / "escaped.txt"
    extracted = run_extract_test(zip_path, target_dir)
    assert extracted == 1
    assert not outside_file.exists()
    assert (target_dir / "valid" / "folder" / "component.json").read_text() == '{"status": "ok"}'
