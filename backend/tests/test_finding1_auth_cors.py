import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import security_config
from main import app

client = TestClient(app)
VALID_TOKEN = security_config.get_or_create_api_token()
AUTH_HEADERS = {"X-API-Token": VALID_TOKEN}


def test_cors_no_wildcard():
    """Verify that wildcard CORS is eliminated."""
    origins = security_config.get_allowed_origins()
    assert "*" not in origins
    assert "http://127.0.0.1:5174" in origins

    # Test preflight from legitimate origin
    response = client.options(
        "/api/calculate-signal-plan",
        headers={
            "Origin": "http://127.0.0.1:5174",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5174"


def test_unauthorized_origin_rejected_on_post():
    """Ensure requests from unauthorized origin return HTTP 403."""
    response = client.post(
        "/api/simulate",
        headers={
            "Origin": "https://malicious-site.example.com",
            **AUTH_HEADERS,
        },
        json={
            "junction_name": "Test Junction",
            "counts": {"North": 5, "South": 5, "East": 5, "West": 5},
            "green_budget": 120,
        },
    )
    assert response.status_code == 403
    assert "Forbidden" in response.text or "not authorized" in response.text


def test_unauthenticated_requests_fail():
    """Unauthenticated requests to sensitive endpoints must return 401."""
    # POST /api/simulate
    res1 = client.post(
        "/api/simulate",
        json={"counts": {"North": 5, "South": 5, "East": 5, "West": 5}},
    )
    assert res1.status_code == 401
    assert "Unauthorized" in res1.text

    # POST /api/calculate-signal-plan
    res2 = client.post(
        "/api/calculate-signal-plan",
        json={"counts": {"North": 5, "South": 5, "East": 5, "West": 5}},
    )
    assert res2.status_code == 401

    # GET /api/reports/123
    res3 = client.get("/api/reports/test123")
    assert res3.status_code == 401


def test_invalid_token_rejected():
    """Supplying an incorrect token must return 401."""
    response = client.post(
        "/api/simulate",
        headers={"X-API-Token": "completely_invalid_token_12345"},
        json={"counts": {"North": 5, "South": 5, "East": 5, "West": 5}},
    )
    assert response.status_code == 401


def test_valid_token_accepted():
    """Valid token allows authorized operations."""
    response = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={
            "junction_name": "Auth Test Junction",
            "counts": {"North": 10, "South": 10, "East": 10, "West": 10},
            "green_budget": 120,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "report_id" in data
    assert data["junction_name"] == "Auth Test Junction"


def test_bearer_token_authorization_accepted():
    """Authorization: Bearer <token> is also accepted."""
    response = client.post(
        "/api/simulate",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        json={
            "junction_name": "Bearer Test Junction",
            "counts": {"North": 8, "South": 8, "East": 8, "West": 8},
            "green_budget": 120,
        },
    )
    assert response.status_code == 200
