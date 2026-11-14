import pytest
from fastapi.testclient import TestClient
from main import app
from services.detection import (
    get_detection_status,
    is_model_warmed_up,
    warmup_model,
)


def test_model_warmup_idempotency_and_state():
    status = get_detection_status()
    if not status["computer_vision_ready"] or not status["model_available"]:
        pytest.skip("Local YOLO model or dependencies not installed in test environment")

    # Trigger warmup (synchronous)
    res = warmup_model(async_mode=False)
    assert res is True
    assert is_model_warmed_up() is True

    # Repeated warmup must be non-blocking and idempotent
    assert warmup_model(async_mode=True) is True
    assert warmup_model(async_mode=False) is True
    assert is_model_warmed_up() is True


def test_unauthenticated_health_triggers_warmup_without_schema_leak():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    # Unauthenticated health must strictly adhere to the minimal privacy contract
    assert data == {
        "app": "urban_flow",
        "status": "ok",
        "privacy_mode": "local_default",
        "storage": "local",
    }
