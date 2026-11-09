import os
import sys
import tempfile
from pathlib import Path
import pytest

from security_config import (
    KNOWN_MODEL_HASHES,
    ProcessSharedRateLimiter,
    get_or_create_api_token,
    secure_file_permissions,
    verify_model_integrity,
)
from services.detection import set_inference_priority


def test_unpinned_model_rejection(tmp_path: Path, monkeypatch):
    """SEC-RES-01: Verify that unpinned/custom PyTorch weights are rejected by default."""
    fake_model = tmp_path / "custom_untrusted.pt"
    fake_model.write_bytes(b"dummy_untrusted_pickle_bytes")

    # By default, unpinned models must be rejected
    monkeypatch.delenv("ALLOW_CUSTOM_UNPINNED_MODELS", raising=False)
    monkeypatch.delenv("CUSTOM_TRUSTED_MODEL_SHA256", raising=False)
    assert verify_model_integrity(fake_model) is False

    # When matching hash is supplied, it is accepted
    import hashlib
    h = hashlib.sha256(b"dummy_untrusted_pickle_bytes").hexdigest()
    monkeypatch.setenv("CUSTOM_TRUSTED_MODEL_SHA256", h)
    assert verify_model_integrity(fake_model) is True


def test_dpapi_token_protection(tmp_path: Path, monkeypatch):
    """SEC-RES-02: Verify that API token is protected at rest."""
    test_token_file = tmp_path / ".test_token"
    monkeypatch.setattr("security_config.TOKEN_FILE", test_token_file)
    monkeypatch.setattr("security_config._api_token_cache", None)
    monkeypatch.delenv("URBAN_FLOW_API_TOKEN", raising=False)

    token = get_or_create_api_token()
    assert len(token) >= 32
    assert test_token_file.is_file()

    content = test_token_file.read_text(encoding="utf-8")
    if sys.platform == "win32":
        assert content.startswith("DPAPI:")

    # Read again with clean cache to verify roundtrip decryption
    monkeypatch.setattr("security_config._api_token_cache", None)
    cached = get_or_create_api_token()
    assert cached == token


def test_process_shared_rate_limiter(tmp_path: Path):
    """SEC-RES-04: Verify SQLite-backed multi-process rate limiting."""
    db_file = tmp_path / "test_rate.sqlite3"
    limiter = ProcessSharedRateLimiter(db_path=db_file)

    client_id = "test_worker_client"
    # Allow 3 requests in a 10s window
    allowed1, _ = limiter.is_allowed(client_id, max_requests=3, window_seconds=10.0)
    allowed2, _ = limiter.is_allowed(client_id, max_requests=3, window_seconds=10.0)
    allowed3, _ = limiter.is_allowed(client_id, max_requests=3, window_seconds=10.0)
    assert allowed1 is True
    assert allowed2 is True
    assert allowed3 is True

    # 4th request must be blocked
    allowed4, retry_after = limiter.is_allowed(client_id, max_requests=3, window_seconds=10.0)
    assert allowed4 is False
    assert retry_after > 0


def test_inference_priority_execution():
    """SEC-RES-03: Verify process priority adjustment executes safely without exceptions."""
    set_inference_priority()
