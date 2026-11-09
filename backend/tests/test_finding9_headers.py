import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from main import app

client = TestClient(app)


def test_security_headers_present_on_api_responses():
    """Verify standard security headers on API responses."""
    response = client.get("/api/health")
    assert response.status_code == 200
    headers = response.headers

    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert "strict-origin-when-cross-origin" in headers.get("referrer-policy", "")
    assert "content-security-policy" in headers
    csp = headers.get("content-security-policy")
    assert "default-src 'self'" in csp


def test_directions_public_has_security_headers():
    """Endpoints receive security headers, and directions requires authentication (R3)."""
    # Unauthenticated access must be rejected (R3)
    unauth = client.get("/api/directions")
    assert unauth.status_code == 401
    assert unauth.headers.get("x-content-type-options") == "nosniff"

    # Authenticated access succeeds and receives security headers
    import security_config
    valid_token = security_config.get_or_create_api_token()
    response = client.get("/api/directions", headers={"X-API-Token": valid_token})
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
