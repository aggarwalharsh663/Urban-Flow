# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

"""
Tests for Storage Accounting Discrepancy Resolution in security_config.py.
Verifies:
1. Normal installation directory (writable BASE_DIR).
2. Program Files installation simulation (read-only BASE_DIR redirected to %LOCALAPPDATA%\\Urban Flow\\data).
3. Missing data directory (graceful zero accounting).
4. Empty data directory (zero bytes counted, .gitkeep ignored).
5. Existing SQLite database (WAL/SHM files properly accounted for).
6. Storage quota exceeded (properly accounts for DB and cache in threshold math).
7. Cleanup and eviction (evicts uploads based on total storage including DB and cache).
8. Directory permission errors (unreadable directories handled gracefully).
9. Deduplication (same directory or file referenced multiple times is never double-counted).
"""

import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import security_config


class TestStorageAccountingResolution:
    """Test suite for storage accounting and dynamic data directory resolution."""

    def test_normal_installation_directory(self, tmp_path: Path, monkeypatch):
        """Under normal writable directory, data directory is BASE_DIR / data or custom dir."""
        normal_dir = tmp_path / "normal_install"
        normal_dir.mkdir()
        monkeypatch.setenv("URBAN_FLOW_DATA_DIR", str(normal_dir))

        resolved = security_config.resolve_data_dir()
        assert resolved == normal_dir

        tracked = security_config.get_default_tracked_dirs()
        assert normal_dir / "uploads" in tracked
        assert normal_dir / "reports" in tracked
        assert normal_dir / "data" in tracked

    def test_program_files_redirection_to_localappdata(self, tmp_path: Path, monkeypatch):
        """
        When installed in C:\\Program Files (simulated by write_test PermissionError),
        data is redirected to %LOCALAPPDATA%\\Urban Flow\\data, and storage accounting
        measures the redirected data directory rather than Program Files.
        """
        fake_appdata = tmp_path / "LocalAppData"
        monkeypatch.setenv("LOCALAPPDATA", str(fake_appdata))
        monkeypatch.delenv("URBAN_FLOW_DATA_DIR", raising=False)

        # Simulate read-only Program Files BASE_DIR
        def mock_touch(self, *args, **kwargs):
            raise PermissionError("Access denied: C:\\Program Files\\Urban Flow is read-only")

        with patch.object(Path, "touch", mock_touch):
            redirected = security_config.get_writable_data_dir()
            expected = fake_appdata / "Urban Flow" / "data"
            assert redirected == expected
            assert redirected.is_dir()

            # Verify resolve_data_dir reflects the redirected directory
            monkeypatch.setattr(security_config, "DATA_DIR", redirected)
            tracked = security_config.get_default_tracked_dirs()
            assert any(str(expected) in str(p) for p in tracked)
            # Ensure read-only Program Files is NOT hardcoded in accounting
            assert not any("Program Files" in str(p) for p in tracked)

    def test_missing_data_directory_handling(self, tmp_path: Path):
        """Missing directories should safely report 0 bytes without throwing exceptions."""
        non_existent_up = tmp_path / "does_not_exist_uploads"
        non_existent_rep = tmp_path / "does_not_exist_reports"
        non_existent_data = tmp_path / "does_not_exist_data"

        usage = security_config.calculate_storage_usage([
            non_existent_up,
            non_existent_rep,
            non_existent_data,
        ])
        assert usage == 0

    def test_empty_data_directory_and_gitkeep(self, tmp_path: Path):
        """Empty directories and .gitkeep sentinel files are not counted towards storage quota."""
        up = tmp_path / "uploads"
        rep = tmp_path / "reports"
        data = tmp_path / "data"
        up.mkdir()
        rep.mkdir()
        data.mkdir()

        (up / ".gitkeep").write_text("", encoding="utf-8")
        (rep / ".gitkeep").write_text("", encoding="utf-8")
        (data / ".gitkeep").write_text("", encoding="utf-8")

        usage = security_config.calculate_storage_usage([up, rep, data])
        assert usage == 0

    def test_existing_sqlite_database_and_wal_accounting(self, tmp_path: Path, monkeypatch):
        """SQLite database, WAL, and SHM files in data directory are properly accounted for."""
        base_dir = tmp_path / "app_data"
        base_dir.mkdir()
        monkeypatch.setenv("URBAN_FLOW_DATA_DIR", str(base_dir))
        monkeypatch.setattr(security_config, "DATA_DIR", base_dir)

        data_dir = base_dir / "data"
        data_dir.mkdir()
        db_file = data_dir / "rate_limits.sqlite3"

        # Populate SQLite database in WAL mode and keep open to retain sidecars
        conn = sqlite3.connect(str(db_file))
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("CREATE TABLE test_tab (id INTEGER PRIMARY KEY, content BLOB);")
            conn.execute("INSERT INTO test_tab (content) VALUES (?);", (b"X" * 50_000,))
            conn.commit()

            wal_file = data_dir / "rate_limits.sqlite3-wal"
            shm_file = data_dir / "rate_limits.sqlite3-shm"

            total_db_files_size = sum(f.stat().st_size for f in [db_file, wal_file, shm_file] if f.exists())
            assert total_db_files_size > 0

            # Calculate storage usage while connection is active so WAL/SHM contribute
            usage = security_config.calculate_storage_usage()
            assert usage >= total_db_files_size

            # Also verify cache file placed directly in base_dir is counted
            cache_file = base_dir / "test_cache.bin"
            cache_file.write_bytes(b"C" * 25_000)

            usage_with_cache = security_config.calculate_storage_usage()
            assert usage_with_cache >= usage + 25_000
        finally:
            conn.close()

    def test_deduplication_prevents_double_counting(self, tmp_path: Path):
        """Passing identical or overlapping directories must not double-count files."""
        up = tmp_path / "uploads"
        up.mkdir()
        f1 = up / "file1.dat"
        f1.write_bytes(b"D" * 10_000)

        # Pass up directory three times
        usage_duplicated = security_config.calculate_storage_usage([up, up, up])
        assert usage_duplicated == 10_000

    def test_storage_quota_exceeded_accounts_for_database(self, tmp_path: Path, monkeypatch):
        """
        When database and cache consume quota, StorageManager.reserve correctly
        detects quota saturation and refuses reservations if quota cannot accommodate them.
        """
        app_dir = tmp_path / "quota_app"
        app_dir.mkdir()
        up = app_dir / "uploads"
        rep = app_dir / "reports"
        data = app_dir / "data"
        up.mkdir()
        rep.mkdir()
        data.mkdir()

        monkeypatch.setenv("URBAN_FLOW_DATA_DIR", str(app_dir))
        monkeypatch.setattr(security_config, "DATA_DIR", app_dir)

        # 300 KB SQLite database in data dir
        db_file = data / "rate_limits.sqlite3"
        db_file.write_bytes(b"D" * 300_000)

        # StorageManager with 500 KB max cap
        mgr = security_config.StorageManager(upload_dir=up, report_dir=rep, data_dir=data, max_bytes=500_000)

        # 150 KB reservation succeeds (300 KB + 150 KB = 450 KB <= 500 KB)
        ok1, res1 = mgr.reserve(150_000)
        assert ok1 is True
        assert res1 is not None

        # Additional 100 KB reservation fails because 300 KB (db) + 150 KB (res) + 100 KB = 550 KB > 500 KB
        ok2, res2 = mgr.reserve(100_000)
        assert ok2 is False
        assert res2 is None

    def test_cleanup_and_eviction_with_redirected_data(self, tmp_path: Path, monkeypatch):
        """
        Storage cleanup must accurately account for SQLite database and evict oldest uploads
        to satisfy target_free_bytes.
        """
        app_dir = tmp_path / "evict_app"
        app_dir.mkdir()
        up = app_dir / "uploads"
        rep = app_dir / "reports"
        data = app_dir / "data"
        up.mkdir()
        rep.mkdir()
        data.mkdir()

        monkeypatch.setenv("URBAN_FLOW_DATA_DIR", str(app_dir))
        monkeypatch.setattr(security_config, "DATA_DIR", app_dir)

        # 200 KB database
        db_file = data / "rate_limits.sqlite3"
        db_file.write_bytes(b"D" * 200_000)

        # Two 100 KB uploads (one older, one newer)
        f_old = up / "old_upload.jpg"
        f_old.write_bytes(b"O" * 100_000)
        old_time = time.time() - 3600
        os.utime(f_old, (old_time, old_time))

        f_new = up / "new_upload.jpg"
        f_new.write_bytes(b"N" * 100_000)

        # Current total is 400 KB (200 KB db + 200 KB uploads)
        # Cap is 450 KB. We request reservation of 100 KB.
        # Target free bytes requires evicting old_upload.
        res = security_config.cleanup_storage(
            upload_dir=up,
            report_dir=rep,
            target_free_bytes=100_000,
            max_bytes=450_000,
            data_dir=data,
        )

        assert res["deleted_uploads"] >= 1
        assert not f_old.exists()
        assert f_new.exists()
        # Database in data directory is never deleted by eviction
        assert db_file.exists()

        # Final accounted usage reflects remaining new upload (100 KB) + db (200 KB) = 300 KB
        assert res["current_usage_bytes"] == 300_000

    def test_directory_permission_errors_handled_gracefully(self, tmp_path: Path):
        """If a directory cannot be read due to permissions or OS errors, calculation continues."""
        up = tmp_path / "uploads"
        up.mkdir()
        f = up / "valid.jpg"
        f.write_bytes(b"V" * 5000)

        restricted = tmp_path / "restricted"
        restricted.mkdir()

        def mock_glob(self, pattern):
            if "restricted" in str(self):
                raise PermissionError("Access is denied")
            return [f]

        with patch.object(Path, "glob", mock_glob):
            usage = security_config.calculate_storage_usage([up, restricted])
            assert usage == 5000
