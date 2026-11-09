import json
import pytest

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import ipc_worker
import security_config


def test_ipc_health_no_absolute_paths():
    """IPC worker health must not expose absolute filesystem paths or usernames."""
    res = ipc_worker.handle_health({})
    assert res["status"] == "ok"
    assert "model_path" not in res
    if res.get("model_name"):
        assert not res["model_name"].startswith("C:")
        assert "\\" not in res["model_name"]


def test_ipc_simulate_rejects_boolean_and_oversized_counts():
    """IPC worker must reject boolean counts, negative counts, and counts > 10,000."""
    # Boolean
    with pytest.raises(ValueError, match="cannot be a boolean"):
        ipc_worker.handle_simulate({"counts": {"North": True, "South": 1, "East": 1, "West": 1}})

    # Negative
    with pytest.raises(ValueError, match="must be a non-negative integer"):
        ipc_worker.handle_simulate({"counts": {"North": -5, "South": 1, "East": 1, "West": 1}})

    # Oversized (>10,000)
    with pytest.raises(ValueError, match="exceeds maximum limit"):
        ipc_worker.handle_simulate({"counts": {"North": 15000, "South": 1, "East": 1, "West": 1}})


def test_ipc_atomic_report_workflow():
    """Verify atomic persistence and version increment in IPC worker."""
    sim_data = {
        "junction_name": "IPC Test Junction",
        "counts": {"North": 10, "South": 15, "East": 20, "West": 25},
        "green_budget": 120,
    }
    report = ipc_worker.handle_simulate(sim_data)
    assert report["report_id"]
    report_id = report["report_id"]
    assert report.get("version") == 1

    # Read back report
    fetched = ipc_worker.handle_get_report({"report_id": report_id})
    assert fetched["junction_name"] == "IPC Test Junction"
    assert fetched["counts"]["North"] == 10

    # Update cycle
    updated_cycle = ipc_worker.handle_update_cycle({"report_id": report_id, "green_budget": 140})
    assert updated_cycle["version"] == 2
    assert len(updated_cycle["history"]) >= 1

    # Update counts
    updated_counts = ipc_worker.handle_update_counts({
        "report_id": report_id,
        "counts": {"North": 30, "South": 15, "East": 20, "West": 25},
    })
    assert updated_counts["version"] == 3
    assert updated_counts["counts"]["North"] == 30
    assert len(updated_counts["history"]) >= 2


def test_ipc_analyse_rejects_oversized_file(tmp_path):
    """IPC worker must reject files exceeding 100 MB."""
    fake_large_file = tmp_path / "large.jpg"
    # Write sparse or simulated file
    with fake_large_file.open("wb") as f:
        f.seek(101 * 1024 * 1024)
        f.write(b"\x00")

    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        ipc_worker.handle_analyse({"file_path": str(fake_large_file)}, video=False)
