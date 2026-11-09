import concurrent.futures
import json
import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import security_config
from main import app, REPORT_DIR

client = TestClient(app)
VALID_TOKEN = security_config.get_or_create_api_token()
AUTH_HEADERS = {"X-API-Token": VALID_TOKEN}


@pytest.fixture
def sample_report():
    """Create a legitimate report for testing."""
    response = client.post(
        "/api/simulate",
        headers=AUTH_HEADERS,
        json={
            "junction_name": "Audit Junction",
            "counts": {"North": 12, "South": 8, "East": 14, "West": 6},
            "green_budget": 120,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_unauthenticated_report_read_and_write(sample_report):
    report_id = sample_report["report_id"]

    # Read unauthenticated -> 401
    r_get = client.get(f"/api/reports/{report_id}")
    assert r_get.status_code == 401

    # Update cycle unauthenticated -> 401
    r_cycle = client.put(f"/api/reports/{report_id}/cycle", json={"green_budget": 150})
    assert r_cycle.status_code == 401

    # Update counts unauthenticated -> 401
    r_counts = client.put(
        f"/api/reports/{report_id}/counts",
        json={"counts": {"North": 20, "South": 10, "East": 15, "West": 5}},
    )
    assert r_counts.status_code == 401


def test_authorized_report_modifications_with_version_history(sample_report):
    report_id = sample_report["report_id"]

    # Initial report should be version 1
    r_initial = client.get(f"/api/reports/{report_id}", headers=AUTH_HEADERS)
    assert r_initial.status_code == 200
    data_initial = r_initial.json()
    assert data_initial.get("version", 1) == 1

    # Modify cycle
    r_cycle = client.put(
        f"/api/reports/{report_id}/cycle",
        headers=AUTH_HEADERS,
        json={"green_budget": 150},
    )
    assert r_cycle.status_code == 200
    data_cycle = r_cycle.json()
    assert data_cycle["version"] == 2
    assert len(data_cycle["history"]) >= 1
    assert data_cycle["history"][-1]["version"] == 1

    # Modify counts
    r_counts = client.put(
        f"/api/reports/{report_id}/counts",
        headers=AUTH_HEADERS,
        json={"counts": {"North": 30, "South": 10, "East": 10, "West": 10}},
    )
    assert r_counts.status_code == 200
    data_counts = r_counts.json()
    assert data_counts["version"] == 3
    assert len(data_counts["history"]) >= 2
    assert data_counts["counts"]["North"] == 30


def test_concurrent_report_updates_no_corruption(sample_report):
    """Ensure concurrent updates do not produce malformed JSON or lost state."""
    report_id = sample_report["report_id"]

    def update_budget(val):
        return client.put(
            f"/api/reports/{report_id}/cycle",
            headers=AUTH_HEADERS,
            json={"green_budget": val},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(update_budget, 100 + i * 10) for i in range(10)]
        results = [f.result() for f in futures]

    for res in results:
        assert res.status_code == 200

    # Final report must be valid JSON on disk
    file_path = REPORT_DIR / f"{report_id}.json"
    assert file_path.is_file()
    final_data = json.loads(file_path.read_text(encoding="utf-8"))
    assert final_data["version"] >= 10
    assert len(final_data["history"]) >= 9
