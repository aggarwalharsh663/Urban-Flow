# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

import os
import subprocess
import tempfile
import sys
import shutil
import pytest

if sys.platform != "win32" or not (shutil.which("powershell.exe") or shutil.which("powershell")):
    pytest.skip("Windows Smart App Control tests require Windows and PowerShell", allow_module_level=True)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUNNER_PS1 = os.path.join(ROOT_DIR, "backend", "tests", "updater_test_runner.ps1")


def call_runner(action: str, arg1: str = "", arg2: str = "") -> str:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", RUNNER_PS1,
        "-Action", action,
        "-Arg1", arg1,
        "-Arg2", arg2
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return proc.stdout.strip()


def test_locate_electron_valid_repo():
    """Verify LocateElectron resolves the bundled Electron executable and frontend directory in the Urban Flow repository."""
    electron_exe = os.path.join(ROOT_DIR, "frontend", "node_modules", "electron", "dist", "electron.exe")
    if not os.path.isfile(electron_exe):
        pytest.skip("frontend/node_modules/electron not installed; run npm install in frontend to test live resolution")

    out = call_runner("locate", ROOT_DIR)
    parts = out.split("|")
    assert len(parts) == 3
    success, exe, frontend = parts[0], parts[1], parts[2]
    assert success.lower() == "true"
    assert os.path.isfile(exe)
    assert exe.lower().endswith("electron.exe")
    assert os.path.isdir(frontend)
    assert frontend.lower().endswith("frontend")


def test_locate_electron_path_with_spaces():
    """Verify LocateElectron properly handles base directories containing spaces."""
    with tempfile.TemporaryDirectory(prefix="Urban Flow Test Dir With Spaces ") as tmp_dir:
        # Create mock frontend/node_modules/electron/dist/electron.exe
        electron_dir = os.path.join(tmp_dir, "frontend", "node_modules", "electron", "dist")
        os.makedirs(electron_dir, exist_ok=True)
        fake_electron = os.path.join(electron_dir, "electron.exe")
        with open(fake_electron, "wb") as f:
            f.write(b"MZ_MOCK_EXE")

        out = call_runner("locate", tmp_dir)
        parts = out.split("|")
        assert len(parts) == 3
        success, exe, frontend = parts[0], parts[1], parts[2]
        assert success.lower() == "true"
        assert os.path.samefile(exe, fake_electron)
        assert os.path.samefile(frontend, os.path.join(tmp_dir, "frontend"))


def test_locate_electron_missing_returns_false():
    """Verify LocateElectron returns false if Electron executable is missing in the target directory."""
    with tempfile.TemporaryDirectory(prefix="empty_dir_") as tmp_dir:
        out = call_runner("locate", tmp_dir)
        parts = out.split("|")
        success = parts[0]
        # In an empty directory without machine-wide fallback, it returns False
        # (or True if machine-wide installed, but here we verify it handles non-existing gracefully)
        if success.lower() == "false":
            assert True
        else:
            # If machine-wide Program Files exists on test host, ensure it still returned a valid path
            assert os.path.isfile(parts[1])


def test_no_urban_flow_exe_references_in_batch_and_vbs():
    """Verify that start.bat, Urban Flow.bat, and Urban Flow.vbs do not launch Urban Flow.exe."""
    scripts = ["Urban Flow.bat", "start.bat", "Urban Flow.vbs"]
    for s in scripts:
        path = os.path.join(ROOT_DIR, s)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        assert "Urban Flow.exe" not in content, f"Script {s} must not reference Urban Flow.exe fallback"


def test_setup_form_no_urban_flow_exe_shortcut_or_launch():
    """Verify setup_form.cs only creates shortcuts and launches electron.exe, not Urban Flow.exe."""
    setup_form_path = os.path.join(ROOT_DIR, "setup_form.cs")
    with open(setup_form_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    assert "Urban Flow.exe" not in content, "setup_form.cs must not reference Urban Flow.exe"
    assert "LocateElectron" in content, "setup_form.cs must implement LocateElectron"
    assert "LaunchElectron" in content, "setup_form.cs must implement LaunchElectron"


def test_updater_launches_electron_not_urban_flow_exe():
    """Verify updater.cs launches Electron upon update completion and not Urban Flow.exe."""
    updater_path = os.path.join(ROOT_DIR, "updater.cs")
    with open(updater_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    assert "Urban Flow.exe" not in content, "updater.cs must not reference Urban Flow.exe"
    assert "LaunchElectron(targetDir)" in content, "updater.cs must restart the app via LaunchElectron"
