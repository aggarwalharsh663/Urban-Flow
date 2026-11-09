import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import security_config
from services.gemini import _parse_detections
from main import app

client = TestClient(app)
VALID_TOKEN = security_config.get_or_create_api_token()
AUTH_HEADERS = {"X-API-Token": VALID_TOKEN}


def test_boolean_counts_rejected():
    """Booleans passed as counts (e.g. True/False) must be explicitly rejected."""
    # Test True
    res_true = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={"counts": {"North": True, "South": 5, "East": 5, "West": 5}},
    )
    assert res_true.status_code == 422

    # Test False
    res_false = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={"counts": {"North": 5, "South": False, "East": 5, "West": 5}},
    )
    assert res_false.status_code == 422


def test_negative_counts_rejected():
    """Negative counts must be rejected."""
    response = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={"counts": {"North": -1, "South": 5, "East": 5, "West": 5}},
    )
    assert response.status_code == 422


def test_oversized_counts_rejected():
    """Counts above 10,000 must be rejected."""
    response = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={"counts": {"North": 10001, "South": 5, "East": 5, "West": 5}},
    )
    assert response.status_code == 422


def test_excessively_long_junction_name_rejected():
    """Junction names exceeding 100 characters must be rejected."""
    long_name = "A" * 101
    response = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={
            "junction_name": long_name,
            "counts": {"North": 5, "South": 5, "East": 5, "West": 5},
        },
    )
    assert response.status_code == 422


def test_gemini_detections_capped_at_500():
    """Gemini raw detections must be capped at 500 max to prevent DoS."""
    raw_list = [
        {
            "class": "car",
            "box_2d": [100, 100, 200, 200],
            "confidence": 0.9,
        }
        for _ in range(700)
    ]
    mock_resp = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": f'{{"detections": {str(raw_list).replace(chr(39), chr(34))}}}'}]
                }
            }
        ]
    }
    parsed = _parse_detections(mock_resp, 1000, 1000)
    assert len(parsed) <= security_config.MAX_GEMINI_DETECTIONS
    assert len(parsed) == 500
