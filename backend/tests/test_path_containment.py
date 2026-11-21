# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

"""
Tests for Path Traversal Prevention, Directory Containment, and Prefix Confusion Immunity in main.py.
Verifies all 9 requirements:
1. Normal uploaded file.
2. Nested upload path handling.
3. ../ traversal rejection.
4. ..\\ traversal rejection.
5. Prefix-confusion path rejection (/app/uploads_evil vs /app/uploads).
6. Absolute path rejection.
7. Symlink pointing outside upload directory rejection.
8. Nonexistent file handling.
9. Malformed filename rejection.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main
from main import app, is_path_contained, UPLOAD_DIR
from security_config import get_or_create_api_token


@pytest.fixture
def auth_client():
    token = get_or_create_api_token()
    client = TestClient(app)
    return client, {"X-API-Token": token}


@pytest.fixture
def temp_upload_dir(tmp_path: Path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    return upload_dir


class TestPathContainmentSecurity:
    """Direct validation of is_path_contained and the /uploads/{filename} endpoint."""

    def test_normal_uploaded_file(self, auth_client, temp_upload_dir: Path):
        """1. Legitimate file within UPLOAD_DIR is contained and served."""
        client, headers = auth_client
        test_file = temp_upload_dir / "test_normal_legit.png"
        test_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        try:
            assert is_path_contained(temp_upload_dir, test_file) is True
            resp = client.get(f"/uploads/{test_file.name}", headers=headers)
            assert resp.status_code == 200
            assert resp.headers.get("x-content-type-options") == "nosniff"
            assert "sandbox" in resp.headers.get("content-security-policy", "")
        finally:
            test_file.unlink(missing_ok=True)

    def test_nested_upload_path(self, tmp_path: Path, auth_client):
        """2. Nested subdirectories inside upload dir are correctly identified as contained."""
        client, headers = auth_client
        sub_dir = tmp_path / "uploads" / "subdir"
        sub_dir.mkdir(parents=True)
        nested_file = sub_dir / "nested_image.jpg"
        nested_file.write_bytes(b"JPEG DATA")

        # Filesystem containment helper confirms containment
        assert is_path_contained(tmp_path / "uploads", nested_file) is True

        # Endpoint strictly enforces flat filename pattern (no directory separators)
        resp = client.get("/uploads/subdir/nested_image.jpg", headers=headers)
        assert resp.status_code in (404, 405)  # URL route mismatch or rejected filename

    def test_dot_dot_slash_traversal(self, tmp_path: Path, auth_client):
        """3. ../ traversal attempts are rejected by containment and regex."""
        client, headers = auth_client
        base = tmp_path / "uploads"
        base.mkdir()
        target = base / ".." / "secret.png"

        assert is_path_contained(base, target) is False

        # Endpoint test
        resp = client.get("/uploads/..%2Fsecret.png", headers=headers)
        assert resp.status_code in (404, 403)

    def test_dot_dot_backslash_traversal(self, tmp_path: Path, auth_client):
        """4. ..\\ traversal attempts are rejected by containment and regex."""
        client, headers = auth_client
        base = tmp_path / "uploads"
        base.mkdir()
        target = Path(f"{base}\\..\\secret.png")

        assert is_path_contained(base, target) is False

        # Endpoint test
        resp = client.get("/uploads/..%5Csecret.png", headers=headers)
        assert resp.status_code in (404, 403)

    def test_prefix_confusion_attack(self, tmp_path: Path):
        """
        5. CRITICAL TEST: Prefix confusion attack.
        /app/uploads_evil/file.png starts with /app/uploads as a string,
        but is NOT contained within /app/uploads.
        """
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        evil_dir = tmp_path / "uploads_evil"
        evil_dir.mkdir()
        evil_file = evil_dir / "malicious.png"
        evil_file.write_bytes(b"EVIL_PAYLOAD")

        # Flawed string prefix check would evaluate to True:
        flawed_prefix_check = str(evil_file.resolve()).startswith(str(base_dir.resolve()))
        assert flawed_prefix_check is True, "Sanity check: string prefix check demonstrates vulnerability"

        # Correct containment check rejects prefix confusion:
        secure_containment_check = is_path_contained(base_dir, evil_file)
        assert secure_containment_check is False, "is_path_contained must reject prefix confusion"

    def test_absolute_path_escape(self, tmp_path: Path):
        """6. Absolute paths resolving outside the base directory are rejected."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # Points to system root or outside folder
        abs_target = Path("C:/Windows/System32/cmd.exe" if sys.platform == "win32" else "/etc/passwd")
        assert is_path_contained(base_dir, abs_target) is False

    def test_symlink_pointing_outside_upload_directory(self, tmp_path: Path, auth_client, temp_upload_dir: Path):
        """
        7. A symlink (or reparse point) inside UPLOAD_DIR pointing to a sensitive file outside UPLOAD_DIR
        must be caught and rejected (403 Forbidden).
        """
        client, headers = auth_client

        outside_secret = tmp_path / "outside_secret.png"
        outside_secret.write_bytes(b"SECRET_DATA")

        symlink_file = temp_upload_dir / "symlink_escape.png"
        try:
            created = False
            try:
                symlink_file.symlink_to(outside_secret)
                created = True
            except (OSError, NotImplementedError):
                pass

            if created:
                # Direct test with real symlink
                assert is_path_contained(temp_upload_dir, symlink_file) is False
                resp = client.get(f"/uploads/{symlink_file.name}", headers=headers)
                assert resp.status_code == 403
            else:
                # If Windows non-admin permissions block symlink creation, test via path resolution
                with patch.object(Path, "resolve", return_value=outside_secret.resolve()):
                    fake_target = temp_upload_dir / "test_fake_symlink.png"
                    assert is_path_contained(temp_upload_dir, fake_target) is False
        finally:
            if symlink_file.is_symlink() or symlink_file.exists():
                symlink_file.unlink(missing_ok=True)

    def test_nonexistent_file(self, auth_client):
        """8. Nonexistent file within UPLOAD_DIR returns 404 Not Found."""
        client, headers = auth_client
        resp = client.get("/uploads/completely_missing_file_98765.jpg", headers=headers)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "File not found."

    def test_malformed_filename_rejected(self, auth_client):
        """9. Malformed filenames with invalid characters or non-media extensions are rejected (404)."""
        client, headers = auth_client

        malformed_cases = [
            "malicious.exe",
            "script.js",
            "shell.php",
            "image.png.exe",
            "invalid;name.png",
            "name with spaces.jpg",
            "image.png%00",
            "test%00.png",
            "eval('test').png",
        ]

        for bad_name in malformed_cases:
            resp = client.get(f"/uploads/{bad_name}", headers=headers)
            assert resp.status_code == 404, f"Filename '{bad_name}' should be rejected with 404"
