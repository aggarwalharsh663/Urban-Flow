# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

import sys
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import ipc_worker
import security_config


def _calculate_file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _create_synthetic_mp4(path: Path, width: int = 320, height: int = 240, fps: float = 10.0, num_frames: int = 25) -> Path:
    """Create a minimal valid synthetic MP4 file with moving rectangular pattern (2.5s duration >= 2.0s min)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    for f in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Draw moving rectangle
        x = 20 + f * 5
        cv2.rectangle(frame, (x, 50), (x + 40, 100), (0, 255, 0), -1)
        writer.write(frame)
    writer.release()
    return path


# 1. Original file survives successful inference
def test_original_file_survives_successful_inference(tmp_path: Path):
    external_dir = tmp_path / "user_videos"
    original_file = _create_synthetic_mp4(external_dir / "user_traffic_camera.mp4")
    original_hash = _calculate_file_hash(original_file)
    original_size = original_file.stat().st_size

    # Execute analysis via IPC worker
    res = ipc_worker.handle_analyse({"file_path": str(original_file)}, video=True)

    assert "report_id" in res
    assert res["source"] == "video"

    # Verify original user file is 100% intact, not moved, not modified, not deleted
    assert original_file.exists(), "Original file must exist at original path after successful analysis"
    assert original_file.stat().st_size == original_size
    assert _calculate_file_hash(original_file) == original_hash

    # Verify an application-controlled copy exists in UPLOAD_DIR
    created_upload = ipc_worker.UPLOAD_DIR / Path(res["original_url"]).name
    assert created_upload.exists()
    assert created_upload.resolve() != original_file.resolve()


# 2. Original file survives failed inference
def test_original_file_survives_failed_inference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    external_dir = tmp_path / "user_videos"
    original_file = _create_synthetic_mp4(external_dir / "fail_test.mp4")
    original_hash = _calculate_file_hash(original_file)
    original_size = original_file.stat().st_size

    # Force inference to fail
    def mock_fail(*args, **kwargs):
        raise RuntimeError("Simulated YOLO inference crash")

    monkeypatch.setattr(ipc_worker, "analyse_video", mock_fail)

    with pytest.raises(RuntimeError, match="Simulated YOLO inference crash"):
        ipc_worker.handle_analyse({"file_path": str(original_file)}, video=True)

    # Verify original user file was not deleted or altered
    assert original_file.exists(), "Original file must survive failed inference"
    assert original_file.stat().st_size == original_size
    assert _calculate_file_hash(original_file) == original_hash


# 3. Original file survives cancelled inference
def test_original_file_survives_cancelled_inference(tmp_path: Path):
    external_dir = tmp_path / "user_videos"
    original_file = _create_synthetic_mp4(external_dir / "cancel_test.mp4")
    original_hash = _calculate_file_hash(original_file)
    original_size = original_file.stat().st_size

    req_id = "req_cancel_test_001"
    ipc_worker.cancel_request(req_id)

    with pytest.raises(RuntimeError, match="cancelled"):
        ipc_worker.handle_analyse({"file_path": str(original_file)}, video=True, req_id=req_id)

    # Verify original file survives cancellation
    assert original_file.exists(), "Original file must survive request cancellation"
    assert original_file.stat().st_size == original_size
    assert _calculate_file_hash(original_file) == original_hash


# 4. Original file survives invalid-video handling
def test_original_file_survives_invalid_video_handling(tmp_path: Path):
    external_dir = tmp_path / "user_videos"
    external_dir.mkdir(parents=True, exist_ok=True)
    invalid_file = external_dir / "corrupted.mp4"
    invalid_file.write_bytes(b"NOT_A_VALID_MP4_HEADER_PAYLOAD_DATA")
    original_hash = _calculate_file_hash(invalid_file)

    with pytest.raises(ValueError, match="Magic bytes verification failed"):
        ipc_worker.handle_analyse({"file_path": str(invalid_file)}, video=True)

    # Verify the corrupted file was not deleted by the validation handler
    assert invalid_file.exists(), "Original invalid file must not be deleted on validation failure"
    assert _calculate_file_hash(invalid_file) == original_hash


# 5. Original file survives failed copying
def test_original_file_survives_failed_copying(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    external_dir = tmp_path / "user_videos"
    original_file = _create_synthetic_mp4(external_dir / "copy_fail.mp4")
    original_hash = _calculate_file_hash(original_file)

    # Mock disk space check to simulate insufficient storage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(1000, 500, 100))

    with pytest.raises(OSError, match="Insufficient disk space"):
        ipc_worker.handle_analyse({"file_path": str(original_file)}, video=True)

    # Original file must survive
    assert original_file.exists(), "Original file must survive failed copy"
    assert _calculate_file_hash(original_file) == original_hash


# 6. Partial destination files are cleaned up
def test_partial_destination_files_are_cleaned_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    external_dir = tmp_path / "user_videos"
    original_file = _create_synthetic_mp4(external_dir / "partial_test.mp4")

    # Simulate an error during data streaming in safe_copy_to_upload_dir
    def mock_fsync(fd):
        raise IOError("Simulated disk error during fsync")

    monkeypatch.setattr(os, "fsync", mock_fsync)

    with pytest.raises(IOError, match="Simulated disk error during fsync"):
        ipc_worker.safe_copy_to_upload_dir(original_file)

    # Staging files must be completely cleaned up
    leftover_staging = list(ipc_worker.UPLOAD_DIR.glob("staging_*.tmp"))
    assert len(leftover_staging) == 0, f"Found orphaned staging files: {leftover_staging}"
    assert original_file.exists()


# 7. Application-owned temporary files are cleaned up on failure
def test_application_owned_temporary_files_are_cleaned_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    external_dir = tmp_path / "user_videos"
    original_file = _create_synthetic_mp4(external_dir / "temp_cleanup.mp4")

    # Count upload files before test
    uploads_before = set(p.name for p in ipc_worker.UPLOAD_DIR.glob("*"))

    def mock_fail(*args, **kwargs):
        raise RuntimeError("Simulated failure after copy")

    monkeypatch.setattr(ipc_worker, "analyse_video", mock_fail)

    with pytest.raises(RuntimeError, match="Simulated failure after copy"):
        ipc_worker.handle_analyse({"file_path": str(original_file)}, video=True)

    uploads_after = set(p.name for p in ipc_worker.UPLOAD_DIR.glob("*"))
    # New upload files should be cleaned up on failure
    new_files = uploads_after - uploads_before
    assert len(new_files) == 0, f"Leaked temporary working files in UPLOAD_DIR: {new_files}"


# 8. External files are never deleted by cleanup
def test_external_files_are_never_deleted_by_cleanup(tmp_path: Path):
    external_archive = tmp_path / "user_external_archive"
    external_archive.mkdir(parents=True, exist_ok=True)
    external_video = _create_synthetic_mp4(external_archive / "archived_junction.mp4")

    # Set external file mtime to 1 year ago (simulating old file)
    old_time = time.time() - (365 * 24 * 3600)
    os.utime(external_video, (old_time, old_time))

    # Run application cleanup routine
    cleanup_res = security_config.cleanup_storage(ipc_worker.UPLOAD_DIR, ipc_worker.REPORT_DIR)

    # Assert external file was completely ignored by cleanup
    assert external_video.exists(), "External files outside UPLOAD_DIR must NEVER be deleted by cleanup"


# 9. Path traversal is rejected
def test_path_traversal_is_rejected(tmp_path: Path):
    # Null byte attack
    with pytest.raises(ValueError, match="null characters detected"):
        ipc_worker.validate_source_path("video.mp4\0.jpg")

    # Windows reserved device name
    with pytest.raises(ValueError, match="reserved device name"):
        ipc_worker.validate_source_path("CON.mp4")

    # Non-existent traversal path
    with pytest.raises(FileNotFoundError):
        ipc_worker.validate_source_path("../../../../nonexistent_sensitive_file.mp4")

    # Directory instead of file
    with pytest.raises(ValueError, match="not a regular file"):
        ipc_worker.validate_source_path(str(tmp_path))


# 10. Symlink edge cases handled safely
def test_symlink_edge_cases_handled_safely(tmp_path: Path):
    external_dir = tmp_path / "symlink_test"
    external_dir.mkdir(parents=True, exist_ok=True)
    real_target = _create_synthetic_mp4(external_dir / "real_target.mp4")
    target_hash = _calculate_file_hash(real_target)
    symlink_file = external_dir / "camera_symlink.mp4"

    try:
        os.symlink(real_target, symlink_file)
        has_symlinks = True
    except (OSError, NotImplementedError):
        has_symlinks = False

    if has_symlinks:
        # Analyse via symlink
        res = ipc_worker.handle_analyse({"file_path": str(symlink_file)}, video=True)
        assert "report_id" in res

        # Target and symlink must both remain intact
        assert real_target.exists(), "Symlink target must not be moved or deleted"
        assert symlink_file.exists(), "Symlink must not be removed"
        assert _calculate_file_hash(real_target) == target_hash

    # Test broken symlink
    broken_link = external_dir / "broken.mp4"
    try:
        os.symlink(external_dir / "does_not_exist.mp4", broken_link)
        with pytest.raises(FileNotFoundError):
            ipc_worker.validate_source_path(str(broken_link))
        assert broken_link.exists() or broken_link.is_symlink()
    except (OSError, NotImplementedError):
        pass


# 11. Repeated analysis does not damage the original file
def test_repeated_analysis_does_not_damage_original_file(tmp_path: Path):
    external_dir = tmp_path / "user_videos"
    original_file = _create_synthetic_mp4(external_dir / "repeated_traffic.mp4")
    original_hash = _calculate_file_hash(original_file)
    original_size = original_file.stat().st_size

    # Run analysis 3 times consecutively on the same original video
    report_ids = []
    for i in range(3):
        res = ipc_worker.handle_analyse({"file_path": str(original_file)}, video=True)
        assert res["report_id"]
        report_ids.append(res["report_id"])

        # Check original file after every single run
        assert original_file.exists()
        assert original_file.stat().st_size == original_size
        assert _calculate_file_hash(original_file) == original_hash

    assert len(set(report_ids)) == 3, "Each run should generate an independent report"


# 12. Multi-video directional analysis preserves all original files on success and failure
def test_multi_video_directional_files_preserved_on_success_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    external_dir = tmp_path / "multi_cam"
    north = _create_synthetic_mp4(external_dir / "north.mp4")
    south = _create_synthetic_mp4(external_dir / "south.mp4")

    n_hash = _calculate_file_hash(north)
    s_hash = _calculate_file_hash(south)

    # 12a. Successful multi-video analysis
    res = ipc_worker.handle_analyse_multi_video({
        "videos": {"North": str(north), "South": str(south)}
    })
    assert res["report_id"]
    assert res["source"] == "multi_video"

    assert north.exists() and _calculate_file_hash(north) == n_hash
    assert south.exists() and _calculate_file_hash(south) == s_hash

    # 12b. Failed multi-video analysis
    def mock_fail(*args, **kwargs):
        raise RuntimeError("Simulated multi-tracker crash")

    monkeypatch.setattr(ipc_worker, "analyse_multi_directional_videos", mock_fail)

    with pytest.raises(RuntimeError, match="Simulated multi-tracker crash"):
        ipc_worker.handle_analyse_multi_video({
            "videos": {"North": str(north), "South": str(south)}
        })

    # Assert both original video files still exist and are untouched
    assert north.exists() and _calculate_file_hash(north) == n_hash
    assert south.exists() and _calculate_file_hash(south) == s_hash
