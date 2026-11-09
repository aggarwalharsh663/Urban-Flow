import time
import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import security_config
from main import app, UPLOAD_DIR, REPORT_DIR

client = TestClient(app)
VALID_TOKEN = security_config.get_or_create_api_token()
AUTH_HEADERS = {"X-API-Token": VALID_TOKEN}


def test_rate_limiting_triggers_429():
    """Repeated rapid requests exceeding category threshold must trigger HTTP 429."""
    # Reset limiter for this test
    security_config.GLOBAL_RATE_LIMITER._history.clear()

    max_reqs, window = security_config.RATE_LIMIT_DEFAULTS["simulate"]
    # Send max_reqs allowed requests
    for _ in range(max_reqs):
        r = client.post(
            "/api/simulate",
            headers=AUTH_HEADERS,
            json={
                "junction_name": "Rate Limit Test",
                "counts": {"North": 5, "South": 5, "East": 5, "West": 5},
            },
        )
        assert r.status_code == 200

    # The (max_reqs + 1)th request must be rejected with 429
    r_blocked = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={
            "junction_name": "Rate Limit Test",
            "counts": {"North": 5, "South": 5, "East": 5, "West": 5},
        },
    )
    assert r_blocked.status_code == 429
    assert "Too many requests" in r_blocked.text
    assert "Retry-After" in r_blocked.headers

    # Reset limiter again so subsequent tests aren't blocked
    security_config.GLOBAL_RATE_LIMITER._history.clear()


def test_inference_concurrency_bounding():
    """Inference concurrency semaphore must protect against resource exhaustion."""
    manager = security_config.GLOBAL_INFERENCE_MANAGER
    # Acquire all permits
    acquired_permits = []
    for _ in range(security_config.MAX_CONCURRENT_INFERENCES):
        acquired = manager.acquire(timeout=0.1)
        if acquired:
            acquired_permits.append(True)

    try:
        # Next acquisition attempt must fail (return False)
        assert not manager.acquire(timeout=0.1)
    finally:
        # Release acquired permits
        for _ in acquired_permits:
            manager.release()


def test_storage_cleanup_expired_files(tmp_path):
    """Ensure cleanup_storage removes expired uploads and reports."""
    test_upload_dir = tmp_path / "uploads"
    test_report_dir = tmp_path / "reports"
    test_upload_dir.mkdir()
    test_report_dir.mkdir()

    old_upload = test_upload_dir / "old_image.jpg"
    old_upload.write_bytes(b"dummy image data")
    # Set modification time to 48 hours ago
    past_time = time.time() - (48 * 3600)
    import os
    os.utime(old_upload, (past_time, past_time))

    new_upload = test_upload_dir / "new_image.jpg"
    new_upload.write_bytes(b"new image data")

    old_report = test_report_dir / "old_report.json"
    old_report.write_text('{"report_id": "old_report"}', encoding="utf-8")
    past_report_time = time.time() - (96 * 3600)
    os.utime(old_report, (past_report_time, past_report_time))

    result = security_config.cleanup_storage(test_upload_dir, test_report_dir)
    assert result["deleted_uploads"] >= 1
    assert result["deleted_reports"] >= 1
    assert not old_upload.exists()
    assert new_upload.exists()
    assert not old_report.exists()
