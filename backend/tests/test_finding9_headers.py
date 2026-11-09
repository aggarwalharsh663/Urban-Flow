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
    """Public endpoints also receive security headers."""
    response = client.get("/api/directions")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
