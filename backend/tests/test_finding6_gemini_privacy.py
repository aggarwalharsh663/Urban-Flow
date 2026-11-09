import io
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import security_config
from main import app

client = TestClient(app)
VALID_TOKEN = security_config.get_or_create_api_token()
AUTH_HEADERS = {"X-API-Token": VALID_TOKEN}


def create_real_png_bytes(width=64, height=64) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(50, 100, 150))
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_privacy_status_in_health():
    """Health check explicitly states privacy_mode: local_default."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("privacy_mode") == "local_default"
    assert data.get("storage") == "local"


def test_local_only_mode_never_calls_gemini_by_default(monkeypatch):
    """Even if GEMINI_API_KEY is set in environment, default upload MUST NOT call Gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_12345")

    fake_local_result = {
        "counts": {"North": 5, "South": 5, "East": 5, "West": 5},
        "total_count": 20,
        "detections": [],
        "annotated_filename": "local-annotated.jpg",
        "analysis_provider": "local-yolo",
    }

    with patch("main.analyse_with_gemini") as mock_gemini, \
         patch("main.analyse_image", return_value=fake_local_result) as mock_local:
        real_png = create_real_png_bytes()
        # Default request without use_cloud_ai
        response = client.post(
            "/api/analyse-image",
            headers=AUTH_HEADERS,
            files={"file": ("junction.png", real_png, "image/png")},
            data={"junction_name": "Local Only Junction"},
        )
        assert response.status_code == 200
        # Crucial check: Gemini MUST NOT be called!
        assert not mock_gemini.called
        assert mock_local.called
        data = response.json()
        assert data.get("analysis_provider") == "local-yolo"


def test_cloud_processing_requires_explicit_consent(monkeypatch):
    """When use_cloud_ai is True, Gemini is called."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_12345")

    fake_gemini_result = {
        "counts": {"North": 4, "South": 2, "East": 3, "West": 1},
        "total_count": 10,
        "detections": [],
        "annotated_filename": "fake-annotated.jpg",
        "analysis_provider": "gemini",
    }

    with patch("main.analyse_with_gemini", return_value=fake_gemini_result) as mock_gemini:
        real_png = create_real_png_bytes()
        response = client.post(
            "/api/analyse-image",
            headers=AUTH_HEADERS,
            files={"file": ("junction.png", real_png, "image/png")},
            data={"junction_name": "Cloud Junction", "use_cloud_ai": "true"},
        )
        assert response.status_code == 200
        assert mock_gemini.called
        data = response.json()
        assert data.get("analysis_provider") == "gemini"


def test_gemini_failure_falls_back_to_local_yolo(monkeypatch):
    """If Gemini request fails, system gracefully falls back to local YOLO."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_12345")

    from services.gemini import GeminiAnalysisError

    fake_local_result = {
        "counts": {"North": 3, "South": 3, "East": 3, "West": 3},
        "total_count": 12,
        "detections": [],
        "annotated_filename": "fallback-annotated.jpg",
        "analysis_provider": "local-yolo",
    }

    with patch("main.analyse_with_gemini", side_effect=GeminiAnalysisError("Network timeout")), \
         patch("main.analyse_image", return_value=fake_local_result):
        real_png = create_real_png_bytes()
        response = client.post(
            "/api/analyse-image",
            headers=AUTH_HEADERS,
            files={"file": ("junction.png", real_png, "image/png")},
            data={"junction_name": "Fallback Junction", "use_cloud_ai": "true"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("analysis_provider") == "local-yolo"
