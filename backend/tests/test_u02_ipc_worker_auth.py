import os
import pytest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import ipc_worker
import security_config


@pytest.fixture(autouse=True)
def setup_ipc_env():
    old_env = os.environ.get("URBAN_FLOW_IPC_TOKEN")
    test_ipc_token = "test_session_secret_0123456789abcdef"
    os.environ["URBAN_FLOW_IPC_TOKEN"] = test_ipc_token
    yield test_ipc_token
    if old_env is None:
        os.environ.pop("URBAN_FLOW_IPC_TOKEN", None)
    else:
        os.environ["URBAN_FLOW_IPC_TOKEN"] = old_env


def test_ipc_worker_missing_token_rejected(setup_ipc_env):
    """Actions requiring auth must be rejected if token is missing."""
    req = {
        "id": "req-missing-token",
        "action": "simulate",
        "data": {"counts": {"North": 5, "South": 5, "East": 5, "West": 5}}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-missing-token"
    assert res["ok"] is False
    assert "Unauthorized" in res["error"]
    assert "token" in res["error"].lower()


def test_ipc_worker_invalid_token_rejected(setup_ipc_env):
    """Actions must be rejected if the provided token does not match."""
    req = {
        "id": "req-bad-token",
        "action": "simulate",
        "token": "completely_bogus_token_hex_99999",
        "data": {"counts": {"North": 5, "South": 5, "East": 5, "West": 5}}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-bad-token"
    assert res["ok"] is False
    assert "Unauthorized" in res["error"]


def test_ipc_worker_valid_session_token_accepted(setup_ipc_env):
    """Actions succeed when the valid session IPC token is provided."""
    session_token = setup_ipc_env
    req = {
        "id": "req-valid-session",
        "action": "simulate",
        "token": session_token,
        "data": {"counts": {"North": 5, "South": 5, "East": 5, "West": 5}}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-valid-session"
    assert res["ok"] is True
    assert "report_id" in res["result"]


def test_ipc_worker_insufficient_scope_rejected(setup_ipc_env):
    """Scoped tokens with insufficient permissions must be rejected."""
    read_token = security_config.generate_scoped_token("read")
    req = {
        "id": "req-read-only-simulate",
        "action": "simulate",
        "token": read_token,
        "data": {"counts": {"North": 5, "South": 5, "East": 5, "West": 5}}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-read-only-simulate"
    assert res["ok"] is False
    assert "Unauthorized" in res["error"]
    assert "scope" in res["error"].lower()


def test_ipc_worker_sufficient_scope_accepted(setup_ipc_env):
    """Scoped tokens with matching action permissions must be accepted."""
    write_token = security_config.generate_scoped_token("reports:write")
    req = {
        "id": "req-write-scope-simulate",
        "action": "simulate",
        "token": write_token,
        "data": {"counts": {"North": 5, "South": 5, "East": 5, "West": 5}}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-write-scope-simulate"
    assert res["ok"] is True
    assert "report_id" in res["result"]


def test_ipc_worker_unauthenticated_action_permitted():
    """Cancellation actions can be dispatched without credentials."""
    req = {
        "id": "req-cancel",
        "action": "cancel",
        "data": {"cancel_id": "test_job_cancel_999"}
    }
    res = ipc_worker.process_ipc_request(req)
    assert res["id"] == "req-cancel"
    assert res["ok"] is True
    assert res["result"].get("cancelled") == "test_job_cancel_999"
