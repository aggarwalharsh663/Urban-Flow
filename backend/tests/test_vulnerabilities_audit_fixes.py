# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

from __future__ import annotations

import io
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

import sys
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from security_config import (
    verify_magic_bytes,
    validate_video_file,
    ProcessSharedRateLimiter,
    get_default_tracked_dirs,
    ALLOWED_VIDEO_EXTENSIONS,
)
import main


def test_avi_magic_bytes_validation():
    """Verify that RIFF AVI headers pass magic byte checks (V-02)."""
    assert ".avi" in ALLOWED_VIDEO_EXTENSIONS

    # Legitimate RIFF AVI header (12 bytes: 'RIFF', 4 size bytes, 'AVI ')
    valid_avi_header = b"RIFF\x24\x00\x00\x00AVI LIST"
    assert verify_magic_bytes(valid_avi_header, ".avi") is True
    assert verify_magic_bytes(valid_avi_header, ".AVI") is True

    # Invalid / spoofed headers
    invalid_header_1 = b"RIFF\x24\x00\x00\x00WAVEfmt " # WAV audio
    assert verify_magic_bytes(invalid_header_1, ".avi") is False

    invalid_header_2 = b"\x00\x00\x00\x18ftypmp42" # MP4 header with .avi extension
    assert verify_magic_bytes(invalid_header_2, ".avi") is False

    short_header = b"RIFF"
    assert verify_magic_bytes(short_header, ".avi") is False


def test_sqlite_rate_limiter_path_resolution(tmp_path: Path):
    """Verify ProcessSharedRateLimiter does not create double-nested data/data paths (V-09)."""
    # 1. Normal base directory
    normal_dir = tmp_path / "urban_backend"
    normal_dir.mkdir()
    with patch("security_config.resolve_data_dir", return_value=normal_dir):
        limiter = ProcessSharedRateLimiter()
        expected = normal_dir / "data" / "rate_limits.sqlite3"
        assert limiter.db_path == expected

    # 2. Redirected AppData directory (already named 'data')
    appdata_data = tmp_path / "AppData" / "Urban Flow" / "data"
    appdata_data.mkdir(parents=True)
    with patch("security_config.resolve_data_dir", return_value=appdata_data):
        limiter = ProcessSharedRateLimiter()
        expected_redirected = appdata_data / "rate_limits.sqlite3"
        assert limiter.db_path == expected_redirected
        assert "data/data" not in str(limiter.db_path).replace("\\", "/")


def test_static_upload_serving_regex_permits_avi():
    """Verify main.py static upload file pattern and media types support .avi (V-02)."""
    import re
    pattern = r"^[a-zA-Z0-9_-]+(\.(jpg|jpeg|png|mp4|avi))$"
    assert re.match(pattern, "sample_clip_01.avi") is not None
    assert re.match(pattern, "1234567890abcdef.mp4") is not None
    assert re.match(pattern, "sample.exe") is None
    assert re.match(pattern, "sample.avi.exe") is None


def test_is_application_owned(tmp_path: Path):
    """Verify is_application_owned correctly validates internal upload paths."""
    from ipc_worker import is_application_owned
    import ipc_worker

    # File inside upload dir
    upload_file = ipc_worker.UPLOAD_DIR / "test_owned_file.tmp"
    upload_file.write_text("sample")
    try:
        assert is_application_owned(upload_file) is True
    finally:
        upload_file.unlink(missing_ok=True)

    # File outside upload dir
    outside_file = tmp_path / "outside_file.txt"
    outside_file.write_text("sample")
    assert is_application_owned(outside_file) is False

    # Non-existent file
    assert is_application_owned(ipc_worker.UPLOAD_DIR / "non_existent.tmp") is False


def test_privacy_redaction_acquires_inference_lock():
    """Verify on-device privacy redaction acquires inference lock."""
    import numpy as np
    from unittest.mock import MagicMock
    import services.privacy as privacy

    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    mock_model = MagicMock()
    mock_result = MagicMock()
    mock_box = MagicMock()
    mock_box.cls = [MagicMock(item=lambda: 0)] # Person
    mock_box.xyxy = [np.array([10, 10, 50, 50])]
    mock_result.boxes = [mock_box]
    mock_model.predict.return_value = [mock_result]

    with patch("services.detection.get_inference_lock") as mock_lock_fn:
        mock_lock = MagicMock()
        mock_lock_fn.return_value = mock_lock
        redacted, summary = privacy.redact_frame_for_cloud(dummy_frame, model=mock_model)
        assert mock_lock.__enter__.called
        assert summary["persons_redacted"] == 1


def test_multi_video_metadata_preservation_on_update(tmp_path: Path):
    """Verify that multi-video metadata is preserved across cycle and count updates (CR-01)."""
    import ipc_worker
    report_id = "testmultirpt01"
    report_file = ipc_worker.REPORT_DIR / f"{report_id}.json"

    initial_report = {
        "report_id": report_id,
        "analysed_at": "2026-11-20T12:00:00Z",
        "junction_name": "Test Multi Junction",
        "source": "multi_video",
        "counts": {"North": 10, "South": 15, "East": 8, "West": 12},
        "total_vehicle_count": 45,
        "green_times": {"North": 30, "South": 40, "East": 25, "West": 35},
        "cycle": {
            "total_green_seconds": 130,
            "yellow_seconds_per_phase": 3,
            "all_red_seconds_per_phase": 1,
            "estimated_full_cycle_seconds": 146,
        },
        "directional_metrics": {
            "North": {"unique_vehicles": 10, "flow_rate_per_min": 12.0},
            "South": {"unique_vehicles": 15, "flow_rate_per_min": 18.0},
        },
        "annotated_files": {
            "North": "test-north-annotated.jpg",
            "South": "test-south-annotated.jpg",
        },
        "original_files": {
            "North": "/uploads/test-north.mp4",
            "South": "/uploads/test-south.mp4",
        },
    }

    try:
        import json
        report_file.write_text(json.dumps(initial_report), encoding="utf-8")

        # 1. Test update_cycle preserves multi-camera metadata
        cycle_res = ipc_worker.handle_update_cycle({"report_id": report_id, "green_budget": 140})
        assert "directional_metrics" in cycle_res
        assert cycle_res["directional_metrics"]["North"]["unique_vehicles"] == 10
        assert "annotated_files" in cycle_res
        assert cycle_res["annotated_files"]["North"] == "test-north-annotated.jpg"
        assert "original_files" in cycle_res
        assert cycle_res["original_files"]["South"] == "/uploads/test-south.mp4"

        # 2. Test update_counts preserves multi-camera metadata
        new_counts = {"North": 12, "South": 15, "East": 8, "West": 12}
        counts_res = ipc_worker.handle_update_counts({"report_id": report_id, "counts": new_counts})
        assert "directional_metrics" in counts_res
        assert "annotated_files" in counts_res
        assert "original_files" in counts_res
        assert counts_res["annotated_files"]["South"] == "test-south-annotated.jpg"
    finally:
        report_file.unlink(missing_ok=True)


