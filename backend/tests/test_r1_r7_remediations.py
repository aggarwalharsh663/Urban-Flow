"""
Comprehensive Verification Tests for Residual Security Findings R1 through R7.

Covers:
- R1: Scoped authorization model, permission enforcement, token derivation, timing safety.
- R2: Secure token storage and transmission, removal of localStorage/window token,
     removal of query parameter auth, media ticket generation and verification.
- R3: Hardening unauthenticated endpoints (/api/health, /api/directions, /uploads/{file}).
- R4: 500 MB storage cap, storage accounting, reservation tracking, eviction cleanup.
- R5: On-device privacy redaction before cloud AI, fail-closed handling, Host header validation.
- R6: IPC cancellation tracking and streaming upload integrity.
- R7: Production script locking, prevention of dev reload mode in production.
"""
from __future__ import annotations

import io
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import security_config
from main import app, REPORT_DIR
from services.privacy import PrivacyRedactionError, redact_frame_for_cloud

client = TestClient(app)
MASTER_TOKEN = security_config.get_or_create_api_token()
MASTER_HEADERS = {"X-API-Token": MASTER_TOKEN}


@pytest.fixture
def sample_report_id():
    """Create a sample report using master token for scoped endpoint testing."""
    resp = client.post(
        "/api/simulate",
        headers=MASTER_HEADERS,
        json={
            "junction_name": "R1 Scoped Test Junction",
            "counts": {"North": 5, "South": 5, "East": 5, "West": 5},
            "green_budget": 120,
        },
    )
    assert resp.status_code == 200
    return resp.json()["report_id"]


# ==============================================================================
# R1: Scoped Authorization Model
# ==============================================================================
class TestR1ScopedAuthorization:
    def test_missing_token_returns_401(self, sample_report_id):
        """Unauthenticated requests without any token return HTTP 401."""
        response = client.get(f"/api/reports/{sample_report_id}")
        assert response.status_code == 401
        assert "Unauthorized" in response.text or "Invalid or missing" in response.text

    def test_invalid_token_returns_401(self, sample_report_id):
        """Requests with an invalid token return HTTP 401."""
        response = client.get(
            f"/api/reports/{sample_report_id}",
            headers={"X-API-Token": "invalid_fake_token_12345"},
        )
        assert response.status_code == 401

    def test_scoped_token_generation_and_detection(self):
        """Scoped tokens are cryptographically derived and correctly mapped to permissions."""
        read_token = security_config.generate_scoped_token(security_config.SCOPE_READ)
        report_write_token = security_config.generate_scoped_token(security_config.SCOPE_REPORTS_WRITE)
        inference_token = security_config.generate_scoped_token(security_config.SCOPE_INFERENCE_WRITE)
        admin_token = security_config.generate_scoped_token(security_config.SCOPE_ADMIN)

        assert security_config.get_token_scopes(read_token) == {security_config.SCOPE_READ}
        assert security_config.SCOPE_REPORTS_WRITE in security_config.get_token_scopes(report_write_token)
        assert security_config.SCOPE_READ in security_config.get_token_scopes(report_write_token)
        assert security_config.SCOPE_INFERENCE_WRITE in security_config.get_token_scopes(inference_token)
        assert security_config.SCOPE_ADMIN in security_config.get_token_scopes(admin_token)

        # Master token has ALL_SCOPES
        assert security_config.get_token_scopes(MASTER_TOKEN) == security_config.ALL_SCOPES

    def test_read_only_token_rejected_on_write_endpoints_returns_403(self, sample_report_id):
        """A read-only token can read reports but is forbidden (403) from simulating or creating them."""
        read_token = security_config.generate_scoped_token(security_config.SCOPE_READ)
        read_headers = {"X-API-Token": read_token}

        # Read succeeds with read token
        get_resp = client.get(f"/api/reports/{sample_report_id}", headers=read_headers)
        assert get_resp.status_code == 200

        # State-modifying /api/simulate is forbidden (403) because it requires reports:write
        post_resp = client.post(
            "/api/simulate",
            headers=read_headers,
            json={
                "junction_name": "Test Read Only Rejection",
                "counts": {"North": 2, "South": 2, "East": 2, "West": 2},
                "green_budget": 90,
            },
        )
        assert post_resp.status_code == 403
        assert "lacks required scope" in post_resp.text

    def test_reports_write_token_succeeds_on_write(self):
        """A token with reports:write scope can successfully simulate and save reports."""
        write_token = security_config.generate_scoped_token(security_config.SCOPE_REPORTS_WRITE)
        write_headers = {"X-API-Token": write_token}

        post_resp = client.post(
            "/api/simulate",
            headers=write_headers,
            json={
                "junction_name": "Test Scoped Write Junction",
                "counts": {"North": 3, "South": 3, "East": 3, "West": 3},
                "green_budget": 90,
            },
        )
        assert post_resp.status_code == 200
        assert "report_id" in post_resp.json()

    def test_master_token_has_all_permissions(self, sample_report_id):
        """The master per-install token holds all scopes and can execute both read and write operations."""
        # Read
        get_resp = client.get(f"/api/reports/{sample_report_id}", headers=MASTER_HEADERS)
        assert get_resp.status_code == 200

        # Write
        post_resp = client.post(
            "/api/simulate",
            headers=MASTER_HEADERS,
            json={
                "junction_name": "Test Master Permissions",
                "counts": {"North": 4, "South": 4, "East": 4, "West": 4},
                "green_budget": 90,
            },
        )
        assert post_resp.status_code == 200


# ==============================================================================
# R2: Secure Token Storage and Transmission
# ==============================================================================
class TestR2TokenStorageAndTransmission:
    def test_api_token_query_parameter_rejected(self):
        """Query parameter authentication is removed from API endpoints to prevent URL leakage."""
        response = client.get(f"/api/directions?api_token={MASTER_TOKEN}")
        assert response.status_code == 401

    def test_media_ticket_generation_and_validation(self):
        """Media tickets are short-lived, HMAC-tied to filename, and time-bounded."""
        test_file = "test_r2_image.jpg"
        ticket = security_config.generate_media_ticket(test_file, expires_in_seconds=60)
        assert security_config.verify_media_ticket(test_file, ticket) is True

        # Cannot use ticket for another file (prevents ticket reuse across resources)
        assert security_config.verify_media_ticket("other_image.jpg", ticket) is False

        # Expired ticket is rejected
        expired_ticket = security_config.generate_media_ticket(test_file, expires_in_seconds=-10)
        assert security_config.verify_media_ticket(test_file, expired_ticket) is False

        # Forged ticket is rejected
        forged_ticket = f"{int(time.time()) + 60}_0123456789abcdef0123456789abcdef"
        assert security_config.verify_media_ticket(test_file, forged_ticket) is False

    def test_frontend_does_not_contain_localstorage_token_or_global_token(self):
        """Frontend React code must not store tokens in localStorage or expose window globals."""
        app_jsx_path = BASE_DIR.parent / "frontend" / "src" / "components" / "urbanflow" / "App.jsx"
        content = app_jsx_path.read_text(encoding="utf-8")

        assert 'localStorage.getItem("urban_flow_api_token")' not in content
        assert "window.__URBAN_FLOW_API_TOKEN__" not in content

    def test_electron_ipc_does_not_expose_get_api_token(self):
        """Electron preload and main must not expose unrestricted get-api-token IPC."""
        preload_path = BASE_DIR.parent / "frontend" / "electron" / "preload.cjs"
        preload_content = preload_path.read_text(encoding="utf-8")
        assert "get-api-token" not in preload_content

        main_path = BASE_DIR.parent / "frontend" / "electron" / "main.cjs"
        main_content = main_path.read_text(encoding="utf-8")
        assert "ipcMain.handle('get-api-token'" not in main_content

    def test_start_bat_does_not_expose_token_on_cmdline(self):
        """start.bat must not pass master tokens through visible command-line arguments."""
        start_bat = BASE_DIR.parent / "start.bat"
        content = start_bat.read_text(encoding="utf-8", errors="ignore")
        assert "cmd /k set URBAN_FLOW_API_TOKEN=" not in content
        assert "VITE_API_TOKEN" not in content


# ==============================================================================
# R3: Hardened Unauthenticated Endpoints
# ==============================================================================
class TestR3HardenedEndpoints:
    def test_unauthenticated_health_returns_minimal_info(self):
        """Unauthenticated health probes receive only minimal, non-sensitive status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("app") == "urban_flow"
        assert data.get("storage") == "local"
        # Must not disclose internal diagnostics, detailed byte counts, or dependencies
        assert "computer_vision_ready" not in data
        assert "model_name" not in data
        assert not isinstance(data.get("storage"), dict)

    def test_authenticated_health_returns_full_diagnostics(self):
        """Authenticated health probes receive full diagnostic and storage metrics."""
        response = client.get("/api/health", headers=MASTER_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert "computer_vision_ready" in data
        assert "model_available" in data
        assert isinstance(data.get("storage"), dict)
        assert "total_used_bytes" in data["storage"]
        assert "max_allowed_bytes" in data["storage"]

    def test_unauthenticated_directions_returns_401(self):
        """Unauthenticated directions queries return HTTP 401."""
        response = client.get("/api/directions")
        assert response.status_code == 401

    def test_authenticated_directions_succeeds(self):
        """Authenticated directions queries return directional options with security headers."""
        response = client.get("/api/directions", headers=MASTER_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert "directions" in data
        assert set(data["directions"]) == {"North", "South", "East", "West"}
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_uploads_endpoint_requires_auth_or_ticket(self):
        """Direct file access under /uploads requires authentication or a valid media ticket."""
        uploads_dir = BASE_DIR / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = uploads_dir / "r3_test_asset.png"
        img = Image.new("RGB", (64, 64), color="blue")
        img.save(dummy_file, format="PNG")

        try:
            # Unauthenticated without ticket -> 401
            resp_unauth = client.get(f"/uploads/{dummy_file.name}")
            assert resp_unauth.status_code == 401

            # Authenticated via Header -> 200
            resp_auth = client.get(f"/uploads/{dummy_file.name}", headers=MASTER_HEADERS)
            assert resp_auth.status_code == 200
            assert resp_auth.headers.get("x-content-type-options") == "nosniff"

            # Authenticated via Media Ticket -> 200
            ticket = security_config.generate_media_ticket(dummy_file.name)
            resp_ticket = client.get(f"/uploads/{dummy_file.name}?ticket={ticket}")
            assert resp_ticket.status_code == 200
        finally:
            if dummy_file.exists():
                dummy_file.unlink()


# ==============================================================================
# R4: 500 MB Storage Cap and Accounting
# ==============================================================================
class TestR4StorageCapAndAccounting:
    def test_storage_constants_and_status(self):
        """The storage cap is strictly set to 500 MB and accounting tracks usage."""
        assert security_config.MAX_STORAGE_BYTES == 500 * 1024 * 1024
        status = security_config.GLOBAL_STORAGE_MANAGER.get_status()
        assert "total_used_bytes" in status
        assert "available_bytes" in status
        assert "max_allowed_bytes" in status
        assert status["max_allowed_bytes"] == 500 * 1024 * 1024

    def test_reservation_rejection_over_capacity(self):
        """Storage manager strictly rejects reservation requests exceeding the configured budget."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_up = Path(tmpdir) / "up"
            test_up.mkdir()
            test_rep = Path(tmpdir) / "rep"
            test_rep.mkdir()

            base_usage = security_config.calculate_storage_usage([test_up, test_rep, BASE_DIR / "data"])
            mgr = security_config.StorageManager(upload_dir=test_up, report_dir=test_rep, max_bytes=base_usage + 1000)
            # Reserving within budget succeeds
            allowed, resid = mgr.reserve(500)
            assert allowed is True
            assert resid is not None

            # Reserving beyond remaining budget fails
            allowed2, resid2 = mgr.reserve(600)
            assert allowed2 is False
            assert resid2 is None

            # Releasing reservation restores capacity
            mgr.release(resid)
            allowed3, resid3 = mgr.reserve(600)
            assert allowed3 is True
            mgr.release(resid3)

    def test_storage_cleanup_evicts_oldest_files(self):
        """Storage cleanup evicts oldest files when threshold is approached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_upload_dir = Path(tmpdir) / "uploads"
            test_upload_dir.mkdir()
            test_report_dir = Path(tmpdir) / "reports"
            test_report_dir.mkdir()

            # Create an expired older file and a fresh newer file
            f_old = test_upload_dir / "old_file.jpg"
            f_old.write_bytes(b"A" * 1200)
            expired_time = time.time() - ((security_config.UPLOAD_RETENTION_HOURS + 2) * 3600)
            os.utime(f_old, (expired_time, expired_time))

            f_new = test_upload_dir / "new_file.jpg"
            f_new.write_bytes(b"B" * 500)

            # Cleanup expired files
            security_config.cleanup_storage(test_upload_dir, test_report_dir)
            # Old expired file should have been evicted to make room
            assert not f_old.exists()
            assert f_new.exists()


# ==============================================================================
# R5: Privacy Redaction & Host Header Validation
# ==============================================================================
class TestR5PrivacyAndHostValidation:
    def test_privacy_redaction_synthetic_frame(self):
        """Verify on-device redaction handles frames and fails closed when input is invalid."""
        with pytest.raises(PrivacyRedactionError):
            redact_frame_for_cloud(None)

        with pytest.raises(PrivacyRedactionError):
            redact_frame_for_cloud(np.array([], dtype=np.uint8))

    def test_host_header_validation_blocks_unauthorized_hosts(self):
        """Requests with unauthorized Host headers are rejected with HTTP 400."""
        # Legitimate loopback host succeeds
        valid_resp = client.get("/api/health", headers={"Host": "127.0.0.1:8000"})
        assert valid_resp.status_code == 200

        # Spoofed external Host header fails with 400 Bad Request
        malicious_resp = client.get("/api/health", headers={"Host": "attacker.malicious-domain.com"})
        assert malicious_resp.status_code == 400
        assert "Invalid Host header" in malicious_resp.text

    def test_security_documentation_accuracy(self):
        """SECURITY.md must exist and accurately document implemented controls."""
        sec_md = BASE_DIR.parent / "SECURITY.md"
        assert sec_md.is_file()
        content = sec_md.read_text(encoding="utf-8").lower()
        assert "500 mb" in content
        assert "scoped authorization" in content or "scoped permission" in content
        assert "media tickets" in content
        assert "privacy" in content
        assert "host" in content


# ==============================================================================
# R6: Streaming Uploads and Worker Cancellation
# ==============================================================================
class TestR6StreamingAndCancellation:
    def test_ipc_worker_cancellation_tracking(self):
        """IPC worker registers and honors task cancellations cooperatively."""
        from ipc_worker import CANCELLED_REQUESTS, handle_cancel

        req_id = "test_cancel_req_001"
        assert req_id not in CANCELLED_REQUESTS

        res = handle_cancel({"cancel_id": req_id})
        assert res.get("cancelled") == req_id
        assert req_id in CANCELLED_REQUESTS

        # Clean up
        CANCELLED_REQUESTS.discard(req_id)

    def test_streaming_magic_byte_check(self):
        """Validates that magic byte signature check accurately detects fake image uploads."""
        header_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        header_jpg = b"\xFF\xD8\xFF" + b"\x00" * 20
        header_fake = b"<html><head><script>alert(1)</script></head></html>"

        assert security_config.verify_magic_bytes(header_png, ".png") is True
        assert security_config.verify_magic_bytes(header_jpg, ".jpg") is True
        assert security_config.verify_magic_bytes(header_fake, ".png") is False
        assert security_config.verify_magic_bytes(header_fake, ".jpg") is False


# ==============================================================================
# R7: Prevent Dev Mode in Production
# ==============================================================================
class TestR7PreventDevModeInProduction:
    def test_production_script_has_no_dev_switch_or_reload(self):
        """Production startup script backend/run-backend.ps1 must not pass dev flags."""
        ps1_path = BASE_DIR / "run-backend.ps1"
        content = ps1_path.read_text(encoding="utf-8")
        assert "param(" not in content or "-Dev" not in content
        assert '"--reload"' not in content and "'--reload'" not in content

    def test_dev_script_is_isolated(self):
        """Development script backend/run-backend-dev.ps1 exists explicitly for developers."""
        dev_ps1_path = BASE_DIR / "run-backend-dev.ps1"
        assert dev_ps1_path.is_file()
        content = dev_ps1_path.read_text(encoding="utf-8")
        assert "Development Mode" in content or "DEVELOPMENT MODE" in content
