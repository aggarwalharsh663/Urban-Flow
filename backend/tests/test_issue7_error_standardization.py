# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import ipc_worker
import security_config
from main import app

client = TestClient(app)
VALID_TOKEN = security_config.get_or_create_api_token()
AUTH_HEADERS = {"X-API-Token": VALID_TOKEN}


def test_fastapi_canonical_error_schema_401():
    """Unauthenticated requests must return the canonical {ok: False, error, detail} format with HTTP 401."""
    res = client.get("/api/directions")
    assert res.status_code == 401
    body = res.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str)
    assert isinstance(body["detail"], str)
    assert len(body["error"]) > 0


def test_fastapi_canonical_error_schema_404():
    """Non-existent report IDs must return canonical format with HTTP 404."""
    res = client.get("/api/reports/nonexistent999", headers=AUTH_HEADERS)
    assert res.status_code == 404
    body = res.json()
    assert body["ok"] is False
    assert "not found" in body["error"].lower()
    assert body["error"] == body["detail"]


def test_fastapi_canonical_error_schema_422():
    """Validation errors must return canonical format with HTTP 422 and human-readable string without [object Object]."""
    res = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={"counts": {"North": "not_an_int", "South": 5, "East": 5, "West": 5}},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str)
    assert "[object Object]" not in body["error"]
    assert len(body["error"]) > 0


def test_ipc_worker_canonical_error_schema_unknown_action():
    """Unknown action in IPC worker returns canonical schema."""
    req = {
        "id": "req-unknown-act",
        "action": "nonexistent_action_xyz",
        "token": VALID_TOKEN,
        "data": {}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-unknown-act"
    assert res["ok"] is False
    assert "error" in res
    assert "detail" in res
    assert "Unknown action" in res["error"]
    assert res["error"] == res["detail"]


def test_ipc_worker_canonical_error_schema_auth_failure():
    """Missing or invalid token in IPC worker returns canonical error with error and detail."""
    req = {
        "id": "req-bad-auth",
        "action": "simulate",
        "token": "invalid_bogus_token",
        "data": {"counts": {"North": 5, "South": 5, "East": 5, "West": 5}}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-bad-auth"
    assert res["ok"] is False
    assert "Unauthorized" in res["error"]
    assert res["detail"] == res["error"]


def test_ipc_worker_canonical_error_schema_exception():
    """Handling an invalid simulation payload raises ValueError formatted into canonical error."""
    req = {
        "id": "req-invalid-counts",
        "action": "simulate",
        "token": VALID_TOKEN,
        "data": {"counts": {"North": -50, "South": 5, "East": 5, "West": 5}}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-invalid-counts"
    assert res["ok"] is False
    assert "error" in res
    assert "detail" in res
    assert "must be a non-negative integer" in res["error"]
