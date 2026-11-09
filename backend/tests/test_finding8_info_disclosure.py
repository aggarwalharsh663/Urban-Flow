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


def test_health_endpoint_no_absolute_paths_or_usernames():
    """Verify /api/health reveals no absolute filesystem paths or Windows usernames."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()

    # Must not contain "model_path" with full drive path
    assert "model_path" not in data
    # Only model_name (e.g. yolov8m.pt or None)
    if data.get("model_name"):
        assert not data["model_name"].startswith("C:")
        assert "\\" not in data["model_name"]
        assert "/" not in data["model_name"]

    raw_text = response.text
    assert "C:\\" not in raw_text
    assert "Users\\" not in raw_text
    assert "AppData" not in raw_text


def test_error_responses_contain_no_internal_paths():
    """Client error messages must not leak filesystem paths."""
    # Invalid report ID
    res = client.get("/api/reports/../../etc/passwd", headers=AUTH_HEADERS)
    assert res.status_code in {400, 404}
    assert "C:\\" not in res.text
    assert "backend\\" not in res.text

    # Upload non-existent or invalid
    res_upload = client.post(
        "/api/analyse-image",
        headers=AUTH_HEADERS,
        files={"file": ("test.png", b"\x00" * 20, "image/png")},
    )
    assert res_upload.status_code == 400
    assert "C:\\" not in res_upload.text
